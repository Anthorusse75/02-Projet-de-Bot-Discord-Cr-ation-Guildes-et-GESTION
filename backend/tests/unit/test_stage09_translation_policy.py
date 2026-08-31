"""Unit tests for REQ-MSG-013: explicit, typed field-by-field MessageModel
translation policy. Technical fields (url, color, custom_id, button style,
component structure) must never reach a translator; only named text fields
do, and only those fields change in the rebuilt model.
"""

from __future__ import annotations

import pytest

from did.messaging.message_model import (
    ButtonStyle,
    ComponentActionRow,
    ComponentButton,
    Embed,
    EmbedField,
    MessageModel,
)
from did.messaging.translation_policy import (
    FieldPath,
    TranslatableFieldKind,
    TranslationUnit,
    apply_translated_units,
    extract_translatable_units,
    translate_message_model,
)

pytestmark = [pytest.mark.security]


def _full_model() -> MessageModel:
    return MessageModel(
        content="Hello everyone!",
        embeds=(
            Embed(
                title="Announcement",
                description="Big news today.",
                url="https://example.com/embed-target",
                color=0x00FF00,
                footer_text="Sent by DID",
                author_name="Campaign Bot",
                fields=(
                    EmbedField(name="Field A", value="Value A"),
                    EmbedField(name="Field B", value="Value B", inline=True),
                ),
            ),
        ),
        action_rows=(
            ComponentActionRow(
                buttons=(
                    ComponentButton(
                        label="Learn more", style=ButtonStyle.LINK, url="https://example.com/learn"
                    ),
                    ComponentButton(label="Confirm", custom_id="confirm_action"),
                )
            ),
        ),
    )


class TestExtractTranslatableUnits:
    def test_extracts_every_translatable_field_exactly_once(self) -> None:
        model = _full_model()
        units = extract_translatable_units(model)
        kinds = [u.path.kind for u in units]
        assert kinds.count(TranslatableFieldKind.CONTENT) == 1
        assert kinds.count(TranslatableFieldKind.EMBED_TITLE) == 1
        assert kinds.count(TranslatableFieldKind.EMBED_DESCRIPTION) == 1
        assert kinds.count(TranslatableFieldKind.EMBED_FOOTER_TEXT) == 1
        assert kinds.count(TranslatableFieldKind.EMBED_AUTHOR_NAME) == 1
        assert kinds.count(TranslatableFieldKind.EMBED_FIELD_NAME) == 2
        assert kinds.count(TranslatableFieldKind.EMBED_FIELD_VALUE) == 2
        assert kinds.count(TranslatableFieldKind.BUTTON_LABEL) == 2

    def test_never_extracts_technical_fields(self) -> None:
        model = _full_model()
        units = extract_translatable_units(model)
        texts = {u.text for u in units}
        assert "https://example.com/embed-target" not in texts
        assert "https://example.com/learn" not in texts
        assert "confirm_action" not in texts
        assert "0" not in texts and str(0x00FF00) not in texts

    def test_blank_optional_fields_are_skipped(self) -> None:
        model = MessageModel(content="Only content, no embeds.")
        units = extract_translatable_units(model)
        assert len(units) == 1
        assert units[0].path.kind is TranslatableFieldKind.CONTENT


class TestApplyTranslatedUnits:
    def test_replaces_only_the_targeted_text_fields(self) -> None:
        model = _full_model()
        translations = {
            FieldPath(TranslatableFieldKind.CONTENT): "Bonjour tout le monde !",
            FieldPath(TranslatableFieldKind.EMBED_TITLE, embed_index=0): "Annonce",
        }
        rebuilt = apply_translated_units(model, translations)
        assert rebuilt.content == "Bonjour tout le monde !"
        assert rebuilt.embeds[0].title == "Annonce"
        # Untouched translatable fields keep their original text.
        assert rebuilt.embeds[0].description == "Big news today."

    def test_never_mutates_technical_fields(self) -> None:
        model = _full_model()
        translations = {
            FieldPath(TranslatableFieldKind.CONTENT): "Bonjour !",
            FieldPath(TranslatableFieldKind.EMBED_TITLE, embed_index=0): "Annonce",
            FieldPath(TranslatableFieldKind.EMBED_DESCRIPTION, embed_index=0): "Grande nouvelle.",
            FieldPath(TranslatableFieldKind.EMBED_FOOTER_TEXT, embed_index=0): "Envoyé par DID",
            FieldPath(TranslatableFieldKind.EMBED_AUTHOR_NAME, embed_index=0): "Bot de campagne",
            FieldPath(
                TranslatableFieldKind.EMBED_FIELD_NAME, embed_index=0, field_index=0
            ): "Champ A",
            FieldPath(
                TranslatableFieldKind.EMBED_FIELD_VALUE, embed_index=0, field_index=0
            ): "Valeur A",
            FieldPath(TranslatableFieldKind.BUTTON_LABEL, action_row_index=0, button_index=0): (
                "En savoir plus"
            ),
            FieldPath(TranslatableFieldKind.BUTTON_LABEL, action_row_index=0, button_index=1): (
                "Confirmer"
            ),
        }
        rebuilt = apply_translated_units(model, translations)
        assert rebuilt.embeds[0].url == model.embeds[0].url
        assert rebuilt.embeds[0].color == model.embeds[0].color
        assert rebuilt.action_rows[0].buttons[0].url == model.action_rows[0].buttons[0].url
        assert (
            rebuilt.action_rows[0].buttons[1].custom_id == model.action_rows[0].buttons[1].custom_id
        )
        assert len(rebuilt.action_rows[0].buttons) == len(model.action_rows[0].buttons)
        assert len(rebuilt.embeds) == len(model.embeds)

    def test_path_absent_from_translations_keeps_original_text(self) -> None:
        model = _full_model()
        rebuilt = apply_translated_units(model, {})
        assert rebuilt == model


class TestTranslateMessageModel:
    async def test_translates_every_unit_and_rebuilds_correctly(self) -> None:
        model = _full_model()
        seen: list[TranslationUnit] = []

        async def fake_translate(unit: TranslationUnit) -> str:
            seen.append(unit)
            return f"[{unit.path.kind.value}] {unit.text}"

        rebuilt = await translate_message_model(model, translate_unit=fake_translate)
        assert rebuilt.content == "[CONTENT] Hello everyone!"
        assert rebuilt.embeds[0].title == "[EMBED_TITLE] Announcement"
        assert rebuilt.action_rows[0].buttons[0].label == "[BUTTON_LABEL] Learn more"
        # Every technical field survives untouched.
        assert rebuilt.embeds[0].url == model.embeds[0].url
        assert rebuilt.action_rows[0].buttons[1].custom_id == "confirm_action"
        assert len(seen) == len(extract_translatable_units(model))

    async def test_a_failing_unit_translation_propagates_not_silently_falls_back(self) -> None:
        model = MessageModel(content="Hello")

        async def failing_translate(unit: TranslationUnit) -> str:
            raise RuntimeError("provider unavailable")

        with pytest.raises(RuntimeError, match="provider unavailable"):
            await translate_message_model(model, translate_unit=failing_translate)
