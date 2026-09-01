"""PostgreSQL integration tests for
``did.campaigns.reconciliation_runtime.CampaignDeliveryReconciliationRuntime``
-- the real, long-lived process wiring for
``did.campaigns.delivery_worker.reconcile_one_stalled_delivery`` (WP20/
REQ-MSG-029). Proves the actual discovery-to-resolution chain a real
``worker`` process now drives: ``RuntimeRepository
.runtime_campaign_reconciliation_guilds`` (0030_stage_09's SECURITY DEFINER
function) finds a Guild with a genuinely stalled/ambiguous delivery, and
``CampaignDeliveryReconciliationRuntime.tick``/``run`` resolves it through
the real ``CampaignsRepository`` -- not the primitive in isolation, which
``test_stage09_delivery_worker_postgres.py`` already covers."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.delivery_worker import DeliveryWorkOutcome, process_one_pending_delivery
from did.campaigns.reconciliation_runtime import CampaignDeliveryReconciliationRuntime
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
from did.domain.message_sending import DiscordSendError, DiscordSendOutcome
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.infrastructure.runtime_repository import RuntimeRepository
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000941
GUILD_B = 880000942
OWNER_A = 880000951

CLEANUP_STATEMENTS = (
    "DELETE FROM message_deliveries WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_campaign_targets WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "gb": GUILD_B, "oa": OWNER_A}


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Reconciliation runtime {guild_id}", "owner_id": OWNER_A},
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
async def reconciliation_context() -> AsyncIterator[tuple[CampaignsRepository, RuntimeRepository]]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"),
                CLEANUP_PARAMS,
            )
            await _insert_user(connection, OWNER_A)
            await _insert_installation(connection, GUILD_A)
            await _insert_installation(connection, GUILD_B)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield CampaignsRepository(factory), RuntimeRepository(factory)
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"),
                CLEANUP_PARAMS,
            )
        await app_engine.dispose()
        await admin_engine.dispose()


async def _setup_pending_delivery(
    repo: CampaignsRepository, *, guild_id: int, content: str = "Hello world"
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
        guild_id=guild_id,
        campaign_id=campaign.id,
        target_kind=DomainTargetKind.CHANNEL,
        discord_channel_id=999,
    )
    await repo.create_target(target)
    delivery = MessageDelivery(
        id=uuid4(),
        guild_id=guild_id,
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
    """Controllable in-memory DiscordMessageSender double, same shape as
    test_stage09_delivery_worker_postgres.py's."""

    mode: str = "success"  # success | discord_error | ambiguous
    sent_messages: list[tuple[int, MessageModel, str]] = field(default_factory=list)
    call_count: int = 0
    next_message_id: int = 222000222

    async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
        self.call_count += 1
        self.sent_messages.append((channel_id, message, nonce))
        if self.mode == "discord_error":
            raise DiscordSendError("403 Forbidden")
        if self.mode == "ambiguous":
            raise TimeoutError("connection reset before response")
        message_id = self.next_message_id
        self.next_message_id += 1
        return DiscordSendOutcome(discord_message_id=message_id)

    async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
        raise NotImplementedError


@pytest.mark.asyncio
class TestRuntimeCampaignReconciliationGuildsDiscovery:
    async def test_a_guild_with_only_a_pending_delivery_is_not_discovered(
        self, reconciliation_context: tuple[CampaignsRepository, RuntimeRepository]
    ) -> None:
        campaigns_repo, runtime_repo = reconciliation_context
        await _setup_pending_delivery(campaigns_repo, guild_id=GUILD_A)
        assert GUILD_A not in await runtime_repo.runtime_campaign_reconciliation_guilds()

    async def test_a_guild_with_an_unknown_delivery_is_discovered(
        self, reconciliation_context: tuple[CampaignsRepository, RuntimeRepository]
    ) -> None:
        campaigns_repo, runtime_repo = reconciliation_context
        await _setup_pending_delivery(campaigns_repo, guild_id=GUILD_A)
        sender = _FakeSender(mode="ambiguous")
        result = await process_one_pending_delivery(
            repository=campaigns_repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME
        assert GUILD_A in await runtime_repo.runtime_campaign_reconciliation_guilds()


@pytest.mark.asyncio
class TestCampaignDeliveryReconciliationRuntime:
    async def test_tick_resolves_the_unknown_delivery_and_the_guild_drops_out(
        self, reconciliation_context: tuple[CampaignsRepository, RuntimeRepository]
    ) -> None:
        campaigns_repo, runtime_repo = reconciliation_context
        await _setup_pending_delivery(campaigns_repo, guild_id=GUILD_A)
        ambiguous_sender = _FakeSender(mode="ambiguous")
        first = await process_one_pending_delivery(
            repository=campaigns_repo,
            sender=ambiguous_sender,
            guild_id=GUILD_A,
            lease_owner="worker-1",
        )
        assert first.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME

        recovering_sender = _FakeSender(mode="success")
        runtime = CampaignDeliveryReconciliationRuntime(
            campaigns_repository=campaigns_repo,
            runtime_repository=runtime_repo,
            sender=recovering_sender,
            lease_owner="reconciler-1",
            poll_interval_seconds=1000.0,
        )
        resolved = await runtime.tick(datetime.now(UTC))
        assert resolved == 1
        assert recovering_sender.call_count == 1
        assert recovering_sender.sent_messages[0][2] == ambiguous_sender.sent_messages[0][2]

        # The Guild has nothing left to reconcile -- it drops out of
        # discovery, and a second tick finds nothing to do.
        assert GUILD_A not in await runtime_repo.runtime_campaign_reconciliation_guilds()
        assert await runtime.tick(datetime.now(UTC)) == 0

    async def test_multiple_guilds_are_each_reconciled_in_one_tick(
        self, reconciliation_context: tuple[CampaignsRepository, RuntimeRepository]
    ) -> None:
        campaigns_repo, runtime_repo = reconciliation_context
        for guild_id in (GUILD_A, GUILD_B):
            await _setup_pending_delivery(campaigns_repo, guild_id=guild_id)
            ambiguous_sender = _FakeSender(mode="ambiguous")
            outcome = await process_one_pending_delivery(
                repository=campaigns_repo,
                sender=ambiguous_sender,
                guild_id=guild_id,
                lease_owner=f"worker-{guild_id}",
            )
            assert outcome.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME

        runtime = CampaignDeliveryReconciliationRuntime(
            campaigns_repository=campaigns_repo,
            runtime_repository=runtime_repo,
            sender=_FakeSender(mode="success"),
            lease_owner="reconciler-1",
            poll_interval_seconds=1000.0,
        )
        resolved = await runtime.tick(datetime.now(UTC))
        assert resolved == 2
        remaining = await runtime_repo.runtime_campaign_reconciliation_guilds()
        assert GUILD_A not in remaining
        assert GUILD_B not in remaining

    async def test_run_stops_cleanly_on_stop_event_after_reconciling(
        self, reconciliation_context: tuple[CampaignsRepository, RuntimeRepository]
    ) -> None:
        """Proves the actual long-lived run() loop (not just tick()) drives
        reconciliation to completion and then stops cleanly -- the real
        entry point the worker process invokes."""
        campaigns_repo, runtime_repo = reconciliation_context
        await _setup_pending_delivery(campaigns_repo, guild_id=GUILD_A)
        ambiguous_sender = _FakeSender(mode="ambiguous")
        first = await process_one_pending_delivery(
            repository=campaigns_repo,
            sender=ambiguous_sender,
            guild_id=GUILD_A,
            lease_owner="worker-1",
        )
        assert first.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME

        recovering_sender = _FakeSender(mode="success")
        runtime = CampaignDeliveryReconciliationRuntime(
            campaigns_repository=campaigns_repo,
            runtime_repository=runtime_repo,
            sender=recovering_sender,
            lease_owner="reconciler-1",
            poll_interval_seconds=0.05,
        )
        stop_event = asyncio.Event()

        async def _stop_after_first_tick() -> None:
            # Polling real database state, not another asyncio task -- there
            # is no Event to wait on instead.
            while GUILD_A in await runtime_repo.runtime_campaign_reconciliation_guilds():  # noqa: ASYNC110
                await asyncio.sleep(0.01)
            stop_event.set()

        stopper = asyncio.create_task(_stop_after_first_tick())
        run_task = asyncio.create_task(runtime.run(stop_event))
        await asyncio.wait_for(asyncio.gather(run_task, stopper), timeout=10)
        assert recovering_sender.call_count == 1
