from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from did.api.dependencies import ApiProblem
from did.api.stage04 import (
    OverwriteInput,
    PermissionRequest,
    ScopeRuleInput,
    SimulationRequest,
    VisibilityScopeCreate,
    _json_ids,
    capabilities,
    coverage,
    evaluate_permission,
    roles,
    simulate_permission,
    structure,
)
from did.application.auth.service import AuthorizationDenied
from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.oauth.stores import SessionData

GUILD = 630303030303030301
OWNER = 630303030303030302
ACTOR = 630303030303030303
CHANNEL = 630303030303030304
NOW = datetime(2026, 8, 17, tzinfo=UTC)


def snapshots() -> tuple[GuildSnapshot, MemberSnapshot]:
    current = FreshnessSnapshot(FreshnessState.FRESH, "LOCAL_CACHE", 1, NOW, NOW, NOW)
    role = RoleSnapshot(GUILD, GUILD, "@everyone", 0, 1 << 10, False, current)
    resource = ChannelSnapshot(
        GUILD,
        CHANNEL,
        ChannelType.GUILD_TEXT,
        0,
        None,
        "general",
        (),
        True,
        ObservabilityState.VISIBLE,
        current,
    )
    guild = GuildSnapshot(
        GUILD,
        OWNER,
        (role,),
        (resource,),
        CoverageSnapshot(
            GUILD,
            CoverageMode.FULL,
            FreshnessState.FRESH,
            "LOCAL_CACHE",
            1,
            1,
            1,
            0,
            1,
            True,
            True,
            True,
            "CONNECTED",
        ),
        current,
        source_versions=("projection:1",),
    )
    return guild, MemberSnapshot(GUILD, ACTOR, (), True, current)


class InstrumentedAuthorization:
    def __init__(self, events: list[str], *, deny: bool = False) -> None:
        self.events = events
        self.deny = deny

    async def authorize(self, **_: Any) -> None:
        self.events.append("authorize")
        if self.deny:
            raise AuthorizationDenied()


class InstrumentedRepository:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.guild, self.member = snapshots()

    async def guild_snapshot(self, guild_id: int, member_id: int):
        assert guild_id == GUILD
        self.events.append("postgres_projection")
        return self.guild, self.member

    async def bot_identity(self, guild_id: int) -> tuple[int, str]:
        assert guild_id == GUILD
        return ACTOR, "ACTIVE"

    async def member_snapshots(
        self, guild_id: int, member_ids: tuple[int, ...]
    ) -> tuple[MemberSnapshot, ...]:
        assert guild_id == GUILD
        return tuple(
            self.member
            if member_id == ACTOR
            else MemberSnapshot(
                GUILD,
                member_id,
                (),
                False,
                FreshnessSnapshot(FreshnessState.UNKNOWN, "LOCAL_CACHE", 1, None),
            )
            for member_id in member_ids
        )

    async def structure(self, guild_id: int):
        assert guild_id == GUILD
        self.events.append("postgres_projection")
        return {
            "snapshot": self.guild,
            "categories": [],
            "children": {},
            "roots": list(self.guild.channels),
            "threads": {},
        }


def session() -> SessionData:
    return SessionData("session", ACTOR, "csrf", GUILD, NOW, NOW, NOW + timedelta(hours=1), 1)


def container(events: list[str], *, deny: bool = False) -> Any:
    return SimpleNamespace(
        authorization=InstrumentedAuthorization(events, deny=deny),
        stage04_repository=InstrumentedRepository(events),
        runtime_repository=SimpleNamespace(metrics=RuntimeMetrics()),
    )


@pytest.mark.parametrize("endpoint", [structure, roles, coverage])
async def test_normal_read_endpoints_authorize_then_use_only_local_projection(
    endpoint: Any,
) -> None:
    events: list[str] = []
    services = container(events)
    if endpoint is structure:
        response = await endpoint(str(GUILD), session(), services, False)
    else:
        response = await endpoint(str(GUILD), session(), services)

    assert events == ["authorize", "postgres_projection"]
    assert response["guild_id"] == str(GUILD)
    assert response["discord_rest_calls"] == 0


async def test_permission_evaluation_is_cache_first_and_serializes_snowflakes_and_bits() -> None:
    events: list[str] = []
    response = await evaluate_permission(
        str(GUILD),
        PermissionRequest(
            view_as="VIEW_AS_MEMBER",
            subject_id=str(ACTOR),
            resource_id=str(CHANNEL),
            requested_permission="VIEW_CHANNEL",
        ),
        session(),
        container(events),
    )

    assert events == ["authorize", "postgres_projection"]
    assert response["subject_id"] == str(ACTOR)
    assert response["resource_id"] == str(CHANNEL)
    assert response["calculated_bits"] == str(1 << 10)
    assert response["outcome"] == "ALLOWED"


@pytest.mark.security
async def test_denied_tenant_authorization_happens_before_any_repository_disclosure() -> None:
    events: list[str] = []
    with pytest.raises(AuthorizationDenied):
        await structure(str(GUILD), session(), container(events, deny=True), False)
    assert events == ["authorize"]


def test_scope_rule_api_accepts_string_snowflakes_and_serializes_them_without_js_loss() -> None:
    huge_role = 1 << 60
    rule = ScopeRuleInput(
        rule_type="DISCORD_ROLE",
        config={"role_ids": [str(huge_role)]},
        priority=1,
    )
    assert rule.config == {"role_ids": [huge_role]}
    assert _json_ids(rule.model_dump())["config"]["role_ids"] == [str(huge_role)]


@pytest.mark.parametrize(
    "config",
    [{"role_ids": []}, {"role_ids": ["10", "10"]}, {"role_ids": ["10", "11"]}],
)
def test_single_role_scope_rule_rejects_invalid_or_ambiguous_configs(
    config: dict[str, list[str]],
) -> None:
    with pytest.raises(ValueError):
        ScopeRuleInput(rule_type="DISCORD_ROLE", config=config, priority=1)


async def test_unknown_permission_and_missing_view_as_role_have_stable_api_codes() -> None:
    services = container([])
    with pytest.raises(ApiProblem) as unknown:
        await evaluate_permission(
            str(GUILD),
            PermissionRequest(
                view_as="VIEW_AS_MEMBER",
                subject_id=str(ACTOR),
                requested_permission="FUTURE_PERMISSION",
            ),
            session(),
            services,
        )
    assert (unknown.value.status_code, unknown.value.code) == (422, "UNKNOWN_PERMISSION")

    with pytest.raises(ApiProblem) as missing_role:
        await evaluate_permission(
            str(GUILD),
            PermissionRequest(
                view_as="VIEW_AS_ROLE",
                role_id="630303030303039999",
                requested_permission="VIEW_CHANNEL",
            ),
            session(),
            services,
        )
    assert (missing_role.value.status_code, missing_role.value.code) == (404, "ROLE_NOT_FOUND")


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("MANAGE_CHANNEL", "CHANNEL_REQUIRED"),
        ("MANAGE_OVERWRITES", "CHANNEL_REQUIRED"),
        ("SEND_MESSAGE", "CHANNEL_REQUIRED"),
        ("MANAGE_THREAD", "CHANNEL_REQUIRED"),
        ("MANAGE_ROLE", "TARGET_ROLE_REQUIRED"),
        ("ASSIGN_ROLE", "TARGET_ROLE_REQUIRED"),
    ],
)
async def test_capability_operations_require_their_target(
    operation: str, expected_code: str
) -> None:
    from did.permissions.capabilities import BotOperation

    with pytest.raises(ApiProblem) as problem:
        await capabilities(
            str(GUILD),
            session(),
            container([]),
            BotOperation(operation),
            None,
            None,
        )
    assert (problem.value.status_code, problem.value.code) == (422, expected_code)


def test_visibility_scope_type_and_logical_group_are_coupled_at_api_boundary() -> None:
    from uuid import uuid4

    with pytest.raises(ValueError):
        VisibilityScopeCreate(scope_type="LOGICAL_GROUP", scope_key="group", name="Group")
    with pytest.raises(ValueError):
        VisibilityScopeCreate(
            scope_type="GLOBAL",
            scope_key="global",
            name="Global",
            logical_group_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("target_type", "code"),
    [(0, "OVERWRITE_ROLE_UNRESOLVED"), (1, "OVERWRITE_MEMBER_UNRESOLVED")],
)
async def test_simulation_rejects_unresolved_overwrite_targets(target_type: int, code: str) -> None:
    body = SimulationRequest(
        resource_id=str(CHANNEL),
        subject_ids=[str(ACTOR)],
        proposed_overwrites=[
            OverwriteInput(
                target_id="630303030303039999",
                target_type=target_type,
                allow="0",
                deny="0",
            )
        ],
    )
    with pytest.raises(ApiProblem) as problem:
        await simulate_permission(str(GUILD), body, session(), container([]))
    assert (problem.value.status_code, problem.value.code) == (422, code)
