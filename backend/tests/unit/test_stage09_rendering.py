"""Unit tests for WP12's real per-delivery content rendering
(did.campaigns.rendering): composes typed field extraction (REQ-MSG-013),
typed template variables (REQ-MSG-018), glossary protection, and the
fail-closed parser/protector pipeline into the one path a delivery's final
content is ever decided through.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.rendering import render_field_text, render_message_model
from did.domain.campaigns import GlossaryBehavior, GlossaryEntry, GlossaryMatchMode, GlossaryScope
from did.messaging.message_model import Embed, MessageModel
from did.messaging.protector import IntegrityViolation
from did.messaging.template_variables import TemplateVariableDefinition, TemplateVariableType
from did.messaging.translation_policy import FieldPath, TranslatableFieldKind, TranslationUnit

pytestmark = [pytest.mark.security]

CAMPAIGN_ID = uuid4()
GUILD_ID = 990000101
OWNER_A = 111


async def _identity_translate(masked_text: str) -> str:
    return masked_text


async def _uppercase_translate(masked_text: str) -> str:
    """A deliberately naive fake 'translation' that only ever reorders/
    transforms ordinary characters (never touches placeholders, which are
    already opaque tokens) -- proves the pipeline survives an actual
    transformation, not just the identity function."""
    return masked_text.upper()


class TestRenderFieldText:
    async def test_plain_text_with_no_variables_or_glossary_round_trips(self) -> None:
        unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), "Hello there!")
        result = await render_field_text(
            unit,
            target_language="en",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text=_identity_translate,
        )
        assert result == "Hello there!"

    async def test_translatable_text_variable_participates_in_translation(self) -> None:
        unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), "Subtitle: {{subtitle}}.")
        definitions = {
            "subtitle": TemplateVariableDefinition(
                "subtitle", TemplateVariableType.TRANSLATABLE_TEXT, value="big sale"
            )
        }
        result = await render_field_text(
            unit,
            target_language="en",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions=definitions,
            glossary_entries=(),
            translate_masked_text=_uppercase_translate,
        )
        # The variable's own text got uppercased along with the rest --
        # proof it was inlined as ordinary translatable prose, not protected.
        assert result == "SUBTITLE: BIG SALE."

    async def test_non_translatable_variable_survives_a_transformation_unchanged(self) -> None:
        unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), "Product: {{product}}.")
        definitions = {
            "product": TemplateVariableDefinition(
                "product", TemplateVariableType.NON_TRANSLATABLE, value="Acme Widget"
            )
        }
        result = await render_field_text(
            unit,
            target_language="de",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions=definitions,
            glossary_entries=(),
            translate_masked_text=_uppercase_translate,
        )
        # Surrounding prose is uppercased, but the protected variable's
        # value survives byte-identical regardless of "translation".
        assert result == "PRODUCT: Acme Widget."

    async def test_localized_value_variable_picks_the_target_language_value(self) -> None:
        unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), "Price: {{price}}.")
        definitions = {
            "price": TemplateVariableDefinition(
                "price",
                TemplateVariableType.LOCALIZED_VALUE,
                values_by_language={"en": "$5.00", "fr": "5,00 €"},
            )
        }
        result = await render_field_text(
            unit,
            target_language="fr",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions=definitions,
            glossary_entries=(),
            translate_masked_text=_identity_translate,
        )
        assert result == "Price: 5,00 €."

    async def test_do_not_translate_glossary_term_is_never_altered(self) -> None:
        unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), "Welcome to Acme Corp.")
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Acme Corp",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        result = await render_field_text(
            unit,
            target_language="de",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(entry,),
            translate_masked_text=_uppercase_translate,
        )
        # "Acme Corp" survives untouched (not uppercased) even though the
        # surrounding text was transformed by "translation".
        assert result == "WELCOME TO Acme Corp."

    async def test_forced_translation_glossary_term_restores_the_forced_value(self) -> None:
        unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), "We sell Widget here.")
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.CAMPAIGN,
            campaign_id=CAMPAIGN_ID,
            source_term="Widget",
            behavior=GlossaryBehavior.FORCED_TRANSLATION,
            forced_translation="Widgeto",
            target_language_code="es",
        )
        result = await render_field_text(
            unit,
            target_language="es",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(entry,),
            translate_masked_text=_identity_translate,
        )
        assert result == "We sell Widgeto here."

    async def test_protected_tokens_survive_both_layers_together(self) -> None:
        """Native protected tokens (URL/mention), a template variable, and
        a glossary term all in the same sentence -- proves the two-layer
        composition doesn't corrupt anything when everything fires at
        once."""
        unit = TranslationUnit(
            FieldPath(TranslatableFieldKind.CONTENT),
            "Hi <@123456789012345678>, welcome to Acme Corp! Your code is {{code}}. "
            "See https://example.com/x.",
        )
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Acme Corp",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        definitions = {
            "code": TemplateVariableDefinition(
                "code", TemplateVariableType.PROTECTED, value="XJ-19-Q"
            )
        }
        result = await render_field_text(
            unit,
            target_language="en",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions=definitions,
            glossary_entries=(entry,),
            translate_masked_text=_identity_translate,
        )
        assert result == (
            "Hi <@123456789012345678>, welcome to Acme Corp! Your code is XJ-19-Q. "
            "See https://example.com/x."
        )

    async def test_corrupted_translation_still_fails_closed(self) -> None:
        """A 'translation' that drops a protected placeholder must still
        raise IntegrityViolation through this composed pipeline exactly as
        it would through the single-layer pipeline."""
        unit = TranslationUnit(
            FieldPath(TranslatableFieldKind.CONTENT), "Ping <@123456789012345678> now."
        )

        async def _dropping_translate(masked_text: str) -> str:
            import re

            return re.sub(r"DIDPH\d{4}Q[0-9A-F]{8}ZH", "", masked_text, count=1)

        with pytest.raises(IntegrityViolation):
            await render_field_text(
                unit,
                target_language="en",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=_dropping_translate,
            )


class TestRenderMessageModel:
    async def test_only_translatable_fields_are_rendered_technical_fields_untouched(self) -> None:
        model = MessageModel(
            content="Hi {{name}}, welcome!",
            embeds=(
                Embed(
                    title="Announcement",
                    url="https://example.com/embed-target",
                    color=0x00FF00,
                ),
            ),
        )
        definitions = {
            "name": TemplateVariableDefinition(
                "name", TemplateVariableType.TRANSLATABLE_TEXT, value="Alex"
            )
        }
        result = await render_message_model(
            model,
            target_language="en",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions=definitions,
            glossary_entries=(),
            translate_masked_text=_uppercase_translate,
        )
        assert result.content == "HI ALEX, WELCOME!"
        assert result.embeds[0].title == "ANNOUNCEMENT"
        assert result.embeds[0].url == "https://example.com/embed-target"
        assert result.embeds[0].color == 0x00FF00

    async def test_none_translate_still_resolves_variables_and_glossary_source_language(
        self,
    ) -> None:
        model = MessageModel(content="Welcome to Acme Corp, {{name}}!")
        definitions = {
            "name": TemplateVariableDefinition(
                "name", TemplateVariableType.TRANSLATABLE_TEXT, value="Sam"
            )
        }
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Acme Corp",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
            match_mode=GlossaryMatchMode.EXACT,
        )
        result = await render_message_model(
            model,
            target_language="en",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions=definitions,
            glossary_entries=(entry,),
            translate_masked_text=None,
        )
        assert result.content == "Welcome to Acme Corp, Sam!"
