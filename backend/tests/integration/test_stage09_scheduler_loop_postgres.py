"""PostgreSQL integration tests for the Stage 09 scheduler tick (WP12/WP13):
did.campaigns.scheduler_loop.run_scheduler_tick wires the real fenced
claim/evaluate/finalize primitives into an actual cycle, proven crash-safe
and restart-idempotent against a real CampaignsRepository.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.activation import FanOutOutcome
from did.campaigns.scheduler_loop import run_scheduler_tick
from did.domain.campaigns import (
    CampaignSchedule as DomainSchedule,
)
from did.domain.campaigns import (
    LifecycleStatus,
    MessageCampaign,
    MessageOccurrence,
    PublicationMode,
    ScheduleKind,
)
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000981
OWNER_A = 880000991

CLEANUP_STATEMENTS = (
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaign_schedules WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"oa": OWNER_A}


async def _insert_user(connection: AsyncConnection, user_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": user_id, "name": f"user-{user_id}"},
    )


@pytest.fixture
async def campaigns_context() -> AsyncIterator[CampaignsRepository]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await _insert_user(connection, OWNER_A)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield CampaignsRepository(factory)
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
        await app_engine.dispose()
        await admin_engine.dispose()


def _campaign(**overrides: object) -> MessageCampaign:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Scheduled launch",
        source_language_code="en",
        message_model={"content": "hello"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.ONE_SHOT_DEFERRED,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    fields.update(overrides)
    return MessageCampaign(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
class TestRunSchedulerTick:
    async def test_due_one_shot_schedule_fans_out_exactly_once(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        now = datetime.now(UTC)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=now - timedelta(minutes=1),
            next_fire_at=now - timedelta(minutes=1),
        )
        await repo.create_schedule(schedule)

        fanned_out_occurrences: list[MessageOccurrence] = []

        async def _fan_out(sched: DomainSchedule, occurrence: MessageOccurrence) -> FanOutOutcome:
            fanned_out_occurrences.append(occurrence)
            return FanOutOutcome(occurrence_id=occurrence.id, deliveries_created=1)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            result = await run_scheduler_tick(
                repository=repo,
                admin_factory=admin_factory,
                lease_owner="scheduler-1",
                now=now,
                fan_out_for_occurrence=_fan_out,
            )
        finally:
            await admin_engine.dispose()

        assert result.schedules_claimed == 1
        assert result.occurrences_fanned_out == 1
        assert not result.errors
        assert len(fanned_out_occurrences) == 1

        # A second tick must find nothing due -- ONE_SHOT already fired.
        admin_engine2 = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory2 = async_sessionmaker(admin_engine2, expire_on_commit=False)
            second = await run_scheduler_tick(
                repository=repo,
                admin_factory=admin_factory2,
                lease_owner="scheduler-1",
                now=now + timedelta(seconds=1),
                fan_out_for_occurrence=_fan_out,
            )
        finally:
            await admin_engine2.dispose()
        assert second.schedules_claimed == 0
        assert len(fanned_out_occurrences) == 1  # unchanged

    async def test_crash_mid_tick_leaves_cursor_unadvanced_and_is_safely_retried(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Simulates a scheduler crash: the fan-out callback raises. The
        cursor must NOT be advanced (finalize is never reached), so a
        subsequent tick (after the lease naturally expires) re-evaluates
        from the same starting point -- and because fan-out is itself
        idempotent per occurrence key, retrying is always safe."""
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        now = datetime.now(UTC)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=now - timedelta(minutes=1),
            next_fire_at=now - timedelta(minutes=1),
        )
        await repo.create_schedule(schedule)

        async def _crashing_fan_out(
            sched: DomainSchedule, occurrence: MessageOccurrence
        ) -> FanOutOutcome:
            raise RuntimeError("simulated worker crash mid fan-out")

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            first = await run_scheduler_tick(
                repository=repo,
                admin_factory=admin_factory,
                lease_owner="scheduler-1",
                now=now,
                fan_out_for_occurrence=_crashing_fan_out,
                lease_seconds=0.01,
            )
            assert first.schedules_claimed == 1
            assert len(first.errors) == 1
            await asyncio.sleep(0.05)  # let the short lease expire

            successful_calls: list[MessageOccurrence] = []

            async def _now_working_fan_out(
                sched: DomainSchedule, occurrence: MessageOccurrence
            ) -> FanOutOutcome:
                successful_calls.append(occurrence)
                return FanOutOutcome(occurrence_id=occurrence.id, deliveries_created=1)

            second = await run_scheduler_tick(
                repository=repo,
                admin_factory=admin_factory,
                lease_owner="scheduler-2",
                now=now + timedelta(seconds=1),
                fan_out_for_occurrence=_now_working_fan_out,
            )
        finally:
            await admin_engine.dispose()

        assert second.schedules_claimed == 1
        assert not second.errors
        assert len(successful_calls) == 1
        # Same deterministic occurrence_key/id both times (ONE_SHOT).
        assert successful_calls[0].occurrence_key.endswith(":one-shot")

    async def test_paused_campaign_is_never_claimed(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(lifecycle_status=LifecycleStatus.PAUSED)
        await repo.create_campaign(campaign)
        now = datetime.now(UTC)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=now - timedelta(minutes=1),
            next_fire_at=now - timedelta(minutes=1),
        )
        await repo.create_schedule(schedule)

        async def _fan_out_should_never_run(
            sched: DomainSchedule, occurrence: MessageOccurrence
        ) -> FanOutOutcome:
            raise AssertionError("fan-out must never run for a paused campaign's schedule")

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            result = await run_scheduler_tick(
                repository=repo,
                admin_factory=admin_factory,
                lease_owner="scheduler-1",
                now=now,
                fan_out_for_occurrence=_fan_out_should_never_run,
            )
        finally:
            await admin_engine.dispose()
        assert result.schedules_claimed == 0
