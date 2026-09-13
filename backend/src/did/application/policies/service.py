from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import UUID, uuid4

from did.domain.policies import (
    Policy,
    PolicyLifecycleError,
    PolicyLifecycleState,
    PolicyScopeType,
    PolicyVersion,
)
from did.infrastructure.policies_repository import PoliciesRepository
from did.policies.registry import (
    POLICY_TYPE_REGISTRY,
    PolicyDefinitionValidationError,
    PolicyReference,
    PolicyTypeRegistry,
)


class PolicyService:
    """Validate and persist declarations; deliberately does not resolve or apply them."""

    def __init__(
        self,
        repository: PoliciesRepository,
        registry: PolicyTypeRegistry = POLICY_TYPE_REGISTRY,
    ) -> None:
        self._repository = repository
        self._registry = registry

    async def list(self, guild_id: int) -> tuple[Policy, ...]:
        return await self._repository.list(guild_id)

    async def get(self, guild_id: int, policy_id: UUID) -> Policy:
        return await self._repository.get(guild_id, policy_id)

    async def versions(self, guild_id: int, policy_id: UUID) -> tuple[PolicyVersion, ...]:
        return await self._repository.versions(guild_id, policy_id)

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
    ) -> Policy:
        current = await self._repository.get(guild_id, policy_id)
        if current.lifecycle_state is PolicyLifecycleState.ACTIVE:
            return current
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
