"""Unit tests for WP6/REQ-MSG-029: proves the exact request payload
discord.py builds actually includes ``enforce_nonce: True`` whenever a
nonce is supplied -- the corrected finding after an earlier session
incorrectly concluded enforce_nonce was unavailable in discord.py==2.7.1
(a silently-failed recursive grep on this repo's accented path, not a real
library limitation; see the module docstring in
``did.infrastructure.discord_message_sender``).
"""

from __future__ import annotations

import pytest
from discord.http import handle_message_parameters

from did.campaigns.delivery_reconciliation import generate_delivery_nonce
from did.infrastructure.discord_message_sender import (
    DiscordPyMessageSender,
    _build_discord_allowed_mentions,
)
from did.messaging.allowed_mentions import NO_MENTIONS

pytestmark = [pytest.mark.security]


class TestEnforceNonceIsAlwaysSubmittedWithANonce:
    def test_payload_includes_enforce_nonce_true_when_nonce_given(self) -> None:
        with handle_message_parameters(content="hello", nonce="abc123") as params:
            assert params.payload is not None
            assert params.payload["nonce"] == "abc123"
            assert params.payload["enforce_nonce"] is True

    def test_payload_has_no_enforce_nonce_key_without_a_nonce(self) -> None:
        with handle_message_parameters(content="hello") as params:
            assert params.payload is not None
            assert "enforce_nonce" not in params.payload
            assert "nonce" not in params.payload

    def test_real_generated_delivery_nonce_round_trips_into_the_payload(self) -> None:
        nonce = generate_delivery_nonce()
        with handle_message_parameters(content="campaign message", nonce=nonce) as params:
            assert params.payload is not None
            assert params.payload["nonce"] == nonce
            assert params.payload["enforce_nonce"] is True

    def test_nonce_is_stringified_in_the_wire_payload(self) -> None:
        """Discord's nonce field is a string on the wire even though the
        Python API accepts int|str -- confirms our str-typed nonce needs no
        conversion and an int nonce would be coerced identically."""
        with handle_message_parameters(content="x", nonce=123456789) as params:
            assert params.payload is not None
            assert params.payload["nonce"] == "123456789"
            assert isinstance(params.payload["nonce"], str)


class TestAdapterConstructsAllowedMentionsCorrectly:
    def test_default_compiled_mentions_become_a_fully_closed_discord_allowed_mentions(
        self,
    ) -> None:
        result = _build_discord_allowed_mentions(NO_MENTIONS)
        assert result.everyone is False
        assert result.users is False
        assert result.roles is False


class TestDiscordPyMessageSenderConstructible:
    def test_sender_wraps_a_client_without_touching_the_network(self) -> None:
        import discord

        client = discord.Client(intents=discord.Intents.none())
        sender = DiscordPyMessageSender(client)
        assert sender is not None
