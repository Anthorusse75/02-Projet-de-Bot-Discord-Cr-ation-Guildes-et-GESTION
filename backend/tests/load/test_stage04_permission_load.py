from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import pytest

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions import PermissionEvaluator
from did.permissions.models import DecisionStatus

pytestmark = pytest.mark.load


def test_permission_engine_deterministic_large_guild_benchmark() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    current = FreshnessSnapshot(FreshnessState.FRESH, "SYNTHETIC", 1, now, now, now)
    guild_id = 730303030303030301
    owner_id = 730303030303030302
    member_id = 730303030303030303
    roles = [RoleSnapshot(guild_id, guild_id, "@everyone", 0, 1 << 10, False, current)]
    for index in range(40):
        role_id = guild_id + 100 + index
        permissions = 1 << ((index % 46) + 6)
        roles.append(
            RoleSnapshot(guild_id, role_id, f"role-{index}", index + 1, permissions, False, current)
        )
    member_roles = tuple(role.role_id for role in roles[1:])
    channels: list[ChannelSnapshot] = []
    for channel_index in range(400):
        channel_id = guild_id + 1000 + channel_index
        overwrites = tuple(
            OverwriteSnapshot(
                guild_id,
                channel_id,
                roles[role_index + 1].role_id,
                0,
                1 << ((role_index + channel_index) % 46),
                1 << ((role_index + channel_index + 1) % 46),
                now,
            )
            for role_index in range(12)
        )
        channels.append(
            ChannelSnapshot(
                guild_id,
                channel_id,
                ChannelType.GUILD_TEXT,
                channel_index,
                None,
                f"channel-{channel_index}",
                overwrites,
                True,
                ObservabilityState.VISIBLE,
                current,
            )
        )
    snapshot = GuildSnapshot(
        guild_id,
        owner_id,
        tuple(roles),
        tuple(channels),
        CoverageSnapshot(
            guild_id,
            CoverageMode.FULL,
            FreshnessState.FRESH,
            "SYNTHETIC",
            1,
            known_channels=len(channels),
            visible_channels=len(channels),
            known_roles=len(roles),
            members_complete=True,
            overwrites_complete=True,
            threads_complete=True,
            gateway_continuity="CONNECTED",
        ),
        current,
    )
    subject = MemberSnapshot(guild_id, member_id, member_roles, True, current)
    evaluator = PermissionEvaluator()

    started = perf_counter()
    decisions = [
        evaluator.evaluate(guild=snapshot, member=subject, resource=resource)
        for resource in channels
    ]
    duration = perf_counter() - started

    assert len(decisions) == 400
    assert all(decision.status is DecisionStatus.COMPLETE for decision in decisions)
    assert duration < 3.0
    print(
        "STAGE04_BENCHMARK "
        f"evaluations={len(decisions)} roles={len(roles)} overwrites_per_channel=12 "
        f"db_queries=0 duration_seconds={duration:.6f}"
    )
