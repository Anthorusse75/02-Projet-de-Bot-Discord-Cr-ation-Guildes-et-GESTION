"""Regression for the Stage08 live validator's sanitized capability-name propagation.

`scripts/validate_discord_live_stage08.py`'s own `validate_plan` raised
`LiveCapabilityBlocked` on a permission-only preflight failure without passing the
sanitized `capability.permission_missing.*` names through `capabilities=...`, so the
live report's `missing_capabilities` field stayed empty even when, e.g., MANAGE_CHANNELS
was genuinely missing. This test drives that exact code path with lightweight fakes
(no live Discord, no database) and asserts the sanitized names reach the exception.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from did.planning.preflight import PreflightResult  # noqa: E402
from validate_discord_live_stage05 import LiveCapabilityBlocked  # noqa: E402
from validate_discord_live_stage08 import validate_plan  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_manage_channels_preflight_failure_reaches_sanitized_capabilities() -> None:
    plan = {"guild_id": 1, "id": str(uuid4()), "state_version": 1}
    preflight = PreflightResult(
        allowed=False,
        errors=(
            "capability.permission_missing.manage_channels",
            "capability.permission_missing.manage_channels",
            "capability.permission_missing.view_channel",
        ),
    )
    planning = SimpleNamespace(validate=AsyncMock(return_value=({}, preflight)))
    authorization = SimpleNamespace(authorize_apply=AsyncMock(return_value=None))

    with pytest.raises(LiveCapabilityBlocked) as excinfo:
        await validate_plan(planning, authorization, plan, actor=1, key="test")

    assert excinfo.value.capabilities == ("MANAGE_CHANNELS", "VIEW_CHANNEL")
    for name in excinfo.value.capabilities:
        assert name.replace("_", "").isalpha() and name.isupper()


async def test_non_permission_preflight_failure_is_not_reclassified() -> None:
    plan = {"guild_id": 1, "id": str(uuid4()), "state_version": 1}
    preflight = PreflightResult(allowed=False, errors=("preflight.structure_stale",))
    planning = SimpleNamespace(validate=AsyncMock(return_value=({}, preflight)))
    authorization = SimpleNamespace(authorize_apply=AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match="live plan preflight failed"):
        await validate_plan(planning, authorization, plan, actor=1, key="test")


async def test_allowed_preflight_confirms_the_plan_and_does_not_raise() -> None:
    plan = {"guild_id": 1, "id": str(uuid4()), "state_version": 1}
    preflight = PreflightResult(allowed=True)
    confirmed = {"status": "CONFIRMED"}
    planning = SimpleNamespace(
        validate=AsyncMock(return_value=({"state_version": 2, "plan_hash": "h"}, preflight)),
        confirm=AsyncMock(return_value=confirmed),
    )
    authorization = SimpleNamespace(authorize_apply=AsyncMock(return_value=None))

    result = await validate_plan(planning, authorization, plan, actor=1, key="test")

    assert result == confirmed
    planning.confirm.assert_awaited_once()
