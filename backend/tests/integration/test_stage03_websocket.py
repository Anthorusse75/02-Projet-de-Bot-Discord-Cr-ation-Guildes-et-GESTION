import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI

from did.api.dependencies import ServiceContainer
from did.api.runtime_cache import guild_events_socket
from did.application.auth.service import AuthorizationDenied
from did.infrastructure.runtime_redis import TenantPubSub
from did.oauth.stores import SessionData
from did.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.api, pytest.mark.security]

GUILD_A = 330303030303030301
GUILD_B = 330303030303030302
USER = 330303030303030303


class FakeSessions:
    def __init__(self) -> None:
        self.revoked = False

    async def load(self, session_id: str | None) -> SessionData | None:
        if session_id != "authorized-session" or self.revoked:
            return None
        now = datetime.now(UTC)
        return SessionData(
            session_id=session_id,
            discord_user_id=USER,
            csrf_token="csrf",
            active_guild_id=GUILD_A,
            created_at=now,
            last_seen_at=now,
            absolute_expires_at=now + timedelta(hours=1),
            policy_version=1,
        )


class FakeAuthorization:
    def __init__(self, denied_guild: int | None = None) -> None:
        self.denied_guild = denied_guild
        self.denied = False
        self.external_denied = False
        self.discovery_calls = 0

    async def authorize(self, *, guild_id: int, **_: object) -> None:
        if guild_id == self.denied_guild or self.denied:
            raise AuthorizationDenied()

    async def discovery(self, _: int, guild_id: int, *, force_refresh: bool) -> None:
        assert guild_id in {GUILD_A, GUILD_B}
        assert force_refresh is True
        self.discovery_calls += 1
        if self.external_denied:
            raise AuthorizationDenied()


class InstrumentedPubSub:
    def __init__(self) -> None:
        self.subscriptions: list[int] = []

    async def subscribe(self, guild_id: int):
        self.subscriptions.append(guild_id)
        yield {"guild_id": str(guild_id), "event": f"guild-{guild_id}"}
        await asyncio.Event().wait()


class GatedPubSub:
    def __init__(self) -> None:
        self.subscribed = asyncio.Event()
        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def subscribe(self, guild_id: int):
        self.subscribed.set()
        while True:
            event = await self.events.get()
            yield {**event, "guild_id": str(guild_id)}


class InstrumentedWebSocket:
    def __init__(self, application: FastAPI, *, authenticated: bool = True) -> None:
        self.app = application
        self.cookies = {"did_session": "authorized-session"} if authenticated else {}
        self.accepted = False
        self.closed_code: int | None = None
        self.sent: list[dict[str, Any]] = []
        self.receive_calls = 0

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int) -> None:
        self.closed_code = code

    async def send_json(self, event: dict[str, Any]) -> None:
        self.sent.append(event)

    async def receive(self) -> dict[str, str]:
        self.receive_calls += 1
        if self.receive_calls == 1:
            await asyncio.sleep(0.05)
            return {"type": "websocket.receive"}
        return {"type": "websocket.disconnect"}


class HoldingWebSocket(InstrumentedWebSocket):
    async def receive(self) -> dict[str, str]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def websocket_application(
    pubsub: object,
    *,
    denied_guild: int | None = None,
    sessions: FakeSessions | None = None,
    authorization: FakeAuthorization | None = None,
    authorization_lease_seconds: float = 300.0,
) -> FastAPI:
    application = FastAPI()
    application.state.services = ServiceContainer(
        settings=Settings(
            _env_file=None,
            websocket_authorization_max_staleness_seconds=authorization_lease_seconds,
        ),
        repository=None,  # type: ignore[arg-type]
        auth=None,  # type: ignore[arg-type]
        authorization=authorization or FakeAuthorization(denied_guild),  # type: ignore[arg-type]
        installations=None,  # type: ignore[arg-type]
        sessions=sessions or FakeSessions(),  # type: ignore[arg-type]
        runtime_repository=None,  # type: ignore[arg-type]
        hot_cache=None,  # type: ignore[arg-type]
        pubsub=pubsub,  # type: ignore[arg-type]
        stage04_repository=None,  # type: ignore[arg-type]
    )
    return application


async def test_websocket_a_and_b_never_receive_each_others_events() -> None:
    pubsub = InstrumentedPubSub()
    application = websocket_application(pubsub)
    websocket_a = InstrumentedWebSocket(application)
    websocket_b = InstrumentedWebSocket(application)
    await asyncio.gather(
        guild_events_socket(websocket_a, str(GUILD_A)),  # type: ignore[arg-type]
        guild_events_socket(websocket_b, str(GUILD_B)),  # type: ignore[arg-type]
    )
    assert websocket_a.accepted and websocket_b.accepted
    assert websocket_a.sent == [{"guild_id": str(GUILD_A), "event": f"guild-{GUILD_A}"}]
    assert websocket_b.sent == [{"guild_id": str(GUILD_B), "event": f"guild-{GUILD_B}"}]
    assert pubsub.subscriptions == [GUILD_A, GUILD_B]


async def test_websocket_authorization_and_authentication_are_backend_enforced() -> None:
    pubsub = InstrumentedPubSub()
    application = websocket_application(pubsub, denied_guild=GUILD_B)
    denied = InstrumentedWebSocket(application)
    await guild_events_socket(denied, str(GUILD_B))  # type: ignore[arg-type]
    assert denied.accepted is False
    assert denied.closed_code == 4403

    anonymous = InstrumentedWebSocket(application, authenticated=False)
    await guild_events_socket(anonymous, str(GUILD_A))  # type: ignore[arg-type]
    assert anonymous.accepted is False
    assert anonymous.closed_code == 4401


def test_forged_tenant_payload_is_rejected_even_on_expected_transport() -> None:
    raw: Any = f'{{"guild_id":"{GUILD_B}","event":"forged"}}'
    assert TenantPubSub.decode_for_guild(GUILD_A, raw) is None


async def test_websocket_revoked_session_is_closed_before_next_payload() -> None:
    sessions = FakeSessions()
    pubsub = GatedPubSub()
    application = websocket_application(pubsub, sessions=sessions)
    websocket = HoldingWebSocket(application)
    task = asyncio.create_task(
        guild_events_socket(websocket, str(GUILD_A))  # type: ignore[arg-type]
    )
    await asyncio.wait_for(pubsub.subscribed.wait(), timeout=1)
    sessions.revoked = True
    await pubsub.events.put({"event": "must-not-leak"})
    await asyncio.wait_for(task, timeout=1)
    assert websocket.accepted is True
    assert websocket.closed_code == 4401
    assert websocket.sent == []


async def test_websocket_revoked_rbac_is_closed_before_next_payload() -> None:
    authorization = FakeAuthorization()
    pubsub = GatedPubSub()
    application = websocket_application(pubsub, authorization=authorization)
    websocket = HoldingWebSocket(application)
    task = asyncio.create_task(
        guild_events_socket(websocket, str(GUILD_A))  # type: ignore[arg-type]
    )
    await asyncio.wait_for(pubsub.subscribed.wait(), timeout=1)
    authorization.denied = True
    await pubsub.events.put({"event": "must-not-leak"})
    await asyncio.wait_for(task, timeout=1)
    assert websocket.closed_code == 4403
    assert websocket.sent == []


async def test_websocket_forces_external_authorization_at_bounded_lease() -> None:
    authorization = FakeAuthorization()
    authorization.external_denied = True
    pubsub = GatedPubSub()
    application = websocket_application(
        pubsub,
        authorization=authorization,
        authorization_lease_seconds=1.0,
    )
    websocket = HoldingWebSocket(application)
    await asyncio.wait_for(
        guild_events_socket(websocket, str(GUILD_A)),  # type: ignore[arg-type]
        timeout=2,
    )
    assert websocket.accepted is True
    assert websocket.closed_code == 4403
    assert authorization.discovery_calls == 1
    assert websocket.sent == []
