"""Real-network smoke test for the production translation adapter (WP9).

Skipped unless DID_ALLOW_NETWORK=1 (see conftest.py). This proves the ACTUAL
production adapter -- did.translation.google_translate_rpc_adapter
.GoogleTranslateRpcCampaignTranslationProvider, the exact same construction
did.runtime.py itself uses -- works end-to-end against the real Google
Translate Web RPC endpoint, real outbound HTTP, distinct from the fully
offline unit tests in test_stage09_google_translate_rpc_adapter.py which
mock the HTTP transport. The full empirical FR/EN/DE/ES benchmark corpus
(WP10) lives in scripts/run_translation_benchmark.py and is a separate,
much larger evidence-gathering exercise -- this test only proves
connectivity/wiring, deliberately with a handful of real calls.

Transport history: the production adapter was originally
did.translation.googletrans_adapter.GoogletransCampaignTranslationProvider
(the unofficial `googletrans` package's `/translate_a/single` endpoint).
That adapter's own real-network smoke was this exact test file until it was
empirically found -- from multiple machines on the product owner's own
network, with a real fail-open defect in that adapter already fixed -- to
consistently receive HTTP 429/403 from that specific endpoint. See
did.translation.google_translate_rpc_adapter's own module docstring and
docs/90_handoffs/STAGE_09_HANDOFF.md for the full, dated evidence trail of
why production switched to the Google Translate Web RPC ("batchexecute")
transport this file now exercises. Never mocks anything -- a real network
failure here must be a real, honest test failure, not silently downgraded.
"""

from __future__ import annotations

import pytest

from did.translation.google_translate_rpc_adapter import (
    GoogleTranslateRpcCampaignTranslationProvider,
)

pytestmark = [pytest.mark.translation_network]

#: Deliberately linguistic prose -- not proper nouns, acronyms, or
#: technical-only strings -- so that `translated_text == source_text` is
#: objectively not an acceptable successful-translation outcome for any of
#: these directions. Each pair is genuinely translatable prose authored
#: natively in the source language.
_LINGUISTIC_SAMPLES: dict[tuple[str, str], str] = {
    ("en", "fr"): "The campaign will be published tomorrow morning.",
    ("fr", "en"): "Nous avons ajouté de nouvelles récompenses pour tout le monde.",
    ("de", "es"): "Die Aktualisierung bringt viele neue Herausforderungen mit sich.",
    ("es", "de"): "Gracias a todos por vuestra paciencia durante el mantenimiento.",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("source_language", "target_language"), sorted(_LINGUISTIC_SAMPLES))
async def test_real_production_provider_translates_linguistic_prose(
    source_language: str, target_language: str
) -> None:
    """Real network call proving the PRODUCTION provider actually
    translates -- not merely that it returns without raising.
    `translated_text == source_text` would also be produced by a silent
    provider-side fallback/echo if this adapter's own fail-closed contract
    ever regressed, so this assertion is the whole point of this test, not
    an incidental extra check."""
    adapter = GoogleTranslateRpcCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=2)
    source_text = _LINGUISTIC_SAMPLES[(source_language, target_language)]
    result = await adapter.translate(
        source_text, source_language=source_language, target_language=target_language
    )
    assert result.source_language == source_language
    assert result.target_language == target_language
    assert result.translated_text.strip() != ""
    assert result.translated_text != source_text


@pytest.mark.asyncio
async def test_real_production_provider_translates_placeholder_preserving_text() -> None:
    """A quick end-to-end sanity check that a DIDPH-style placeholder token
    survives a real round trip through the live translation endpoint -- the
    full statistical measurement of this is WP10's benchmark corpus. This
    test alone must never be read as proof of real translation: a
    placeholder could legitimately survive an untranslated echo too (the
    placeholder is never touched either way) -- see the linguistic prose
    tests above for that assertion."""
    adapter = GoogleTranslateRpcCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=2)
    masked = "Hello DIDPH0000QA1B2C3D4ZH, welcome to the campaign."
    result = await adapter.translate(masked, source_language="en", target_language="de")
    assert "DIDPH0000QA1B2C3D4ZH" in result.translated_text
