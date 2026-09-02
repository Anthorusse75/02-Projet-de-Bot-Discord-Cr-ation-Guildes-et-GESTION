"""Unit tests for WP8: glossary priority resolution and protection via the
existing PROTECTED-node/placeholder machinery (never raw post-translation
string substitution).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.glossary import (
    apply_glossary_protection,
    matched_source_terms,
    resolve_applicable_entries,
)
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

    def test_guild_scope_entry_applies_only_to_its_own_guild(self) -> None:
        entry = _entry(scope_kind=GlossaryScope.GUILD, guild_id=880000001, campaign_id=None)
        assert resolve_applicable_entries(
            [entry], campaign_id=uuid4(), target_language_code="fr", guild_id=880000001
        ) == [entry]
        assert (
            resolve_applicable_entries(
                [entry], campaign_id=uuid4(), target_language_code="fr", guild_id=880000002
            )
            == []
        )

    def test_guild_scope_entry_excluded_when_no_guild_context_given(self) -> None:
        entry = _entry(scope_kind=GlossaryScope.GUILD, guild_id=880000001, campaign_id=None)
        assert (
            resolve_applicable_entries([entry], campaign_id=uuid4(), target_language_code="fr")
            == []
        )

    def test_three_tier_priority_ordering(self) -> None:
        campaign_id = uuid4()
        campaign_entry = _entry(
            scope_kind=GlossaryScope.CAMPAIGN, campaign_id=campaign_id, source_term="Widget"
        )
        guild_entry = _entry(
            scope_kind=GlossaryScope.GUILD,
            guild_id=880000001,
            campaign_id=None,
            source_term="Widget",
        )
        global_entry = _entry(scope_kind=GlossaryScope.GLOBAL_USER, source_term="Widget")
        resolved = resolve_applicable_entries(
            [global_entry, guild_entry, campaign_entry],
            campaign_id=campaign_id,
            target_language_code="fr",
            guild_id=880000001,
        )
        assert resolved == [campaign_entry, guild_entry, global_entry]

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


class TestMatchedSourceTerms:
    """REQ-MSG-014/022 simulation/preview integration (mission section 11)."""

    def test_a_term_present_in_the_text_is_reported(self) -> None:
        entry = _entry(source_term="Widget")
        assert matched_source_terms([entry], "Our Widget just shipped!") == ("Widget",)

    def test_a_term_absent_from_the_text_is_not_reported(self) -> None:
        entry = _entry(source_term="Gadget")
        assert matched_source_terms([entry], "Our Widget just shipped!") == ()

    def test_case_insensitive_matching_respects_match_mode(self) -> None:
        entry = _entry(source_term="widget", match_mode=GlossaryMatchMode.CASE_INSENSITIVE)
        assert matched_source_terms([entry], "Our WIDGET just shipped!") == ("widget",)

    def test_exact_match_mode_is_case_sensitive(self) -> None:
        entry = _entry(source_term="Widget", match_mode=GlossaryMatchMode.EXACT)
        assert matched_source_terms([entry], "Our widget just shipped!") == ()

    def test_multiple_entries_each_reported_once(self) -> None:
        first = _entry(source_term="Widget")
        second = _entry(source_term="Gadget")
        result = matched_source_terms([first, second], "The Widget and the Widget and the Gadget.")
        assert result == ("Widget", "Gadget")
