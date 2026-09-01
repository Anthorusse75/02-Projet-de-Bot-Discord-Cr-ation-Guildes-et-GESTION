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
    assert intents.guild_messages is False
    assert intents.message_content is False
    assert intents.presences is False
    assert member_data_capability(enable_member_events=False) is (
        MemberDataCapability.ON_DEMAND_MEMBER_LOOKUP
    )
    assert member_data_capability(enable_member_events=True) is (
        MemberDataCapability.FULL_MEMBER_EVENTS
    )


class TestCampaignMessageIntentContract:
    """REQ-MSG-030: ADR-008 gates the genuinely PRIVILEGED MESSAGE_CONTENT
    intent, not the non-privileged GUILD_MESSAGES one -- these prove the
    exact intent contract did.settings.config.Settings/did.runtime.py wire
    for the campaign-message-ancestry producing side."""

    def test_default_behavior_never_requests_guild_messages_or_message_content(self) -> None:
        intents = minimal_gateway_intents()
        assert intents.guild_messages is False
        assert intents.message_content is False

    def test_guild_messages_can_be_enabled_for_stage09_without_message_content(self) -> None:
        intents = minimal_gateway_intents(enable_campaign_message_events=True)
        assert intents.guild_messages is True
        assert intents.message_content is False

    def test_message_content_stays_disabled_by_default_even_with_guild_messages_on(self) -> None:
        intents = minimal_gateway_intents(
            enable_campaign_message_events=True, enable_message_content=False
        )
        assert intents.guild_messages is True
        assert intents.message_content is False

    def test_message_content_is_ignored_without_the_non_privileged_base_capability(self) -> None:
        # Defense in depth (Settings enforces the same dependency at
        # configuration time): requesting the privileged intent alone,
        # without campaign_message_events also being a deliberate choice,
        # never actually turns it on.
        intents = minimal_gateway_intents(
            enable_campaign_message_events=False, enable_message_content=True
        )
        assert intents.guild_messages is False
        assert intents.message_content is False

    def test_message_content_can_be_enabled_together_with_its_base_capability(self) -> None:
        intents = minimal_gateway_intents(
            enable_campaign_message_events=True, enable_message_content=True
        )
        assert intents.guild_messages is True
        assert intents.message_content is True

    def test_member_intent_remains_independently_controlled(self) -> None:
        intents = minimal_gateway_intents(
            enable_member_events=True, enable_campaign_message_events=False
        )
        assert intents.members is True
        assert intents.guild_messages is False
        assert intents.message_content is False

        intents = minimal_gateway_intents(
            enable_member_events=False, enable_campaign_message_events=True
        )
        assert intents.members is False
        assert intents.guild_messages is True


def test_contract_fixture_derived_from_official_docs_is_detected_only_by_flag() -> None:
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
            "THREAD_CREATE",
            {
                "guild_id": str(GUILD),
                "id": "333333333333333333",
                "type": 12,
                "position": 0,
                "parent_id": "222222222222222222",
                "name": "private-thread",
                "permission_overwrites": [],
                "thread_metadata": {"archived": False, "locked": True},
            },
            "channel_id",
        ),
        (
            "THREAD_DELETE",
            {
                "guild_id": str(GUILD),
                "id": "333333333333333333",
                "type": 12,
                "parent_id": "222222222222222222",
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


class TestMessageDispatchNormalization:
    """REQ-MSG-030: MESSAGE_CREATE/UPDATE/DELETE are only ever captured
    when did.settings.config.Settings.discord_campaign_message_events_enabled
    is on (see TestCampaignMessageIntentContract) -- once captured,
    normalization must extract ONLY structural message identity, never
    content/embeds/attachments/components, regardless of whether the raw
    Gateway payload happens to carry them (e.g. because MESSAGE_CONTENT is
    also enabled, or because the message is the bot's own -- Discord always
    includes an app's own sent-message content even without that intent)."""

    def test_message_create_extracts_only_structural_identity(self) -> None:
        envelope = normalize_gateway_dispatch(
            dispatch(
                "MESSAGE_CREATE",
                {
                    "id": "777777777777777777",
                    "channel_id": "666666666666666666",
                    "guild_id": str(GUILD),
                    "author": {"id": "888888888888888888", "bot": True},
                    "content": "this must never survive normalization",
                    "embeds": [{"title": "should also never survive"}],
                    "attachments": [{"filename": "secret.txt"}],
                    "components": [{"type": 1}],
                },
            ),
            discord_session_id=SESSION,
        )
        assert envelope is not None
        assert envelope.guild_id == GUILD
        assert envelope.payload == {
            "message_id": 777777777777777777,
            "channel_id": 666666666666666666,
            "author_discord_user_id": 888888888888888888,
            "author_is_bot": True,
        }
        assert "content" not in envelope.payload
        assert "embeds" not in envelope.payload
        assert "attachments" not in envelope.payload
        assert "components" not in envelope.payload

    def test_message_create_from_a_regular_member_is_not_marked_bot_authored(self) -> None:
        envelope = normalize_gateway_dispatch(
            dispatch(
                "MESSAGE_CREATE",
                {
                    "id": "777777777777777777",
                    "channel_id": "666666666666666666",
                    "guild_id": str(GUILD),
                    "author": {"id": "111111111111111112", "bot": False},
                    "content": "hello there",
                },
            ),
            discord_session_id=SESSION,
        )
        assert envelope is not None
        assert envelope.payload["author_is_bot"] is False
        assert envelope.payload["author_discord_user_id"] == 111111111111111112

    def test_message_update_extracts_only_structural_identity(self) -> None:
        envelope = normalize_gateway_dispatch(
            dispatch(
                "MESSAGE_UPDATE",
                {
                    "id": "777777777777777777",
                    "channel_id": "666666666666666666",
                    "guild_id": str(GUILD),
                    "author": {"id": "888888888888888888", "bot": True},
                    "content": "edited content must never survive",
                },
            ),
            discord_session_id=SESSION,
        )
        assert envelope is not None
        assert "content" not in envelope.payload
        assert envelope.payload["message_id"] == 777777777777777777

    def test_message_delete_extracts_only_message_and_channel_id(self) -> None:
        envelope = normalize_gateway_dispatch(
            dispatch(
                "MESSAGE_DELETE",
                {
                    "id": "777777777777777777",
                    "channel_id": "666666666666666666",
                    "guild_id": str(GUILD),
                },
            ),
            discord_session_id=SESSION,
        )
        assert envelope is not None
        assert envelope.payload == {
            "message_id": 777777777777777777,
            "channel_id": 666666666666666666,
        }


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
    assert envelope.payload["members"] == []
    assert envelope.payload["members_complete"] is False


def test_guild_create_proves_member_completeness_only_from_exact_count() -> None:
    member = {
        "user": {"id": "555555555555555555"},
        "roles": ["444444444444444444"],
    }
    complete = normalize_gateway_dispatch(
        dispatch(
            "GUILD_CREATE",
            {
                "id": str(GUILD),
                "name": "Guild",
                "owner_id": "999999999999999999",
                "channels": [],
                "roles": [],
                "member_count": 1,
                "members": [member],
            },
        ),
        discord_session_id=SESSION,
    )
    partial = normalize_gateway_dispatch(
        dispatch(
            "GUILD_CREATE",
            {
                "id": str(GUILD),
                "name": "Guild",
                "owner_id": "999999999999999999",
                "channels": [],
                "roles": [],
                "member_count": 2,
                "members": [member],
            },
        ),
        discord_session_id=SESSION,
    )

    assert complete is not None and partial is not None
    assert complete.payload["members_complete"] is True
    assert complete.payload["members"] == [
        {
            "discord_user_id": 555555555555555555,
            "role_ids": [444444444444444444],
            "is_bot": False,
        }
    ]
    assert partial.payload["members_complete"] is False
    assert partial.payload["members"] == []


def test_thread_metadata_and_initial_threads_are_normalized() -> None:
    thread = {
        "guild_id": str(GUILD),
        "id": "333333333333333333",
        "type": 12,
        "position": 0,
        "parent_id": "222222222222222222",
        "name": "private-thread",
        "permission_overwrites": [],
        "thread_metadata": {"archived": True, "locked": False},
    }
    direct = normalize_gateway_dispatch(
        dispatch("THREAD_UPDATE", thread), discord_session_id=SESSION
    )
    initial = normalize_gateway_dispatch(
        dispatch(
            "GUILD_CREATE",
            {
                "id": str(GUILD),
                "name": "Guild",
                "owner_id": "999999999999999999",
                "channels": [],
                "threads": [thread],
                "roles": [],
            },
        ),
        discord_session_id=SESSION,
    )

    assert direct is not None and initial is not None
    assert direct.payload["archived"] is True
    assert direct.payload["locked"] is False
    assert initial.payload["threads"] == [direct.payload]


def test_thread_sync_and_current_user_membership_signals_are_normalized() -> None:
    thread_id = 333333333333333333
    parent_id = 222222222222222222
    user_id = 555555555555555555
    thread = {
        "id": str(thread_id),
        "type": 12,
        "parent_id": str(parent_id),
        "name": "private-thread",
        "thread_metadata": {"archived": False, "locked": False},
        "member": {"id": str(thread_id)},
    }
    sync = normalize_gateway_dispatch(
        dispatch(
            "THREAD_LIST_SYNC",
            {
                "guild_id": str(GUILD),
                "channel_ids": [str(parent_id)],
                "threads": [thread],
                "members": [{"id": str(thread_id), "user_id": str(user_id)}],
            },
        ),
        discord_session_id=SESSION,
    )
    whole_guild_sync = normalize_gateway_dispatch(
        dispatch(
            "THREAD_LIST_SYNC",
            {"guild_id": str(GUILD), "threads": [], "members": []},
        ),
        discord_session_id=SESSION,
    )
    current_member = normalize_gateway_dispatch(
        dispatch(
            "THREAD_MEMBER_UPDATE",
            {"guild_id": str(GUILD), "id": str(thread_id), "user_id": str(user_id)},
        ),
        discord_session_id=SESSION,
    )
    members_changed = normalize_gateway_dispatch(
        dispatch(
            "THREAD_MEMBERS_UPDATE",
            {
                "guild_id": str(GUILD),
                "id": str(thread_id),
                "added_members": [{"user_id": str(user_id)}],
                "removed_member_ids": ["666666666666666666"],
            },
        ),
        discord_session_id=SESSION,
    )

    assert sync is not None
    assert sync.payload["channel_ids"] == [parent_id]
    assert sync.payload["threads"][0]["current_user_member"] is True
    assert sync.payload["members"] == [{"thread_id": thread_id, "discord_user_id": user_id}]
    assert whole_guild_sync is not None
    assert whole_guild_sync.payload["channel_ids"] is None
    assert current_member is not None
    assert current_member.payload["membership_state"] == "MEMBER"
    assert members_changed is not None
    assert members_changed.payload["added_user_ids"] == [user_id]


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
