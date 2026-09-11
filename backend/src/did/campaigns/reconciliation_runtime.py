"""WP20/REQ-MSG-029: the real, long-lived Stage 09 delivery-reconciliation
process -- discovers Guilds with a genuinely stalled/ambiguous
``message_deliveries`` row (0030_stage_09's ``runtime_campaign_reconciliation
_guilds`` SECURITY DEFINER function) and drives each one through
``did.campaigns.delivery_worker.reconcile_one_stalled_delivery`` on a bounded
polling loop, run alongside ``DurableDiscordIOWorker`` in the same
``worker`` process (see ``did.runtime.run_process``).

External-review finding this closes: ``reconcile_one_stalled_delivery`` and
its supporting ``decide_unknown_outcome_recovery`` decision logic were a
complete, independently-tested primitive that no real process ever called --
a delivery that reached ``SENDING``/``UNKNOWN`` and then lost its worker
(crash, lost response) could be durably correct in the database but would
never actually get resolved by anything running in production. This module
is the missing caller, not new decision logic -- it owns discovery and
looping only.

Every reconciliation attempt is independently safe to repeat (claim queries
are lease-fenced, ``decide_unknown_outcome_recovery`` always reuses the
original persisted nonce rather than minting a new one), so a crash between
any two Guilds -- or a full process restart -- never double-sends and never
permanently strands a stalled delivery; the next tick (this process or
another) simply resumes wherever the crash interrupted."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from did.campaigns.delivery_worker import DeliveryWorkOutcome, reconcile_one_stalled_delivery
from did.domain.message_sending import DiscordMessageSender
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.logging import EventId, emit_event
from did.infrastructure.runtime_repository import RuntimeRepository

logger = logging.getLogger(__name__)


class CampaignDeliveryReconciliationRuntime:
    def __init__(
        self,
        *,
        campaigns_repository: CampaignsRepository,
        runtime_repository: RuntimeRepository,
        sender: DiscordMessageSender,
        lease_owner: str,
        poll_interval_seconds: float = 5.0,
        guild_limit: int = 256,
        per_guild_attempt_limit: int = 25,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if per_guild_attempt_limit < 1:
            raise ValueError("per_guild_attempt_limit must be at least 1")
        self._campaigns_repository = campaigns_repository
        self._runtime_repository = runtime_repository
        self._sender = sender
        self._lease_owner = lease_owner
        self._poll_interval_seconds = poll_interval_seconds
        self._guild_limit = guild_limit
        self._per_guild_attempt_limit = per_guild_attempt_limit

    async def _reconcile_guild(self, guild_id: int, *, now: datetime) -> int:
        """Drains this Guild's currently-reconcilable deliveries one at a
        time (each call claims and resolves exactly one), bounded by
        ``per_guild_attempt_limit`` so a single busy Guild can never starve
        every other Guild's turn within one tick -- any remainder is simply
        picked up again next tick, same as every other durable sweep in this
        engine. Returns the number of deliveries actually reconciled
        (NOTHING_TO_DO/LEASE_LOST do not count -- nothing was resolved)."""
        resolved = 0
        for _ in range(self._per_guild_attempt_limit):
            result = await reconcile_one_stalled_delivery(
                repository=self._campaigns_repository,
                sender=self._sender,
                guild_id=guild_id,
                lease_owner=self._lease_owner,
                now=now,
            )
            if result.outcome in (
                DeliveryWorkOutcome.NOTHING_TO_DO,
                DeliveryWorkOutcome.LEASE_LOST,
            ):
                break
            resolved += 1
        return resolved

    async def tick(self, now: datetime) -> int:
        resolved = 0
        for guild_id in await self._runtime_repository.runtime_campaign_reconciliation_guilds(
            limit=self._guild_limit
        ):
            resolved += await self._reconcile_guild(guild_id, now=now)
        return resolved

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.tick(datetime.now(UTC))
            except Exception as exc:
                # One bad tick (a transient DB error, an unexpected
                # exception reconciling a single delivery) must never take
                # down the whole worker process -- the next tick simply
                # retries whatever durable work is still stalled.
                emit_event(
                    logger,
                    logging.ERROR,
                    EventId.CAMPAIGN_RECONCILIATION_TICK_FAILED,
                    fields={"error": str(exc)},
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                pass
