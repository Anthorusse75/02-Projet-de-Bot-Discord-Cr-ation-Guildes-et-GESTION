"""Unit tests for WP11: approved localized variant fingerprint reuse."""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.approved_variants import (
    VariantOutcome,
    compute_source_fingerprint,
    resolve_variant_for_delivery,
)
from did.domain.campaigns import ApprovedVariant, MessageCampaign, PublicationMode

pytestmark = [pytest.mark.security]


def _campaign(message_model: dict[str, object]) -> MessageCampaign:
    return MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=1,
        logical_campaign_key="k",
        name="Launch",
        source_language_code="en",
        message_model=message_model,
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.RECURRING,
    )


def _variant(campaign: MessageCampaign, target_language_code: str) -> ApprovedVariant:
    return ApprovedVariant(
        id=uuid4(),
        owner_discord_user_id=1,
        campaign_id=campaign.id,
        target_language_code=target_language_code,
        source_fingerprint=compute_source_fingerprint(campaign),
        localized_message_model={"content": "bonjour"},
        approved_by_discord_user_id=1,
    )


class TestComputeSourceFingerprint:
    def test_identical_content_fingerprints_identically_regardless_of_key_order(self) -> None:
        a = _campaign({"content": "hi", "flag": True})
        b = _campaign({"flag": True, "content": "hi"})
        assert compute_source_fingerprint(a) == compute_source_fingerprint(b)

    def test_different_content_fingerprints_differently(self) -> None:
        a = _campaign({"content": "hi"})
        b = _campaign({"content": "hello"})
        assert compute_source_fingerprint(a) != compute_source_fingerprint(b)

    def test_fingerprint_is_a_64_char_hex_digest(self) -> None:
        fingerprint = compute_source_fingerprint(_campaign({"content": "hi"}))
        assert len(fingerprint) == 64
        int(fingerprint, 16)  # raises if not valid hex


class TestResolveVariantForDelivery:
    def test_missing_variant_reports_missing(self) -> None:
        campaign = _campaign({"content": "hi"})
        resolution = resolve_variant_for_delivery(campaign, "fr", {})
        assert resolution.outcome is VariantOutcome.MISSING
        assert resolution.localized_message_model is None

    def test_matching_fingerprint_is_reusable(self) -> None:
        campaign = _campaign({"content": "hi"})
        variant = _variant(campaign, "fr")
        resolution = resolve_variant_for_delivery(campaign, "fr", {"fr": variant})
        assert resolution.outcome is VariantOutcome.REUSABLE
        assert resolution.localized_message_model == variant.localized_message_model

    def test_changed_source_makes_variant_stale(self) -> None:
        campaign = _campaign({"content": "hi"})
        variant = _variant(campaign, "fr")
        changed_campaign = _campaign({"content": "hi there, updated"})
        resolution = resolve_variant_for_delivery(changed_campaign, "fr", {"fr": variant})
        assert resolution.outcome is VariantOutcome.STALE
        assert resolution.localized_message_model is None

    def test_recurring_campaign_reuses_unchanged_variant_across_occurrences(self) -> None:
        """The actual WP11 scenario: same static campaign firing repeatedly
        should keep resolving REUSABLE, never re-translating."""
        campaign = _campaign({"content": "weekly reminder"})
        variant = _variant(campaign, "de")
        for _ in range(5):
            resolution = resolve_variant_for_delivery(campaign, "de", {"de": variant})
            assert resolution.outcome is VariantOutcome.REUSABLE

    def test_wrong_language_key_is_missing_not_a_crash(self) -> None:
        campaign = _campaign({"content": "hi"})
        variant = _variant(campaign, "fr")
        resolution = resolve_variant_for_delivery(campaign, "de", {"fr": variant})
        assert resolution.outcome is VariantOutcome.MISSING
