"""Real-network smoke test for the googletrans adapter (WP9).

Skipped unless DID_ALLOW_NETWORK=1 (see conftest.py). This proves the actual
adapter -- real googletrans.Translator, real outbound HTTP -- works
end-to-end, distinct from the fully offline unit tests in
test_stage09_translation_adapter.py which fake the translator. The full
empirical FR/EN/DE/ES benchmark corpus (WP10) lives in
scripts/run_translation_benchmark.py and is a separate, much larger
evidence-gathering exercise -- this test only proves connectivity/wiring.
"""

from __future__ import annotations

import pytest

from did.translation.googletrans_adapter import GoogletransCampaignTranslationProvider

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
async def test_real_googletrans_translates_linguistic_prose(
    source_language: str, target_language: str
) -> None:
    """Real network call proving the provider actually translates -- not
    merely that it returns without raising. `translated_text == source_text`
    would also be produced by googletrans's own `DUMMY_DATA` echo fallback
    when the transport fails and `raise_exception` is left at its unsafe
    default (see `googletrans_adapter._production_translator`), so this
    assertion is the whole point of this test, not an incidental extra
    check."""
    adapter = GoogletransCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=2)
    source_text = _LINGUISTIC_SAMPLES[(source_language, target_language)]
    result = await adapter.translate(
        source_text, source_language=source_language, target_language=target_language
    )
    assert result.source_language == source_language
    assert result.target_language == target_language
    assert result.translated_text.strip() != ""
    assert result.translated_text != source_text


@pytest.mark.asyncio
async def test_real_googletrans_translates_placeholder_preserving_text() -> None:
    """A quick end-to-end sanity check that a DIDPH-style placeholder token
    survives a real round trip through the live translation endpoint -- the
    full statistical measurement of this is WP10's benchmark corpus. This
    test alone must never be read as proof of real translation: a
    placeholder can legitimately survive an echoed DUMMY_DATA response too
    (the placeholder is never touched either way) -- see the linguistic
    prose tests above for that assertion."""
    adapter = GoogletransCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=2)
    masked = "Hello DIDPH0000QA1B2C3D4ZH, welcome to the campaign."
    result = await adapter.translate(masked, source_language="en", target_language="de")
    assert "DIDPH0000QA1B2C3D4ZH" in result.translated_text
