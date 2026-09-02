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
    both what DID's own code is responsible for (correct destination
    routing, correct destination count, non-empty delivered content,
    exactly-one-message-per-delivery) AND that a genuine translation
    actually occurred: the content used is deliberately linguistic prose
    (never a proper noun/acronym/technical-only string), so a translated
    destination coming back byte-identical to the untranslated source is
    treated as a real failure, not logged and excused. A previous version of
    this script only logged that identity as a non-blocking ``[observed]``
    note -- a real test-severity defect an external audit found: it masked
    the fact that ``GoogletransCampaignTranslationProvider`` was silently
    accepting a transport failure (googletrans's own ``DUMMY_DATA`` echo
    fallback, triggered by its unsafe ``raise_exception=False`` default) as
    a successful translation. Both issues are fixed now: the adapter itself
    fails closed on a transport failure (``_production_translator`` in
    ``did.translation.googletrans_adapter``), and this script's assertions
    no longer excuse an echo that does slip through. When the real
    googletrans endpoint is genuinely unavailable (proven in this sandbox --
    HTTP 429/403 from Google's own endpoints), these translation-dependent
    checks now correctly FAIL rather than reporting a false PASS; any
    resulting content-identity rejection is still recorded in the JSON
    report's own ``notes`` field alongside the group's own ``[FAIL]`` log
    line, never silently dropped.
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
groups in the real sandbox Guild(s), uses synthetic content only, and writes
a sanitized JSON report (including a "cleanup" summary, see below) with zero
secrets, zero raw Discord ids, zero PII.

Cleanup correctness (external review finding, fixed): every created channel
is registered with a `CleanupRegistry` (scripts/_stage09_cleanup_registry.py)
IMMEDIATELY on creation and cleaned up from a `finally` block that always
runs, regardless of how a scenario group exits (success, assertion failure,
provider failure, timeout, cancellation, or a discord.py event-handler
exception). A previous version of this script batched created channels into
a second list that was only populated after every scenario group had already
completed successfully -- a mid-run failure left that second list empty, and
the `finally` block that used it deleted nothing, even though real channels
had already been created. That defect is what left the ``did-s09-fc-...``
orphan channels this repository's own sandbox accumulated after interrupted
live runs; `scripts/cleanup_stage09_orphan_fixtures.py` is the separate,
conservative one-time sweep that removed them (name-match AND audit-log-
confirmed bot authorship required by default -- never a bare name-prefix
match). This canonical script itself now reports FAIL (never a false PASS)
if any resource it created remains undeleted when it finishes -- see its
own report's "cleanup" field: created/deletion_attempted/deleted_or_already_
absent/failed/remaining.
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
        scenarios, observations, cleanup_summary = asyncio.run(
            asyncio.wait_for(run_live(guild_a, guild_b, token, groups), timeout=180.0)
        )
    except Exception as exc:
        # Real Discord channels created before the failure are still
        # cleaned up inside run_live's own `finally` block regardless of
        # this exception -- see _stage09_cleanup_registry.py. Its summary is
        # attached to the exception (when available) so a BLOCKED report
        # never silently omits cleanup evidence just because the run itself
        # failed partway through.
        report_cleanup = getattr(exc, "cleanup_summary", None)
        args.report.write_text(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": str(exc),
                    "generated_at": datetime.now(UTC).isoformat(),
                    "cleanup": report_cleanup,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        cleanup_note = f", cleanup={report_cleanup}" if report_cleanup is not None else ""
        print(f"Discord live STAGE 09 full-chain qualification: BLOCKED ({exc}){cleanup_note}")
        return 1

    # A canonical run must never report PASS while resources it created
    # remain undeleted -- a leaked orphan channel in the real sandbox is a
    # real defect this validator itself must catch, not merely something to
    # note. cleanup_all() is best-effort (one failing deletion never blocks
    # cleanup of the rest -- see CleanupRegistry), so `remaining` reflects
    # genuine leftovers, not merely deletions still in flight.
    all_pass = all(scenarios.values()) and cleanup_summary["remaining"] == 0
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
        "cleanup": cleanup_summary,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Discord live STAGE 09 full-chain qualification: {report['status']} -- {args.report}")
    if cleanup_summary["remaining"] > 0:
        print(
            f"  [FAIL] {cleanup_summary['remaining']} resource(s) created by this run remain "
            'undeleted in the real sandbox -- see the report\'s own "cleanup" field.'
        )
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
