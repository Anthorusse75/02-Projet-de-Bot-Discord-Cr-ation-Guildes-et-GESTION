from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.policies import (
    Policy,
    PolicyLifecycleError,
    PolicyLifecycleState,
    PolicyScopeType,
    PolicyVersion,
)
from did.domain.read_model.models import ChannelType, GuildSnapshot, MemberSnapshot
from did.infrastructure.policies_repository import PoliciesRepository
from did.permissions.calculator import PermissionEvaluator
from did.permissions.views import AccessSynthesis, synthesize_access, view_as_role
from did.policies.conflict_explanations import (
    BlacklistRegrant,
    ConflictExplanation,
    explain_conflicts,
    find_blacklist_regrants,
)
from did.policies.registry import (
    POLICY_TYPE_REGISTRY,
    PolicyDefinitionValidationError,
    PolicyReference,
    PolicyTypeRegistry,
)
from did.policies.resolver import (
    PolicyResolution,
    PolicyResolutionContext,
    PolicyResolutionOutcome,
    PolicyResolver,
    PolicyTargetState,
)


@dataclass(frozen=True, slots=True)
class ExplainedPolicyResolution:
    resolution: PolicyResolution
    conflict_explanations: tuple[ConflictExplanation, ...]
    blacklist_regrants: tuple[BlacklistRegrant, ...]


@dataclass(frozen=True, slots=True)
class AccessMatrixCell:
    """One role x resource cell (REQ-AP-MAT-002/004): synthesis comes from the
    canonical `PermissionEvaluator`, conflict/exception/inherited from the
    canonical `PolicyResolver` -- no second calculation of either."""

    role_id: int
    resource_id: int
    synthesis: AccessSynthesis
    permission_status: str
    policy_outcome: PolicyResolutionOutcome
    conflict: bool
    exception: bool
    inherited: bool
    contributing_policy_ids: tuple[UUID, ...]
    conflict_policy_ids: tuple[UUID, ...]
    incomplete_reasons: tuple[str, ...]
    role_known: bool
    resource_known: bool


@dataclass(frozen=True, slots=True)
class AccessMatrixResult:
    guild_id: int
    coverage: CoverageMode
    freshness: FreshnessState
    source_versions: tuple[str, ...]
    cells: tuple[AccessMatrixCell, ...]


@dataclass(frozen=True, slots=True)
class BulkPolicyDraftDefinition:
    policy_type: str
    contract_version: int
    name: str
    description: str
    scope_type: PolicyScopeType
    scope_id: str | None
    conditions: object
    effects: object
    metadata: object
    priority: int = 0


class PolicyService:
    """Validate, persist and explain declarations without applying Discord changes."""

    def __init__(
        self,
        repository: PoliciesRepository,
        registry: PolicyTypeRegistry = POLICY_TYPE_REGISTRY,
        *,
        read_models: Any = None,
        resolver: PolicyResolver | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._read_models = read_models
        self._resolver = resolver or PolicyResolver(registry)

    async def list(self, guild_id: int) -> tuple[Policy, ...]:
        return await self._repository.list(guild_id)

    async def get(self, guild_id: int, policy_id: UUID) -> Policy:
        return await self._repository.get(guild_id, policy_id)

    async def versions(self, guild_id: int, policy_id: UUID) -> tuple[PolicyVersion, ...]:
        return await self._repository.versions(guild_id, policy_id)

    async def get_revision(self, guild_id: int, policy_id: UUID, revision: int) -> Policy:
        return await self._repository.get_revision(guild_id, policy_id, revision)

    async def create_draft(
        self,
        *,
        guild_id: int,
        actor_id: int,
        policy_type: str,
        contract_version: int,
        name: str,
        description: str,
        scope_type: PolicyScopeType,
        scope_id: str | None,
        conditions: object,
        effects: object,
        metadata: object,
        idempotency_key: str,
        priority: int = 0,
    ) -> Policy:
        normalized_scope_id = self._normalize_scope_id(scope_type, scope_id)
        definition = self._registry.validate(
            policy_type=policy_type,
            contract_version=contract_version,
            scope_type=scope_type,
            conditions=conditions,
            effects=effects,
            metadata=metadata,
        )
        await self._validate_targets(
            guild_id, scope_type, normalized_scope_id, definition.references
        )
        await self._validate_definition_compatibility(
            guild_id, actor_id, scope_type, normalized_scope_id, definition.effects
        )
        policy = Policy(
            policy_id=uuid4(),
            guild_id=guild_id,
            policy_type=policy_type,
            contract_version=contract_version,
            name=name.strip(),
            description=description.strip(),
            lifecycle_state=PolicyLifecycleState.DRAFT,
            revision=1,
            scope_type=scope_type,
            scope_id=normalized_scope_id,
            conditions=definition.conditions,
            effects=definition.effects,
            metadata=definition.metadata,
            created_by_user_id=actor_id,
            modified_by_user_id=actor_id,
            priority=priority,
        )
        request_hash = self._hash(
            {
                "guild_id": guild_id,
                "actor_id": actor_id,
                **PoliciesRepository._snapshot(policy),
                "policy_id": None,
            }
        )
        return await self._repository.create(
            policy,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=uuid4(),
        )

    async def create_bulk_drafts(
        self,
        *,
        guild_id: int,
        actor_id: int,
        definitions: Sequence[BulkPolicyDraftDefinition],
        idempotency_key: str,
    ) -> tuple[Policy, ...]:
        """Create one explicit DRAFT per target under one retry-safe user intention.

        The individual Policy aggregate remains canonical.  Stable child keys make a
        retry after a timeout return the same drafts instead of duplicating them.
        """

        drafts: list[Policy] = []
        operation_id = self.bulk_operation_id(idempotency_key)
        for definition in definitions:
            child_key = self.bulk_child_key(
                idempotency_key,
                "draft",
                definition.scope_type.value,
                definition.scope_id or "*",
            )
            metadata = dict(definition.metadata) if isinstance(definition.metadata, dict) else {}
            tags = list(metadata.get("tags", ()))
            if operation_id not in tags:
                tags.append(operation_id)
            metadata["tags"] = tags
            drafts.append(
                await self.create_draft(
                    guild_id=guild_id,
                    actor_id=actor_id,
                    policy_type=definition.policy_type,
                    contract_version=definition.contract_version,
                    name=definition.name,
                    description=definition.description,
                    scope_type=definition.scope_type,
                    scope_id=definition.scope_id,
                    conditions=definition.conditions,
                    effects=definition.effects,
                    metadata=metadata,
                    idempotency_key=child_key,
                    priority=definition.priority,
                )
            )
        return tuple(drafts)

    async def update_draft(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_id: int,
        expected_revision: int,
        name: str,
        description: str,
        scope_type: PolicyScopeType,
        scope_id: str | None,
        conditions: object,
        effects: object,
        metadata: object,
        idempotency_key: str,
        priority: int | None = None,
    ) -> Policy:
        current = await self._repository.get(guild_id, policy_id)
        if current.lifecycle_state is not PolicyLifecycleState.DRAFT:
            raise PolicyLifecycleError("only a DRAFT Policy can be edited")
        normalized_scope_id = self._normalize_scope_id(scope_type, scope_id)
        definition = self._registry.validate(
            policy_type=current.policy_type,
            contract_version=current.contract_version,
            scope_type=scope_type,
            conditions=conditions,
            effects=effects,
            metadata=metadata,
        )
        await self._validate_targets(
            guild_id, scope_type, normalized_scope_id, definition.references
        )
        await self._validate_definition_compatibility(
            guild_id, actor_id, scope_type, normalized_scope_id, definition.effects
        )
        changed = replace(
            current,
            name=name.strip(),
            description=description.strip(),
            scope_type=scope_type,
            scope_id=normalized_scope_id,
            conditions=definition.conditions,
            effects=definition.effects,
            metadata=definition.metadata,
            modified_by_user_id=actor_id,
            priority=current.priority if priority is None else priority,
            revision=expected_revision + 1,
        )
        request_hash = self._hash(
            {**PoliciesRepository._snapshot(changed), "expected_revision": expected_revision}
        )
        return await self._repository.update_draft(
            changed,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=uuid4(),
        )

    async def activate(
        self,
        guild_id: int,
        policy_id: UUID,
        actor_id: int,
        expected_revision: int,
        idempotency_key: str,
        activation_plan_id: UUID,
    ) -> Policy:
        current = await self._repository.get(guild_id, policy_id)
        if current.lifecycle_state is PolicyLifecycleState.ACTIVE:
            return current
        await self._repository.assert_activation_plan(
            guild_id=guild_id,
            policy_id=policy_id,
            policy_revision=expected_revision,
            plan_id=activation_plan_id,
        )
        definition = self._registry.validate(
            policy_type=current.policy_type,
            contract_version=current.contract_version,
            scope_type=current.scope_type,
            conditions=current.conditions,
            effects=current.effects,
            metadata=current.metadata,
        )
        await self._validate_targets(
            guild_id, current.scope_type, current.scope_id, definition.references
        )
        return await self._transition(
            current,
            actor_id,
            expected_revision,
            PolicyLifecycleState.ACTIVE,
            "ACTIVATE",
            idempotency_key,
        )

    async def disable(
        self,
        guild_id: int,
        policy_id: UUID,
        actor_id: int,
        expected_revision: int,
        idempotency_key: str,
    ) -> Policy:
        current = await self._repository.get(guild_id, policy_id)
        if current.lifecycle_state is PolicyLifecycleState.DISABLED:
            return current
        return await self._transition(
            current,
            actor_id,
            expected_revision,
            PolicyLifecycleState.DISABLED,
            "DISABLE",
            idempotency_key,
        )

    async def retire(
        self,
        guild_id: int,
        policy_id: UUID,
        actor_id: int,
        expected_revision: int,
        idempotency_key: str,
    ) -> Policy:
        current = await self._repository.get(guild_id, policy_id)
        if current.lifecycle_state is PolicyLifecycleState.RETIRED:
            return current
        return await self._transition(
            current,
            actor_id,
            expected_revision,
            PolicyLifecycleState.RETIRED,
            "RETIRE",
            idempotency_key,
        )

    async def accept_exception(
        self,
        guild_id: int,
        policy_id: UUID,
        actor_id: int,
        *,
        other_policy_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        reason: str | None = None,
    ) -> Policy:
        """Document an intentional exception on this Policy's metadata (REQ-AP-VIS-017).

        Reuses the existing Policy metadata contract (tags/reason) instead of
        a second exceptions store: a conflict between this Policy and
        ``other_policy_id`` becomes an explicit "exception voulue" rather than
        a silent conflict. Conditions, effects, scope and lifecycle state are
        untouched -- only metadata changes, as a new audited revision.
        """
        current = await self._repository.get(guild_id, policy_id)
        if current.lifecycle_state not in {
            PolicyLifecycleState.ACTIVE,
            PolicyLifecycleState.DISABLED,
        }:
            raise PolicyLifecycleError(
                "an exception can only be accepted on an ACTIVE or DISABLED Policy"
            )
        tag = f"exception_accepted:{other_policy_id}"
        raw_tags = current.metadata.get("tags", ())
        existing_tags: tuple[str, ...] = (
            tuple(str(value) for value in raw_tags) if isinstance(raw_tags, list | tuple) else ()
        )
        if tag in existing_tags:
            return current
        new_metadata = {
            **current.metadata,
            "tags": (*existing_tags, tag),
            "reason": reason if reason is not None else current.metadata.get("reason"),
        }
        contract = self._registry.get(current.policy_type, current.contract_version)
        validated_metadata = contract.metadata_adapter.validate_python(new_metadata)
        changed = replace(
            current,
            metadata=validated_metadata.model_dump(mode="json"),
            modified_by_user_id=actor_id,
            revision=expected_revision + 1,
        )
        request_hash = self._hash(
            {
                "guild_id": current.guild_id,
                "policy_id": str(current.policy_id),
                "actor_id": actor_id,
                "expected_revision": expected_revision,
                "other_policy_id": str(other_policy_id),
                "reason": reason,
            }
        )
        return await self._repository.annotate(
            changed,
            expected_revision=expected_revision,
            expected_state=current.lifecycle_state,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=uuid4(),
        )

    async def _transition(
        self,
        current: Policy,
        actor_id: int,
        expected_revision: int,
        target: PolicyLifecycleState,
        change_kind: str,
        idempotency_key: str,
    ) -> Policy:
        changed = replace(
            current.transition_to(target),
            modified_by_user_id=actor_id,
            revision=expected_revision + 1,
        )
        request_hash = self._hash(
            {
                "guild_id": current.guild_id,
                "policy_id": str(current.policy_id),
                "actor_id": actor_id,
                "expected_revision": expected_revision,
                "target": target.value,
            }
        )
        return await self._repository.transition(
            changed,
            expected_revision=expected_revision,
            expected_state=current.lifecycle_state,
            change_kind=change_kind,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=uuid4(),
        )

    async def resolve_access(
        self,
        *,
        guild_id: int,
        subject_id: int,
        target_scope_type: PolicyScopeType,
        target_scope_id: str | None,
        requested_access: str,
    ) -> PolicyResolution:
        """Build a cache-first context and run the one canonical resolver.

        The method performs tenant-scoped local reads only.  It never calls
        Discord, creates a Plan or mutates observed/designed state.
        """

        if self._read_models is None:
            raise RuntimeError("Policy resolution read model is not configured")
        normalized_target_id = self._normalize_resolution_target(target_scope_type, target_scope_id)
        policies, snapshot_and_member, logical_groups = await asyncio.gather(
            self._repository.list(guild_id),
            self._read_models.guild_snapshot(guild_id, subject_id),
            self._read_models.list_logical_groups(guild_id),
        )
        guild, member = snapshot_and_member
        return self.resolve_loaded(
            policies=policies,
            guild=guild,
            member=member,
            logical_groups=logical_groups,
            target_scope_type=target_scope_type,
            target_scope_id=normalized_target_id,
            requested_access=requested_access,
            subject_id=subject_id,
        )

    async def resolve_access_explained(
        self,
        *,
        guild_id: int,
        subject_id: int,
        target_scope_type: PolicyScopeType,
        target_scope_id: str | None,
        requested_access: str,
    ) -> ExplainedPolicyResolution:
        """Same as `resolve_access`, plus human-narratable conflict causes.

        REQ-AP-VIS-011/012/013: re-reads the same resolution the canonical
        resolver already produced -- no second resolver, no new permission
        evaluation -- and explains, in terms of the member's actual roles,
        both a genuine resolver-detected conflict and a blacklist an
        unrelated Policy silently bypasses.
        """

        if self._read_models is None:
            raise RuntimeError("Policy resolution read model is not configured")
        normalized_target_id = self._normalize_resolution_target(target_scope_type, target_scope_id)
        policies, snapshot_and_member, logical_groups = await asyncio.gather(
            self._repository.list(guild_id),
            self._read_models.guild_snapshot(guild_id, subject_id),
            self._read_models.list_logical_groups(guild_id),
        )
        guild, member = snapshot_and_member
        resolution = self.resolve_loaded(
            policies=policies,
            guild=guild,
            member=member,
            logical_groups=logical_groups,
            target_scope_type=target_scope_type,
            target_scope_id=normalized_target_id,
            requested_access=requested_access,
            subject_id=subject_id,
        )
        policies_by_id = {policy.policy_id: policy for policy in policies}
        member_role_ids = tuple(sorted(str(role_id) for role_id in member.role_ids))
        return ExplainedPolicyResolution(
            resolution=resolution,
            conflict_explanations=explain_conflicts(
                resolution, policies_by_id=policies_by_id, member_role_ids=member_role_ids
            ),
            blacklist_regrants=find_blacklist_regrants(
                resolution, policies_by_id=policies_by_id, member_role_ids=member_role_ids
            ),
        )

    def resolve_loaded(
        self,
        *,
        policies: tuple[Policy, ...],
        guild: GuildSnapshot,
        member: MemberSnapshot,
        logical_groups: Sequence[dict[str, Any]],
        target_scope_type: PolicyScopeType,
        target_scope_id: str | None,
        requested_access: str,
        subject_id: int | None = None,
    ) -> PolicyResolution:
        """Resolve already loaded cache facts through the canonical resolver."""

        normalized_target_id = self._normalize_resolution_target(target_scope_type, target_scope_id)
        target_state, target_freshness, category_id = self._target_state(
            guild, target_scope_type, normalized_target_id, logical_groups
        )
        matching_groups = self._matching_logical_groups(
            logical_groups,
            target_scope_type=target_scope_type,
            target_scope_id=normalized_target_id,
            category_id=category_id,
        )
        context = PolicyResolutionContext(
            guild_id=guild.guild_id,
            requested_access=requested_access,
            target_scope_type=target_scope_type,
            target_scope_id=normalized_target_id,
            target_state=target_state,
            target_freshness=target_freshness,
            coverage=guild.coverage.mode,
            subject_id=subject_id if subject_id is not None else member.user_id,
            subject_role_ids=tuple(sorted(str(role_id) for role_id in member.role_ids)),
            subject_roles_complete=member.roles_complete,
            subject_freshness=member.freshness.state,
            subject_is_bot=(
                member.is_bot
                if member.freshness.state not in {FreshnessState.STALE, FreshnessState.UNKNOWN}
                else None
            ),
            category_id=category_id,
            logical_group_ids=matching_groups,
            known_role_ids=tuple(sorted(str(role.role_id) for role in guild.roles)),
            roles_catalog_complete=guild.roles_complete,
            source_versions=guild.source_versions,
            target_channel_type=(
                int(channel.channel_type)
                if target_scope_type in {PolicyScopeType.CHANNEL, PolicyScopeType.CATEGORY}
                and normalized_target_id is not None
                and (channel := guild.channel(int(normalized_target_id))) is not None
                else None
            ),
        )
        return self._resolver.resolve(policies=policies, context=context)

    async def resolve_matrix(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        role_ids: tuple[int, ...],
        resource_ids: tuple[int, ...],
    ) -> AccessMatrixResult:
        """Batch-resolve Discord effective access and Policy intent for a role
        x resource grid (REQ-AP-MAT-001..004).

        Loads the tenant Guild snapshot, the active Policies and the logical
        groups exactly once, then evaluates every (role, resource) pair in
        memory with the same canonical `PermissionEvaluator` and
        `PolicyResolver` used everywhere else in the product -- no second
        engine, no per-cell Discord or database round trip. Complexity is
        O(len(role_ids) * len(resource_ids)) pure in-memory calls after three
        constant-size reads; callers must keep both lists within
        `MAX_MATRIX_ROLES`/`MAX_MATRIX_RESOURCES` (enforced at the API layer).
        """

        if self._read_models is None:
            raise RuntimeError("Policy resolution read model is not configured")
        policies, snapshot_and_member, logical_groups = await asyncio.gather(
            self._repository.list(guild_id),
            self._read_models.guild_snapshot(guild_id, actor_user_id),
            self._read_models.list_logical_groups(guild_id),
        )
        guild, _ = snapshot_and_member
        evaluator = PermissionEvaluator()
        cells: list[AccessMatrixCell] = []
        for role_id in role_ids:
            try:
                subject = view_as_role(guild, role_id, freshness=guild.freshness)
            except ValueError:
                resource_known = {
                    resource_id: guild.channel(resource_id) is not None
                    for resource_id in resource_ids
                }
                cells.extend(
                    AccessMatrixCell(
                        role_id=role_id,
                        resource_id=resource_id,
                        synthesis=AccessSynthesis.UNKNOWN,
                        permission_status="UNKNOWN",
                        policy_outcome=PolicyResolutionOutcome.UNKNOWN,
                        conflict=False,
                        exception=False,
                        inherited=False,
                        contributing_policy_ids=(),
                        conflict_policy_ids=(),
                        incomplete_reasons=("policy.matrix.role_unknown",),
                        role_known=False,
                        resource_known=resource_known[resource_id],
                    )
                    for resource_id in resource_ids
                )
                continue
            member = subject.member
            for resource_id in resource_ids:
                channel = guild.channel(resource_id)
                if channel is None:
                    cells.append(
                        AccessMatrixCell(
                            role_id=role_id,
                            resource_id=resource_id,
                            synthesis=AccessSynthesis.UNKNOWN,
                            permission_status="UNKNOWN",
                            policy_outcome=PolicyResolutionOutcome.UNKNOWN,
                            conflict=False,
                            exception=False,
                            inherited=False,
                            contributing_policy_ids=(),
                            conflict_policy_ids=(),
                            incomplete_reasons=("policy.matrix.resource_unknown",),
                            role_known=True,
                            resource_known=False,
                        )
                    )
                    continue
                decision = evaluator.evaluate(guild=guild, member=member, resource=channel)
                is_voice = channel.channel_type in {
                    ChannelType.GUILD_VOICE,
                    ChannelType.GUILD_STAGE_VOICE,
                }
                synthesis = (
                    synthesize_access(decision.effective_bits, is_voice=is_voice)
                    if decision.status.value == "COMPLETE"
                    else AccessSynthesis.UNKNOWN
                )
                target_scope_type = (
                    PolicyScopeType.CATEGORY
                    if channel.channel_type is ChannelType.GUILD_CATEGORY
                    else PolicyScopeType.CHANNEL
                )
                requested_accesses = (
                    ("VIEW", "CONNECT", "SPEAK", "MANAGE")
                    if is_voice
                    else ("VIEW", "WRITE", "MANAGE")
                )
                resolutions = tuple(
                    self.resolve_loaded(
                        policies=policies,
                        guild=guild,
                        member=member,
                        logical_groups=logical_groups,
                        target_scope_type=target_scope_type,
                        target_scope_id=str(resource_id),
                        requested_access=requested_access,
                        subject_id=member.user_id,
                    )
                    for requested_access in requested_accesses
                )
                scopes = tuple(
                    scope for resolution in resolutions for scope in resolution.source_scopes
                )
                inherited = any(scope.inherited for scope in scopes)
                local = any(not scope.inherited for scope in scopes)
                outcomes = {resolution.outcome for resolution in resolutions}
                primary_access = {
                    AccessSynthesis.WRITE: "WRITE",
                    AccessSynthesis.MANAGE: "MANAGE",
                    AccessSynthesis.CONNECT: "CONNECT",
                    AccessSynthesis.SPEAK: "SPEAK",
                }.get(synthesis, "VIEW")
                primary_outcome = next(
                    resolution.outcome
                    for resolution in resolutions
                    if resolution.decision.endswith(f":{primary_access}")
                )
                policy_outcome = (
                    PolicyResolutionOutcome.BLOCKED
                    if PolicyResolutionOutcome.BLOCKED in outcomes
                    else PolicyResolutionOutcome.UNKNOWN
                    if PolicyResolutionOutcome.UNKNOWN in outcomes
                    else primary_outcome
                )
                cells.append(
                    AccessMatrixCell(
                        role_id=role_id,
                        resource_id=resource_id,
                        synthesis=synthesis,
                        permission_status=decision.status.value,
                        policy_outcome=policy_outcome,
                        conflict=any(resolution.conflicts for resolution in resolutions),
                        exception=inherited and local,
                        inherited=inherited,
                        contributing_policy_ids=tuple(
                            dict.fromkeys(
                                item.policy_id
                                for resolution in resolutions
                                for item in resolution.contributions
                                if item.selected
                            )
                        ),
                        conflict_policy_ids=tuple(
                            dict.fromkeys(
                                policy_id
                                for resolution in resolutions
                                for conflict in resolution.conflicts
                                for policy_id in conflict.policy_ids
                            )
                        ),
                        incomplete_reasons=tuple(
                            dict.fromkeys(
                                (
                                    *decision.incomplete_reasons,
                                    *(
                                        reason
                                        for resolution in resolutions
                                        for reason in resolution.incomplete_reasons
                                    ),
                                )
                            )
                        ),
                        role_known=True,
                        resource_known=True,
                    )
                )
        return AccessMatrixResult(
            guild_id=guild_id,
            coverage=guild.coverage.mode,
            freshness=guild.coverage.freshness,
            source_versions=guild.source_versions,
            cells=tuple(cells),
        )

    @classmethod
    def _target_state(
        cls,
        guild: GuildSnapshot,
        scope_type: PolicyScopeType,
        scope_id: str | None,
        logical_groups: Sequence[dict[str, Any]],
    ) -> tuple[PolicyTargetState, FreshnessState, str | None]:
        if scope_type is PolicyScopeType.GUILD:
            state = cls._freshness_state(guild.freshness.state)
            return state, guild.freshness.state, None
        if scope_type is PolicyScopeType.LOGICAL_GROUP:
            known = {str(group["id"]) for group in logical_groups}
            state = PolicyTargetState.CURRENT if scope_id in known else PolicyTargetState.DELETED
            return state, FreshnessState.FRESH, None
        assert scope_id is not None
        channel = guild.channel(int(scope_id))
        if channel is None:
            state = (
                PolicyTargetState.DELETED if guild.channels_complete else PolicyTargetState.UNKNOWN
            )
            return state, guild.coverage.freshness, None
        category_id = cls._category_id(guild, channel.channel_id)
        if (
            scope_type is PolicyScopeType.CATEGORY
            and channel.channel_type is not ChannelType.GUILD_CATEGORY
        ) or (
            scope_type is PolicyScopeType.CHANNEL
            and channel.channel_type is ChannelType.GUILD_CATEGORY
        ):
            return PolicyTargetState.UNKNOWN, channel.freshness.state, category_id
        if channel.observability in {
            ObservabilityState.DELETED_CONFIRMED,
            ObservabilityState.USER_CONFIRMED_DELETED,
        }:
            state = PolicyTargetState.DELETED
        elif channel.observability in {
            ObservabilityState.OBFUSCATED,
            ObservabilityState.ACCESS_LOST,
        }:
            state = PolicyTargetState.INACCESSIBLE
        elif channel.observability is ObservabilityState.UNKNOWN:
            state = PolicyTargetState.UNKNOWN
        else:
            state = cls._freshness_state(channel.freshness.state)
        return state, channel.freshness.state, category_id

    @staticmethod
    def _freshness_state(freshness: FreshnessState) -> PolicyTargetState:
        if freshness is FreshnessState.STALE:
            return PolicyTargetState.STALE
        if freshness is FreshnessState.UNKNOWN:
            return PolicyTargetState.UNKNOWN
        return PolicyTargetState.CURRENT

    @staticmethod
    def _category_id(guild: GuildSnapshot, channel_id: int) -> str | None:
        channel = guild.channel(channel_id)
        if channel is None:
            return None
        if channel.channel_type is ChannelType.GUILD_CATEGORY:
            return str(channel.channel_id)
        parent = guild.channel(channel.parent_id) if channel.parent_id is not None else None
        if channel.is_thread and parent is not None:
            parent = guild.channel(parent.parent_id) if parent.parent_id is not None else None
        if parent is not None and parent.channel_type is ChannelType.GUILD_CATEGORY:
            return str(parent.channel_id)
        return None

    @staticmethod
    def _matching_logical_groups(
        groups: Sequence[dict[str, Any]],
        *,
        target_scope_type: PolicyScopeType,
        target_scope_id: str | None,
        category_id: str | None,
    ) -> tuple[str, ...]:
        if target_scope_type is PolicyScopeType.GUILD:
            return ()
        matches: list[str] = []
        for group in groups:
            if (
                target_scope_type is PolicyScopeType.LOGICAL_GROUP
                and str(group["id"]) == target_scope_id
            ):
                matches.append(str(group["id"]))
                continue
            for resource in group.get("resources", ()):
                resource_type = str(resource.get("resource_type"))
                resource_id = str(resource.get("discord_channel_id"))
                if (
                    resource_type == "CHANNEL"
                    and target_scope_type is PolicyScopeType.CHANNEL
                    and resource_id == target_scope_id
                ) or (
                    resource_type == "CATEGORY"
                    and resource_id
                    in {
                        category_id,
                        target_scope_id if target_scope_type is PolicyScopeType.CATEGORY else None,
                    }
                ):
                    matches.append(str(group["id"]))
                    break
        return tuple(sorted(set(matches)))

    @staticmethod
    def _normalize_resolution_target(
        scope_type: PolicyScopeType, scope_id: str | None
    ) -> str | None:
        if scope_type not in {
            PolicyScopeType.GUILD,
            PolicyScopeType.LOGICAL_GROUP,
            PolicyScopeType.CATEGORY,
            PolicyScopeType.CHANNEL,
        }:
            raise PolicyDefinitionValidationError(
                "Policy resolution target must be GUILD, LOGICAL_GROUP, CATEGORY or CHANNEL"
            )
        return PolicyService._normalize_scope_id(scope_type, scope_id)

    async def _validate_targets(
        self,
        guild_id: int,
        scope_type: PolicyScopeType,
        scope_id: str | None,
        references: tuple[PolicyReference, ...],
    ) -> None:
        await self._repository.validate_target(guild_id, scope_type, scope_id)
        role_ids = tuple(
            reference.scope_id
            for reference in references
            if reference.scope_type is PolicyScopeType.ROLE
        )
        await self._repository.validate_role_references(guild_id, role_ids)
        for reference in references:
            if reference.scope_type is PolicyScopeType.BOT:
                await self._repository.validate_target(
                    guild_id, PolicyScopeType.BOT, reference.scope_id
                )

    async def _validate_definition_compatibility(
        self,
        guild_id: int,
        actor_id: int,
        scope_type: PolicyScopeType,
        scope_id: str | None,
        effects: tuple[dict[str, object], ...],
    ) -> None:
        accesses = {str(effect["access"]) for effect in effects}
        voice_only = {"CONNECT", "SPEAK", "MANAGE_VOICE"}
        thread_text_only = {"CREATE_THREAD", "PARTICIPATE_THREAD", "REACT"}
        bot_channel_only = {"READ_HISTORY", "SEND", "MANAGE_CHANNEL"}
        specialized = accesses & (voice_only | thread_text_only | bot_channel_only)
        if not specialized:
            return
        if scope_type is not PolicyScopeType.CHANNEL or scope_id is None:
            raise PolicyDefinitionValidationError(
                "vocal, thread, reaction and bot-function intentions require an explicit "
                "compatible channel"
            )
        if self._read_models is None:
            raise PolicyDefinitionValidationError(
                "channel compatibility cannot be verified from the local read model"
            )
        guild, _ = await self._read_models.guild_snapshot(guild_id, actor_id)
        channel = guild.channel(int(scope_id))
        if channel is None:
            raise PolicyDefinitionValidationError("Policy channel is absent from the read model")
        voice_types = {ChannelType.GUILD_VOICE, ChannelType.GUILD_STAGE_VOICE}
        text_types = {
            ChannelType.GUILD_TEXT,
            ChannelType.GUILD_ANNOUNCEMENT,
            ChannelType.GUILD_FORUM,
            ChannelType.GUILD_MEDIA,
        }
        if accesses & voice_only and channel.channel_type not in voice_types:
            raise PolicyDefinitionValidationError(
                "vocal intentions are only valid for voice and stage channels"
            )
        if accesses & thread_text_only and channel.channel_type not in text_types:
            raise PolicyDefinitionValidationError(
                "thread and reaction intentions require a text, announcement, "
                "forum or media channel"
            )

    @staticmethod
    def _normalize_scope_id(scope_type: PolicyScopeType, scope_id: str | None) -> str | None:
        if scope_type is PolicyScopeType.GUILD:
            if scope_id is not None:
                raise PolicyDefinitionValidationError("GUILD scope_id must be null")
            return None
        if scope_id is None or not scope_id.strip():
            raise PolicyDefinitionValidationError("non-GUILD scope_id is required")
        normalized = scope_id.strip()
        if scope_type is PolicyScopeType.LOGICAL_GROUP:
            try:
                UUID(normalized)
            except ValueError as exc:
                raise PolicyDefinitionValidationError(
                    "LOGICAL_GROUP scope_id must be a UUID"
                ) from exc
        elif scope_type in {
            PolicyScopeType.CATEGORY,
            PolicyScopeType.CHANNEL,
            PolicyScopeType.ROLE,
            PolicyScopeType.MEMBER,
            PolicyScopeType.BOT,
        }:
            if not normalized.isascii() or not normalized.isdigit() or int(normalized) <= 0:
                raise PolicyDefinitionValidationError(
                    "Discord target scope_id must be a positive decimal ID"
                )
        return normalized

    @staticmethod
    def _hash(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def bulk_child_key(parent: str, *parts: str) -> str:
        digest = hashlib.sha256("\x00".join((parent, *parts)).encode()).hexdigest()
        return f"policy-bulk:{digest}"

    @staticmethod
    def bulk_operation_id(parent: str) -> str:
        digest = hashlib.sha256(parent.encode()).hexdigest()[:48]
        return f"bulk-operation:{digest}"
