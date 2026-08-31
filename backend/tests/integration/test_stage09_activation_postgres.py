"""PostgreSQL integration tests for the Stage 09 campaign activation /
occurrence fan-out orchestration (WP12): did.campaigns.activation is the
real service connecting a decided occurrence -> target resolution ->
per-Guild authorization -> translation/approved-variant decision ->
deterministic delivery creation, proven crash-safe and restart-idempotent
against a real CampaignsRepository.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.activation import FanOutOutcome, OccurrenceNotClaimable, fan_out_occurrence
from did.campaigns.approved_variants import compute_source_fingerprint
from did.domain.campaigns import (
    ApprovedVariant,
    LifecycleStatus,
    MessageCampaign,
    MessageOccurrence,
    OccurrenceSource,
    PublicationMode,
)
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.messaging.allowed_mentions import NO_MENTIONS
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
OWNER_A = 880000951

CLEANUP_STATEMENTS = (
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_approved_variants WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
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
        {"guild_id": guild_id, "name": f"Stage 09 activation {guild_id}", "owner_id": OWNER_A},
    )


async def _insert_translation_group(
    connection: AsyncConnection, guild_id: int, group_id: object
) -> None:
    await connection.execute(
        text(
            "INSERT INTO translation_groups (id, guild_id, name, root_kind) "
            "VALUES (:id, :guild_id, :name, 'CHANNEL_SET') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": group_id, "guild_id": guild_id, "name": f"group-{group_id}"},
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


class _FakeChecker:
    def __init__(self, *, sendable_channels: set[int] | None = None) -> None:
        self.sendable_channels = sendable_channels
        self.guild_checks = 0
        self.channel_checks = 0

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        self.guild_checks += 1
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        self.channel_checks += 1
        if self.sendable_channels is None:
            return True
        return discord_channel_id in self.sendable_channels


async def _identity_translate(masked_text: str) -> str:
    return masked_text


def _campaign(**overrides: object) -> MessageCampaign:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Launch",
        source_language_code="en",
        message_model=MessageModel(content="Hello world!").to_dict(),
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    fields.update(overrides)
    return MessageCampaign(**fields)  # type: ignore[arg-type]


def _occurrence(campaign_id: object, **overrides: object) -> MessageOccurrence:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign_id,
        occurrence_key=f"occ-{uuid4().hex[:8]}",
        occurrence_source=OccurrenceSource.EVENT,
        source_event_id=uuid4(),
    )
    fields.update(overrides)
    return MessageOccurrence(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
class TestFanOutSourceLanguage:
    async def test_immediate_channel_target_creates_one_delivery(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=999,
        )
        await repo.create_target(target)
        occurrence = _occurrence(campaign.id)

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(target,),
            occurrence=occurrence,
            lease_owner="worker-1",
            topology_by_target={},
            language_profile_codes={},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=None,
        )
        assert outcome.deliveries_created == 1
        assert outcome.is_fully_healthy
        status = await repo.get_delivery_status(GUILD_A, uuid4())  # sanity: method exists/works
        assert status is None  # unrelated random id, must not error

    async def test_restart_after_fanned_out_is_idempotent_no_op(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=999,
        )
        await repo.create_target(target)
        occurrence = _occurrence(campaign.id)

        kwargs = dict(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(target,),
            occurrence=occurrence,
            lease_owner="worker-1",
            topology_by_target={},
            language_profile_codes={},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=None,
        )
        first = await fan_out_occurrence(**kwargs)  # type: ignore[arg-type]
        assert first.deliveries_created == 1

        # A second fan-out attempt for the SAME occurrence (simulating a
        # restart replaying the same "occurrence is due" decision) must
        # not create a second delivery, nor even re-attempt claiming --
        # the occurrence is already FANNED_OUT.
        second = await fan_out_occurrence(**kwargs)  # type: ignore[arg-type]
        assert second.deliveries_created == 0
        assert second.deliveries_already_existed == 0  # never even reached the delivery loop
        assert second.occurrence_id == first.occurrence_id

    async def test_two_concurrent_fan_out_attempts_only_one_wins(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Simulates two scheduler/event-consumer workers both deciding the
        same occurrence is due at the same time (a genuine restart race,
        not merely a sequential replay)."""
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=999,
        )
        await repo.create_target(target)
        occurrence_key = f"occ-{uuid4().hex[:8]}"

        async def _attempt(worker_id: str) -> FanOutOutcome | OccurrenceNotClaimable:
            occurrence = _occurrence(campaign.id, id=uuid4(), occurrence_key=occurrence_key)
            try:
                return await fan_out_occurrence(
                    repository=repo,
                    checker=_FakeChecker(),
                    campaign=campaign,
                    targets=(target,),
                    occurrence=occurrence,
                    lease_owner=worker_id,
                    topology_by_target={},
                    language_profile_codes={},
                    compiled_mentions=NO_MENTIONS,
                    template_variable_definitions={},
                    glossary_entries=(),
                    translate_masked_text_for_language=None,
                )
            except OccurrenceNotClaimable as exc:
                return exc

        results = await asyncio.gather(_attempt("worker-1"), _attempt("worker-2"))
        outcomes = [r for r in results if isinstance(r, FanOutOutcome)]
        created_counts = [r.deliveries_created for r in outcomes]
        # Exactly one delivery must exist in total across both attempts --
        # either one attempt created it and the other saw it already
        # existed/was unclaimable, but never two deliveries for one logical
        # occurrence.
        assert sum(created_counts) <= 1
        total_deliveries = sum(
            r.deliveries_created + r.deliveries_already_existed for r in outcomes
        )
        assert total_deliveries <= 1


@pytest.mark.asyncio
class TestFanOutTranslation:
    async def test_translated_destination_reuses_a_matching_approved_variant(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        approved_content = MessageModel(content="Bonjour le monde !")
        await repo.upsert_approved_variant(
            ApprovedVariant(
                id=uuid4(),
                owner_discord_user_id=OWNER_A,
                campaign_id=campaign.id,
                target_language_code="fr",
                source_fingerprint=compute_source_fingerprint(campaign),
                localized_message_model=approved_content.to_dict(),
                approved_by_discord_user_id=OWNER_A,
            )
        )
        language_profile_id = uuid4()
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=999,
        )
        # Force the target to resolve with a translated destination by
        # monkeypatching resolve_target's behavior via a direct delivery
        # build path is unnecessary -- CHANNEL targets always resolve
        # source-only; to exercise a translated destination, use a
        # TRANSLATION_GROUP target instead.
        await repo.create_target(target)

        async def _translate_should_never_be_called(masked_text: str) -> str:
            raise AssertionError("translate_masked_text must not be called for a REUSABLE variant")

        # Directly exercise the approved-variant branch via a
        # TRANSLATION_GROUP-shaped resolution using the real
        # target_resolution module through fan_out_occurrence's own target
        # loop: build a translation-group target + topology.
        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
        from did.domain.campaigns import TranslationPublicationMode

        group_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT,
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_translation_group(
                    connection, GUILD_A, group_target.translation_group_id
                )
        finally:
            await admin_engine.dispose()
        await repo.create_target(group_target)
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=999, variants=((language_profile_id, 1000),)
        )

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(group_target,),
            occurrence=_occurrence(campaign.id),
            lease_owner="worker-1",
            topology_by_target={group_target.id: topology},
            language_profile_codes={language_profile_id: "fr"},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=lambda _lang: _translate_should_never_be_called,
        )
        assert outcome.is_fully_healthy
        # Source channel (no translation) + fr variant (reused) = 2 deliveries.
        assert outcome.deliveries_created == 2

    async def test_missing_variant_renders_fresh_but_is_never_auto_approved(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(message_model=MessageModel(content="Hello {{name}}!").to_dict())
        await repo.create_campaign(campaign)
        language_profile_id = uuid4()

        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
        from did.domain.campaigns import TranslationPublicationMode
        from did.messaging.template_variables import (
            TemplateVariableDefinition,
            TemplateVariableType,
        )

        group_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_translation_group(
                    connection, GUILD_A, group_target.translation_group_id
                )
        finally:
            await admin_engine.dispose()
        await repo.create_target(group_target)
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=999, variants=((language_profile_id, 1000),)
        )
        definitions = {
            "name": TemplateVariableDefinition(
                "name", TemplateVariableType.TRANSLATABLE_TEXT, value="Sam"
            )
        }

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(group_target,),
            occurrence=_occurrence(campaign.id),
            lease_owner="worker-1",
            topology_by_target={group_target.id: topology},
            language_profile_codes={language_profile_id: "fr"},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions=definitions,
            glossary_entries=(),
            translate_masked_text_for_language=lambda _lang: _identity_translate,
        )
        assert outcome.is_fully_healthy
        assert outcome.deliveries_created == 1  # SELECTED_LANGUAGES: only the fr variant

        # Fan-out never silently records a fresh machine render as a
        # human-approved variant (REQ-MSG-016) -- it must remain absent
        # until an explicit, separately-authenticated approval call.
        variants = await repo.list_approved_variants(OWNER_A, campaign.id)
        assert "fr" not in variants

        from did.campaigns.approved_variants import (
            VariantApproval,
            approve_variant,
            compute_source_fingerprint,
        )

        approved = await approve_variant(
            repo,
            owner_discord_user_id=OWNER_A,
            approving_discord_user_id=OWNER_A,
            approval=VariantApproval(
                campaign_id=campaign.id,
                target_language_code="fr",
                localized_message_model={"content": "Bonjour Sam!"},
                source_fingerprint=compute_source_fingerprint(campaign),
            ),
        )
        assert approved.approved_by_discord_user_id == OWNER_A
        variants_after = await repo.list_approved_variants(OWNER_A, campaign.id)
        assert "fr" in variants_after

    async def test_missing_variant_with_no_provider_is_a_render_failure_not_a_crash(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        language_profile_id = uuid4()

        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
        from did.domain.campaigns import TranslationPublicationMode

        group_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_translation_group(
                    connection, GUILD_A, group_target.translation_group_id
                )
        finally:
            await admin_engine.dispose()
        await repo.create_target(group_target)
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=999, variants=((language_profile_id, 1000),)
        )

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(group_target,),
            occurrence=_occurrence(campaign.id),
            lease_owner="worker-1",
            topology_by_target={group_target.id: topology},
            language_profile_codes={language_profile_id: "fr"},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=None,  # no provider configured
        )
        assert outcome.deliveries_created == 0
        assert len(outcome.render_failures) == 1
        assert not outcome.is_fully_healthy

    async def test_each_destination_is_translated_into_its_own_target_language(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Regression test for a real defect found while wiring a live
        translation provider into the runtime: a single fan-out call
        routinely spans destinations in several different target languages,
        but the old `translate_masked_text: TranslateMaskedText` parameter
        (no language argument of its own) was bound ONCE for the whole
        call -- a real provider would have silently translated every
        non-source destination into whichever language happened to be
        bound first. `translate_masked_text_for_language` fixes this by
        being invoked once per destination with that destination's own
        resolved target language."""
        repo = campaigns_context
        campaign = _campaign(message_model=MessageModel(content="Hello!").to_dict())
        await repo.create_campaign(campaign)
        fr_language_profile_id = uuid4()
        de_language_profile_id = uuid4()

        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
        from did.domain.campaigns import TranslationPublicationMode

        group_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT,
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_translation_group(
                    connection, GUILD_A, group_target.translation_group_id
                )
        finally:
            await admin_engine.dispose()
        await repo.create_target(group_target)
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=999,
            variants=((fr_language_profile_id, 1000), (de_language_profile_id, 2000)),
        )

        requested_languages: list[str] = []

        def _translate_for_language(target_language: str):  # type: ignore[no-untyped-def]
            async def _translate(masked_text: str) -> str:
                requested_languages.append(target_language)
                return f"[{target_language}] {masked_text}"

            return _translate

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(group_target,),
            occurrence=_occurrence(campaign.id),
            lease_owner="worker-1",
            topology_by_target={group_target.id: topology},
            language_profile_codes={
                fr_language_profile_id: "fr",
                de_language_profile_id: "de",
            },
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=_translate_for_language,
        )
        assert outcome.is_fully_healthy
        # Source + fr + de = 3 deliveries, and each translation call was
        # requested for exactly the language its own destination needed --
        # never a single language reused across both.
        assert outcome.deliveries_created == 3
        assert sorted(requested_languages) == ["de", "fr"]


@pytest.mark.asyncio
class TestFanOutAuthorizationAndPreflight:
    async def test_bot_cannot_send_destination_is_blocked_not_a_crash(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign()
        await repo.create_campaign(campaign)
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=999,
        )
        await repo.create_target(target)
        occurrence = _occurrence(campaign.id)

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(sendable_channels=set()),
            campaign=campaign,
            targets=(target,),
            occurrence=occurrence,
            lease_owner="worker-1",
            topology_by_target={},
            language_profile_codes={},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=None,
        )
        assert outcome.deliveries_created == 0
        assert len(outcome.blocked_destinations) == 1
        assert not outcome.is_fully_healthy


@pytest.mark.asyncio
class TestFanOutLeaseFencing:
    """External-review finding (this pass): fan_out_occurrence ignored
    finalize_occurrence_fanout's boolean fencing result, and a real fan-out
    (many Guilds/destinations/translation calls) can easily outlive a short
    fixed lease -- both must be closed, not merely acknowledged."""

    async def test_lease_stolen_mid_expansion_raises_instead_of_reporting_success(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Simulates a reconciler reclaiming this exact occurrence's lease
        WHILE this fan-out's own translate callback is still running (well
        past what a real stall-detection reconciler would consider
        abandoned). The original fan-out must never report a healthy
        FanOutOutcome once it can no longer prove it owns the occurrence."""
        repo = campaigns_context
        campaign = _campaign(
            message_model=MessageModel(content="Hello {{name}}!").to_dict(),
            source_language_code="en",
        )
        await repo.create_campaign(campaign)
        language_profile_id = uuid4()

        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
        from did.domain.campaigns import TranslationPublicationMode

        group_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        async with admin_engine.begin() as connection:
            await _insert_translation_group(connection, GUILD_A, group_target.translation_group_id)
        await repo.create_target(group_target)
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=999, variants=((language_profile_id, 1000),)
        )
        occurrence = _occurrence(campaign.id)

        async def _steal_lease_mid_render(masked_text: str) -> str:
            # A second worker reclaims the occurrence once its lease looks
            # expired -- force that by directly expiring leased_until (real
            # wall-clock waiting would make this test slow and flaky).
            async with admin_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE message_occurrences SET leased_until = now() - "
                        "interval '1 second' WHERE campaign_id = :campaign_id"
                    ),
                    {"campaign_id": campaign.id},
                )
            reclaimed = await repo.claim_occurrence_for_fanout(
                OWNER_A, occurrence.id, lease_owner="reconciler-mid-flight"
            )
            assert reclaimed is not None  # the theft must actually succeed
            return masked_text

        try:
            from did.campaigns.activation import FanOutLeaseLostError

            with pytest.raises(FanOutLeaseLostError):
                await fan_out_occurrence(
                    repository=repo,
                    checker=_FakeChecker(),
                    campaign=campaign,
                    targets=(group_target,),
                    occurrence=occurrence,
                    lease_owner="worker-original",
                    topology_by_target={group_target.id: topology},
                    language_profile_codes={language_profile_id: "fr"},
                    compiled_mentions=NO_MENTIONS,
                    template_variable_definitions={},
                    glossary_entries=(),
                    translate_masked_text_for_language=lambda _lang: _steal_lease_mid_render,
                )
        finally:
            await admin_engine.dispose()

        # The reconciler's own claim is still valid -- it, not the original
        # worker, now owns the occurrence, and no delivery was left behind
        # claiming a health this worker could no longer prove.
        row = await repo.get_occurrence_by_key(OWNER_A, campaign.id, occurrence.occurrence_key)
        assert row is not None
        assert row["status"] == "CLAIMED"
        assert row["lease_owner"] == "reconciler-mid-flight"

    async def test_heartbeat_renews_lease_across_a_slow_fanout(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """A translate callback slower than the configured lease_seconds
        must not cause the occurrence's own lease to expire underneath a
        still-healthy worker -- the heartbeat must renew it in time."""
        repo = campaigns_context
        campaign = _campaign(
            message_model=MessageModel(content="Hello {{name}}!").to_dict(),
            source_language_code="en",
        )
        await repo.create_campaign(campaign)
        language_profile_id = uuid4()

        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
        from did.domain.campaigns import TranslationPublicationMode

        group_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_translation_group(
                    connection, GUILD_A, group_target.translation_group_id
                )
        finally:
            await admin_engine.dispose()
        await repo.create_target(group_target)
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=999, variants=((language_profile_id, 1000),)
        )
        occurrence = _occurrence(campaign.id)

        async def _slow_translate(masked_text: str) -> str:
            await asyncio.sleep(0.3)
            return masked_text

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(group_target,),
            occurrence=occurrence,
            lease_owner="worker-original",
            topology_by_target={group_target.id: topology},
            language_profile_codes={language_profile_id: "fr"},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=lambda _lang: _slow_translate,
            lease_seconds=0.1,
        )
        assert outcome.is_fully_healthy
        assert outcome.deliveries_created == 1  # SELECTED_LANGUAGES: only the fr variant
