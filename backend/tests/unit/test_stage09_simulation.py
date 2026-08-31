"""Unit tests for WP12/REQ-MSG-022's complete campaign simulation
(did.campaigns.simulation.simulate_campaign): destinations, translation
state, and MESSAGE_CONTENT warnings, with zero Discord mutation -- every
dependency is an injected read-only fake, never a repository write.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.approved_variants import compute_source_fingerprint
from did.campaigns.simulation import DestinationTranslationState, simulate_campaign
from did.domain.campaigns import (
    ApprovedVariant,
    CampaignTarget,
    CampaignTrigger,
    LifecycleStatus,
    MessageCampaign,
    PublicationMode,
    TargetKind,
    TranslationPublicationMode,
)

pytestmark = [pytest.mark.security]

GUILD_A = 990000201
OWNER_A = 111


class _FakeAuthorization:
    def __init__(
        self,
        *,
        authorized_guilds: set[int] | None = None,
        sendable_channels: set[int] | None = None,
    ) -> None:
        self.authorized_guilds = authorized_guilds if authorized_guilds is not None else {GUILD_A}
        self.sendable_channels = sendable_channels

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        return guild_id in self.authorized_guilds

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        if self.sendable_channels is None:
            return True
        return discord_channel_id in self.sendable_channels


def _campaign(**overrides: object) -> MessageCampaign:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Launch",
        source_language_code="en",
        message_model={"content": "hello"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    fields.update(overrides)
    return MessageCampaign(**fields)  # type: ignore[arg-type]


def _channel_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=uuid4(),
        target_kind=TargetKind.CHANNEL,
        discord_channel_id=111,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


class TestSimulateCampaignSourceOnly:
    async def test_source_language_destination_is_ready_with_source_state(self) -> None:
        campaign = _campaign()
        target = _channel_target(campaign_id=campaign.id)
        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={},
            approved_variants={},
            language_profile_codes={},
            translation_provider_available=True,
        )
        assert report.total_destinations == 1
        assert report.ready_destinations == 1
        assert report.estimated_delivery_count == 1
        [dest] = report.destinations
        assert dest.translation_state is DestinationTranslationState.SOURCE
        assert dest.delivery_executable is True
        assert not report.blockers

    async def test_unauthorized_guild_is_blocked_and_not_counted_in_delivery_estimate(self) -> None:
        campaign = _campaign()
        target = _channel_target(campaign_id=campaign.id, guild_id=990000202)
        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(authorized_guilds={GUILD_A}),
            topology_by_target={},
            approved_variants={},
            language_profile_codes={},
            translation_provider_available=True,
        )
        assert report.blocked_destinations == 1
        assert report.estimated_delivery_count == 0
        assert "GUILD_NOT_AUTHORIZED" in report.blockers

    async def test_bot_cannot_send_is_blocked(self) -> None:
        campaign = _campaign()
        target = _channel_target(campaign_id=campaign.id)
        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(sendable_channels=set()),
            topology_by_target={},
            approved_variants={},
            language_profile_codes={},
            translation_provider_available=True,
        )
        assert report.blocked_destinations == 1
        assert "BOT_CANNOT_SEND" in report.blockers


class TestSimulateCampaignTranslation:
    async def test_reusable_approved_variant_is_reported_correctly(self) -> None:
        campaign = _campaign()
        language_profile_id = uuid4()
        target = CampaignTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=TargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot

        topology = TranslationGroupTopologySnapshot(
            source_channel_id=111, variants=((language_profile_id, 222),)
        )
        variant = ApprovedVariant(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            target_language_code="fr",
            source_fingerprint=compute_source_fingerprint(campaign),
            localized_message_model={"content": "bonjour"},
            approved_by_discord_user_id=OWNER_A,
        )

        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={target.id: topology},
            approved_variants={"fr": variant},
            language_profile_codes={language_profile_id: "fr"},
            translation_provider_available=True,
        )
        assert report.estimated_delivery_count == 1
        [dest] = report.destinations
        assert dest.translation_state is DestinationTranslationState.REUSABLE_APPROVED

    async def test_stale_variant_would_retranslate_when_provider_available(self) -> None:
        campaign = _campaign()
        language_profile_id = uuid4()
        target = CampaignTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=TargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot

        topology = TranslationGroupTopologySnapshot(
            source_channel_id=111, variants=((language_profile_id, 222),)
        )
        stale_variant = ApprovedVariant(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            target_language_code="fr",
            source_fingerprint="0" * 64,  # deliberately does not match current content
            localized_message_model={"content": "bonjour (obsolete)"},
            approved_by_discord_user_id=OWNER_A,
        )

        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={target.id: topology},
            approved_variants={"fr": stale_variant},
            language_profile_codes={language_profile_id: "fr"},
            translation_provider_available=True,
        )
        [dest] = report.destinations
        assert (
            dest.translation_state is DestinationTranslationState.STALE_APPROVED_WOULD_RETRANSLATE
        )
        assert report.estimated_delivery_count == 1

    async def test_missing_variant_with_no_provider_is_blocked_not_silently_untranslated(
        self,
    ) -> None:
        campaign = _campaign()
        language_profile_id = uuid4()
        target = CampaignTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=TargetKind.TRANSLATION_GROUP,
            translation_group_id=uuid4(),
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(language_profile_id,),
        )
        from did.campaigns.target_resolution import TranslationGroupTopologySnapshot

        topology = TranslationGroupTopologySnapshot(
            source_channel_id=111, variants=((language_profile_id, 222),)
        )
        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={target.id: topology},
            approved_variants={},
            language_profile_codes={language_profile_id: "fr"},
            translation_provider_available=False,
        )
        [dest] = report.destinations
        assert dest.translation_state is DestinationTranslationState.MISSING_NO_PROVIDER_CONFIGURED
        # Ready by target_resolution's own check, but excluded from the
        # delivery estimate and counted as blocked for a distinct reason --
        # `delivery_executable` is the one flag a consumer should trust for
        # "will this destination actually get a delivery", precisely
        # because `ready` alone would be misleading here.
        assert dest.ready is True
        assert dest.delivery_executable is False
        assert report.estimated_delivery_count == 0
        assert "TRANSLATION_PROVIDER_UNAVAILABLE" in report.blockers


class TestSimulateCampaignMessageContentWarnings:
    async def test_dependent_trigger_surfaces_a_warning_without_blocking_destinations(self) -> None:
        campaign = _campaign()
        target = _channel_target(campaign_id=campaign.id)
        trigger = CampaignTrigger(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            event_type="MESSAGE_CREATE",
            condition_ast={"op": "ALWAYS"},
            requires_message_content=True,
        )

        class _FakeMessageContentChecker:
            async def is_message_content_available(self, *, guild_id: int) -> bool:
                return False

        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={},
            approved_variants={},
            language_profile_codes={},
            translation_provider_available=True,
            triggers=(trigger,),
            message_content_checker=_FakeMessageContentChecker(),
            message_content_guild_id=GUILD_A,
        )
        assert len(report.message_content_warnings) == 1
        assert report.message_content_warnings[0].is_blocking is True
        # A capability warning does not by itself block send destinations
        # in the simulation -- it is surfaced separately for the author.
        assert report.estimated_delivery_count == 1

    async def test_trigger_not_requiring_message_content_yields_no_warning(self) -> None:
        campaign = _campaign()
        target = _channel_target(campaign_id=campaign.id)
        trigger = CampaignTrigger(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            event_type="MEMBER_JOIN",
            condition_ast={"op": "ALWAYS"},
            requires_message_content=False,
        )

        class _FakeMessageContentChecker:
            async def is_message_content_available(self, *, guild_id: int) -> bool:
                return False

        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={},
            approved_variants={},
            language_profile_codes={},
            translation_provider_available=True,
            triggers=(trigger,),
            message_content_checker=_FakeMessageContentChecker(),
            message_content_guild_id=GUILD_A,
        )
        assert report.message_content_warnings == ()

    async def test_no_message_content_checker_supplied_yields_no_warnings(self) -> None:
        campaign = _campaign()
        target = _channel_target(campaign_id=campaign.id)
        report = await simulate_campaign(
            campaign=campaign,
            targets=(target,),
            authorization=_FakeAuthorization(),
            topology_by_target={},
            approved_variants={},
            language_profile_codes={},
            translation_provider_available=True,
        )
        assert report.message_content_warnings == ()
