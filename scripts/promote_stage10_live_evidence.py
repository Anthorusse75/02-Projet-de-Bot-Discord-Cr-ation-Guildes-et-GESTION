"""Fail-closed promotion proof for the Stage 10 Discord A/B live matrix.

The evidence directory passed on the command line is the trust boundary.  This
module never searches ``artifacts`` and never accepts a source report outside
that directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AGGREGATE_NAME = "stage10-discord-live-closure.json"
REQUIREMENT_ID = "REQ-TEST-003"
FULL_CHAIN_GROUPS = (
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
PRIMITIVE_SCENARIOS = {
    "immediate_send_allowed_mentions_none",
    "owned_edit_applies_new_content",
    "owned_delete_removes_message",
    "same_nonce_dedups_to_one_message",
    "different_nonce_creates_distinct_message",
}
PASS_WITH_APPROVED_LIMITATION_STAGES = {"02", "03", "04"}
APPROVED_LIMITATIONS = {
    "02": {
        "live administrator non-owner profile",
        "live non-administrator profile",
    },
    "03": {
        "external Discord mutation observed through Gateway",
        "forced Gateway reconnect/RESUME/non-resumed",
        "Channel Obfuscation live visibility change: CONTRACT_ONLY_NOT_LIVE_VERIFIED",
        "inherited STAGE 02 administrator non-owner profile",
        "inherited STAGE 02 non-administrator profile",
    },
    "04": {
        "active/public/private thread membership matrix requires controlled fixtures",
        "category synced/desynced mutation fixtures are not created by this read-only runner",
        "managed/equal role hierarchy mutation fixtures are not created by this read-only runner",
        "inherited STAGE 02 administrator non-owner human profile",
        "inherited STAGE 02 non-administrator human profile",
    },
    "05": {
        "429 behavior is contract-tested, not forced against Discord",
        "ambiguous duplicate CREATE requires manual sandbox fixture and is not forced",
    },
    "06": {
        "bot/webhook incompatibilities are security-tested without unsafe live fixtures",
    },
}
EXPECTED_PROFILES = {
    "02": "discord-live-sandbox",
    "03": "discord-live-sandbox-read-only",
    "04": "discord-live-sandbox-read-only",
    "05": "discord-live-plan-engine-safe-mutations",
    "06": "discord-live-cross-guild-portability",
    "08": "discord-live-multilingual-topology",
}
EXPECTED_REPORTS = (
    "discord-live-02.json",
    "discord-live-03.json",
    "discord-live-04.json",
    "discord-live-05.json",
    "discord-live-06.json",
    "discord-live-08.json",
    "discord-live-09-primitives.json",
    "discord-live-09-full-chain.json",
)
EXPECTED_TOP_LEVEL_KEYS = {
    "02": {
        "stage",
        "profile",
        "status",
        "generated_at",
        "checks",
        "missing_variable_names",
        "details",
        "skipped_not_verified",
        "secrets_recorded",
    },
    "03": {
        "stage",
        "profile",
        "status",
        "generated_at",
        "checks",
        "missing_variable_names",
        "resource_counts",
        "skipped_not_verified",
        "discord_mutations",
        "secrets_recorded",
    },
    "04": {
        "stage",
        "profile",
        "status",
        "generated_at",
        "checks",
        "missing_variable_names",
        "resource_counts",
        "skipped_not_verified",
        "oracle",
        "discord_mutations",
        "secrets_recorded",
    },
    "05": {
        "stage",
        "profile",
        "status",
        "generated_at",
        "checks",
        "missing_variable_names",
        "counts",
        "skipped_not_verified",
        "resource_prefix",
        "secrets_recorded",
        "discord_identifiers_recorded",
    },
    "06": {
        "stage",
        "profile",
        "status",
        "generated_at",
        "checks",
        "missing_variable_names",
        "counts",
        "skipped_not_verified",
        "resource_prefix",
        "secrets_recorded",
        "discord_identifiers_recorded",
    },
    "08": {
        "stage",
        "profile",
        "status",
        "generated_at",
        "checks",
        "missing_variable_names",
        "counts",
        "evidence_hashes",
        "blocker",
        "missing_capabilities",
        "resource_prefix_family",
        "secrets_recorded",
        "discord_identifiers_recorded",
        "message_content_intent_enabled",
        "discord_structural_mutations_direct",
    },
}
EXPECTED_CHECKS = {
    "02": {
        "bot identity matches application",
        "OAuth identify/guilds profile: owner",
        "targeted Get Guild Member for each live actor",
        "temporary OAuth grants revoked",
        "minimal bot installation observed: Guild A",
        "bot uninstall observed: Guild A",
        "bot reinstall observed: Guild A",
        "minimal bot installation observed: Guild B",
        "bot uninstall observed: Guild B",
        "bot reinstall observed: Guild B",
    },
    "03": {
        "bot-token identity login through discord.py",
        "Guild A/B Get Guild Channels and Get Guild Roles through governed initial sync",
        "categories/channels/roles/overwrites normalized and persisted in PostgreSQL test DB",
        "Redis hot projections rebuilt from PostgreSQL for Guild A/B",
        "tenant Redis namespaces distinct; Discord mutations remained zero",
    },
    "04": {
        "Guild A/B roles, channels and bot member observed read-only",
        "effective bot channel permissions matched discord.py secondary oracle",
        "Snowflakes and permission bitfields retained as arbitrary-precision integers",
        "Discord mutations remained zero",
    },
    "05": {
        "persisted plans, sensitive worker authorization and final preflight",
        "all Discord REST reads and mutations passed the workload governor",
        "CREATE category, channel and role fixtures",
        "UPDATE role, category and channel",
        "MOVE channel parent and REORDER roles",
        "UPSERT and DELETE overwrite",
        "controlled crash after CREATE_ROLE Discord response",
        "UNKNOWN_OUTCOME recovery without duplicate CREATE",
        "recovered durable symbol binding",
        "targeted REST verification after each plan",
        "persisted destructive cleanup plan",
        "all prefixed fixtures absent after cleanup",
    },
    "06": {
        "source fixtures created only by STAGE 05 plan",
        "LIVE export produced immutable encrypted artifact",
        "Dependency Graph and Mapping Resolver compiled a destination-only plan",
        "COPY_AS_NEW created distinct destination Discord IDs",
        "explicit existing-role mapping was confirmed",
        "divergent destination role/channel were restored by stored MERGE",
        "text slowmode and default auto archive duration were preserved",
        "stored artifact compiled and applied with source reader fail-if-called",
        "A1 artifact deletion preserved the server-generated clone relationship",
        "natural A1-to-A2 RECONCILE exposed the exact removed-source destination",
        "natural A1-to-A2 RECONCILE updated, created and tombstoned bindings",
        "unrelated destination control remained untouched",
        "source A2 snapshot remained byte-identical during destination reconciliation",
        "mutable adapter recorded zero source calls during clone",
        "source and destination cleanup used audited STAGE 05 plans",
        "A2 artifact deletion preserved the relationship and active bindings",
        "ephemeral artifacts and transfers were purged",
    },
    "08": {
        "all Discord REST reads and plan mutations traversed the workload governor",
        "two independent groups exercised FR/EN and FR/EN/DE/ES variants",
        "provider-present verification used authoritative bot and permission facts",
        "provider-absent manual verification failed closed",
        "Scope x Language roles were created lazily, reused, and permissionless",
        "many-language, zero-language, and open-all paths were exercised",
        "the Stage 06 to Stage 05 clone created an independent Guild B topology",
        "provider bindings, provider identity, tokens, and source IDs were omitted",
        "source fixture hashes remained identical across the clone",
        "owned fixtures and safe technical bindings were deleted through plans",
    },
}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^(?P<timestamp>\d{8}T\d{12}Z)-(?P<sha>[0-9a-f]{12})-[A-Za-z0-9._-]+$")
SNOWFLAKE = re.compile(r"(?<!\d)\d{15,22}(?!\d)")
SENSITIVE_KEY = re.compile(r"(?:^|_)(?:token|password|secret|guild_id|channel_id|role_id)(?:$|_)")


class PromotionError(ValueError):
    """The supplied live evidence cannot qualify REQ-TEST-003."""


@dataclass(frozen=True, slots=True)
class ValidatedReport:
    name: str
    stage: str
    profile: str
    status: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedClosure:
    commit: str
    run_id: str
    reports: tuple[ValidatedReport, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionError(message)


def _safe_child(directory: Path, name: str) -> Path:
    path = directory / name
    _require(not path.is_symlink(), f"symlink evidence is forbidden: {name}")
    _require(path.resolve().parent == directory, f"evidence escapes the current run: {name}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"required report is missing: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid JSON report: {path.name}") from exc
    _require(isinstance(payload, dict), f"report root must be an object: {path.name}")
    return payload


def _walk_privacy(value: Any, *, path: str = "report") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _require(isinstance(key, str), f"non-string JSON key at {path}")
            if key == "commit" or key == "sha256" or key.endswith("_sha256"):
                digest_pattern = FULL_SHA if key == "commit" else SHA256
                _require(
                    isinstance(child, str) and digest_pattern.fullmatch(child) is not None,
                    f"invalid digest at {path}.{key}",
                )
                continue
            if key not in {"secrets_recorded", "discord_identifiers_recorded"}:
                _require(
                    SENSITIVE_KEY.search(key.lower()) is None,
                    f"sensitive field is forbidden at {path}.{key}",
                )
            _walk_privacy(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_privacy(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        _require(SNOWFLAKE.search(value) is None, f"raw Discord identifier at {path}")
    elif isinstance(value, int) and not isinstance(value, bool):
        _require(not (10**14 <= value < 10**22), f"raw Discord identifier at {path}")


def _run_started_at(run_id: str, commit: str) -> datetime | None:
    match = RUN_ID.fullmatch(run_id)
    if match is None:
        return None
    _require(commit.startswith(match.group("sha")), "run id commit prefix does not match commit")
    return datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)


def _validate_timestamp(payload: dict[str, Any], *, name: str, started_at: datetime | None) -> None:
    raw = payload.get("generated_at")
    _require(isinstance(raw, str), f"generated_at is missing: {name}")
    try:
        generated_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError(f"generated_at is invalid: {name}") from exc
    _require(generated_at.tzinfo is not None, f"generated_at is not timezone-aware: {name}")
    generated_at = generated_at.astimezone(UTC)
    if started_at is not None:
        _require(generated_at >= started_at, f"report predates the current run: {name}")
    _require(generated_at <= datetime.now(UTC), f"report timestamp is in the future: {name}")


def _string_set(payload: dict[str, Any], field: str, *, name: str) -> set[str]:
    value = payload.get(field)
    _require(
        isinstance(value, list) and all(isinstance(item, str) for item in value),
        f"{field} must be a string list: {name}",
    )
    return set(value)


def _int_map(payload: dict[str, Any], field: str, *, name: str) -> dict[str, int]:
    value = payload.get(field)
    _require(isinstance(value, dict), f"{field} must be an object: {name}")
    _require(
        all(
            isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool)
            for key, item in value.items()
        ),
        f"{field} must contain integer counters: {name}",
    )
    return value


def _validate_common(
    payload: dict[str, Any], *, stage: str, name: str, started_at: datetime | None
) -> None:
    _require(set(payload) == EXPECTED_TOP_LEVEL_KEYS[stage], f"unexpected schema in {name}")
    _require(payload.get("stage") == stage, f"unexpected stage in {name}")
    _require(payload.get("profile") == EXPECTED_PROFILES[stage], f"unexpected profile in {name}")
    allowed_status = (
        {"PASS_WITH_APPROVED_LIMITATION"}
        if stage in PASS_WITH_APPROVED_LIMITATION_STAGES
        else {"PASS"}
    )
    status = payload.get("status")
    _require(status in allowed_status, f"non-green or unexpected status in {name}: {status!r}")
    _require(
        payload.get("secrets_recorded") is False, f"privacy assertion missing/unsafe in {name}"
    )
    if stage in {"05", "06", "08"}:
        _require(
            payload.get("discord_identifiers_recorded") is False,
            f"Discord identifier assertion missing/unsafe in {name}",
        )
    if stage in {"05", "06"}:
        _require(
            payload.get("resource_prefix") == f"DID-STAGE{stage}-TEST-",
            f"unexpected live resource prefix in {name}",
        )
    _require(payload.get("missing_variable_names") == [], f"missing live configuration in {name}")
    checks = _string_set(payload, "checks", name=name)
    _require(checks == EXPECTED_CHECKS[stage], f"incomplete or unexpected check set in {name}")
    if stage in APPROVED_LIMITATIONS:
        limitations = _string_set(payload, "skipped_not_verified", name=name)
        _require(
            limitations == APPROVED_LIMITATIONS[stage],
            f"unapproved or incomplete limitation set in {name}",
        )
    _validate_timestamp(payload, name=name, started_at=started_at)


def _validate_counters(stage: str, payload: dict[str, Any], *, name: str) -> None:
    field = "resource_counts" if stage in {"03", "04"} else "counts"
    counts = _int_map(payload, field, name=name)
    if stage == "03":
        expected = {
            "guild_1_channels",
            "guild_1_roles",
            "guild_2_channels",
            "guild_2_roles",
        }
        _require(
            set(counts) == expected and all(item >= 0 for item in counts.values()),
            f"invalid Guild A/B resource counters in {name}",
        )
        _require(
            payload.get("discord_mutations") == 0, f"read-only Stage 03 mutated Discord in {name}"
        )
    elif stage == "04":
        expected = {
            f"guild_{guild}_{suffix}"
            for guild in (1, 2)
            for suffix in ("channels_compared", "roles_observed", "permission_mismatches")
        }
        _require(set(counts) == expected, f"invalid Guild A/B oracle counters in {name}")
        _require(
            counts["guild_1_permission_mismatches"] == 0
            and counts["guild_2_permission_mismatches"] == 0,
            f"permission mismatches in {name}",
        )
        _require(
            payload.get("discord_mutations") == 0, f"read-only Stage 04 mutated Discord in {name}"
        )
        _require(
            payload.get("oracle")
            == "Discord API observations with discord.py as secondary calculator",
            f"unexpected permission oracle in {name}",
        )
    elif stage == "05":
        expected = {
            "plans_succeeded",
            "create_operations",
            "create_calls_at_crash_recovery",
            "create_calls_total",
            "update_operations_verified",
            "move_or_reorder_operations_verified",
            "overwrite_upserts",
            "overwrite_deletes",
            "cleanup_operations",
            "role_order_restore_operations",
            "symbol_bindings_recovered",
            "controlled_failure_hooks",
            "abandoned_fixture_jobs_resumed",
            "terminal_fixture_jobs_acknowledged",
            "preexisting_fixtures_cleaned",
        }
        _require(set(counts) == expected, f"incomplete Stage 05 counters in {name}")
        _require(
            all(counts[key] > 0 for key in expected - {"preexisting_fixtures_cleaned"}),
            f"non-positive Stage 05 proof counter in {name}",
        )
        _require(
            counts["create_calls_at_crash_recovery"] == 1,
            f"duplicate crash-recovery create in {name}",
        )
    elif stage == "06":
        expected = {
            "source_fixture_resources",
            "destination_copy_plans",
            "explicit_role_mappings",
            "explicit_structural_mappings",
            "new_destination_ids_verified",
            "source_mutations_during_clone",
            "source_read_after_export",
            "divergent_merge_updates_verified",
            "full_text_channel_properties_verified",
            "reconcile_owned_deletes",
            "reconcile_unrelated_controls_untouched",
            "stable_survivor_refs_across_generations",
            "natural_a1_a2_reconcile_cycles",
            "durable_export_retries_without_source_read",
            "relationships_surviving_artifact_delete",
            "bindings_surviving_artifact_delete",
            "tombstoned_removed_bindings",
            "resumed_portability_jobs",
            "cleanup_resources",
            "artifacts_purged",
        }
        _require(set(counts) == expected, f"incomplete Stage 06 counters in {name}")
        _require(
            counts["source_mutations_during_clone"] == 0
            and counts["source_read_after_export"] == 0,
            f"source isolation failed in {name}",
        )
        positive = expected - {"source_mutations_during_clone", "source_read_after_export"}
        _require(
            all(counts[key] > 0 for key in positive),
            f"non-positive Stage 06 proof counter in {name}",
        )
        _require(counts["artifacts_purged"] == 2, f"Stage 06 artifacts were not purged in {name}")
    elif stage == "08":
        expected = {
            "guilds_verified",
            "languages_created",
            "independent_same_pair_groups",
            "variant_plans_applied",
            "provider_present_verified",
            "provider_absent_failed_closed",
            "hub_and_spoke_routes",
            "scope_language_roles_created",
            "scope_language_roles_reused",
            "member_roles_assigned",
            "member_roles_removed",
            "open_all_paths_verified",
            "destination_translation_groups_created",
            "stage05_plan_mutations",
            "cleanup_plans_applied",
            "stale_technical_roles_recovered",
            "direct_discord_mutations",
            "message_content_intent",
        }
        _require(set(counts) == expected, f"incomplete Stage 08 counters in {name}")
        _require(
            counts["guilds_verified"] == 2, f"two independent Guilds were not verified in {name}"
        )
        _require(
            counts["independent_same_pair_groups"] >= 2, f"independent groups missing in {name}"
        )
        _require(counts["cleanup_plans_applied"] > 0, f"Stage 08 cleanup proof missing in {name}")
        _require(
            counts["direct_discord_mutations"] == 0 and counts["message_content_intent"] == 0,
            f"Stage 08 safety contract failed in {name}",
        )
        _require(
            payload.get("blocker") is None and payload.get("missing_capabilities") == [],
            f"Stage 08 is blocked or lacks capabilities in {name}",
        )
        _require(
            payload.get("message_content_intent_enabled") is False,
            f"MESSAGE_CONTENT was enabled in {name}",
        )
        _require(
            payload.get("discord_structural_mutations_direct") == 0,
            f"direct Discord mutation in {name}",
        )
        _require(
            payload.get("resource_prefix_family") == "DID-STAGE08-TEST-",
            f"unexpected Stage 08 resource prefix in {name}",
        )
        hashes = payload.get("evidence_hashes")
        _require(
            isinstance(hashes, dict)
            and set(hashes)
            == {
                "run_prefix_sha256",
                "source_before_clone_sha256",
                "source_after_clone_sha256",
                "portable_artifact_sha256",
            },
            f"Stage 08 evidence hashes are incomplete in {name}",
        )
        _require(
            hashes["source_before_clone_sha256"] == hashes["source_after_clone_sha256"],
            f"Stage 08 source changed during clone in {name}",
        )


def _validate_primitives(
    payload: dict[str, Any], *, name: str, started_at: datetime | None
) -> None:
    _require(
        set(payload) == {"status", "scope", "generated_at", "scenarios"},
        f"unexpected primitives schema in {name}",
    )
    _require(payload.get("status") == "PASS", f"non-green primitives status in {name}")
    _require(
        payload.get("scope")
        == "targeted (send/edit/delete/nonce primitives only, not the full acceptance matrix)",
        f"unexpected primitives scope in {name}",
    )
    scenarios = payload.get("scenarios")
    _require(
        isinstance(scenarios, dict) and set(scenarios) == PRIMITIVE_SCENARIOS,
        f"incomplete primitive scenarios in {name}",
    )
    _require(
        all(value is True for value in scenarios.values()), f"failed primitive scenario in {name}"
    )
    _validate_timestamp(payload, name=name, started_at=started_at)


def _validate_full_chain(
    payload: dict[str, Any], *, name: str, started_at: datetime | None
) -> None:
    _require(
        set(payload)
        == {
            "status",
            "scope",
            "groups_run",
            "generated_at",
            "scenarios",
            "notes",
            "cleanup",
            "secrets_recorded",
            "discord_identifiers_recorded",
        },
        f"unexpected full-chain schema in {name}",
    )
    _require(payload.get("status") == "PASS", f"non-green full-chain status in {name}")
    scope = payload.get("scope")
    _require(
        isinstance(scope, str) and scope.startswith("the COMPLETE runtime chain"),
        f"unexpected full-chain scope in {name}",
    )
    _require(
        payload.get("groups_run") == list(FULL_CHAIN_GROUPS),
        f"full-chain group matrix is incomplete in {name}",
    )
    _require(
        isinstance(payload.get("notes"), list)
        and all(isinstance(note, str) for note in payload["notes"]),
        f"full-chain notes are invalid in {name}",
    )
    scenarios = payload.get("scenarios")
    _require(
        isinstance(scenarios, dict) and len(scenarios) == 60,
        f"full-chain scenarios are incomplete in {name}",
    )
    _require(
        all(isinstance(key, str) and value is True for key, value in scenarios.items()),
        f"failed full-chain scenario in {name}",
    )
    cleanup = _int_map(payload, "cleanup", name=name)
    _require(
        set(cleanup)
        == {"created", "deletion_attempted", "deleted_or_already_absent", "failed", "remaining"},
        f"invalid full-chain cleanup proof in {name}",
    )
    _require(cleanup["created"] > 0, f"full-chain created no live fixture in {name}")
    _require(
        cleanup["created"] == cleanup["deletion_attempted"] == cleanup["deleted_or_already_absent"],
        f"full-chain cleanup is incomplete in {name}",
    )
    _require(
        cleanup["failed"] == 0 and cleanup["remaining"] == 0, f"full-chain cleanup failed in {name}"
    )
    _require(
        payload.get("secrets_recorded") is False, f"privacy assertion missing/unsafe in {name}"
    )
    _require(
        payload.get("discord_identifiers_recorded") is False,
        f"Discord identifier assertion missing/unsafe in {name}",
    )
    _validate_timestamp(payload, name=name, started_at=started_at)


def validate_live_reports(
    evidence_directory: Path, *, expected_commit: str, expected_run_id: str
) -> tuple[ValidatedReport, ...]:
    _require(
        FULL_SHA.fullmatch(expected_commit) is not None,
        "expected commit must be a full lowercase Git SHA",
    )
    _require(
        evidence_directory.exists() and evidence_directory.is_dir(),
        "evidence directory does not exist",
    )
    _require(not evidence_directory.is_symlink(), "evidence directory symlinks are forbidden")
    directory = evidence_directory.resolve()
    _require(directory.name == expected_run_id, "evidence directory does not match expected run id")
    started_at = _run_started_at(expected_run_id, expected_commit)
    validated: list[ValidatedReport] = []
    for name in EXPECTED_REPORTS:
        path = _safe_child(directory, name)
        payload = _load_json(path)
        _walk_privacy(payload)
        if name.endswith("09-primitives.json"):
            _validate_primitives(payload, name=name, started_at=started_at)
            stage, profile = "09-primitives", "discord-live-targeted-primitives"
        elif name.endswith("09-full-chain.json"):
            _validate_full_chain(payload, name=name, started_at=started_at)
            stage, profile = "09-full-chain", "discord-live-complete-runtime-chain"
        else:
            stage = name.removeprefix("discord-live-").removesuffix(".json")
            _validate_common(payload, stage=stage, name=name, started_at=started_at)
            if stage != "02":
                _validate_counters(stage, payload, name=name)
            else:
                details = payload.get("details")
                _require(
                    details
                    == {
                        "oauth_profiles": (
                            "one sandbox account; actual A/B permission states recorded"
                        ),
                        "guilds": "Guild A and Guild B",
                        "cleanup": (
                            "bot reinstalled on both sandboxes; temporary OAuth grants revoked"
                        ),
                        "limitation": (
                            "single-account live profile explicitly required by the user"
                        ),
                    },
                    f"Stage 02 Guild A/B details are incomplete or unexpected in {name}",
                )
            profile = EXPECTED_PROFILES[stage]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        validated.append(ValidatedReport(name, stage, profile, str(payload["status"]), digest))
    return tuple(validated)


def build_aggregate(
    *, commit: str, run_id: str, reports: tuple[ValidatedReport, ...]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "requirement": REQUIREMENT_ID,
        "result": "PASS",
        "commit": commit,
        "run_id": run_id,
        "evidence_directory": f"stage-10/{run_id}",
        "generated_at": datetime.now(UTC).isoformat(),
        "guilds_verified": 2,
        "reports": [
            {
                "name": report.name,
                "stage": report.stage,
                "profile": report.profile,
                "status": report.status,
                "sha256": report.sha256,
            }
            for report in reports
        ],
        "secrets_recorded": False,
        "discord_identifiers_recorded": False,
    }


def promote(evidence_directory: Path, *, expected_commit: str, expected_run_id: str) -> Path:
    directory = evidence_directory.resolve()
    reports = validate_live_reports(
        directory, expected_commit=expected_commit, expected_run_id=expected_run_id
    )
    output = _safe_child(directory, AGGREGATE_NAME)
    payload = build_aggregate(commit=expected_commit, run_id=expected_run_id, reports=reports)
    temporary = directory / f".{AGGREGATE_NAME}.tmp"
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return output


def validate_aggregate_proof(
    path: Path, *, expected_commit: str, expected_run_id: str
) -> ValidatedClosure:
    _require(path.name == AGGREGATE_NAME, "unexpected aggregate proof filename")
    _require(not path.is_symlink(), "aggregate proof symlinks are forbidden")
    directory = path.resolve().parent
    _require(directory.name == expected_run_id, "aggregate proof is from another run")
    payload = _load_json(path)
    _walk_privacy(payload)
    expected_keys = {
        "schema_version",
        "requirement",
        "result",
        "commit",
        "run_id",
        "evidence_directory",
        "generated_at",
        "guilds_verified",
        "reports",
        "secrets_recorded",
        "discord_identifiers_recorded",
    }
    _require(set(payload) == expected_keys, "aggregate proof schema is invalid")
    _require(
        payload["schema_version"] == 1 and payload["requirement"] == REQUIREMENT_ID,
        "aggregate proof contract is invalid",
    )
    _require(payload["result"] == "PASS", "aggregate proof is not green")
    _require(payload["commit"] == expected_commit, "aggregate proof commit is stale or unexpected")
    _require(payload["run_id"] == expected_run_id, "aggregate proof run id is unexpected")
    _require(
        payload["evidence_directory"] == f"stage-10/{expected_run_id}",
        "aggregate evidence directory is unexpected",
    )
    _require(payload["guilds_verified"] == 2, "aggregate does not prove two Guilds")
    _require(payload["secrets_recorded"] is False, "aggregate declares a recorded secret")
    _require(
        payload["discord_identifiers_recorded"] is False,
        "aggregate declares raw Discord identifiers",
    )
    _validate_timestamp(
        payload, name=path.name, started_at=_run_started_at(expected_run_id, expected_commit)
    )
    reports = validate_live_reports(
        directory, expected_commit=expected_commit, expected_run_id=expected_run_id
    )
    entries = payload["reports"]
    _require(
        isinstance(entries, list) and len(entries) == len(reports),
        "aggregate report list is incomplete",
    )
    expected_entries = [
        {
            "name": report.name,
            "stage": report.stage,
            "profile": report.profile,
            "status": report.status,
            "sha256": report.sha256,
        }
        for report in reports
    ]
    _require(entries == expected_entries, "aggregate report metadata or hashes are corrupt")
    return ValidatedClosure(expected_commit, expected_run_id, reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-run-id", required=True)
    arguments = parser.parse_args(argv)
    try:
        output = promote(
            arguments.evidence_directory,
            expected_commit=arguments.expected_commit,
            expected_run_id=arguments.expected_run_id,
        )
    except PromotionError as exc:
        print(f"Stage 10 Discord live evidence promotion: FAIL -- {exc}")
        return 1
    print(f"Stage 10 Discord live evidence promotion: PASS -- {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
