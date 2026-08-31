"""WP12/REQ-MSG-022: the complete campaign simulation -- destinations,
languages, authorization/bot-permission state, approved-variant/translation
state, MESSAGE_CONTENT trigger dependencies, and an estimated delivery
count, all without publishing or mutating anything.

Composes three already-built, independently-tested pure/read-only pieces
rather than duplicating any of their logic:
``did.campaigns.target_resolution.resolve_target`` (destinations +
authorization/bot-permission re-check), ``did.campaigns.approved_variants
.resolve_variant_for_delivery`` (REUSABLE/STALE/MISSING), and
``did.campaigns.message_content_policy.simulate_message_content_dependency``
(per-trigger MESSAGE_CONTENT warning). Zero Discord mutation: every
authorization/permission fact comes from the caller-supplied checker's own
read-only methods (the exact same contract ``resolve_target`` already
has); this module never calls a repository write method or a Discord API.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from did.campaigns.approved_variants import VariantOutcome, resolve_variant_for_delivery
from did.campaigns.message_content_policy import (
    MessageContentCapabilityChecker,
    MessageContentSimulationWarning,
    simulate_message_content_dependency,
)
from did.campaigns.target_resolution import (
    BlockReason,
    ResolvedDestination,
    TargetAuthorizationChecker,
    TranslationGroupTopologySnapshot,
    resolve_target,
)
from did.domain.campaigns import ApprovedVariant, CampaignTarget, CampaignTrigger, MessageCampaign


class DestinationTranslationState(StrEnum):
    #: No translation involved -- the source-language destination.
    SOURCE = "SOURCE"
    #: A matching approved variant exists and would be reused as-is.
    REUSABLE_APPROVED = "REUSABLE_APPROVED"
    #: An approved variant exists but the source has changed since -- would
    #: require a fresh translation, never silently reused.
    STALE_APPROVED_WOULD_RETRANSLATE = "STALE_APPROVED_WOULD_RETRANSLATE"
    #: No approved variant exists yet -- would translate fresh.
    MISSING_WOULD_TRANSLATE = "MISSING_WOULD_TRANSLATE"
    #: A translation is required but no provider is currently configured --
    #: this destination would be blocked at fan-out time, not silently sent
    #: untranslated.
    MISSING_NO_PROVIDER_CONFIGURED = "MISSING_NO_PROVIDER_CONFIGURED"


@dataclass(frozen=True, slots=True)
class DestinationSimulation:
    guild_id: int
    discord_channel_id: int
    language_profile_id: UUID | None
    #: Target reachability ONLY -- Guild/channel authorization and bot-send
    #: permission (exactly what did.campaigns.target_resolution.resolve_target
    #: itself proves). Deliberately narrower than "would fan-out actually
    #: send here": a destination can be `ready=True` while its content
    #: cannot currently be produced (see `translation_state`
    #: MISSING_NO_PROVIDER_CONFIGURED) -- external review flagged that a
    #: consumer conflating the two into one overloaded flag could show a
    #: destination as "will send" when it would actually be blocked at
    #: fan-out time. Use `delivery_executable` for the single canonical
    #: "will this destination actually get a delivery right now" answer.
    ready: bool
    blocked_reason: BlockReason | None
    translation_state: DestinationTranslationState
    #: The one flag a UI/API consumer should render a destination's overall
    #: status from: True only when the target is reachable (`ready`) AND
    #: its content can currently be produced (`translation_state` is not
    #: MISSING_NO_PROVIDER_CONFIGURED). Exactly mirrors whether this
    #: destination is counted in `CampaignSimulationReport
    #: .estimated_delivery_count`.
    delivery_executable: bool


@dataclass(frozen=True, slots=True)
class CampaignSimulationReport:
    destinations: tuple[DestinationSimulation, ...]
    total_destinations: int
    ready_destinations: int
    blocked_destinations: int
    #: Exactly the number of deliveries fan-out would create if run right
    #: now -- one per ready destination whose translation state is not
    #: MISSING_NO_PROVIDER_CONFIGURED (that state is itself counted as
    #: blocked for this estimate, even though target_resolution considers
    #: the destination "ready" -- the two checks are independent: resolve_
    #: target only proves the Guild/channel is reachable, this module is
    #: what additionally proves content can actually be produced for it).
    estimated_delivery_count: int
    blockers: dict[str, int] = field(default_factory=dict)
    message_content_warnings: tuple[MessageContentSimulationWarning, ...] = field(
        default_factory=tuple
    )


async def simulate_campaign(
    *,
    campaign: MessageCampaign,
    targets: Sequence[CampaignTarget],
    authorization: TargetAuthorizationChecker,
    topology_by_target: dict[UUID, TranslationGroupTopologySnapshot | None],
    approved_variants: dict[str, ApprovedVariant],
    language_profile_codes: dict[UUID, str],
    translation_provider_available: bool,
    triggers: Sequence[CampaignTrigger] = (),
    message_content_checker: MessageContentCapabilityChecker | None = None,
    message_content_guild_id: int | None = None,
) -> CampaignSimulationReport:
    """The complete, non-mutating preview. ``triggers``/
    ``message_content_checker``/``message_content_guild_id`` are optional --
    a purely schedule-driven campaign has no triggers to warn about and may
    omit them entirely."""
    destinations: list[DestinationSimulation] = []
    blockers: dict[str, int] = {}
    estimated_deliveries = 0

    for target in targets:
        resolved = await resolve_target(
            target,
            owner_discord_user_id=campaign.owner_discord_user_id,
            authorization=authorization,
            topology=topology_by_target.get(target.id),
        )
        for dest in resolved:
            translation_state = _translation_state(
                campaign,
                dest,
                approved_variants=approved_variants,
                language_profile_codes=language_profile_codes,
                translation_provider_available=translation_provider_available,
            )
            delivery_executable = (
                dest.is_ready
                and translation_state
                is not DestinationTranslationState.MISSING_NO_PROVIDER_CONFIGURED
            )
            destinations.append(
                DestinationSimulation(
                    guild_id=dest.guild_id,
                    discord_channel_id=dest.discord_channel_id,
                    language_profile_id=dest.language_profile_id,
                    ready=dest.is_ready,
                    blocked_reason=dest.blocked_reason,
                    translation_state=translation_state,
                    delivery_executable=delivery_executable,
                )
            )
            if not dest.is_ready:
                assert dest.blocked_reason is not None
                blockers[dest.blocked_reason.value] = blockers.get(dest.blocked_reason.value, 0) + 1
            elif translation_state is DestinationTranslationState.MISSING_NO_PROVIDER_CONFIGURED:
                blockers["TRANSLATION_PROVIDER_UNAVAILABLE"] = (
                    blockers.get("TRANSLATION_PROVIDER_UNAVAILABLE", 0) + 1
                )
            else:
                estimated_deliveries += 1

    message_content_warnings: list[MessageContentSimulationWarning] = []
    if message_content_checker is not None and message_content_guild_id is not None:
        for trigger in triggers:
            warning = await simulate_message_content_dependency(
                trigger, guild_id=message_content_guild_id, checker=message_content_checker
            )
            if warning is not None:
                message_content_warnings.append(warning)

    ready_count = sum(1 for d in destinations if d.ready)
    return CampaignSimulationReport(
        destinations=tuple(destinations),
        total_destinations=len(destinations),
        ready_destinations=ready_count,
        blocked_destinations=len(destinations) - ready_count,
        estimated_delivery_count=estimated_deliveries,
        blockers=blockers,
        message_content_warnings=tuple(message_content_warnings),
    )


def _translation_state(
    campaign: MessageCampaign,
    dest: ResolvedDestination,
    *,
    approved_variants: dict[str, ApprovedVariant],
    language_profile_codes: dict[UUID, str],
    translation_provider_available: bool,
) -> DestinationTranslationState:
    if dest.language_profile_id is None:
        return DestinationTranslationState.SOURCE
    target_language_code = language_profile_codes.get(dest.language_profile_id)
    if target_language_code is None:
        return DestinationTranslationState.MISSING_NO_PROVIDER_CONFIGURED
    resolution = resolve_variant_for_delivery(campaign, target_language_code, approved_variants)
    if resolution.outcome is VariantOutcome.REUSABLE:
        return DestinationTranslationState.REUSABLE_APPROVED
    if not translation_provider_available:
        return DestinationTranslationState.MISSING_NO_PROVIDER_CONFIGURED
    if resolution.outcome is VariantOutcome.STALE:
        return DestinationTranslationState.STALE_APPROVED_WOULD_RETRANSLATE
    return DestinationTranslationState.MISSING_WOULD_TRANSLATE
