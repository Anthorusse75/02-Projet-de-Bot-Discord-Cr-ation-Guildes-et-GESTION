"""Unit tests for the Stage 09 create-time Guild authorization service (1E,
external-review findings across the third and fourth remediation passes): a
campaign target or trigger source binding must never be persisted for a
Guild the caller is not currently authorized for, and never for a
campaign/trigger the caller does not actually own, a channel/category/
Translation Group belonging to a different Guild, or the wrong resource
type -- none of these are trusted from a caller-supplied id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from did.campaigns.authorization import (
    CampaignNotOwnedByCaller,
    ForeignOrUnknownResourceError,
    GuildNotAuthorizedForCampaign,
    WrongResourceTypeError,
    create_authorized_campaign_target,
    create_authorized_trigger_source,
)
from did.domain.campaigns import (
    CampaignTarget,
    TargetKind,
    TranslationPublicationMode,
    TriggerSourceBinding,
)
from did.domain.campaigns import TriggerSourceScopeKind as ScopeKind
from did.domain.read_model.models import ChannelType

pytestmark = [pytest.mark.security]

OWNER_A = 111
OWNER_B = 222
GUILD_A = 990000001  # owner A is authorized here
GUILD_B = 990000002  # owner A is NOT authorized here

CHANNEL_IN_A = 555
CHANNEL_IN_B = 556
CATEGORY_IN_A = 655
TRANSLATION_GROUP_IN_A = uuid4()
TRANSLATION_GROUP_IN_B = uuid4()
LOGICAL_GROUP_IN_A = uuid4()
LOGICAL_GROUP_IN_B = uuid4()


class _FakeChecker:
    """Fake implementing the full CampaignGuildAuthorizationChecker surface
    the create-time service now depends on -- deliberately not the real
    Stage04/Stage08-backed implementation, so these tests stay fast/
    isolated; the real implementation's own wiring is covered by
    test_stage09_target_resolution.py and the Stage04/Stage08 test suites
    it composes."""

    def __init__(
        self,
        *,
        authorized_guilds: set[int],
        channels_by_guild: dict[int, dict[int, ChannelType]] | None = None,
        sendable_channels: set[int] | None = None,
        translation_groups_by_guild: dict[int, set[UUID]] | None = None,
        logical_groups_by_guild: dict[int, set[UUID]] | None = None,
    ) -> None:
        self.authorized_guilds = authorized_guilds
        self.channels_by_guild = channels_by_guild or {}
        self.sendable_channels = sendable_channels
        self.translation_groups_by_guild = translation_groups_by_guild or {}
        self.logical_groups_by_guild = logical_groups_by_guild or {}
        self.guild_checks: list[tuple[int, int]] = []
        self.channel_membership_checks: list[tuple[int, int]] = []
        self.bot_can_send_checks: list[tuple[int, int]] = []
        self.translation_group_checks: list[tuple[int, UUID]] = []
        self.logical_group_checks: list[tuple[int, UUID]] = []

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        self.guild_checks.append((guild_id, owner_discord_user_id))
        return guild_id in self.authorized_guilds

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        self.bot_can_send_checks.append((guild_id, discord_channel_id))
        if self.sendable_channels is None:
            return True
        return discord_channel_id in self.sendable_channels

    async def channel_belongs_to_guild(self, *, guild_id: int, discord_channel_id: int) -> bool:
        self.channel_membership_checks.append((guild_id, discord_channel_id))
        return discord_channel_id in self.channels_by_guild.get(guild_id, {})

    async def resource_type(self, *, guild_id: int, discord_resource_id: int) -> ChannelType | None:
        return self.channels_by_guild.get(guild_id, {}).get(discord_resource_id)

    async def translation_group_belongs_to_guild(
        self, *, guild_id: int, translation_group_id: UUID
    ) -> bool:
        self.translation_group_checks.append((guild_id, translation_group_id))
        return translation_group_id in self.translation_groups_by_guild.get(guild_id, set())

    async def logical_group_belongs_to_guild(
        self, *, guild_id: int, logical_group_id: UUID
    ) -> bool:
        self.logical_group_checks.append((guild_id, logical_group_id))
        return logical_group_id in self.logical_groups_by_guild.get(guild_id, set())


def _default_checker(**overrides: object) -> _FakeChecker:
    fields: dict[str, object] = dict(
        authorized_guilds={GUILD_A},
        channels_by_guild={
            GUILD_A: {
                CHANNEL_IN_A: ChannelType.GUILD_TEXT,
                CATEGORY_IN_A: ChannelType.GUILD_CATEGORY,
            },
            GUILD_B: {CHANNEL_IN_B: ChannelType.GUILD_TEXT},
        },
        translation_groups_by_guild={
            GUILD_A: {TRANSLATION_GROUP_IN_A},
            GUILD_B: {TRANSLATION_GROUP_IN_B},
        },
        logical_groups_by_guild={
            GUILD_A: {LOGICAL_GROUP_IN_A},
            GUILD_B: {LOGICAL_GROUP_IN_B},
        },
    )
    fields.update(overrides)
    return _FakeChecker(**fields)  # type: ignore[arg-type]


@dataclass
class _FakeRepository:
    """Only implements the handful of CampaignsRepository methods the
    create-time authorization service actually calls -- deliberately not the
    real Postgres-backed repository, since this is pure orchestration-logic
    coverage; the real repository's owner-scoped RLS query itself is proven
    against real PostgreSQL in test_stage09_campaigns_postgres.py."""

    owned_campaigns: dict[tuple[int, UUID], dict[str, object]] = field(default_factory=dict)
    owned_triggers: dict[tuple[int, UUID], dict[str, object]] = field(default_factory=dict)
    created_targets: list[CampaignTarget] = field(default_factory=list)
    created_trigger_sources: list[TriggerSourceBinding] = field(default_factory=list)

    async def get_campaign(
        self, owner_discord_user_id: int, campaign_id: UUID
    ) -> dict[str, object] | None:
        return self.owned_campaigns.get((owner_discord_user_id, campaign_id))

    async def get_trigger(
        self, owner_discord_user_id: int, trigger_id: UUID
    ) -> dict[str, object] | None:
        return self.owned_triggers.get((owner_discord_user_id, trigger_id))

    async def create_target(self, target: CampaignTarget) -> None:
        self.created_targets.append(target)

    async def create_trigger_source(self, binding: TriggerSourceBinding) -> None:
        self.created_trigger_sources.append(binding)


def _channel_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=uuid4(),
        target_kind=TargetKind.CHANNEL,
        discord_channel_id=CHANNEL_IN_A,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


def _group_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=uuid4(),
        target_kind=TargetKind.TRANSLATION_GROUP,
        translation_group_id=TRANSLATION_GROUP_IN_A,
        translation_publication_mode=TranslationPublicationMode.SOURCE_ONLY,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


def _logical_group_target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=uuid4(),
        target_kind=TargetKind.LOGICAL_GROUP,
        logical_group_id=LOGICAL_GROUP_IN_A,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)  # type: ignore[arg-type]


class TestCreateAuthorizedCampaignTarget:
    async def test_authorized_owner_can_attach_a_channel_target_to_their_own_campaign(
        self,
    ) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _channel_target(campaign_id=campaign_id)

        result = await create_authorized_campaign_target(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            target=target,
        )
        assert repo.created_targets == [target]
        assert result.target == target
        assert result.bot_send_preflight_ok is True
        assert checker.guild_checks == [(GUILD_A, OWNER_A)]
        assert checker.channel_membership_checks == [(GUILD_A, CHANNEL_IN_A)]

    async def test_unauthorized_guild_is_rejected_before_persistence(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()  # GUILD_B not authorized
        target = _channel_target(
            campaign_id=campaign_id, guild_id=GUILD_B, discord_channel_id=CHANNEL_IN_B
        )

        with pytest.raises(GuildNotAuthorizedForCampaign):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_cannot_attach_a_target_to_another_owners_campaign(self) -> None:
        """Cross-owner attack: owner A tries to attach a target to a
        campaign_id that actually belongs to owner B. The RLS-scoped
        get_campaign lookup (real behavior proven against PostgreSQL
        elsewhere) returns None for a foreign campaign -- this must be
        rejected before the Guild authorization check ever runs, and never
        discloses whether the campaign_id exists at all."""
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_B, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _channel_target(campaign_id=campaign_id)

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []
        # The Guild authorization check must never even run for a resource
        # the caller does not own -- ownership is checked first.
        assert checker.guild_checks == []

    async def test_nonexistent_campaign_is_rejected_identically_to_foreign_campaign(self) -> None:
        repo = _FakeRepository()
        checker = _default_checker()
        target = _channel_target(campaign_id=uuid4())

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_guild_a_authorized_but_channel_actually_belongs_to_guild_b_is_rejected(
        self,
    ) -> None:
        """Owner A is authorized for GUILD_A and declares a target for
        GUILD_A, but supplies a discord_channel_id that Stage04's real
        topology shows belongs to GUILD_B, not GUILD_A -- must be rejected
        even though the Guild-authorization check alone would have passed."""
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _channel_target(campaign_id=campaign_id, discord_channel_id=CHANNEL_IN_B)

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_foreign_or_nonexistent_channel_is_rejected(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _channel_target(campaign_id=campaign_id, discord_channel_id=999999999)

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_bot_lacking_send_messages_is_a_non_blocking_preflight_not_a_rejection(
        self,
    ) -> None:
        """External-review finding (fourth remediation pass): bot-send
        capability is explicitly NOT a create-time blocker (see the module
        docstring) -- REQ-MSG-003 places the hard enforcement point at
        delivery time. Creation succeeds, but the preflight result is
        returned so a caller/UI can warn immediately."""
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker(sendable_channels=set())  # bot can send nowhere
        target = _channel_target(campaign_id=campaign_id)

        result = await create_authorized_campaign_target(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            target=target,
        )
        assert repo.created_targets == [target]
        assert result.bot_send_preflight_ok is False

    async def test_authorized_owner_can_attach_a_translation_group_target(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _group_target(campaign_id=campaign_id)

        result = await create_authorized_campaign_target(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            target=target,
        )
        assert repo.created_targets == [target]
        assert result.bot_send_preflight_ok is None  # not applicable to TRANSLATION_GROUP
        assert checker.translation_group_checks == [(GUILD_A, TRANSLATION_GROUP_IN_A)]

    async def test_guild_a_authorized_but_translation_group_belongs_to_guild_b_is_rejected(
        self,
    ) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _group_target(campaign_id=campaign_id, translation_group_id=TRANSLATION_GROUP_IN_B)

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_foreign_or_nonexistent_translation_group_is_rejected(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _group_target(campaign_id=campaign_id, translation_group_id=uuid4())

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_authorized_owner_can_attach_a_logical_group_target_to_their_own_campaign(
        self,
    ) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _logical_group_target(campaign_id=campaign_id)

        result = await create_authorized_campaign_target(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            target=target,
        )
        assert result.target is target
        assert repo.created_targets == [target]
        assert checker.logical_group_checks == [(GUILD_A, LOGICAL_GROUP_IN_A)]

    async def test_guild_a_authorized_but_logical_group_belongs_to_guild_b_is_rejected(
        self,
    ) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _logical_group_target(campaign_id=campaign_id, logical_group_id=LOGICAL_GROUP_IN_B)

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []

    async def test_foreign_or_nonexistent_logical_group_is_rejected(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _default_checker()
        target = _logical_group_target(campaign_id=campaign_id, logical_group_id=uuid4())

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_campaign_target(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []


class TestCreateAuthorizedTriggerSource:
    async def test_authorized_owner_can_bind_a_guild_scoped_source_to_their_own_trigger(
        self,
    ) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        result = await create_authorized_trigger_source(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            trigger_id=trigger_id,
            binding=binding,
        )
        assert repo.created_trigger_sources == [binding]
        assert result.binding == binding

    async def test_authorized_owner_can_bind_a_channel_scoped_source(self) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.CHANNEL,
            discord_resource_id=CHANNEL_IN_A,
        )

        await create_authorized_trigger_source(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            trigger_id=trigger_id,
            binding=binding,
        )
        assert repo.created_trigger_sources == [binding]

    async def test_authorized_owner_can_bind_a_category_scoped_source(self) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.CATEGORY,
            discord_resource_id=CATEGORY_IN_A,
        )

        await create_authorized_trigger_source(
            repository=repo,  # type: ignore[arg-type]
            checker=checker,  # type: ignore[arg-type]
            owner_discord_user_id=OWNER_A,
            trigger_id=trigger_id,
            binding=binding,
        )
        assert repo.created_trigger_sources == [binding]

    async def test_cannot_bind_a_source_to_another_owners_trigger(self) -> None:
        """Cross-owner attack: owner A supplies a trigger_id that belongs to
        owner B. Must be rejected before any Guild check, never disclosing
        the trigger's existence."""
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_B, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []
        assert checker.guild_checks == []

    async def test_cross_guild_source_binding_requires_authorization_for_that_source_guild(
        self,
    ) -> None:
        """Owner A legitimately owns the trigger, but is trying to bind a
        source in GUILD_B, a Guild they are not authorized in -- an
        unauthorized event source must be rejected exactly like an
        unauthorized publish destination would be."""
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_B,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        with pytest.raises(GuildNotAuthorizedForCampaign):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []

    async def test_binding_trigger_id_mismatch_with_the_authorized_trigger_is_rejected(
        self,
    ) -> None:
        """A binding whose own trigger_id field disagrees with the trigger_id
        parameter used to load ownership must never be persisted -- this
        would otherwise let a caller "borrow" ownership proof for trigger X
        while writing a binding actually pointed at trigger Y."""
        trigger_id = uuid4()
        other_trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=other_trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []

    async def test_channel_scoped_binding_naming_a_guild_b_channel_is_rejected(self) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.CHANNEL,
            discord_resource_id=CHANNEL_IN_B,
        )

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []

    async def test_category_scoped_binding_naming_a_foreign_or_nonexistent_resource_is_rejected(
        self,
    ) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.CATEGORY,
            discord_resource_id=888888888,
        )

        with pytest.raises(ForeignOrUnknownResourceError):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []

    async def test_category_scoped_binding_naming_an_ordinary_channel_is_wrong_resource_type(
        self,
    ) -> None:
        """CATEGORY_IN_A exists, and belongs to GUILD_A, but the caller
        declared CATEGORY when CHANNEL_IN_A is actually a plain text
        channel -- resource membership alone is not enough, the type must
        also match."""
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.CATEGORY,
            discord_resource_id=CHANNEL_IN_A,  # a GUILD_TEXT channel, not a category
        )

        with pytest.raises(WrongResourceTypeError):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []

    async def test_channel_scoped_binding_naming_a_category_is_wrong_resource_type(self) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _default_checker()
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.CHANNEL,
            discord_resource_id=CATEGORY_IN_A,  # a GUILD_CATEGORY, not a plain channel
        )

        with pytest.raises(WrongResourceTypeError):
            await create_authorized_trigger_source(
                repository=repo,  # type: ignore[arg-type]
                checker=checker,  # type: ignore[arg-type]
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []
