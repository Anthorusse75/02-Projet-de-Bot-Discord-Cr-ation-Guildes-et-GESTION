"""Unit tests for WP4: target resolution, execution-time authorization
revalidation, and side-effect-free simulation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.target_resolution import (
    BlockReason,
    TranslationGroupTopologySnapshot,
    resolve_target,
    summarize_simulation,
)
from did.domain.campaigns import CampaignTarget, TargetKind, TranslationPublicationMode

pytestmark = [pytest.mark.security]


class _FakeAuthorization:
    def __init__(
        self,
        *,
        authorized_guilds: set[int] | None = None,
        sendable_channels: set[int] | None = None,
    ) -> None:
        self.authorized_guilds = authorized_guilds if authorized_guilds is not None else {880000001}
        self.sendable_channels = sendable_channels if sendable_channels is not None else None
        self.guild_checks = 0
        self.channel_checks = 0

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        self.guild_checks += 1
        return guild_id in self.authorized_guilds

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        self.channel_checks += 1
        if self.sendable_channels is None:
            return True
        return discord_channel_id in self.sendable_channels


def _channel_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=880000001,
        campaign_id=uuid4(),
        target_kind=TargetKind.CHANNEL,
        discord_channel_id=111,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


def _group_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=880000001,
        campaign_id=uuid4(),
        target_kind=TargetKind.TRANSLATION_GROUP,
        translation_group_id=uuid4(),
        translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


class TestChannelTargetResolution:
    @pytest.mark.asyncio
    async def test_authorized_and_sendable_resolves_ready(self) -> None:
        target = _channel_target()
        auth = _FakeAuthorization()
        [resolved] = await resolve_target(target, owner_discord_user_id=1, authorization=auth)
        assert resolved.is_ready
        assert resolved.discord_channel_id == 111

    @pytest.mark.asyncio
    async def test_unauthorized_guild_blocks(self) -> None:
        target = _channel_target()
        auth = _FakeAuthorization(authorized_guilds=set())
        [resolved] = await resolve_target(target, owner_discord_user_id=1, authorization=auth)
        assert not resolved.is_ready
        assert resolved.blocked_reason is BlockReason.GUILD_NOT_AUTHORIZED

    @pytest.mark.asyncio
    async def test_bot_cannot_send_blocks(self) -> None:
        target = _channel_target()
        auth = _FakeAuthorization(sendable_channels=set())
        [resolved] = await resolve_target(target, owner_discord_user_id=1, authorization=auth)
        assert not resolved.is_ready
        assert resolved.blocked_reason is BlockReason.BOT_CANNOT_SEND

    @pytest.mark.asyncio
    async def test_authorization_is_always_rechecked_not_cached(self) -> None:
        """Creation-time authorization is never treated as permanent --
        resolving the same target twice must call the checker again both
        times, not reuse a cached result."""
        target = _channel_target()
        auth = _FakeAuthorization()
        await resolve_target(target, owner_discord_user_id=1, authorization=auth)
        await resolve_target(target, owner_discord_user_id=1, authorization=auth)
        assert auth.guild_checks == 2
        assert auth.channel_checks == 2


class TestTranslationGroupResolution:
    def _topology(self) -> TranslationGroupTopologySnapshot:
        return TranslationGroupTopologySnapshot(
            source_channel_id=100,
            variants=((uuid4(), 200), (uuid4(), 300)),
        )

    @pytest.mark.asyncio
    async def test_source_only_never_fans_out(self) -> None:
        topology = self._topology()
        target = _group_target(translation_publication_mode=TranslationPublicationMode.SOURCE_ONLY)
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            topology=topology,
        )
        assert len(resolved) == 1
        assert resolved[0].discord_channel_id == topology.source_channel_id
        assert resolved[0].language_profile_id is None

    @pytest.mark.asyncio
    async def test_existing_provider_never_fans_out(self) -> None:
        topology = self._topology()
        target = _group_target(
            translation_publication_mode=TranslationPublicationMode.EXISTING_PROVIDER
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            topology=topology,
        )
        assert len(resolved) == 1
        assert resolved[0].discord_channel_id == topology.source_channel_id

    @pytest.mark.asyncio
    async def test_did_translated_fanout_resolves_source_plus_all_variants(self) -> None:
        topology = self._topology()
        target = _group_target(
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            topology=topology,
        )
        assert len(resolved) == 3
        assert {d.discord_channel_id for d in resolved} == {100, 200, 300}

    @pytest.mark.asyncio
    async def test_selected_languages_only_resolves_the_chosen_subset(self) -> None:
        topology = self._topology()
        chosen_language = topology.variants[0][0]
        target = _group_target(
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(chosen_language,),
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            topology=topology,
        )
        assert len(resolved) == 1
        assert resolved[0].language_profile_id == chosen_language
        assert resolved[0].discord_channel_id == topology.variants[0][1]

    @pytest.mark.asyncio
    async def test_selected_languages_with_no_match_is_blocked(self) -> None:
        topology = self._topology()
        target = _group_target(
            translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            selected_language_profile_ids=(uuid4(),),
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            topology=topology,
        )
        assert len(resolved) == 1
        assert resolved[0].blocked_reason is BlockReason.NO_MATCHING_LANGUAGE_VARIANTS

    @pytest.mark.asyncio
    async def test_missing_topology_is_blocked_not_crashed(self) -> None:
        target = _group_target()
        resolved = await resolve_target(
            target, owner_discord_user_id=1, authorization=_FakeAuthorization(), topology=None
        )
        assert len(resolved) == 1
        assert resolved[0].blocked_reason is BlockReason.TRANSLATION_GROUP_NOT_FOUND

    @pytest.mark.asyncio
    async def test_unauthorized_guild_blocks_before_topology_is_consulted(self) -> None:
        target = _group_target()
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(authorized_guilds=set()),
            topology=self._topology(),
        )
        assert len(resolved) == 1
        assert resolved[0].blocked_reason is BlockReason.GUILD_NOT_AUTHORIZED


def _logical_group_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=880000001,
        campaign_id=uuid4(),
        target_kind=TargetKind.LOGICAL_GROUP,
        logical_group_id=uuid4(),
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


class TestLogicalGroupResolution:
    @pytest.mark.asyncio
    async def test_unauthorized_guild_blocks_before_any_expansion_is_consulted(self) -> None:
        from did.campaigns.logical_groups import LogicalGroupExpansion

        target = _logical_group_target()
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(authorized_guilds=set()),
            logical_group_expansion=LogicalGroupExpansion(discord_channel_ids=(111, 222)),
        )
        assert len(resolved) == 1
        assert resolved[0].blocked_reason is BlockReason.GUILD_NOT_AUTHORIZED

    @pytest.mark.asyncio
    async def test_missing_expansion_is_logical_group_not_found(self) -> None:
        target = _logical_group_target()
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            logical_group_expansion=None,
        )
        assert len(resolved) == 1
        assert resolved[0].blocked_reason is BlockReason.LOGICAL_GROUP_NOT_FOUND

    @pytest.mark.asyncio
    async def test_expansion_with_zero_channels_is_logical_group_empty(self) -> None:
        from did.campaigns.logical_groups import LogicalGroupExpansion

        target = _logical_group_target()
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(),
            logical_group_expansion=LogicalGroupExpansion(discord_channel_ids=()),
        )
        assert len(resolved) == 1
        assert resolved[0].blocked_reason is BlockReason.LOGICAL_GROUP_EMPTY

    @pytest.mark.asyncio
    async def test_every_expanded_channel_is_individually_re_authorized(self) -> None:
        from did.campaigns.logical_groups import LogicalGroupExpansion

        target = _logical_group_target()
        checker = _FakeAuthorization(sendable_channels={111})
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=checker,
            logical_group_expansion=LogicalGroupExpansion(discord_channel_ids=(111, 222)),
        )
        assert len(resolved) == 2
        by_channel = {dest.discord_channel_id: dest for dest in resolved}
        assert by_channel[111].is_ready is True
        assert by_channel[222].blocked_reason is BlockReason.BOT_CANNOT_SEND
        # bot_can_send is re-checked once per channel, never assumed from
        # one check applying to the whole group.
        assert checker.channel_checks == 2


class TestSimulationSummary:
    @pytest.mark.asyncio
    async def test_simulation_never_creates_deliveries_just_counts(self) -> None:
        topology = TranslationGroupTopologySnapshot(
            source_channel_id=100, variants=((uuid4(), 200),)
        )
        target = _group_target(
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=1,
            authorization=_FakeAuthorization(sendable_channels={100}),
            topology=topology,
        )
        summary = summarize_simulation(resolved)
        assert summary.total_destinations == 2
        assert summary.ready_destinations == 1
        assert summary.blocked_destinations == 1
        assert summary.blockers == {BlockReason.BOT_CANNOT_SEND.value: 1}
