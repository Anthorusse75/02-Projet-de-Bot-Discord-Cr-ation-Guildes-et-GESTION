"""Unit tests for REQ-MSG-020: MESSAGE_CONTENT capability requirement,
configuration blocker and simulation warning for event triggers.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.message_content_policy import (
    MessageContentCapabilityBlocked,
    simulate_message_content_dependency,
    validate_message_content_capability,
)
from did.domain.campaigns import CampaignTrigger

pytestmark = [pytest.mark.security]


class _FakeChecker:
    def __init__(self, *, available_guilds: set[int]) -> None:
        self.available_guilds = available_guilds
        self.calls: list[int] = []

    async def is_message_content_available(self, *, guild_id: int) -> bool:
        self.calls.append(guild_id)
        return guild_id in self.available_guilds


def _trigger(**overrides: object) -> CampaignTrigger:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=1,
        campaign_id=uuid4(),
        event_type="MEMBER_JOIN",
        condition_ast={"op": "ALWAYS"},
    )
    fields.update(overrides)
    return CampaignTrigger(**fields)  # type: ignore[arg-type]


class TestValidateMessageContentCapability:
    async def test_time_based_trigger_never_checks_the_capability(self) -> None:
        trigger = _trigger(requires_message_content=False)
        checker = _FakeChecker(available_guilds=set())
        await validate_message_content_capability(trigger, guild_id=111, checker=checker)
        assert checker.calls == []

    async def test_available_capability_passes(self) -> None:
        trigger = _trigger(requires_message_content=True)
        checker = _FakeChecker(available_guilds={111})
        await validate_message_content_capability(trigger, guild_id=111, checker=checker)
        assert checker.calls == [111]

    async def test_unavailable_capability_blocks_configuration(self) -> None:
        trigger = _trigger(requires_message_content=True)
        checker = _FakeChecker(available_guilds=set())
        with pytest.raises(MessageContentCapabilityBlocked) as excinfo:
            await validate_message_content_capability(trigger, guild_id=111, checker=checker)
        assert excinfo.value.guild_id == 111


class TestSimulateMessageContentDependency:
    async def test_time_based_trigger_yields_no_warning(self) -> None:
        trigger = _trigger(requires_message_content=False)
        checker = _FakeChecker(available_guilds=set())
        warning = await simulate_message_content_dependency(trigger, guild_id=111, checker=checker)
        assert warning is None
        assert checker.calls == []

    async def test_dependent_trigger_with_available_capability_is_non_blocking(self) -> None:
        trigger = _trigger(requires_message_content=True)
        checker = _FakeChecker(available_guilds={111})
        warning = await simulate_message_content_dependency(trigger, guild_id=111, checker=checker)
        assert warning is not None
        assert warning.available is True
        assert warning.is_blocking is False

    async def test_dependent_trigger_with_unavailable_capability_is_blocking(self) -> None:
        trigger = _trigger(requires_message_content=True)
        checker = _FakeChecker(available_guilds=set())
        warning = await simulate_message_content_dependency(trigger, guild_id=111, checker=checker)
        assert warning is not None
        assert warning.available is False
        assert warning.is_blocking is True
