"""Approved localized variant reuse (WP11).

REQ-MSG-016/017: an approved variant is reused for a recurring campaign's
unchanged source without re-translating on every occurrence, but only while
``ApprovedVariant.source_fingerprint`` still matches the campaign's current
rendered content -- the moment the source changes, the previous approval
becomes stale and unusable until a human reviews or regenerates it. This
module never silently falls back to live (re-)translation when a variant is
missing/stale; the caller decides what to do next (translate live, block,
etc.) based on the ``VariantResolution`` returned here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from did.domain.campaigns import ApprovedVariant, MessageCampaign


def compute_source_fingerprint(campaign: MessageCampaign) -> str:
    """Deterministic sha256 over the campaign's rendered source content --
    the exact thing an approval is scoped to. Canonical JSON (sorted keys,
    no whitespace) so equivalent content always fingerprints identically
    regardless of dict insertion order."""
    canonical = json.dumps(campaign.message_model, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class VariantOutcome(StrEnum):
    REUSABLE = "REUSABLE"
    STALE = "STALE"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class VariantResolution:
    outcome: VariantOutcome
    variant: ApprovedVariant | None

    @property
    def localized_message_model(self) -> dict[str, object] | None:
        if self.outcome is not VariantOutcome.REUSABLE or self.variant is None:
            return None
        return self.variant.localized_message_model


def resolve_variant_for_delivery(
    campaign: MessageCampaign,
    target_language_code: str,
    approved_variants: dict[str, ApprovedVariant],
) -> VariantResolution:
    """``approved_variants`` keyed by target_language_code -- the caller's
    repository read, one row per (campaign, language) per the WP1 unique
    constraint."""
    variant = approved_variants.get(target_language_code)
    if variant is None:
        return VariantResolution(outcome=VariantOutcome.MISSING, variant=None)

    current_fingerprint = compute_source_fingerprint(campaign)
    if variant.is_stale_for(current_fingerprint):
        return VariantResolution(outcome=VariantOutcome.STALE, variant=variant)

    return VariantResolution(outcome=VariantOutcome.REUSABLE, variant=variant)
