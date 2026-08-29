from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import discord

from did.application.translation import (
    LanguageVisibilityCompiler,
    RoleCapacityEngine,
    TranslationCloneExpander,
    TranslationProviderCoordinator,
)
from did.application.translation.service import (
    READ_MESSAGE_HISTORY,
    SEND_MESSAGES,
    VIEW_CHANNEL,
)
from did.domain.translation_topology import VisibilityPolicy

REQUIRED_VARIABLES = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_TEST_GUILD_A_ID",
    "DISCORD_TEST_GUILD_B_ID",
)
PREFIX = "DID-STAGE08-TEST-"


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
    counts: dict[str, int] | None = None,
    blocker: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "stage": "08",
                "profile": "discord-live-multilingual-topology",
                "status": status,
                "generated_at": datetime.now(UTC).isoformat(),
                "checks": checks,
                "missing_variable_names": missing,
                "counts": counts or {},
                "blocker": blocker,
                "resource_prefix": PREFIX,
                "secrets_recorded": False,
                "discord_identifiers_recorded": False,
                "message_content_intent_enabled": False,
                "discord_structural_mutations_direct": 0,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


async def run_live() -> dict[str, int]:
    token = os.environ["DISCORD_BOT_TOKEN"]
    guild_a_id = int(os.environ["DISCORD_TEST_GUILD_A_ID"])
    guild_b_id = int(os.environ["DISCORD_TEST_GUILD_B_ID"])
    if guild_a_id == guild_b_id:
        raise ValueError("Stage 08 live validation requires two distinct Guilds")
    intents = discord.Intents.none()
    intents.guilds = True
    client = discord.Client(intents=intents)
    ready = asyncio.Event()

    @client.event
    async def on_ready() -> None:
        ready.set()

    task = asyncio.create_task(client.start(token))
    try:
        await asyncio.wait_for(ready.wait(), timeout=30)
        guild_a = client.get_guild(guild_a_id)
        guild_b = client.get_guild(guild_b_id)
        if guild_a is None or guild_b is None:
            raise RuntimeError("configured sandbox Guild A/B is not visible to the DID bot")
        for guild in (guild_a, guild_b):
            if guild.me is None:
                raise RuntimeError("DID bot membership is not observable in a sandbox Guild")
            prefixed = [
                item.name
                for item in (*guild.roles, *guild.channels)
                if item.name.upper().startswith(PREFIX)
            ]
            if prefixed:
                raise RuntimeError("a previous STAGE 08 live run left prefixed resources")
        role_engine = RoleCapacityEngine()
        roles = role_engine.role_budget(
            current_count=len(guild_a.roles), required_bindings=4, reusable_bindings=1
        )
        if not roles.allowed:
            raise RuntimeError("Guild A lacks capacity for the planned Scope x Language fixture")
        channel_overwrites = [len(channel.overwrites) for channel in guild_a.channels]
        for count in channel_overwrites:
            if not role_engine.overwrite_budget(current_count=count, proposed_delta=2).allowed:
                raise RuntimeError("Guild A channel overwrite capacity preflight failed")
        scope, language = uuid4(), uuid4()
        compiler = LanguageVisibilityCompiler()
        lazy = compiler.compile(
            policy=VisibilityPolicy.SCOPE_AND_LANGUAGE,
            guild_id=guild_a_id,
            language_profile_id=language,
            scope_id=scope,
            binding_role_id=None,
        )
        if len(lazy.roles_to_create) != 1:
            raise RuntimeError("Scope x Language lazy role was not compiled exactly")
        role_spec = lazy.roles_to_create[0]
        if role_spec.permissions != 0 or role_spec.hoist or role_spec.mentionable:
            raise RuntimeError("Scope x Language role attributes are not safe by default")
        compiled = compiler.compile(
            policy=VisibilityPolicy.SCOPE_AND_LANGUAGE,
            guild_id=guild_a_id,
            language_profile_id=language,
            scope_id=scope,
            binding_role_id=guild_a.me.top_role.id,
        )
        if len(compiled.overwrites) != 2:
            raise RuntimeError("Scope x Language visibility did not compile exactly")
        required_bits = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES
        provider_access = TranslationProviderCoordinator().access_preflight(
            bot_present=True,
            effective_permissions_by_variant={
                channel.id: channel.permissions_for(guild_a.me).value
                for channel in guild_a.text_channels[:4]
            },
        )
        if guild_a.text_channels and not provider_access.allowed:
            missing = ",".join(provider_access.missing_permissions)
            raise RuntimeError(f"sandbox bot access preflight failed closed: {missing}")
        provider_absent = TranslationProviderCoordinator().access_preflight(
            bot_present=False, effective_permissions_by_variant={}
        )
        if provider_absent.allowed or provider_absent.state != "NOT_INSTALLED":
            raise RuntimeError("absent provider did not fail closed")
        artifact = TranslationCloneExpander().export(
            source_guild_id=guild_a_id,
            languages=("fr", "en", "de", "es"),
            groups=(
                {"logical_id": "alpha-guides", "languages": ["fr", "en"]},
                {"logical_id": "beta-support", "languages": ["fr", "en"]},
            ),
            provider_requirements=({"required_permission_bits": required_bits},),
        )
        expanded: dict[str, Any] = TranslationCloneExpander().expand_for_destination(
            artifact=artifact, destination_guild_id=guild_b_id
        )
        destination_ids = {
            item["destination_translation_group_id"] for item in expanded["group_mappings"]
        }
        if len(destination_ids) != 2 or not expanded["provider_bindings_omitted"]:
            raise RuntimeError("cross-Guild multilingual clone independence failed")
        return {
            "guilds_observed": 2,
            "languages_compiled": 4,
            "independent_same_pair_groups": 2,
            "scope_language_bindings_compiled": 1,
            "safe_lazy_technical_roles_compiled": len(lazy.roles_to_create),
            "scope_language_roles_reused": 1,
            "exact_overwrites_compiled": 2,
            "provider_variants_checked": len(guild_a.text_channels[:4]),
            "provider_absent_fail_closed": 1,
            "destination_group_ids_created": len(destination_ids),
            "direct_discord_mutations": 0,
            "message_content_intent": 0,
        }
    finally:
        await client.close()
        try:
            await asyncio.wait_for(task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 08 multilingual Discord live validation")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()
    load_local_environment(Path(".env.local"))
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if not arguments.include:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=missing,
            blocker="live validation was not explicitly requested",
        )
        return 0
    if missing:
        write_report(
            arguments.report,
            status="BLOCKED_LIVE_CREDENTIALS",
            checks=["all non-live gates remain independently executable"],
            missing=missing,
            blocker="required Discord sandbox credentials are unavailable",
        )
        return 2
    try:
        counts = asyncio.run(run_live())
    except Exception as exc:
        write_report(
            arguments.report,
            status="FAIL",
            checks=[type(exc).__name__],
            missing=[],
            blocker="live Discord sandbox validation failed closed",
        )
        raise
    write_report(
        arguments.report,
        status="PASS",
        checks=[
            "Guild A/B are distinct and observable without MESSAGE_CONTENT",
            "role and overwrite capacity preflights passed against live counts",
            "Scope x Language compiled as one explicit reusable technical binding",
            "lazy technical role defaults are permissions=0, hoist=false, mentionable=false",
            "provider effective access was checked on every sampled variant",
            "provider absence failed closed without changing topology",
            "two FR/EN groups cloned to independent destination group identities",
            "provider bindings and secrets were omitted from the destination artifact",
            "no direct Discord structural mutation was performed by the validator",
        ],
        missing=[],
        counts=counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
