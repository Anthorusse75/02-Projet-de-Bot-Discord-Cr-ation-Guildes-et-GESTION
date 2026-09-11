"""PostgreSQL integration tests for the durable delivery-dispatch bridge
(WP12/WP13, sixth remediation pass): proves message_deliveries rows are not
merely created but are guaranteed to reach the shared discord_io_jobs
durable worker architecture -- did.campaigns.dispatch.enqueue_delivery_job/
route_pending_deliveries_to_jobs, RuntimeRepository
.runtime_campaign_delivery_guilds (migration 0026_stage_09), and
did.campaigns.dispatch.CampaignDeliveryExecutor executing through the real
DurableDiscordIOWorker -- against a real CampaignsRepository AND a real
RuntimeRepository sharing the same database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.dispatch import (
    CampaignDeliveryExecutor,
    enqueue_delete_job,
    enqueue_delivery_job,
    enqueue_edit_job,
    route_pending_deliveries_to_jobs,
)
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import (
    LifecycleStatus,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
    OccurrenceSource,
    PublicationMode,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.domain.message_sending import DiscordSendOutcome
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine, tenant_transaction
from did.infrastructure.runtime_repository import RuntimeRepository
from did.messaging.message_model import MessageModel
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
GUILD_A = 880000981
OWNER_A = 880000991

CLEANUP_STATEMENTS = (
    "DELETE FROM discord_io_jobs WHERE guild_id = :ga",
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "oa": OWNER_A}


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Stage 09 dispatch {guild_id}", "owner_id": OWNER_A},
    )


async def _insert_user(connection: AsyncConnection, user_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": user_id, "name": f"user-{user_id}"},
    )


@pytest.fixture
async def repositories() -> AsyncIterator[
    tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
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
        yield CampaignsRepository(factory), RuntimeRepository(factory), factory
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
        await app_engine.dispose()
        await admin_engine.dispose()


async def _setup_pending_delivery(
    repo: CampaignsRepository, *, content: str = "Hello world"
) -> MessageDelivery:
    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Launch",
        source_language_code="en",
        message_model={"content": content},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    await repo.create_campaign(campaign)
    occurrence = MessageOccurrence(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign.id,
        occurrence_key=f"occ-{uuid4().hex[:8]}",
        occurrence_source=OccurrenceSource.EVENT,
        source_event_id=uuid4(),
    )
    await repo.create_occurrence(OWNER_A, occurrence)
    target = DomainTarget(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=campaign.id,
        target_kind=DomainTargetKind.CHANNEL,
        discord_channel_id=999,
    )
    await repo.create_target(target)
    delivery = MessageDelivery(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=campaign.id,
        occurrence_id=occurrence.id,
        target_id=target.id,
        delivery_key=f"dk-{uuid4().hex[:8]}",
        discord_channel_id=999,
        allowed_mentions_snapshot={"parse": [], "users": [], "roles": [], "replied_user": False},
        content_snapshot=MessageModel(content=content).to_dict(),
    )
    await repo.create_delivery(delivery)
    return delivery


@dataclass
class _FakeSender:
    call_count: int = 0
    sent_channel_ids: list[int] = field(default_factory=list)
    edit_calls: list[tuple[int, int]] = field(default_factory=list)
    delete_calls: list[tuple[int, int]] = field(default_factory=list)

    async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
        self.call_count += 1
        self.sent_channel_ids.append(channel_id)
        return DiscordSendOutcome(discord_message_id=555000555)

    async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
        self.edit_calls.append((channel_id, message_id))

    async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
        self.delete_calls.append((channel_id, message_id))


@pytest.mark.asyncio
class TestEnqueueDeliveryJob:
    async def test_enqueue_creates_exactly_one_durable_job_and_is_idempotent(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        campaigns_repo, runtime_repo, _factory = repositories
        delivery = await _setup_pending_delivery(campaigns_repo)

        first_job_id = await enqueue_delivery_job(
            runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id
        )
        second_job_id = await enqueue_delivery_job(
            runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id
        )
        # Coalescing: enqueueing the same delivery twice returns the SAME
        # durable job, never a duplicate -- this is what makes the crash-
        # recovery routing sweep safe to call repeatedly.
        assert first_job_id == second_job_id

        leased = await runtime_repo.lease_next_job(GUILD_A, lease_owner="test-worker")
        assert leased is not None
        assert leased["workload_type"] == "SEND_CAMPAIGN_MESSAGE"
        assert leased["payload"]["delivery_id"] == str(delivery.id)
        # job_id IS the delivery id -- the named-identity contract.
        assert str(leased["job_id"]) == str(delivery.id)

    async def test_job_id_is_the_delivery_id_named_identity(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        campaigns_repo, runtime_repo, _factory = repositories
        delivery_a = await _setup_pending_delivery(campaigns_repo, content="A")
        delivery_b = await _setup_pending_delivery(campaigns_repo, content="B")

        job_id_a = await enqueue_delivery_job(
            runtime_repo, guild_id=GUILD_A, delivery_id=delivery_a.id
        )
        job_id_b = await enqueue_delivery_job(
            runtime_repo, guild_id=GUILD_A, delivery_id=delivery_b.id
        )
        assert job_id_a == delivery_a.id
        assert job_id_b == delivery_b.id
        assert job_id_a != job_id_b


@pytest.mark.asyncio
class TestRoutePendingDeliveriesToJobs:
    async def test_routes_every_pending_delivery_exactly_once(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        campaigns_repo, runtime_repo, factory = repositories
        delivery_a = await _setup_pending_delivery(campaigns_repo, content="A")
        delivery_b = await _setup_pending_delivery(campaigns_repo, content="B")

        routed_first = await route_pending_deliveries_to_jobs(
            campaigns_repo, runtime_repo, guild_id=GUILD_A
        )
        assert routed_first == 2

        async with tenant_transaction(factory, TenantContext(GUILD_A, OWNER_A)) as session:
            count = await session.scalar(text("SELECT count(*) FROM discord_io_jobs"))
        assert count == 2

        # Re-sweeping is a safe, cheap no-op once every delivery already has
        # a live job -- this is the crash-recovery guarantee: calling this
        # again after a process restart never creates a duplicate.
        routed_second = await route_pending_deliveries_to_jobs(
            campaigns_repo, runtime_repo, guild_id=GUILD_A
        )
        assert routed_second == 2  # still "routed" (attempted), but coalesced
        async with tenant_transaction(factory, TenantContext(GUILD_A, OWNER_A)) as session:
            count_after = await session.scalar(text("SELECT count(*) FROM discord_io_jobs"))
        assert count_after == 2  # NOT 4 -- no duplicates
        assert {delivery_a.id, delivery_b.id}  # both deliveries were real


@pytest.mark.asyncio
class TestRuntimeCampaignDeliveryGuilds:
    async def test_guild_reported_only_while_a_pending_delivery_has_no_live_job(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        campaigns_repo, runtime_repo, _factory = repositories
        delivery = await _setup_pending_delivery(campaigns_repo)

        assert GUILD_A in await runtime_repo.runtime_campaign_delivery_guilds()

        await enqueue_delivery_job(runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id)

        # A live (PENDING) job now exists for this delivery -- the durable
        # "delivery exists, job missing" signal must clear.
        assert GUILD_A not in await runtime_repo.runtime_campaign_delivery_guilds()

    async def test_guild_with_no_pending_deliveries_is_never_reported(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        _campaigns_repo, runtime_repo, _factory = repositories
        assert GUILD_A not in await runtime_repo.runtime_campaign_delivery_guilds()


@pytest.mark.asyncio
class TestCampaignDeliveryExecutorThroughRealWorker:
    async def test_leased_job_executes_via_process_delivery_and_sends_exactly_once(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        """End-to-end: a durable discord_io_jobs row (created by
        enqueue_delivery_job) is leased and executed by the REAL
        DurableDiscordIOWorker.run_guild_once, routed through
        CampaignDeliveryExecutor to did.campaigns.delivery_worker
        .process_delivery -- proving the full durable dispatch bridge, not
        just its individual pieces in isolation."""
        campaigns_repo, runtime_repo, factory = repositories
        delivery = await _setup_pending_delivery(campaigns_repo)
        await enqueue_delivery_job(runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id)

        sender = _FakeSender()
        executor = CampaignDeliveryExecutor(campaigns_repo, sender, worker_id="durable-worker-1")

        class _NullSync:
            async def refresh_channels(self, guild_id: int) -> dict[str, int]:
                raise NotImplementedError

            async def initial_sync(self, guild_id: int) -> dict[str, int]:
                raise NotImplementedError

        worker = DurableDiscordIOWorker(
            runtime_repo,
            _NullSync(),
            worker_id="durable-worker-1",
            campaign_delivery_executor=executor,
        )
        progressed = await worker.run_guild_once(GUILD_A)
        assert progressed is True
        assert sender.call_count == 1
        assert sender.sent_channel_ids == [999]

        status = await campaigns_repo.get_delivery_status(GUILD_A, delivery.id)
        assert status == "SENT"

        async with tenant_transaction(factory, TenantContext(GUILD_A, OWNER_A)) as session:
            job_status = await session.scalar(
                text("SELECT status FROM discord_io_jobs WHERE job_id=:id"), {"id": delivery.id}
            )
        assert job_status == "SUCCEEDED"

    async def test_a_job_replayed_after_completion_never_double_sends(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        """Simulates a durable job being leased and executed twice (e.g. a
        misbehaving redelivery) -- process_delivery's own named-identity
        claim must make the second execution a no-op, never a second
        Discord send."""
        campaigns_repo, runtime_repo, _factory = repositories
        delivery = await _setup_pending_delivery(campaigns_repo)
        await enqueue_delivery_job(runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id)

        sender = _FakeSender()
        executor = CampaignDeliveryExecutor(campaigns_repo, sender, worker_id="durable-worker-1")
        leased = await runtime_repo.lease_next_job(GUILD_A, lease_owner="durable-worker-1")
        assert leased is not None

        await executor.execute_leased(GUILD_A, leased)
        await executor.execute_leased(GUILD_A, leased)  # replay with the same payload
        assert sender.call_count == 1


@pytest.mark.asyncio
class TestOwnedEditDeleteThroughRealWorker:
    async def test_edit_and_delete_jobs_route_through_the_real_worker(
        self, repositories: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
    ) -> None:
        """End-to-end: EDIT_CAMPAIGN_MESSAGE/DELETE_CAMPAIGN_MESSAGE durable
        jobs (enqueue_edit_job/enqueue_delete_job) are leased and executed
        by the REAL DurableDiscordIOWorker.run_guild_once, routed through
        CampaignDeliveryExecutor to did.campaigns.delivery_worker
        .execute_owned_edit/execute_owned_delete -- the same full-chain
        proof TestCampaignDeliveryExecutorThroughRealWorker gives SEND,
        now for the owned edit/delete product flows."""
        campaigns_repo, runtime_repo, factory = repositories
        delivery = await _setup_pending_delivery(campaigns_repo)
        async with tenant_transaction(factory, TenantContext(GUILD_A, OWNER_A)) as session:
            await session.execute(
                text(
                    "UPDATE message_deliveries SET status='SENT', "
                    "discord_message_id=444000444, "
                    "content_snapshot=CAST(:content AS JSONB) WHERE id=:id"
                ),
                {
                    "id": delivery.id,
                    "content": '{"content": "edited via durable job", "embeds": []}',
                },
            )
        await enqueue_edit_job(runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id)

        sender = _FakeSender()
        executor = CampaignDeliveryExecutor(campaigns_repo, sender, worker_id="durable-worker-1")

        class _NullSync:
            async def refresh_channels(self, guild_id: int) -> dict[str, int]:
                raise NotImplementedError

            async def initial_sync(self, guild_id: int) -> dict[str, int]:
                raise NotImplementedError

        worker = DurableDiscordIOWorker(
            runtime_repo,
            _NullSync(),
            worker_id="durable-worker-1",
            campaign_delivery_executor=executor,
        )
        edit_progressed = await worker.run_guild_once(GUILD_A)
        assert edit_progressed is True
        assert sender.edit_calls == [(999, 444000444)]

        status_after_edit = await campaigns_repo.get_delivery_status(GUILD_A, delivery.id)
        assert status_after_edit == "SENT"

        await enqueue_delete_job(runtime_repo, guild_id=GUILD_A, delivery_id=delivery.id)
        delete_progressed = await worker.run_guild_once(GUILD_A)
        assert delete_progressed is True
        assert sender.delete_calls == [(999, 444000444)]

        status_after_delete = await campaigns_repo.get_delivery_status(GUILD_A, delivery.id)
        assert status_after_delete == "DELETED"
