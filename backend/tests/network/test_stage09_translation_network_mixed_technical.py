"""Real-network TARGETED qualification for the STAGE09 -- SOURCE-PROVEN
PROTECTED-TOKEN BOUNDARY SPACING REMEDIATION mission's fix
(did.messaging.protector.restore_source_proven_protected_boundary_spacing).

Skipped unless DID_ALLOW_NETWORK=1 (see conftest.py). Exercises ONLY the
``mixed_technical_and_linguistic`` corpus item, in all 12 directed language
pairs (the full EN/FR/DE/ES matrix), through the EXACT production path:
``did.campaigns.rendering.render_field_text`` (FULL_MASKED_MESSAGE, the same
bounded integrity retry every real delivery gets, the same
``validate_full_pipeline()`` fail-closed gate), the exact same
``GoogleTranslateRpcCampaignTranslationProvider`` construction
``did.runtime.py`` itself uses. This deliberately reuses
``scripts/generate_human_semantic_review_pack.py``'s own
``translate_one_for_review`` helper directly rather than
``scripts/run_translation_benchmark.py``'s ``_run_one_production`` -- that
script's ``MeasurementRecord.translated_preview`` is truncated to 80
characters (correct for its own statistical-evidence purpose), which is too
short to assert boundary spacing on this corpus item's COMPLETE text; this
qualification needs (and gets, via ``translate_one_for_review``) the full
untruncated restored text.

Why this exists: the real 36-row human semantic review pack (SHA
``92fa8aae18542416790767909e45a755ee6e321e``) found this exact content class
exhibiting a lost-whitespace defect at TWO protected-token boundaries
(USER_MENTION+"!", TIMESTAMP+".") in all 12/12 directed pairs -- a
PRESENTATION defect that placeholder-multiset integrity alone could not
detect (see ``did.messaging.protector``'s module-level docstring on
``restore_source_proven_protected_boundary_spacing`` for the full write-up).
This targeted qualification (12 real calls, not the full ~2272-attempt
canonical benchmark) is what the product owner runs, AFTER an external audit
of the fix, to confirm the generalized repair actually closes this defect
against the real endpoint -- see docs/90_handoffs/STAGE_09_HANDOFF.md for the
full evidence trail. Only once this passes 12/12 with correct boundary
spacing should the product owner regenerate
docs/90_handoffs/evidence/stage09/HUMAN_SEMANTIC_REVIEW.md for actual human
semantic scoring.

Never mocks anything -- a real network failure here must be a real, honest
test failure, not silently downgraded. Assertions on boundary spacing are
deliberately derived from the SOURCE corpus item's own parsed structure (via
``did.messaging.parser.parse`` and
``did.messaging.protector.SUPPORTED_BOUNDARY_PUNCTUATION`` -- the exact same
matrix the fix itself uses) rather than hardcoded target-language words, so
this qualification stays valid regardless of which exact words Google
Translate happens to choose for a given direction.

Usage:
    DID_ALLOW_NETWORK=1 uv run pytest \\
        backend/tests/network/test_stage09_translation_network_mixed_technical.py \\
        -m translation_network -v -s
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from did.messaging.parser import ProtectedNode, parse
from did.messaging.protector import SUPPORTED_BOUNDARY_PUNCTUATION
from did.translation.google_translate_rpc_adapter import (
    GoogleTranslateRpcCampaignTranslationProvider,
)
from generate_human_semantic_review_pack import translate_one_for_review

pytestmark = [pytest.mark.translation_network]

_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "translation_corpus" / "stage09_corpus.json"
)
_MIXED_TECHNICAL_CLASS = "mixed_technical_and_linguistic"


def _load_mixed_technical_items() -> dict[str, dict[str, str]]:
    corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    items: dict[str, dict[str, str]] = {}
    for language, entries in corpus["items_by_language"].items():
        for entry in entries:
            if entry["class"] == _MIXED_TECHNICAL_CLASS:
                items[language] = entry
    return items


_MIXED_TECHNICAL_ITEMS = _load_mixed_technical_items()
_LANGUAGES = sorted(_MIXED_TECHNICAL_ITEMS)
_DIRECTIONS = [(src, dst) for src in _LANGUAGES for dst in _LANGUAGES if src != dst]


def _is_horizontal_whitespace(character: str) -> bool:
    """TAB, or any Unicode category "Zs" (Separator, space) -- deliberately
    includes ASCII SPACE, NO-BREAK SPACE (U+00A0), NARROW NO-BREAK SPACE
    (U+202F), and every other Unicode space separator, but NEVER a line
    break. Defined independently here (not imported from
    ``did.messaging.protector``) so this qualification's own assertion of
    correctness never silently inherits a blind spot from the production
    repair it is meant to verify -- see the real-network finding (SHA
    ``450bf3b928c931a1355078d3ba3305f8eb8b3ae6``) that motivated this: the
    production repair itself used to recognize only ASCII SPACE/TAB and
    therefore missed a legitimate French NBSP-before-``!`` boundary."""
    return character == "\t" or unicodedata.category(character) == "Zs"


def _skip_horizontal_whitespace(text: str, index: int) -> int:
    while index < len(text) and _is_horizontal_whitespace(text[index]):
        index += 1
    return index


def _source_proven_boundaries(source_content: str) -> list[tuple[str, str]]:
    """Every (restore_value, punctuation) pair the SOURCE structure itself
    proves a whitespace-after-punctuation boundary for -- derived from the
    real parsed node sequence, never from a hardcoded target-language word.
    A ProtectedNode's own restore value survives translation byte-for-byte
    (proven separately by placeholder-multiset integrity), so it is a safe,
    language-independent anchor to search for in the restored text."""
    nodes = parse(source_content)
    boundaries: list[tuple[str, str]] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, ProtectedNode):
            continue
        punctuation = SUPPORTED_BOUNDARY_PUNCTUATION.get(node.kind)
        if punctuation is None:
            continue
        if index + 1 >= len(nodes):
            continue  # nothing follows this node in the source at all
        following = nodes[index + 1]
        if not hasattr(following, "text"):
            continue  # next node is itself protected, not plain text
        following_text = following.text  # type: ignore[union-attr]
        boundary = _skip_horizontal_whitespace(following_text, 0)
        if boundary >= len(following_text) or following_text[boundary] != punctuation:
            continue
        after_punctuation = boundary + 1
        if after_punctuation < len(following_text) and following_text[after_punctuation].isspace():
            boundaries.append((node.value, punctuation))
    return boundaries


def _assert_boundaries_are_correctly_spaced(
    restored_text: str, source_proven_boundaries: list[tuple[str, str]]
) -> None:
    """For every source-proven (value, punctuation) boundary, the SAME
    value in the restored text must have the punctuation followed by
    whitespace (or nothing, i.e. end of string) -- NEVER glued directly to
    a non-whitespace character. This is exactly the defect the fix
    repairs; asserting it here (rather than trusting integrity_ok alone)
    proves the repair actually ran, not merely that no *structural*
    violation was raised.

    Uses ``_is_horizontal_whitespace`` (Unicode category "Zs" or TAB) to
    locate the punctuation after the protected value, so a legitimate
    Unicode horizontal-whitespace character (e.g. French NBSP before "!")
    is correctly skipped over on the way to the punctuation -- while a
    genuinely still-glued boundary (no whitespace at all after the
    punctuation) still fails this assertion exactly as before."""
    for value, punctuation in source_proven_boundaries:
        value_index = restored_text.find(value)
        assert value_index != -1, f"restored text lost protected value {value!r} entirely"
        after_value = value_index + len(value)
        index = _skip_horizontal_whitespace(restored_text, after_value)
        assert index < len(restored_text) and restored_text[index] == punctuation, (
            f"expected {value!r} to be followed by {punctuation!r} in restored text: "
            f"{restored_text!r}"
        )
        after_punctuation = index + 1
        glued = (
            after_punctuation < len(restored_text)
            and not restored_text[after_punctuation].isspace()
        )
        assert not glued, (
            f"BOUNDARY-SPACING DEFECT NOT REPAIRED: {value!r}{punctuation!r} is glued directly "
            f"to the next character in restored text: {restored_text!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("source_language", "target_language"), _DIRECTIONS)
async def test_mixed_technical_item_passes_the_real_production_pipeline_with_correct_spacing(
    source_language: str, target_language: str
) -> None:
    """One real measurement per directed pair -- the exact production
    provider/render_field_text/retry/validation pipeline, on ONLY the
    ``mixed_technical_and_linguistic`` corpus item. Must report zero
    provider/transport errors, 100% protected-token integrity, AND
    correctly-spaced protected boundaries (source-derived, never
    hardcoded target words) for every direction."""
    assert len(_MIXED_TECHNICAL_ITEMS) == 4, (
        "expected exactly 4 mixed_technical_and_linguistic corpus items (EN/FR/DE/ES); "
        f"found {sorted(_MIXED_TECHNICAL_ITEMS)}"
    )
    item = _MIXED_TECHNICAL_ITEMS[source_language]
    source_proven_boundaries = _source_proven_boundaries(item["content"])
    assert source_proven_boundaries, (
        f"expected at least one source-proven boundary for {source_language!r}'s "
        f"{_MIXED_TECHNICAL_CLASS} item -- corpus item may have changed shape"
    )

    provider = GoogleTranslateRpcCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=3)

    async def translate_one(masked_text: str, source: str, target: str) -> str:
        result = await provider.translate(
            masked_text, source_language=source, target_language=target
        )
        return result.translated_text

    row = await translate_one_for_review(
        translate_one,
        row_id=0,
        source_language=source_language,
        target_language=target_language,
        item=item,
    )

    print(
        f"\n[mixed_technical {source_language}->{target_language}] "
        f"integrity={row.protected_integrity_result} "
        f"error={row.provider_error!r} "
        f"http_attempts={row.http_attempt_count} "
        f"integrity_retries={row.integrity_retry_count} "
        f"restored={row.restored_text!r}"
    )

    assert row.provider_error is None, (
        f"real provider/transport error for {source_language}->{target_language}: "
        f"{row.provider_error}"
    )
    assert row.protected_integrity_result == "PASS", (
        f"protected-token integrity FAILED for {source_language}->{target_language}: "
        f"{row.restored_text!r}"
    )
    assert row.restored_text is not None
    _assert_boundaries_are_correctly_spaced(row.restored_text, source_proven_boundaries)
