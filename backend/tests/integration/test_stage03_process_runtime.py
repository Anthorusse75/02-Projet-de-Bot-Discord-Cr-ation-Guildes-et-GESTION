import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from did import runtime
from did.api.runtime_cache import enqueue_channel_refresh
from did.domain.discord_runtime import (
    DiscordErrorKind,
    DiscordFailure,
    WorkloadJob,
    WorkloadPriority,
)
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.discord import DiscordAdapterError
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import RedisRuntimeWakeup
from did.infrastructure.runtime_repository import RuntimeRepository
from did.settings import Settings
from did.tenancy import TenantContext
from did.worker.io import DiscordWorkloadGovernor

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")
GUILD = 830303030303030301
CHANNEL = 830303030303030311
ACTOR = 830303030303030321


async def reset_runtime() -> tuple[RuntimeRepository, Any]:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("TRUNCATE users, guild_installations CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id, username) "
                    "VALUES (:actor, 'process-actor')"
                ),
                {"actor": ACTOR},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id, name, installation_status) "
                    "VALUES (:guild, 'Process Runtime', 'ACTIVE')"
                ),
                {"guild": GUILD},
            )
    finally:
        await admin.dispose()
    engine = create_database_engine(APP_URL, pool_size=4)
    return RuntimeRepository(create_session_factory(engine)), engine


def runtime_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr(APP_URL),
        database_admin_url=SecretStr(ADMIN_URL),
        redis_url=SecretStr(REDIS_URL),
        discord_bot_token=SecretStr("placeholder"),
        discord_worker_poll_seconds=0.05,
        discord_worker_recovery_seconds=0.1,
        reconcile_scheduler_poll_seconds=0.1,
        discord_runtime_routing_batch_size=32,
        discord_worker_dispatch_batch_size=32,
    )


class FakeDiscordClient:
    instances: ClassVar[list["FakeDiscordClient"]] = []

    def __init__(self, **_: object) -> None:
        self.logged_in = False
        self.closed = False
        self.instances.append(self)

    async def login(self, _: str) -> None:
        self.logged_in = True

    async def close(self) -> None:
        self.closed = True


class AdapterProbe:
    def __init__(self, *, unauthorized: bool = False) -> None:
        self.unauthorized = unauthorized
        self.channel_calls = 0
        self.role_calls = 0

    async def fetch_channels(self, guild_id: int) -> list[dict[str, object]]:
        assert guild_id == GUILD
        self.channel_calls += 1
        if self.unauthorized:
            raise DiscordAdapterError(
                DiscordFailure(DiscordErrorKind.UNAUTHORIZED, status_code=401)
            )
        return [
            {
                "channel_id": CHANNEL,
                "type": 0,
                "name": "persisted-by-real-worker",
                "topic": None,
                "parent_id": None,
                "position": 0,
                "nsfw": False,
                "flags": 0,
                "permission_overwrites": [],
            }
        ]

    async def fetch_roles(self, guild_id: int) -> list[dict[str, object]]:
        assert guild_id == GUILD
        self.role_calls += 1
        return [
            {
                "role_id": GUILD,
                "name": "@everyone",
                "position": 0,
                "permissions": 0,
                "managed": False,
                "color": 0,
                "hoist": False,
                "mentionable": False,
            }
        ]


class CapturingGovernor(DiscordWorkloadGovernor):
    instances: ClassVar[list["CapturingGovernor"]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.instances.append(self)


async def wait_until(
    predicate: Callable[[], Awaitable[bool]],
    *,
    process_task: asyncio.Task[None],
    max_wait_seconds: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + max_wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        if process_task.done():
            process_task.result()
        if await predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("real process runtime did not reach its durable terminal state")


@pytest.mark.parametrize("lose_wakeup", [False, True])
async def test_real_worker_process_consumes_and_publishes_with_wakeup_recovery(
    monkeypatch: pytest.MonkeyPatch, *, lose_wakeup: bool
) -> None:
    repository, engine = await reset_runtime()
    redis = create_redis_client(REDIS_URL)
    adapter = AdapterProbe()
    CapturingGovernor.instances.clear()
    FakeDiscordClient.instances.clear()
    monkeypatch.setattr(runtime.discord, "Client", FakeDiscordClient)
    monkeypatch.setattr(runtime, "DiscordPyStructureAdapter", lambda _: adapter)
    monkeypatch.setattr(runtime, "DiscordWorkloadGovernor", CapturingGovernor)
    try:
        await redis.flushdb()

        class AuthorizationProbe:
            async def authorize(self, **_: object) -> None:
                return None

        api_response = await enqueue_channel_refresh(
            str(GUILD),
            SimpleNamespace(discord_user_id=ACTOR),
            SimpleNamespace(
                authorization=AuthorizationProbe(),
                runtime_repository=repository,
            ),
        )
        job_id = UUID(api_response["job_id"])
        await RedisRuntimeWakeup(redis).signal_job(GUILD)
        if lose_wakeup:
            await redis.flushdb()

        stop = asyncio.Event()
        process = asyncio.create_task(
            runtime.run_process(
                "worker",
                configured_settings=runtime_settings(),
                external_stop_event=stop,
            )
        )

        async def completed_and_published() -> bool:
            async with tenant_transaction(
                create_session_factory(engine), TenantContext(GUILD)
            ) as session:
                state = await session.scalar(
                    text("SELECT status FROM discord_io_jobs WHERE job_id=:job"),
                    {"job": job_id},
                )
                unpublished = await session.scalar(
                    text("SELECT count(*) FROM discord_outbox WHERE status != 'PUBLISHED'")
                )
                persisted = await session.scalar(
                    text(
                        "SELECT count(*) FROM discord_channels_cache "
                        "WHERE channel_id=:channel AND name='persisted-by-real-worker'"
                    ),
                    {"channel": CHANNEL},
                )
            return state == "SUCCEEDED" and unpublished == 0 and persisted == 1

        await wait_until(completed_and_published, process_task=process)
        stop.set()
        await asyncio.wait_for(process, timeout=2)

        assert adapter.channel_calls == 1
        assert adapter.role_calls == 0
        assert len(CapturingGovernor.instances) == 1
        governor = CapturingGovernor.instances[0]
        assert governor.metrics.submitted == 1
        assert governor.metrics.completed == 1
        assert governor.metrics.peak_guild_concurrency == 1
        assert FakeDiscordClient.instances[0].logged_in is True
        assert FakeDiscordClient.instances[0].closed is True
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_real_scheduler_process_enqueues_without_discord_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, engine = await reset_runtime()
    redis = create_redis_client(REDIS_URL)
    FakeDiscordClient.instances.clear()
    monkeypatch.setattr(runtime.discord, "Client", FakeDiscordClient)
    try:
        await redis.flushdb()
        stop = asyncio.Event()
        process = asyncio.create_task(
            runtime.run_process(
                "scheduler",
                configured_settings=runtime_settings(),
                external_stop_event=stop,
            )
        )

        async def reconcile_enqueued() -> bool:
            async with tenant_transaction(
                create_session_factory(engine), TenantContext(GUILD)
            ) as session:
                count = await session.scalar(
                    text(
                        "SELECT count(*) FROM discord_io_jobs "
                        "WHERE workload_type='RECONCILE_STRUCTURE' AND status='PENDING'"
                    )
                )
            return count == 1

        await wait_until(reconcile_enqueued, process_task=process)
        stop.set()
        await asyncio.wait_for(process, timeout=2)
        assert FakeDiscordClient.instances == []
        assert await repository.runtime_job_guilds() == [GUILD]
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_real_worker_governor_halts_after_discord_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, engine = await reset_runtime()
    redis = create_redis_client(REDIS_URL)
    adapter = AdapterProbe(unauthorized=True)
    CapturingGovernor.instances.clear()
    monkeypatch.setattr(runtime.discord, "Client", FakeDiscordClient)
    monkeypatch.setattr(runtime, "DiscordPyStructureAdapter", lambda _: adapter)
    monkeypatch.setattr(runtime, "DiscordWorkloadGovernor", CapturingGovernor)
    try:
        await redis.flushdb()
        job = WorkloadJob(
            uuid4(),
            GUILD,
            "INITIAL_SYNC",
            "process-unauthorized",
            WorkloadPriority.USER_REFRESH,
            datetime.now(UTC),
        )
        await repository.enqueue_job(job, requested_by=None, correlation_id=uuid4())
        stop = asyncio.Event()
        process = asyncio.create_task(
            runtime.run_process(
                "worker",
                configured_settings=runtime_settings(),
                external_stop_event=stop,
            )
        )

        async def failed_and_halted() -> bool:
            if not CapturingGovernor.instances:
                return False
            async with tenant_transaction(
                create_session_factory(engine), TenantContext(GUILD)
            ) as session:
                state = await session.scalar(
                    text("SELECT status FROM discord_io_jobs WHERE job_id=:job"),
                    {"job": job.job_id},
                )
            return state == "FAILED" and CapturingGovernor.instances[0].halted

        await wait_until(failed_and_halted, process_task=process)
        stop.set()
        await asyncio.wait_for(process, timeout=2)
        governor = CapturingGovernor.instances[0]
        assert governor.halted is True
        assert governor.metrics.failed == 1
        assert adapter.channel_calls == 1
        assert adapter.role_calls == 0
    finally:
        await redis.aclose()
        await engine.dispose()
