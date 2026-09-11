"""Real-network TARGETED qualification for the STAGE09 -- URL PLACEHOLDER
SENTENCE-BOUNDARY INTEGRITY REMEDIATION mission's fix
(did.messaging.protector.restore_source_proven_url_boundary_spacing).

Skipped unless DID_ALLOW_NETWORK=1 (see conftest.py). Exercises ONLY the
``url_adversarial`` corpus item, in all 12 directed language pairs (the
full EN/FR/DE/ES matrix), through the EXACT real production measurement
path: the same ``GoogleTranslateRpcCampaignTranslationProvider``
construction ``did.runtime.py`` itself uses, FULL_MASKED_MESSAGE
segmentation wrapped in the same bounded integrity retry
``did.campaigns.rendering`` applies to every real delivery. This reuses
``scripts/run_translation_benchmark.py``'s own ``_run_one_production``
function directly rather than reimplementing an approximation of it, so
this test genuinely IS the production measurement, on a small, targeted
subset -- not a different pipeline that merely resembles it.

Why this exists: the real canonical benchmark (SHA
``1d71164f5ab24f1585048b3fcc226461d5b2ce1d``) found this exact content
class failing 12/12 across every directed pair -- the ONLY class that
failed production integrity in that run. This targeted qualification (12
real calls, not the full ~2285-attempt canonical benchmark) is what the
product owner runs to confirm the fix works against the real endpoint
BEFORE rerunning the full benchmark -- see
docs/90_handoffs/STAGE_09_HANDOFF.md for the full evidence trail and the
forensic root-cause writeup.

Never mocks anything -- a real network failure here must be a real,
honest test failure, not silently downgraded.

Usage:
    DID_ALLOW_NETWORK=1 uv run pytest \\
        backend/tests/network/test_stage09_translation_network_url_adversarial.py \\
        -m translation_network -v -s
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from did.translation.google_translate_rpc_adapter import (
    GoogleTranslateRpcCampaignTranslationProvider,
)
from run_translation_benchmark import _run_one_production

pytestmark = [pytest.mark.translation_network]

_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "translation_corpus" / "stage09_corpus.json"
)


def _load_url_adversarial_items() -> dict[str, dict[str, str]]:
    corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    items: dict[str, dict[str, str]] = {}
    for language, entries in corpus["items_by_language"].items():
        for entry in entries:
            if entry["class"] == "url_adversarial":
                items[language] = entry
    return items


_URL_ADVERSARIAL_ITEMS = _load_url_adversarial_items()
_LANGUAGES = sorted(_URL_ADVERSARIAL_ITEMS)
_DIRECTIONS = [(src, dst) for src in _LANGUAGES for dst in _LANGUAGES if src != dst]


@pytest.mark.asyncio
@pytest.mark.parametrize(("source_language", "target_language"), _DIRECTIONS)
async def test_url_adversarial_item_passes_the_real_production_pipeline(
    source_language: str, target_language: str
) -> None:
    """One real measurement per directed pair -- the exact production
    provider/strategy/retry/validation pipeline, on ONLY the
    ``url_adversarial`` corpus item. Must report zero provider/transport
    errors and 100% protected-token integrity for every direction; the
    transport attempt count and a translated preview are printed for
    manual inspection (run with ``-s`` to see them; pytest never silently
    discards them)."""
    assert len(_URL_ADVERSARIAL_ITEMS) == 4, (
        "expected exactly 4 url_adversarial corpus items (EN/FR/DE/ES); "
        f"found {sorted(_URL_ADVERSARIAL_ITEMS)}"
    )
    item = _URL_ADVERSARIAL_ITEMS[source_language]
    provider = GoogleTranslateRpcCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=3)
    record = await _run_one_production(provider, item, source_language, target_language)

    print(
        f"\n[url_adversarial {source_language}->{target_language}] "
        f"error={record.error!r} "
        f"integrity_ok={record.protected_integrity_ok} "
        f"transport_attempts={record.provider_invocation_count} "
        f"retry_count={record.retry_count} "
        f"preview={record.translated_preview!r}"
    )

    assert record.error is None, (
        f"real provider/transport error for {source_language}->{target_language}: {record.error}"
    )
    assert record.protected_integrity_ok is True, (
        f"protected-token integrity FAILED for {source_language}->{target_language}: "
        f"{record.translated_preview!r}"
    )
