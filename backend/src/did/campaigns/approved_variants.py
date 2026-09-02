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
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from did.domain.campaigns import ApprovedVariant, MessageCampaign

if TYPE_CHECKING:
    from did.infrastructure.campaigns_repository import CampaignsRepository


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


class ForeignApprovingPrincipalError(ValueError):
    """The approving principal was not the authenticated caller. Approval
    identity is never inferred from campaign ownership or supplied as a
    machine default -- it must be exactly the caller performing this
    explicit action."""


@dataclass(frozen=True, slots=True)
class VariantApproval:
    """An explicit human review decision, never something fan-out infers on
    its own. ``localized_message_model``/``source_fingerprint`` are the
    EXACT content being approved (typically what a translation preview
    already rendered) -- approval always records what a reviewer actually
    saw, never a promise to re-render later."""

    campaign_id: UUID
    target_language_code: str
    localized_message_model: dict[str, object]
    source_fingerprint: str


async def approve_variant(
    repository: CampaignsRepository,
    *,
    owner_discord_user_id: int,
    approving_discord_user_id: int,
    approval: VariantApproval,
) -> ApprovedVariant:
    """Record a variant as human-approved. ``approving_discord_user_id`` MUST
    be the authenticated principal performing this call (e.g. the caller's
    own session identity from the API layer) -- REQ-MSG-016 requires
    truthful audit semantics: a machine translation may be previewed and
    delivered according to policy without ever being recorded as "human
    approved" just because fan-out happened to render it. Fan-out
    (``did.campaigns.activation.fan_out_occurrence``) deliberately has no
    parameter that can trigger this path; only an explicit caller-driven
    review flow (the future API's approval endpoint) may call it."""
    if approving_discord_user_id <= 0:
        raise ForeignApprovingPrincipalError("approving_discord_user_id must be a real principal")
    variant = ApprovedVariant(
        id=uuid4(),
        owner_discord_user_id=owner_discord_user_id,
        campaign_id=approval.campaign_id,
        target_language_code=approval.target_language_code,
        source_fingerprint=approval.source_fingerprint,
        localized_message_model=approval.localized_message_model,
        approved_by_discord_user_id=approving_discord_user_id,
    )
    await repository.upsert_approved_variant(variant)
    return variant
