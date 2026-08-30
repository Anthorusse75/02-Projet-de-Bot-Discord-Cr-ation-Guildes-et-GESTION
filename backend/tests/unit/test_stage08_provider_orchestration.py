from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from did.api.stage08 import ProviderAccessInput
from did.application.translation.provider_orchestration import (
    Stage08ProviderOrchestrationService,
)
from did.application.translation.service import (
    READ_MESSAGE_HISTORY,
    SEND_MESSAGES,
    VIEW_CHANNEL,
)
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
from did.infrastructure.stage08_repository import Stage08NotFound

GUILD = 811111111111111111
PROVIDER_USER = 811111111111111112
CHANNEL = 811111111111111113


def provider_snapshot() -> tuple[GuildSnapshot, MemberSnapshot]:
    now = datetime.now(UTC)
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, now, now, now)
    permissions = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES
    roles = (RoleSnapshot(GUILD, GUILD, "@everyone", 0, permissions, False, fresh),)
    channel = ChannelSnapshot(
        GUILD,
        CHANNEL,
        ChannelType.GUILD_TEXT,
        0,
        None,
        "translated",
        (),
        True,
        ObservabilityState.VISIBLE,
        fresh,
    )
    coverage = CoverageSnapshot(
        GUILD,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "GATEWAY",
        1,
        known_channels=1,
        visible_channels=1,
        known_roles=1,
        overwrites_complete=True,
    )
    guild = GuildSnapshot(GUILD, GUILD + 99, roles, (channel,), coverage, fresh)
    member = MemberSnapshot(GUILD, PROVIDER_USER, (GUILD,), True, fresh, is_bot=True)
    return guild, member


def service() -> tuple[Stage08ProviderOrchestrationService, AsyncMock, AsyncMock]:
    group_id = uuid4()
    binding_id = uuid4()
    groups = AsyncMock()
    groups.workspace_group.return_value = {
        "id": group_id,
        "provider_binding_id": binding_id,
        "routing_mode": "FULL_MESH",
        "languages": [{"id": uuid4()}, {"id": uuid4()}],
        "channel_variants": [
            {"discord_channel_id": CHANNEL, "state": "ACTIVE"},
        ],
    }
    providers = AsyncMock()
    providers.get.return_value = {
        "id": binding_id,
        "provider_discord_user_id": PROVIDER_USER,
        "capabilities_json": {
            "supports_hub_and_spoke": True,
            "supports_full_mesh": False,
        },
        "status": "MANUAL_CONFIGURATION_REQUIRED",
    }
    providers.set_group_provider_state.return_value = {"status": "READY"}
    read_models = AsyncMock()
    read_models.guild_snapshot.return_value = provider_snapshot()
    return (
        Stage08ProviderOrchestrationService(
            read_models=read_models,
            groups=groups,
            providers=providers,
        ),
        groups,
        providers,
    )


async def test_provider_routing_eligibility_uses_durable_capabilities() -> None:
    orchestration, groups, providers = service()
    group_id = groups.workspace_group.return_value["id"]
    binding_id = providers.get.return_value["id"]
    access, authority = await orchestration.access_preflight(
        guild_id=GUILD,
        group_id=group_id,
        binding_id=binding_id,
    )
    assert access.allowed
    assert authority["source"] == "DURABLE_BINDING_AND_STAGE04_CACHE"
    assert authority["routing_supported"] is False
    with pytest.raises(ValueError, match="authoritative access or routing"):
        await orchestration.verify_manual_configuration(
            guild_id=GUILD,
            group_id=group_id,
            binding_id=binding_id,
            confirmed_manual_configuration=True,
        )
    providers.set_group_provider_state.assert_not_awaited()

    providers.get.return_value["capabilities_json"]["supports_full_mesh"] = True
    result = await orchestration.verify_manual_configuration(
        guild_id=GUILD,
        group_id=group_id,
        binding_id=binding_id,
        confirmed_manual_configuration=True,
    )
    assert result["state"] == "READY"
    providers.set_group_provider_state.assert_awaited_once_with(
        guild_id=GUILD,
        group_id=group_id,
        binding_id=binding_id,
        provider_status="READY",
        group_status="ACTIVE",
        verified=True,
    )


async def test_provider_binding_must_belong_to_url_group() -> None:
    orchestration, groups, providers = service()
    groups.workspace_group.return_value["provider_binding_id"] = uuid4()
    with pytest.raises(Stage08NotFound, match="does not belong"):
        await orchestration.access_preflight(
            guild_id=GUILD,
            group_id=groups.workspace_group.return_value["id"],
            binding_id=providers.get.return_value["id"],
        )
    providers.get.assert_not_awaited()


async def test_provider_access_fails_closed_without_active_variants() -> None:
    orchestration, groups, providers = service()
    groups.workspace_group.return_value["channel_variants"] = []
    access, authority = await orchestration.access_preflight(
        guild_id=GUILD,
        group_id=groups.workspace_group.return_value["id"],
        binding_id=providers.get.return_value["id"],
    )
    assert access.allowed is False
    assert access.state == "OBSERVABILITY_INCOMPLETE"
    assert authority["active_variant_count"] == 0
    assert authority["incomplete"] == ["NO_ACTIVE_VARIANTS"]


def test_provider_access_dto_rejects_browser_supplied_permissions_and_capabilities() -> None:
    with pytest.raises(ValueError):
        ProviderAccessInput.model_validate(
            {
                "binding_id": str(uuid4()),
                "bot_present": True,
                "supports_full_mesh": True,
                "effective_permissions_by_variant": {str(CHANNEL): str((1 << 53) - 1)},
            }
        )
