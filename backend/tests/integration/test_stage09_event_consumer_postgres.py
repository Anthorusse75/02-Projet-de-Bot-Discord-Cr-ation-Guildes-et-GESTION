"""PostgreSQL integration tests for the Stage 09 event consumer (WP12):
did.campaigns.event_consumer.consume_event_for_trigger against a real
CampaignsRepository -- proves the round trip through
CampaignsRepository.load_trigger_sources (including real enum
deserialization, not a hand-built Python object) correctly feeds
did.campaigns.causality.should_trigger, and that trigger/event consumption
dedup and deterministic occurrence creation are both real and durable.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.event_consumer import consume_event_for_trigger
from did.domain.campaigns import CampaignTrigger, TriggerSourceBinding
from did.domain.campaigns import TriggerSourceScopeKind as ScopeKind
from did.domain.discord_runtime import EventEnvelope, EventOrigin, EventSource
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
GUILD_A = 880000961
GUILD_B = 880000962
OWNER_A = 880000971

CLEANUP_STATEMENTS = (
    "DELETE FROM message_campaign_trigger_consumptions WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_campaign_trigger_sources WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaign_triggers WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "gb": GUILD_B, "oa": OWNER_A}


def _envelope(
    *,
    guild_id: int,
    event_type: str = "MEMBER_JOIN",
    payload: Mapping[str, object] | None = None,
    causation_depth: int = 0,
    event_id: UUID | None = None,
) -> EventEnvelope:
    """A real EventEnvelope -- the exact shape a durable Stage03
    discord_gateway_inbox row (or, for the synthetic non-Gateway-captured
    event_type used by these tests, an analogous durable event) carries."""
    identity = event_id or uuid4()
    return EventEnvelope(
        event_id=identity,
        guild_id=guild_id,
        event_type=event_type,
        discord_sequence=None,
        discord_session_id="test-session",
        occurred_at=None,
        received_at=datetime.now(UTC),
        correlation_id=identity,
        causation_id=None,
        schema_version=1,
        payload=dict(payload or {}),
        source=EventSource.GATEWAY,
        origin=EventOrigin.DISCORD_EXTERNAL,
        causation_depth=causation_depth,
    )


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Stage 09 event consumer {guild_id}", "owner_id": OWNER_A},
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
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"),
                CLEANUP_PARAMS,
            )
            await _insert_user(connection, OWNER_A)
            await _insert_installation(connection, GUILD_A)
            await _insert_installation(connection, GUILD_B)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield CampaignsRepository(factory)
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


async def _campaign_and_trigger(
    repo: CampaignsRepository,
    *,
    requires_message_content: bool = False,
    event_type: str = "MEMBER_JOIN",
) -> CampaignTrigger:
    from did.domain.campaigns import LifecycleStatus, MessageCampaign, PublicationMode

    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Event campaign",
        source_language_code="en",
        message_model={"content": "hello"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.EVENT_TRIGGERED,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    await repo.create_campaign(campaign)
    trigger = CampaignTrigger(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign.id,
        event_type=event_type,
        condition_ast={"op": "ALWAYS"},
        requires_message_content=requires_message_content,
    )
    await repo.create_trigger(trigger)
    return trigger


@pytest.mark.asyncio
class TestConsumeEventForTrigger:
    async def test_authorized_event_fires_exactly_once(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )

        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A),
            discord_resource_id=None,
        )
        assert result.fired is True
        assert result.already_consumed is False
        assert result.occurrence is not None
        assert result.occurrence.campaign_id == trigger.campaign_id
        # Ownership is derived from the durably-loaded trigger, never a
        # caller-supplied parameter (this function no longer even accepts
        # one) -- REQ-MSG-020/027 external-review finding.
        assert result.occurrence.owner_discord_user_id == trigger.owner_discord_user_id

    async def test_duplicate_event_id_is_a_safe_no_op_replay(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        event = _envelope(guild_id=GUILD_A)

        first = await consume_event_for_trigger(
            repository=repo, trigger=trigger, event=event, discord_resource_id=None
        )
        assert first.already_consumed is False

        second = await consume_event_for_trigger(
            repository=repo, trigger=trigger, event=event, discord_resource_id=None
        )
        assert second.fired is True
        assert second.already_consumed is True
        assert second.occurrence is not None
        assert second.occurrence.id == first.occurrence.id  # type: ignore[union-attr]

    async def test_unbound_guild_b_cannot_trigger_guild_a_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        # Event arrives from GUILD_B, which has no source binding for this trigger.
        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_B),
            discord_resource_id=None,
        )
        assert result.fired is False
        assert result.occurrence is None

    async def test_wrong_event_type_does_not_fire_even_with_matching_binding_and_payload(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """External-review finding: a trigger configured for event_type X
        bound to this exact Guild/channel, whose condition AST matches the
        payload, must still NOT fire for an envelope of a different
        event_type Y. Before this pass, consume_event_for_trigger never
        even received or checked event_type at all."""
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo, event_type="MEMBER_JOIN")
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A, event_type="MESSAGE_CREATE"),
            discord_resource_id=None,
        )
        assert result.fired is False
        assert result.occurrence is None

        # The identical envelope shape, but the correct event_type, DOES fire.
        matching = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A, event_type="MEMBER_JOIN"),
            discord_resource_id=None,
        )
        assert matching.fired is True

    async def test_message_content_dependent_trigger_fails_closed_when_unavailable(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo, requires_message_content=True)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A),
            discord_resource_id=None,
            message_content_available=False,
        )
        assert result.fired is False

    async def test_message_content_dependent_trigger_fires_when_available(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo, requires_message_content=True)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A),
            discord_resource_id=None,
            message_content_available=True,
        )
        assert result.fired is True

    async def test_depth_exceeded_is_rejected(self, campaigns_context: CampaignsRepository) -> None:
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A, causation_depth=trigger.max_causation_depth + 1),
            discord_resource_id=None,
        )
        assert result.fired is False

    async def test_ancestor_loop_is_rejected(self, campaigns_context: CampaignsRepository) -> None:
        from did.campaigns.causality import with_campaign_ancestry

        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.GUILD,
            )
        )
        looping_payload = with_campaign_ancestry({}, trigger.campaign_id)
        result = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A, payload=looping_payload, causation_depth=1),
            discord_resource_id=None,
        )
        assert result.fired is False

    async def test_channel_scoped_binding_round_trips_through_real_repository(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Proves the real load_trigger_sources -> TriggerSourceBinding
        reconstruction correctly deserializes source_scope_kind back into
        the real enum (not a raw string) -- should_trigger's `is` comparison
        against the enum would silently reject every match otherwise."""
        repo = campaigns_context
        trigger = await _campaign_and_trigger(repo)
        await repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=ScopeKind.CHANNEL,
                discord_resource_id=555,
            )
        )
        matching = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A),
            discord_resource_id=555,
        )
        assert matching.fired is True

        non_matching = await consume_event_for_trigger(
            repository=repo,
            trigger=trigger,
            event=_envelope(guild_id=GUILD_A),
            discord_resource_id=999,  # different channel, binding does not match
        )
        assert non_matching.fired is False
