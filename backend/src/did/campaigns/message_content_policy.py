"""REQ-MSG-020: MESSAGE_CONTENT dependency capability requirement,
configuration blocker and simulation warning for event triggers.

The Campaign Engine never globally enables Discord's privileged
MESSAGE_CONTENT gateway intent for itself. Time-based (schedule-driven)
campaigns are entirely independent of it -- this module is only ever
consulted for an event-triggered ``CampaignTrigger`` that itself declares
``requires_message_content=True`` (``did.domain.campaigns.CampaignTrigger``).
The actual fail-closed *runtime* behavior when the intent turns out to be
unavailable lives in ``did.campaigns.causality.should_trigger`` (it consults
``TriggerEvaluationContext.message_content_available`` directly, since that
decision happens per-event on the hot path); this module covers the other
two moments the requirement calls out: blocking a bad configuration before
it is saved, and warning about it in a simulation/preview.
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
