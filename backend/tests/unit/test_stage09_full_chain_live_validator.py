from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _stage09_full_chain_impl import _reset  # noqa: E402
from validate_discord_live_stage09_full_chain import sanitized_failure_reason  # noqa: E402


class _FakeConnection:
    def __init__(self) -> None:
        self.translation_routes_exist = True
        self.resource_language_policies_exist = True
        self.tenant_purge_enabled = False
        self.statements: list[str] = []

    async def execute(self, statement: Any, parameters: dict[str, Any] | None = None) -> None:
        del parameters
        sql = str(statement)
        self.statements.append(sql)
        if sql.startswith("SELECT set_config('app.tenant_purge_in_progress'"):
            self.tenant_purge_enabled = True
        if sql.startswith("DELETE FROM translation_routes"):
            self.translation_routes_exist = False
        if sql.startswith("DELETE FROM resource_language_policies"):
            self.resource_language_policies_exist = False
        if sql.startswith("DELETE FROM translation_group_languages"):
            assert not self.translation_routes_exist, (
                "translation_routes must be deleted before their RESTRICT-referenced "
                "translation_group_languages"
            )
        if sql.startswith("DELETE FROM language_profiles"):
            assert not self.resource_language_policies_exist, (
                "resource_language_policies must be deleted before their composite "
                "SET NULL reference attempts to null a non-null guild_id"
            )
        if sql.startswith("DELETE FROM guild_installations"):
            assert self.tenant_purge_enabled, (
                "the append-only plan snapshot guard may only be bypassed by an explicit "
                "transaction-local tenant purge"
            )


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeEngine:
    def __init__(self) -> None:
        self.connection = _FakeConnection()

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self.connection)


@pytest.mark.asyncio
async def test_reset_removes_stage08_dependents_before_their_references() -> None:
    engine = _FakeEngine()

    await _reset(engine, 111, 222)

    route_index = next(
        index
        for index, statement in enumerate(engine.connection.statements)
        if statement.startswith("DELETE FROM translation_routes")
    )
    language_index = next(
        index
        for index, statement in enumerate(engine.connection.statements)
        if statement.startswith("DELETE FROM translation_group_languages")
    )
    assert route_index < language_index
    policy_index = next(
        index
        for index, statement in enumerate(engine.connection.statements)
        if statement.startswith("DELETE FROM resource_language_policies")
    )
    profile_index = next(
        index
        for index, statement in enumerate(engine.connection.statements)
        if statement.startswith("DELETE FROM language_profiles")
    )
    assert policy_index < profile_index
    purge_index = next(
        index
        for index, statement in enumerate(engine.connection.statements)
        if statement.startswith("SELECT set_config('app.tenant_purge_in_progress'")
    )
    installation_index = next(
        index
        for index, statement in enumerate(engine.connection.statements)
        if statement.startswith("DELETE FROM guild_installations")
    )
    assert purge_index < installation_index


def test_blocked_reason_redacts_live_identifiers_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-token-value-that-must-not-survive"
    snowflake = "123456789012345678"
    identifier = "4ca1cf38-ee0d-46bf-a1f2-71912a91c252"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", token)

    reason = sanitized_failure_reason(RuntimeError(f"guild={snowflake} row={identifier} {token}"))

    assert token not in reason
    assert snowflake not in reason
    assert identifier not in reason
    assert "[REDACTED]" in reason
    assert "[REDACTED_DISCORD_ID]" in reason
    assert "[REDACTED_UUID]" in reason
    assert os.environ["DISCORD_BOT_TOKEN"] == token
