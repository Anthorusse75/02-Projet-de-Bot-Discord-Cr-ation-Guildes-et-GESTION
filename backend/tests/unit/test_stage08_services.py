from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from did.api.main import create_app
from did.api.stage08 import MultilingualCloneInput, multilingual_clone_plan
from did.application.auth.service import AuthorizationDenied
from did.application.planning.service import PlanningService
from did.application.translation import (
    LanguageVisibilityCompiler,
    MemberTechnicalRoleReconciler,
    RoleCapacityEngine,
    RoleOptimizer,
    TranslationDriftDetector,
    TranslationProviderCoordinator,
    TranslationRouteCompiler,
)
from did.application.translation.service import (
    ADMINISTRATOR,
    READ_MESSAGE_HISTORY,
    SEND_MESSAGES,
    VIEW_CHANNEL,
)
from did.domain.translation_topology import (
    LanguageProfile,
    ProviderConfigurationMode,
    ResourceLanguagePolicy,
    ResourceLanguageResolver,
    TranslationGroupTopology,
    TranslationProviderCapabilities,
    VisibilityPolicy,
)
from did.infrastructure.translation_provider import NonInvasiveExistingBotProvider
from did.planning.models import (
    CompensationClass,
    OperationType,
    PlanOperation,
    RecoveryStrategy,
    ResourceType,
    RiskLevel,
    VerificationStrategy,
    freeze_json_object,
)

GUILD = 700000000000000001
NOW = datetime(2026, 8, 28, tzinfo=UTC)


def profile(*, enabled: bool = True) -> LanguageProfile:
    return LanguageProfile(uuid4(), GUILD, "fr", "French", enabled, NOW, NOW)


def capabilities(**overrides: object) -> TranslationProviderCapabilities:
    values: dict[str, object] = {
        "supports_hub_and_spoke": True,
        "supports_full_mesh": True,
        "supports_custom": True,
        "health": "READY",
    }
    values.update(overrides)
    return TranslationProviderCapabilities(**values)  # type: ignore[arg-type]


def test_inheritance_requires_intent_and_never_returns_a_disabled_profile() -> None:
    resolver = ResourceLanguageResolver()
    category = profile()
    disabled = profile(enabled=False)
    policy = ResourceLanguagePolicy(
        uuid4(), GUILD, "CHANNEL", 12, None, False, VisibilityPolicy.OPEN_ALL
    )
    assert resolver.resolve(
        channel_language=None, category_language=category, channel_policy=policy
    ) == (None, "NONE")
    assert resolver.resolve(channel_language=disabled, category_language=category) == (
        None,
        "NONE",
    )


def test_route_compiler_supports_all_topologies_and_keeps_groups_external() -> None:
    fr, en, de = uuid4(), uuid4(), uuid4()
    compiler = TranslationRouteCompiler()
    hub = compiler.compile(
        topology=TranslationGroupTopology.HUB_AND_SPOKE,
        language_ids=(fr, en, de),
        hub_language_id=fr,
        custom_routes=(),
        capabilities=capabilities(),
    )
    assert set(hub) == {(fr, en), (en, fr), (fr, de), (de, fr)}
    mesh = compiler.compile(
        topology=TranslationGroupTopology.FULL_MESH,
        language_ids=(fr, en, de),
        hub_language_id=None,
        custom_routes=(),
        capabilities=capabilities(),
    )
    assert len(mesh) == 6
    assert compiler.compile(
        topology=TranslationGroupTopology.CUSTOM,
        language_ids=(fr, en),
        hub_language_id=None,
        custom_routes=((fr, en),),
        capabilities=capabilities(),
    ) == ((fr, en),)


@pytest.mark.parametrize("health", ["UNKNOWN", "DEGRADED"])
def test_full_mesh_fails_closed_when_provider_capability_is_unknown(health: str) -> None:
    with pytest.raises(ValueError, match="CAPABILITY"):
        TranslationRouteCompiler().compile(
            topology=TranslationGroupTopology.FULL_MESH,
            language_ids=(uuid4(), uuid4()),
            hub_language_id=None,
            custom_routes=(),
            capabilities=capabilities(supports_full_mesh=False, health=health),
        )


def test_visibility_compiler_materializes_scope_language_intersection() -> None:
    scope, language = uuid4(), uuid4()
    compiler = LanguageVisibilityCompiler()
    lazy = compiler.compile(
        policy=VisibilityPolicy.SCOPE_AND_LANGUAGE,
        guild_id=GUILD,
        language_profile_id=language,
        scope_id=scope,
        binding_role_id=None,
    )
    assert lazy.overwrites == ()
    assert asdict(lazy.roles_to_create[0]) == {
        "scope_id": scope,
        "language_profile_id": language,
        "name": lazy.roles_to_create[0].name,
        "permissions": 0,
        "hoist": False,
        "mentionable": False,
    }
    compiled = compiler.compile(
        policy=VisibilityPolicy.SCOPE_AND_LANGUAGE,
        guild_id=GUILD,
        language_profile_id=language,
        scope_id=scope,
        binding_role_id=42,
    )
    assert [(item.target_id, item.allow, item.deny) for item in compiled.overwrites] == [
        (GUILD, 0, VIEW_CHANNEL),
        (42, VIEW_CHANNEL, 0),
    ]
    assert (
        compiler.compile(
            policy=VisibilityPolicy.OPEN_ALL,
            guild_id=GUILD,
            language_profile_id=None,
            scope_id=None,
            binding_role_id=None,
        ).overwrites
        == ()
    )

    language_filtered = compiler.compile(
        policy=VisibilityPolicy.LANGUAGE_FILTERED,
        guild_id=GUILD,
        language_profile_id=language,
        scope_id=None,
        binding_role_id=None,
    )
    assert language_filtered.roles_to_create[0].scope_id is None
    assert "LANG" in language_filtered.roles_to_create[0].name
    language_filtered_bound = compiler.compile(
        policy=VisibilityPolicy.LANGUAGE_FILTERED,
        guild_id=GUILD,
        language_profile_id=language,
        scope_id=uuid4(),
        binding_role_id=43,
    )
    assert language_filtered_bound.reused_role_ids == (43,)
    assert [item.target_id for item in language_filtered_bound.overwrites] == [GUILD, 43]


def test_custom_visibility_requires_explicit_semantics() -> None:
    with pytest.raises(ValueError, match="explicit"):
        LanguageVisibilityCompiler().compile(
            policy=VisibilityPolicy.CUSTOM,
            guild_id=GUILD,
            language_profile_id=None,
            scope_id=None,
            binding_role_id=None,
            custom_policy={},
        )


def test_member_reconciliation_cannot_grant_scope_or_all_languages() -> None:
    joined, forbidden, fr, en = uuid4(), uuid4(), uuid4(), uuid4()
    desired = MemberTechnicalRoleReconciler().desired_roles(
        member_scope_ids={joined},
        visible_language_ids={fr, en},
        required_pairs={(joined, fr), (forbidden, en)},
        role_bindings={(joined, fr): 10, (forbidden, en): 20},
    )
    assert desired == {10}
    assert MemberTechnicalRoleReconciler().diff(
        current_role_ids={20}, desired_role_ids=set(desired)
    ) == {
        "assign": [10],
        "remove": [20],
        "member_specific_overwrites": [],
        "all_languages_role": None,
    }


def test_role_optimizer_reuses_global_pair_and_cleans_only_proven_unused() -> None:
    pair, unused, referenced = (uuid4(), uuid4()), (uuid4(), uuid4()), (uuid4(), uuid4())
    result = RoleOptimizer().optimize(
        required_pairs={pair},
        existing_bindings={pair: 10, unused: 20, referenced: 30},
        referenced_role_ids={30},
        member_role_ids=set(),
    )
    assert result["reuse"] == {pair: 10}
    assert result["create"] == []
    assert result["cleanup_role_ids"] == [20]


def test_role_and_overwrite_capacity_block_boundary_plus_one() -> None:
    engine = RoleCapacityEngine()
    assert engine.role_budget(current_count=249, required_bindings=1, reusable_bindings=0).allowed
    assert not engine.role_budget(
        current_count=250, required_bindings=1, reusable_bindings=0
    ).allowed
    assert engine.overwrite_budget(current_count=999, proposed_delta=1).allowed
    assert not engine.overwrite_budget(current_count=1000, proposed_delta=1).allowed


def test_provider_access_checks_every_variant_and_never_recommends_admin() -> None:
    required = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES
    coordinator = TranslationProviderCoordinator()
    missing = coordinator.access_preflight(
        bot_present=True, effective_permissions_by_variant={1: required, 2: VIEW_CHANNEL}
    )
    assert not missing.allowed and "SEND_MESSAGES" in missing.missing_permissions
    admin = coordinator.access_preflight(
        bot_present=True, effective_permissions_by_variant={1: required | ADMINISTRATOR}
    )
    assert admin.allowed and admin.warnings == ("PROVIDER_HAS_ADMINISTRATOR",)


@pytest.mark.asyncio
async def test_non_invasive_provider_is_manual_and_owns_message_content_requirement() -> None:
    async def probe(_: int) -> dict[str, object]:
        return {
            "supports_hub_and_spoke": True,
            "requires_message_content": True,
            "health": "READY",
        }

    async def health(_: int) -> dict[str, object]:
        return {"status": "READY"}

    provider = NonInvasiveExistingBotProvider(probe, health)
    observed = await provider.capabilities(GUILD)
    assert observed.requires_message_content
    assert observed.configuration_mode is ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED
    result = await TranslationProviderCoordinator().prepare(
        provider=provider,
        guild_id=GUILD,
        desired_group={"token": "must-not-leak"},
    )
    assert result.state.value == "MANUAL_CONFIGURATION_REQUIRED"
    assert result.verification_state == "PENDING_MANUAL_VERIFICATION"
    assert "must-not-leak" not in repr(result.payload)


def test_drift_needs_positive_deletion_evidence_and_is_non_destructive() -> None:
    detector = TranslationDriftDetector()
    assert (
        detector.observe_variant(
            current_state="ACTIVE", evidence="LIST_OMISSION", discord_resource_present=False
        )["state"]
        == "ACTIVE"
    )
    assert detector.observe_variant(
        current_state="ACTIVE", evidence="GATEWAY_DELETE", discord_resource_present=False
    ) == {"state": "MISSING", "drift": "MISSING_VARIANT", "repair": "PLAN_REQUIRED"}


def test_multilingual_clone_accepts_only_a_durable_group_business_intent() -> None:
    with pytest.raises(ValueError):
        MultilingualCloneInput.model_validate(
            {
                "destination_guild_id": "700000000000000002",
                "translation_group_id": str(uuid4()),
                "idempotency_key": "clone",
                "groups": [{"id": "client-authored-topology"}],
                "provider_requirements": [{"client_secret": "must-not-enter"}],
            }
        )


def test_stage08_openapi_exposes_workspace_lifecycle_plans_and_clone() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        "/api/v1/guilds/{guild_id}/translation-workspace",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/variants/plan",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/link",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/unlink",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/repair/plan",
        "/api/v1/guilds/{guild_id}/multilingual-clone/plan",
    }
    assert required <= set(paths)
    arbitrary_graph_aliases = {
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/structural-plan",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/provider/plan",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/routes/plan",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/link/plan",
        "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/unlink/plan",
    }
    assert arbitrary_graph_aliases.isdisjoint(paths)


def test_stage08_plan_policy_orders_create_phases_and_reverses_safe_deletes() -> None:
    def operation(resource: ResourceType, operation_type: OperationType) -> PlanOperation:
        return PlanOperation(
            uuid4(),
            operation_type,
            resource,
            f"stage08.{resource.value.lower()}.{operation_type.value.lower()}",
            freeze_json_object({}),
            freeze_json_object({}),
            (),
            CompensationClass.REVERSIBLE,
            RiskLevel.LOW,
            VerificationStrategy.TARGETED_GET,
            RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
            (),
        )

    creates = (
        operation(ResourceType.OVERWRITE, OperationType.UPSERT_OVERWRITE),
        operation(ResourceType.ROLE, OperationType.CREATE_ROLE),
        operation(ResourceType.CHANNEL, OperationType.CREATE_CHANNEL),
        operation(ResourceType.CATEGORY, OperationType.CREATE_CHANNEL),
    )
    ordered_creates = PlanningService._ordered(PlanningService._stage08_structural_order(creates))
    assert [item.resource_type for item in ordered_creates] == [
        ResourceType.CATEGORY,
        ResourceType.CHANNEL,
        ResourceType.ROLE,
        ResourceType.OVERWRITE,
    ]

    deletes = (
        operation(ResourceType.CATEGORY, OperationType.DELETE_CHANNEL),
        operation(ResourceType.CHANNEL, OperationType.DELETE_CHANNEL),
        operation(ResourceType.ROLE, OperationType.DELETE_ROLE),
        operation(ResourceType.OVERWRITE, OperationType.DELETE_OVERWRITE),
    )
    ordered_deletes = PlanningService._ordered(PlanningService._stage08_structural_order(deletes))
    assert [item.resource_type for item in ordered_deletes] == [
        ResourceType.OVERWRITE,
        ResourceType.ROLE,
        ResourceType.CHANNEL,
        ResourceType.CATEGORY,
    ]


@pytest.mark.asyncio
@pytest.mark.security
async def test_multilingual_clone_authorizes_source_then_destination_before_compilation() -> None:
    destination = 700000000000000002
    body = MultilingualCloneInput.model_validate(
        {
            "destination_guild_id": str(destination),
            "translation_group_id": str(uuid4()),
            "idempotency_key": "clone-authorized",
        }
    )
    session = cast(Any, SimpleNamespace(discord_user_id=99))
    request = cast(Any, SimpleNamespace(state=SimpleNamespace(correlation_id=uuid4())))

    source_denied_authorize = AsyncMock(side_effect=AuthorizationDenied())
    with pytest.raises(AuthorizationDenied):
        await multilingual_clone_plan(
            str(GUILD),
            body,
            request,
            session,
            cast(
                Any,
                SimpleNamespace(authorization=SimpleNamespace(authorize=source_denied_authorize)),
            ),
        )
    assert source_denied_authorize.await_count == 1
    assert source_denied_authorize.await_args.kwargs["guild_id"] == GUILD

    async def deny_destination(**kwargs: object) -> None:
        if kwargs["guild_id"] == destination:
            raise AuthorizationDenied()

    destination_denied_authorize = AsyncMock(side_effect=deny_destination)
    with pytest.raises(AuthorizationDenied):
        await multilingual_clone_plan(
            str(GUILD),
            body,
            request,
            session,
            cast(
                Any,
                SimpleNamespace(
                    authorization=SimpleNamespace(authorize=destination_denied_authorize)
                ),
            ),
        )
    assert [call.kwargs["guild_id"] for call in destination_denied_authorize.await_args_list] == [
        GUILD,
        destination,
    ]

    authorize = AsyncMock()
    portability = SimpleNamespace(
        export_live_translation_group=AsyncMock(
            return_value=(
                {"id": uuid4(), "content_hash": "a" * 64},
                True,
            )
        ),
        compile_stored=AsyncMock(
            return_value=(
                {"id": uuid4(), "status": "COMPILED"},
                {"id": uuid4(), "status": "DRAFT"},
                True,
            )
        ),
    )
    result = await multilingual_clone_plan(
        str(GUILD),
        body,
        request,
        session,
        cast(
            Any,
            SimpleNamespace(
                authorization=SimpleNamespace(authorize=authorize),
                portability=portability,
            ),
        ),
    )
    assert [call.kwargs["guild_id"] for call in authorize.await_args_list] == [
        GUILD,
        destination,
        destination,
    ]
    assert result["destination_plan_status"] == "DRAFT"
    assert result["provider_bindings_omitted"] is True
    portability.export_live_translation_group.assert_awaited_once()
    portability.compile_stored.assert_awaited_once()
