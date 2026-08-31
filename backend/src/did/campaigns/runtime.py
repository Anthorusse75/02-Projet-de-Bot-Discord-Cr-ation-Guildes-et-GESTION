"""WP12/WP20: the real, long-lived Stage 09 campaign scheduler process --
composes ``did.campaigns.scheduler_loop.run_scheduler_tick`` (schedule
decision), ``did.campaigns.context.load_fan_out_context``/
``did.campaigns.activation.fan_out_occurrence`` (occurrence expansion), and
``did.campaigns.dispatch.route_pending_deliveries_to_jobs`` (durable
delivery-job routing) into one bounded polling loop, run alongside the
existing ``ReconcileScheduler`` in the same ``scheduler`` process (see
``did.runtime.run_process``) rather than as a second, uncoordinated process
type.

Every stage of this loop is independently idempotent (a schedule claim is
lease-fenced, an occurrence fan-out is lease-fenced and per-destination
idempotent, a delivery-job enqueue coalesces on ``UNIQUE(guild_id,
logical_key)``), so a crash between any two stages -- or a full process
restart -- never produces a duplicate send and never permanently strands
durable work; the next tick (this process or another) simply repeats
whatever the crash interrupted."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from did.campaigns.activation import FanOutOutcome, fan_out_occurrence
from did.campaigns.context import load_campaign, load_fan_out_context
from did.campaigns.scheduler_loop import run_scheduler_tick
from did.campaigns.target_resolution import TargetAuthorizationChecker
from did.domain.campaigns import CampaignSchedule, MessageOccurrence
from did.domain.translation_provider import CampaignTranslationProvider
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.logging import EventId, emit_event
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
)

logger = logging.getLogger(__name__)


class CampaignSchedulerRuntime:
    def __init__(
        self,
        *,
        campaigns_repository: CampaignsRepository,
        runtime_repository: RuntimeRepository,
        admin_factory: async_sessionmaker[Any],
        language_profiles: LanguageProfileRepository,
        translation_groups: TranslationGroupRepository,
        checker: TargetAuthorizationChecker,
        translation_provider: CampaignTranslationProvider | None,
        lease_owner: str,
        poll_interval_seconds: float = 5.0,
        schedule_limit: int = 20,
        routing_limit: int = 200,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._campaigns_repository = campaigns_repository
        self._runtime_repository = runtime_repository
        self._admin_factory = admin_factory
        self._language_profiles = language_profiles
        self._translation_groups = translation_groups
        self._checker = checker
        self._translation_provider = translation_provider
        self._lease_owner = lease_owner
        self._poll_interval_seconds = poll_interval_seconds
        self._schedule_limit = schedule_limit
        self._routing_limit = routing_limit

    async def _fan_out_for_occurrence(
        self, schedule: CampaignSchedule, occurrence: MessageOccurrence
    ) -> FanOutOutcome:
        campaign = await load_campaign(
            self._campaigns_repository,
            owner_discord_user_id=schedule.owner_discord_user_id,
            campaign_id=schedule.campaign_id,
        )
        if campaign is None:
            # The campaign was deleted between the schedule claim and this
            # expansion -- nothing to fan out; the claimed schedule's own
            # finalize (in run_scheduler_tick) still durably advances its
            # cursor so this dangling schedule is not reclaimed forever.
            return FanOutOutcome(occurrence_id=occurrence.id)
        context = await load_fan_out_context(
            campaigns_repository=self._campaigns_repository,
            admin_factory=self._admin_factory,
            language_profiles=self._language_profiles,
            translation_groups=self._translation_groups,
            campaign=campaign,
            translation_provider=self._translation_provider,
        )
        return await fan_out_occurrence(
            repository=self._campaigns_repository,
            checker=self._checker,
            campaign=campaign,
            targets=context.targets,
            occurrence=occurrence,
            lease_owner=self._lease_owner,
            topology_by_target=context.topology_by_target,
            language_profile_codes=context.language_profile_codes,
            compiled_mentions=context.compiled_mentions,
            # No durable persistence exists yet for author-defined template
            # variable definitions (REQ-MSG-018's typed semantics are fully
            # implemented; only authoring-time storage is missing) -- an
            # empty mapping is the documented, safe default: every
            # {{variable}} in message content fails safe to NON_TRANSLATABLE
            # protected text rather than being guessed or silently dropped.
            template_variable_definitions={},
            glossary_entries=context.glossary_entries,
            translate_masked_text_for_language=context.translate_masked_text_for_language,
        )

    async def tick(self, now: datetime) -> int:
        """One scheduling cycle: claim+expand due schedules, then route any
        newly-created (or previously stranded) PENDING deliveries to durable
        discord_io_jobs. Returns the number of deliveries routed this
        tick."""
        result = await run_scheduler_tick(
            repository=self._campaigns_repository,
            admin_factory=self._admin_factory,
            lease_owner=self._lease_owner,
            now=now,
            fan_out_for_occurrence=self._fan_out_for_occurrence,
            limit=self._schedule_limit,
        )
        for error in result.errors:
            emit_event(
                logger,
                logging.WARNING,
                EventId.CAMPAIGN_SCHEDULE_EVALUATION_FAILED,
                fields={"schedule_id": str(error.schedule_id), "reason": error.reason},
            )

        routed = 0
        for guild_id in await self._runtime_repository.runtime_campaign_delivery_guilds(
            limit=self._routing_limit
        ):
            routed += await self._route_deliveries(guild_id)
        return routed

    async def _route_deliveries(self, guild_id: int) -> int:
        from did.campaigns.dispatch import route_pending_deliveries_to_jobs

        return await route_pending_deliveries_to_jobs(
            self._campaigns_repository,
            self._runtime_repository,
            guild_id=guild_id,
            limit=self._routing_limit,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.tick(datetime.now(UTC))
            except Exception as exc:
                # One bad tick (a transient DB error, an unexpected
                # exception from a single campaign's context loading) must
                # never take down the whole scheduler process -- the next
                # tick simply retries whatever durable work is still due.
                emit_event(
                    logger,
                    logging.ERROR,
                    EventId.CAMPAIGN_SCHEDULER_TICK_FAILED,
                    fields={"error": str(exc)},
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                pass
