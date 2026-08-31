"""Translation segmentation strategies benchmarked in WP10.

Each strategy takes the already placeholder-masked text (see
``did.messaging.protector``) and decides how to slice it into one or more
segments to send to the translation provider, then how to rejoin the
translated segments back into one masked string for
``protector.validate_and_restore``.

``NAIVE_PER_TEXT_NODE`` is not a segmentation of the masked text at all: it
translates each original TEXT node individually, which is the "no
linguistic context" negative control the Stage 09 spec explicitly asks the
benchmark to include -- never a production candidate.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from enum import StrEnum

from did.messaging.parser import MessageNode, TextNode

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_BOUNDARY = re.compile(r"\n\s*\n")

Translate = Callable[[str], Awaitable[str]]


class SegmentationStrategy(StrEnum):
    FULL_MASKED_MESSAGE = "FULL_MASKED_MESSAGE"
    PARAGRAPH_GROUPING = "PARAGRAPH_GROUPING"
    SENTENCE_GROUPING = "SENTENCE_GROUPING"
    NAIVE_PER_TEXT_NODE = "NAIVE_PER_TEXT_NODE"


async def translate_masked_text(
    masked_text: str, strategy: SegmentationStrategy, translate: Translate
) -> str:
    if strategy is SegmentationStrategy.FULL_MASKED_MESSAGE:
        return await translate(masked_text)

    if strategy is SegmentationStrategy.PARAGRAPH_GROUPING:
        parts = _PARAGRAPH_BOUNDARY.split(masked_text)
        translated = [await translate(part) if part.strip() else part for part in parts]
        return "\n\n".join(translated)

    if strategy is SegmentationStrategy.SENTENCE_GROUPING:
        parts = _SENTENCE_BOUNDARY.split(masked_text)
        translated = [await translate(part) if part.strip() else part for part in parts]
        return " ".join(translated)

    raise ValueError(
        f"{strategy} operates on individual TEXT nodes, not masked text -- "
        "the benchmark runner builds it directly from the parsed node sequence"
    )


async def translate_nodes_naively(
    nodes: tuple[MessageNode, ...], placeholders: dict[int, str], translate: Translate
) -> str:
    """NAIVE_PER_TEXT_NODE control: translate each TEXT node's raw text in
    total isolation from its neighbors (worst-case linguistic context),
    leaving PROTECTED nodes as their already-issued placeholder untouched.

    ``placeholders`` maps the position of each PROTECTED node in ``nodes``
    to its placeholder string (from a ``ProtectionResult``).
    """
    out: list[str] = []
    for position, node in enumerate(nodes):
        if isinstance(node, TextNode):
            out.append(await translate(node.text) if node.text.strip() else node.text)
        else:
            out.append(placeholders[position])
    return "".join(out)


def segment_count(masked_text: str, strategy: SegmentationStrategy) -> int:
    if strategy is SegmentationStrategy.FULL_MASKED_MESSAGE:
        return 1
    if strategy is SegmentationStrategy.PARAGRAPH_GROUPING:
        return len([p for p in _PARAGRAPH_BOUNDARY.split(masked_text) if p.strip()])
    if strategy is SegmentationStrategy.SENTENCE_GROUPING:
        return len([p for p in _SENTENCE_BOUNDARY.split(masked_text) if p.strip()])
    return 0


def count_text_nodes(nodes: tuple[MessageNode, ...]) -> int:
    return sum(1 for node in nodes if isinstance(node, TextNode) and node.text.strip())


def select_translation_strategy(masked_text: str) -> SegmentationStrategy:
    """REQ-MSG-024/026: the production default, chosen from real measured
    evidence -- see
    docs/90_handoffs/evidence/stage09/translation-benchmark.json for the
    exact run (live googletrans calls across the full directed FR/EN/DE/ES
    matrix, 4 strategies) this decision is based on.

    Always FULL_MASKED_MESSAGE. External-review correction: an earlier
    version of this function switched to PARAGRAPH_GROUPING above an
    arbitrary 1500-character threshold that no benchmark evidence backed --
    the committed corpus never contained a multi-KB sample, so that
    threshold was a guess, not a measured decision, and has been removed
    (REQ-MSG-026 stays NOT_STARTED: no evidence yet justifies varying the
    strategy by content length or class). FULL_MASKED_MESSAGE achieved 100%
    protected-token integrity with the lowest measured average latency and,
    unlike NAIVE_PER_TEXT_NODE, preserved inter-token whitespace correctly
    (the naive control visibly dropped spaces around placeholders in the
    recorded samples -- concrete evidence for why per-fragment translation
    degrades quality, not just theory). PARAGRAPH_GROUPING/SENTENCE_GROUPING
    remain implemented and benchmarked (see the evidence file) for future
    use if representative long-content corpus classes are added and
    demonstrate a real quality or reliability benefit -- until then,
    picking either automatically would be exactly the unjustified
    threshold this correction removes.
    """
    del masked_text  # kept in the signature: a future length-based decision
    # would read it, but none is applied without measured evidence to back it.
    return SegmentationStrategy.FULL_MASKED_MESSAGE
