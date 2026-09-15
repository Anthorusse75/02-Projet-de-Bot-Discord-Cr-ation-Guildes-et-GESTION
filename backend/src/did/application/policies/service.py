from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

from did.domain.discord_runtime import FreshnessState, ObservabilityState
from did.domain.policies import (
    Policy,
    PolicyLifecycleError,
    PolicyLifecycleState,
    PolicyScopeType,
    PolicyVersion,
)
from did.domain.read_model.models import ChannelType, GuildSnapshot, MemberSnapshot
from did.infrastructure.policies_repository import PoliciesRepository
from did.policies.registry import (
    POLICY_TYPE_REGISTRY,
    PolicyDefinitionValidationError,
    PolicyReference,
    PolicyTypeRegistry,
)
from did.policies.resolver import (
    PolicyResolution,
    PolicyResolutionContext,
    PolicyResolver,
    PolicyTargetState,
)


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

        normalized_target_id = self._normalize_resolution_target(
            target_scope_type, target_scope_id
        )
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
        )
        return self._resolver.resolve(policies=policies, context=context)

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
