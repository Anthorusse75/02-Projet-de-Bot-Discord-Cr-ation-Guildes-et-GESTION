"""Unit tests for WP8: glossary priority resolution and protection via the
existing PROTECTED-node/placeholder machinery (never raw post-translation
string substitution).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.glossary import apply_glossary_protection, resolve_applicable_entries
from did.domain.campaigns import GlossaryBehavior, GlossaryEntry, GlossaryMatchMode, GlossaryScope
from did.messaging.parser import ProtectedKind, ProtectedNode, parse
from did.messaging.protector import protect, validate_and_restore

pytestmark = [pytest.mark.security]


def _entry(**overrides: object) -> GlossaryEntry:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=1,
        scope_kind=GlossaryScope.GLOBAL_USER,
        source_term="Widget",
        behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
    )
    fields.update(overrides)
    return GlossaryEntry(**fields)  # type: ignore[arg-type]


class TestResolveApplicableEntries:
    def test_campaign_scope_entry_only_applies_to_its_own_campaign(self) -> None:
        campaign_id = uuid4()
        other_campaign_id = uuid4()
        entry = _entry(scope_kind=GlossaryScope.CAMPAIGN, campaign_id=campaign_id)
        assert resolve_applicable_entries(
            [entry], campaign_id=campaign_id, target_language_code="fr"
        ) == [entry]
        assert (
            resolve_applicable_entries(
                [entry], campaign_id=other_campaign_id, target_language_code="fr"
            )
            == []
        )

    def test_global_user_entry_applies_to_any_campaign(self) -> None:
        entry = _entry(scope_kind=GlossaryScope.GLOBAL_USER)
        assert resolve_applicable_entries(
            [entry], campaign_id=uuid4(), target_language_code="fr"
        ) == [entry]

    def test_language_specific_entry_only_applies_to_its_language(self) -> None:
        entry = _entry(target_language_code="fr")
        assert resolve_applicable_entries(
            [entry], campaign_id=uuid4(), target_language_code="fr"
        ) == [entry]
        assert (
            resolve_applicable_entries([entry], campaign_id=uuid4(), target_language_code="de")
            == []
        )

    def test_language_agnostic_entry_applies_to_every_language(self) -> None:
        entry = _entry(target_language_code=None)
        assert resolve_applicable_entries(
            [entry], campaign_id=uuid4(), target_language_code="es"
        ) == [entry]

    def test_ordering_is_most_specific_first(self) -> None:
        campaign_id = uuid4()
        global_entry = _entry(scope_kind=GlossaryScope.GLOBAL_USER, source_term="Widget")
        campaign_entry = _entry(
            scope_kind=GlossaryScope.CAMPAIGN, campaign_id=campaign_id, source_term="Widget"
        )
        resolved = resolve_applicable_entries(
            [global_entry, campaign_entry], campaign_id=campaign_id, target_language_code="fr"
        )
        assert resolved == [campaign_entry, global_entry]


class TestApplyGlossaryProtection:
    def test_do_not_translate_term_becomes_glossary_protected_node(self) -> None:
        nodes = parse("Our Widget is on sale.")
        entry = _entry(source_term="Widget")
        application = apply_glossary_protection(nodes, [entry])
        glossary_nodes = [
            n
            for n in application.nodes
            if isinstance(n, ProtectedNode) and n.kind is ProtectedKind.GLOSSARY_TERM
        ]
        assert len(glossary_nodes) == 1
        assert glossary_nodes[0].value == "Widget"
        assert application.matched_term_count == 1

    def test_forced_translation_sets_restore_override(self) -> None:
        nodes = parse("Our Widget is on sale.")
        entry = _entry(
            source_term="Widget",
            behavior=GlossaryBehavior.FORCED_TRANSLATION,
            forced_translation="Gadgeto",
        )
        application = apply_glossary_protection(nodes, [entry])
        assert list(application.restore_overrides.values()) == ["Gadgeto"]

    def test_forced_translation_survives_simulated_translation(self) -> None:
        nodes = parse("Our Widget is on sale.")
        entry = _entry(
            source_term="Widget",
            behavior=GlossaryBehavior.FORCED_TRANSLATION,
            forced_translation="Gadgeto",
        )
        application = apply_glossary_protection(nodes, [entry])
        protection = protect(application.nodes, restore_overrides=application.restore_overrides)
        # Identity "translation": the placeholder survives untouched, but
        # restoration must substitute the *forced* text, not the original.
        restored = validate_and_restore(protection.masked_text, protection)
        assert "Gadgeto" in restored
        assert "Widget" not in restored

    def test_case_insensitive_match_mode(self) -> None:
        nodes = parse("our WIDGET is great")
        entry = _entry(source_term="Widget", match_mode=GlossaryMatchMode.CASE_INSENSITIVE)
        application = apply_glossary_protection(nodes, [entry])
        assert application.matched_term_count == 1

    def test_exact_match_mode_is_case_sensitive(self) -> None:
        nodes = parse("our WIDGET is great")
        entry = _entry(source_term="Widget", match_mode=GlossaryMatchMode.EXACT)
        application = apply_glossary_protection(nodes, [entry])
        assert application.matched_term_count == 0

    def test_word_boundary_prevents_partial_word_match(self) -> None:
        nodes = parse("The Widgetry team met today.")
        entry = _entry(source_term="Widget")
        application = apply_glossary_protection(nodes, [entry])
        assert application.matched_term_count == 0

    def test_most_specific_entry_wins_at_same_position(self) -> None:
        nodes = parse("Buy the Widget Pro today.")
        short_entry = _entry(source_term="Widget")
        long_entry = _entry(source_term="Widget Pro")
        resolved = sorted([short_entry, long_entry], key=lambda e: e.specificity(), reverse=True)
        application = apply_glossary_protection(nodes, resolved)
        glossary_values = [
            n.value
            for n in application.nodes
            if isinstance(n, ProtectedNode) and n.kind is ProtectedKind.GLOSSARY_TERM
        ]
        assert glossary_values == ["Widget Pro"]

    def test_no_entries_is_a_noop(self) -> None:
        nodes = parse("Nothing to protect here.")
        application = apply_glossary_protection(nodes, [])
        assert application.nodes == nodes
        assert application.matched_term_count == 0

    def test_full_pipeline_with_mentions_and_glossary_term(self) -> None:
        content = "Hey <@123456789012345678>, our Widget just shipped!"
        nodes = parse(content)
        entry = _entry(source_term="Widget")
        application = apply_glossary_protection(nodes, [entry])
        protection = protect(application.nodes, restore_overrides=application.restore_overrides)
        restored = validate_and_restore(protection.masked_text, protection)
        assert restored == content
