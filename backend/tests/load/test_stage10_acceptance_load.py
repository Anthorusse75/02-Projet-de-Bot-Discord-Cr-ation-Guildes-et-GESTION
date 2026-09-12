from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import pytest

from did.application.translation.service import RoleCapacityEngine
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

GUILD = 731010101010101001
OWNER = 731010101010101002
MEMBER = 731010101010101003
NOW = datetime(2026, 9, 11, tzinfo=UTC)


def _write_report(report: dict[str, object]) -> None:
    configured = os.environ.get("DID_STAGE10_LOAD_REPORT")
    if configured is None:
        return
    path = Path(configured)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def test_representative_500_channel_250_role_overwrite_boundary_is_bounded() -> None:
    freshness = FreshnessSnapshot(FreshnessState.FRESH, "LOAD", 1, NOW, NOW, NOW)
    roles = [RoleSnapshot(GUILD, GUILD, "@everyone", 0, 1 << 10, False, freshness)]
    roles.extend(
        RoleSnapshot(GUILD, GUILD + index, f"role-{index}", index, 1 << 11, False, freshness)
        for index in range(1, 250)
    )
    channels: list[ChannelSnapshot] = []
    for channel_index in range(500):
        channel_id = GUILD + 1_000 + channel_index
        overwrite_count = 1_000 if channel_index == 0 else 12
        overwrites = tuple(
            OverwriteSnapshot(
                GUILD,
                channel_id,
                roles[(overwrite_index % 249) + 1].role_id
                if overwrite_index < 249
                else GUILD + 10_000 + overwrite_index,
                0 if overwrite_index < 249 else 1,
                1 << 10,
                0,
                NOW,
            )
            for overwrite_index in range(overwrite_count)
        )
        channels.append(
            ChannelSnapshot(
                GUILD,
                channel_id,
                ChannelType.GUILD_TEXT,
                channel_index,
                None,
                f"channel-{channel_index}",
                overwrites,
                True,
                ObservabilityState.VISIBLE,
                freshness,
            )
        )
    snapshot = GuildSnapshot(
        GUILD,
        OWNER,
        tuple(roles),
        tuple(channels),
        CoverageSnapshot(
            GUILD,
            CoverageMode.FULL,
            FreshnessState.FRESH,
            "LOAD",
            1,
            known_channels=500,
            visible_channels=500,
            known_roles=250,
            members_complete=True,
            overwrites_complete=True,
            threads_complete=True,
            gateway_continuity="CONNECTED",
        ),
        freshness,
    )
    member = MemberSnapshot(
        GUILD,
        MEMBER,
        tuple(role.role_id for role in roles[1:]),
        True,
        freshness,
    )

    evaluator = PermissionEvaluator()
    started = perf_counter()
    decisions = [
        evaluator.evaluate(guild=snapshot, member=member, resource=channel) for channel in channels
    ]
    duration = perf_counter() - started
    capacity = RoleCapacityEngine()

    assert len(decisions) == 500
    assert all(decision.status is DecisionStatus.COMPLETE for decision in decisions)
    assert len(channels[0].overwrites) == 1_000
    assert capacity.role_budget(current_count=249, required_bindings=1, reusable_bindings=0).allowed
    assert not capacity.role_budget(
        current_count=250, required_bindings=1, reusable_bindings=0
    ).allowed
    assert capacity.overwrite_budget(current_count=999, proposed_delta=1).allowed
    assert not capacity.overwrite_budget(current_count=1_000, proposed_delta=1).allowed
    assert duration < 5.0
    _write_report(
        {
            "scenario": "stage10-representative-guild",
            "channels": len(channels),
            "roles": len(roles),
            "maximum_overwrites_on_one_channel": len(channels[0].overwrites),
            "permission_evaluations": len(decisions),
            "duration_seconds": round(duration, 6),
            "threshold_seconds": 5.0,
            "network_calls": 0,
            "database_calls": 0,
        }
    )
