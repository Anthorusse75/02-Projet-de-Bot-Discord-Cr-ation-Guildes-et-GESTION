import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from did.application.discord_runtime import (
    GatewayContractError,
    GatewaySessionTracker,
    normalize_gateway_dispatch,
)
from did.bot.gateway.client import member_data_capability, minimal_gateway_intents
from did.domain.discord_runtime import (
    CHANNEL_OBFUSCATED_FLAG,
    CHANNEL_OBFUSCATION_GATEWAY_CAPABILITY,
    GatewayContinuity,
    MemberDataCapability,
)
from did.infrastructure.auth_repository import InstallationIdentityMismatch
from did.infrastructure.runtime_repository import RuntimeRepository

GUILD = 111111111111111111
SESSION = "gateway-session-stage03"


def dispatch(event_type: str, data: dict[str, object], *, sequence: int = 1) -> dict[str, object]:
    return {"op": 0, "s": sequence, "t": event_type, "d": data}


def test_minimal_intents_do_not_enable_privileged_or_message_content() -> None:
    intents = minimal_gateway_intents()
    assert intents.guilds is True
    assert intents.members is False
    assert intents.message_content is False
    assert intents.presences is False
    assert member_data_capability(enable_member_events=False) is (
        MemberDataCapability.ON_DEMAND_MEMBER_LOOKUP
    )
    assert member_data_capability(enable_member_events=True) is (
        MemberDataCapability.FULL_MEMBER_EVENTS
    )


def test_official_channel_obfuscation_fixture_is_detected_only_by_flag() -> None:
    fixture = json.loads(
        Path("backend/tests/fixtures/discord/channel_obfuscated_2026-08-12.json").read_text(
            encoding="utf-8"
        )
    )
    envelope = normalize_gateway_dispatch(fixture, discord_session_id=SESSION)
    assert envelope is not None
    assert envelope.guild_id == GUILD
    assert envelope.payload["is_obfuscated"] is True
    assert envelope.payload["flags"] & CHANNEL_OBFUSCATED_FLAG
    assert envelope.payload["name"] is None
    assert envelope.payload["topic"] is None
    assert envelope.payload["permission_overwrites"] == [
        {"id": GUILD, "type": 0, "allow": 0, "deny": 1 << 10}
    ]
    assert CHANNEL_OBFUSCATION_GATEWAY_CAPABILITY == 1 << 15


@pytest.mark.parametrize(
    ("event_type", "data", "expected"),
    [
        (
            "CHANNEL_CREATE",
            {
                "guild_id": str(GUILD),
                "id": "222222222222222222",
                "type": 0,
                "position": 1,
                "parent_id": None,
                "name": "general",
                "topic": "hello",
                "nsfw": False,
                "permission_overwrites": [],
            },
            "channel_id",
        ),
        (
            "CHANNEL_UPDATE",
            {
                "guild_id": str(GUILD),
                "id": "222222222222222222",
                "type": 0,
                "position": 2,
                "parent_id": None,
                "name": "updated",
                "permission_overwrites": [],
            },
            "channel_id",
        ),
        (
            "CHANNEL_DELETE",
            {
                "guild_id": str(GUILD),
                "id": "222222222222222222",
                "type": 0,
                "position": 2,
                "parent_id": None,
            },
            "channel_id",
        ),
        (
            "GUILD_ROLE_CREATE",
            {
                "guild_id": str(GUILD),
                "role": {
                    "id": "444444444444444444",
                    "name": "role",
                    "position": 1,
                    "permissions": "8",
                },
            },
            "role_id",
        ),
        (
            "GUILD_ROLE_UPDATE",
            {
                "guild_id": str(GUILD),
                "role": {
                    "id": "444444444444444444",
                    "name": "updated-role",
                    "position": 2,
                    "permissions": "16",
                },
            },
            "role_id",
        ),
        (
            "GUILD_ROLE_DELETE",
            {"guild_id": str(GUILD), "role_id": "444444444444444444"},
            "role_id",
        ),
        (
            "GUILD_MEMBER_UPDATE",
            {
                "guild_id": str(GUILD),
                "user": {"id": "555555555555555555"},
                "roles": ["444444444444444444"],
            },
            "discord_user_id",
        ),
    ],
)
def test_supported_dispatches_are_normalized(
    event_type: str, data: dict[str, object], expected: str
) -> None:
    envelope = normalize_gateway_dispatch(
        dispatch(event_type, data),
        discord_session_id=SESSION,
        received_at=datetime(2026, 8, 16, tzinfo=UTC),
    )
    assert envelope is not None
    assert envelope.guild_id == GUILD
    assert expected in envelope.payload
    assert envelope.discord_sequence == 1
    assert envelope.schema_version == 1


def test_guild_create_normalizes_initial_structure_without_member_list() -> None:
    envelope = normalize_gateway_dispatch(
        dispatch(
            "GUILD_CREATE",
            {
                "id": str(GUILD),
                "name": "Guild",
                "owner_id": "999999999999999999",
                "channels": [
                    {
                        "id": "222222222222222222",
                        "type": 4,
                        "position": 0,
                        "parent_id": None,
                        "name": "category",
                    }
                ],
                "roles": [
                    {
                        "id": str(GUILD),
                        "name": "@everyone",
                        "position": 0,
                        "permissions": "0",
                    }
                ],
            },
        ),
        discord_session_id=SESSION,
    )
    assert envelope is not None
    assert len(envelope.payload["channels"]) == 1
    assert len(envelope.payload["roles"]) == 1
    assert "members" not in envelope.payload


@pytest.mark.parametrize(
    "packet",
    [
        {"op": 0, "s": "bad", "t": "CHANNEL_CREATE", "d": {}},
        {"op": 0, "s": 1, "t": "CHANNEL_CREATE", "d": []},
        dispatch("CHANNEL_UPDATE", {"guild_id": str(GUILD), "id": "bad"}),
    ],
)
def test_malformed_payloads_fail_closed(packet: dict[str, object]) -> None:
    with pytest.raises(GatewayContractError):
        normalize_gateway_dispatch(packet, discord_session_id=SESSION)


def test_session_tracker_distinguishes_resume_new_session_and_gap() -> None:
    tracker = GatewaySessionTracker()
    assert tracker.ready("session-a") is GatewayContinuity.CONNECTED
    assert tracker.observe_sequence(10) is GatewayContinuity.CONNECTED
    assert tracker.observe_sequence(12) is GatewayContinuity.GAP_DETECTED
    assert tracker.resumed("session-a") is GatewayContinuity.RESUMED
    assert tracker.ready("session-b") is GatewayContinuity.NON_RESUMED
    with pytest.raises(GatewayContractError):
        tracker.resumed("session-a")


def test_runtime_bot_identity_is_bound_once_and_fails_closed_on_change() -> None:
    repository = RuntimeRepository(None)  # type: ignore[arg-type]
    repository.bind_bot_identity(application_id=123, bot_user_id=456)
    repository.bind_bot_identity(application_id=123, bot_user_id=456)
    with pytest.raises(InstallationIdentityMismatch):
        repository.bind_bot_identity(application_id=123, bot_user_id=789)
