"""Unit/property tests for REQ-MSG-018: typed template variable semantics
(TRANSLATABLE_TEXT / NON_TRANSLATABLE / LOCALIZED_VALUE / PROTECTED).
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from did.messaging.parser import ProtectedNode, parse, render
from did.messaging.protector import protect, validate_full_pipeline
from did.messaging.template_variables import (
    MissingLocalizedValue,
    TemplateVariableDefinition,
    TemplateVariableType,
    resolve_template_variables,
    undeclared_variable_names,
)

pytestmark = [pytest.mark.security]


class TestTemplateVariableDefinitionValidation:
    def test_translatable_text_requires_a_value(self) -> None:
        with pytest.raises(ValueError, match="requires a `value`"):
            TemplateVariableDefinition("x", TemplateVariableType.TRANSLATABLE_TEXT)

    def test_localized_value_requires_values_by_language(self) -> None:
        with pytest.raises(ValueError, match="requires a non-empty values_by_language"):
            TemplateVariableDefinition("x", TemplateVariableType.LOCALIZED_VALUE)

    def test_localized_value_must_not_also_carry_a_single_value(self) -> None:
        with pytest.raises(ValueError, match="must not also carry"):
            TemplateVariableDefinition(
                "x",
                TemplateVariableType.LOCALIZED_VALUE,
                value="oops",
                values_by_language={"en": "Hi"},
            )

    def test_non_localized_type_must_not_carry_values_by_language(self) -> None:
        with pytest.raises(ValueError, match="must not carry values_by_language"):
            TemplateVariableDefinition(
                "x",
                TemplateVariableType.NON_TRANSLATABLE,
                value="v",
                values_by_language={"en": "Hi"},
            )

    def test_resolve_localized_value_missing_language_raises(self) -> None:
        definition = TemplateVariableDefinition(
            "price", TemplateVariableType.LOCALIZED_VALUE, values_by_language={"en": "$5"}
        )
        with pytest.raises(MissingLocalizedValue):
            definition.resolve(target_language="fr")


class TestUndeclaredVariableNames:
    def test_finds_every_referenced_name(self) -> None:
        nodes = parse("Hi {{user_name}}, your code is {{code}}.")
        assert undeclared_variable_names(nodes) == {"user_name", "code"}


class TestResolveTemplateVariables:
    def test_translatable_text_is_inlined_as_plain_text_not_protected(self) -> None:
        nodes = parse("Subtitle: {{subtitle}} today.")
        definitions = {
            "subtitle": TemplateVariableDefinition(
                "subtitle", TemplateVariableType.TRANSLATABLE_TEXT, value="Big Sale"
            )
        }
        resolved_nodes, overrides = resolve_template_variables(
            nodes, definitions, target_language="en"
        )
        assert overrides == {}
        assert render(resolved_nodes) == "Subtitle: Big Sale today."
        # No PROTECTED node remains for this variable.
        assert not any(isinstance(n, ProtectedNode) for n in resolved_nodes)

    def test_non_translatable_stays_protected_with_fixed_value(self) -> None:
        nodes = parse("Product: {{product}}.")
        definitions = {
            "product": TemplateVariableDefinition(
                "product", TemplateVariableType.NON_TRANSLATABLE, value="Acme Widget"
            )
        }
        resolved_nodes, overrides = resolve_template_variables(
            nodes, definitions, target_language="fr"
        )
        protection = protect(resolved_nodes, restore_overrides=overrides)
        restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
        assert restored == "Product: Acme Widget."

    def test_non_translatable_value_is_identical_across_languages(self) -> None:
        nodes = parse("{{product}}")
        definitions = {
            "product": TemplateVariableDefinition(
                "product", TemplateVariableType.NON_TRANSLATABLE, value="Acme Widget"
            )
        }
        for lang in ("en", "fr", "de", "es"):
            resolved_nodes, overrides = resolve_template_variables(
                nodes, definitions, target_language=lang
            )
            protection = protect(resolved_nodes, restore_overrides=overrides)
            restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
            assert restored == "Acme Widget"

    def test_localized_value_picks_the_correct_target_language_value(self) -> None:
        nodes = parse("Price: {{price}}.")
        definitions = {
            "price": TemplateVariableDefinition(
                "price",
                TemplateVariableType.LOCALIZED_VALUE,
                values_by_language={"en": "$5.00", "fr": "5,00 €", "de": "5,00 €"},
            )
        }
        for lang, expected in (("en", "$5.00"), ("fr", "5,00 €"), ("de", "5,00 €")):
            resolved_nodes, overrides = resolve_template_variables(
                nodes, definitions, target_language=lang
            )
            protection = protect(resolved_nodes, restore_overrides=overrides)
            restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
            assert restored == f"Price: {expected}."

    def test_protected_type_behaves_like_non_translatable_in_the_pipeline(self) -> None:
        nodes = parse("Ref: {{ref_code}}.")
        definitions = {
            "ref_code": TemplateVariableDefinition(
                "ref_code", TemplateVariableType.PROTECTED, value="XJ-19-Q"
            )
        }
        resolved_nodes, overrides = resolve_template_variables(
            nodes, definitions, target_language="de"
        )
        protection = protect(resolved_nodes, restore_overrides=overrides)
        restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
        assert restored == "Ref: XJ-19-Q."

    def test_undeclared_variable_defaults_to_non_translatable_fail_safe(self) -> None:
        nodes = parse("Hello {{unknown_var}}!")
        resolved_nodes, overrides = resolve_template_variables(nodes, {}, target_language="en")
        protection = protect(resolved_nodes, restore_overrides=overrides)
        restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
        # Fail-safe: never guessed, echoes its own raw {{name}} syntax.
        assert restored == "Hello {{unknown_var}}!"

    def test_mixed_types_in_one_message_resolve_independently(self) -> None:
        nodes = parse("{{headline}} -- ref {{ref}} -- price {{price}} -- see <@123456789012345678>")
        definitions = {
            "headline": TemplateVariableDefinition(
                "headline", TemplateVariableType.TRANSLATABLE_TEXT, value="Big Launch"
            ),
            "ref": TemplateVariableDefinition(
                "ref", TemplateVariableType.PROTECTED, value="REF-001"
            ),
            "price": TemplateVariableDefinition(
                "price",
                TemplateVariableType.LOCALIZED_VALUE,
                values_by_language={"en": "$10"},
            ),
        }
        resolved_nodes, overrides = resolve_template_variables(
            nodes, definitions, target_language="en"
        )
        protection = protect(resolved_nodes, restore_overrides=overrides)
        restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
        assert restored == "Big Launch -- ref REF-001 -- price $10 -- see <@123456789012345678>"


class TestPropertyMultipleVariableTypesNeverCorruptTheReparse:
    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    @given(
        headline=st.text(min_size=1, max_size=15).filter(lambda s: "{" not in s and "}" not in s),
        # Excludes Markdown emphasis-marker substrings ("**", "__", "~~",
        # "||"): a NON_TRANSLATABLE value that happens to literally BE one
        # of those is a legitimate but separate edge case for
        # protector.validate_structural_balance's own (already tested
        # elsewhere) best-effort emphasis-count signal, not something this
        # placeholder-integrity round-trip property needs to also probe.
        ref=st.text(
            alphabet=st.characters(blacklist_categories=["Cs"], blacklist_characters="{}*_~|"),
            min_size=1,
            max_size=10,
        ),
    )
    def test_arbitrary_values_always_round_trip_safely(self, headline: str, ref: str) -> None:
        nodes = parse("{{headline}} :: {{ref}}")
        definitions = {
            "headline": TemplateVariableDefinition(
                "headline", TemplateVariableType.TRANSLATABLE_TEXT, value=headline
            ),
            "ref": TemplateVariableDefinition(
                "ref", TemplateVariableType.NON_TRANSLATABLE, value=ref
            ),
        }
        resolved_nodes, overrides = resolve_template_variables(
            nodes, definitions, target_language="en"
        )
        protection = protect(resolved_nodes, restore_overrides=overrides)
        # Identity "translation": every protected token/value must survive.
        restored = validate_full_pipeline(resolved_nodes, protection.masked_text, protection)
        assert ref in restored
