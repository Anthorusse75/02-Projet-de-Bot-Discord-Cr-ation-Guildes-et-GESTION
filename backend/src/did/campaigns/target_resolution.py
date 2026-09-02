"""Target resolution, execution-time authorization revalidation and
simulation/impact preview (WP4).

Every Guild a target touches is authorized independently, and creation-time
authorization is never treated as a standing permission: this module always
takes a fresh authorization check as a parameter and calls it again, even
if the same target was authorized when it was created. This module has no
database access of its own -- expansion of a TRANSLATION_GROUP target uses
whatever Stage 08 topology data the caller already loaded (its owning
service is responsible for reading current data, not a cached snapshot from
target-creation time).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from did.campaigns.logical_groups import LogicalGroupExpansion
from did.campaigns.translation_group_safety import evaluate_translation_group_safety
from did.domain.campaigns import CampaignTarget, TargetKind, TranslationPublicationMode


@runtime_checkable
class TargetAuthorizationChecker(Protocol):
    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        """Fresh, execution-time check -- e.g. delegates to the Stage 04
        PermissionEvaluator/authorization service. Never a cached value."""
        ...

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        """Whether the DID bot currently has send permission in this
        specific channel (Discord can change this at any time)."""
        ...


class BlockReason(StrEnum):
    GUILD_NOT_AUTHORIZED = "GUILD_NOT_AUTHORIZED"
    BOT_CANNOT_SEND = "BOT_CANNOT_SEND"
    TRANSLATION_GROUP_NOT_FOUND = "TRANSLATION_GROUP_NOT_FOUND"
    NO_MATCHING_LANGUAGE_VARIANTS = "NO_MATCHING_LANGUAGE_VARIANTS"
    LOGICAL_GROUP_NOT_FOUND = "LOGICAL_GROUP_NOT_FOUND"
    #: The logical group exists but currently names zero messageable
    #: channels (e.g. every resource is a ROLE, or a CATEGORY resource has
    #: no member channels right now) -- distinct from "not found" so a
    #: caller can tell "misconfigured target" from "empty group right now".
    LOGICAL_GROUP_EMPTY = "LOGICAL_GROUP_EMPTY"
    #: REQ-MSG-007/013: DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES would post
    #: destination-language messages while an external translation provider
    #: is bound to this Translation Group and might still be active -- DID
    #: cannot verify without modifying that provider whether it would
    #: re-translate DID's own posts, so fan-out is blocked rather than
    #: risking a double-translation loop. See
    #: did.campaigns.translation_group_safety.
    PROVIDER_SAFETY_MANUAL_CONFIGURATION_REQUIRED = "PROVIDER_SAFETY_MANUAL_CONFIGURATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class ResolvedDestination:
    guild_id: int
    discord_channel_id: int
    language_profile_id: UUID | None  # None = source-language / not-translated delivery
    blocked_reason: BlockReason | None = None

    @property
    def is_ready(self) -> bool:
        return self.blocked_reason is None


@dataclass(frozen=True, slots=True)
class TranslationGroupTopologySnapshot:
    """Freshly-read Stage 08 data needed to expand a TRANSLATION_GROUP
    target, supplied by the caller (this module never reads the DB)."""

    source_channel_id: int
    #: (language_profile_id, discord_channel_id) for every non-source variant.
    variants: tuple[tuple[UUID, int], ...]
    #: REQ-MSG-007/013: the REAL current
    #: translation_provider_bindings.status for this group's
    #: provider_binding_id, or None when no provider is bound at all --
    #: see did.campaigns.translation_group_safety for how this gates
    #: DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES.
    provider_binding_status: str | None = None


async def resolve_channel_target(
    target: CampaignTarget,
    *,
    owner_discord_user_id: int,
    authorization: TargetAuthorizationChecker,
) -> ResolvedDestination:
    assert target.target_kind is TargetKind.CHANNEL
    assert target.discord_channel_id is not None
    if not await authorization.is_guild_authorized(
        guild_id=target.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        return ResolvedDestination(
            guild_id=target.guild_id,
            discord_channel_id=target.discord_channel_id,
            language_profile_id=None,
            blocked_reason=BlockReason.GUILD_NOT_AUTHORIZED,
        )
    if not await authorization.bot_can_send(
        guild_id=target.guild_id, discord_channel_id=target.discord_channel_id
    ):
        return ResolvedDestination(
            guild_id=target.guild_id,
            discord_channel_id=target.discord_channel_id,
            language_profile_id=None,
            blocked_reason=BlockReason.BOT_CANNOT_SEND,
        )
    return ResolvedDestination(
        guild_id=target.guild_id,
        discord_channel_id=target.discord_channel_id,
        language_profile_id=None,
    )


async def resolve_translation_group_target(
    target: CampaignTarget,
    *,
    owner_discord_user_id: int,
    authorization: TargetAuthorizationChecker,
    topology: TranslationGroupTopologySnapshot | None,
) -> list[ResolvedDestination]:
    """WP12's publication-mode gate lives here too: SOURCE_ONLY and
    EXISTING_PROVIDER never fan out DID-translated child deliveries."""
    assert target.target_kind is TargetKind.TRANSLATION_GROUP
    mode = target.translation_publication_mode
    assert mode is not None

    if not await authorization.is_guild_authorized(
        guild_id=target.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        placeholder_channel = topology.source_channel_id if topology else 0
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=placeholder_channel,
                language_profile_id=None,
                blocked_reason=BlockReason.GUILD_NOT_AUTHORIZED,
            )
        ]
    if topology is None:
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=0,
                language_profile_id=None,
                blocked_reason=BlockReason.TRANSLATION_GROUP_NOT_FOUND,
            )
        ]

    async def _resolve_channel(
        channel_id: int, language_profile_id: UUID | None
    ) -> ResolvedDestination:
        if not await authorization.bot_can_send(
            guild_id=target.guild_id, discord_channel_id=channel_id
        ):
            return ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=channel_id,
                language_profile_id=language_profile_id,
                blocked_reason=BlockReason.BOT_CANNOT_SEND,
            )
        return ResolvedDestination(
            guild_id=target.guild_id,
            discord_channel_id=channel_id,
            language_profile_id=language_profile_id,
        )

    # SOURCE_ONLY / EXISTING_PROVIDER: DID only ever publishes to the source
    # channel -- an external provider (or nothing) handles the rest.
    source_only_modes = (
        TranslationPublicationMode.SOURCE_ONLY,
        TranslationPublicationMode.EXISTING_PROVIDER,
    )
    if mode in source_only_modes:
        return [await _resolve_channel(topology.source_channel_id, None)]

    # REQ-MSG-007/013: DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES post
    # destination-language messages themselves -- re-checked here, at
    # execution time, exactly like Guild authorization/bot-can-send, never
    # trusted as a standing decision from target-creation time (a provider
    # binding can change after a target is created).
    safety = evaluate_translation_group_safety(
        publication_mode=mode, provider_binding_status=topology.provider_binding_status
    )
    if not safety.is_safe:
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=topology.source_channel_id,
                language_profile_id=None,
                blocked_reason=BlockReason.PROVIDER_SAFETY_MANUAL_CONFIGURATION_REQUIRED,
            )
        ]

    if mode is TranslationPublicationMode.DID_TRANSLATED_FANOUT:
        destinations = [await _resolve_channel(topology.source_channel_id, None)]
        for language_profile_id, channel_id in topology.variants:
            destinations.append(await _resolve_channel(channel_id, language_profile_id))
        return destinations

    # SELECTED_LANGUAGES
    selected = set(target.selected_language_profile_ids)
    matching = [(lp, ch) for lp, ch in topology.variants if lp in selected]
    if not matching:
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=topology.source_channel_id,
                language_profile_id=None,
                blocked_reason=BlockReason.NO_MATCHING_LANGUAGE_VARIANTS,
            )
        ]
    return [await _resolve_channel(channel_id, lp) for lp, channel_id in matching]


async def resolve_logical_group_target(
    target: CampaignTarget,
    *,
    owner_discord_user_id: int,
    authorization: TargetAuthorizationChecker,
    expansion: LogicalGroupExpansion | None,
) -> list[ResolvedDestination]:
    """REQ-MSG-002: every channel a logical group currently names still
    undergoes the exact same fresh Guild-authorization/bot-can-send
    re-check as any other destination -- expansion only answers WHICH
    channels; it never implies they are reachable."""
    assert target.target_kind is TargetKind.LOGICAL_GROUP
    if not await authorization.is_guild_authorized(
        guild_id=target.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=0,
                language_profile_id=None,
                blocked_reason=BlockReason.GUILD_NOT_AUTHORIZED,
            )
        ]
    if expansion is None:
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=0,
                language_profile_id=None,
                blocked_reason=BlockReason.LOGICAL_GROUP_NOT_FOUND,
            )
        ]
    if not expansion.discord_channel_ids:
        return [
            ResolvedDestination(
                guild_id=target.guild_id,
                discord_channel_id=0,
                language_profile_id=None,
                blocked_reason=BlockReason.LOGICAL_GROUP_EMPTY,
            )
        ]

    destinations: list[ResolvedDestination] = []
    for channel_id in expansion.discord_channel_ids:
        if not await authorization.bot_can_send(
            guild_id=target.guild_id, discord_channel_id=channel_id
        ):
            destinations.append(
                ResolvedDestination(
                    guild_id=target.guild_id,
                    discord_channel_id=channel_id,
                    language_profile_id=None,
                    blocked_reason=BlockReason.BOT_CANNOT_SEND,
                )
            )
        else:
            destinations.append(
                ResolvedDestination(
                    guild_id=target.guild_id,
                    discord_channel_id=channel_id,
                    language_profile_id=None,
                )
            )
    return destinations


async def resolve_target(
    target: CampaignTarget,
    *,
    owner_discord_user_id: int,
    authorization: TargetAuthorizationChecker,
    topology: TranslationGroupTopologySnapshot | None = None,
    logical_group_expansion: LogicalGroupExpansion | None = None,
) -> list[ResolvedDestination]:
    if target.target_kind is TargetKind.CHANNEL:
        return [
            await resolve_channel_target(
                target, owner_discord_user_id=owner_discord_user_id, authorization=authorization
            )
        ]
    if target.target_kind is TargetKind.LOGICAL_GROUP:
        return await resolve_logical_group_target(
            target,
            owner_discord_user_id=owner_discord_user_id,
            authorization=authorization,
            expansion=logical_group_expansion,
        )
    return await resolve_translation_group_target(
        target,
        owner_discord_user_id=owner_discord_user_id,
        authorization=authorization,
        topology=topology,
    )


@dataclass(frozen=True, slots=True)
class CampaignSimulation:
    total_destinations: int
    ready_destinations: int
    blocked_destinations: int
    languages: tuple[UUID | None, ...]
    blockers: dict[str, int]


def summarize_simulation(destinations: Iterable[ResolvedDestination]) -> CampaignSimulation:
    """WP4: a pure, side-effect-free preview -- callers must never persist
    or send anything from this summary; it exists to answer "what would
    happen" without touching Discord or creating deliveries."""
    all_destinations = list(destinations)
    ready = [d for d in all_destinations if d.is_ready]
    blocked = [d for d in all_destinations if not d.is_ready]
    blockers: dict[str, int] = {}
    for d in blocked:
        assert d.blocked_reason is not None
        blockers[d.blocked_reason.value] = blockers.get(d.blocked_reason.value, 0) + 1
    return CampaignSimulation(
        total_destinations=len(all_destinations),
        ready_destinations=len(ready),
        blocked_destinations=len(blocked),
        languages=tuple(d.language_profile_id for d in all_destinations),
        blockers=blockers,
    )
