"""Unit tests for WP6/REQ-MSG-029: proves the exact request payload
discord.py builds actually includes ``enforce_nonce: True`` whenever a
nonce is supplied -- the corrected finding after an earlier session
incorrectly concluded enforce_nonce was unavailable in discord.py==2.7.1
(a silently-failed recursive grep on this repo's accented path, not a real
library limitation; see the module docstring in
``did.infrastructure.discord_message_sender``).
"""

from __future__ import annotations

import discord
import pytest
from discord.http import handle_message_parameters

from did.campaigns.delivery_reconciliation import generate_delivery_nonce
from did.domain.campaigns import AttachmentPolicy
from did.domain.message_sending import DiscordSendError
from did.infrastructure.discord_message_sender import (
    DiscordPyMessageSender,
    _build_discord_allowed_mentions,
)
from did.messaging.allowed_mentions import NO_MENTIONS
from did.messaging.edit_payload import EditPayload, NewAttachment
from did.messaging.message_model import MessageModel

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
        client = discord.Client(intents=discord.Intents.none())
        sender = DiscordPyMessageSender(client)
        assert sender is not None


class _FakeMessage:
    def __init__(self) -> None:
        self.edit_calls: list[dict[str, object]] = []

    async def edit(self, **kwargs: object) -> None:
        self.edit_calls.append(kwargs)


class _FakeChannel:
    def __init__(self, message: _FakeMessage) -> None:
        self._message = message

    async def fetch_message(self, message_id: int) -> _FakeMessage:
        return self._message


class TestEditReplaceAllAttachmentConversion:
    """External-review adapter-level test: REPLACE_ALL's NewAttachment
    entries must actually reach message.edit() as real discord.File objects
    under the ``attachments`` kwarg -- not silently dropped."""

    @pytest.mark.asyncio
    async def test_replace_all_converts_new_attachments_to_discord_files(self) -> None:
        client = discord.Client(intents=discord.Intents.none())
        sender = DiscordPyMessageSender(client)
        fake_message = _FakeMessage()
        fake_channel = _FakeChannel(fake_message)
        sender._get_channel = lambda channel_id: _async_return(fake_channel)  # type: ignore[method-assign,assignment,return-value]

        attachment = NewAttachment(filename="report.pdf", content=b"%PDF-1.4 fake")
        payload = EditPayload(
            message_model=MessageModel(content="updated"),
            allowed_mentions=NO_MENTIONS,
            attachment_policy=AttachmentPolicy.REPLACE_ALL,
            new_attachments=(attachment,),
        )

        await sender.edit(channel_id=123, message_id=456, payload=payload)

        assert len(fake_message.edit_calls) == 1
        sent_kwargs = fake_message.edit_calls[0]
        assert "new_attachments" not in sent_kwargs
        files = sent_kwargs["attachments"]
        assert isinstance(files, list)
        assert len(files) == 1
        assert isinstance(files[0], discord.File)
        assert files[0].filename == "report.pdf"

    @pytest.mark.asyncio
    async def test_preserve_existing_never_sets_attachments_key(self) -> None:
        client = discord.Client(intents=discord.Intents.none())
        sender = DiscordPyMessageSender(client)
        fake_message = _FakeMessage()
        fake_channel = _FakeChannel(fake_message)
        sender._get_channel = lambda channel_id: _async_return(fake_channel)  # type: ignore[method-assign,assignment,return-value]

        payload = EditPayload(
            message_model=MessageModel(content="updated"),
            allowed_mentions=NO_MENTIONS,
            attachment_policy=AttachmentPolicy.PRESERVE_EXISTING,
        )
        await sender.edit(channel_id=123, message_id=456, payload=payload)

        assert "attachments" not in fake_message.edit_calls[0]


async def _async_return(value: object) -> object:
    return value


class _FakeHttpResponse:
    def __init__(self, status: int, reason: str = "Error") -> None:
        self.status = status
        self.reason = reason


class _RaisingChannel:
    """Fake Messageable whose .send() raises a caller-supplied exception --
    used to prove the adapter classifies REAL discord.py exception classes
    into the correct Stage09 DiscordSendError/ambiguous-exception category,
    not just a fake sender manually raising DiscordSendError."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def send(self, **kwargs: object) -> object:
        raise self._exc


class TestRealDiscordExceptionClassification:
    """External-review finding (fourth remediation pass): the REAL adapter
    must translate discord.py's own exception hierarchy into the
    DiscordSendError (definitively known failure) vs. ambiguous-exception
    (UNKNOWN_OUTCOME) contract -- previously nothing did this at all, so
    every discord.py exception happened to fall through as "ambiguous" by
    accident, even a clean 403/404."""

    def _sender(self, exc: BaseException) -> DiscordPyMessageSender:
        client = discord.Client(intents=discord.Intents.none())
        sender = DiscordPyMessageSender(client)
        sender._get_channel = lambda channel_id: _async_return(  # type: ignore[method-assign,assignment,return-value]
            _RaisingChannel(exc)
        )
        return sender

    async def _attempt_send(self, sender: DiscordPyMessageSender) -> None:
        await sender.send(
            channel_id=123,
            message=MessageModel(content="hi"),
            allowed_mentions=NO_MENTIONS,
            nonce="n1",
        )

    @pytest.mark.asyncio
    async def test_forbidden_403_is_a_definitive_known_failure(self) -> None:
        exc = discord.Forbidden(_FakeHttpResponse(403), "missing SEND_MESSAGES")
        sender = self._sender(exc)
        with pytest.raises(DiscordSendError):
            await self._attempt_send(sender)

    @pytest.mark.asyncio
    async def test_not_found_404_is_a_definitive_known_failure(self) -> None:
        exc = discord.NotFound(_FakeHttpResponse(404), "unknown channel")
        sender = self._sender(exc)
        with pytest.raises(DiscordSendError):
            await self._attempt_send(sender)

    @pytest.mark.asyncio
    async def test_generic_4xx_validation_error_is_a_definitive_known_failure(self) -> None:
        exc = discord.HTTPException(_FakeHttpResponse(400), "invalid form body")
        sender = self._sender(exc)
        with pytest.raises(DiscordSendError):
            await self._attempt_send(sender)

    @pytest.mark.asyncio
    async def test_rate_limited_429_is_ambiguous_not_a_known_failure(self) -> None:
        """discord.py's own client-side rate limiter already retries before
        ever raising -- a 429 reaching here means that retry was exhausted,
        which is an operational/transport concern, not proof Discord
        rejected the message. Must NOT become DiscordSendError."""
        exc = discord.HTTPException(_FakeHttpResponse(429), "rate limited")
        sender = self._sender(exc)
        with pytest.raises(discord.HTTPException) as excinfo:
            await self._attempt_send(sender)
        assert not isinstance(excinfo.value, DiscordSendError)

    @pytest.mark.asyncio
    async def test_server_error_5xx_is_ambiguous_not_a_known_failure(self) -> None:
        """A 5xx means the request may have been processed server-side
        before the error response -- outcome-ambiguous."""
        exc = discord.DiscordServerError(_FakeHttpResponse(503), "internal server error")
        sender = self._sender(exc)
        with pytest.raises(discord.HTTPException) as excinfo:
            await self._attempt_send(sender)
        assert not isinstance(excinfo.value, DiscordSendError)

    @pytest.mark.asyncio
    async def test_connection_reset_propagates_unwrapped_as_ambiguous(self) -> None:
        sender = self._sender(ConnectionResetError("connection reset by peer"))
        with pytest.raises(ConnectionResetError) as excinfo:
            await self._attempt_send(sender)
        assert not isinstance(excinfo.value, DiscordSendError)

    @pytest.mark.asyncio
    async def test_timeout_propagates_unwrapped_as_ambiguous(self) -> None:
        sender = self._sender(TimeoutError("timed out"))
        with pytest.raises(TimeoutError) as excinfo:
            await self._attempt_send(sender)
        assert not isinstance(excinfo.value, DiscordSendError)
