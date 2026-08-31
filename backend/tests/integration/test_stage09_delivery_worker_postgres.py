"""PostgreSQL integration tests for the Stage 09 delivery worker (WP13):
the real claim -> mark SENDING -> send -> finalize pipeline, and the
UNKNOWN_OUTCOME reconciliation retry path, against a real
CampaignsRepository and a fake (in-memory, controllable) DiscordMessageSender.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.delivery_worker import (
    DeliveryWorkOutcome,
    process_one_pending_delivery,
    reconcile_one_stalled_delivery,
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
from did.domain.message_sending import DiscordSendError, DiscordSendOutcome
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000921
OWNER_A = 880000931

CLEANUP_STATEMENTS = (
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
        {"guild_id": guild_id, "name": f"Stage 09 worker {guild_id}", "owner_id": OWNER_A},
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
async def campaigns_context() -> AsyncIterator[CampaignsRepository]:
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
        yield CampaignsRepository(factory)
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
    """Controllable in-memory DiscordMessageSender double."""

    mode: str = "success"  # success | discord_error | ambiguous
    sent_messages: list[tuple[int, MessageModel, str]] = field(default_factory=list)
    call_count: int = 0
    next_message_id: int = 111000111

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
class TestProcessOnePendingDelivery:
    async def test_successful_send_finalizes_as_sent(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, content="Hello there")
        sender = _FakeSender(mode="success")

        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.SENT
        assert result.discord_message_id is not None
        assert sender.call_count == 1
        assert sender.sent_messages[0][1].content == "Hello there"

        row = await repo.get_campaign(
            OWNER_A, delivery.campaign_id
        )  # sanity: campaign still readable
        assert row is not None

    async def test_discord_error_finalizes_as_failed_not_unknown(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = _FakeSender(mode="discord_error")

        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.FAILED

    async def test_ambiguous_exception_finalizes_as_unknown_outcome(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = _FakeSender(mode="ambiguous")

        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME

    async def test_nothing_pending_returns_nothing_to_do(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        sender = _FakeSender()
        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.NOTHING_TO_DO
        assert sender.call_count == 0

    async def test_same_delivery_is_never_sent_twice_by_two_racing_workers(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = _FakeSender(mode="success")

        import asyncio

        results = await asyncio.gather(
            process_one_pending_delivery(
                repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
            ),
            process_one_pending_delivery(
                repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-2"
            ),
        )
        outcomes = [r.outcome for r in results]
        assert outcomes.count(DeliveryWorkOutcome.SENT) == 1
        assert outcomes.count(DeliveryWorkOutcome.NOTHING_TO_DO) == 1
        assert sender.call_count == 1


@pytest.mark.asyncio
class TestReconcileOneStalledDelivery:
    async def test_stalled_sending_delivery_is_reconciled_with_the_same_nonce(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = _FakeSender(mode="ambiguous")

        first = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert first.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME
        original_nonce = sender.sent_messages[0][2]

        sender.mode = "success"
        far_future = datetime.now(UTC) + timedelta(seconds=200)
        result = await reconcile_one_stalled_delivery(
            repository=repo,
            sender=sender,
            guild_id=GUILD_A,
            lease_owner="reconciler-1",
            now=far_future,
        )
        assert result.outcome is DeliveryWorkOutcome.SENT
        assert sender.call_count == 2
        assert sender.sent_messages[1][2] == original_nonce  # same nonce reused, never fresh

    async def test_a_send_still_recently_in_flight_is_left_alone(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """A delivery that just entered SENDING (its worker may still be
        legitimately waiting on a slow Discord response) must not be
        reconciled -- only a delivery stuck well past
        STALLED_SENDING_THRESHOLD_SECONDS, or one already finalized to
        UNKNOWN, is eligible. Simulates the crashed-before-finalize case
        directly via the repository (bypassing the worker, which always
        sends+finalizes together) so the delivery is genuinely still
        SENDING with no UNKNOWN row backing it."""
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        [claimed] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")
        await repo.mark_delivery_sending(
            claimed["id"],
            GUILD_A,
            claimed["lease_token"],
            now=datetime.now(UTC),
            discord_nonce="n1",
        )

        result = await reconcile_one_stalled_delivery(
            repository=repo,
            sender=_FakeSender(),
            guild_id=GUILD_A,
            lease_owner="reconciler-1",
            now=datetime.now(UTC),
        )
        assert result.outcome is DeliveryWorkOutcome.NOTHING_TO_DO

    async def test_an_unknown_outcome_delivery_is_reconciled_immediately_no_stall_wait(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Once the worker itself has caught the ambiguous exception and
        finalized to UNKNOWN, there is no live worker left to protect --
        reconciliation must not additionally wait for a stall threshold."""
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = _FakeSender(mode="ambiguous")
        first = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert first.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME

        sender.mode = "success"
        result = await reconcile_one_stalled_delivery(
            repository=repo,
            sender=sender,
            guild_id=GUILD_A,
            lease_owner="reconciler-1",
            now=datetime.now(UTC),
        )
        assert result.outcome is DeliveryWorkOutcome.SENT
