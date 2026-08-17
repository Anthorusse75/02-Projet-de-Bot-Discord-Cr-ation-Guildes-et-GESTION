from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import discord
from redis.asyncio import Redis

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import RedisDiscordWorkloadCoordinator
from did.permissions import DEFAULT_PERMISSION_REGISTRY, PermissionEvaluator

REQUIRED_VARIABLES = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_TEST_GUILD_A_ID",
    "DISCORD_TEST_GUILD_B_ID",
)
REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")


def oracle_comparison_mask(channel_type: ChannelType | int) -> int:
    common = ("VIEW_CHANNEL", "MANAGE_CHANNELS", "MANAGE_ROLES")
    if channel_type in {
        ChannelType.GUILD_TEXT,
        ChannelType.GUILD_ANNOUNCEMENT,
        ChannelType.GUILD_FORUM,
        ChannelType.GUILD_MEDIA,
    }:
        names = (
            *common,
            "SEND_MESSAGES",
            "SEND_TTS_MESSAGES",
            "MANAGE_MESSAGES",
            "EMBED_LINKS",
            "ATTACH_FILES",
            "READ_MESSAGE_HISTORY",
            "MENTION_EVERYONE",
            "MANAGE_THREADS",
            "CREATE_PUBLIC_THREADS",
            "CREATE_PRIVATE_THREADS",
            "SEND_MESSAGES_IN_THREADS",
        )
    elif channel_type is ChannelType.GUILD_VOICE:
        names = (
            *common,
            "CONNECT",
            "SPEAK",
            "STREAM",
            "MUTE_MEMBERS",
            "DEAFEN_MEMBERS",
            "MOVE_MEMBERS",
            "USE_VAD",
        )
    elif channel_type is ChannelType.GUILD_STAGE_VOICE:
        names = (
            *common,
            "CONNECT",
            "STREAM",
            "MUTE_MEMBERS",
            "MOVE_MEMBERS",
            "REQUEST_TO_SPEAK",
        )
    else:
        return 0
    return sum(DEFAULT_PERMISSION_REGISTRY.value(name) for name in names)


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() in REQUIRED_VARIABLES and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip('"').strip("'")


def write_report(
    path: Path,
    *,
    status: str,
    checks: list[str],
    missing: list[str],
    skipped: list[str],
    counts: dict[str, int] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "stage": "04",
                "profile": "discord-live-sandbox-read-only",
                "status": status,
                "generated_at": datetime.now(UTC).isoformat(),
                "checks": checks,
                "missing_variable_names": missing,
                "resource_counts": counts or {},
                "skipped_not_verified": skipped,
                "oracle": "Discord API observations with discord.py as secondary calculator",
                "discord_mutations": 0,
                "secrets_recorded": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def guild_ids() -> tuple[int, int]:
    try:
        result = tuple(int(os.environ[name]) for name in REQUIRED_VARIABLES[1:])
    except ValueError as exc:
        raise RuntimeError("Discord test Guild IDs must be positive snowflakes") from exc
    if len(result) != 2 or min(result) <= 0 or result[0] == result[1]:
        raise RuntimeError("Discord test Guild IDs must be distinct positive snowflakes")
    return result[0], result[1]


def _snapshot(
    guild: discord.Guild,
    roles: list[discord.Role],
    channels: list[discord.abc.GuildChannel],
    bot: discord.Member,
) -> tuple[GuildSnapshot, MemberSnapshot]:
    now = datetime.now(UTC)
    current = FreshnessSnapshot(FreshnessState.FRESH, "DISCORD_LIVE_REST", 1, now, now, now)
    role_snapshots = tuple(
        RoleSnapshot(
            guild.id,
            role.id,
            role.name,
            role.position,
            role.permissions.value,
            role.managed,
            current,
        )
        for role in roles
    )
    channel_snapshots: list[ChannelSnapshot] = []
    for item in channels:
        overwrites: list[OverwriteSnapshot] = []
        for target, overwrite in item.overwrites.items():
            allow, deny = overwrite.pair()
            overwrites.append(
                OverwriteSnapshot(
                    guild.id,
                    item.id,
                    target.id,
                    0 if isinstance(target, discord.Role) else 1,
                    allow.value,
                    deny.value,
                    now,
                )
            )
        raw_type = int(item.type.value)
        try:
            channel_type: ChannelType | int = ChannelType(raw_type)
        except ValueError:
            channel_type = raw_type
        channel_snapshots.append(
            ChannelSnapshot(
                guild.id,
                item.id,
                channel_type,
                item.position,
                item.category_id,
                item.name,
                tuple(overwrites),
                True,
                ObservabilityState.VISIBLE,
                current,
            )
        )
    coverage = CoverageSnapshot(
        guild.id,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "DISCORD_LIVE_REST",
        1,
        len(channels),
        len(channels),
        0,
        len(roles),
        True,
        True,
        False,
        "CONNECTED",
    )
    return (
        GuildSnapshot(
            guild.id,
            guild.owner_id,
            role_snapshots,
            tuple(channel_snapshots),
            coverage,
            current,
            source_versions=("discord-live-rest",),
        ),
        MemberSnapshot(
            guild.id,
            bot.id,
            tuple(role.id for role in bot.roles if not role.is_default()),
            True,
            current,
            is_bot=True,
        ),
    )


async def run_live() -> dict[str, int]:
    client = discord.Client(intents=discord.Intents.none())
    redis: Redis = create_redis_client(REDIS_URL)
    governor = RedisDiscordWorkloadCoordinator(redis, global_concurrency=4, per_guild_concurrency=1)
    evaluator = PermissionEvaluator()
    counts: dict[str, int] = {}
    try:
        await client.login(os.environ["DISCORD_BOT_TOKEN"])
        if client.user is None:
            raise RuntimeError("Discord bot identity is unavailable")
        for index, guild_id in enumerate(guild_ids(), start=1):
            permit = await governor.acquire(guild_id)
            try:
                live_guild = await client.fetch_guild(guild_id)
                roles = await live_guild.fetch_roles()
                channels = await live_guild.fetch_channels()
                bot = await live_guild.fetch_member(client.user.id)
            finally:
                await governor.release(permit)
            snapshot, subject = _snapshot(live_guild, roles, channels, bot)
            mismatches = 0
            compared = 0
            first_mismatch: str | None = None
            for live_channel, resource in zip(channels, snapshot.channels, strict=True):
                if resource.channel_type in {
                    ChannelType.GUILD_CATEGORY,
                    ChannelType.GUILD_DIRECTORY,
                }:
                    continue
                compared += 1
                decision = evaluator.evaluate(guild=snapshot, member=subject, resource=resource)
                oracle = live_channel.permissions_for(bot).value
                comparison_mask = oracle_comparison_mask(resource.channel_type)
                if decision.effective_bits & comparison_mask != oracle & comparison_mask:
                    mismatches += 1
                    if first_mismatch is None:
                        missing = DEFAULT_PERMISSION_REGISTRY.names(
                            oracle & ~decision.effective_bits & comparison_mask
                        )
                        extra = DEFAULT_PERMISSION_REGISTRY.names(
                            decision.effective_bits & ~oracle & comparison_mask
                        )
                        first_mismatch = (
                            f"type={int(resource.channel_type)};"
                            f"missing={','.join(missing) or 'none'};"
                            f"extra={','.join(extra) or 'none'}"
                        )
            if mismatches:
                raise RuntimeError(
                    f"permission evaluator differs from secondary live oracle: {first_mismatch}"
                )
            counts[f"guild_{index}_channels_compared"] = compared
            counts[f"guild_{index}_roles_observed"] = len(roles)
            counts[f"guild_{index}_permission_mismatches"] = mismatches
        return counts
    finally:
        await client.close()
        await redis.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 04 read-only Discord live oracle")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()
    skipped = [
        "active/public/private thread membership matrix requires controlled fixtures",
        "category synced/desynced mutation fixtures are not created by this read-only runner",
        "managed/equal role hierarchy mutation fixtures are not created by this read-only runner",
        "inherited STAGE 02 administrator non-owner human profile",
        "inherited STAGE 02 non-administrator human profile",
    ]
    if not arguments.include:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=[],
            skipped=skipped,
        )
        print("Discord live STAGE 04: SKIPPED_NOT_VERIFIED (explicit opt-in required)")
        return 0
    load_local_environment(Path(".env.local"))
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=missing,
            skipped=skipped,
        )
        print("Discord live STAGE 04: missing variable names: " + ", ".join(missing))
        return 2
    try:
        counts = asyncio.run(run_live())
    except Exception as exc:
        safe_failures = {
            "Discord test Guild IDs must be positive snowflakes": "INVALID_GUILD_IDS",
            "Discord test Guild IDs must be distinct positive snowflakes": "INVALID_GUILD_IDS",
            "Discord bot identity is unavailable": "BOT_IDENTITY_UNAVAILABLE",
            "Discord token is halted system-wide": "GOVERNOR_TOKEN_HALTED",
            "permission evaluator differs from secondary live oracle": "ORACLE_MISMATCH",
        }
        failure_code = safe_failures.get(str(exc), type(exc).__name__)
        mismatch_prefix = "permission evaluator differs from secondary live oracle: "
        if str(exc).startswith(mismatch_prefix):
            failure_code = "ORACLE_MISMATCH:" + str(exc).removeprefix(mismatch_prefix)
        write_report(
            arguments.report,
            status="FAIL",
            checks=[],
            missing=[],
            skipped=skipped,
        )
        print(f"Discord live STAGE 04: FAIL ({failure_code}); no secret recorded")
        return 1
    write_report(
        arguments.report,
        status="PASS_WITH_APPROVED_LIMITATION",
        checks=[
            "Guild A/B roles, channels and bot member observed read-only",
            "effective bot channel permissions matched discord.py secondary oracle",
            "Snowflakes and permission bitfields retained as arbitrary-precision integers",
            "Discord mutations remained zero",
        ],
        missing=[],
        skipped=skipped,
        counts=counts,
    )
    print("Discord live STAGE 04: PASS_WITH_APPROVED_LIMITATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
