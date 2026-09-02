"""PostgreSQL integration tests for the owned message edit/delete product
flows (mission sections 7-8, REQ-MSG): ``CampaignsRepository
.prepare_owned_edit_for_owner``/``verify_owned_sent_delivery_for_owner``/
``get_sent_delivery_for_edit``/``mark_delivery_deleted`` and
``did.campaigns.delivery_worker.execute_owned_edit``/``execute_owned_delete``
-- the real, ledger-sourced chain a durable worker drives, never a
client-supplied channel/message id.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.delivery_worker import (
    DeliveryWorkOutcome,
    execute_owned_delete,
    execute_owned_edit,
    process_one_pending_delivery,
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
from did.infrastructure.database import create_database_engine
from did.messaging.edit_payload import EditPayload
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000961
OWNER_A = 880000971
OWNER_B = 880000972

CLEANUP_STATEMENTS = (
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id IN (:oa,:ob)",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "oa": OWNER_A, "ob": OWNER_B}


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Owned edit/delete {guild_id}", "owner_id": OWNER_A},
    )


@pytest.fixture
async def owned_context() -> AsyncIterator[CampaignsRepository]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
                    "ON CONFLICT (discord_user_id) DO NOTHING"
                ),
                {"id": OWNER_A, "name": "owner-a"},
            )
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


@dataclass
class _FakeSender:
    sent_messages: list[tuple[int, MessageModel, str]] = field(default_factory=list)
    edited: list[tuple[int, int, EditPayload]] = field(default_factory=list)
    deleted: list[tuple[int, int]] = field(default_factory=list)
    edit_calls: int = 0
    delete_calls: int = 0
    next_message_id: int = 333000333

    async def send(self, *, channel_id, message, allowed_mentions, nonce):  # type: ignore[no-untyped-def]
        self.sent_messages.append((channel_id, message, nonce))
        message_id = self.next_message_id
        self.next_message_id += 1
        return DiscordSendOutcome(discord_message_id=message_id)

    async def edit(self, *, channel_id, message_id, payload):  # type: ignore[no-untyped-def]
        self.edit_calls += 1
        self.edited.append((channel_id, message_id, payload))

    async def delete(self, *, channel_id, message_id):  # type: ignore[no-untyped-def]
        self.delete_calls += 1
        self.deleted.append((channel_id, message_id))


async def _sent_delivery(
    repo: CampaignsRepository, sender: _FakeSender, *, owner: int = OWNER_A, content: str = "Hello"
) -> MessageDelivery:
    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=owner,
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
        owner_discord_user_id=owner,
        campaign_id=campaign.id,
        occurrence_key=f"occ-{uuid4().hex[:8]}",
        occurrence_source=OccurrenceSource.EVENT,
        source_event_id=uuid4(),
    )
    await repo.create_occurrence(owner, occurrence)
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
    result = await process_one_pending_delivery(
        repository=repo, sender=sender, guild_id=GUILD_A, lease_owner="worker-1"
    )
    assert result.outcome is DeliveryWorkOutcome.SENT
    return delivery


@pytest.mark.asyncio
class TestPrepareOwnedEdit:
    async def test_ownership_and_status_are_enforced(
        self, owned_context: CampaignsRepository
    ) -> None:
        repo = owned_context
        sender = _FakeSender()
        delivery = await _sent_delivery(repo, sender)
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        try:
            # Wrong campaign_id -> None.
            assert (
                await repo.prepare_owned_edit_for_owner(
                    admin_factory,
                    OWNER_A,
                    uuid4(),
                    delivery.id,
                    message_model={"content": "new"},
                )
                is None
            )
            # Foreign owner -> None, no row persisted a foreign owner could
            # have changed.
            assert (
                await repo.prepare_owned_edit_for_owner(
                    admin_factory,
                    OWNER_B,
                    delivery.campaign_id,
                    delivery.id,
                    message_model={"content": "hijacked"},
                )
                is None
            )
            # Real owner, real campaign, SENT delivery -> succeeds and
            # durably updates content_snapshot.
            prepared = await repo.prepare_owned_edit_for_owner(
                admin_factory,
                OWNER_A,
                delivery.campaign_id,
                delivery.id,
                message_model={"content": "edited content"},
            )
            assert prepared is not None
            assert prepared["guild_id"] == GUILD_A
            fetched = await repo.get_sent_delivery_for_edit(GUILD_A, delivery.id)
            assert fetched is not None
            assert fetched["content_snapshot"]["content"] == "edited content"
            # Mention policy is never touched by an edit.
            assert fetched["allowed_mentions_snapshot"]["parse"] == []
        finally:
            await admin_engine.dispose()

    async def test_non_sent_delivery_is_not_editable(
        self, owned_context: CampaignsRepository
    ) -> None:
        repo = owned_context
        sender = _FakeSender()
        delivery = await _sent_delivery(repo, sender)
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        try:
            await repo.mark_delivery_deleted(delivery.id, GUILD_A)
            assert (
                await repo.prepare_owned_edit_for_owner(
                    admin_factory,
                    OWNER_A,
                    delivery.campaign_id,
                    delivery.id,
                    message_model={"content": "too late"},
                )
                is None
            )
        finally:
            await admin_engine.dispose()


@pytest.mark.asyncio
class TestExecuteOwnedEdit:
    async def test_edits_using_the_ledgers_own_channel_and_message_id(
        self, owned_context: CampaignsRepository
    ) -> None:
        repo = owned_context
        sender = _FakeSender()
        delivery = await _sent_delivery(repo, sender)
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        try:
            prepared = await repo.prepare_owned_edit_for_owner(
                admin_factory,
                OWNER_A,
                delivery.campaign_id,
                delivery.id,
                message_model={"content": "updated"},
            )
            assert prepared is not None
        finally:
            await admin_engine.dispose()

        ledger_row = await repo.get_sent_delivery_for_edit(GUILD_A, delivery.id)
        assert ledger_row is not None
        expected_message_id = ledger_row["discord_message_id"]

        await execute_owned_edit(
            repository=repo, sender=sender, guild_id=GUILD_A, delivery_id=delivery.id
        )
        assert sender.edit_calls == 1
        channel_id, message_id, payload = sender.edited[0]
        assert channel_id == 999
        # The message id came from the delivery's own ledger row (set by
        # the earlier SEND), never from any caller-supplied value -- this
        # test never passes a message id anywhere.
        assert message_id == expected_message_id
        assert payload.message_model.content == "updated"

    async def test_a_delivery_no_longer_sent_is_silently_skipped_not_a_failure(
        self, owned_context: CampaignsRepository
    ) -> None:
        repo = owned_context
        sender = _FakeSender()
        delivery = await _sent_delivery(repo, sender)
        await repo.mark_delivery_deleted(delivery.id, GUILD_A)
        await execute_owned_edit(
            repository=repo, sender=sender, guild_id=GUILD_A, delivery_id=delivery.id
        )
        assert sender.edit_calls == 0


@pytest.mark.asyncio
class TestExecuteOwnedDelete:
    async def test_deletes_and_transitions_to_deleted(
        self, owned_context: CampaignsRepository
    ) -> None:
        repo = owned_context
        sender = _FakeSender()
        delivery = await _sent_delivery(repo, sender)
        await execute_owned_delete(
            repository=repo, sender=sender, guild_id=GUILD_A, delivery_id=delivery.id
        )
        assert sender.delete_calls == 1
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                status = (
                    await connection.execute(
                        text("SELECT status FROM message_deliveries WHERE id=:id"),
                        {"id": delivery.id},
                    )
                ).scalar_one()
                assert status == "DELETED"
        finally:
            await admin_engine.dispose()

    async def test_replay_after_success_is_idempotent_no_second_discord_call(
        self, owned_context: CampaignsRepository
    ) -> None:
        """REQ-MSG owned delete: a job replay (e.g. at-least-once durable
        dispatch redelivering the same job) must never re-attempt the
        Discord call once the delivery has already transitioned to
        DELETED -- get_sent_delivery_for_edit no longer finds a SENT row,
        so the second execute_owned_delete call is a safe no-op."""
        repo = owned_context
        sender = _FakeSender()
        delivery = await _sent_delivery(repo, sender)
        await execute_owned_delete(
            repository=repo, sender=sender, guild_id=GUILD_A, delivery_id=delivery.id
        )
        assert sender.delete_calls == 1
        await execute_owned_delete(
            repository=repo, sender=sender, guild_id=GUILD_A, delivery_id=delivery.id
        )
        assert sender.delete_calls == 1
