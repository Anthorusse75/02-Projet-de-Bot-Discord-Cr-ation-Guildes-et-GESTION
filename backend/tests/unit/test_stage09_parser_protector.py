"""Unit, property and fuzz tests for the Stage 09 Discord-safe parser/protector.

REQ-MSG-010..013 / 023 / 025: 100% protected-token integrity is mandatory on
the compliance corpus below. Every corruption scenario (missing/duplicated/
invented placeholder) must FAIL CLOSED, never publish silently.
"""

from __future__ import annotations

import random
from typing import ClassVar

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from did.messaging.parser import ProtectedKind, ProtectedNode, TextNode, parse, render
from did.messaging.protector import IntegrityViolation, protect, validate_and_restore

pytestmark = [pytest.mark.security]

# A representative Discord-safe compliance corpus: one example per protected
# kind, plus combinations, in the four benchmark languages' scripts where it
# matters (Latin script covers FR/EN/DE/ES equally for token syntax, since
# these are ASCII Discord control sequences regardless of surrounding prose
# language).
COMPLIANCE_CORPUS: tuple[str, ...] = (
    "Hello <@123456789012345678>, welcome!",
    "Bonjour <@!123456789012345678> et <@&234567890123456789> !",
    "Check <#345678901234567890> for details.",
    "React with <a:party:456789012345678901> or <:wave:567890123456789012>.",
    "Event starts <t:1700000000:F>, see you there.",
    "Run </deploy:678901234567890123> before the release.",
    "Visit https://example.com/campaign?id=42 for more.",
    "```py\nprint('hello')\n```",
    "Use `campaign.send()` to publish.",
    "Hallo {{user_name}}, dein Code ist bereit.",
    "@everyone the campaign is live! Details: https://example.com <t:1700000000:R>",
    "Plain sentence with no protected tokens at all.",
    "",
    "Mixed: <@111111111111111111> said `inline` near https://a.b/c and {{var}}.",
)


class TestParseRenderRoundtrip:
    @pytest.mark.parametrize("content", COMPLIANCE_CORPUS)
    def test_render_of_parse_is_lossless(self, content: str) -> None:
        assert render(parse(content)) == content

    def test_classifies_each_kind_correctly(self) -> None:
        nodes = parse("<@123456789012345678> <@&234567890123456789> <#345678901234567890>")
        kinds = [n.kind for n in nodes if isinstance(n, ProtectedNode)]
        assert kinds == [
            ProtectedKind.USER_MENTION,
            ProtectedKind.ROLE_MENTION,
            ProtectedKind.CHANNEL_MENTION,
        ]

    def test_code_block_is_one_atomic_node(self) -> None:
        nodes = parse("before ```<@123456789012345678> not a mention``` after")
        protected = [n for n in nodes if isinstance(n, ProtectedNode)]
        assert len(protected) == 1
        assert protected[0].kind is ProtectedKind.CODE_BLOCK
        assert "<@123456789012345678>" in protected[0].value

    def test_plain_text_has_no_protected_nodes(self) -> None:
        nodes = parse("just a sentence")
        assert all(isinstance(n, TextNode) for n in nodes)

    def test_empty_string_parses_to_empty(self) -> None:
        assert parse("") == ()


class TestProtectRestoreIdentity:
    """When the 'translation' is the identity function, restore must return
    exactly the original content -- the base case every corruption test
    diverges from."""

    @pytest.mark.parametrize("content", COMPLIANCE_CORPUS)
    def test_identity_translation_restores_original(self, content: str) -> None:
        nodes = parse(content)
        protection = protect(nodes)
        restored = validate_and_restore(protection.masked_text, protection)
        assert restored == content

    def test_masked_text_contains_no_raw_protected_values(self) -> None:
        content = "Hello <@123456789012345678>, visit https://example.com now."
        protection = protect(parse(content))
        assert "<@123456789012345678>" not in protection.masked_text
        assert "https://example.com" not in protection.masked_text

    def test_reordering_text_around_placeholders_still_restores(self) -> None:
        """Simulates legitimate MT word reordering: as long as every
        placeholder string survives untouched, the exact set-integrity gate
        passes regardless of where in the string it ends up."""
        content = "Hi <@123456789012345678>, the launch is at <t:1700000000:F>."
        protection = protect(parse(content))
        placeholders = [fp.placeholder for fp in protection.fingerprints]
        # Fabricate a "translation" that reverses word order but keeps both
        # placeholders intact somewhere in the output.
        fake_translation = f"{placeholders[1]} ist der Start, Hallo {placeholders[0]}!"
        restored = validate_and_restore(fake_translation, protection)
        assert "<@123456789012345678>" in restored
        assert "<t:1700000000:F>" in restored


class TestCorruptionFailsClosed:
    def test_missing_placeholder_fails_closed(self) -> None:
        content = "Hello <@123456789012345678> and <@&234567890123456789>."
        protection = protect(parse(content))
        corrupted = protection.masked_text.replace(protection.fingerprints[0].placeholder, "")
        with pytest.raises(IntegrityViolation, match="dropped"):
            validate_and_restore(corrupted, protection)

    def test_duplicated_placeholder_fails_closed(self) -> None:
        content = "Ping <@123456789012345678> now."
        protection = protect(parse(content))
        placeholder = protection.fingerprints[0].placeholder
        corrupted = protection.masked_text + f" {placeholder}"
        with pytest.raises(IntegrityViolation, match="duplicated"):
            validate_and_restore(corrupted, protection)

    def test_invented_placeholder_fails_closed(self) -> None:
        content = "Ping <@123456789012345678> now."
        protection = protect(parse(content))
        corrupted = protection.masked_text + " DIDPH9999QDEADBEEFZH"
        with pytest.raises(IntegrityViolation, match="invented"):
            validate_and_restore(corrupted, protection)

    def test_altered_placeholder_is_treated_as_missing_plus_invented(self) -> None:
        content = "Ping <@123456789012345678> now."
        protection = protect(parse(content))
        original = protection.fingerprints[0].placeholder
        altered = original[:-3] + "XYZ"
        corrupted = protection.masked_text.replace(original, altered)
        with pytest.raises(IntegrityViolation):
            validate_and_restore(corrupted, protection)

    def test_glossary_forced_translation_restore_override(self) -> None:
        """WP8: a protected node can restore to a *different* string than its
        original value (forced glossary translation), never a raw
        post-translation substitution."""
        # Simulate the glossary layer marking "Widget" (position 1, a TEXT
        # node split manually here for the test) as a forced-translation term
        # by re-parsing with an injected protected node.
        from did.messaging.parser import TextNode as TN

        custom_nodes = (
            TN("Our "),
            ProtectedNode(kind=ProtectedKind.GLOSSARY_TERM, value="Widget"),
            TN(" is great."),
        )
        protection = protect(custom_nodes, restore_overrides={1: "Widgeto"})
        restored = validate_and_restore(protection.masked_text, protection)
        assert restored == "Our Widgeto is great."


class TestFuzzProtectedTokenIntegrity:
    """Property-based fuzzing over synthetic messages combining random prose
    with protected tokens, proving 100% integrity on well-formed input and
    100% fail-closed detection on any single-token corruption."""

    _SNOWFLAKES: ClassVar[list[str]] = [
        str(random.Random(i).randint(10**17, 10**18 - 1)) for i in range(8)
    ]

    def _protected_token_pool(self) -> list[str]:
        sf = self._SNOWFLAKES
        return [
            f"<@{sf[0]}>",
            f"<@!{sf[1]}>",
            f"<@&{sf[2]}>",
            f"<#{sf[3]}>",
            f"<a:party:{sf[4]}>",
            "<t:1700000000:F>",
            f"</deploy:{sf[5]}>",
            "https://example.com/x?y=1",
            "```code block```",
            "`inline`",
            "{{variable_name}}",
            "@everyone",
        ]

    @settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
    @given(
        words=st.lists(
            st.text(
                alphabet=st.characters(
                    blacklist_categories=["Cs"], blacklist_characters="<>`{}@"
                ),
                min_size=1,
                max_size=12,
            ),
            min_size=0,
            max_size=6,
        ),
        token_indices=st.lists(st.integers(min_value=0, max_value=11), min_size=0, max_size=4),
        seed=st.integers(min_value=0, max_value=10_000),
    )
    def test_well_formed_messages_always_round_trip(
        self, words: list[str], token_indices: list[int], seed: int
    ) -> None:
        pool = self._protected_token_pool()
        rng = random.Random(seed)
        pieces: list[str] = list(words) + [pool[i] for i in token_indices]
        rng.shuffle(pieces)
        content = " ".join(pieces)

        nodes = parse(content)
        protection = protect(nodes)
        # Identity "translation": every protected token must survive
        # untouched for a well-formed pipeline.
        restored = validate_and_restore(protection.masked_text, protection)
        assert render(parse(restored)) == restored
        for fp in protection.fingerprints:
            assert fp.restore_value in restored

    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    @given(seed=st.integers(min_value=0, max_value=10_000))
    def test_dropping_any_single_protected_token_is_always_caught(self, seed: int) -> None:
        pool = self._protected_token_pool()
        rng = random.Random(seed)
        chosen = rng.sample(pool, k=rng.randint(2, len(pool)))
        content = " ".join(chosen)
        nodes = parse(content)
        protection = protect(nodes)
        if not protection.fingerprints:
            return
        victim = rng.choice(protection.fingerprints)
        corrupted = protection.masked_text.replace(victim.placeholder, "", 1)
        with pytest.raises(IntegrityViolation):
            validate_and_restore(corrupted, protection)
