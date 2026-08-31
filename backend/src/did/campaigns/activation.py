"""WP12: campaign activation / occurrence fan-out orchestration -- the
service connecting campaign lifecycle, a decided occurrence (from a due
schedule or an accepted event -- this module does not decide WHEN, only
WHAT to do once one exists), target resolution, per-Guild re-authorization,
translation/approved-variant selection, and deterministic delivery
creation.

Deliberately does NOT decide when a schedule is due or an event qualifies
(``did.campaigns.scheduling``/``did.campaigns.causality`` already do that)
and does NOT dispatch/send anything (``did.campaigns.delivery_worker``
already does that, via the shared governor) -- this module is exactly the
middle: given one already-decided occurrence, expand it into the correct
set of Guild-scoped ``message_deliveries`` rows, exactly once, safely
resumable after a crash at any point.

Crash-safety contract: the occurrence's own ``PENDING_FANOUT -> CLAIMED ->
FANNED_OUT/FAILED`` lease-fenced lifecycle (``CampaignsRepository
.claim_occurrence_for_fanout``/``finalize_occurrence_fanout``) plus each
delivery's own deterministic, unique ``delivery_key`` together guarantee: a
worker that crashes mid-fan-out leaves the occurrence reclaimable (never
stuck), and a worker that restarts and re-attempts fan-out for an
occurrence that already has some deliveries created will simply see
``create_delivery`` return ``False`` (no-op) for the ones that already
exist and continue creating any that do not -- fan-out is naturally
idempotent per destination, not just per occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from did.campaigns.approved_variants import VariantOutcome, resolve_variant_for_delivery
from did.campaigns.rendering import TranslateMaskedText, render_message_model
from did.campaigns.target_resolution import (
    ResolvedDestination,
    TargetAuthorizationChecker,
    TranslationGroupTopologySnapshot,
    resolve_target,
)
from did.domain.campaigns import (
    ApprovedVariant,
    CampaignTarget,
    GlossaryEntry,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
)
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.messaging.allowed_mentions import CompiledAllowedMentions
from did.messaging.message_model import MessageModel
from did.messaging.protector import IntegrityViolation
from did.messaging.template_variables import TemplateVariableDefinition


class OccurrenceNotClaimable(RuntimeError):
    """The occurrence could not be claimed for fan-out: it does not exist
    for this owner, is already FANNED_OUT/COMPLETED/FAILED (fan-out is a
    one-time, explicit-retry-only operation -- never silently repeated), or
    is currently validly leased by another worker."""


@dataclass(frozen=True, slots=True)
class RenderFailure:
    destination: ResolvedDestination
    target_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class FanOutOutcome:
    occurrence_id: UUID
    deliveries_created: int = 0
    deliveries_already_existed: int = 0
    blocked_destinations: tuple[ResolvedDestination, ...] = ()
    render_failures: tuple[RenderFailure, ...] = field(default_factory=tuple)

    @property
    def is_fully_healthy(self) -> bool:
        return not self.blocked_destinations and not self.render_failures


def _compiled_mentions_dict(compiled_mentions: CompiledAllowedMentions) -> dict[str, object]:
    return {
        "parse": list(compiled_mentions.parse),
        "users": list(compiled_mentions.users),
        "roles": list(compiled_mentions.roles),
        "replied_user": compiled_mentions.replied_user,
    }


def _delivery_key(occurrence: MessageOccurrence, target_id: UUID, dest: ResolvedDestination) -> str:
    """Deterministic and restart-safe: the same (occurrence, target,
    resolved language) triple always produces the same key, so a re-run of
    fan-out after a crash creates no duplicate delivery for a destination
    that was already created, and produces exactly one delivery for a
    destination that was not (message_deliveries UNIQUE(guild_id,
    delivery_key) is the durable source of truth, not this function alone).
    """
    language_component = str(dest.language_profile_id) if dest.language_profile_id else "source"
    return f"{occurrence.occurrence_key}:{target_id}:{language_component}"


async def fan_out_occurrence(
    *,
    repository: CampaignsRepository,
    checker: TargetAuthorizationChecker,
    campaign: MessageCampaign,
    targets: tuple[CampaignTarget, ...],
    occurrence: MessageOccurrence,
    lease_owner: str,
    topology_by_target: dict[UUID, TranslationGroupTopologySnapshot | None],
    language_profile_codes: dict[UUID, str],
    compiled_mentions: CompiledAllowedMentions,
    template_variable_definitions: dict[str, TemplateVariableDefinition],
    glossary_entries: tuple[GlossaryEntry, ...],
    translate_masked_text: TranslateMaskedText | None,
    approve_fresh_translations: bool = False,
) -> FanOutOutcome:
    """Expand ``occurrence`` into deliveries for every ready, authorized
    destination across ``targets``. Never sends anything to Discord --
    every destination becomes an explicit Guild-scoped ``message_deliveries``
    row for :func:`did.campaigns.delivery_worker.process_delivery` to pick
    up later, exactly the multi-Guild-parent-never-calls-Discord-directly
    contract.

    ``approve_fresh_translations``: when a destination requires a translation
    that is MISSING/STALE and one is freshly rendered here, whether to also
    immediately upsert it as the new approved variant (REUSABLE for the next
    occurrence of an otherwise-unchanged recurring campaign) -- False by
    default, since auto-approving a machine translation without any human
    review contradicts REQ-MSG-016's explicit "never claim semantic
    perfection" stance; a caller representing an explicit human-reviewed
    approval flow should pass True only when that review has actually
    happened.
    """
    created = await repository.create_occurrence(campaign.owner_discord_user_id, occurrence)
    if created:
        occurrence_id = occurrence.id
    else:
        existing = await repository.get_occurrence_by_key(
            campaign.owner_discord_user_id, campaign.id, occurrence.occurrence_key
        )
        if existing is None:
            raise OccurrenceNotClaimable(
                f"occurrence {occurrence.occurrence_key} could not be created or found"
            )
        if existing["status"] in ("FANNED_OUT", "COMPLETED", "FAILED"):
            return FanOutOutcome(occurrence_id=existing["id"])
        occurrence_id = existing["id"]

    claimed = await repository.claim_occurrence_for_fanout(
        campaign.owner_discord_user_id, occurrence_id, lease_owner=lease_owner
    )
    if claimed is None:
        raise OccurrenceNotClaimable(
            f"occurrence {occurrence_id} is not currently claimable for fan-out"
        )
    lease_token = claimed["lease_token"]

    approved_variants_raw = await repository.list_approved_variants(
        campaign.owner_discord_user_id, campaign.id
    )
    approved_variants = {
        code: ApprovedVariant(
            id=row["id"],
            owner_discord_user_id=row["owner_discord_user_id"],
            campaign_id=row["campaign_id"],
            target_language_code=row["target_language_code"],
            source_fingerprint=row["source_fingerprint"],
            localized_message_model=row["localized_message_model"],
            approved_by_discord_user_id=row["approved_by_discord_user_id"],
        )
        for code, row in approved_variants_raw.items()
    }

    source_model = MessageModel.from_dict(campaign.message_model)
    mentions_dict = _compiled_mentions_dict(compiled_mentions)

    deliveries_created = 0
    deliveries_already_existed = 0
    blocked: list[ResolvedDestination] = []
    render_failures: list[RenderFailure] = []

    for target in targets:
        destinations = await resolve_target(
            target,
            owner_discord_user_id=campaign.owner_discord_user_id,
            authorization=checker,
            topology=topology_by_target.get(target.id),
        )
        for dest in destinations:
            if not dest.is_ready:
                blocked.append(dest)
                continue

            if dest.language_profile_id is None:
                content_model = await render_message_model(
                    source_model,
                    target_language=campaign.source_language_code,
                    campaign_id=campaign.id,
                    guild_id=dest.guild_id,
                    template_variable_definitions=template_variable_definitions,
                    glossary_entries=glossary_entries,
                    translate_masked_text=None,
                )
            else:
                target_language_code = language_profile_codes.get(dest.language_profile_id)
                if target_language_code is None:
                    render_failures.append(
                        RenderFailure(
                            dest, target.id, "unknown language_profile_id (no code mapping)"
                        )
                    )
                    continue
                resolution = resolve_variant_for_delivery(
                    campaign, target_language_code, approved_variants
                )
                if resolution.outcome is VariantOutcome.REUSABLE:
                    assert resolution.localized_message_model is not None
                    content_model = MessageModel.from_dict(resolution.localized_message_model)
                else:
                    if translate_masked_text is None:
                        render_failures.append(
                            RenderFailure(
                                dest,
                                target.id,
                                f"translation required ({resolution.outcome.value}) but no "
                                "translation provider was supplied",
                            )
                        )
                        continue
                    try:
                        content_model = await render_message_model(
                            source_model,
                            target_language=target_language_code,
                            campaign_id=campaign.id,
                            guild_id=dest.guild_id,
                            template_variable_definitions=template_variable_definitions,
                            glossary_entries=glossary_entries,
                            translate_masked_text=translate_masked_text,
                        )
                    except IntegrityViolation as exc:
                        render_failures.append(RenderFailure(dest, target.id, str(exc)))
                        continue
                    if approve_fresh_translations:
                        from did.campaigns.approved_variants import compute_source_fingerprint

                        await repository.upsert_approved_variant(
                            ApprovedVariant(
                                id=uuid4(),
                                owner_discord_user_id=campaign.owner_discord_user_id,
                                campaign_id=campaign.id,
                                target_language_code=target_language_code,
                                source_fingerprint=compute_source_fingerprint(campaign),
                                localized_message_model=content_model.to_dict(),
                                approved_by_discord_user_id=campaign.owner_discord_user_id,
                            )
                        )

            delivery = MessageDelivery(
                id=uuid4(),
                guild_id=dest.guild_id,
                campaign_id=campaign.id,
                occurrence_id=occurrence_id,
                target_id=target.id,
                language_profile_id=dest.language_profile_id,
                delivery_key=_delivery_key(occurrence, target.id, dest),
                discord_channel_id=dest.discord_channel_id,
                allowed_mentions_snapshot=mentions_dict,
                content_snapshot=content_model.to_dict(),
            )
            if await repository.create_delivery(delivery):
                deliveries_created += 1
            else:
                deliveries_already_existed += 1

    final_status = "FANNED_OUT" if not render_failures else "FAILED"
    await repository.finalize_occurrence_fanout(
        campaign.owner_discord_user_id, occurrence_id, lease_token, status=final_status
    )

    return FanOutOutcome(
        occurrence_id=occurrence_id,
        deliveries_created=deliveries_created,
        deliveries_already_existed=deliveries_already_existed,
        blocked_destinations=tuple(blocked),
        render_failures=tuple(render_failures),
    )
