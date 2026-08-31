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
from did.messaging.protector import (
    IntegrityViolation,
    protect,
    validate_and_restore,
    validate_full_pipeline,
    validate_reparsed_structure,
)

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
                alphabet=st.characters(blacklist_categories=["Cs"], blacklist_characters="<>`{}@"),
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


class TestReparsedStructureValidation:
    """External-review WP7 strengthening: reparse the restored output and
    compare it against the original source, independent of the placeholder
    mechanism itself."""

    def test_identity_translation_passes(self) -> None:
        content = "Hi <@123456789012345678>, visit https://example.com now."
        nodes = parse(content)
        protection = protect(nodes)
        restored = validate_and_restore(protection.masked_text, protection)
        validate_reparsed_structure(nodes, restored)  # must not raise

    def test_hallucinated_mention_in_translated_text_is_caught(self) -> None:
        """Simulates a translation engine emitting literal mention-shaped
        text that was never a protected token in the source -- structurally
        indistinguishable from a real mention once it reaches Discord, so
        it must be caught even though every original placeholder round-
        tripped correctly."""
        content = "Plain announcement, nothing technical here."
        nodes = parse(content)
        protection = protect(nodes)
        hallucinated = protection.masked_text + " <@999999999999999999>"
        restored = validate_and_restore(hallucinated, protection)
        with pytest.raises(IntegrityViolation, match="hallucinated"):
            validate_reparsed_structure(nodes, restored)

    def test_hallucinated_url_is_caught(self) -> None:
        content = "No links in this one."
        nodes = parse(content)
        protection = protect(nodes)
        hallucinated = protection.masked_text + " https://not-in-the-source.example"
        restored = validate_and_restore(hallucinated, protection)
        with pytest.raises(IntegrityViolation, match="hallucinated"):
            validate_reparsed_structure(nodes, restored)


class TestFullPipelineValidator:
    """validate_full_pipeline() is the single production-grade gate the
    benchmark must also use -- proves it composes all three checks."""

    @pytest.mark.parametrize("content", COMPLIANCE_CORPUS)
    def test_identity_translation_passes_the_full_pipeline(self, content: str) -> None:
        nodes = parse(content)
        protection = protect(nodes)
        restored = validate_full_pipeline(nodes, protection.masked_text, protection)
        assert restored == content

    def test_full_pipeline_still_catches_dropped_placeholders(self) -> None:
        content = "Ping <@123456789012345678> now."
        nodes = parse(content)
        protection = protect(nodes)
        corrupted = protection.masked_text.replace(protection.fingerprints[0].placeholder, "")
        with pytest.raises(IntegrityViolation):
            validate_full_pipeline(nodes, corrupted, protection)

    def test_full_pipeline_catches_hallucinated_content_even_with_intact_placeholders(
        self,
    ) -> None:
        content = "Hi <@123456789012345678>, welcome."
        nodes = parse(content)
        protection = protect(nodes)
        translated_with_extra = protection.masked_text + " <#999999999999999999>"
        with pytest.raises(IntegrityViolation, match="hallucinated"):
            validate_full_pipeline(nodes, translated_with_extra, protection)


class TestMeaningfulReorderIsSafeNotCorruption:
    """External-review request for property/fuzz coverage of 'meaningful
    reorder corruption': proves the actual, documented design property --
    since each placeholder is an opaque, independently-restoring token,
    shuffling WHERE intact placeholders sit in the translated text can never
    corrupt their restored values. This is what makes legitimate MT word
    reordering safe; genuine corruption can only come from altering,
    duplicating, or dropping a placeholder's own string, all of which are
    covered by TestCorruptionFailsClosed above."""

    @settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    @given(seed=st.integers(min_value=0, max_value=10_000))
    def test_shuffling_intact_placeholder_positions_always_round_trips(self, seed: int) -> None:
        content = (
            "Hi <@123456789012345678>, your event {{event_name}} at "
            "<#234567890123456789> starts <t:1700000000:F> -- see https://example.com."
        )
        nodes = parse(content)
        protection = protect(nodes)
        rng = random.Random(seed)

        # Split the masked text into placeholder tokens and literal chunks,
        # then shuffle ONLY the relative order of the placeholder tokens
        # amongst themselves (simulating grammar-driven word reordering)
        # while every placeholder's own string stays byte-identical.
        placeholders = [fp.placeholder for fp in protection.fingerprints]
        shuffled = placeholders[:]
        rng.shuffle(shuffled)
        fake_translation = protection.masked_text
        for original, replacement in zip(placeholders, shuffled, strict=True):
            fake_translation = fake_translation.replace(original, f"\x00{replacement}\x00", 1)
        fake_translation = fake_translation.replace("\x00", "")

        restored = validate_full_pipeline(nodes, fake_translation, protection)
        for fp in protection.fingerprints:
            assert fp.restore_value in restored


class TestUrlTrailingPunctuationTrim:
    """External-review finding (REQ-MSG-025, second remediation pass): a real
    516-call FR/EN/DE/ES googletrans benchmark measured FULL_MASKED_MESSAGE
    at 97.2%, not 100%. Root cause, confirmed live against the actual
    googletrans backend: it regularly drops the whitespace it received
    before a sentence-final "." when the URL placeholder ends up as the
    last token before that punctuation in the target word order (e.g. an
    English "... Details: <URL> for full details." rendered into German as
    "... unter <URL>." with no space before the period). Since the URL
    character class must legitimately allow "." (domains, paths), the
    un-trimmed greedy match would silently absorb that glued period into the
    reparsed URL, producing a value that no longer equals the original
    protected value -- a real, previously undetected corruption class that
    the fail-closed gate correctly caught every time (zero false negatives)
    but that must be fixed at the source rather than merely detected.
    """

    def test_trailing_period_with_no_space_is_not_absorbed_into_the_url(self) -> None:
        content = "Details: https://example.com/campaign?ref=discord for full details."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == (
            "https://example.com/campaign?ref=discord"
        )

    def test_reparse_of_mt_glued_trailing_period_matches_original_value(self) -> None:
        """Reproduces the exact live-observed corruption: MT emits the
        placeholder immediately followed by "." with no separating space."""
        content = (
            "Check out our new announcement at "
            "https://example.com/campaign?ref=discord for full details."
        )
        nodes = parse(content)
        protection = protect(nodes)
        placeholder = protection.fingerprints[0].placeholder
        glued_translation = f"See our announcement at {placeholder}."
        restored = validate_full_pipeline(nodes, glued_translation, protection)
        assert restored == "See our announcement at https://example.com/campaign?ref=discord."

    @pytest.mark.parametrize("trailing", [".", ",", ";", ":", "!", "?"])
    def test_each_sentence_terminal_punctuation_mark_is_trimmed(self, trailing: str) -> None:
        content = f"Go to https://example.com/x{trailing}"
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/x"

    def test_legitimate_mid_url_periods_and_colons_are_preserved(self) -> None:
        content = "See https://example.com/v1.2.3?a=1,2;b=3 now."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/v1.2.3?a=1,2;b=3"

    def test_url_that_is_only_punctuation_after_scheme_is_not_trimmed_to_nothing(self) -> None:
        content = "https://x..."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value.startswith("https://")
        assert len(protection.fingerprints[0].restore_value) >= len("https://x")

    @settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
    @given(
        trailing=st.sampled_from([".", ",", ";", ":", "!", "?", ".!", "?!"]),
        glued=st.booleans(),
        seed=st.integers(min_value=0, max_value=10_000),
    )
    def test_fuzzed_mt_gluing_never_corrupts_a_full_pipeline_round_trip(
        self, trailing: str, glued: bool, seed: int
    ) -> None:
        rng = random.Random(seed)
        path_segment = "".join(rng.choices("abcdefghijklmnop0123456789-", k=6))
        content = f"Visit https://example.com/{path_segment} for details{trailing}"
        nodes = parse(content)
        protection = protect(nodes)
        placeholder = protection.fingerprints[0].placeholder
        original_url = protection.fingerprints[0].restore_value
        separator = "" if glued else " "
        fake_translation = f"See{separator}{placeholder} for details{trailing}"
        restored = validate_full_pipeline(nodes, fake_translation, protection)
        assert original_url in restored
        assert restored.count(original_url) == 1
