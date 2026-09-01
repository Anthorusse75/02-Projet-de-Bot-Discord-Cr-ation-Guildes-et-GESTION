"""REQ-MSG-020: MESSAGE_CONTENT dependency capability requirement,
configuration blocker and simulation warning for event triggers.

**Deliberate scope decision (Option B, not a temporary gap)**: Stage09 does
not support raw content-dependent trigger evaluation. The Campaign Engine
never requests Discord's privileged MESSAGE_CONTENT gateway intent, and no
code path anywhere in the Campaign Engine ever extracts ``content``/
``embeds``/``attachments`` from a Gateway dispatch --
``did.application.discord_runtime.gateway.normalize_gateway_dispatch``
normalizes a MESSAGE_CREATE/UPDATE/DELETE to structural identity only
(message/channel/author ids) regardless of which intents happen to be
active, and ``did.campaigns.event_transport.consume_new_events_for_guild``
always passes ``message_content_available=False`` to every trigger
evaluation for exactly this reason. This is the truthful, permanent
contract -- not "the setting is off by default", but "there is currently no
capability to turn on".

``CampaignTrigger.requires_message_content`` stays as an explicit, honest
*declared dependency* an author can still set (useful for a future Option A
pass, and for making an author's intent legible even though it cannot be
satisfied yet): declaring it always blocks trigger creation
(:func:`validate_message_content_capability`, wired into
``did.api.stage09.create_trigger``) and always shows as a blocking warning
in a campaign simulation (:func:`simulate_message_content_dependency`, wired
into ``did.api.stage09.simulate``) via
:class:`PermanentlyUnavailableMessageContentChecker` below. Time-based
(schedule-driven) campaigns are entirely independent of all of this --
this module is only ever consulted for an event-triggered
``CampaignTrigger`` that itself declares ``requires_message_content=True``.
The actual fail-closed *runtime* behavior lives in
``did.campaigns.causality.should_trigger`` (it consults
``TriggerEvaluationContext.message_content_available`` directly, since that
decision happens per-event on the hot path); this module covers the other
two moments the requirement calls out: blocking a bad configuration before
it is saved, and warning about it in a simulation/preview.

The :class:`MessageContentCapabilityChecker` protocol stays Guild-scoped
even though the current, only implementation ignores ``guild_id`` and always
reports unavailable -- so that a future Option A pass (real, restart-safe,
privacy-bounded content capture) only has to supply a new implementation,
never touch the call sites in ``did.api.stage09`` or this module's contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from did.domain.campaigns import CampaignTrigger


@runtime_checkable
class MessageContentCapabilityChecker(Protocol):
    async def is_message_content_available(self, *, guild_id: int) -> bool:
        """Fresh, execution-time check of whether the DID bot currently has
        the MESSAGE_CONTENT privileged intent enabled and active for this
        Guild -- never a cached/assumed value, mirroring
        ``did.campaigns.target_resolution.TargetAuthorizationChecker``."""
        ...


class MessageContentCapabilityBlocked(RuntimeError):
    """The trigger declares requires_message_content=True but the DID bot
    does not currently have that capability for the source Guild -- a
    configuration blocker, raised before the trigger is persisted/activated,
    never silently ignored."""

    def __init__(self, guild_id: int) -> None:
        super().__init__(
            f"trigger requires MESSAGE_CONTENT but it is not available for guild {guild_id}"
        )
        self.guild_id = guild_id


async def validate_message_content_capability(
    trigger: CampaignTrigger, *, guild_id: int, checker: MessageContentCapabilityChecker
) -> None:
    """Call before persisting/activating a trigger bound to ``guild_id``.
    A no-op for a trigger that does not declare
    ``requires_message_content`` -- time-based/content-independent triggers
    never even perform the capability check."""
    if not trigger.requires_message_content:
        return
    if not await checker.is_message_content_available(guild_id=guild_id):
        raise MessageContentCapabilityBlocked(guild_id)


@dataclass(frozen=True, slots=True)
class MessageContentSimulationWarning:
    guild_id: int
    trigger_id: str
    available: bool

    @property
    def is_blocking(self) -> bool:
        return not self.available


async def simulate_message_content_dependency(
    trigger: CampaignTrigger, *, guild_id: int, checker: MessageContentCapabilityChecker
) -> MessageContentSimulationWarning | None:
    """Preview-time counterpart to :func:`validate_message_content_capability`
    -- never raises, never mutates anything; returns None for a trigger that
    does not depend on MESSAGE_CONTENT (nothing to warn about), otherwise a
    warning record a campaign simulation surface should display regardless
    of whether the capability currently happens to be available (so an
    author can see the dependency explicitly, not just the failure case)."""
    if not trigger.requires_message_content:
        return None
    available = await checker.is_message_content_available(guild_id=guild_id)
    return MessageContentSimulationWarning(
        guild_id=guild_id, trigger_id=str(trigger.id), available=available
    )


class PermanentlyUnavailableMessageContentChecker:
    """The only concrete :class:`MessageContentCapabilityChecker` Stage09
    currently wires in production. ``guild_id`` is accepted (the protocol
    is Guild-scoped for forward compatibility -- see the module docstring)
    but deliberately never consulted: MESSAGE_CONTENT is unavailable for
    every Guild, permanently, because the Campaign Engine has no content-
    capture capability at all right now (Option B), not because of any
    per-Guild state that could ever make one Guild's answer differ from
    another's."""

    async def is_message_content_available(self, *, guild_id: int) -> bool:
        del guild_id
        return False
