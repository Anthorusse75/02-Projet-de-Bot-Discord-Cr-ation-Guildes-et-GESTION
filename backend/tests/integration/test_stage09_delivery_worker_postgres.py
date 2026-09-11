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
    process_delivery,
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
from did.infrastructure.discord_message_sender import DiscordPyMessageSender
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


@pytest.mark.asyncio
class TestProcessDeliveryNamedIdentity:
    """External-review finding (fourth remediation pass): a durable
    governor job names ONE delivery_id. It must only ever be able to claim
    and process that exact row -- never "whatever is next pending" in the
    Guild, which is what process_one_pending_delivery does and which a
    delayed/replayed/stale job could otherwise use to steal a different
    delivery. process_delivery (backed by CampaignsRepository.claim_delivery)
    is the fix."""

    async def test_job_a_sends_only_a(self, campaigns_context: CampaignsRepository) -> None:
        repo = campaigns_context
        delivery_a = await _setup_pending_delivery(repo, content="Content A")
        delivery_b = await _setup_pending_delivery(repo, content="Content B")
        sender = _FakeSender(mode="success")

        result = await process_delivery(
            repository=repo,
            sender=sender,
            guild_id=GUILD_A,
            delivery_id=delivery_a.id,
            lease_owner="worker-1",
        )
        assert result.outcome is DeliveryWorkOutcome.SENT
        assert result.delivery_id == delivery_a.id
        assert sender.call_count == 1
        assert sender.sent_messages[0][1].content == "Content A"
        assert await repo.get_delivery_status(GUILD_A, delivery_b.id) == "PENDING"

    async def test_job_b_sends_only_b(self, campaigns_context: CampaignsRepository) -> None:
        repo = campaigns_context
        delivery_a = await _setup_pending_delivery(repo, content="Content A")
        delivery_b = await _setup_pending_delivery(repo, content="Content B")
        sender = _FakeSender(mode="success")

        result = await process_delivery(
            repository=repo,
            sender=sender,
            guild_id=GUILD_A,
            delivery_id=delivery_b.id,
            lease_owner="worker-1",
        )
        assert result.outcome is DeliveryWorkOutcome.SENT
        assert result.delivery_id == delivery_b.id
        assert sender.sent_messages[0][1].content == "Content B"
        assert await repo.get_delivery_status(GUILD_A, delivery_a.id) == "PENDING"

    async def test_replayed_job_a_after_a_is_sent_does_not_send_b(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery_a = await _setup_pending_delivery(repo, content="Content A")
        delivery_b = await _setup_pending_delivery(repo, content="Content B")
        sender = _FakeSender(mode="success")

        first = await process_delivery(
            repository=repo,
            sender=sender,
            guild_id=GUILD_A,
            delivery_id=delivery_a.id,
            lease_owner="worker-1",
        )
        assert first.outcome is DeliveryWorkOutcome.SENT
        assert sender.call_count == 1

        # A replayed/duplicate dispatch of the SAME job (same delivery_id)
        # must be an idempotent no-op -- it must never fall through to
        # claiming B, which is still genuinely PENDING and available.
        replay = await process_delivery(
            repository=repo,
            sender=sender,
            guild_id=GUILD_A,
            delivery_id=delivery_a.id,
            lease_owner="worker-2",
        )
        assert replay.outcome is DeliveryWorkOutcome.ALREADY_RESOLVED
        assert sender.call_count == 1  # no second send of A, and B untouched
        assert await repo.get_delivery_status(GUILD_A, delivery_b.id) == "PENDING"

    async def test_stale_job_a_cannot_steal_b_even_while_a_is_still_sending(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """A's job is claimed (SENDING) but not yet finalized; a stale/
        duplicate dispatch of A's own job must not silently succeed against
        B instead -- it must report LEASE_LOST for A specifically (its own
        lease is already held), never touch B."""
        repo = campaigns_context
        delivery_a = await _setup_pending_delivery(repo, content="Content A")
        delivery_b = await _setup_pending_delivery(repo, content="Content B")

        [claimed_a] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")
        assert claimed_a["id"] == delivery_a.id
        await repo.mark_delivery_sending(
            claimed_a["id"],
            GUILD_A,
            claimed_a["lease_token"],
            now=datetime.now(UTC),
            discord_nonce="n1",
        )

        stale_replay = await process_delivery(
            repository=repo,
            sender=_FakeSender(mode="success"),
            guild_id=GUILD_A,
            delivery_id=delivery_a.id,
            lease_owner="worker-2",
        )
        assert stale_replay.outcome is DeliveryWorkOutcome.ALREADY_RESOLVED
        assert await repo.get_delivery_status(GUILD_A, delivery_b.id) == "PENDING"

    async def test_concurrent_jobs_a_and_b_each_send_exactly_once(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery_a = await _setup_pending_delivery(repo, content="Content A")
        delivery_b = await _setup_pending_delivery(repo, content="Content B")
        sender = _FakeSender(mode="success")

        import asyncio

        result_a, result_b = await asyncio.gather(
            process_delivery(
                repository=repo,
                sender=sender,
                guild_id=GUILD_A,
                delivery_id=delivery_a.id,
                lease_owner="worker-1",
            ),
            process_delivery(
                repository=repo,
                sender=sender,
                guild_id=GUILD_A,
                delivery_id=delivery_b.id,
                lease_owner="worker-2",
            ),
        )
        assert result_a.outcome is DeliveryWorkOutcome.SENT
        assert result_b.outcome is DeliveryWorkOutcome.SENT
        assert sender.call_count == 2
        sent_contents = {m.content for _, m, _ in sender.sent_messages}
        assert sent_contents == {"Content A", "Content B"}

    async def test_unknown_delivery_id_is_already_resolved_not_an_error(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        result = await process_delivery(
            repository=repo,
            sender=_FakeSender(),
            guild_id=GUILD_A,
            delivery_id=uuid4(),
            lease_owner="worker-1",
        )
        assert result.outcome is DeliveryWorkOutcome.ALREADY_RESOLVED


@pytest.mark.asyncio
class TestFinalizationFencingResultHonored:
    """External-review finding (fourth remediation pass):
    _send_and_finalize must check the bool finalize_delivery() returns
    rather than assuming its own fenced write always commits."""

    async def test_lost_fencing_after_a_successful_send_reports_stale_not_sent(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Simulates the exact race the review names: a stalled-SENDING
        reconciler steals the row's lease WHILE the original worker's send
        call is in flight (before it can finalize). The original worker's
        Discord call still genuinely succeeds -- but its finalize must fail
        (wrong token) and it must report STALE_OUTCOME, never SENT, and
        must never invent a fresh nonce."""
        repo = campaigns_context
        await _setup_pending_delivery(repo, content="Race content")

        @dataclass
        class _RacingSender:
            repo: CampaignsRepository
            call_count: int = 0
            seen_nonce: str | None = None

            async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
                self.call_count += 1
                self.seen_nonce = nonce
                # Simulate a reconciler stealing this same row's lease
                # WHILE this send is still in flight, well past the stall
                # threshold from this call's perspective.
                await self.repo.claim_stalled_sending_for_reconciliation(
                    GUILD_A,
                    now=datetime.now(UTC) + timedelta(seconds=200),
                    lease_owner="reconciler-mid-flight",
                    stall_after_seconds=1.0,
                )
                return DiscordSendOutcome(discord_message_id=999888777)

            async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
                raise NotImplementedError

            async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
                raise NotImplementedError

        sender = _RacingSender(repo=repo)
        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-original"
        )
        assert result.outcome is DeliveryWorkOutcome.STALE_OUTCOME
        assert result.discord_message_id == 999888777
        assert sender.call_count == 1  # exactly one real Discord call was made

    async def test_lost_fencing_on_ambiguous_outcome_reports_stale_not_unknown(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)

        @dataclass
        class _RacingAmbiguousSender:
            repo: CampaignsRepository

            async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
                await self.repo.claim_stalled_sending_for_reconciliation(
                    GUILD_A,
                    now=datetime.now(UTC) + timedelta(seconds=200),
                    lease_owner="reconciler-mid-flight",
                    stall_after_seconds=1.0,
                )
                raise TimeoutError("connection reset before response")

            async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
                raise NotImplementedError

            async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
                raise NotImplementedError

        result = await process_one_pending_delivery(
            repository=repo,
            sender=_RacingAmbiguousSender(repo=repo),
            guild_id=GUILD_A,
            lease_owner="worker-original",
        )
        assert result.outcome is DeliveryWorkOutcome.STALE_OUTCOME

    async def test_lost_fencing_on_discord_error_reports_stale_not_failed(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)

        @dataclass
        class _RacingErrorSender:
            repo: CampaignsRepository

            async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
                await self.repo.claim_stalled_sending_for_reconciliation(
                    GUILD_A,
                    now=datetime.now(UTC) + timedelta(seconds=200),
                    lease_owner="reconciler-mid-flight",
                    stall_after_seconds=1.0,
                )
                raise DiscordSendError("403 Forbidden")

            async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
                raise NotImplementedError

            async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
                raise NotImplementedError

        result = await process_one_pending_delivery(
            repository=repo,
            sender=_RacingErrorSender(repo=repo),
            guild_id=GUILD_A,
            lease_owner="worker-original",
        )
        assert result.outcome is DeliveryWorkOutcome.STALE_OUTCOME


class _RaisingChannel:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def send(self, **kwargs: object) -> object:
        raise self._exc


class _FakeHttpResponse:
    def __init__(self, status: int, reason: str = "Error") -> None:
        self.status = status
        self.reason = reason


@pytest.mark.asyncio
class TestWorkerUsesRealAdapterExceptionClassification:
    """External-review finding (fourth remediation pass): failure injection
    must exercise the REAL DiscordPyMessageSender's exception translation,
    not only a fake sender that manually raises DiscordSendError -- proves
    the full worker+real-adapter pipeline, not just each half in isolation."""

    def _real_sender_raising(self, exc: BaseException) -> DiscordPyMessageSender:
        import discord

        client = discord.Client(intents=discord.Intents.none())
        sender = DiscordPyMessageSender(client)
        channel = _RaisingChannel(exc)

        async def _get_channel(channel_id: int) -> object:
            return channel

        sender._get_channel = _get_channel  # type: ignore[method-assign]
        return sender

    async def test_real_403_forbidden_finalizes_as_failed(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        import discord

        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = self._real_sender_raising(
            discord.Forbidden(_FakeHttpResponse(403), "missing SEND_MESSAGES")
        )

        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.FAILED

    async def test_real_5xx_server_error_finalizes_as_unknown_outcome(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        import discord

        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = self._real_sender_raising(
            discord.DiscordServerError(_FakeHttpResponse(503), "internal server error")
        )

        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME

    async def test_real_connection_reset_finalizes_as_unknown_outcome(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        await _setup_pending_delivery(repo)
        sender = self._real_sender_raising(ConnectionResetError("connection reset"))

        result = await process_one_pending_delivery(
            repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
        )
        assert result.outcome is DeliveryWorkOutcome.UNKNOWN_OUTCOME
