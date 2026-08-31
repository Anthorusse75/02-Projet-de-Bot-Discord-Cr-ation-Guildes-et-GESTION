"""Stage 09 Discord sandbox live qualification (targeted, honest scope).

Exercises the REAL did.infrastructure.discord_message_sender adapter
(DiscordPyMessageSender) against a real sandbox Guild: immediate send with
allowed_mentions=none, an owned edit, an owned delete, and the
nonce/enforce_nonce dedup-vs-distinct behavior. This is deliberately NOT the
full Stage09 live acceptance matrix from the specification (no scheduled
delivery, no crash/retry, no four-language Translation Group publication, no
external-provider-present/absent scenario) -- those require the end-to-end
campaign orchestration service that does not exist yet (see
docs/90_handoffs/STAGE_09_HANDOFF.md). This script proves the message
send/edit/delete/nonce primitives that DO exist work against the real
Discord API, honestly scoped, not a substitute for the full matrix.

Skipped unless --include is passed (mirrors every other Stage stage's live
validator). Creates one temporary channel, uses synthetic content only,
cleans up fully, and writes a sanitized JSON report with zero secrets, zero
Discord ids, zero PII.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

REQUIRED_VARIABLES = ("DISCORD_BOT_TOKEN", "DISCORD_TEST_GUILD_A_ID")


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def _run_live(guild_id: int, token: str) -> dict[str, Any]:
    import discord

    from did.campaigns.delivery_reconciliation import generate_delivery_nonce
    from did.infrastructure.discord_message_sender import DiscordPyMessageSender
    from did.messaging.allowed_mentions import NO_MENTIONS
    from did.messaging.edit_payload import AttachmentPolicy, EditPayload
    from did.messaging.message_model import MessageModel

    scenarios: dict[str, Any] = {}
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        try:
            guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
            channel = await guild.create_text_channel("did-stage09-live-qualification-tmp")
            sender = DiscordPyMessageSender(client)
            try:
                # --- Scenario 1: immediate send, allowed_mentions=none ---
                model = MessageModel(
                    content="DID Stage09 live qualification (synthetic, will be deleted)."
                )
                nonce_a = generate_delivery_nonce()
                sent = await sender.send(
                    channel_id=channel.id,
                    message=model,
                    allowed_mentions=NO_MENTIONS,
                    nonce=nonce_a,
                )
                fetched = await channel.fetch_message(sent.discord_message_id)
                scenarios["immediate_send_allowed_mentions_none"] = fetched.content == model.content

                # --- Scenario 2: owned edit, explicit attachment policy ---
                edited_model = MessageModel(content="Edited by Stage09 live qualification.")
                await sender.edit(
                    channel_id=channel.id,
                    message_id=sent.discord_message_id,
                    payload=EditPayload(
                        message_model=edited_model,
                        allowed_mentions=NO_MENTIONS,
                        attachment_policy=AttachmentPolicy.PRESERVE_EXISTING,
                    ),
                )
                refetched = await channel.fetch_message(sent.discord_message_id)
                scenarios["owned_edit_applies_new_content"] = (
                    refetched.content == edited_model.content
                )

                # --- Scenario 3: owned delete ---
                await sender.delete(channel_id=channel.id, message_id=sent.discord_message_id)
                deleted_ok = False
                try:
                    await channel.fetch_message(sent.discord_message_id)
                except discord.NotFound:
                    deleted_ok = True
                scenarios["owned_delete_removes_message"] = deleted_ok

                # --- Scenario 4: nonce dedup vs. distinct ---
                nonce_dedup = generate_delivery_nonce()
                first = await sender.send(
                    channel_id=channel.id,
                    message=model,
                    allowed_mentions=NO_MENTIONS,
                    nonce=nonce_dedup,
                )
                second = await sender.send(
                    channel_id=channel.id,
                    message=model,
                    allowed_mentions=NO_MENTIONS,
                    nonce=nonce_dedup,
                )
                scenarios["same_nonce_dedups_to_one_message"] = (
                    first.discord_message_id == second.discord_message_id
                )
                nonce_distinct = generate_delivery_nonce()
                third = await sender.send(
                    channel_id=channel.id,
                    message=model,
                    allowed_mentions=NO_MENTIONS,
                    nonce=nonce_distinct,
                )
                scenarios["different_nonce_creates_distinct_message"] = (
                    third.discord_message_id != first.discord_message_id
                )

                # --- Cleanup ---
                for message_id in {first.discord_message_id, third.discord_message_id}:
                    try:
                        m = await channel.fetch_message(message_id)
                        await m.delete()
                    except discord.NotFound:
                        pass
            finally:
                await channel.delete()
        finally:
            await client.close()

    await client.start(token)
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include", action="store_true")
    parser.add_argument(
        "--report", type=Path, default=Path("artifacts/test-evidence/stage-09/discord-live.json")
    )
    args = parser.parse_args()

    args.report.parent.mkdir(parents=True, exist_ok=True)

    if not args.include:
        args.report.write_text(
            json.dumps(
                {
                    "status": "SKIPPED",
                    "reason": "pass --include to run against the real Discord sandbox",
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("Discord live STAGE 09 qualification: SKIPPED (pass --include to run it)")
        return 0

    load_local_environment(Path(__file__).resolve().parents[1] / ".env.local")
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variables for live qualification: {missing}")
        return 2

    token = os.environ["DISCORD_BOT_TOKEN"]
    guild_id = int(os.environ["DISCORD_TEST_GUILD_A_ID"])

    try:
        scenarios = asyncio.run(_run_live(guild_id, token))
    except Exception as exc:
        args.report.write_text(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": str(exc),
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Discord live STAGE 09 qualification: BLOCKED ({exc})")
        return 1

    all_pass = all(scenarios.values())
    report = {
        "status": "PASS" if all_pass else "FAIL",
        "scope": (
            "targeted (send/edit/delete/nonce primitives only, not the full acceptance matrix)"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "scenarios": scenarios,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Discord live STAGE 09 qualification: {report['status']} -- {args.report}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
