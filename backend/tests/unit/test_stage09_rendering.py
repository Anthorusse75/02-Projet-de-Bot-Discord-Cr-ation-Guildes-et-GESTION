"""Unit tests for WP12's real per-delivery content rendering
(did.campaigns.rendering): composes typed field extraction (REQ-MSG-013),
typed template variables (REQ-MSG-018), glossary protection, and the
fail-closed parser/protector pipeline into the one path a delivery's final
content is ever decided through.
"""

from __future__ import annotations

import logging
import re
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


def _mutate_one_placeholder(text: str) -> str:
    """Simulates a real, externally-observed provider failure mode
    (mission: "STAGE09 -- FINAL TRANSLATION INTEGRITY FINDING"): the
    provider does not drop or duplicate a placeholder (that's a separate,
    already-covered failure mode) -- it transforms ONE issued placeholder
    into a DIFFERENT token that is still shaped exactly like a valid DIDPH
    placeholder (same ``DIDPH{index:04d}Q{8 hex}ZH`` pattern), by flipping
    one hex digit of the nonce. This is exactly the "invented unknown
    placeholder token" case a real benchmark run isolated on
    ``es-inline-code-and-block-mixed`` (ES->FR, FULL_MASKED_MESSAGE, 1/312)."""
    match = re.search(r"DIDPH(\d{4})Q([0-9A-F]{8})ZH", text)
    assert match is not None, "fixture text must contain at least one placeholder"
    index, nonce = match.group(1), match.group(2)
    flipped_char = "1" if nonce[-1] != "1" else "2"
    mutated = f"DIDPH{index}Q{nonce[:-1]}{flipped_char}ZH"
    return text[: match.start()] + mutated + text[match.end() :]


class TestBoundedIntegrityRetryOnPlaceholderMutation:
    """Deterministic regression coverage for the googletrans intermittent
    placeholder-mutation finding: a provider output that changes an issued
    placeholder into a different, still valid-looking DIDPH token must
    never reach publication, and the bounded-retry recovery path (fresh
    placeholders regenerated per attempt, never an unbounded loop) must be
    exercised, not merely asserted."""

    UNIT = TranslationUnit(
        FieldPath(TranslatableFieldKind.CONTENT), "Ping <@123456789012345678> now."
    )

    async def test_a_provider_that_always_mutates_the_placeholder_fails_closed(self) -> None:
        """No corrupted candidate reaches the caller even after retrying --
        the FINAL attempt's failure still propagates as IntegrityViolation,
        proving retry is recovery, never a relaxation of the fail-closed
        guarantee."""
        calls = 0

        async def _always_corrupt(masked_text: str) -> str:
            nonlocal calls
            calls += 1
            return _mutate_one_placeholder(masked_text)

        with pytest.raises(IntegrityViolation, match="invented unknown placeholder"):
            await render_field_text(
                self.UNIT,
                target_language="fr",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=_always_corrupt,
            )
        # Exactly the default bound (2), never open-ended.
        assert calls == 2

    async def test_retry_recovers_when_only_the_first_attempt_is_corrupted(self) -> None:
        """The real-world evidence this remediation is built on: a fresh
        retry with regenerated placeholders succeeded 5/5 times against the
        exact content/direction that failed once in the real benchmark.
        This test proves the mechanism, not just the anecdote: attempt 1's
        placeholder is corrupted, attempt 2 (necessarily a DIFFERENT,
        freshly-generated placeholder, since protect() draws a new random
        nonce every call) is left untouched, and the final result is the
        correct, uncorrupted restoration."""
        calls = 0

        async def _corrupt_first_call_only(masked_text: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _mutate_one_placeholder(masked_text)
            return masked_text

        result = await render_field_text(
            self.UNIT,
            target_language="fr",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text=_corrupt_first_call_only,
        )
        assert result == "Ping <@123456789012345678> now."
        assert calls == 2  # one retry, never more than the bound

    async def test_the_two_attempts_use_different_placeholders_never_reused(self) -> None:
        """Proves retry actually regenerates placeholders rather than
        resending the same masked text (which would just risk the same
        corruption again) -- the exact mechanism the mission requires."""
        seen_masked_texts: list[str] = []

        async def _record_and_corrupt_first(masked_text: str) -> str:
            seen_masked_texts.append(masked_text)
            if len(seen_masked_texts) == 1:
                return _mutate_one_placeholder(masked_text)
            return masked_text

        await render_field_text(
            self.UNIT,
            target_language="fr",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text=_record_and_corrupt_first,
        )
        assert len(seen_masked_texts) == 2
        assert seen_masked_texts[0] != seen_masked_texts[1]

    async def test_custom_max_integrity_attempts_bounds_retries_deterministically(self) -> None:
        """The retry ceiling is a real, callable-configurable bound (item F:
        "set a strict maximum"), not a hidden constant -- proves 3 attempts
        are made when configured for 3, and no more."""
        calls = 0

        async def _always_corrupt(masked_text: str) -> str:
            nonlocal calls
            calls += 1
            return _mutate_one_placeholder(masked_text)

        with pytest.raises(IntegrityViolation):
            await render_field_text(
                self.UNIT,
                target_language="fr",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=_always_corrupt,
                max_integrity_attempts=3,
            )
        assert calls == 3

    async def test_no_retry_loop_when_translation_is_not_requested(self) -> None:
        """translate_masked_text=None can never produce a corrupted
        candidate (nothing translates it) -- the retry machinery must not
        loop pointlessly in that case."""
        result = await render_field_text(
            self.UNIT,
            target_language="fr",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text=None,
        )
        assert result == "Ping <@123456789012345678> now."

    async def test_integrity_retry_is_logged_as_a_registered_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Item F: "expose/record integrity retry count" -- verifies the
        real, registered EventId fires (never a bare/unstructured log
        call) exactly once for the one retry in the recovery scenario."""
        calls = 0

        async def _corrupt_first_call_only(masked_text: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _mutate_one_placeholder(masked_text)
            return masked_text

        with caplog.at_level(logging.WARNING, logger="did.campaigns.rendering"):
            await render_field_text(
                self.UNIT,
                target_language="fr",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=_corrupt_first_call_only,
            )
        retry_records = [
            r for r in caplog.records if getattr(r, "msg", None) == "translation.integrity.retry"
        ]
        assert len(retry_records) == 1
        assert retry_records[0].fields["attempt"] == 1
        assert retry_records[0].fields["max_attempts"] == 2

    async def test_render_message_model_end_to_end_recovers_from_one_corrupted_field(self) -> None:
        """The same recovery proven at the field level also works through
        the real per-delivery entrypoint every Stage09 delivery actually
        calls."""
        model = MessageModel(content="Ping <@123456789012345678> now.")
        calls = 0

        async def _corrupt_first_call_only(masked_text: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _mutate_one_placeholder(masked_text)
            return masked_text

        result = await render_message_model(
            model,
            target_language="fr",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text=_corrupt_first_call_only,
        )
        assert result.content == "Ping <@123456789012345678> now."
        assert calls == 2

    @pytest.mark.parametrize("invalid", [0, -1, -5])
    async def test_render_field_text_rejects_non_positive_max_integrity_attempts(
        self, invalid: int
    ) -> None:
        """An invalid bound must fail explicitly and immediately (item:
        "must fail explicitly with ValueError, not reach an internal
        assertion") -- never silently produce a zero-attempt loop that
        would otherwise trip the bare `assert last_error is not None`."""
        with pytest.raises(ValueError, match="max_integrity_attempts must be at least 1"):
            await render_field_text(
                self.UNIT,
                target_language="fr",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=_identity_translate,
                max_integrity_attempts=invalid,
            )

    async def test_render_message_model_rejects_non_positive_max_integrity_attempts(self) -> None:
        model = MessageModel(content="Ping <@123456789012345678> now.")
        with pytest.raises(ValueError, match="max_integrity_attempts must be at least 1"):
            await render_message_model(
                model,
                target_language="fr",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=_identity_translate,
                max_integrity_attempts=0,
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
