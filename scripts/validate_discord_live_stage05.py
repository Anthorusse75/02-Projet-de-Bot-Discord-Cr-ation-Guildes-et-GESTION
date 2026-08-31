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

from did.application.auth import AuthorizationService
from did.application.planning import ApplyActorAuthorizer, PlanningService
from did.domain.auth import AuthorizationScope, PlatformRole
from did.infrastructure.auth_repository import AuthRepository
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.discord import DiscordPyMutableAdapter, DiscordPyStructureAdapter
from did.infrastructure.planning_lock import RedisGuildMutationLock
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import RedisDiscordWorkloadCoordinator, RedisSingleFlight
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.oauth.discord import HttpDiscordMemberClient
from did.oauth.models import DiscordGuild
from did.oauth.stores import RedisActorMembershipStore, RedisGuildDiscoveryStore
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    OperationType,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)
from did.worker.io.governor import DiscordWorkloadGovernor
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
    def __init__(self, message: str, *, capabilities: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        # Sanitized Discord permission names only (e.g. "MANAGE_CHANNELS"); never
        # a Discord ID, token, or other PII.
        self.capabilities = capabilities


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

    async def check_preconditions(self, **kwargs: Any) -> Any:
        return await self.delegate.check_preconditions(**kwargs)

    async def execute(self, **kwargs: Any) -> Any:
        if str(kwargs["operation_type"]).startswith("CREATE_"):
            self.create_calls += 1
        return await self.delegate.execute(**kwargs)

    async def recover(self, **kwargs: Any) -> Any:
        return await self.delegate.recover(**kwargs)

    async def verify(self, **kwargs: Any) -> bool:
        return await self.delegate.verify(**kwargs)


class CachedGuildAuthContext:
    """Minimum discovery surface used by the existing STAGE 02 authorization service."""

    def __init__(self, guild_store: RedisGuildDiscoveryStore) -> None:
        self.guild_store = guild_store

    async def refresh_guilds(self, discord_user_id: int) -> tuple[DiscordGuild, ...]:
        del discord_user_id
        raise RuntimeError("live authorization discovery cache unexpectedly expired")


async def seed_snapshot(
    *,
    guild_id: int,
    client: discord.Client,
    structure: DiscordPyStructureAdapter,
    runtime: RuntimeRepository,
    auth_repository: AuthRepository,
    guild_store: RedisGuildDiscoveryStore,
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
    await auth_repository.save_user_access(
        guild_id=guild_id,
        target_user_id=client.user.id,
        role=PlatformRole.TENANT_ADMIN,
        actor_user_id=client.user.id,
        scope=AuthorizationScope.guild(),
    )
    await guild_store.put(
        client.user.id,
        (
            DiscordGuild(
                guild_id=guild_id,
                name=live_guild.name,
                icon_hash=None,
                owner=live_guild.owner_id == client.user.id,
                permissions=0,
            ),
        ),
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
    authorization: ApplyActorAuthorizer,
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
    await authorization.authorize_apply(guild_id=graph.guild_id, actor_user_id=actor)
    plan, preflight = await service.validate(
        guild_id=graph.guild_id,
        plan_id=UUID(str(plan["id"])),
        actor_user_id=actor,
        expected_version=1,
        correlation_id=correlation,
        actor_authorization_fresh=True,
    )
    if not preflight.allowed:
        if all(error.startswith("capability.permission_missing") for error in preflight.errors):
            names = tuple(
                sorted(
                    {
                        error.rsplit(".", 1)[-1].upper()
                        for error in preflight.errors
                        if error.startswith("capability.permission_missing")
                    }
                )
            )
            raise LiveCapabilityBlocked(
                "sandbox bot lacks structural mutation capabilities", capabilities=names
            )
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
    authorization: ApplyActorAuthorizer,
    governor: DiscordWorkloadGovernor,
    admin_engine: Any,
    guild_id: int,
    actor: int,
    plan: dict[str, Any],
    inject_crash: bool,
    lease_seconds: int = 300,
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
    leased = await runtime.lease_next_job(
        guild_id, lease_owner=first_worker, lease_seconds=lease_seconds
    )
    if leased is None:
        raise RuntimeError("live apply job was not leasable")
    if inject_crash:
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            lock,
            worker_id=first_worker,
            authorization=authorization,
            faults=CrashAfterDiscord(),
            preflight=service,
        )
        try:
            await executor.execute_leased(guild_id, leased, governor)
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
            guild_id, lease_owner=recovery_worker, lease_seconds=lease_seconds
        )
        if leased is None:
            raise RuntimeError("live recovery job was not leasable")
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            lock,
            worker_id=recovery_worker,
            authorization=authorization,
            preflight=service,
        )
        await executor.execute_leased(guild_id, leased, governor)
        worker = recovery_worker
    else:
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            lock,
            worker_id=first_worker,
            authorization=authorization,
            preflight=service,
        )
        await executor.execute_leased(guild_id, leased, governor)
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


async def assert_operation_catalog(
    plans: PlanningRepository,
    *,
    guild_id: int,
    plan: dict[str, Any],
    expected: dict[OperationType, int],
) -> None:
    rows = await plans.operations(guild_id, UUID(str(plan["id"])))
    actual = {
        operation_type: sum(str(row["operation_type"]) == operation_type.value for row in rows)
        for operation_type in expected
    }
    if actual != expected or len(rows) != sum(expected.values()):
        raise RuntimeError("live compiler did not produce the required operation catalog")


async def run_live() -> dict[str, int]:
    guild_id = int(os.environ["DISCORD_TEST_GUILD_B_ID"])
    suffix = datetime.now(UTC).strftime("%H%M%S%f")[-10:]
    role_name = f"{PREFIX}ROLE-{suffix}"
    anchor_role_name = f"{PREFIX}ANCHOR-{suffix}"
    category_name = f"{PREFIX}CATEGORY-{suffix}"
    channel_name = f"{PREFIX}channel-{suffix}".lower()
    engine = create_database_engine(APP_URL, pool_size=4)
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    redis: Redis = create_redis_client(REDIS_URL)
    client = discord.Client(intents=discord.Intents.none())
    member_client = HttpDiscordMemberClient(bot_token=os.environ["DISCORD_BOT_TOKEN"])
    try:
        await client.login(os.environ["DISCORD_BOT_TOKEN"])
        factory = create_session_factory(engine)
        runtime = RuntimeRepository(factory)
        plans = PlanningRepository(factory)
        auth_repository = AuthRepository(factory)
        read_models = Stage04Repository(factory)
        service = PlanningService(plans, read_models)
        structure = DiscordPyStructureAdapter(client)
        mutable = CountingAdapter(DiscordPyMutableAdapter(client))
        lock = RedisGuildMutationLock(redis, ttl_seconds=30)
        guild_store = RedisGuildDiscoveryStore(redis, ttl_seconds=300)
        auth_context: Any = CachedGuildAuthContext(guild_store)
        authorization = ApplyActorAuthorizer(
            AuthorizationService(
                auth=auth_context,
                repository=auth_repository,
                membership_store=RedisActorMembershipStore(redis, ttl_seconds=1),
                member_client=member_client,
                freshness_seconds=1,
                membership_singleflight=RedisSingleFlight(redis),
                metrics=runtime.metrics,
            )
        )
        governor = DiscordWorkloadGovernor(
            global_concurrency=2,
            per_guild_concurrency=1,
            max_queue_depth=16,
            distributed_coordinator=RedisDiscordWorkloadCoordinator(
                redis,
                global_concurrency=2,
                per_guild_concurrency=1,
                permit_ttl_seconds=30,
            ),
        )
        actor = await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )

        # A previous live crash may have intentionally left an APPLY_PLAN lease
        # and a prefixed resource behind. Resume only runner-owned plans, then
        # remove every observed prefixed fixture through a new audited plan.
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE discord_io_jobs SET leased_until=now()-interval '1 second' "
                    "WHERE guild_id=:guild AND workload_type='APPLY_PLAN' "
                    "AND requested_by=:actor AND status='LEASED'"
                ),
                {"guild": guild_id, "actor": actor},
            )
        resumed_jobs = 0
        terminal_jobs_acknowledged = 0
        while True:
            resume_worker = f"stage05-live-resume-{resumed_jobs}"
            abandoned = await runtime.lease_next_job(
                guild_id, lease_owner=resume_worker, lease_seconds=300
            )
            if abandoned is None:
                break
            if str(abandoned["workload_type"]) != "APPLY_PLAN":
                raise RuntimeError("sandbox contains an unrelated pending Discord job")
            abandoned_plan_id = UUID(str(dict(abandoned["payload"])["plan_id"]))
            abandoned_operations = await plans.operations(guild_id, abandoned_plan_id)
            if not abandoned_operations or any(
                not str(row["resource_ref"]).startswith("live.") for row in abandoned_operations
            ):
                raise RuntimeError("refusing to resume a non-fixture live plan")
            abandoned_plan = await plans.get_plan(guild_id, abandoned_plan_id)
            if str(abandoned_plan["status"]) == "SUCCEEDED":
                if not await runtime.complete_job(
                    guild_id,
                    UUID(str(abandoned["job_id"])),
                    lease_owner=resume_worker,
                    lease_token=UUID(str(abandoned["lease_token"])),
                ):
                    raise RuntimeError("terminal fixture job acknowledgement was fenced")
                terminal_jobs_acknowledged += 1
                continue
            if any(str(row["status"]) != "UNKNOWN_OUTCOME" for row in abandoned_operations):
                raise RuntimeError("abandoned fixture plan is not recovery-only")
            executor = ApplyPlanExecutor(
                plans,
                mutable,
                lock,
                worker_id=resume_worker,
                authorization=authorization,
            )
            await executor.execute_leased(guild_id, abandoned, governor)
            if not await runtime.complete_job(
                guild_id,
                UUID(str(abandoned["job_id"])),
                lease_owner=resume_worker,
                lease_token=UUID(str(abandoned["lease_token"])),
            ):
                raise RuntimeError("resumed fixture job acknowledgement was fenced")
            resumed_plan = await plans.get_plan(guild_id, abandoned_plan_id)
            if str(resumed_plan["status"]) != "SUCCEEDED":
                raise RuntimeError("abandoned fixture plan did not recover successfully")
            resumed_jobs += 1

        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        existing_roles = [
            item
            for item in await structure.fetch_roles(guild_id)
            if str(item["name"]).upper().startswith(PREFIX)
        ]
        existing_channels = [
            item
            for item in await structure.fetch_channels(guild_id)
            if str(item["name"]).upper().startswith(PREFIX)
        ]
        if existing_roles or existing_channels:
            category_keys = {
                int(item["channel_id"]): f"live.preexisting.category.{index}"
                for index, item in enumerate(existing_channels)
                if int(item["type"]) == 4
            }
            cleanup_nodes = [
                DesiredNode.build(
                    logical_key=f"live.preexisting.role.{index}",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(item["role_id"]),
                    presence=NodePresence.ABSENT,
                )
                for index, item in enumerate(existing_roles)
            ]
            for index, item in enumerate(existing_channels):
                channel_id = int(item["channel_id"])
                parent_id = item.get("parent_id")
                cleanup_nodes.append(
                    DesiredNode.build(
                        logical_key=category_keys.get(
                            channel_id, f"live.preexisting.channel.{index}"
                        ),
                        resource_type=(
                            ResourceType.CATEGORY
                            if int(item["type"]) == 4
                            else ResourceType.CHANNEL
                        ),
                        discord_id=channel_id,
                        presence=NodePresence.ABSENT,
                        relations=(
                            {
                                "parent": ResourceReference(
                                    ReferenceKind.LOGICAL, category_keys[int(parent_id)]
                                )
                            }
                            if parent_id is not None and int(parent_id) in category_keys
                            else None
                        ),
                    )
                )
            preexisting_cleanup = await create_validated_plan(
                service,
                graph=DesiredStateGraph(guild_id, tuple(cleanup_nodes)),
                actor=actor,
                key=f"stage05-preexisting-cleanup-{suffix}",
                authorization=authorization,
            )
            await apply_with_optional_crash(
                service=service,
                plans=plans,
                runtime=runtime,
                adapter=mutable,
                lock=lock,
                authorization=authorization,
                governor=governor,
                admin_engine=admin_engine,
                guild_id=guild_id,
                actor=actor,
                plan=preexisting_cleanup,
                inject_crash=False,
            )
            await seed_snapshot(
                guild_id=guild_id,
                client=client,
                structure=structure,
                runtime=runtime,
                auth_repository=auth_repository,
                guild_store=guild_store,
                admin_engine=admin_engine,
            )

        # The crash window is isolated to CREATE_ROLE: Get Guild Roles is an
        # exhaustive recovery signal, unlike an omitted Get Guild Channels row.
        crash_graph = DesiredStateGraph(
            guild_id,
            (
                DesiredNode.build(
                    logical_key="live.role",
                    resource_type=ResourceType.ROLE,
                    symbol="live.role",
                    properties={"name": role_name, "permissions": "0"},
                ),
            ),
        )
        crash_plan = await create_validated_plan(
            service,
            graph=crash_graph,
            actor=actor,
            key=f"stage05-crash-{suffix}",
            authorization=authorization,
        )
        await assert_operation_catalog(
            plans,
            guild_id=guild_id,
            plan=crash_plan,
            expected={OperationType.CREATE_ROLE: 1},
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=crash_plan,
            inject_crash=True,
        )
        if mutable.create_calls != 1:
            raise RuntimeError("live recovery duplicated or omitted a CREATE")

        roles = await structure.fetch_roles(guild_id)
        matching_roles = [item for item in roles if item["name"] == role_name]
        if len(matching_roles) != 1:
            raise RuntimeError("live crash recovery did not leave exactly one role fixture")
        async with admin_engine.connect() as connection:
            bound_symbols = int(
                (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM plan_symbol_bindings WHERE guild_id=:guild "
                            "AND plan_id=:plan AND symbol='live.role' AND status='BOUND' "
                            "AND discord_id IS NOT NULL"
                        ),
                        {"guild": guild_id, "plan": UUID(str(crash_plan["id"]))},
                    )
                ).scalar_one()
            )
        if bound_symbols != 1:
            raise RuntimeError("live crash recovery did not restore the symbol binding")

        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        create_graph = DesiredStateGraph(
            guild_id,
            (
                DesiredNode.build(
                    logical_key="live.anchor-role",
                    resource_type=ResourceType.ROLE,
                    symbol="live.anchor-role",
                    properties={"name": anchor_role_name, "permissions": "0"},
                ),
                DesiredNode.build(
                    logical_key="live.category",
                    resource_type=ResourceType.CATEGORY,
                    symbol="live.category",
                    properties={"name": category_name},
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
            service,
            graph=create_graph,
            actor=actor,
            key=f"stage05-create-{suffix}",
            authorization=authorization,
        )
        await assert_operation_catalog(
            plans,
            guild_id=guild_id,
            plan=create_plan,
            expected={OperationType.CREATE_ROLE: 1, OperationType.CREATE_CHANNEL: 2},
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=create_plan,
            inject_crash=False,
        )

        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        roles = await structure.fetch_roles(guild_id)
        channels = await structure.fetch_channels(guild_id)
        role = next((item for item in roles if item["name"] == role_name), None)
        anchor = next((item for item in roles if item["name"] == anchor_role_name), None)
        category = next((item for item in channels if item["name"] == category_name), None)
        channel = next((item for item in channels if item["name"] == channel_name), None)
        if role is None or anchor is None or category is None or channel is None:
            raise RuntimeError("live create plan resources were not all observed")
        role_position = int(role["position"])
        anchor_position = int(anchor["position"])
        if role_position == anchor_position:
            # Discord may assign equal positions to newly-created roles. Both
            # fixtures sit immediately above @everyone and below the bot role,
            # so keep one at 1 and place the other immediately below the bot's
            # highest role. This avoids Discord normalizing the request around
            # managed roles that may already occupy the lowest positions.
            if client.user is None:
                raise RuntimeError("Discord bot identity unavailable during role reorder")
            bot_member = await structure.fetch_member(guild_id, client.user.id)
            bot_role_ids = {int(item) for item in bot_member["role_ids"]}
            bot_role_positions = [
                int(item["position"]) for item in roles if int(item["role_id"]) in bot_role_ids
            ]
            if not bot_role_positions or max(bot_role_positions) <= 2:
                raise RuntimeError("bot hierarchy cannot safely demonstrate role reorder")
            target_role_position = 1
            # Keep one free position below the bot's highest role. Discord can
            # normalise a requested adjacent position around existing guild
            # roles, while the lower destination remains stable and still
            # proves a real, hierarchy-safe reorder.
            target_anchor_position = max(bot_role_positions) - 2
        else:
            target_role_position = anchor_position
            target_anchor_position = role_position

        updated_role_name = f"{role_name}-UPDATED"
        updated_category_name = f"{category_name}-UPDATED"
        update_graph = DesiredStateGraph(
            guild_id,
            (
                DesiredNode.build(
                    logical_key="live.role",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(role["role_id"]),
                    properties={
                        "name": updated_role_name,
                        "permissions": "0",
                        "position": target_role_position,
                    },
                ),
                DesiredNode.build(
                    logical_key="live.anchor-role",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(anchor["role_id"]),
                    properties={
                        "name": anchor_role_name,
                        "permissions": "0",
                        "position": target_anchor_position,
                    },
                ),
                DesiredNode.build(
                    logical_key="live.category",
                    resource_type=ResourceType.CATEGORY,
                    discord_id=int(category["channel_id"]),
                    properties={"name": updated_category_name, "type": 4},
                ),
                DesiredNode.build(
                    logical_key="live.channel",
                    resource_type=ResourceType.CHANNEL,
                    discord_id=int(channel["channel_id"]),
                    properties={
                        "name": channel_name,
                        "type": 0,
                        "topic": "DID STAGE 05 live update",
                        "position": int(channel["position"]),
                    },
                    relations={"parent": ResourceReference(ReferenceKind.LOGICAL, "live.category")},
                ),
                DesiredNode.build(
                    logical_key="live.overwrite",
                    resource_type=ResourceType.OVERWRITE,
                    properties={"target_type": 0, "allow": 1024, "deny": 0},
                    relations={
                        "channel": ResourceReference(ReferenceKind.LOGICAL, "live.channel"),
                        "subject": ResourceReference(ReferenceKind.LOGICAL, "live.role"),
                    },
                ),
            ),
        )
        update_plan = await create_validated_plan(
            service,
            graph=update_graph,
            actor=actor,
            key=f"stage05-update-{suffix}",
            authorization=authorization,
        )
        await assert_operation_catalog(
            plans,
            guild_id=guild_id,
            plan=update_plan,
            expected={
                OperationType.UPDATE_ROLE: 1,
                OperationType.REORDER_ROLES: 1,
                OperationType.UPDATE_CHANNEL: 2,
                OperationType.MOVE_OR_REORDER_CHANNELS: 1,
                OperationType.UPSERT_OVERWRITE: 1,
            },
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=update_plan,
            inject_crash=False,
        )

        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        delete_overwrite_graph = DesiredStateGraph(
            guild_id,
            (
                DesiredNode.build(
                    logical_key="live.role",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(role["role_id"]),
                    properties={"name": updated_role_name},
                ),
                DesiredNode.build(
                    logical_key="live.channel",
                    resource_type=ResourceType.CHANNEL,
                    discord_id=int(channel["channel_id"]),
                    properties={"name": channel_name},
                ),
                DesiredNode.build(
                    logical_key="live.overwrite",
                    resource_type=ResourceType.OVERWRITE,
                    presence=NodePresence.ABSENT,
                    properties={"target_type": 0},
                    relations={
                        "channel": ResourceReference(ReferenceKind.LOGICAL, "live.channel"),
                        "subject": ResourceReference(ReferenceKind.LOGICAL, "live.role"),
                    },
                ),
            ),
        )
        overwrite_cleanup = await create_validated_plan(
            service,
            graph=delete_overwrite_graph,
            actor=actor,
            key=f"stage05-overwrite-delete-{suffix}",
            authorization=authorization,
        )
        await assert_operation_catalog(
            plans,
            guild_id=guild_id,
            plan=overwrite_cleanup,
            expected={OperationType.DELETE_OVERWRITE: 1},
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=overwrite_cleanup,
            inject_crash=False,
        )

        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        restore_role_order = await create_validated_plan(
            service,
            graph=DesiredStateGraph(
                guild_id,
                (
                    DesiredNode.build(
                        logical_key="live.anchor-role",
                        resource_type=ResourceType.ROLE,
                        discord_id=int(anchor["role_id"]),
                        properties={
                            "name": anchor_role_name,
                            "permissions": "0",
                            "position": 1,
                        },
                    ),
                ),
            ),
            actor=actor,
            key=f"stage05-role-order-restore-{suffix}",
            authorization=authorization,
        )
        await assert_operation_catalog(
            plans,
            guild_id=guild_id,
            plan=restore_role_order,
            expected={OperationType.REORDER_ROLES: 1},
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=restore_role_order,
            inject_crash=False,
        )

        await seed_snapshot(
            guild_id=guild_id,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
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
                    logical_key="live.cleanup.anchor-role",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(anchor["role_id"]),
                    presence=NodePresence.ABSENT,
                ),
                DesiredNode.build(
                    logical_key="live.cleanup.channel",
                    resource_type=ResourceType.CHANNEL,
                    discord_id=int(channel["channel_id"]),
                    presence=NodePresence.ABSENT,
                    relations={
                        "parent": ResourceReference(ReferenceKind.LOGICAL, "live.cleanup.category")
                    },
                ),
                DesiredNode.build(
                    logical_key="live.cleanup.category",
                    resource_type=ResourceType.CATEGORY,
                    discord_id=int(category["channel_id"]),
                    presence=NodePresence.ABSENT,
                ),
            ),
        )
        cleanup = await create_validated_plan(
            service,
            graph=cleanup_graph,
            actor=actor,
            key=f"stage05-cleanup-{suffix}",
            authorization=authorization,
        )
        await assert_operation_catalog(
            plans,
            guild_id=guild_id,
            plan=cleanup,
            expected={OperationType.DELETE_ROLE: 2, OperationType.DELETE_CHANNEL: 2},
        )
        await apply_with_optional_crash(
            service=service,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_id,
            actor=actor,
            plan=cleanup,
            inject_crash=False,
        )
        remaining_roles = await structure.fetch_roles(guild_id)
        remaining_channels = await structure.fetch_channels(guild_id)
        if any(str(item["name"]).upper().startswith(PREFIX) for item in remaining_roles) or any(
            str(item["name"]).upper().startswith(PREFIX) for item in remaining_channels
        ):
            raise RuntimeError("live cleanup plan did not remove all test resources")
        return {
            "plans_succeeded": 6,
            "create_operations": 4,
            "create_calls_at_crash_recovery": 1,
            "create_calls_total": mutable.create_calls,
            "update_operations_verified": 3,
            "move_or_reorder_operations_verified": 3,
            "overwrite_upserts": 1,
            "overwrite_deletes": 1,
            "cleanup_operations": 4,
            "role_order_restore_operations": 1,
            "symbol_bindings_recovered": bound_symbols,
            "controlled_failure_hooks": 1,
            "abandoned_fixture_jobs_resumed": resumed_jobs,
            "terminal_fixture_jobs_acknowledged": terminal_jobs_acknowledged,
            "preexisting_fixtures_cleaned": len(existing_roles) + len(existing_channels),
        }
    finally:
        await client.close()
        await member_client.aclose()
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
            status="BLOCKED_CAPABILITY_CONFIGURATION",
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
        return 2
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
            "persisted plans, sensitive worker authorization and final preflight",
            "all Discord REST reads and mutations passed the workload governor",
            "CREATE category, channel and role fixtures",
            "UPDATE role, category and channel",
            "MOVE channel parent and REORDER roles",
            "UPSERT and DELETE overwrite",
            "controlled crash after CREATE_ROLE Discord response",
            "UNKNOWN_OUTCOME recovery without duplicate CREATE",
            "recovered durable symbol binding",
            "targeted REST verification after each plan",
            "persisted destructive cleanup plan",
            "all prefixed fixtures absent after cleanup",
        ],
        missing=[],
        skipped=skipped,
        counts=counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
