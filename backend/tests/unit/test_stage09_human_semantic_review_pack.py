"""Deterministic, offline coverage for
scripts/generate_human_semantic_review_pack.py.

No real network call is ever made here -- a fake, injected ``translate_one``
callable stands in for the real provider, exactly like
did.campaigns.rendering's own retry tests. These tests prove the
GENERATOR's mechanics -- row count/shape, direction coverage, complete
text retention, blank human fields, technical integrity metadata,
determinism -- never a claim about linguistic/translation quality (that is
exactly what the human reviewer's own judgment is for, once the real
36-call pack has been generated for real by the product owner).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from generate_human_semantic_review_pack import (
    REVIEW_FAMILIES,
    ReviewRow,
    _select_review_items,
    build_directions,
    build_review_rows,
    render_markdown,
    translate_one_for_review,
)

pytestmark = [pytest.mark.security]

_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "translation_corpus" / "stage09_corpus.json"
)


def _load_corpus() -> dict[str, object]:
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


async def _identity_translate(masked_text: str, source_language: str, target_language: str) -> str:
    return masked_text


class TestBuildDirections:
    def test_twelve_directed_pairs_no_same_language(self) -> None:
        directions = build_directions(["en", "fr", "de", "es"])
        assert len(directions) == 12
        assert len(set(directions)) == 12
        assert all(src != dst for src, dst in directions)

    def test_every_language_appears_as_both_source_and_target(self) -> None:
        directions = build_directions(["en", "fr", "de", "es"])
        sources = {src for src, _ in directions}
        targets = {dst for _, dst in directions}
        assert sources == {"en", "fr", "de", "es"}
        assert targets == {"en", "fr", "de", "es"}


class TestSelectReviewItems:
    def test_selects_exactly_one_item_per_language_per_family(self) -> None:
        corpus = _load_corpus()
        selected = _select_review_items(corpus)
        assert set(selected) == {"en", "fr", "de", "es"}
        for _language, by_family in selected.items():
            assert set(by_family) == set(REVIEW_FAMILIES)
            for family, item in by_family.items():
                assert item["class"] == family

    def test_raises_loudly_when_a_family_is_missing_for_a_language(self) -> None:
        corpus = {
            "items_by_language": {
                "en": [{"id": "x", "class": "negation_and_pronouns", "content": "..."}],
            }
        }
        with pytest.raises(ValueError, match="long_sentence"):
            _select_review_items(corpus)

    def test_raises_loudly_when_a_family_is_duplicated_for_a_language(self) -> None:
        corpus = {
            "items_by_language": {
                "en": [
                    {"id": "a", "class": "negation_and_pronouns", "content": "one"},
                    {"id": "b", "class": "negation_and_pronouns", "content": "two"},
                    {"id": "c", "class": "long_sentence", "content": "three"},
                    {"id": "d", "class": "mixed_technical_and_linguistic", "content": "four"},
                ],
            }
        }
        with pytest.raises(ValueError, match="negation_and_pronouns"):
            _select_review_items(corpus)


class TestBuildReviewRows:
    async def test_exactly_36_rows(self) -> None:
        corpus = _load_corpus()
        rows = await build_review_rows(_identity_translate, corpus)
        assert len(rows) == 36

    async def test_exactly_12_directed_pairs_each_with_exactly_3_rows(self) -> None:
        corpus = _load_corpus()
        rows = await build_review_rows(_identity_translate, corpus)
        counts: dict[tuple[str, str], int] = {}
        for row in rows:
            key = (row.source_language, row.target_language)
            counts[key] = counts.get(key, 0) + 1
        assert len(counts) == 12
        assert set(counts.values()) == {3}

    async def test_no_same_language_pair(self) -> None:
        corpus = _load_corpus()
        rows = await build_review_rows(_identity_translate, corpus)
        assert all(row.source_language != row.target_language for row in rows)

    async def test_each_direction_uses_exactly_the_three_review_families(self) -> None:
        corpus = _load_corpus()
        rows = await build_review_rows(_identity_translate, corpus)
        by_direction: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            key = (row.source_language, row.target_language)
            by_direction.setdefault(key, set()).add(row.item_class)
        for classes in by_direction.values():
            assert classes == set(REVIEW_FAMILIES)

    async def test_complete_source_text_retained_verbatim_from_the_corpus(self) -> None:
        corpus = _load_corpus()
        rows = await build_review_rows(_identity_translate, corpus)
        items_by_language: dict[str, list[dict[str, str]]] = corpus["items_by_language"]  # type: ignore[assignment]
        for row in rows:
            source_items = items_by_language[row.source_language]
            matching = [i for i in source_items if i["id"] == row.item_id]
            assert len(matching) == 1
            assert row.source_text == matching[0]["content"]

    async def test_no_content_outside_the_committed_synthetic_corpus(self) -> None:
        """Every row's source text must be traceable to the committed
        fixture file -- proves this pack never injects private/user
        content, only the synthetic corpus."""
        corpus = _load_corpus()
        rows = await build_review_rows(_identity_translate, corpus)
        all_corpus_texts = {
            item["content"]
            for items in corpus["items_by_language"].values()  # type: ignore[union-attr]
            for item in items
        }
        for row in rows:
            assert row.source_text in all_corpus_texts

    async def test_complete_restored_text_retained_not_truncated(self) -> None:
        """Deliberately unlike the benchmark's 80-char translated_preview --
        a human reviewer needs the FULL text."""
        long_content = "A" * 500

        async def echo_long(masked_text: str, source_language: str, target_language: str) -> str:
            return masked_text

        corpus = _load_corpus()
        # Patch one item's content to something long to prove no truncation
        # happens anywhere in the row-building path.
        items_by_language: dict[str, list[dict[str, str]]] = corpus["items_by_language"]  # type: ignore[assignment]
        for item in items_by_language["en"]:
            if item["class"] == "negation_and_pronouns":
                item["content"] = long_content
        rows = await build_review_rows(echo_long, corpus)
        matching = [
            r for r in rows if r.source_language == "en" and r.item_class == "negation_and_pronouns"
        ]
        assert matching
        for row in matching:
            assert row.source_text == long_content
            assert row.restored_text == long_content
            assert len(row.restored_text) == 500

    async def test_deterministic_row_structure_across_two_runs(self) -> None:
        """Apart from the actual translation result and any runtime
        timestamp, two runs against the same corpus and the same fake
        translator must produce byte-identical row metadata and ordering."""
        corpus = _load_corpus()
        rows_a = await build_review_rows(_identity_translate, corpus)
        rows_b = await build_review_rows(_identity_translate, corpus)
        keys_a = [
            (r.row_id, r.source_language, r.target_language, r.item_id, r.item_class)
            for r in rows_a
        ]
        keys_b = [
            (r.row_id, r.source_language, r.target_language, r.item_id, r.item_class)
            for r in rows_b
        ]
        assert keys_a == keys_b


class TestTranslateOneForReview:
    async def test_successful_translation_produces_a_pass_row_with_full_text(self) -> None:
        item = {
            "id": "test-item",
            "class": "plain_prose",
            "content": "Ping <@123456789012345678> now.",
        }

        async def translate(masked_text: str, source_language: str, target_language: str) -> str:
            return masked_text

        row = await translate_one_for_review(
            translate, row_id=1, source_language="en", target_language="fr", item=item
        )
        assert row.protected_integrity_result == "PASS"
        assert row.restored_text == "Ping <@123456789012345678> now."
        assert row.provider_error is None
        assert row.integrity_retry_count == 0
        assert isinstance(row.http_attempt_count, int)

    async def test_integrity_violation_produces_a_fail_row_with_no_restored_text(self) -> None:
        item = {
            "id": "test-item",
            "class": "plain_prose",
            "content": "Ping <@123456789012345678> now.",
        }

        async def translate(masked_text: str, source_language: str, target_language: str) -> str:
            return "no placeholder survived here"

        row = await translate_one_for_review(
            translate, row_id=2, source_language="en", target_language="fr", item=item
        )
        assert row.protected_integrity_result == "FAIL"
        assert row.restored_text is None
        assert row.provider_error is None

    async def test_transport_error_produces_an_error_row_with_the_message(self) -> None:
        item = {"id": "test-item", "class": "plain_prose", "content": "Hello world."}

        async def translate(masked_text: str, source_language: str, target_language: str) -> str:
            raise RuntimeError("simulated transport failure")

        row = await translate_one_for_review(
            translate, row_id=3, source_language="en", target_language="fr", item=item
        )
        assert row.protected_integrity_result == "ERROR"
        assert row.restored_text is None
        assert row.provider_error == "simulated transport failure"

    async def test_retry_count_reflects_real_integrity_retries(self) -> None:
        item = {
            "id": "test-item",
            "class": "plain_prose",
            "content": "Ping <@123456789012345678> now.",
        }
        calls = 0

        async def translate_corrupt_first(
            masked_text: str, source_language: str, target_language: str
        ) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                import re

                match = re.search(r"DIDPH(\d{4})Q([0-9A-F]{8})ZH", masked_text)
                assert match is not None
                index, nonce = match.group(1), match.group(2)
                flipped = "1" if nonce[-1] != "1" else "2"
                mutated = f"DIDPH{index}Q{nonce[:-1]}{flipped}ZH"
                return masked_text[: match.start()] + mutated + masked_text[match.end() :]
            return masked_text

        row = await translate_one_for_review(
            translate_corrupt_first, row_id=4, source_language="en", target_language="fr", item=item
        )
        assert row.protected_integrity_result == "PASS"
        assert row.integrity_retry_count == 1


class TestRenderMarkdown:
    def _sample_rows(self) -> list[ReviewRow]:
        return [
            ReviewRow(
                row_id=1,
                source_language="en",
                target_language="fr",
                item_id="en-negation-pronouns",
                item_class="negation_and_pronouns",
                source_text="She said she would not attend.",
                restored_text="Elle a dit qu'elle n'assisterait pas.",
                protected_integrity_result="PASS",
                provider_error=None,
                http_attempt_count=1,
                integrity_retry_count=0,
            ),
            ReviewRow(
                row_id=2,
                source_language="en",
                target_language="de",
                item_id="en-long-sentence",
                item_class="long_sentence",
                source_text="A very long sentence.",
                restored_text=None,
                protected_integrity_result="ERROR",
                provider_error="HTTP 429",
                http_attempt_count=3,
                integrity_retry_count=0,
            ),
        ]

    def test_human_fields_are_blank_by_construction(self) -> None:
        markdown = render_markdown(self._sample_rows(), generated_at="T", sha="SHA")
        # The blank human-verdict row is an empty markdown table row --
        # never a pre-filled score, never "PASS"/"FAIL" typed in by this
        # generator itself.
        assert "|  |  |  |  |  |  |  |  |" in markdown
        assert "Fidélité sémantique" in markdown  # rubric header present
        # No numeric score characters ("0", "1", "2") appear inside the
        # blank verdict row itself.
        blank_row_index = markdown.index("|  |  |  |  |  |  |  |  |")
        line_end = markdown.index("\n", blank_row_index)
        blank_row_line = markdown[blank_row_index:line_end]
        assert blank_row_line == "|  |  |  |  |  |  |  |  |"

    def test_technical_integrity_metadata_present_for_every_row(self) -> None:
        markdown = render_markdown(self._sample_rows(), generated_at="T", sha="SHA")
        assert "Intégrité des placeholders protégés" in markdown
        assert "`PASS`" in markdown
        assert "`ERROR`" in markdown
        assert "HTTP 429" in markdown
        assert "Nombre de tentatives HTTP réelles" in markdown
        assert "Nombre de reprises d'intégrité" in markdown

    def test_complete_source_and_restored_text_appear_verbatim(self) -> None:
        markdown = render_markdown(self._sample_rows(), generated_at="T", sha="SHA")
        assert "She said she would not attend." in markdown
        assert "Elle a dit qu'elle n'assisterait pas." in markdown

    def test_pending_human_review_status_stated_explicitly(self) -> None:
        markdown = render_markdown(self._sample_rows(), generated_at="T", sha="SHA")
        assert "PENDING_HUMAN_REVIEW" in markdown
        assert "Claude" in markdown  # explicit "never Claude/Codex" statement

    def test_deterministic_for_the_same_rows_and_metadata(self) -> None:
        rows = self._sample_rows()
        first = render_markdown(rows, generated_at="FIXED", sha="FIXEDSHA")
        second = render_markdown(rows, generated_at="FIXED", sha="FIXEDSHA")
        assert first == second

    def test_sha_and_timestamp_are_recorded(self) -> None:
        markdown = render_markdown(
            self._sample_rows(), generated_at="2026-09-11T00:00:00", sha="abc123"
        )
        assert "2026-09-11T00:00:00" in markdown
        assert "abc123" in markdown
