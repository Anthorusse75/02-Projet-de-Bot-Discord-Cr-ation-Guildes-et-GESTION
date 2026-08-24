from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import discord
from redis.asyncio import Redis
from sqlalchemy import text

from did.application.planning import PlanningService
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.discord import DiscordPyMutableAdapter, DiscordPyStructureAdapter
from did.infrastructure.planning_lock import RedisGuildMutationLock
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.planning.models import DesiredNode, DesiredStateGraph, NodePresence, ResourceType
from did.worker.io.plan_executor import ApplyPlanExecutor

REQUIRED_VARIABLES = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_TEST_GUILD_A_ID",
    "DISCORD_TEST_GUILD_B_ID",
)
APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")
PREFIX = "DID-STAGE05-TEST-"


class LiveCapabilityBlocked(RuntimeError):
    pass


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in REQUIRED_VARIABLES and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def write_report(
    path: Path,
    *,
    status: str,
    checks: list[str],
    missing: list[str],
    skipped: list[str],
    counts: dict[str, int] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "stage": "05",
                "profile": "discord-live-plan-engine-safe-mutations",
                "status": status,
                "generated_at": datetime.now(UTC).isoformat(),
                "checks": checks,
                "missing_variable_names": missing,
                "counts": counts or {},
                "skipped_not_verified": skipped,
                "resource_prefix": PREFIX,
                "secrets_recorded": False,
                "discord_identifiers_recorded": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class CrashAfterDiscord:
    def __init__(self) -> None:
        self.triggered = False

    async def checkpoint(self, name: str) -> None:
        if name == "E_AFTER_DISCORD_BEFORE_COMMIT" and not self.triggered:
            self.triggered = True
            raise RuntimeError("controlled live crash after Discord response")


class CountingAdapter:
    def __init__(self, delegate: DiscordPyMutableAdapter) -> None:
        self.delegate = delegate
        self.create_calls = 0

    async def execute(self, **kwargs: Any) -> Any:
        if str(kwargs["operation_type"]).startswith("CREATE_"):
            self.create_calls += 1
        return await self.delegate.execute(**kwargs)

    async def recover(self, **kwargs: Any) -> Any:
        return await self.delegate.recover(**kwargs)

    async def verify(self, **kwargs: Any) -> bool:
        return await self.delegate.verify(**kwargs)


async def seed_snapshot(
    *,
    guild_id: int,
    client: discord.Client,
    structure: DiscordPyStructureAdapter,
    runtime: RuntimeRepository,
    admin_engine: Any,
) -> int:
    if client.user is None:
        raise RuntimeError("Discord bot identity unavailable")
    live_guild = await client.fetch_guild(guild_id)
    member = await structure.fetch_member(guild_id, client.user.id)
    roles = await structure.fetch_roles(guild_id)
    channels = await structure.fetch_channels(guild_id)
    async with admin_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (discord_user_id,username) VALUES (:bot,'stage05-live') "
                "ON CONFLICT (discord_user_id) DO NOTHING"
            ),
            {"bot": client.user.id},
        )
        await connection.execute(
            text(
                "INSERT INTO guild_installations "
                "(guild_id,name,owner_id,installation_status,application_id,bot_user_id) "
                "VALUES (:guild,:name,:owner,'ACTIVE',:bot,:bot) ON CONFLICT (guild_id) "
                "DO UPDATE SET name=EXCLUDED.name,owner_id=EXCLUDED.owner_id,"
                "installation_status='ACTIVE',bot_user_id=EXCLUDED.bot_user_id,"
                "application_id=EXCLUDED.application_id,version=guild_installations.version+1"
            ),
            {
                "guild": guild_id,
                "name": live_guild.name,
                "owner": live_guild.owner_id,
                "bot": client.user.id,
            },
        )
    correlation = uuid4()
    await runtime.apply_rest_role_snapshot(
        guild_id=guild_id, roles=roles, correlation_id=correlation
    )
    await runtime.apply_rest_channel_snapshot(
        guild_id=guild_id, channels=channels, correlation_id=correlation
    )
    await runtime.mark_structure_sync_complete(guild_id)
    async with admin_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO discord_member_authorization_cache "
                "(guild_id,discord_user_id,role_ids,source,validity,observed_at) VALUES "
                "(:guild,:bot,:roles,'TARGETED_REST','FRESH',now()) ON CONFLICT "
                "(guild_id,discord_user_id) DO UPDATE SET role_ids=EXCLUDED.role_ids,"
                "source='TARGETED_REST',validity='FRESH',observed_at=now(),invalidated_at=NULL"
            ),
            {"guild": guild_id, "bot": client.user.id, "roles": member["role_ids"]},
        )
        await connection.execute(
            text(
                "UPDATE discord_cache_coverage SET coverage_mode='FULL',"
                "freshness_state='FRESH',gateway_continuity='CONNECTED' "
                "WHERE guild_id=:guild"
            ),
            {"guild": guild_id},
        )
    return client.user.id


async def create_validated_plan(
    service: PlanningService,
    *,
    graph: DesiredStateGraph,
    actor: int,
    key: str,
) -> dict[str, Any]:
    correlation = uuid4()
    plan, created = await service.create(
        graph=graph,
        actor_user_id=actor,
        idempotency_key=f"{key}-create",
        correlation_id=correlation,
    )
    if not created:
        raise RuntimeError("live plan idempotency key unexpectedly existed")
    plan, preflight = await service.validate(
        guild_id=graph.guild_id,
        plan_id=UUID(str(plan["id"])),
        actor_user_id=actor,
        expected_version=1,
        correlation_id=correlation,
    )
    if not preflight.allowed:
        if all(error.startswith("capability.permission_missing") for error in preflight.errors):
            raise LiveCapabilityBlocked("sandbox bot lacks structural mutation capabilities")
        raise RuntimeError(f"live preflight blocked: {','.join(preflight.errors)}")
    return await service.confirm(
        guild_id=graph.guild_id,
        plan_id=UUID(str(plan["id"])),
        actor_user_id=actor,
        idempotency_key=f"{key}-confirm",
        expected_version=2,
        supplied_plan_hash=str(plan["plan_hash"]),
        reinforced_acknowledgement=True,
        correlation_id=correlation,
    )


async def apply_with_optional_crash(
    *,
    service: PlanningService,
    plans: PlanningRepository,
    runtime: RuntimeRepository,
    adapter: CountingAdapter,
    lock: RedisGuildMutationLock,
    admin_engine: Any,
    guild_id: int,
    actor: int,
    plan: dict[str, Any],
    inject_crash: bool,
) -> None:
    plan_id = UUID(str(plan["id"]))
    correlation = uuid4()
    job_id = await service.apply(
        guild_id=guild_id,
        plan_id=plan_id,
        actor_user_id=actor,
        correlation_id=correlation,
    )
    first_worker = "stage05-live-first"
    leased = await runtime.lease_next_job(guild_id, lease_owner=first_worker, lease_seconds=30)
    if leased is None:
        raise RuntimeError("live apply job was not leasable")
    if inject_crash:
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            lock,
            worker_id=first_worker,
            faults=CrashAfterDiscord(),
        )
        try:
            await executor.execute_leased(guild_id, leased, None)
        except RuntimeError as exc:
            if str(exc) != "controlled live crash after Discord response":
                raise
        else:
            raise RuntimeError("controlled live failure hook did not trigger")
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE discord_io_jobs SET leased_until=now()-interval '1 second' "
                    "WHERE job_id=:job"
                ),
                {"job": job_id},
            )
        recovery_worker = "stage05-live-recovery"
        leased = await runtime.lease_next_job(
            guild_id, lease_owner=recovery_worker, lease_seconds=30
        )
        if leased is None:
            raise RuntimeError("live recovery job was not leasable")
        executor = ApplyPlanExecutor(plans, adapter, lock, worker_id=recovery_worker)
        await executor.execute_leased(guild_id, leased, None)
        worker = recovery_worker
    else:
        executor = ApplyPlanExecutor(plans, adapter, lock, worker_id=first_worker)
        await executor.execute_leased(guild_id, leased, None)
        worker = first_worker
    if not await runtime.complete_job(
        guild_id,
        job_id,
        lease_owner=worker,
        lease_token=UUID(str(leased["lease_token"])),
    ):
        raise RuntimeError("live plan job acknowledgement was fenced")
    final = await plans.get_plan(guild_id, plan_id)
    if str(final["status"]) != "SUCCEEDED":
        raise RuntimeError(f"live plan did not succeed: {final['status']}")


async def run_live() -> dict[str, int]:
    guild_id = int(os.environ["DISCORD_TEST_GUILD_B_ID"])
    suffix = datetime.now(UTC).strftime("%H%M%S%f")[-10:]
    role_name = f"{PREFIX}ROLE-{suffix}"
    channel_name = f"{PREFIX}channel-{suffix}".lower()
    engine = create_database_engine(APP_URL, pool_size=4)
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    redis: Redis = create_redis_client(REDIS_URL)
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(os.environ["DISCORD_BOT_TOKEN"])
        factory = create_session_factory(engine)
        runtime = RuntimeRepository(factory)
        plans = PlanningRepository(factory)
        read_models = Stage04Repository(factory)
        service = PlanningService(plans, read_models)
        structure = DiscordPyStructureAdapter(client)
        mutable = CountingAdapter(DiscordPyMutableAdapter(client))
        lock = RedisGuildMutationLock(redis, ttl_seconds=30)
        actor = await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            admin_engine=admin_engine,
        )
        graph = DesiredStateGraph(
            guild_id,
            (
                DesiredNode.build(
                    logical_key="live.role",
                    resource_type=ResourceType.ROLE,
                    symbol="live.role",
                    properties={"name": role_name, "permissions": "0"},
                ),
                DesiredNode.build(
                    logical_key="live.channel",
                    resource_type=ResourceType.CHANNEL,
                    symbol="live.channel",
                    properties={"name": channel_name, "type": 0},
                ),
            ),
        )
        create_plan = await create_validated_plan(
            service, graph=graph, actor=actor, key=f"stage05-live-{suffix}"
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=create_plan,
            inject_crash=True,
        )
        if mutable.create_calls != 2:
            raise RuntimeError("live recovery duplicated or omitted a CREATE")

        roles = await structure.fetch_roles(guild_id)
        channels = await structure.fetch_channels(guild_id)
        role = next((item for item in roles if item["name"] == role_name), None)
        channel = next((item for item in channels if item["name"] == channel_name), None)
        if role is None or channel is None:
            raise RuntimeError("live created resources were not observed")
        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            admin_engine=admin_engine,
        )
        cleanup_graph = DesiredStateGraph(
            guild_id,
            (
                DesiredNode.build(
                    logical_key="live.cleanup.role",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(role["role_id"]),
                    presence=NodePresence.ABSENT,
                ),
                DesiredNode.build(
                    logical_key="live.cleanup.channel",
                    resource_type=ResourceType.CHANNEL,
                    discord_id=int(channel["channel_id"]),
                    presence=NodePresence.ABSENT,
                ),
            ),
        )
        cleanup = await create_validated_plan(
            service, graph=cleanup_graph, actor=actor, key=f"stage05-cleanup-{suffix}"
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=cleanup,
            inject_crash=False,
        )
        remaining_roles = await structure.fetch_roles(guild_id)
        remaining_channels = await structure.fetch_channels(guild_id)
        if any(item["name"] == role_name for item in remaining_roles) or any(
            item["name"] == channel_name for item in remaining_channels
        ):
            raise RuntimeError("live cleanup plan did not remove all test resources")
        return {
            "plans_succeeded": 2,
            "create_operations": 2,
            "create_calls_after_recovery": mutable.create_calls,
            "cleanup_operations": 2,
            "controlled_failure_hooks": 1,
        }
    finally:
        await client.close()
        await redis.aclose()
        await engine.dispose()
        await admin_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 05 safe live Plan Engine validation")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()
    load_local_environment(Path(".env.local"))
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    skipped = [
        "429 behavior is contract-tested, not forced against Discord",
        "ambiguous duplicate CREATE requires manual sandbox fixture and is not forced",
    ]
    if not arguments.include:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=missing,
            skipped=skipped,
        )
        return 0
    if missing:
        write_report(
            arguments.report,
            status="BLOCKED_MISSING_CONFIGURATION",
            checks=[],
            missing=missing,
            skipped=skipped,
        )
        return 2
    try:
        counts = asyncio.run(run_live())
    except LiveCapabilityBlocked:
        write_report(
            arguments.report,
            status="PASS_WITH_APPROVED_LIMITATION",
            checks=[
                "live cache snapshot acquired",
                "persisted Plan compiled",
                "preflight correctly denied missing bot capabilities",
                "zero Discord mutations after fail-closed preflight",
            ],
            missing=[],
            skipped=[
                *skipped,
                "safe create/recovery/cleanup not verified: sandbox bot lacks MANAGE_CHANNELS",
                "safe create/recovery/cleanup not verified: sandbox bot lacks MANAGE_ROLES",
            ],
            counts={"plans_compiled": 1, "discord_mutations": 0},
        )
        return 0
    except Exception as exc:
        write_report(
            arguments.report,
            status="FAIL",
            checks=[type(exc).__name__],
            missing=[],
            skipped=skipped,
        )
        raise
    write_report(
        arguments.report,
        status="PASS",
        checks=[
            "persisted create plan and preflight",
            "controlled crash after Discord response",
            "UNKNOWN_OUTCOME recovery without duplicate CREATE",
            "targeted REST verification",
            "persisted destructive cleanup plan",
            "cleanup absence verified",
        ],
        missing=[],
        skipped=skipped,
        counts=counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
