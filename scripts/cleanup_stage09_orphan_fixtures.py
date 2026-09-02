"""Stage09 merge-blocker remediation: SAFE orphan-fixture cleanup for the
live sandbox.

Root cause of the orphans this cleans up (see scripts/_stage09_cleanup_
registry.py's own docstring for the full story): earlier versions of
scripts/_stage09_full_chain_impl.py registered created Discord channels into
a list that was only copied into the one actually used by cleanup after
every scenario group had already run successfully. A mid-run failure,
timeout, or cancellation -- all things this repository's own live googletrans
remediation work has genuinely triggered -- left the real Discord channel
behind, uncleaned. That defect is fixed (CleanupRegistry registers and
cleans up immediately). This script is the SEPARATE, one-time (or as-needed)
sweep to remove the channels that already leaked into the sandbox before the
fix existed.

Deliberately conservative, matching this repository's own "never fake or
guess, document honestly" convention:

  * Only ever touches the two Guilds named by DISCORD_TEST_GUILD_A_ID /
    DISCORD_TEST_GUILD_B_ID -- the exact same sandbox Guilds every other
    Stage09 live validator in this repository is already scoped to. Never a
    guild id read from anywhere else.
  * A channel is only ever a DELETE candidate if its name matches the exact
    reserved Stage09 fixture naming convention this repository's own live
    scripts use (see FIXTURE_NAME_PATTERN below) -- never a loose substring
    match.
  * By default, a name match ALONE is not enough: the channel must ALSO
    appear in the Guild's own audit log as created by this bot user
    (discord.AuditLogAction.channel_create, filtered to the bot's own user
    id) -- a second, independent provenance signal. Discord's audit log has
    finite retention/pagination; a channel that name-matches but cannot be
    confirmed via audit log is reported separately and is NEVER deleted
    unless the caller passes --include-unconfirmed-name-matches explicitly
    (an explicit, auditable opt-in to the weaker single-signal check, never
    the default).
  * Dry-run by default. Nothing is deleted unless --execute is passed.
  * Writes a sanitized JSON report -- counts only, zero raw Discord
    ids/names/secrets -- exactly like every other live evidence file in this
    repository.

Usage:
    # Dry run (default): reports what WOULD be deleted, deletes nothing.
    uv run python scripts/cleanup_stage09_orphan_fixtures.py

    # Actually delete confirmed orphans (name match + audit-log-confirmed).
    uv run python scripts/cleanup_stage09_orphan_fixtures.py --execute

    # Also delete name-matched channels the audit log could not confirm
    # (explicit opt-in, logged loudly, use with care).
    uv run python scripts/cleanup_stage09_orphan_fixtures.py --execute \
        --include-unconfirmed-name-matches
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import discord

REQUIRED_VARIABLES = ("DISCORD_BOT_TOKEN", "DISCORD_TEST_GUILD_A_ID", "DISCORD_TEST_GUILD_B_ID")

#: The exact reserved Stage09 live-fixture naming convention -- matches both
#: `did-s09-fc-{uuid4().hex[:8]}` (every non-translation group) and
#: `did-s09-fc-tr-{code}-{uuid4().hex[:6]}` (translation-group channels),
#: never a loose prefix/substring match that could catch an unrelated,
#: legitimately user-named channel.
FIXTURE_NAME_PATTERN = re.compile(r"^did-s09-fc-(tr-[a-z]{2,3}-[0-9a-f]{6}|[0-9a-f]{8})$")

#: How many audit-log channel_create entries (by this bot) to page through
#: looking for provenance confirmation. Generous but bounded -- this is a
#: maintenance sweep, not a hot path.
AUDIT_LOG_SCAN_LIMIT = 2000


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in REQUIRED_VARIABLES and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


@dataclass(slots=True)
class _Findings:
    scanned_channels: int = 0
    name_matched: int = 0
    audit_confirmed: int = 0
    name_matched_unconfirmed: int = 0
    deleted: int = 0
    already_absent: int = 0
    failed: int = 0
    skipped_unconfirmed: int = 0
    audit_log_accessible: bool = True
    failures: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int | bool]:
        return {
            "scanned_channels": self.scanned_channels,
            "name_matched": self.name_matched,
            "audit_confirmed": self.audit_confirmed,
            "name_matched_unconfirmed": self.name_matched_unconfirmed,
            "deletion_attempted": self.deleted + self.already_absent + self.failed,
            "deleted_or_already_absent": self.deleted + self.already_absent,
            "failed": self.failed,
            "skipped_unconfirmed": self.skipped_unconfirmed,
            "remaining_confirmed_orphans": (
                self.audit_confirmed - self.deleted - self.already_absent - self.failed
            ),
            "audit_log_accessible": self.audit_log_accessible,
        }


async def _confirmed_channel_ids_from_audit_log(
    guild: discord.Guild, bot_user_id: int, findings: _Findings
) -> set[int] | None:
    """Returns the set of channel ids the audit log confirms THIS bot
    created, or None if the audit log could not be read at all (missing
    permission, API error) -- distinct from an empty-but-successful scan, so
    callers never conflate "confirmed nothing" with "could not check"."""
    confirmed: set[int] = set()
    try:
        scanned = 0
        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.channel_create,
            user=discord.Object(id=bot_user_id),
            limit=AUDIT_LOG_SCAN_LIMIT,
        ):
            scanned += 1
            target_id = getattr(entry.target, "id", None)
            if target_id is not None:
                confirmed.add(int(target_id))
    except discord.Forbidden:
        findings.audit_log_accessible = False
        return None
    except discord.HTTPException:
        findings.audit_log_accessible = False
        return None
    return confirmed


async def _sweep_guild(
    guild: discord.Guild,
    bot_user_id: int,
    *,
    execute: bool,
    include_unconfirmed: bool,
    findings: _Findings,
) -> None:
    channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    findings.scanned_channels += len(channels)

    name_matched = [c for c in channels if FIXTURE_NAME_PATTERN.match(c.name)]
    findings.name_matched += len(name_matched)
    if not name_matched:
        return

    confirmed_ids = await _confirmed_channel_ids_from_audit_log(guild, bot_user_id, findings)

    for channel in name_matched:
        is_audit_confirmed = confirmed_ids is not None and channel.id in confirmed_ids
        if is_audit_confirmed:
            findings.audit_confirmed += 1
        else:
            findings.name_matched_unconfirmed += 1

        if is_audit_confirmed:
            should_delete = True
        elif confirmed_ids is None:
            # Audit log itself could not be read (permission/API error) --
            # only delete if the caller explicitly opted into the weaker,
            # single-signal (name-only) check.
            should_delete = include_unconfirmed
        else:
            # Audit log WAS readable and does not show this bot creating
            # this channel -- never delete it, regardless of flags. A name
            # match alone is never sufficient when we can actually check.
            should_delete = False

        if not should_delete:
            findings.skipped_unconfirmed += 1
            continue

        if not execute:
            continue

        try:
            await channel.delete(reason="Stage09 orphan live-fixture cleanup (safe sweep)")
            findings.deleted += 1
        except discord.NotFound:
            findings.already_absent += 1
        except Exception as exc:  # deliberately broad -- best-effort, see module docstring
            findings.failed += 1
            findings.failures.append(f"channel {channel.id}: {exc!r}")


async def run_cleanup(
    guild_a_id: int, guild_b_id: int, token: str, *, execute: bool, include_unconfirmed: bool
) -> _Findings:
    findings = _Findings()
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    captured: list[BaseException] = []

    @client.event
    async def on_ready() -> None:
        try:
            bot_user_id = client.user.id  # type: ignore[union-attr]
            for guild_id in (guild_a_id, guild_b_id):
                guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
                await _sweep_guild(
                    guild,
                    bot_user_id,
                    execute=execute,
                    include_unconfirmed=include_unconfirmed,
                    findings=findings,
                )
        except BaseException as exc:  # deliberately broad -- see run_live's identical rationale
            captured.append(exc)
        finally:
            await client.close()

    await client.start(token)
    if captured:
        raise captured[0]
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually delete confirmed orphan fixtures (default: dry run, deletes nothing)",
    )
    parser.add_argument(
        "--include-unconfirmed-name-matches",
        action="store_true",
        help=(
            "also delete name-matched channels the audit log could not confirm "
            "(only when the audit log itself is unreadable, never when it is "
            "readable and simply does not show this bot as the creator)"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/test-evidence/stage-09/orphan-fixture-cleanup.json"),
    )
    args = parser.parse_args()

    load_local_environment(Path(__file__).resolve().parents[1] / ".env.local")
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variables: {missing}")
        return 2

    token = os.environ["DISCORD_BOT_TOKEN"]
    guild_a = int(os.environ["DISCORD_TEST_GUILD_A_ID"])
    guild_b = int(os.environ["DISCORD_TEST_GUILD_B_ID"])

    findings = asyncio.run(
        run_cleanup(
            guild_a,
            guild_b,
            token,
            execute=args.execute,
            include_unconfirmed=args.include_unconfirmed_name_matches,
        )
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "execute" if args.execute else "dry_run",
        "include_unconfirmed_name_matches": args.include_unconfirmed_name_matches,
        "generated_at": datetime.now(UTC).isoformat(),
        **findings.summary(),
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
