from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import promote_stage10_live_evidence as promotion

COMMIT = "a" * 40
RUN_ID = f"20200101T000000000000Z-{COMMIT[:12]}-unit"
GENERATED_AT = "2020-01-01T00:00:01+00:00"


def _common(stage: str, *, counts: dict[str, int] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": stage,
        "profile": promotion.EXPECTED_PROFILES[stage],
        "status": "PASS_WITH_APPROVED_LIMITATION" if stage in {"02", "03", "04"} else "PASS",
        "generated_at": GENERATED_AT,
        "checks": sorted(promotion.EXPECTED_CHECKS[stage]),
        "missing_variable_names": [],
        "secrets_recorded": False,
    }
    if stage != "08":
        payload["skipped_not_verified"] = sorted(promotion.APPROVED_LIMITATIONS.get(stage, set()))
    if counts is not None:
        payload["resource_counts" if stage in {"03", "04"} else "counts"] = counts
    if stage in {"05", "06", "08"}:
        payload["discord_identifiers_recorded"] = False
    return payload


def valid_reports() -> dict[str, dict[str, Any]]:
    stage02 = _common("02")
    stage02["details"] = {
        "oauth_profiles": "one sandbox account; actual A/B permission states recorded",
        "guilds": "Guild A and Guild B",
        "cleanup": "bot reinstalled on both sandboxes; temporary OAuth grants revoked",
        "limitation": "single-account live profile explicitly required by the user",
    }
    stage03 = _common(
        "03",
        counts={
            "guild_1_channels": 2,
            "guild_1_roles": 3,
            "guild_2_channels": 4,
            "guild_2_roles": 5,
        },
    )
    stage03["discord_mutations"] = 0
    stage04 = _common(
        "04",
        counts={
            "guild_1_channels_compared": 2,
            "guild_1_roles_observed": 3,
            "guild_1_permission_mismatches": 0,
            "guild_2_channels_compared": 4,
            "guild_2_roles_observed": 5,
            "guild_2_permission_mismatches": 0,
        },
    )
    stage04["discord_mutations"] = 0
    stage04["oracle"] = "Discord API observations with discord.py as secondary calculator"
    stage05 = _common(
        "05",
        counts={
            "plans_succeeded": 6,
            "create_operations": 4,
            "create_calls_at_crash_recovery": 1,
            "create_calls_total": 4,
            "update_operations_verified": 3,
            "move_or_reorder_operations_verified": 3,
            "overwrite_upserts": 1,
            "overwrite_deletes": 1,
            "cleanup_operations": 4,
            "role_order_restore_operations": 1,
            "symbol_bindings_recovered": 1,
            "controlled_failure_hooks": 1,
            "abandoned_fixture_jobs_resumed": 1,
            "terminal_fixture_jobs_acknowledged": 1,
            "preexisting_fixtures_cleaned": 0,
        },
    )
    stage05["resource_prefix"] = "DID-STAGE05-TEST-"
    stage06 = _common(
        "06",
        counts={
            "source_fixture_resources": 4,
            "destination_copy_plans": 2,
            "explicit_role_mappings": 1,
            "explicit_structural_mappings": 1,
            "new_destination_ids_verified": 2,
            "source_mutations_during_clone": 0,
            "source_read_after_export": 0,
            "divergent_merge_updates_verified": 2,
            "full_text_channel_properties_verified": 2,
            "reconcile_owned_deletes": 1,
            "reconcile_unrelated_controls_untouched": 1,
            "stable_survivor_refs_across_generations": 1,
            "natural_a1_a2_reconcile_cycles": 1,
            "durable_export_retries_without_source_read": 1,
            "relationships_surviving_artifact_delete": 1,
            "bindings_surviving_artifact_delete": 1,
            "tombstoned_removed_bindings": 1,
            "resumed_portability_jobs": 1,
            "cleanup_resources": 8,
            "artifacts_purged": 2,
        },
    )
    stage06["resource_prefix"] = "DID-STAGE06-TEST-"
    stage08 = _common(
        "08",
        counts={
            "guilds_verified": 2,
            "languages_created": 4,
            "independent_same_pair_groups": 2,
            "variant_plans_applied": 4,
            "provider_present_verified": 1,
            "provider_absent_failed_closed": 1,
            "hub_and_spoke_routes": 3,
            "scope_language_roles_created": 2,
            "scope_language_roles_reused": 1,
            "member_roles_assigned": 2,
            "member_roles_removed": 2,
            "open_all_paths_verified": 1,
            "destination_translation_groups_created": 1,
            "stage05_plan_mutations": 12,
            "cleanup_plans_applied": 2,
            "stale_technical_roles_recovered": 1,
            "direct_discord_mutations": 0,
            "message_content_intent": 0,
        },
    )
    stage08.update(
        {
            "evidence_hashes": {
                "run_prefix_sha256": "1" * 64,
                "source_before_clone_sha256": "2" * 64,
                "source_after_clone_sha256": "2" * 64,
                "portable_artifact_sha256": "3" * 64,
            },
            "blocker": None,
            "missing_capabilities": [],
            "resource_prefix_family": "DID-STAGE08-TEST-",
            "message_content_intent_enabled": False,
            "discord_structural_mutations_direct": 0,
        }
    )
    primitives = {
        "status": "PASS",
        "scope": "targeted (send/edit/delete/nonce primitives only, "
        + "not the full acceptance matrix)",
        "generated_at": GENERATED_AT,
        "scenarios": {name: True for name in sorted(promotion.PRIMITIVE_SCENARIOS)},
    }
    full_chain = {
        "status": "PASS",
        "scope": "the COMPLETE runtime chain (synthetic deterministic fixture)",
        "groups_run": list(promotion.FULL_CHAIN_GROUPS),
        "generated_at": GENERATED_AT,
        "scenarios": {f"scenario_{index:02d}": True for index in range(60)},
        "notes": [],
        "cleanup": {
            "created": 42,
            "deletion_attempted": 42,
            "deleted_or_already_absent": 42,
            "failed": 0,
            "remaining": 0,
        },
        "secrets_recorded": False,
        "discord_identifiers_recorded": False,
    }
    return {
        "discord-live-02.json": stage02,
        "discord-live-03.json": stage03,
        "discord-live-04.json": stage04,
        "discord-live-05.json": stage05,
        "discord-live-06.json": stage06,
        "discord-live-08.json": stage08,
        "discord-live-09-primitives.json": primitives,
        "discord-live-09-full-chain.json": full_chain,
    }


def write_valid_reports(
    parent: Path, *, commit: str = COMMIT, run_id: str | None = None
) -> tuple[Path, str, str]:
    selected_run_id = run_id or f"20200101T000000000000Z-{commit[:12]}-unit"
    directory = parent / selected_run_id
    directory.mkdir()
    for name, payload in valid_reports().items():
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")
    return directory, commit, selected_run_id


def create_valid_closure(parent: Path) -> tuple[Path, str, str, Path]:
    directory, commit, run_id = write_valid_reports(parent)
    aggregate = promotion.promote(
        directory,
        expected_commit=commit,
        expected_run_id=run_id,
    )
    return directory, commit, run_id, aggregate
