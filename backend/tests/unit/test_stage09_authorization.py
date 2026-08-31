"""Unit tests for the Stage 09 create-time Guild authorization service (1E,
external-review finding, third remediation pass): a campaign target or
trigger source binding must never be persisted for a Guild the caller is
not currently authorized for, and never for a campaign/trigger the caller
does not actually own -- neither is trusted from a caller-supplied id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from did.campaigns.authorization import (
    CampaignNotOwnedByCaller,
    GuildNotAuthorizedForCampaign,
    create_authorized_campaign_target,
    create_authorized_trigger_source,
)
from did.domain.campaigns import CampaignTarget, TargetKind, TriggerSourceBinding
from did.domain.campaigns import TriggerSourceScopeKind as ScopeKind

pytestmark = [pytest.mark.security]

OWNER_A = 111
OWNER_B = 222
GUILD_A = 990000001  # owner A is authorized here
GUILD_B = 990000002  # owner A is NOT authorized here


class _FakeChecker:
    def __init__(self, *, authorized_guilds: set[int]) -> None:
        self.authorized_guilds = authorized_guilds
        self.guild_checks: list[tuple[int, int]] = []

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        self.guild_checks.append((guild_id, owner_discord_user_id))
        return guild_id in self.authorized_guilds

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        return True


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


def _target(**overrides: object) -> CampaignTarget:
    fields: dict[str, object] = dict(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=uuid4(),
        target_kind=TargetKind.CHANNEL,
        discord_channel_id=555,
    )
    fields.update(overrides)
    return CampaignTarget(**fields)


class TestCreateAuthorizedCampaignTarget:
    async def test_authorized_owner_can_attach_a_target_to_their_own_campaign(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        target = _target(campaign_id=campaign_id, guild_id=GUILD_A)

        await create_authorized_campaign_target(
            repository=repo,
            checker=checker,
            owner_discord_user_id=OWNER_A,
            target=target,
        )
        assert repo.created_targets == [target]
        assert checker.guild_checks == [(GUILD_A, OWNER_A)]

    async def test_unauthorized_guild_is_rejected_before_persistence(self) -> None:
        campaign_id = uuid4()
        repo = _FakeRepository(owned_campaigns={(OWNER_A, campaign_id): {"id": campaign_id}})
        checker = _FakeChecker(authorized_guilds={GUILD_A})  # GUILD_B not authorized
        target = _target(campaign_id=campaign_id, guild_id=GUILD_B)

        with pytest.raises(GuildNotAuthorizedForCampaign):
            await create_authorized_campaign_target(
                repository=repo,
                checker=checker,
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
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        target = _target(campaign_id=campaign_id, guild_id=GUILD_A)

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_campaign_target(
                repository=repo,
                checker=checker,
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []
        # The Guild authorization check must never even run for a resource
        # the caller does not own -- ownership is checked first.
        assert checker.guild_checks == []

    async def test_nonexistent_campaign_is_rejected_identically_to_foreign_campaign(self) -> None:
        repo = _FakeRepository()
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        target = _target(campaign_id=uuid4(), guild_id=GUILD_A)

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_campaign_target(
                repository=repo,
                checker=checker,
                owner_discord_user_id=OWNER_A,
                target=target,
            )
        assert repo.created_targets == []


class TestCreateAuthorizedTriggerSource:
    async def test_authorized_owner_can_bind_a_source_to_their_own_trigger(self) -> None:
        trigger_id = uuid4()
        repo = _FakeRepository(owned_triggers={(OWNER_A, trigger_id): {"id": trigger_id}})
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        await create_authorized_trigger_source(
            repository=repo,
            checker=checker,
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
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_trigger_source(
                repository=repo,
                checker=checker,
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
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_B,
            trigger_id=trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        with pytest.raises(GuildNotAuthorizedForCampaign):
            await create_authorized_trigger_source(
                repository=repo,
                checker=checker,
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
        checker = _FakeChecker(authorized_guilds={GUILD_A})
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=other_trigger_id,
            source_scope_kind=ScopeKind.GUILD,
        )

        with pytest.raises(CampaignNotOwnedByCaller):
            await create_authorized_trigger_source(
                repository=repo,
                checker=checker,
                owner_discord_user_id=OWNER_A,
                trigger_id=trigger_id,
                binding=binding,
            )
        assert repo.created_trigger_sources == []
