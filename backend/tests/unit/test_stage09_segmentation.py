"""Unit tests for WP10 segmentation strategies (offline, fake translate)."""

from __future__ import annotations

import pytest

from did.messaging.parser import TextNode, parse
from did.messaging.protector import protect
from did.translation.segmentation import (
    SegmentationStrategy,
    count_text_nodes,
    segment_count,
    select_translation_strategy,
    translate_masked_text,
    translate_nodes_naively,
)

pytestmark = [pytest.mark.security]


async def _uppercase(segment: str) -> str:
    return segment.upper()


class TestFullMaskedMessage:
    @pytest.mark.asyncio
    async def test_translates_as_a_single_call(self) -> None:
        calls = []

        async def track(segment: str) -> str:
            calls.append(segment)
            return segment.upper()

        result = await translate_masked_text(
            "hello world", SegmentationStrategy.FULL_MASKED_MESSAGE, track
        )
        assert result == "HELLO WORLD"
        assert len(calls) == 1


class TestParagraphGrouping:
    @pytest.mark.asyncio
    async def test_splits_on_blank_lines(self) -> None:
        text = "First paragraph.\n\nSecond paragraph."
        calls = []

        async def track(segment: str) -> str:
            calls.append(segment)
            return segment.upper()

        result = await translate_masked_text(text, SegmentationStrategy.PARAGRAPH_GROUPING, track)
        assert len(calls) == 2
        assert result == "FIRST PARAGRAPH.\n\nSECOND PARAGRAPH."

    def test_segment_count_matches_paragraphs(self) -> None:
        text = "A.\n\nB.\n\nC."
        assert segment_count(text, SegmentationStrategy.PARAGRAPH_GROUPING) == 3


class TestSentenceGrouping:
    @pytest.mark.asyncio
    async def test_splits_on_sentence_boundaries(self) -> None:
        text = "One sentence. Two sentence! Three sentence?"
        calls = []

        async def track(segment: str) -> str:
            calls.append(segment)
            return segment

        await translate_masked_text(text, SegmentationStrategy.SENTENCE_GROUPING, track)
        assert len(calls) == 3

    def test_single_sentence_is_one_segment(self) -> None:
        assert segment_count("Just one.", SegmentationStrategy.SENTENCE_GROUPING) == 1


class TestNaivePerTextNode:
    @pytest.mark.asyncio
    async def test_translates_each_text_node_independently_and_preserves_placeholders(
        self,
    ) -> None:
        content = "Hello <@123456789012345678>, how are you?"
        nodes = parse(content)
        protection = protect(nodes)
        protected_positions = [i for i, n in enumerate(nodes) if not isinstance(n, TextNode)]
        placeholders = dict(
            zip(
                protected_positions,
                [fp.placeholder for fp in protection.fingerprints],
                strict=True,
            )
        )
        calls: list[str] = []

        async def track(segment: str) -> str:
            calls.append(segment)
            return segment.upper()

        result = await translate_nodes_naively(nodes, placeholders, track)
        assert len(calls) == count_text_nodes(nodes)
        assert protection.fingerprints[0].placeholder in result
        assert result == result.upper() or "<@" not in result  # sanity: placeholder untouched

    def test_count_text_nodes_ignores_blank_and_protected(self) -> None:
        nodes = parse("Hi <@123456789012345678> there")
        assert count_text_nodes(nodes) == 2  # "Hi " and " there"


class TestStrategySelection:
    def test_short_message_selects_full_masked_message(self) -> None:
        assert select_translation_strategy("short message") is (
            SegmentationStrategy.FULL_MASKED_MESSAGE
        )

    def test_long_message_falls_back_to_paragraph_grouping(self) -> None:
        assert select_translation_strategy("x" * 2000) is (
            SegmentationStrategy.PARAGRAPH_GROUPING
        )
