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


@pytest.mark.asyncio
async def test_real_googletrans_translates_en_to_fr() -> None:
    adapter = GoogletransCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=2)
    result = await adapter.translate(
        "The campaign will be published tomorrow.",
        source_language="en",
        target_language="fr",
    )
    assert result.source_language == "en"
    assert result.target_language == "fr"
    assert result.translated_text.strip() != ""
    assert result.translated_text != "The campaign will be published tomorrow."


@pytest.mark.asyncio
async def test_real_googletrans_translates_placeholder_preserving_text() -> None:
    """A quick end-to-end sanity check that a DIDPH-style placeholder token
    survives a real round trip through the live translation endpoint -- the
    full statistical measurement of this is WP10's benchmark corpus."""
    adapter = GoogletransCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=2)
    masked = "Hello DIDPH0000QA1B2C3D4ZH, welcome to the campaign."
    result = await adapter.translate(masked, source_language="en", target_language="de")
    assert "DIDPH0000QA1B2C3D4ZH" in result.translated_text
