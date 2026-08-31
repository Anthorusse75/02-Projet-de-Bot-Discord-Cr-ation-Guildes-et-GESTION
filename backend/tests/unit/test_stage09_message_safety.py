"""Unit tests for WP5: MessageModel limits, AllowedMentionsCompiler, the
explicit-attachment-policy edit payload builder, and safe owned-message
edit/delete authorization.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from did.domain.campaigns import AttachmentPolicy, DeliveryStatus, MessageDelivery
from did.messaging.allowed_mentions import (
    NO_MENTIONS,
    AllowedMentionsCompiler,
    AllowedMentionsPolicy,
    MentionPolicyError,
)
from did.messaging.edit_payload import EditPayload
from did.messaging.message_model import (
    ButtonStyle,
    ComponentActionRow,
    ComponentButton,
    Embed,
    EmbedField,
    MessageModel,
    MessageModelViolation,
    validate_message_model,
)
from did.messaging.mutation_guard import MessageMutationError, authorize_owned_message_mutation

pytestmark = [pytest.mark.security]


class TestMessageModelLimits:
    def test_valid_plain_content_passes(self) -> None:
        validate_message_model(MessageModel(content="hello world"))

    def test_blank_message_rejected(self) -> None:
        with pytest.raises(MessageModelViolation, match="content or"):
            validate_message_model(MessageModel(content=""))

    def test_embed_only_message_is_valid(self) -> None:
        validate_message_model(MessageModel(embeds=(Embed(title="t", description="d"),)))

    def test_content_over_2000_chars_rejected(self) -> None:
        with pytest.raises(MessageModelViolation, match="2000"):
            validate_message_model(MessageModel(content="x" * 2001))

    def test_more_than_ten_embeds_rejected(self) -> None:
        embeds = tuple(Embed(title=f"t{i}") for i in range(11))
        with pytest.raises(MessageModelViolation, match="10 embeds"):
            validate_message_model(MessageModel(content="ok", embeds=embeds))

    def test_embed_title_over_limit_rejected(self) -> None:
        with pytest.raises(MessageModelViolation, match="title"):
            validate_message_model(
                MessageModel(content="ok", embeds=(Embed(title="x" * 257),))
            )

    def test_more_than_25_fields_rejected(self) -> None:
        fields = tuple(EmbedField(name=f"n{i}", value="v") for i in range(26))
        with pytest.raises(MessageModelViolation, match="25 fields"):
            validate_message_model(MessageModel(content="ok", embeds=(Embed(fields=fields),)))

    def test_combined_embed_budget_over_6000_rejected(self) -> None:
        embed = Embed(description="x" * 4096, footer_text="y" * 2000)
        with pytest.raises(MessageModelViolation, match="6000"):
            validate_message_model(MessageModel(content="ok", embeds=(embed,)))

    def test_more_than_five_action_rows_rejected(self) -> None:
        row = ComponentActionRow(
            buttons=(ComponentButton(label="b", custom_id="x"),)
        )
        with pytest.raises(MessageModelViolation, match="action rows"):
            validate_message_model(
                MessageModel(content="ok", action_rows=tuple(row for _ in range(6)))
            )

    def test_link_button_requires_url_not_custom_id(self) -> None:
        with pytest.raises(MessageModelViolation, match="LINK buttons require a url"):
            validate_message_model(
                MessageModel(
                    content="ok",
                    action_rows=(
                        ComponentActionRow(
                            buttons=(ComponentButton(label="go", style=ButtonStyle.LINK),)
                        ),
                    ),
                )
            )

    def test_non_link_button_requires_custom_id(self) -> None:
        with pytest.raises(MessageModelViolation, match="custom_id"):
            validate_message_model(
                MessageModel(
                    content="ok",
                    action_rows=(ComponentActionRow(buttons=(ComponentButton(label="go"),)),),
                )
            )

    def test_valid_button_row_passes(self) -> None:
        validate_message_model(
            MessageModel(
                content="ok",
                action_rows=(
                    ComponentActionRow(
                        buttons=(
                            ComponentButton(label="Open", style=ButtonStyle.LINK, url="https://x"),
                            ComponentButton(label="Ack", custom_id="ack"),
                        )
                    ),
                ),
            )
        )


class TestAllowedMentionsCompiler:
    def test_default_policy_compiles_to_no_mentions(self) -> None:
        compiled = AllowedMentionsCompiler().compile(
            AllowedMentionsPolicy(), capability_allows_everyone=False
        )
        assert compiled == NO_MENTIONS
        assert compiled.to_discord_payload() == {"parse": [], "replied_user": False}

    def test_everyone_without_capability_is_rejected(self) -> None:
        with pytest.raises(MentionPolicyError):
            AllowedMentionsCompiler().compile(
                AllowedMentionsPolicy(allow_everyone=True), capability_allows_everyone=False
            )

    def test_everyone_with_capability_is_allowed(self) -> None:
        compiled = AllowedMentionsCompiler().compile(
            AllowedMentionsPolicy(allow_everyone=True), capability_allows_everyone=True
        )
        assert compiled.parse == ("everyone",)

    def test_explicit_users_never_combined_with_parse_users(self) -> None:
        compiled = AllowedMentionsCompiler().compile(
            AllowedMentionsPolicy(allowed_user_ids=(111, 222)), capability_allows_everyone=False
        )
        payload = compiled.to_discord_payload()
        assert payload["users"] == [111, 222]
        assert "users" not in compiled.parse

    def test_payload_omits_empty_users_roles_keys(self) -> None:
        compiled = AllowedMentionsCompiler().compile(
            AllowedMentionsPolicy(), capability_allows_everyone=False
        )
        payload = compiled.to_discord_payload()
        assert "users" not in payload
        assert "roles" not in payload

    def test_non_positive_user_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            AllowedMentionsPolicy(allowed_user_ids=(0,))


class TestEditPayloadAttachmentPolicy:
    def _payload(self, policy: AttachmentPolicy) -> EditPayload:
        return EditPayload(
            message_model=MessageModel(content="updated"),
            allowed_mentions=NO_MENTIONS,
            attachment_policy=policy,
        )

    def test_remove_all_sends_empty_attachments_list(self) -> None:
        kwargs = self._payload(AttachmentPolicy.REMOVE_ALL).to_discord_kwargs()
        assert kwargs["attachments"] == []

    def test_preserve_existing_omits_attachments_key(self) -> None:
        kwargs = self._payload(AttachmentPolicy.PRESERVE_EXISTING).to_discord_kwargs()
        assert "attachments" not in kwargs

    def test_every_edit_carries_allowed_mentions(self) -> None:
        kwargs = self._payload(AttachmentPolicy.PRESERVE_EXISTING).to_discord_kwargs()
        assert kwargs["allowed_mentions"] == {"parse": [], "replied_user": False}

    def test_over_limit_model_is_rejected_before_dispatch(self) -> None:
        payload = EditPayload(
            message_model=MessageModel(content="x" * 2001),
            allowed_mentions=NO_MENTIONS,
            attachment_policy=AttachmentPolicy.PRESERVE_EXISTING,
        )
        with pytest.raises(MessageModelViolation):
            payload.to_discord_kwargs()


class TestOwnedMessageMutationGuard:
    def _sent_delivery(self, **overrides: object) -> MessageDelivery:
        fields: dict[str, Any] = dict(
            id=uuid4(),
            guild_id=880000001,
            campaign_id=uuid4(),
            occurrence_id=uuid4(),
            target_id=uuid4(),
            delivery_key="k1",
            discord_channel_id=555,
            allowed_mentions_snapshot={"parse": []},
            status=DeliveryStatus.SENT,
            discord_message_id=999888777,
        )
        fields.update(overrides)
        return MessageDelivery(**fields)

    def test_owner_can_mutate_sent_delivery_in_correct_destination(self) -> None:
        delivery = self._sent_delivery()
        message_id = authorize_owned_message_mutation(
            delivery,
            actor_discord_user_id=42,
            campaign_owner_discord_user_id=42,
            expected_guild_id=880000001,
            expected_channel_id=555,
        )
        assert message_id == 999888777

    def test_non_owner_actor_rejected(self) -> None:
        delivery = self._sent_delivery()
        with pytest.raises(MessageMutationError, match="owning campaign"):
            authorize_owned_message_mutation(
                delivery,
                actor_discord_user_id=99,
                campaign_owner_discord_user_id=42,
                expected_guild_id=880000001,
                expected_channel_id=555,
            )

    def test_non_sent_delivery_rejected(self) -> None:
        delivery = self._sent_delivery(status=DeliveryStatus.PENDING, discord_message_id=None)
        with pytest.raises(MessageMutationError, match="no live Discord message"):
            authorize_owned_message_mutation(
                delivery,
                actor_discord_user_id=42,
                campaign_owner_discord_user_id=42,
                expected_guild_id=880000001,
                expected_channel_id=555,
            )

    def test_guild_mismatch_rejected(self) -> None:
        delivery = self._sent_delivery()
        with pytest.raises(MessageMutationError, match="guild mismatch"):
            authorize_owned_message_mutation(
                delivery,
                actor_discord_user_id=42,
                campaign_owner_discord_user_id=42,
                expected_guild_id=999999999,
                expected_channel_id=555,
            )

    def test_channel_mismatch_rejected(self) -> None:
        delivery = self._sent_delivery()
        with pytest.raises(MessageMutationError, match="channel mismatch"):
            authorize_owned_message_mutation(
                delivery,
                actor_discord_user_id=42,
                campaign_owner_discord_user_id=42,
                expected_guild_id=880000001,
                expected_channel_id=1,
            )
