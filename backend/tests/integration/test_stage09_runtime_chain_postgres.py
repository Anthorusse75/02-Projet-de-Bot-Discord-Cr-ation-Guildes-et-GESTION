"""PostgreSQL integration tests for the COMPLETE real Stage 09 runtime
chain, end to end through the actual production entrypoints -- not just
each stage's own primitive in isolation (those already have dedicated
crash-safety tests elsewhere: ``test_stage09_scheduler_loop_postgres.py``,
``test_stage09_activation_postgres.py``'s ``TestFanOutLeaseFencing``,
``test_stage09_durable_dispatch_postgres.py``,
``test_stage09_delivery_worker_postgres.py``).

What none of those files exercise is ``did.campaigns.runtime
.CampaignSchedulerRuntime.tick()`` itself -- the actual composed public
entrypoint ``did.runtime.py`` runs in the real scheduler process -- calling
the REAL ``fan_out_occurrence`` (not a fake callback) followed by the REAL
``did.worker.io.DurableDiscordIOWorker.run_guild_once`` picking up what that
tick queued. This file closes that gap: schedule due -> occurrence reserve
-> fan-out -> delivery -> durable job creation -> worker claim -> adapter
send -> ledger finalize, as one continuous chain through the exact objects
``did.runtime.py`` constructs, plus two concurrent scheduler instances
racing the same due schedule (proving the composition -- not just each
primitive alone -- is still fenced end to end).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.runtime import CampaignSchedulerRuntime
from did.domain.campaigns import (
    CampaignSchedule as DomainSchedule,
)
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import (
    LifecycleStatus,
    MessageCampaign,
    PublicationMode,
    ScheduleKind,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.domain.message_sending import DiscordSendOutcome
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine, tenant_transaction
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
)
from did.tenancy import TenantContext
from did.worker.io import DurableDiscordIOWorker

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000971
OWNER_A = 880000972
CHANNEL_A = 999

CLEANUP_STATEMENTS = (
    "DELETE FROM discord_io_jobs WHERE guild_id = :ga",
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaign_schedules WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "oa": OWNER_A}


async def _insert_user(connection: AsyncConnection, user_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": user_id, "name": f"user-{user_id}"},
    )


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Stage 09 runtime chain {guild_id}", "owner_id": OWNER_A},
    )


class _AlwaysAuthorizedChecker:
    """The full chain's authorization concern (real Stage04/08 membership
    checks) is already proven independently by
    ``test_stage09_authorization.py``/``test_stage09_logical_groups_postgres.py``
    -- this fake keeps that dimension fixed at "authorized" so this file's
    tests isolate the ONE thing nothing else proves: the composed runtime
    chain's own crash-safety and fencing."""

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        del guild_id, owner_discord_user_id
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        del guild_id, discord_channel_id
        return True


@dataclass
class _FakeSender:
    """Controllable in-memory DiscordMessageSender double (mirrors
    ``test_stage09_delivery_worker_postgres.py``'s own -- duplicated rather
    than imported since test modules do not export fixtures/doubles to each
    other in this codebase)."""

    call_count: int = 0
    sent_channel_ids: list[int] = field(default_factory=list)
    next_message_id: int = 991000111

    async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
        del message, allowed_mentions, nonce
        self.call_count += 1
        self.sent_channel_ids.append(channel_id)
        message_id = self.next_message_id
        self.next_message_id += 1
        return DiscordSendOutcome(discord_message_id=message_id)

    async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class _NullSync:
    async def refresh_channels(self, guild_id: int) -> dict[str, int]:
        raise NotImplementedError

    async def initial_sync(self, guild_id: int) -> dict[str, int]:
        raise NotImplementedError


@pytest.fixture
async def chain_context() -> AsyncIterator[
    tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=5)
    app_engine = create_database_engine(APP_URL, pool_size=5)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
            await _insert_user(connection, OWNER_A)
            await _insert_installation(connection, GUILD_A)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        yield CampaignsRepository(factory), RuntimeRepository(factory), admin_factory
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
        await app_engine.dispose()
        await admin_engine.dispose()


def _due_one_shot_campaign_with_target(
    *, campaign_id: Any = None
) -> tuple[MessageCampaign, DomainSchedule, DomainTarget]:
    campaign = MessageCampaign(
        id=campaign_id or uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"chain-{uuid4().hex[:8]}",
        name="Full chain launch",
        source_language_code="en",
        message_model={"content": "Hello from the full chain"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.ONE_SHOT_DEFERRED,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    now = datetime.now(UTC)
    schedule = DomainSchedule(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign.id,
        schedule_kind=ScheduleKind.ONE_SHOT,
        fire_at=now - timedelta(minutes=1),
        next_fire_at=now - timedelta(minutes=1),
    )
    target = DomainTarget(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=campaign.id,
        target_kind=DomainTargetKind.CHANNEL,
        discord_channel_id=CHANNEL_A,
    )
    return campaign, schedule, target


def _runtime(
    campaigns_repo: CampaignsRepository,
    runtime_repo: RuntimeRepository,
    admin_factory: async_sessionmaker[Any],
    *,
    lease_owner: str,
) -> CampaignSchedulerRuntime:
    return CampaignSchedulerRuntime(
        campaigns_repository=campaigns_repo,
        runtime_repository=runtime_repo,
        admin_factory=admin_factory,
        # Unused by these tests' CHANNEL-only targets beyond a harmless
        # empty per-Guild language-profile listing -- the admin factory
        # works fine here too (RLS-bypassing, so the Guild-scoped
        # TenantContext these repositories set internally is a no-op).
        language_profiles=LanguageProfileRepository(admin_factory),
        translation_groups=TranslationGroupRepository(admin_factory),
        checker=_AlwaysAuthorizedChecker(),
        translation_provider=None,
        lease_owner=lease_owner,
    )


@pytest.mark.asyncio
class TestFullRuntimeChain:
    async def test_tick_then_worker_completes_the_full_chain_exactly_once(
        self,
        chain_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """The exact production sequence: a due ONE_SHOT schedule ->
        CampaignSchedulerRuntime.tick() (claims the schedule, fans out the
        occurrence through the REAL fan_out_occurrence, routes the resulting
        PENDING delivery to a durable discord_io_jobs row) -> a separate,
        independently constructed DurableDiscordIOWorker.run_guild_once()
        (leases that exact job, sends through the adapter, finalizes the
        delivery). Proves the full chain -- not each stage's own primitive
        in isolation -- produces exactly one real send for one due
        occurrence."""
        campaigns_repo, runtime_repo, admin_factory = chain_context
        campaign, schedule, target = _due_one_shot_campaign_with_target()
        await campaigns_repo.create_campaign(campaign)
        await campaigns_repo.create_target(target)
        await campaigns_repo.create_schedule(schedule)

        runtime = _runtime(campaigns_repo, runtime_repo, admin_factory, lease_owner="scheduler-a")
        routed = await runtime.tick(datetime.now(UTC))
        assert routed == 1

        async with tenant_transaction(admin_factory, TenantContext(GUILD_A, OWNER_A)) as session:
            delivery_row = (
                (
                    await session.execute(
                        text("SELECT id, status FROM message_deliveries WHERE campaign_id=:cid"),
                        {"cid": campaign.id},
                    )
                )
                .mappings()
                .one()
            )
        assert delivery_row["status"] == "PENDING"
        delivery_id = delivery_row["id"]

        sender = _FakeSender()
        from did.campaigns.dispatch import CampaignDeliveryExecutor

        executor = CampaignDeliveryExecutor(campaigns_repo, sender, worker_id="worker-a")
        worker = DurableDiscordIOWorker(
            runtime_repo, _NullSync(), worker_id="worker-a", campaign_delivery_executor=executor
        )
        progressed = await worker.run_guild_once(GUILD_A)
        assert progressed is True
        assert sender.call_count == 1
        assert sender.sent_channel_ids == [CHANNEL_A]

        status = await campaigns_repo.get_delivery_status(GUILD_A, delivery_id)
        assert status == "SENT"

        # A second tick (the next real scheduler poll) must never re-claim
        # the already-consumed one-shot schedule or re-fan-out the same
        # occurrence -- no second delivery, no second job.
        routed_again = await runtime.tick(datetime.now(UTC))
        assert routed_again == 0
        async with tenant_transaction(admin_factory, TenantContext(GUILD_A, OWNER_A)) as session:
            delivery_count = (
                await session.execute(
                    text("SELECT count(*) FROM message_deliveries WHERE campaign_id=:cid"),
                    {"cid": campaign.id},
                )
            ).scalar_one()
        assert delivery_count == 1

    async def test_two_concurrent_scheduler_instances_racing_the_same_due_schedule_never_duplicate(
        self,
        chain_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """Two independently constructed CampaignSchedulerRuntime instances
        (e.g. two scheduler process replicas, or a restart racing the
        process it is replacing) tick concurrently against the SAME due
        schedule. The composed chain -- not just claim_due_schedules' own
        primitive fencing -- must still guarantee exactly one occurrence,
        one delivery, and one durable job: the mission's explicit 'no
        silent duplicate' bar applied to the real entrypoint, not a
        synthetic call to the fencing primitive alone."""
        campaigns_repo, runtime_repo, admin_factory = chain_context
        campaign, schedule, target = _due_one_shot_campaign_with_target()
        await campaigns_repo.create_campaign(campaign)
        await campaigns_repo.create_target(target)
        await campaigns_repo.create_schedule(schedule)

        runtime_a = _runtime(campaigns_repo, runtime_repo, admin_factory, lease_owner="scheduler-a")
        runtime_b = _runtime(campaigns_repo, runtime_repo, admin_factory, lease_owner="scheduler-b")

        now = datetime.now(UTC)
        results = await asyncio.gather(
            runtime_a.tick(now), runtime_b.tick(now), return_exceptions=True
        )
        for result in results:
            assert not isinstance(result, BaseException), result

        async with tenant_transaction(admin_factory, TenantContext(GUILD_A, OWNER_A)) as session:
            occurrence_count = (
                await session.execute(
                    text("SELECT count(*) FROM message_occurrences WHERE campaign_id=:cid"),
                    {"cid": campaign.id},
                )
            ).scalar_one()
            delivery_count = (
                await session.execute(
                    text("SELECT count(*) FROM message_deliveries WHERE campaign_id=:cid"),
                    {"cid": campaign.id},
                )
            ).scalar_one()
            job_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM discord_io_jobs "
                        "WHERE guild_id=:gid AND workload_type='SEND_CAMPAIGN_MESSAGE'"
                    ),
                    {"gid": GUILD_A},
                )
            ).scalar_one()
        assert occurrence_count == 1
        assert delivery_count == 1
        assert job_count == 1

    async def test_a_freshly_constructed_runtime_and_worker_recover_work_queued_by_a_dead_one(
        self,
        chain_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """Simulates a full process restart mid-chain: the scheduler
        instance that queued the durable job is discarded (as if its
        process died) and a BRAND NEW CampaignSchedulerRuntime + a brand new
        DurableDiscordIOWorker (fresh objects, no shared in-memory state)
        complete the work -- proving durability does not depend on any
        single process instance surviving between stages, only on the
        database."""
        campaigns_repo, runtime_repo, admin_factory = chain_context
        campaign, schedule, target = _due_one_shot_campaign_with_target()
        await campaigns_repo.create_campaign(campaign)
        await campaigns_repo.create_target(target)
        await campaigns_repo.create_schedule(schedule)

        dead_runtime = _runtime(
            campaigns_repo, runtime_repo, admin_factory, lease_owner="scheduler-dying"
        )
        routed = await dead_runtime.tick(datetime.now(UTC))
        assert routed == 1
        del dead_runtime  # the "process" that queued this work is gone

        # A fresh runtime instance (e.g. the replacement process) polling
        # again must be a safe no-op for the already-routed delivery -- not
        # a second occurrence/delivery/job.
        replacement_runtime = _runtime(
            campaigns_repo, runtime_repo, admin_factory, lease_owner="scheduler-replacement"
        )
        routed_again = await replacement_runtime.tick(datetime.now(UTC))
        assert routed_again == 0

        sender = _FakeSender()
        from did.campaigns.dispatch import CampaignDeliveryExecutor

        executor = CampaignDeliveryExecutor(campaigns_repo, sender, worker_id="worker-replacement")
        fresh_worker = DurableDiscordIOWorker(
            runtime_repo,
            _NullSync(),
            worker_id="worker-replacement",
            campaign_delivery_executor=executor,
        )
        progressed = await fresh_worker.run_guild_once(GUILD_A)
        assert progressed is True
        assert sender.call_count == 1

        async with tenant_transaction(admin_factory, TenantContext(GUILD_A, OWNER_A)) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT status FROM message_deliveries WHERE campaign_id=:cid"),
                        {"cid": campaign.id},
                    )
                )
                .mappings()
                .one()
            )
        assert row["status"] == "SENT"
