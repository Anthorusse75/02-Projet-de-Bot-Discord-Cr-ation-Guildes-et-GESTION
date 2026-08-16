from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import discord
from redis.asyncio import Redis
from sqlalchemy import text

from did.application.reconciliation import DiscordSyncService
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.discord import DiscordPyStructureAdapter
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import (
    OutboxPublisher,
    RedisHotCache,
    RedisSingleFlight,
    TenantPubSub,
)
from did.infrastructure.runtime_repository import RuntimeRepository

REQUIRED_VARIABLES = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_TEST_GUILD_A_ID",
    "DISCORD_TEST_GUILD_B_ID",
)
TEST_DATABASE_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
TEST_ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
TEST_REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in REQUIRED_VARIABLES and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


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
                "stage": "03",
                "profile": "discord-live-sandbox-read-only",
                "status": status,
                "generated_at": datetime.now(UTC).isoformat(),
                "checks": checks,
                "missing_variable_names": missing,
                "resource_counts": counts or {},
                "skipped_not_verified": skipped,
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
        values = tuple(int(os.environ[name]) for name in REQUIRED_VARIABLES[1:])
    except ValueError as exc:
        raise RuntimeError("Discord test Guild IDs must be positive snowflakes") from exc
    if any(value <= 0 for value in values) or values[0] == values[1]:
        raise RuntimeError("Discord test Guild IDs must be distinct positive snowflakes")
    return values


async def seed_installations(guilds: tuple[int, int]) -> None:
    engine = create_database_engine(TEST_ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            for index, guild_id in enumerate(guilds, start=1):
                await connection.execute(
                    text(
                        "INSERT INTO guild_installations "
                        "(guild_id, name, installation_status) VALUES "
                        "(:guild_id, :name, 'ACTIVE') ON CONFLICT (guild_id) DO NOTHING"
                    ),
                    {"guild_id": guild_id, "name": f"STAGE03 live Guild {index}"},
                )
    finally:
        await engine.dispose()


async def run_live() -> dict[str, int]:
    guilds = guild_ids()
    await seed_installations(guilds)
    engine = create_database_engine(TEST_DATABASE_URL, pool_size=3)
    redis: Redis = create_redis_client(TEST_REDIS_URL)
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(os.environ["DISCORD_BOT_TOKEN"])
        adapter = DiscordPyStructureAdapter(client)
        repository = RuntimeRepository(create_session_factory(engine))
        hot = RedisHotCache(redis)
        sync = DiscordSyncService(
            adapter=adapter,
            repository=repository,
            singleflight=RedisSingleFlight(redis),
        )
        counts: dict[str, int] = {}
        for index, guild_id in enumerate(guilds, start=1):
            result = await sync.initial_sync(guild_id)
            await OutboxPublisher(
                repository,
                TenantPubSub(redis),
                hot_cache=hot,
            ).publish_guild(guild_id)
            await hot.rebuild_channels(repository, guild_id)
            counts[f"guild_{index}_channels"] = result["channels"]
            counts[f"guild_{index}_roles"] = result["roles"]
            durable = await repository.channels(guild_id, None, include_hidden_deleted=True)
            rebuilt = await hot.get_channels(guild_id)
            if (
                rebuilt is None
                or len(durable) != result["channels"]
                or len(rebuilt) != len(durable)
            ):
                raise RuntimeError("live cache persistence or Redis rebuild count mismatch")
        if hot.channels_key(guilds[0]) == hot.channels_key(guilds[1]):
            raise RuntimeError("live Redis tenant namespaces collided")
        return counts
    finally:
        await client.close()
        await redis.aclose()
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 03 safe Discord live validation")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()
    skipped = [
        "external Discord mutation observed through Gateway",
        "forced Gateway reconnect/RESUME/non-resumed",
        "Channel Obfuscation live visibility change: CONTRACT_ONLY_NOT_LIVE_VERIFIED",
        "inherited STAGE 02 administrator non-owner profile",
        "inherited STAGE 02 non-administrator profile",
    ]
    if not arguments.include:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=[],
            skipped=skipped,
        )
        print("Discord live STAGE 03: SKIPPED_NOT_VERIFIED (explicit opt-in required)")
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
        print("Discord live STAGE 03: missing variable names: " + ", ".join(missing))
        return 2
    try:
        counts = asyncio.run(run_live())
    except Exception as exc:
        write_report(
            arguments.report,
            status="FAIL",
            checks=[],
            missing=[],
            skipped=skipped,
        )
        print(f"Discord live STAGE 03: FAIL ({type(exc).__name__}); secrets were not recorded")
        return 1
    write_report(
        arguments.report,
        status="PASS_WITH_APPROVED_LIMITATION",
        checks=[
            "bot-token identity login through discord.py",
            "Guild A/B Get Guild Channels and Get Guild Roles through governed initial sync",
            "categories/channels/roles/overwrites normalized and persisted in PostgreSQL test DB",
            "Redis hot projections rebuilt from PostgreSQL for Guild A/B",
            "tenant Redis namespaces distinct; Discord mutations remained zero",
        ],
        missing=[],
        skipped=skipped,
        counts=counts,
    )
    print("Discord live STAGE 03: PASS_WITH_APPROVED_LIMITATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
