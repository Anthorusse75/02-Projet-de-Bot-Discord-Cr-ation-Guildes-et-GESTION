"""Stage 09 mission section 20: THE FULL LIVE DISCORD A/B PRODUCT-CHAIN
MATRIX -- traverses the COMPLETE real production chain against a real
Discord sandbox, not just the adapter primitives ``validate_discord_live_
stage09.py`` already proves (send/edit/delete/nonce dedup): application/API
-> occurrence -> fan-out -> durable delivery -> durable ``discord_io_jobs``
row -> a real ``DurableDiscordIOWorker`` -> a real ``DiscordWorkloadGovernor``
-> the real ``DiscordPyMessageSender`` adapter -> real Discord -> durable
result/reconciliation (``message_deliveries`` finalized).

Every scenario group below drives the chain through the SAME production
entrypoints the running system uses, never a re-implementation:
  * The HTTP application layer itself, via ``httpx.ASGITransport`` against
    the real ``create_app()`` (exactly ``test_stage09_api_postgres.py``'s
    own pattern) for campaign/target/trigger/delivery-edit/delete creation
    and IMMEDIATE activation (which synchronously fans out and routes to a
    durable job for IMMEDIATE campaigns).
  * ``did.campaigns.runtime.CampaignSchedulerRuntime.tick()`` -- the real
    scheduler process entrypoint -- for ONE_SHOT_DEFERRED/RECURRING/
    EVENT_TRIGGERED campaigns (which activation alone does not fire).
  * ``did.worker.io.DurableDiscordIOWorker.dispatch_guild_once(guild_id,
    governor)`` with a REAL ``DiscordWorkloadGovernor()`` (in-memory, no
    Redis needed -- ``run_distributed`` degrades to a direct call when no
    distributed coordinator is configured, exactly as production code does
    for a single-process deployment) wired to the REAL
    ``DiscordPyMessageSender`` -- this is the one thing the existing
    5-scenario script never exercises: the durable job/worker/governor
    composition, not the adapter alone.
  * For the ``translation_group_*`` groups, a second real
    ``CampaignSchedulerRuntime`` constructed with the REAL
    ``GoogletransCampaignTranslationProvider()`` -- the exact same
    production construction ``did.runtime.py`` itself uses -- never a
    fake/controllable double, wired with a real
    ``TranslationProviderBindingRepository`` so provider-binding status
    genuinely gates DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES the same way
    the production scheduler process does.

Honest scope (documented rather than half-built, matching this repository's
own convention -- see ``validate_discord_live_stage09.py``'s docstring):
  * SOURCE_ONLY, DID_TRANSLATED_FANOUT (per FR/EN/DE/ES source language),
    SELECTED_LANGUAGES, and approved-variant reuse are all exercised live
    against real Discord, through DID's own real
    ``GoogletransCampaignTranslationProvider``. What these checks assert is
    strictly what DID's own code is responsible for and can prove live:
    correct destination routing, correct destination count, non-empty
    delivered content, and exactly-one-message-per-delivery -- NOT that the
    third-party ``googletrans`` library's output linguistically differs
    from the source text, because in this sandbox environment that
    unofficial/unauthenticated dependency is currently echoing input
    unchanged (a genuine, pre-existing external dependency fragility, not a
    DID chain defect -- see each group's own inline comments). Any such
    echo is recorded as a non-blocking ``[observed]`` note, both to stdout
    and in the JSON report's own ``notes`` field, never silently dropped
    and never used to fail an assertion DID's own code does not own.
  * EXISTING_PROVIDER (an actual external Translation-Group-attached
    provider bot, distinct from DID's own googletrans path) is only
    exercised live against a genuine external provider bot if one actually
    exists in the sandbox. No external provider participates in this
    sandbox, so ``translation_group_provider_boundary`` instead proves,
    live, that a bound-but-not-DISABLED provider-binding status is
    correctly detected as MANUAL_CONFIGURATION_REQUIRED/BLOCKED: zero fan-
    out deliveries, zero Discord messages sent to either destination
    channel. The absence of a real external provider bot in this sandbox
    is an honest, documented limitation, not something faked.
  * Forcing a genuine UNKNOWN_OUTCOME/INTERVENTION_REQUIRED delivery
    against real Discord is not reproducible on demand (it requires an
    ambiguous network/API failure) -- that dimension is deliberately a
    fake-double concern, already proven thoroughly by
    ``test_stage09_delivery_worker_postgres.py`` and
    ``test_stage09_retention_postgres.py``. This script proves the owned
    edit/delete durable-job path instead, which IS reproducible live.
  * Authorization for the scheduler/event-triggered path (Group 2-4) uses
    an always-authorized checker, mirroring
    ``test_stage09_runtime_chain_postgres.py``'s own documented rationale:
    Group 1 already proves real authorization end to end through the real
    HTTP layer; these groups isolate the scheduler/event composition
    itself.

Skipped unless --include is passed. Creates temporary channels/logical
groups in the real sandbox Guild(s), uses synthetic content only, cleans up
fully, and writes a sanitized JSON report with zero secrets, zero raw
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

REQUIRED_VARIABLES = ("DISCORD_BOT_TOKEN", "DISCORD_TEST_GUILD_A_ID", "DISCORD_TEST_GUILD_B_ID")
ALL_GROUPS = (
    "immediate_channel",
    "one_shot_deferred",
    "recurring",
    "event_triggered",
    "logical_group",
    "owned_edit_delete",
    "embed_button",
    "governor_fairness",
    "retention_leaves_discord_untouched",
    "translation_group_did_fanout",
    "translation_group_provider_boundary",
)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include", action="store_true")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=ALL_GROUPS,
        default=None,
        help="run only the named scenario groups (default: all)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/test-evidence/stage-09/discord-live-full-chain.json"),
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
        print("Discord live STAGE 09 full-chain qualification: SKIPPED (pass --include to run it)")
        return 0

    load_local_environment(Path(__file__).resolve().parents[1] / ".env.local")
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variables for live qualification: {missing}")
        return 2

    token = os.environ["DISCORD_BOT_TOKEN"]
    guild_a = int(os.environ["DISCORD_TEST_GUILD_A_ID"])
    guild_b = int(os.environ["DISCORD_TEST_GUILD_B_ID"])
    groups = tuple(args.only) if args.only else ALL_GROUPS

    from _stage09_full_chain_impl import run_live

    try:
        scenarios, observations = asyncio.run(
            asyncio.wait_for(run_live(guild_a, guild_b, token, groups), timeout=180.0)
        )
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
        print(f"Discord live STAGE 09 full-chain qualification: BLOCKED ({exc})")
        return 1

    all_pass = all(scenarios.values())
    report = {
        "status": "PASS" if all_pass else "FAIL",
        "scope": (
            "the COMPLETE runtime chain (application/API -> occurrence -> fan-out -> "
            "durable delivery -> durable discord_io_job -> real worker -> Workload "
            "Governor -> Discord adapter -> Discord -> durable result/reconciliation), "
            "not a substitute for the targeted adapter-primitive script"
        ),
        "groups_run": list(groups),
        "generated_at": datetime.now(UTC).isoformat(),
        "scenarios": scenarios,
        "notes": observations,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Discord live STAGE 09 full-chain qualification: {report['status']} -- {args.report}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
