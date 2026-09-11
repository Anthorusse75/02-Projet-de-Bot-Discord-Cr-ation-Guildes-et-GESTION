"""Unit tests for REQ-MSG-007/013 double-translation safety
(did.campaigns.translation_group_safety): SOURCE_ONLY/EXISTING_PROVIDER are
always safe; DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES are safe only when no
active external provider is bound, and fail closed to
MANUAL_CONFIGURATION_REQUIRED for every other real Stage08 provider status.
"""

from __future__ import annotations

import pytest

from did.campaigns.translation_group_safety import (
    TranslationGroupSafetyDecision,
    evaluate_translation_group_safety,
)
from did.domain.campaigns import TranslationPublicationMode

pytestmark = [pytest.mark.security]


class TestSourceOnlyAndExistingProviderAlwaysSafe:
    @pytest.mark.parametrize(
        "mode",
        [TranslationPublicationMode.SOURCE_ONLY, TranslationPublicationMode.EXISTING_PROVIDER],
    )
    @pytest.mark.parametrize(
        "provider_binding_status",
        [
            None,
            "READY",
            "DEGRADED",
            "ERROR",
            "DISABLED",
            "UNKNOWN",
            "MANUAL_CONFIGURATION_REQUIRED",
        ],
    )
    def test_always_safe_regardless_of_provider_state(
        self, mode: TranslationPublicationMode, provider_binding_status: str | None
    ) -> None:
        result = evaluate_translation_group_safety(
            publication_mode=mode, provider_binding_status=provider_binding_status
        )
        assert result.is_safe
        assert result.decision is TranslationGroupSafetyDecision.SAFE


class TestDidTranslatedModesGateOnProviderState:
    @pytest.mark.parametrize(
        "mode",
        [
            TranslationPublicationMode.DID_TRANSLATED_FANOUT,
            TranslationPublicationMode.SELECTED_LANGUAGES,
        ],
    )
    def test_safe_when_no_provider_is_bound(self, mode: TranslationPublicationMode) -> None:
        result = evaluate_translation_group_safety(
            publication_mode=mode, provider_binding_status=None
        )
        assert result.is_safe

    @pytest.mark.parametrize(
        "mode",
        [
            TranslationPublicationMode.DID_TRANSLATED_FANOUT,
            TranslationPublicationMode.SELECTED_LANGUAGES,
        ],
    )
    def test_safe_when_bound_provider_is_disabled(self, mode: TranslationPublicationMode) -> None:
        result = evaluate_translation_group_safety(
            publication_mode=mode, provider_binding_status="DISABLED"
        )
        assert result.is_safe

    @pytest.mark.parametrize(
        "mode",
        [
            TranslationPublicationMode.DID_TRANSLATED_FANOUT,
            TranslationPublicationMode.SELECTED_LANGUAGES,
        ],
    )
    @pytest.mark.parametrize(
        "provider_binding_status",
        ["READY", "DEGRADED", "ERROR", "UNKNOWN", "MANUAL_CONFIGURATION_REQUIRED"],
    )
    def test_requires_manual_configuration_for_every_other_real_status(
        self, mode: TranslationPublicationMode, provider_binding_status: str
    ) -> None:
        """Never fake provider coordination and never guess: DID has no
        visibility into whether a READY/DEGRADED/ERROR/UNKNOWN/
        MANUAL_CONFIGURATION_REQUIRED external provider actually
        re-translates DID's own posts, so every one of these fails closed
        identically -- there is no status this module treats as "probably
        fine"."""
        result = evaluate_translation_group_safety(
            publication_mode=mode, provider_binding_status=provider_binding_status
        )
        assert not result.is_safe
        assert result.decision is TranslationGroupSafetyDecision.MANUAL_CONFIGURATION_REQUIRED
        assert provider_binding_status in result.reason
