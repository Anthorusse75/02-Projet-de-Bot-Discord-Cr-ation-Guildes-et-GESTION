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
    PlaceholderFingerprint,
    ProtectionResult,
    protect,
    restore_source_proven_url_boundary_spacing,
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


class TestUrlTrailingPunctuationTrimAdversarialRobustness:
    """External-review finding (fourth remediation pass): the trim fix must
    not be broadened to "pass tests" -- these prove it stays scoped to
    exactly the trailing-punctuation case while every legitimate URL
    character (query delimiters/values, fragments, percent-encoding, path
    punctuation, parenthesised destinations) round-trips unchanged, and that
    ``render(parse(content)) == content`` always holds regardless."""

    @pytest.mark.parametrize(
        "content",
        [
            "Query with a delimiter and values: https://example.com/search?q=hello&lang=en.",
            "Query string only, no trailing punctuation: https://example.com/search?q=hello&lang=en",
            "Fragment: https://example.com/docs#section-2, see above.",
            "Fragment only: https://example.com/docs#section-2",
            "Percent-encoded space: https://example.com/a%20b?x=1.",
            "Percent-encoded punctuation not at the boundary: https://example.com/search?q=a%2Cb!",
            "Multi-dot path/version string: https://example.com/releases/v1.2.3-beta.",
            "Markdown-style destination in parens: See [the docs](https://example.com/docs).",
            "Wikipedia-style balanced parens right after the domain: "
            "https://en.wikipedia.org/wiki/Discord_(software) is relevant.",
            "Trailing colon before a clause: https://example.com/api: use with care.",
            "Semicolon-separated clause: https://example.com/x; then continue.",
            "Double punctuation at the end: https://example.com/y?!",
            "Query value that itself ends in a digit: https://example.com/x?v=123.",
        ],
    )
    def test_full_source_text_always_round_trips_exactly(self, content: str) -> None:
        assert render(parse(content)) == content

    def test_query_delimiter_and_values_survive_the_trim_untouched(self) -> None:
        content = "Search: https://example.com/search?q=hello&lang=en."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == (
            "https://example.com/search?q=hello&lang=en"
        )

    def test_fragment_survives_the_trim_untouched(self) -> None:
        content = "See https://example.com/docs#section-2, right there."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/docs#section-2"

    def test_percent_encoded_punctuation_mid_url_is_never_mistaken_for_trailing_punctuation(
        self,
    ) -> None:
        """%2E is an encoded period as literal alnum text -- the trim only
        ever inspects the actual last characters, never decodes
        percent-escapes, so a URL ending in an encoded period is untouched."""
        content = "Encoded: https://example.com/x%2E"
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/x%2E"

    def test_multi_dot_path_version_string_is_preserved(self) -> None:
        content = "Release notes: https://example.com/releases/v1.2.3-beta."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == (
            "https://example.com/releases/v1.2.3-beta"
        )

    def test_markdown_style_destination_in_parens_extracts_the_bare_url(self) -> None:
        """Parens are already excluded from the URL character class
        (pre-existing behavior, unrelated to the trailing-punctuation fix):
        the ')' correctly terminates the match, leaving a clean URL with no
        trim needed here since 's' (from "docs") isn't punctuation."""
        content = "See [the docs](https://example.com/docs)."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/docs"

    def test_double_trailing_punctuation_is_fully_trimmed(self) -> None:
        content = "Look: https://example.com/y?!"
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/y"

    def test_glued_query_value_ending_in_a_digit_is_never_trimmed(self) -> None:
        """A URL whose real last character is a digit must never lose it --
        proves the trim only ever removes characters actually in the
        trailing-punctuation set, never digits/letters."""
        content = "Version: https://example.com/x?v=123."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints[0].restore_value == "https://example.com/x?v=123"

    def test_identity_translation_still_restores_the_full_original_sentence(self) -> None:
        """End-to-end: for every adversarial case, an identity 'translation'
        (nothing corrupted) must still restore byte-identically -- proves
        the trim/restore round trip, not just the isolated protected value."""
        content = "Search: https://example.com/search?q=hello&lang=en#top, done."
        nodes = parse(content)
        protection = protect(nodes)
        restored = validate_full_pipeline(nodes, protection.masked_text, protection)
        assert restored == content


def _url_protection(masked_text: str, placeholder: str, restore_value: str) -> ProtectionResult:
    """Hand-built single-URL-fingerprint ProtectionResult for precise
    control over exactly what the SOURCE masked text proves at the
    boundary immediately after the placeholder -- used where constructing
    an equivalent real ``parse()``/``protect()`` input would be indirect
    (e.g. proving "no source evidence" requires a source shape the real
    URL regex would not itself naturally produce)."""
    fingerprint = PlaceholderFingerprint(
        placeholder=placeholder,
        kind=ProtectedKind.URL,
        order_index=0,
        value_sha256="0" * 64,
        restore_value=restore_value,
    )
    return ProtectionResult(masked_text=masked_text, fingerprints=(fingerprint,))


_ADVERSARIAL_URL_ONE = (
    "https://example.com/events/2026-season-three?ref=discord&utm=campaign#schedule"
)
_ADVERSARIAL_URL_TWO = "https://example.com/archive/2025"
_ADVERSARIAL_CONTENT = (
    "Full details, including the updated schedule, are available at "
    f"{_ADVERSARIAL_URL_ONE}. See also (the archived version): {_ADVERSARIAL_URL_TWO}."
)


class TestUrlBoundarySpacingSourceProvenRepair:
    """STAGE09 -- URL PLACEHOLDER SENTENCE-BOUNDARY INTEGRITY REMEDIATION.

    Real canonical benchmark (SHA ``1d71164f5ab24f1585048b3fcc226461d5b2ce1d``):
    FULL_MASKED_MESSAGE 300/312 (0.9615...), 12/12 production failures ==
    class ``url_adversarial``, all 12 directed language pairs, every
    failure persisting through the second bounded integrity attempt.
    Forensic one-call reproduction (real MkEWBc EN->FR): the URL
    placeholder and the URL it stands for were preserved byte-for-byte --
    the defect is that the translator dropped the whitespace between the
    placeholder's trailing "." and the next target-language word (e.g.
    "DIDPHxxxx. See also" -> "DIDPHxxxx.Voir aussi"), which then makes the
    restored URL lexically absorb "Voir" once the placeholder is replaced
    -- correctly rejected by ``validate_reparsed_structure`` as
    protected-looking content not present in the source. This is NOT a
    dropped/invented placeholder, NOT a URL parser defect, and NOT a URL
    mutation by the provider -- see ``restore_source_proven_url_boundary_
    spacing``'s own docstring in ``did.messaging.protector`` for the full
    root-cause writeup and the exact, narrow scope of the fix.
    """

    def test_real_regression_the_exact_adversarial_corpus_url_end_to_end(self) -> None:
        """The mission's own forensic reproduction, end to end, through the
        real parse/protect/validate_full_pipeline pipeline, using the
        EXACT adversarial URL/content from
        backend/tests/fixtures/translation_corpus/stage09_corpus.json's
        ``url_adversarial`` class."""
        nodes = parse(_ADVERSARIAL_CONTENT)
        protection = protect(nodes)
        assert len(protection.fingerprints) == 2
        ph_one, ph_two = (fp.placeholder for fp in protection.fingerprints)
        assert protection.fingerprints[0].restore_value == _ADVERSARIAL_URL_ONE
        assert protection.fingerprints[1].restore_value == _ADVERSARIAL_URL_TWO

        # Exact real MkEWBc-observed shape: the whitespace after the FIRST
        # placeholder's "." is lost; everything else (including the second
        # placeholder, itself at the very end with no following word) is
        # translated/preserved normally.
        translated = (
            "Tous les détails, y compris le calendrier mis à jour, sont "
            f"disponibles sur {ph_one}.Voir aussi (la version archivée) : {ph_two}."
        )
        restored = validate_full_pipeline(nodes, translated, protection)
        assert restored == (
            "Tous les détails, y compris le calendrier mis à jour, sont "
            f"disponibles sur {_ADVERSARIAL_URL_ONE}. Voir aussi (la version archivée) : "
            f"{_ADVERSARIAL_URL_TWO}."
        )

    def test_without_the_fix_the_defect_would_fail_reparsed_structure(self) -> None:
        """Isolates the exact mechanism: restoring the glued translation
        WITHOUT the boundary-spacing repair produces a reparsed URL that
        genuinely differs from the original (the next word absorbed into
        it) -- proves the repair is fixing a real, reproducible failure,
        not a hypothetical one."""
        nodes = parse(_ADVERSARIAL_CONTENT)
        protection = protect(nodes)
        ph_one = protection.fingerprints[0].placeholder
        glued = f"See {ph_one}.Voir aussi"
        naive_restore = glued
        for fp in protection.fingerprints:
            naive_restore = naive_restore.replace(fp.placeholder, fp.restore_value)
        with pytest.raises(IntegrityViolation, match="not present"):
            validate_reparsed_structure(nodes, naive_restore)

    def test_no_repair_when_translation_already_has_correct_spacing(self) -> None:
        """No unnecessary modification: if the provider already returns
        the correctly-spaced boundary, the text must come back byte-
        identical -- never a needless rewrite."""
        protection = _url_protection(
            masked_text="Visit DIDPH0000QAAAAAAAAZH. See also that",
            placeholder="DIDPH0000QAAAAAAAAZH",
            restore_value="https://example.com/x",
        )
        translated = "Visitez DIDPH0000QAAAAAAAAZH. Voir aussi cela"
        repaired = restore_source_proven_url_boundary_spacing(translated, protection)
        assert repaired == translated

    def test_source_evidence_mandatory_never_invents_whitespace_absent_from_source(self) -> None:
        """If the SOURCE masked text never proved a "<placeholder>. "
        boundary existed (here: the placeholder's "." is immediately
        followed by a non-whitespace character in the source itself,
        because a closing parenthesis -- excluded from the URL character
        class -- ended the URL match right there), the function must
        never invent a repair, no matter what the translated text looks
        like."""
        protection = _url_protection(
            masked_text="See DIDPH0000QAAAAAAAAZH.)Next",
            placeholder="DIDPH0000QAAAAAAAAZH",
            restore_value="https://example.com/x",
        )
        translated = "Voir DIDPH0000QAAAAAAAAZH.)Suite"
        repaired = restore_source_proven_url_boundary_spacing(translated, protection)
        assert repaired == translated

    def test_url_only_scope_never_touches_ordinary_text_punctuation(self) -> None:
        """The mechanism must never rewrite punctuation spacing anywhere
        else in the text -- only immediately after a URL-kind placeholder
        that itself has source-proven evidence."""
        protection = _url_protection(
            masked_text="Visit DIDPH0000QAAAAAAAAZH. See also",
            placeholder="DIDPH0000QAAAAAAAAZH",
            restore_value="https://example.com/x",
        )
        translated = "Note.Sans espace ici, puis DIDPH0000QAAAAAAAAZH.Voir aussi"
        repaired = restore_source_proven_url_boundary_spacing(translated, protection)
        assert repaired == "Note.Sans espace ici, puis DIDPH0000QAAAAAAAAZH. Voir aussi"

    def test_non_url_placeholder_kind_is_never_touched(self) -> None:
        """Scope is URL-kind only -- a mention/timestamp/other protected
        kind glued to a following word by the same defect must NOT be
        "repaired" by this mechanism (out of the empirically-proven
        scope; a different content class showed 0 production failures in
        the real benchmark, so there is no evidence this defect even
        applies there)."""
        fingerprint = PlaceholderFingerprint(
            placeholder="DIDPH0000QAAAAAAAAZH",
            kind=ProtectedKind.USER_MENTION,
            order_index=0,
            value_sha256="0" * 64,
            restore_value="<@123456789012345678>",
        )
        protection = ProtectionResult(
            masked_text="Ping DIDPH0000QAAAAAAAAZH. See also", fingerprints=(fingerprint,)
        )
        translated = "Ping DIDPH0000QAAAAAAAAZH.Voir aussi"
        repaired = restore_source_proven_url_boundary_spacing(translated, protection)
        assert repaired == translated

    def test_genuine_hallucinated_url_from_ordinary_text_still_rejected(self) -> None:
        """A translator inventing a brand-new URL out of ordinary prose
        (unrelated to any placeholder) must still fail closed -- the
        boundary repair only ever touches the separator immediately after
        an already-issued, already-verified placeholder token; it cannot
        rescue or interact with content it never processed."""
        content = "Please read the announcement carefully."
        nodes = parse(content)
        protection = protect(nodes)
        assert protection.fingerprints == ()
        hallucinated = "Veuillez lire https://evil.example/ attentivement."
        with pytest.raises(IntegrityViolation, match="not present"):
            validate_full_pipeline(nodes, hallucinated, protection)

    def test_genuine_url_mutation_unrelated_to_the_source_proven_boundary_still_rejected(
        self,
    ) -> None:
        """A URL that genuinely differs from the source for any reason
        OTHER than the exact source-proven lost boundary whitespace must
        remain fail closed -- the repair never touches the restored URL
        value itself, only the separator immediately after the still-
        opaque placeholder, so a provider that mutates the URL's own
        path/query cannot be rescued by it."""
        content = "Visit https://example.com/x. See also that."
        nodes = parse(content)
        protection = protect(nodes)
        placeholder = protection.fingerprints[0].placeholder
        mutated = f"Visitez https://example.com/y. Voir aussi cela {placeholder}"
        with pytest.raises(IntegrityViolation):
            validate_full_pipeline(nodes, mutated, protection)

    def test_placeholder_integrity_violations_are_never_masked_by_boundary_repair(self) -> None:
        """Missing/unknown/duplicated placeholders must still fail BEFORE
        boundary normalization can run at all -- proves the wiring order
        in ``validate_and_restore`` (multiset checks first, repair only
        after) rather than merely the isolated helper's own behavior."""
        content = "Visit https://example.com/x. See also that."
        nodes = parse(content)
        protection = protect(nodes)
        placeholder = protection.fingerprints[0].placeholder

        # Missing entirely.
        with pytest.raises(IntegrityViolation, match="dropped"):
            validate_and_restore("No link here at all.", protection)

        # Duplicated.
        with pytest.raises(IntegrityViolation, match="duplicated"):
            validate_and_restore(f"{placeholder} and again {placeholder}.", protection)

        # Unknown/invented token of the same shape.
        with pytest.raises(IntegrityViolation, match="invented"):
            validate_and_restore(f"{placeholder} and DIDPH9999QFFFFFFFFZH.", protection)

    def test_two_urls_only_the_source_proven_boundary_is_repaired(self) -> None:
        """The exact corpus shape: two URLs, only the first has a
        following word in the source (the second is message-final) -- the
        repair must apply only to the first."""
        nodes = parse(_ADVERSARIAL_CONTENT)
        protection = protect(nodes)
        ph_one, ph_two = (fp.placeholder for fp in protection.fingerprints)
        translated = f"See {ph_one}.Then {ph_two}."
        repaired = restore_source_proven_url_boundary_spacing(translated, protection)
        assert repaired == f"See {ph_one}. Then {ph_two}."

    def test_retry_behavior_the_repaired_shape_succeeds_on_the_first_attempt(self) -> None:
        """After the deterministic repair, the exact real-observed
        defective shape must validate successfully on a single
        ``validate_full_pipeline`` call -- no integrity retry is needed
        for this failure class any more (bounded-integrity-retry
        behavior itself, tested in ``test_stage09_rendering.py``, is
        unrelated to this repair and remains unchanged)."""
        nodes = parse(_ADVERSARIAL_CONTENT)
        protection = protect(nodes)
        ph_one, ph_two = (fp.placeholder for fp in protection.fingerprints)
        translated = f"See {ph_one}.Then also {ph_two}."
        # A single call, no retry loop involved at all -- if this raises,
        # the fix does not work; there is no second attempt to fall back on.
        restored = validate_full_pipeline(nodes, translated, protection)
        assert _ADVERSARIAL_URL_ONE in restored
        assert _ADVERSARIAL_URL_TWO in restored
