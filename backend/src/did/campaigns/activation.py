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

import asyncio
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


class FanOutLeaseLostError(RuntimeError):
    """The occurrence fan-out lease was lost mid-expansion (expired and
    possibly reclaimed by another worker) before this attempt could
    finalize. Deliveries already created up to that point remain durable
    and idempotent (each has its own unique delivery_key) -- but this
    attempt must NEVER report a normal successful FanOutOutcome, since it
    no longer provably owns the occurrence and cannot know whether a
    concurrent reclaimer is also expanding it right now. A future retry
    (this worker or another) safely resumes via the same crash-safety
    contract: create_delivery is idempotent per destination."""


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
    lease_seconds: float = 30.0,
) -> FanOutOutcome:
    """Expand ``occurrence`` into deliveries for every ready, authorized
    destination across ``targets``. Never sends anything to Discord --
    every destination becomes an explicit Guild-scoped ``message_deliveries``
    row for :func:`did.campaigns.delivery_worker.process_delivery` to pick
    up later, exactly the multi-Guild-parent-never-calls-Discord-directly
    contract.

    A destination whose translation is MISSING/STALE gets a fresh render
    here, but that render is NEVER auto-recorded as an approved variant --
    doing so would silently claim human review that never happened
    (REQ-MSG-016). Only an explicit, caller-driven review action (see
    ``did.campaigns.approved_variants.approve_variant``) carrying its own
    authenticated approving principal may create an approved variant.

    ``lease_seconds`` bounds the occurrence's fan-out lease; a background
    heartbeat renews it every ``lease_seconds / 5`` for the duration of this
    call so a slow fan-out (many Guilds/destinations/translation-provider
    calls) does not outlive a short fixed lease. If the lease is lost mid-
    expansion or at finalize time, this raises :class:`FanOutLeaseLostError`
    instead of ever returning a normal successful :class:`FanOutOutcome` --
    deliveries already durably created remain valid and idempotent for a
    future retry.
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

    stopped = asyncio.Event()
    lease_lost = asyncio.Event()

    async def renew_lease() -> None:
        interval = max(0.01, lease_seconds / 5)
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                renewed = await repository.renew_occurrence_fanout_lease(
                    campaign.owner_discord_user_id,
                    occurrence_id,
                    lease_token,
                    lease_seconds=lease_seconds,
                )
            except Exception:
                renewed = False
            if not renewed:
                lease_lost.set()
                return

    async def expand() -> tuple[int, int, list[ResolvedDestination], list[RenderFailure]]:
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
                        # Machine fan-out NEVER records this fresh render as a
                        # human-approved variant -- see approved_variants
                        # .approve_variant for the only path that may (an
                        # explicit, caller-driven review action carrying its
                        # own authenticated principal).

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

        return deliveries_created, deliveries_already_existed, blocked, render_failures

    heartbeat = asyncio.create_task(renew_lease())
    expand_task = asyncio.create_task(expand())
    lost_task = asyncio.create_task(lease_lost.wait())
    try:
        done, _ = await asyncio.wait({expand_task, lost_task}, return_when=asyncio.FIRST_COMPLETED)
        if lost_task in done and lease_lost.is_set() and not expand_task.done():
            expand_task.cancel()
            await asyncio.gather(expand_task, return_exceptions=True)
            raise FanOutLeaseLostError(
                f"occurrence {occurrence_id} fan-out lease was lost mid-expansion"
            )
        (
            deliveries_created,
            deliveries_already_existed,
            blocked,
            render_failures,
        ) = await expand_task
    finally:
        stopped.set()
        if not expand_task.done():
            expand_task.cancel()
        heartbeat.cancel()
        lost_task.cancel()
        await asyncio.gather(heartbeat, lost_task, expand_task, return_exceptions=True)

    final_status = "FANNED_OUT" if not render_failures else "FAILED"
    finalized = await repository.finalize_occurrence_fanout(
        campaign.owner_discord_user_id, occurrence_id, lease_token, status=final_status
    )
    if not finalized:
        # The lease was lost between the last successful renewal and this
        # finalize call (or was never renewed in time for a very short
        # lease_seconds). Deliveries already created above remain durable
        # and idempotent; this attempt must not claim success it can no
        # longer prove it owns.
        raise FanOutLeaseLostError(
            f"occurrence {occurrence_id} fan-out lease was lost before finalize"
        )

    return FanOutOutcome(
        occurrence_id=occurrence_id,
        deliveries_created=deliveries_created,
        deliveries_already_existed=deliveries_already_existed,
        blocked_destinations=tuple(blocked),
        render_failures=tuple(render_failures),
    )
