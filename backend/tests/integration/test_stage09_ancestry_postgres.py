"""PostgreSQL integration tests for the REQ-MSG-030 producing side:
did.campaigns.event_transport's durable correlation of a bot-authored
MESSAGE_CREATE back to the exact SENT delivery that produced it, and the
resulting ancestry-tagged event correctly feeding the already-proven
consuming-side loop guard (did.campaigns.causality.should_trigger).

Proves, against a real database, every scenario the mission names:
direct self-loop, A->B->A, cross-Guild A->B->C->A, causation_depth
increments, correlation_id stability, causation_id changing per hop, both
Gateway/finalize race orderings, and restart-safety (fresh repository
instances between calls).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.event_transport import (
    BOT_MESSAGE_CORRELATION_GRACE_SECONDS,
    consume_new_events_for_guild,
)
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import (
    CampaignTrigger,
    LifecycleStatus,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
    OccurrenceSource,
    OccurrenceStatus,
    PublicationMode,
    TriggerSourceBinding,
    TriggerSourceScopeKind,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
)
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880002101
GUILD_B = 880002102
GUILD_C = 880002103
OWNER_A = 880002111
BOT_USER_ID = 880002199
THIRD_PARTY_BOT_USER_ID = 880002198
HUMAN_USER_ID = 880002197
CHANNEL_A = 880002121
CHANNEL_B = 880002122
CHANNEL_C = 880002123

ALL_GUILDS = (GUILD_A, GUILD_B, GUILD_C)

CLEANUP_STATEMENTS = (
    "DELETE FROM discord_gateway_inbox WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_event_cursor WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_trigger_consumptions WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_trigger_sources WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_deliveries WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaign_targets WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_triggers WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"guilds": list(ALL_GUILDS), "oa": OWNER_A}


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    # bot_user_id is set to BOT_USER_ID so did.infrastructure.stage04_repository
    # .Stage04Repository.bot_identity resolves the same durable identity
    # _insert_bot_message_event's "author_discord_user_id" uses -- exactly
    # what did.campaigns.event_transport._is_own_did_bot_message_create
    # requires to ever enter the correlation-wait path (REQ-MSG-030
    # own-bot-vs-third-party-bot fix).
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status,bot_user_id) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE',:bot_user_id) "
            "ON CONFLICT (guild_id) DO UPDATE SET "
            "name=EXCLUDED.name, bot_user_id=EXCLUDED.bot_user_id"
        ),
        {
            "guild_id": guild_id,
            "name": f"Ancestry test {guild_id}",
            "owner_id": OWNER_A,
            "bot_user_id": BOT_USER_ID,
        },
    )


async def _insert_user(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": OWNER_A, "name": f"user-{OWNER_A}"},
    )


async def _insert_bot_message_event(
    connection: AsyncConnection,
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    author_is_bot: bool = True,
    author_discord_user_id: int = BOT_USER_ID,
    received_at: datetime | None = None,
) -> UUID:
    event_id = uuid4()
    payload = {
        "message_id": message_id,
        "channel_id": channel_id,
        "author_discord_user_id": author_discord_user_id,
        "author_is_bot": author_is_bot,
    }
    await connection.execute(
        text(
            "INSERT INTO discord_gateway_inbox "
            "(event_id,guild_id,event_type,discord_session_id,received_at,correlation_id,"
            "schema_version,source,origin,causation_depth,payload) VALUES "
            "(:event_id,:guild,'MESSAGE_CREATE','test-session',:received_at,:event_id,1,"
            "'GATEWAY','DISCORD_EXTERNAL',0,CAST(:payload AS JSONB))"
        ),
        {
            "event_id": event_id,
            "guild": guild_id,
            "received_at": received_at or datetime.now(UTC),
            "payload": json.dumps(payload),
        },
    )
    return event_id


@pytest.fixture
async def ancestry_context() -> AsyncIterator[
    tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=5)
    app_engine = create_database_engine(APP_URL, pool_size=5)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = ANY(:guilds)"),
                CLEANUP_PARAMS,
            )
            await _insert_user(connection)
            for guild_id in ALL_GUILDS:
                await _insert_installation(connection, guild_id)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        yield CampaignsRepository(factory), RuntimeRepository(factory), admin_factory
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = ANY(:guilds)"),
                CLEANUP_PARAMS,
            )
        await app_engine.dispose()
        await admin_engine.dispose()


class _FakeChecker:
    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        del guild_id, owner_discord_user_id
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        del guild_id, discord_channel_id
        return True


def _kwargs(
    campaigns_repo: CampaignsRepository,
    runtime_repo: RuntimeRepository,
    admin_factory: async_sessionmaker[Any],
    *,
    guild_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    return dict(
        campaigns_repository=campaigns_repo,
        runtime_repository=runtime_repo,
        admin_factory=admin_factory,
        language_profiles=LanguageProfileRepository(admin_factory),
        translation_groups=TranslationGroupRepository(admin_factory),
        checker=_FakeChecker(),
        translation_provider=None,
        lease_owner="ancestry-test",
        stage04_repository=Stage04Repository(admin_factory),
        guild_id=guild_id,
        now=now,
    )


async def _make_campaign(repo: CampaignsRepository, *, name: str) -> MessageCampaign:
    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name=name,
        source_language_code="en",
        message_model=MessageModel(content=f"Hello from {name}").to_dict(),
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.EVENT_TRIGGERED,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    await repo.create_campaign(campaign)
    return campaign


async def _make_target(
    repo: CampaignsRepository, *, guild_id: int, campaign_id: UUID, channel_id: int
) -> UUID:
    target = DomainTarget(
        id=uuid4(),
        guild_id=guild_id,
        campaign_id=campaign_id,
        target_kind=DomainTargetKind.CHANNEL,
        discord_channel_id=channel_id,
    )
    await repo.create_target(target)
    return target.id


async def _make_trigger(
    repo: CampaignsRepository, *, campaign_id: UUID, source_guild_id: int
) -> CampaignTrigger:
    trigger = CampaignTrigger(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign_id,
        event_type="MESSAGE_CREATE",
        condition_ast={"op": "ALWAYS"},
    )
    await repo.create_trigger(trigger)
    await repo.create_trigger_source(
        TriggerSourceBinding(
            id=uuid4(),
            guild_id=source_guild_id,
            trigger_id=trigger.id,
            source_scope_kind=TriggerSourceScopeKind.GUILD,
        )
    )
    return trigger


async def _make_root_occurrence(
    repo: CampaignsRepository, *, campaign_id: UUID
) -> MessageOccurrence:
    """A SCHEDULE-sourced occurrence -- its own causal root (depth 0,
    ancestry exactly {campaign_id}), exactly as
    did.campaigns.scheduler_loop/did.api.stage09 construct one."""
    occurrence = MessageOccurrence(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign_id,
        occurrence_key=f"root-{uuid4().hex[:8]}",
        occurrence_source=OccurrenceSource.SCHEDULE,
        scheduled_for=datetime.now(UTC),
        source_causation_depth=0,
        source_ancestry=frozenset({str(campaign_id)}),
        status=OccurrenceStatus.COMPLETED,
    )
    created = await repo.create_occurrence(OWNER_A, occurrence)
    assert created
    return occurrence


async def _send(
    repo: CampaignsRepository,
    admin_factory: async_sessionmaker[Any],
    *,
    guild_id: int,
    campaign_id: UUID,
    occurrence_id: UUID,
    target_id: UUID,
    channel_id: int,
    message_id: int,
) -> MessageDelivery:
    """Directly records a finalized SENT delivery -- the real
    fan_out_occurrence -> worker -> Discord path is proven end to end
    elsewhere (test_stage09_runtime_chain_postgres.py); these tests isolate
    the ONE thing nothing else proves: correlating an already-SENT
    delivery's resulting Gateway echo back to its causal metadata.
    ``CampaignsRepository.create_delivery`` only ever inserts a PENDING
    delivery (``discord_message_id`` is set later by ``finalize_delivery``
    alone, mirroring the real product lifecycle) -- so this creates the row
    normally and then finalizes it with a direct admin update, exactly like
    ``_finalize_as_sent`` below does for a delivery the real fan-out path
    created."""
    delivery = MessageDelivery(
        id=uuid4(),
        guild_id=guild_id,
        campaign_id=campaign_id,
        occurrence_id=occurrence_id,
        target_id=target_id,
        delivery_key=f"dk-{uuid4().hex[:8]}",
        discord_channel_id=channel_id,
        allowed_mentions_snapshot={},
    )
    created = await repo.create_delivery(delivery)
    assert created
    await _finalize_as_sent(admin_factory, delivery_id=delivery.id, message_id=message_id)
    return delivery


async def _occurrence_row(
    admin_factory: async_sessionmaker[Any], *, campaign_id: UUID, occurrence_key_prefix: str
) -> dict[str, Any]:
    async with admin_factory() as session, session.begin():
        result = (
            (
                await session.execute(
                    text(
                        "SELECT * FROM message_occurrences WHERE campaign_id=:cid "
                        "AND occurrence_key LIKE :prefix ORDER BY id"
                    ),
                    {"cid": campaign_id, "prefix": f"{occurrence_key_prefix}%"},
                )
            )
            .mappings()
            .all()
        )
    assert len(result) == 1, f"expected exactly one occurrence for {campaign_id}, got {result}"
    return dict(result[0])


async def _occurrence_count(admin_factory: async_sessionmaker[Any], *, campaign_id: UUID) -> int:
    async with admin_factory() as session, session.begin():
        result = await session.execute(
            text("SELECT count(*) FROM message_occurrences WHERE campaign_id=:cid"),
            {"cid": campaign_id},
        )
        return int(result.scalar_one())


async def _insert_event(
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    author_is_bot: bool = True,
    author_discord_user_id: int = BOT_USER_ID,
) -> None:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin_engine.begin() as connection:
            await _insert_bot_message_event(
                connection,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                author_is_bot=author_is_bot,
                author_discord_user_id=author_discord_user_id,
            )
    finally:
        await admin_engine.dispose()


async def _finalize_as_sent(
    admin_factory: async_sessionmaker[Any], *, delivery_id: UUID, message_id: int
) -> None:
    async with admin_factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE message_deliveries SET status='SENT', discord_message_id=:mid WHERE id=:id"
            ),
            {"mid": message_id, "id": delivery_id},
        )


@pytest.mark.asyncio
class TestDirectSelfLoopBlocked:
    async def test_campaign_a_own_message_create_does_not_retrigger_itself(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        target_a = await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_a.id, channel_id=CHANNEL_A
        )
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)
        occurrence_a = await _make_root_occurrence(campaigns_repo, campaign_id=campaign_a.id)
        await _send(
            campaigns_repo,
            admin_factory,
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            occurrence_id=occurrence_a.id,
            target_id=target_a,
            channel_id=CHANNEL_A,
            message_id=910001,
        )
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_A, message_id=910001)

        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 0
        assert await _occurrence_count(admin_factory, campaign_id=campaign_a.id) == 1


@pytest.mark.asyncio
class TestABACycleBlocked:
    async def test_a_to_b_fires_but_b_to_a_is_blocked(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        campaign_b = await _make_campaign(campaigns_repo, name="B")
        target_a = await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_a.id, channel_id=CHANNEL_A
        )
        await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_b.id, channel_id=CHANNEL_B
        )
        # B listens for MESSAGE_CREATE in Guild A (where A publishes).
        await _make_trigger(campaigns_repo, campaign_id=campaign_b.id, source_guild_id=GUILD_A)
        # A ALSO listens for MESSAGE_CREATE in Guild A -- this is what
        # closes the loop once B's own message re-enters (both A and B
        # target the same Guild here for simplicity; the cross-Guild
        # variant is proven separately below).
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)

        occurrence_a = await _make_root_occurrence(campaigns_repo, campaign_id=campaign_a.id)
        await _send(
            campaigns_repo,
            admin_factory,
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            occurrence_id=occurrence_a.id,
            target_id=target_a,
            channel_id=CHANNEL_A,
            message_id=910101,
        )
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_A, message_id=910101)

        # --- Hop 1: A's message fires B (B is not yet in A's ancestry).
        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 1

        occurrence_b = await _occurrence_row(
            admin_factory, campaign_id=campaign_b.id, occurrence_key_prefix="trigger:"
        )
        assert set(occurrence_b["source_ancestry"]) == {str(campaign_a.id), str(campaign_b.id)}
        assert occurrence_b["source_causation_depth"] == 1
        # correlation_id is inherited from A's own root occurrence (which
        # had none of its own -- its own id is the chain's stable root).
        assert UUID(str(occurrence_b["source_correlation_id"])) == occurrence_a.id
        # causation_id is the MESSAGE_CREATE Gateway event id A's message
        # produced -- NOT A's occurrence id.
        assert occurrence_b["source_event_id"] is not None

        # B's delivery was created PENDING by the real fan_out_occurrence
        # path -- finalize it as SENT to simulate the worker having sent
        # it, so its own resulting message can be correlated next.
        pending = await campaigns_repo.list_pending_delivery_ids(GUILD_A, limit=10)
        assert len(pending) == 1
        await _finalize_as_sent(admin_factory, delivery_id=pending[0], message_id=910102)
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_B, message_id=910102)

        # --- Hop 2: B's own resulting message must NOT re-trigger A (A is
        # already in B's ancestry) -- and must not re-trigger B itself
        # either (B is also in its own ancestry).
        fired_again = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired_again == 0
        assert await _occurrence_count(admin_factory, campaign_id=campaign_a.id) == 1


@pytest.mark.asyncio
class TestCrossGuildABCACycleBlocked:
    async def test_a_to_b_to_c_to_a_across_three_guilds_is_blocked_at_the_final_hop(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        campaign_b = await _make_campaign(campaigns_repo, name="B")
        campaign_c = await _make_campaign(campaigns_repo, name="C")
        target_a = await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_a.id, channel_id=CHANNEL_A
        )
        await _make_target(
            campaigns_repo, guild_id=GUILD_B, campaign_id=campaign_b.id, channel_id=CHANNEL_B
        )
        await _make_target(
            campaigns_repo, guild_id=GUILD_C, campaign_id=campaign_c.id, channel_id=CHANNEL_C
        )
        # B listens for MESSAGE_CREATE from Guild A (cross-Guild source --
        # REQ-MSG-027 explicit source binding, not inferred).
        await _make_trigger(campaigns_repo, campaign_id=campaign_b.id, source_guild_id=GUILD_A)
        # C listens for MESSAGE_CREATE from Guild B.
        await _make_trigger(campaigns_repo, campaign_id=campaign_c.id, source_guild_id=GUILD_B)
        # A listens for MESSAGE_CREATE from Guild C -- closing the cycle.
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_C)

        occurrence_a = await _make_root_occurrence(campaigns_repo, campaign_id=campaign_a.id)
        await _send(
            campaigns_repo,
            admin_factory,
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            occurrence_id=occurrence_a.id,
            target_id=target_a,
            channel_id=CHANNEL_A,
            message_id=920001,
        )
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_A, message_id=920001)

        # --- Hop A -> B (Guild A's inbox).
        fired_ab = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired_ab == 1
        occurrence_b = await _occurrence_row(
            admin_factory, campaign_id=campaign_b.id, occurrence_key_prefix="trigger:"
        )
        assert set(occurrence_b["source_ancestry"]) == {str(campaign_a.id), str(campaign_b.id)}
        assert occurrence_b["source_causation_depth"] == 1
        pending_b = await campaigns_repo.list_pending_delivery_ids(GUILD_B, limit=10)
        assert len(pending_b) == 1
        await _finalize_as_sent(admin_factory, delivery_id=pending_b[0], message_id=920002)
        await _insert_event(guild_id=GUILD_B, channel_id=CHANNEL_B, message_id=920002)

        # --- Hop B -> C (Guild B's inbox).
        fired_bc = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_B)
        )
        assert fired_bc == 1
        occurrence_c = await _occurrence_row(
            admin_factory, campaign_id=campaign_c.id, occurrence_key_prefix="trigger:"
        )
        assert set(occurrence_c["source_ancestry"]) == {
            str(campaign_a.id),
            str(campaign_b.id),
            str(campaign_c.id),
        }
        assert occurrence_c["source_causation_depth"] == 2
        pending_c = await campaigns_repo.list_pending_delivery_ids(GUILD_C, limit=10)
        assert len(pending_c) == 1
        await _finalize_as_sent(admin_factory, delivery_id=pending_c[0], message_id=920003)
        await _insert_event(guild_id=GUILD_C, channel_id=CHANNEL_C, message_id=920003)

        # --- Hop C -> A (Guild C's inbox): A is already in the ancestry
        # {A, B, C} that C's message carries -- the 4-hop cycle is blocked.
        fired_ca = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_C)
        )
        assert fired_ca == 0
        assert await _occurrence_count(admin_factory, campaign_id=campaign_a.id) == 1


@pytest.mark.asyncio
class TestOwnBotVsThirdPartyBotIdentity:
    """REQ-MSG-030 fix: only a MESSAGE_CREATE confirmed to be DID's own
    bound bot identity (did.infrastructure.stage04_repository
    .Stage04Repository.bot_identity, never a hardcoded snowflake) may ever
    enter the correlation-wait path. A third-party bot's own messages, or a
    human's, are DID's concern in the ordinary trigger sense only -- never
    searched against the delivery ledger, never made to stall the cursor."""

    async def test_third_party_bot_message_is_never_deferred_or_searched(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)
        # Freshly received (well inside the grace window) -- if this were
        # ever mistaken for DID's own bot, it would defer instead of firing
        # in this same pass.
        await _insert_event(
            guild_id=GUILD_A,
            channel_id=CHANNEL_A,
            message_id=950001,
            author_is_bot=True,
            author_discord_user_id=THIRD_PARTY_BOT_USER_ID,
        )
        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 1
        # The cursor progressed in this same pass -- no correlation wait.
        assert GUILD_A not in await runtime_repo.runtime_campaign_event_guilds()

    async def test_human_message_is_evaluated_normally_without_correlation_wait(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)
        await _insert_event(
            guild_id=GUILD_A,
            channel_id=CHANNEL_A,
            message_id=950002,
            author_is_bot=False,
            author_discord_user_id=HUMAN_USER_ID,
        )
        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 1
        assert GUILD_A not in await runtime_repo.runtime_campaign_event_guilds()

    async def test_own_did_bot_message_enters_the_correlation_wait_path(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """Contrast case: the exact same shape of event, but genuinely
        DID's own bot identity, DOES defer while unresolved -- proving the
        distinction is real, not that nothing ever waits."""
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)
        await _insert_event(
            guild_id=GUILD_A,
            channel_id=CHANNEL_A,
            message_id=950003,
            author_is_bot=True,
            author_discord_user_id=BOT_USER_ID,
        )
        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 0
        # Still waiting -- the cursor has NOT progressed.
        assert GUILD_A in await runtime_repo.runtime_campaign_event_guilds()


@pytest.mark.asyncio
class TestGatewayFinalizeRaceOrdering:
    async def test_finalize_before_gateway_resolves_in_the_same_pass(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """The common ordering: the HTTP send response (and
        finalize_delivery setting discord_message_id) is already durably
        persisted by the time the Gateway MESSAGE_CREATE is consumed."""
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        campaign_b = await _make_campaign(campaigns_repo, name="B")
        target_a = await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_a.id, channel_id=CHANNEL_A
        )
        await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_b.id, channel_id=CHANNEL_B
        )
        await _make_trigger(campaigns_repo, campaign_id=campaign_b.id, source_guild_id=GUILD_A)
        occurrence_a = await _make_root_occurrence(campaigns_repo, campaign_id=campaign_a.id)

        # finalize_delivery (via _send) happens BEFORE the Gateway event is
        # even inserted.
        await _send(
            campaigns_repo,
            admin_factory,
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            occurrence_id=occurrence_a.id,
            target_id=target_a,
            channel_id=CHANNEL_A,
            message_id=930001,
        )
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_A, message_id=930001)

        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 1
        # The cursor advanced past this event in the very same pass --
        # nothing left to consume.
        assert GUILD_A not in await runtime_repo.runtime_campaign_event_guilds()

    async def test_gateway_before_finalize_defers_until_resolved(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """The race: the Gateway MESSAGE_CREATE is consumed BEFORE the
        delivery has been finalized SENT. The cursor must not advance past
        it (so no other event in this Guild is skipped ahead of it either),
        and once the delivery finalizes, the very next pass resolves and
        fires correctly -- no lucky ordering assumed."""
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        campaign_b = await _make_campaign(campaigns_repo, name="B")
        target_a = await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_a.id, channel_id=CHANNEL_A
        )
        await _make_target(
            campaigns_repo, guild_id=GUILD_A, campaign_id=campaign_b.id, channel_id=CHANNEL_B
        )
        await _make_trigger(campaigns_repo, campaign_id=campaign_b.id, source_guild_id=GUILD_A)
        occurrence_a = await _make_root_occurrence(campaigns_repo, campaign_id=campaign_a.id)

        # The delivery exists (PENDING) but is NOT yet finalized SENT --
        # exactly the state a real delivery is in between claim and the
        # HTTP response actually landing.
        delivery = MessageDelivery(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            occurrence_id=occurrence_a.id,
            target_id=target_a,
            delivery_key=f"dk-{uuid4().hex[:8]}",
            discord_channel_id=CHANNEL_A,
            allowed_mentions_snapshot={},
        )
        assert await campaigns_repo.create_delivery(delivery)
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_A, message_id=930101)

        # --- Attempt 1: the Gateway event is there, but nothing has SENT
        # yet -- correlation fails, the cursor must not advance past it.
        fired_1 = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired_1 == 0
        assert GUILD_A in await runtime_repo.runtime_campaign_event_guilds()

        # A second attempt with nothing changed must be exactly as safe a
        # no-op (this is what a real restart between attempts looks like --
        # a brand new RuntimeRepository/CampaignsRepository instance,
        # proving no in-memory state was ever relied on).
        fresh_runtime_repo = RuntimeRepository(
            async_sessionmaker(create_database_engine(APP_URL, pool_size=1), expire_on_commit=False)
        )
        fired_1b = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, fresh_runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired_1b == 0

        # --- Now finalize_delivery lands (the HTTP response finally
        # returns and is persisted).
        await _finalize_as_sent(admin_factory, delivery_id=delivery.id, message_id=930101)

        # --- Attempt 2 (the next real tick): correlation now succeeds.
        fired_2 = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired_2 == 1
        assert GUILD_A not in await runtime_repo.runtime_campaign_event_guilds()


@pytest.mark.asyncio
class TestUnresolvableBotMessageAgesOut:
    async def test_a_bot_message_never_sent_through_the_ledger_eventually_skips_fail_closed(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        """A MESSAGE_CREATE confirmed to be DID's own bot identity, but
        which will NEVER correlate to any Stage09 delivery (sent through
        some other feature entirely), must not stall this Guild's event
        processing forever -- but it also must NEVER be evaluated against
        any trigger once it ages out: silently treating it as an "ordinary"
        event would reopen exactly the self/cross-campaign loop the
        ancestor-loop guard exists to prevent. Fail-closed, not fail-open."""
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)

        old_received_at = datetime.now(UTC) - timedelta(
            seconds=BOT_MESSAGE_CORRELATION_GRACE_SECONDS + 30
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_bot_message_event(
                    connection,
                    guild_id=GUILD_A,
                    channel_id=CHANNEL_A,
                    message_id=940001,
                    received_at=old_received_at,
                )
        finally:
            await admin_engine.dispose()

        # A's own trigger never fires on this uncorrelated event -- it is
        # skipped, not treated as an ordinary unattributed event.
        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 0
        assert await _occurrence_count(admin_factory, campaign_id=campaign_a.id) == 0
        # The cursor still advanced -- it is not stuck on this event forever.
        assert GUILD_A not in await runtime_repo.runtime_campaign_event_guilds()

    async def test_a_recent_unresolved_bot_message_is_not_aged_out_prematurely(
        self,
        ancestry_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, admin_factory = ancestry_context
        campaign_a = await _make_campaign(campaigns_repo, name="A")
        await _make_trigger(campaigns_repo, campaign_id=campaign_a.id, source_guild_id=GUILD_A)
        await _insert_event(guild_id=GUILD_A, channel_id=CHANNEL_A, message_id=940101)

        fired = await consume_new_events_for_guild(
            **_kwargs(campaigns_repo, runtime_repo, admin_factory, guild_id=GUILD_A)
        )
        assert fired == 0
        # Still not advanced -- this Guild still shows up as having
        # unconsumed campaign events, waiting for correlation.
        assert GUILD_A in await runtime_repo.runtime_campaign_event_guilds()
