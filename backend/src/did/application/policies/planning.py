from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from did.application.policies.service import DRIFT_EXCEPTION_TAG_PREFIX, PolicyService
from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.policies import Policy, PolicyLifecycleError, PolicyLifecycleState, PolicyScopeType
from did.domain.read_model import GuildSnapshot, MemberSnapshot
from did.domain.read_model.models import ChannelType
from did.permissions import DEFAULT_PERMISSION_REGISTRY, PermissionEvaluator
from did.permissions.views import SimplePermissionConcept, compile_simple_permissions
from did.planning.canonical import canonical_hash
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    PlanOriginType,
    PlanProvenance,
    PlanState,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)
from did.planning.preflight import PolicyPreflightResult, PreflightResult
from did.policies.drift import discord_currently_satisfies, real_state_resolution
from did.policies.resolver import PolicyResolution, PolicyResolutionOutcome

MAX_POLICY_PREVIEW_CONTEXTS = 2_000


class ImpactAccuracy(StrEnum):
    EXACT = "EXACT"
    BOUNDED = "BOUNDED"
    INCOMPLETE = "INCOMPLETE"


class AccessChange(StrEnum):
    UNCHANGED = "UNCHANGED"
    GAINED = "GAINED"
    LOST = "LOST"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    RESOLUTION_CHANGED = "RESOLUTION_CHANGED"


class PreviewSimulation(StrEnum):
    """What the proposed side of a preview simulates for the target Policy.

    ACTIVATE (the historical, only behaviour before REQ-AP-INH-003): the
    target Policy is forced ACTIVE in the proposed policy set, simulating
    what happens once a DRAFT is activated.

    DISABLE (REQ-AP-INH-003 "reapply category policy"): the target Policy is
    entirely removed from the proposed policy set, simulating what happens
    once an already-ACTIVE Policy is disabled -- typically revealing the
    inherited category policy a channel-level exception was overriding.
    """

    ACTIVATE = "ACTIVATE"
    DISABLE = "DISABLE"
    REASSERT = "REASSERT"
    """REQ-AP-LOCK-*: the target Policy's own lifecycle is untouched (it stays
    ACTIVE throughout); only Discord's drifted state is being corrected back
    to what this already-ACTIVE Policy already says. ``evaluated_policies``
    is the loaded policy set completely unmodified -- no add, no remove."""


@dataclass(frozen=True, slots=True)
class PolicyPreviewTarget:
    subject_id: int
    scope_type: PolicyScopeType
    scope_id: str | None
    requested_access: str


@dataclass(frozen=True, slots=True)
class PolicyPreviewEntry:
    target: PolicyPreviewTarget
    current: PolicyResolution
    proposed: PolicyResolution
    access_change: AccessChange
    gained_contributions: tuple[str, ...]
    lost_contributions: tuple[str, ...]
    conflicts_created: tuple[str, ...]
    conflicts_resolved: tuple[str, ...]
    diagnostics: tuple[str, ...]
    warnings: tuple[str, ...]
    remediations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyImpact:
    accuracy: ImpactAccuracy
    candidate_contexts: int
    evaluated_contexts: int
    affected_resources: int
    affected_roles: int
    affected_members: int
    access_gains: int
    access_losses: int
    conflicts: int
    impossible_or_incomplete_targets: int
    lower_bound_only: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyPreview:
    policy_id: UUID
    policy_revision: int
    lifecycle_state: PolicyLifecycleState
    scope_type: PolicyScopeType
    scope_id: str | None
    entries: tuple[PolicyPreviewEntry, ...]
    impact: PolicyImpact
    freshness: FreshnessState
    coverage: CoverageMode
    source_versions: tuple[str, ...]
    warnings: tuple[str, ...]
    persisted: bool = False
    discord_mutations: int = 0


def drift_fingerprint(preview: PolicyPreview) -> str:
    """Stable identity for the exact observed Discord/Policy delta.

    Policy revision is deliberately excluded: accepting the exception is an
    audited annotation that increments that revision but does not itself
    change the desired rule or the observed Discord state.
    """

    material = {
        "source_versions": list(preview.source_versions),
        "entries": [
            {
                "subject_id": str(entry.target.subject_id),
                "scope_type": entry.target.scope_type.value,
                "scope_id": entry.target.scope_id,
                "access": entry.target.requested_access,
                "change": entry.access_change.value,
                "current": entry.current.outcome.value,
                "proposed": entry.proposed.outcome.value,
            }
            for entry in preview.entries
            if entry.access_change is not AccessChange.UNCHANGED
        ],
    }
    return canonical_hash(material)


class PolicyPlanningService:
    """Preview and compile a DRAFT Policy through the existing Plan Engine."""

    def __init__(self, *, policies: PolicyService, planning: Any = None, read_models: Any) -> None:
        self._policies = policies
        self._planning = planning
        self._read_models = read_models

    def bind_planning(self, planning: Any) -> None:
        if self._planning is not None:
            raise RuntimeError("Policy planning is already bound")
        self._planning = planning

    async def preview(self, *, guild_id: int, policy_id: UUID, actor_user_id: int) -> PolicyPreview:
        draft = await self._policies.get(guild_id, policy_id)
        if draft.lifecycle_state is not PolicyLifecycleState.DRAFT:
            raise PolicyLifecycleError("only a DRAFT Policy can be previewed")
        policies, seed_pair, groups, cached_members = await self._load(
            guild_id=guild_id, actor_user_id=actor_user_id
        )
        guild, seed_member = seed_pair
        return await self._preview_loaded(
            draft=draft,
            policies=policies,
            guild=guild,
            seed_member=seed_member,
            groups=groups,
            cached_members=cached_members,
        )

    async def preview_many(
        self, *, guild_id: int, policy_ids: Sequence[UUID], actor_user_id: int
    ) -> tuple[PolicyPreview, ...]:
        """Preview a bounded batch after one shared Policy/read-model load."""

        policies, seed_pair, groups, cached_members = await self._load(
            guild_id=guild_id, actor_user_id=actor_user_id
        )
        guild, seed_member = seed_pair
        by_id = {policy.policy_id: policy for policy in policies}
        drafts: list[Policy] = []
        for policy_id in policy_ids:
            draft = by_id.get(policy_id)
            if draft is None:
                # Preserve the repository's canonical not-found behavior.
                draft = await self._policies.get(guild_id, policy_id)
            if draft.lifecycle_state is not PolicyLifecycleState.DRAFT:
                raise PolicyLifecycleError("only a DRAFT Policy can be previewed")
            drafts.append(draft)
        return tuple(
            [
                await self._preview_loaded(
                    draft=draft,
                    policies=policies,
                    guild=guild,
                    seed_member=seed_member,
                    groups=groups,
                    cached_members=cached_members,
                )
                for draft in drafts
            ]
        )

    async def preview_disable(
        self, *, guild_id: int, policy_id: UUID, actor_user_id: int
    ) -> PolicyPreview:
        """REQ-AP-INH-003: preview disabling an ACTIVE Policy (e.g. a channel
        exception) so the admin sees exactly what falls back to an inherited
        category policy before anything is changed. Reuses the same
        candidate/resolve/diff machinery as the DRAFT preview -- only the
        proposed policy set differs (this Policy removed, not forced ACTIVE)."""

        current_policy = await self._policies.get(guild_id, policy_id)
        if current_policy.lifecycle_state is not PolicyLifecycleState.ACTIVE:
            raise PolicyLifecycleError("only an ACTIVE Policy can be previewed for disable")
        policies, seed_pair, groups, cached_members = await self._load(
            guild_id=guild_id, actor_user_id=actor_user_id
        )
        guild, seed_member = seed_pair
        return await self._preview_loaded(
            draft=current_policy,
            policies=policies,
            guild=guild,
            seed_member=seed_member,
            groups=groups,
            cached_members=cached_members,
            simulate=PreviewSimulation.DISABLE,
        )

    async def _preview_loaded(
        self,
        *,
        draft: Policy,
        policies: tuple[Policy, ...],
        guild: GuildSnapshot,
        seed_member: MemberSnapshot,
        groups: list[dict[str, Any]],
        cached_members: tuple[MemberSnapshot, ...],
        simulate: PreviewSimulation = PreviewSimulation.ACTIVATE,
    ) -> PolicyPreview:
        members = await self._candidate_members(draft, cached_members, seed_member)
        resources = self._candidate_resources(draft, guild, groups)
        accesses = tuple(sorted({str(effect["access"]) for effect in draft.effects}))
        candidate_contexts = len(members) * len(resources) * len(accesses)
        contexts = [
            (member, scope_type, scope_id, access)
            for member in members
            for scope_type, scope_id in resources
            for access in accesses
        ]
        truncated = len(contexts) > MAX_POLICY_PREVIEW_CONTEXTS
        contexts = contexts[:MAX_POLICY_PREVIEW_CONTEXTS]
        if simulate is PreviewSimulation.DISABLE:
            proposed_policies = tuple(
                policy for policy in policies if policy.policy_id != draft.policy_id
            )
        else:
            proposed_policies = tuple(
                replace(policy, lifecycle_state=PolicyLifecycleState.ACTIVE)
                if policy.policy_id == draft.policy_id
                else policy
                for policy in policies
            )
            if not any(policy.policy_id == draft.policy_id for policy in policies):
                proposed_policies += (replace(draft, lifecycle_state=PolicyLifecycleState.ACTIVE),)
        entries = tuple(
            self._entry(
                current=self._policies.resolve_loaded(
                    policies=policies,
                    guild=guild,
                    member=member,
                    logical_groups=groups,
                    target_scope_type=scope_type,
                    target_scope_id=scope_id,
                    requested_access=access,
                ),
                proposed=self._policies.resolve_loaded(
                    policies=proposed_policies,
                    guild=guild,
                    member=member,
                    logical_groups=groups,
                    target_scope_type=scope_type,
                    target_scope_id=scope_id,
                    requested_access=access,
                ),
            )
            for member, scope_type, scope_id, access in contexts
        )
        requires_complete_member_inventory = draft.scope_type not in {
            PolicyScopeType.MEMBER,
            PolicyScopeType.BOT,
        }
        complete_members = (
            not requires_complete_member_inventory or guild.coverage.members_complete
        ) and all(
            member.roles_complete
            and member.freshness.state not in {FreshnessState.STALE, FreshnessState.UNKNOWN}
            for member in members
        )
        if guild.coverage.mode is not CoverageMode.FULL or not complete_members:
            accuracy = ImpactAccuracy.INCOMPLETE
        elif truncated:
            accuracy = ImpactAccuracy.BOUNDED
        else:
            accuracy = ImpactAccuracy.EXACT
        changed = tuple(
            entry for entry in entries if entry.access_change is not AccessChange.UNCHANGED
        )
        impacted_member_ids = {entry.target.subject_id for entry in changed}
        impacted_resources = {(entry.target.scope_type, entry.target.scope_id) for entry in changed}
        member_by_id = {member.user_id: member for member in members}
        role_ids = {
            role_id
            for member_id in impacted_member_ids
            for role_id in member_by_id[member_id].role_ids
            if member_id in member_by_id
        }
        if draft.scope_type is PolicyScopeType.ROLE and draft.scope_id is not None:
            role_ids.add(int(draft.scope_id))
        impossible = sum(
            entry.proposed.outcome
            in {PolicyResolutionOutcome.BLOCKED, PolicyResolutionOutcome.UNKNOWN}
            for entry in entries
        )
        diagnostics = set()
        if requires_complete_member_inventory and not guild.coverage.members_complete:
            diagnostics.add("policy.preview.member_coverage_incomplete")
        if guild.coverage.mode is not CoverageMode.FULL:
            diagnostics.add("policy.preview.resource_coverage_incomplete")
        if truncated:
            diagnostics.add("policy.preview.context_limit_reached")
        diagnostics.update(reason for entry in entries for reason in entry.diagnostics)
        impact = PolicyImpact(
            accuracy=accuracy,
            candidate_contexts=candidate_contexts,
            evaluated_contexts=len(entries),
            affected_resources=len(impacted_resources),
            affected_roles=len(role_ids),
            affected_members=len(impacted_member_ids),
            access_gains=sum(entry.access_change is AccessChange.GAINED for entry in entries),
            access_losses=sum(entry.access_change is AccessChange.LOST for entry in entries),
            conflicts=sum(len(entry.proposed.conflicts) for entry in entries),
            impossible_or_incomplete_targets=impossible,
            lower_bound_only=accuracy is not ImpactAccuracy.EXACT,
            diagnostics=tuple(sorted(diagnostics)),
        )
        warnings = set(impact.diagnostics)
        warnings.update(warning for entry in entries for warning in entry.warnings)
        return PolicyPreview(
            policy_id=draft.policy_id,
            policy_revision=draft.revision,
            lifecycle_state=draft.lifecycle_state,
            scope_type=draft.scope_type,
            scope_id=draft.scope_id,
            entries=entries,
            impact=impact,
            freshness=guild.freshness.state,
            coverage=guild.coverage.mode,
            source_versions=guild.source_versions,
            warnings=tuple(sorted(warnings)),
        )

    async def create_plan(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_user_id: int,
        idempotency_key: str,
        correlation_id: UUID,
        expected_revision: int,
    ) -> tuple[PolicyPreview, dict[str, Any], bool, PreflightResult]:
        if self._planning is None:
            raise RuntimeError("canonical PlanningService is not configured")
        preview = await self.preview(
            guild_id=guild_id, policy_id=policy_id, actor_user_id=actor_user_id
        )
        guild, _ = await self._read_models.guild_snapshot(guild_id, actor_user_id)
        return await self._create_plan_from_preview(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            preview=preview,
            guild=guild,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            expected_revision=expected_revision,
            simulate=PreviewSimulation.ACTIVATE,
        )

    async def create_disable_plan(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_user_id: int,
        idempotency_key: str,
        correlation_id: UUID,
        expected_revision: int,
        temporary_access: bool = False,
    ) -> tuple[PolicyPreview, dict[str, Any], bool, PreflightResult]:
        """REQ-AP-INH-003: compile preview_disable()'s simulation to the same
        canonical DSG/Plan/preflight pipeline as any other Policy Plan --
        disabling the Policy itself only happens afterwards, gated on this
        exact Plan being preflight-validated (see PolicyService.disable)."""

        if self._planning is None:
            raise RuntimeError("canonical PlanningService is not configured")
        preview = await self.preview_disable(
            guild_id=guild_id, policy_id=policy_id, actor_user_id=actor_user_id
        )
        guild, _ = await self._read_models.guild_snapshot(guild_id, actor_user_id)
        return await self._create_plan_from_preview(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            preview=preview,
            guild=guild,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            expected_revision=expected_revision,
            simulate=PreviewSimulation.DISABLE,
            temporary_access=temporary_access,
        )

    async def detect_drift(
        self, *, guild_id: int, policy_id: UUID, actor_user_id: int
    ) -> PolicyPreview:
        """REQ-AP-LOCK-002/003/006: compare what this ACTIVE Policy says
        Discord should grant against what Discord's cached read model
        actually has right now, reusing the same ``PermissionEvaluator`` the
        Access Matrix already uses -- never a second permission engine.
        Works identically for locked and unlocked Policies; the caller (a
        periodic sweep for locked Policies, or a manual "check" for
        unlocked ones) decides what to do with a drifted result.
        """
        policy = await self._policies.get(guild_id, policy_id)
        if policy.lifecycle_state is not PolicyLifecycleState.ACTIVE:
            raise PolicyLifecycleError("only an ACTIVE Policy can be checked for drift")
        policies, seed_pair, groups, cached_members = await self._load(
            guild_id=guild_id, actor_user_id=actor_user_id
        )
        guild, seed_member = seed_pair
        members = await self._candidate_members(policy, cached_members, seed_member)
        resources = self._candidate_resources(policy, guild, groups)
        accesses = tuple(sorted({str(effect["access"]) for effect in policy.effects}))
        candidate_contexts = len(members) * len(resources) * len(accesses)
        contexts = [
            (member, scope_type, scope_id, access)
            for member in members
            for scope_type, scope_id in resources
            for access in accesses
        ]
        truncated = len(contexts) > MAX_POLICY_PREVIEW_CONTEXTS
        contexts = contexts[:MAX_POLICY_PREVIEW_CONTEXTS]
        requires_complete_member_inventory = policy.scope_type not in {
            PolicyScopeType.MEMBER,
            PolicyScopeType.BOT,
        }
        incomplete_member_inventory = requires_complete_member_inventory and not (
            guild.coverage.members_complete
            and all(
                member.roles_complete
                and member.freshness.state not in {FreshnessState.STALE, FreshnessState.UNKNOWN}
                for member in members
            )
        )
        evaluator = PermissionEvaluator()
        entries = []
        any_unknown = False
        for member, scope_type, scope_id, access in contexts:
            proposed = self._policies.resolve_loaded(
                policies=policies,
                guild=guild,
                member=member,
                logical_groups=groups,
                target_scope_type=scope_type,
                target_scope_id=scope_id,
                requested_access=access,
            )
            channel = guild.channel(int(scope_id)) if scope_id is not None else None
            if channel is None or proposed.outcome not in {
                PolicyResolutionOutcome.CAN,
                PolicyResolutionOutcome.CANNOT,
            }:
                # No concrete Discord resource to compare against, or the
                # Policy itself is already BLOCKED/UNKNOWN -- fail closed
                # rather than guessing at a drift verdict.
                any_unknown = True
                current = real_state_resolution(proposed, satisfied=False, unknown=True)
            else:
                satisfied, unknown = discord_currently_satisfies(
                    proposed, guild=guild, member=member, channel=channel, evaluator=evaluator
                )
                any_unknown = any_unknown or unknown
                current = real_state_resolution(proposed, satisfied=satisfied, unknown=unknown)
            entries.append(self._entry(current=current, proposed=proposed))
        changed = tuple(
            entry for entry in entries if entry.access_change is not AccessChange.UNCHANGED
        )
        if (
            guild.coverage.mode is not CoverageMode.FULL
            or any_unknown
            or incomplete_member_inventory
        ):
            accuracy = ImpactAccuracy.INCOMPLETE
        elif truncated:
            accuracy = ImpactAccuracy.BOUNDED
        else:
            accuracy = ImpactAccuracy.EXACT
        diagnostics = set()
        if incomplete_member_inventory:
            diagnostics.add("policy.drift.member_coverage_incomplete")
        if truncated:
            diagnostics.add("policy.drift.context_limit_reached")
        diagnostics.update(reason for entry in entries for reason in entry.diagnostics)
        impact = PolicyImpact(
            accuracy=accuracy,
            candidate_contexts=candidate_contexts,
            evaluated_contexts=len(entries),
            affected_resources=len(
                {(entry.target.scope_type, entry.target.scope_id) for entry in changed}
            ),
            affected_roles=0,
            affected_members=len({entry.target.subject_id for entry in changed}),
            access_gains=sum(entry.access_change is AccessChange.GAINED for entry in entries),
            access_losses=sum(entry.access_change is AccessChange.LOST for entry in entries),
            conflicts=sum(len(entry.proposed.conflicts) for entry in entries),
            impossible_or_incomplete_targets=sum(
                entry.current.outcome is PolicyResolutionOutcome.UNKNOWN for entry in entries
            ),
            lower_bound_only=accuracy is not ImpactAccuracy.EXACT,
            diagnostics=tuple(sorted(diagnostics)),
        )
        warnings = set(impact.diagnostics)
        warnings.update(warning for entry in entries for warning in entry.warnings)
        preview = PolicyPreview(
            policy_id=policy.policy_id,
            policy_revision=policy.revision,
            lifecycle_state=policy.lifecycle_state,
            scope_type=policy.scope_type,
            scope_id=policy.scope_id,
            entries=tuple(entries),
            impact=impact,
            freshness=guild.freshness.state,
            coverage=guild.coverage.mode,
            source_versions=guild.source_versions,
            warnings=tuple(sorted(warnings)),
        )
        accepted_tag = f"{DRIFT_EXCEPTION_TAG_PREFIX}{drift_fingerprint(preview)[:40]}"
        raw_tags = policy.metadata.get("tags", ())
        tags = tuple(str(value) for value in raw_tags) if isinstance(raw_tags, list | tuple) else ()
        if changed and accepted_tag in tags:
            preview = replace(
                preview,
                warnings=tuple(sorted({*preview.warnings, "policy.drift.exception_accepted"})),
            )
        return preview

    async def create_drift_plan(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_user_id: int,
        idempotency_key: str,
        correlation_id: UUID,
        expected_revision: int,
        auto_reconcile: bool = False,
    ) -> tuple[PolicyPreview, dict[str, Any], bool, PreflightResult]:
        """REQ-AP-LOCK-*: compile a real drift check into the same canonical
        DSG/Plan/preflight pipeline as any other Policy Plan. The target
        Policy's own lifecycle never changes here (see
        ``PreviewSimulation.REASSERT``) -- only Discord's drifted overwrites
        do, once this Plan is confirmed and applied."""

        if self._planning is None:
            raise RuntimeError("canonical PlanningService is not configured")
        preview = await self.detect_drift(
            guild_id=guild_id, policy_id=policy_id, actor_user_id=actor_user_id
        )
        guild, _ = await self._read_models.guild_snapshot(guild_id, actor_user_id)
        return await self._create_plan_from_preview(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            preview=preview,
            guild=guild,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            expected_revision=expected_revision,
            simulate=PreviewSimulation.REASSERT,
            auto_reconcile=auto_reconcile,
        )

    async def create_plans(
        self,
        *,
        guild_id: int,
        items: Sequence[tuple[UUID, int, str]],
        actor_user_id: int,
        correlation_id: UUID,
    ) -> tuple[tuple[PolicyPreview, dict[str, Any], bool, PreflightResult], ...]:
        """Compile one canonical Plan per Policy without N preview HTTP/read-model loads."""

        previews = await self.preview_many(
            guild_id=guild_id,
            policy_ids=tuple(policy_id for policy_id, _, _ in items),
            actor_user_id=actor_user_id,
        )
        guild, _ = await self._read_models.guild_snapshot(guild_id, actor_user_id)
        results = []
        for preview, (_, expected_revision, idempotency_key) in zip(previews, items, strict=True):
            results.append(
                await self._create_plan_from_preview(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    preview=preview,
                    guild=guild,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    expected_revision=expected_revision,
                )
            )
        return tuple(results)

    async def _create_plan_from_preview(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        preview: PolicyPreview,
        guild: GuildSnapshot,
        idempotency_key: str,
        correlation_id: UUID,
        expected_revision: int,
        simulate: PreviewSimulation = PreviewSimulation.ACTIVATE,
        auto_reconcile: bool = False,
        temporary_access: bool = False,
    ) -> tuple[PolicyPreview, dict[str, Any], bool, PreflightResult]:
        if preview.policy_revision != expected_revision:
            raise PolicyLifecycleError("Policy revision changed before Plan creation")
        graph = self._compile_graph(guild, preview)
        context_rows = tuple(
            {
                "subject_id": str(entry.target.subject_id),
                "target_scope_type": entry.target.scope_type.value,
                "target_scope_id": entry.target.scope_id,
                "requested_access": entry.target.requested_access,
                "expected_outcome": entry.proposed.outcome.value,
            }
            for entry in preview.entries
        )
        metadata: dict[str, Any] = {
            "scope_type": preview.scope_type.value,
            "scope_id": preview.scope_id,
            "preview_accuracy": preview.impact.accuracy.value,
            "preview_contexts": list(context_rows),
            "source_versions": list(preview.source_versions),
            "simulate": simulate.value,
            "auto_reconcile": auto_reconcile,
            "temporary_access": temporary_access,
        }
        metadata["preview_fingerprint"] = canonical_hash(metadata)
        provenance = PlanProvenance.policy(
            policy_id=preview.policy_id,
            policy_revision=expected_revision,
            metadata=metadata,
        )
        plan, created = await self._planning.create(
            graph=graph,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            provenance=provenance,
        )
        if str(plan["status"]) == PlanState.DRAFT.value:
            plan, preflight = await self._planning.validate(
                guild_id=guild_id,
                plan_id=UUID(str(plan["id"])),
                actor_user_id=actor_user_id,
                expected_version=int(plan["state_version"]),
                correlation_id=correlation_id,
                actor_authorization_fresh=True,
            )
        else:
            preflight = await self._planning.recheck(
                guild_id=guild_id,
                plan_id=UUID(str(plan["id"])),
                actor_authorization_fresh=True,
                require_policy_active=False,
            )
        return preview, plan, created, preflight

    async def evaluate_plan(
        self,
        *,
        guild_id: int,
        provenance: PlanProvenance,
        require_active: bool,
    ) -> PolicyPreflightResult:
        if provenance.origin_type is not PlanOriginType.POLICY:
            return PolicyPreflightResult(True)
        assert provenance.policy_id is not None and provenance.policy_revision is not None
        metadata = provenance.metadata_map()
        simulate = PreviewSimulation(metadata.get("simulate", PreviewSimulation.ACTIVATE.value))
        errors: set[str] = set()
        warnings: set[str] = set()
        if metadata.get("preview_accuracy") != ImpactAccuracy.EXACT.value:
            errors.add("preflight.policy_preview_not_exact")
        source = await self._policies.get_revision(
            guild_id, provenance.policy_id, provenance.policy_revision
        )
        current = await self._policies.get(guild_id, provenance.policy_id)
        if metadata.get("auto_reconcile") is True and not current.locked:
            # A system-initiated REASSERT is authorized by the administrator's
            # durable Policy lock, not by a synthetic Discord user.  Recheck
            # that opt-in at the last possible preflight boundary.
            errors.add("preflight.policy_not_locked")
        if not self._same_definition(source, current):
            errors.add("preflight.policy_revision_changed")
        if simulate is PreviewSimulation.DISABLE:
            # REQ-AP-INH-003: the terminal state a disable-Plan expects at
            # apply-time is DISABLED, the mirror image of an activate-Plan
            # expecting ACTIVE -- disable() already flipped the lifecycle
            # before this Plan is ever applied.
            if require_active and current.lifecycle_state not in {
                PolicyLifecycleState.DISABLED,
                PolicyLifecycleState.RETIRED,
            }:
                errors.add("preflight.policy_not_disabled")
            if not require_active and current.lifecycle_state not in {
                PolicyLifecycleState.ACTIVE,
                PolicyLifecycleState.DISABLED,
            }:
                errors.add("preflight.policy_not_eligible")
        else:
            if require_active and current.lifecycle_state is not PolicyLifecycleState.ACTIVE:
                errors.add("preflight.policy_not_active")
            if not require_active and current.lifecycle_state not in {
                PolicyLifecycleState.DRAFT,
                PolicyLifecycleState.ACTIVE,
            }:
                errors.add("preflight.policy_not_eligible")
        raw_contexts = metadata.get("preview_contexts", [])
        if not isinstance(raw_contexts, list) or len(raw_contexts) > MAX_POLICY_PREVIEW_CONTEXTS:
            return PolicyPreflightResult(False, ("preflight.policy_context_invalid",))
        subject_ids = tuple(sorted({int(item["subject_id"]) for item in raw_contexts}))
        if not subject_ids:
            return PolicyPreflightResult(not errors, tuple(sorted(errors)))
        policies, seed_pair, groups, _ = await self._load(
            guild_id=guild_id, actor_user_id=subject_ids[0]
        )
        guild, _ = seed_pair
        members = await self._read_models.member_snapshots(guild_id, subject_ids)
        members_by_id = {member.user_id: member for member in members}
        if simulate is PreviewSimulation.DISABLE:
            evaluated_policies = tuple(
                policy for policy in policies if policy.policy_id != provenance.policy_id
            )
        elif simulate is PreviewSimulation.REASSERT:
            evaluated_policies = policies
        else:
            evaluated_policies = (
                *(policy for policy in policies if policy.policy_id != provenance.policy_id),
                replace(source, lifecycle_state=PolicyLifecycleState.ACTIVE),
            )
        explanations: list[dict[str, Any]] = []
        for item in raw_contexts:
            member = members_by_id.get(int(item["subject_id"]))
            if member is None:
                errors.add("preflight.policy_subject_unavailable")
                continue
            resolution = self._policies.resolve_loaded(
                policies=evaluated_policies,
                guild=guild,
                member=member,
                logical_groups=groups,
                target_scope_type=PolicyScopeType(str(item["target_scope_type"])),
                target_scope_id=item.get("target_scope_id"),
                requested_access=str(item["requested_access"]),
            )
            explanations.append(self._resolution_json(resolution))
            if resolution.outcome is PolicyResolutionOutcome.BLOCKED:
                errors.add("preflight.policy_blocked")
            elif resolution.outcome is PolicyResolutionOutcome.UNKNOWN:
                errors.add("preflight.policy_unknown")
            elif resolution.outcome.value != str(item["expected_outcome"]):
                errors.add("preflight.policy_resolution_changed")
            warnings.update(resolution.warnings)
        return PolicyPreflightResult(
            not errors,
            tuple(sorted(errors)),
            tuple(sorted(warnings)),
            tuple(explanations),
        )

    async def _load(
        self, *, guild_id: int, actor_user_id: int
    ) -> tuple[
        tuple[Policy, ...],
        tuple[GuildSnapshot, MemberSnapshot],
        list[dict[str, Any]],
        tuple[MemberSnapshot, ...],
    ]:
        import asyncio

        policies, seed_pair, groups, members = await asyncio.gather(
            self._policies.list(guild_id),
            self._read_models.guild_snapshot(guild_id, actor_user_id),
            self._read_models.list_logical_groups(guild_id),
            self._read_models.cached_member_snapshots(guild_id),
        )
        return (
            policies,
            cast(tuple[GuildSnapshot, MemberSnapshot], seed_pair),
            cast(list[dict[str, Any]], groups),
            cast(tuple[MemberSnapshot, ...], members),
        )

    async def _candidate_members(
        self,
        draft: Policy,
        cached: tuple[MemberSnapshot, ...],
        seed: MemberSnapshot,
    ) -> tuple[MemberSnapshot, ...]:
        raw_bot_ids = tuple(
            condition.get("bot_user_ids")
            for condition in draft.conditions
            if condition.get("kind") == "BOT_MATCH"
        )
        bot_ids = tuple(
            int(value)
            for values in raw_bot_ids
            if isinstance(values, list | tuple)
            for value in values
        )
        if bot_ids:
            members = await self._read_models.member_snapshots(draft.guild_id, bot_ids)
            return cast(tuple[MemberSnapshot, ...], tuple(members))
        if draft.scope_type in {PolicyScopeType.MEMBER, PolicyScopeType.BOT}:
            assert draft.scope_id is not None
            members = await self._read_models.member_snapshots(
                draft.guild_id, (int(draft.scope_id),)
            )
            return cast(tuple[MemberSnapshot, ...], tuple(members))
        if draft.scope_type is PolicyScopeType.ROLE:
            assert draft.scope_id is not None
            matching = tuple(member for member in cached if int(draft.scope_id) in member.role_ids)
            return matching or ((seed,) if not seed.roles_complete else ())
        return cached or (seed,)

    @staticmethod
    def _candidate_resources(
        draft: Policy, guild: GuildSnapshot, groups: list[dict[str, Any]]
    ) -> tuple[tuple[PolicyScopeType, str | None], ...]:
        channels = tuple(channel for channel in guild.channels if not channel.is_thread)
        selected_ids: set[int] = set()
        if draft.scope_type is PolicyScopeType.CHANNEL:
            assert draft.scope_id is not None
            selected_ids.add(int(draft.scope_id))
        elif draft.scope_type is PolicyScopeType.CATEGORY:
            assert draft.scope_id is not None
            category_id = int(draft.scope_id)
            selected_ids.add(category_id)
            selected_ids.update(
                channel.channel_id for channel in channels if channel.parent_id == category_id
            )
        elif draft.scope_type is PolicyScopeType.LOGICAL_GROUP:
            group = next((row for row in groups if str(row["id"]) == draft.scope_id), None)
            if group is not None:
                for resource in group.get("resources", ()):
                    channel_id = resource.get("discord_channel_id")
                    if channel_id is None:
                        continue
                    selected_ids.add(int(channel_id))
                    if str(resource.get("resource_type")) == "CATEGORY":
                        selected_ids.update(
                            channel.channel_id
                            for channel in channels
                            if channel.parent_id == int(channel_id)
                        )
        else:
            selected_ids.update(channel.channel_id for channel in channels)
        resources = []
        for channel_id in sorted(selected_ids):
            channel = guild.channel(channel_id)
            scope_type = (
                PolicyScopeType.CATEGORY
                if channel is not None and channel.channel_type is ChannelType.GUILD_CATEGORY
                else PolicyScopeType.CHANNEL
            )
            resources.append((scope_type, str(channel_id)))
        if resources:
            return tuple(resources)
        if draft.scope_type in {PolicyScopeType.CHANNEL, PolicyScopeType.CATEGORY}:
            return ((draft.scope_type, draft.scope_id),)
        return ((PolicyScopeType.GUILD, None),)

    @staticmethod
    def _entry(*, current: PolicyResolution, proposed: PolicyResolution) -> PolicyPreviewEntry:
        current_keys = PolicyPlanningService._contribution_keys(current)
        proposed_keys = PolicyPlanningService._contribution_keys(proposed)
        current_conflicts = PolicyPlanningService._conflict_keys(current)
        proposed_conflicts = PolicyPlanningService._conflict_keys(proposed)
        if current.outcome == proposed.outcome and current_keys == proposed_keys:
            change = AccessChange.UNCHANGED
        elif proposed.outcome is PolicyResolutionOutcome.BLOCKED:
            change = AccessChange.BLOCKED
        elif proposed.outcome is PolicyResolutionOutcome.UNKNOWN:
            change = AccessChange.UNKNOWN
        elif (
            current.outcome is PolicyResolutionOutcome.CANNOT
            and proposed.outcome is PolicyResolutionOutcome.CAN
        ):
            change = AccessChange.GAINED
        elif (
            current.outcome is PolicyResolutionOutcome.CAN
            and proposed.outcome is PolicyResolutionOutcome.CANNOT
        ):
            change = AccessChange.LOST
        else:
            change = AccessChange.RESOLUTION_CHANGED
        diagnostics = tuple(
            sorted(set(current.incomplete_reasons) | set(proposed.incomplete_reasons))
        )
        warnings = tuple(sorted(set(current.warnings) | set(proposed.warnings)))
        return PolicyPreviewEntry(
            target=PolicyPreviewTarget(
                proposed.subject_id,
                proposed.target_scope_type,
                proposed.target_scope_id,
                proposed.decision.rsplit(":", 1)[-1],
            ),
            current=current,
            proposed=proposed,
            access_change=change,
            gained_contributions=tuple(sorted(proposed_keys - current_keys)),
            lost_contributions=tuple(sorted(current_keys - proposed_keys)),
            conflicts_created=tuple(sorted(proposed_conflicts - current_conflicts)),
            conflicts_resolved=tuple(sorted(current_conflicts - proposed_conflicts)),
            diagnostics=diagnostics,
            warnings=warnings,
            remediations=tuple(
                sorted(value for value in warnings if value.endswith("recommended"))
            ),
        )

    @staticmethod
    def _contribution_keys(resolution: PolicyResolution) -> set[str]:
        return {
            f"{item.policy_id}:{item.revision}:{item.effect_index}:{item.disposition}"
            for item in resolution.contributions
            if item.selected or item.disposition in {"CONFLICT_UNRESOLVED", "DATA_INCOMPLETE"}
        }

    @staticmethod
    def _conflict_keys(resolution: PolicyResolution) -> set[str]:
        return {
            ":".join(sorted(str(value) for value in conflict.policy_ids))
            + f":{conflict.outcome.value}"
            for conflict in resolution.conflicts
        }

    @staticmethod
    def _compile_graph(guild: GuildSnapshot, preview: PolicyPreview) -> DesiredStateGraph:
        desired: dict[tuple[int, int], tuple[int, int]] = {}
        for entry in preview.entries:
            if entry.access_change not in {AccessChange.GAINED, AccessChange.LOST}:
                continue
            if (
                entry.target.scope_type
                not in {
                    PolicyScopeType.CATEGORY,
                    PolicyScopeType.CHANNEL,
                }
                or entry.target.scope_id is None
            ):
                continue
            channel_id = int(entry.target.scope_id)
            channel = guild.channel(channel_id)
            if channel is None or channel.is_thread:
                continue
            key = (channel_id, entry.target.subject_id)
            if key not in desired:
                current = next(
                    (
                        overwrite
                        for overwrite in channel.overwrites
                        if overwrite.target_type == 1
                        and overwrite.target_id == entry.target.subject_id
                    ),
                    None,
                )
                desired[key] = (current.allow, current.deny) if current is not None else (0, 0)
            allow, deny = desired[key]
            bits = (
                int(entry.proposed.discord_allow_bits)
                if entry.proposed.outcome is PolicyResolutionOutcome.CAN
                else int(entry.proposed.discord_deny_bits)
            )
            if entry.proposed.outcome is PolicyResolutionOutcome.CAN:
                allow, deny = allow | bits, deny & ~bits
            else:
                allow, deny = allow & ~bits, deny | bits
            desired[key] = allow, deny
        nodes = tuple(
            DesiredNode.build(
                logical_key=(f"policy.{preview.policy_id}.overwrite.{channel_id}.{subject_id}"),
                resource_type=ResourceType.OVERWRITE,
                properties={"target_type": 1, "allow": str(allow), "deny": str(deny)},
                relations={
                    "channel": ResourceReference(ReferenceKind.DISCORD_ID, str(channel_id)),
                    "subject": ResourceReference(ReferenceKind.DISCORD_ID, str(subject_id)),
                },
            )
            for (channel_id, subject_id), (allow, deny) in sorted(desired.items())
        )
        return DesiredStateGraph(guild.guild_id, nodes)

    @staticmethod
    def _access_bits(access: str) -> int:
        concepts = {
            "VIEW": SimplePermissionConcept.VIEW,
            "WRITE": SimplePermissionConcept.WRITE,
            "MANAGE": SimplePermissionConcept.MANAGE,
        }
        if access in concepts:
            return compile_simple_permissions((concepts[access],)).allow_bits
        aliases = {
            "CONNECT": "CONNECT",
            "SPEAK": "SPEAK",
            "REACT": "ADD_REACTIONS",
            "MENTION_EVERYONE_HERE": "MENTION_EVERYONE",
            "PARTICIPATE_THREAD": "SEND_MESSAGES_IN_THREADS",
        }
        if access in aliases:
            return DEFAULT_PERMISSION_REGISTRY.value(aliases[access])
        from did.permissions.views import compile_policy_access

        return compile_policy_access(access).bits

    @staticmethod
    def _same_definition(source: Policy, current: Policy) -> bool:
        return (
            source.policy_id == current.policy_id
            and source.guild_id == current.guild_id
            and source.policy_type == current.policy_type
            and source.contract_version == current.contract_version
            and source.priority == current.priority
            and source.scope_type == current.scope_type
            and source.scope_id == current.scope_id
            and source.conditions == current.conditions
            and source.effects == current.effects
            and source.metadata == current.metadata
        )

    @staticmethod
    def _resolution_json(value: PolicyResolution) -> dict[str, Any]:
        def encode(item: Any) -> Any:
            if isinstance(item, UUID | StrEnum):
                return str(item)
            if isinstance(item, tuple | list):
                return [encode(child) for child in item]
            if isinstance(item, dict):
                return {str(key): encode(child) for key, child in item.items()}
            return item

        encoded = encode(asdict(value))
        assert isinstance(encoded, dict)
        return cast(dict[str, Any], encoded)


__all__ = [
    "AccessChange",
    "ImpactAccuracy",
    "PolicyImpact",
    "PolicyPlanningService",
    "PolicyPreview",
    "PolicyPreviewEntry",
    "PolicyPreviewTarget",
]
