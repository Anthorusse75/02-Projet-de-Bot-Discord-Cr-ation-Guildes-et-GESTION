"""Discord message send/edit/delete port (WP6).

Deliberately NOT folded into Stage 05's ``MutableDiscordPort``/DSG pipeline:
that pipeline diffs a *desired structural state* (does this channel/role
exist with these properties) against Discord, which has no natural meaning
for "send a new message" -- there is no prior state to diff against, it is
an imperative side-effecting action. What *is* reused from Stage 05 is the
shape of the guarantee: durable claim via the existing ``discord_io_jobs``
lease/governor machinery (a new ``workload_type``, see
``docs/90_handoffs/STAGE_09_HANDOFF.md``), and the same
crash-after-send-before-commit problem, solved here with the delivery's
stored ``discord_nonce`` instead of a DSG ``recover()`` hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from did.messaging.allowed_mentions import CompiledAllowedMentions
from did.messaging.edit_payload import EditPayload
from did.messaging.message_model import MessageModel


class DiscordSendError(Exception):
    """Raised only when the outcome is definitively known to have failed
    (e.g. 403/404) -- a timeout/connection-reset must never raise this;
    callers treat any non-DiscordSendError exception as UNKNOWN_OUTCOME."""


@dataclass(frozen=True, slots=True)
class DiscordSendOutcome:
    discord_message_id: int


@runtime_checkable
class DiscordMessageSender(Protocol):
    async def send(
        self,
        *,
        channel_id: int,
        message: MessageModel,
        allowed_mentions: CompiledAllowedMentions,
        nonce: str,
    ) -> DiscordSendOutcome:
        """Every call must pass the same ``nonce`` again on an
        UNKNOWN_OUTCOME retry (see ``did.campaigns.delivery_reconciliation``)
        -- Discord's documented enforce_nonce dedup contract (always active
        here: discord.py sets ``enforce_nonce=True`` automatically whenever
        ``nonce`` is supplied) collapses a same-nonce/same-content resend
        back to the original message instead of creating a duplicate."""
        ...

    async def edit(self, *, channel_id: int, message_id: int, payload: EditPayload) -> None: ...

    async def delete(self, *, channel_id: int, message_id: int) -> None: ...
