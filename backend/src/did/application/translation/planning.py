from __future__ import annotations

from typing import Any
from uuid import UUID

from did.application.planning import PlanningService
from did.application.translation.service import (
    DISCORD_OVERWRITE_LIMIT,
    DISCORD_ROLE_LIMIT,
    VIEW_CHANNEL,
)
from did.domain.discord_runtime import ObservabilityState
from did.domain.scopes import MembershipOutcome, ScopeMembershipResolver
from did.domain.translation_topology import VisibilityPolicy
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_lifecycle_repository import (
    Stage08LifecycleConflict,
    Stage08LifecycleRepository,
)
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    ResourceLanguagePolicyRepository,
    TranslationGroupRepository,
    VisibilityScopeLanguageRepository,
)
from did.planning import (
    DesiredNode,
    DesiredStateGraph,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)


class Stage08StructuralPlanningService:
    """Compile business intents from durable topology plus the cache-first Discord model."""

    def __init__(
        self,
        *,
        planning: PlanningService,
        read_models: Stage04Repository,
        groups: TranslationGroupRepository,
        languages: LanguageProfileRepository,
        policies: ResourceLanguagePolicyRepository,
        scope_roles: VisibilityScopeLanguageRepository,
        lifecycle: Stage08LifecycleRepository,
    ) -> None:
        self._planning = planning
        self._read_models = read_models
        self._groups = groups
        self._languages = languages
        self._policies = policies
        self._scope_roles = scope_roles
        self._lifecycle = lifecycle

    async def create_visibility_plan(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        actor_user_id: int,
        resource_type: str,
        discord_resource_id: int,
        idempotency_key: str,
        correlation_id: UUID,
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        if resource_type not in {"CATEGORY", "CHANNEL"}:
            raise ValueError("visibility target must be a category or channel")
        group = await self._groups.workspace_group(guild_id=guild_id, group_id=group_id)
        self._assert_group_resource(group, resource_type, discord_resource_id)
        guild, _ = await self._read_models.guild_snapshot(guild_id, actor_user_id)
        channel = guild.channel(discord_resource_id)
        if channel is None or channel.observability is not ObservabilityState.VISIBLE:
            raise ValueError("visibility target is unavailable in the trusted Discord cache")
        if not channel.overwrites_complete:
            raise ValueError("visibility overwrite coverage is incomplete")
        policy = await self._effective_policy(
            guild_id=guild_id,
            resource_type=resource_type,
            resource_id=discord_resource_id,
            parent_id=channel.parent_id,
        )
        visibility = VisibilityPolicy(str(policy["visibility_policy"]))
        if visibility in {VisibilityPolicy.OPEN_ALL, VisibilityPolicy.CUSTOM}:
            raise ValueError("this endpoint only plans managed language visibility")
        language_id = policy.get("explicit_language_profile_id")
        if language_id is None:
            raise ValueError("managed language visibility requires an explicit language")
        language = await self._languages.get(guild_id, UUID(str(language_id)))
        if not bool(language["enabled"]):
            raise ValueError("managed language visibility requires an enabled language")
        scope_id = policy.get("visibility_scope_id")
        role_id: int | None = None
        reservation: dict[str, Any] | None = None
        symbol: str | None = None
        intent_type: str | None = None
        if visibility is VisibilityPolicy.LANGUAGE_FILTERED:
            binding = await self._lifecycle.language_binding(
                guild_id=guild_id,
                language_profile_id=UUID(str(language_id)),
            )
            binding_key = f"language:{language_id}"
            role_name = f"DID·LANG·{str(language['code']).upper()}"
            intent_type = "BIND_LANGUAGE_ROLE"
        else:
            if scope_id is None:
                raise ValueError("scope-and-language visibility requires an explicit scope")
            binding = await self._scope_roles.find_binding(
                guild_id=guild_id,
                visibility_scope_id=UUID(str(scope_id)),
                language_profile_id=UUID(str(language_id)),
            )
            binding_key = f"scope:{scope_id}:language:{language_id}"
            role_name = f"DID·{str(scope_id)[:8]}·{str(language['code']).upper()}"
            intent_type = "BIND_SCOPE_LANGUAGE_ROLE"
        if binding is not None and str(binding["role_state"]) == "ACTIVE":
            role_id = int(binding["discord_role_id"])
            if guild.role(role_id) is None:
                raise ValueError("technical role binding is absent from the trusted Discord cache")
        else:
            if len(guild.roles) + 1 > DISCORD_ROLE_LIMIT:
                raise ValueError("ROLE_CAPACITY_EXCEEDED")
            prospective_additions = 1 + (
                0
                if any(
                    overwrite.target_type == 0 and overwrite.target_id == guild_id
                    for overwrite in channel.overwrites
                )
                else 1
            )
            if len(channel.overwrites) + prospective_additions > DISCORD_OVERWRITE_LIMIT:
                raise ValueError("OVERWRITE_CAPACITY_EXCEEDED")
            symbol = f"stage08.role.{binding_key}"
            reservation, created = await self._lifecycle.reserve_role(
                guild_id=guild_id,
                binding_kind=(
                    "LANGUAGE"
                    if visibility is VisibilityPolicy.LANGUAGE_FILTERED
                    else "SCOPE_LANGUAGE"
                ),
                binding_key=binding_key,
                visibility_scope_id=UUID(str(scope_id)) if scope_id is not None else None,
                language_profile_id=UUID(str(language_id)),
                symbol=symbol,
            )
            if not created:
                status = str(reservation["status"])
                if status == "BOUND" and reservation["discord_role_id"] is not None:
                    role_id = int(reservation["discord_role_id"])
                    reservation = None
                    symbol = None
                else:
                    raise Stage08LifecycleConflict("technical role creation is already reserved")
        nodes: list[DesiredNode] = []
        if symbol is not None:
            nodes.append(
                DesiredNode.build(
                    logical_key=f"stage08.role.{binding_key}",
                    resource_type=ResourceType.ROLE,
                    symbol=symbol,
                    properties={
                        "name": role_name[:100],
                        "permissions": "0",
                        "color": 0,
                        "hoist": False,
                        "mentionable": False,
                    },
                )
            )
        channel_ref = ResourceReference(ReferenceKind.DISCORD_ID, str(discord_resource_id))
        everyone_ref = ResourceReference(ReferenceKind.DISCORD_ID, str(guild_id))
        role_ref = (
            ResourceReference(ReferenceKind.DISCORD_ID, str(role_id))
            if role_id is not None
            else ResourceReference(ReferenceKind.SYMBOL, str(symbol))
        )
        nodes.extend(
            (
                DesiredNode.build(
                    logical_key=f"stage08.overwrite.{discord_resource_id}.everyone",
                    resource_type=ResourceType.OVERWRITE,
                    properties={"target_type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
                    relations={"channel": channel_ref, "subject": everyone_ref},
                ),
                DesiredNode.build(
                    logical_key=f"stage08.overwrite.{discord_resource_id}.{binding_key}",
                    resource_type=ResourceType.OVERWRITE,
                    properties={"target_type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
                    relations={"channel": channel_ref, "subject": role_ref},
                ),
            )
        )
        additions = sum(
            1
            for target_id in (guild_id, role_id)
            if target_id is None
            or not any(
                overwrite.target_type == 0 and overwrite.target_id == target_id
                for overwrite in channel.overwrites
            )
        )
        if len(channel.overwrites) + additions > DISCORD_OVERWRITE_LIMIT:
            raise ValueError("OVERWRITE_CAPACITY_EXCEEDED")
        plan, replayed = await self._planning.create(
            graph=DesiredStateGraph(guild_id, tuple(nodes)),
            actor_user_id=actor_user_id,
            idempotency_key=f"stage08:visibility:{group_id}:{idempotency_key}",
            correlation_id=correlation_id,
            operation_order_policy="STAGE08_STRUCTURAL",
        )
        if reservation is not None:
            assert symbol is not None and intent_type is not None
            payload = {
                "reservation_id": str(reservation["id"]),
                "language_profile_id": str(language_id),
                "symbol": symbol,
            }
            if scope_id is not None:
                payload["visibility_scope_id"] = str(scope_id)
            await self._lifecycle.attach_role_plan(
                guild_id=guild_id,
                reservation_id=UUID(str(reservation["id"])),
                plan_id=UUID(str(plan["id"])),
                intent_type=intent_type,
                payload=payload,
            )
        return plan, replayed, {
            "source": "TRUSTED_CACHE_AND_DURABLE_TOPOLOGY",
            "role_count": len(guild.roles),
            "role_delta": 1 if reservation is not None else 0,
            "overwrite_count": len(channel.overwrites),
            "overwrite_delta": additions,
        }

    async def create_member_role_plan(
        self,
        *,
        guild_id: int,
        member_id: int,
        actor_user_id: int,
        idempotency_key: str,
        correlation_id: UUID,
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        guild, member = await self._read_models.guild_snapshot(guild_id, member_id)
        if not member.roles_complete or member.freshness.state.value != "FRESH":
            raise ValueError("member role state is incomplete or stale")
        visible_languages = {
            UUID(str(row["language_profile_id"]))
            for row in await self._languages.member_languages(guild_id, member_id)
            if bool(row["enabled"])
        }
        global_bindings = await self._lifecycle.list_language_bindings(guild_id=guild_id)
        scope_bindings = await self._scope_roles.list_bindings(guild_id)
        scopes = await self._read_models.list_visibility_scopes(guild_id)
        member_scopes: set[UUID] = set()
        resolver = ScopeMembershipResolver()
        for scope, rules, explicit_members in scopes:
            decision = resolver.resolve(
                scope=scope,
                member=member,
                rules=rules,
                explicit_member_ids=explicit_members,
            )
            if decision.outcome is MembershipOutcome.UNKNOWN:
                raise ValueError("scope membership is not authoritative")
            if decision.outcome is MembershipOutcome.MATCH:
                member_scopes.add(scope.id)
        desired: set[int] = {
            int(row["discord_role_id"])
            for row in global_bindings
            if str(row["role_state"]) == "ACTIVE"
            and UUID(str(row["language_profile_id"])) in visible_languages
        }
        desired.update(
            int(row["discord_role_id"])
            for row in scope_bindings
            if str(row["role_state"]) == "ACTIVE"
            and UUID(str(row["visibility_scope_id"])) in member_scopes
            and UUID(str(row["language_profile_id"])) in visible_languages
        )
        managed = {
            int(row["discord_role_id"])
            for row in (*global_bindings, *scope_bindings)
            if str(row["role_state"]) == "ACTIVE"
        }
        if any(guild.role(role_id) is None for role_id in managed):
            raise ValueError("managed technical role is absent from the trusted Discord cache")
        current = set(member.role_ids).intersection(managed)
        assign = sorted(desired - current)
        remove = sorted(current - desired)
        nodes = tuple(
            DesiredNode.build(
                logical_key=f"stage08.member.{member_id}.role.{role_id}",
                resource_type=ResourceType.MEMBER_ROLE,
                discord_id=member_id,
                properties={
                    "member_id": member_id,
                    "role_id": role_id,
                    "assigned": assigned,
                    "current_assigned": not assigned,
                },
            )
            for assigned, role_ids in ((True, assign), (False, remove))
            for role_id in role_ids
        )
        plan, replayed = await self._planning.create(
            graph=DesiredStateGraph(guild_id, nodes),
            actor_user_id=actor_user_id,
            idempotency_key=f"stage08:member-roles:{member_id}:{idempotency_key}",
            correlation_id=correlation_id,
            operation_order_policy="STAGE08_STRUCTURAL",
        )
        return plan, replayed, {
            "source": "TRUSTED_CACHE_SCOPE_RESOLVER_AND_DURABLE_LANGUAGES",
            "member_id": str(member_id),
            "assign": [str(value) for value in assign],
            "remove": [str(value) for value in remove],
            "member_specific_overwrites": [],
            "all_languages_role": None,
        }

    async def _effective_policy(
        self,
        *,
        guild_id: int,
        resource_type: str,
        resource_id: int,
        parent_id: int | None,
    ) -> dict[str, Any]:
        policy = await self._policies.get_optional(guild_id, resource_type, resource_id)
        if policy is not None and (
            not bool(policy["inherit_language"])
            or policy.get("explicit_language_profile_id") is not None
        ):
            return policy
        if parent_id is not None:
            inherited = await self._policies.get_optional(guild_id, "CATEGORY", parent_id)
            if inherited is not None:
                return inherited
        if policy is not None:
            return policy
        raise ValueError("visibility target has no durable language policy")

    @staticmethod
    def _assert_group_resource(group: dict[str, Any], resource_type: str, resource_id: int) -> None:
        collection = (
            group["category_variants"]
            if resource_type == "CATEGORY"
            else group["channel_variants"]
        )
        key = "discord_category_id" if resource_type == "CATEGORY" else "discord_channel_id"
        if not any(
            int(row[key]) == resource_id and str(row["state"]) == "ACTIVE"
            for row in collection
        ):
            raise ValueError("visibility target is not an active variant of this group")
