from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import discord
from redis.asyncio import Redis
from sqlalchemy import text

from did.application.auth import AuthorizationService
from did.application.planning import ApplyActorAuthorizer, PlanningService
from did.application.portability import ArtifactKind, PortabilityService
from did.application.translation import LanguageProfileService, TranslationTopologyService
from did.application.translation.lifecycle import Stage08PostVerificationMaterializer
from did.application.translation.planning import Stage08StructuralPlanningService
from did.application.translation.provider_orchestration import Stage08ProviderOrchestrationService
from did.domain.auth import ActorMembership, AuthorizationScope, PlatformRole
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.domain.scopes import ScopeType
from did.domain.translation_topology import TranslationGroupTopology
from did.infrastructure.auth_repository import AuthRepository
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.discord import DiscordPyMutableAdapter, DiscordPyStructureAdapter
from did.infrastructure.planning_lock import RedisGuildMutationLock
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.portability_repository import PortabilityRepository
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import RedisDiscordWorkloadCoordinator, RedisSingleFlight
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    ResourceLanguagePolicyRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
    VisibilityScopeLanguageRepository,
)
from did.oauth.discord import HttpDiscordMemberClient
from did.oauth.models import DiscordGuild
from did.oauth.stores import RedisActorMembershipStore, RedisGuildDiscoveryStore
from did.planning.models import DesiredNode, DesiredStateGraph, NodePresence, ResourceType
from did.portability import ArtifactCipher, CloneMode, InMemoryKeyProvider
from did.worker.io.governor import DiscordWorkloadGovernor
from did.worker.io.plan_executor import ApplyPlanExecutor
from validate_discord_live_stage05 import CachedGuildAuthContext, LiveCapabilityBlocked

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
PREFIX = "DID-STAGE08-TEST-"


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
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
    counts: dict[str, int] | None = None,
    hashes: dict[str, str] | None = None,
    blocker: str | None = None,
    missing_capabilities: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "stage": "08",
                "profile": "discord-live-multilingual-topology",
                "status": status,
                "generated_at": datetime.now(UTC).isoformat(),
                "checks": checks,
                "missing_variable_names": missing,
                "counts": counts or {},
                "evidence_hashes": hashes or {},
                "blocker": blocker,
                # Sanitized Discord permission names only (e.g. "MANAGE_CHANNELS");
                # never a Discord ID, token, or other PII.
                "missing_capabilities": missing_capabilities or [],
                "resource_prefix_family": PREFIX,
                "secrets_recorded": False,
                "discord_identifiers_recorded": False,
                "message_content_intent_enabled": False,
                "discord_structural_mutations_direct": 0,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class CountingAdapter:
    def __init__(self, delegate: DiscordPyMutableAdapter) -> None:
        self.delegate = delegate
        self.calls: Counter[int] = Counter()

    async def check_preconditions(self, **kwargs: Any) -> Any:
        return await self.delegate.check_preconditions(**kwargs)

    async def execute(self, **kwargs: Any) -> Any:
        self.calls[int(kwargs["guild_id"])] += 1
        return await self.delegate.execute(**kwargs)

    async def recover(self, **kwargs: Any) -> Any:
        return await self.delegate.recover(**kwargs)

    async def verify(self, **kwargs: Any) -> bool:
        return await self.delegate.verify(**kwargs)


async def governed[T](
    governor: DiscordWorkloadGovernor,
    guild_id: int,
    key: str,
    operation: Callable[[], Awaitable[T]],
) -> T:
    async def distributed() -> T:
        return cast(T, await governor.run_distributed(guild_id, operation))

    future = governor.submit(
        WorkloadJob(
            uuid4(),
            guild_id,
            "LIVE_REFRESH",
            f"stage08:{key}:{uuid4()}",
            WorkloadPriority.USER_REFRESH,
            datetime.now(UTC),
        ),
        distributed,
    )
    await governor.drain()
    return cast(T, await future)


async def refresh(
    *,
    guild_id: int,
    client: discord.Client,
    structure: DiscordPyStructureAdapter,
    governor: DiscordWorkloadGovernor,
    runtime: RuntimeRepository,
    auth: AuthRepository,
    memberships: RedisActorMembershipStore,
    admin_engine: Any,
) -> tuple[int, DiscordGuild]:
    if client.user is None:
        raise RuntimeError("Discord bot identity unavailable")
    actor = int(client.user.id)
    live = await governed(governor, guild_id, "guild", lambda: client.fetch_guild(guild_id))
    roles = await governed(governor, guild_id, "roles", lambda: structure.fetch_roles(guild_id))
    channels = await governed(
        governor, guild_id, "channels", lambda: structure.fetch_channels(guild_id)
    )
    try:
        members = await governed(
            governor, guild_id, "members", lambda: structure.fetch_members(guild_id)
        )
    except Exception as exc:
        raise LiveCapabilityBlocked(
            "Server Members Intent is required for complete cleanup evidence"
        ) from exc
    actor_member = next((row for row in members if int(row["discord_user_id"]) == actor), None)
    if actor_member is None or not bool(actor_member.get("is_bot")):
        raise RuntimeError("DID provider bot is absent from the complete member snapshot")
    async with admin_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (discord_user_id,username) VALUES (:bot,'stage08-live') "
                "ON CONFLICT (discord_user_id) DO NOTHING"
            ),
            {"bot": actor},
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
            {"guild": guild_id, "name": live.name, "owner": live.owner_id, "bot": actor},
        )
    await auth.save_user_access(
        guild_id=guild_id,
        target_user_id=actor,
        role=PlatformRole.TENANT_ADMIN,
        actor_user_id=actor,
        scope=AuthorizationScope.guild(),
    )
    correlation = uuid4()
    await runtime.apply_rest_role_snapshot(
        guild_id=guild_id, roles=roles, correlation_id=correlation
    )
    await runtime.apply_rest_channel_snapshot(
        guild_id=guild_id, channels=channels, correlation_id=correlation
    )
    await runtime.apply_complete_rest_member_snapshot(
        guild_id=guild_id, members=members, correlation_id=correlation
    )
    await runtime.mark_structure_sync_complete(guild_id)
    await memberships.put(
        ActorMembership(
            guild_id,
            actor,
            tuple(int(value) for value in actor_member["role_ids"]),
            datetime.now(UTC),
            "FULL_REST_LIST",
        )
    )
    return actor, DiscordGuild(guild_id, live.name, None, live.owner_id == actor, 0)


async def validate_plan(
    planning: PlanningService,
    authorization: ApplyActorAuthorizer,
    plan: dict[str, Any],
    *,
    actor: int,
    key: str,
) -> dict[str, Any]:
    guild_id, plan_id = int(plan["guild_id"]), UUID(str(plan["id"]))
    await authorization.authorize_apply(guild_id=guild_id, actor_user_id=actor)
    validated, preflight = await planning.validate(
        guild_id=guild_id,
        plan_id=plan_id,
        actor_user_id=actor,
        expected_version=int(plan["state_version"]),
        correlation_id=uuid4(),
        actor_authorization_fresh=True,
    )
    if not preflight.allowed:
        if preflight.errors and all(
            error.startswith("capability.permission_missing") for error in preflight.errors
        ):
            raise LiveCapabilityBlocked(
                "sandbox bot lacks structural mutation capabilities: " + ",".join(preflight.errors)
            )
        raise RuntimeError(f"live plan preflight failed: {','.join(preflight.errors)}")
    return await planning.confirm(
        guild_id=guild_id,
        plan_id=plan_id,
        actor_user_id=actor,
        idempotency_key=f"stage08:{key}:confirm",
        expected_version=int(validated["state_version"]),
        supplied_plan_hash=str(validated["plan_hash"]),
        reinforced_acknowledgement=True,
        correlation_id=uuid4(),
    )


async def apply_plan(
    *,
    planning: PlanningService,
    plans: PlanningRepository,
    runtime: RuntimeRepository,
    adapter: CountingAdapter,
    lock: RedisGuildMutationLock,
    authorization: ApplyActorAuthorizer,
    governor: DiscordWorkloadGovernor,
    lifecycle: Stage08LifecycleRepository,
    guild_id: int,
    actor: int,
    plan: dict[str, Any],
) -> str:
    plan_id = UUID(str(plan["id"]))
    job_id = await planning.apply(
        guild_id=guild_id,
        plan_id=plan_id,
        actor_user_id=actor,
        correlation_id=uuid4(),
    )
    worker = f"stage08-live-{uuid4()}"
    leased = await runtime.lease_next_job(guild_id, lease_owner=worker, lease_seconds=600)
    if leased is None:
        raise RuntimeError("live apply job was not leasable")
    await ApplyPlanExecutor(
        plans,
        adapter,
        lock,
        worker_id=worker,
        authorization=authorization,
        preflight=planning,
        post_verification=Stage08PostVerificationMaterializer(lifecycle),
    ).execute_leased(guild_id, leased, governor)
    if not await runtime.complete_job(
        guild_id,
        job_id,
        lease_owner=worker,
        lease_token=UUID(str(leased["lease_token"])),
    ):
        raise RuntimeError("live plan acknowledgement was fenced")
    status = str((await plans.get_plan(guild_id, plan_id))["status"])
    if status not in {"SUCCEEDED", "APPLIED_WITH_PENDING_PROVIDER"}:
        raise RuntimeError(f"live plan failed: {status}")
    return status


def fixture_hash(roles: list[dict[str, Any]], channels: list[dict[str, Any]], prefix: str) -> str:
    payload = {
        "roles": sorted(
            (str(row["role_id"]), str(row["name"]), str(row["permissions"]))
            for row in roles
            if str(row["name"]).upper().startswith(prefix.upper())
        ),
        "channels": sorted(
            (str(row["channel_id"]), str(row["name"]), int(row["type"]))
            for row in channels
            if str(row["name"]).upper().startswith(prefix.upper())
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def resources(
    structure: DiscordPyStructureAdapter,
    governor: DiscordWorkloadGovernor,
    guild_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return (
        await governed(
            governor, guild_id, "roles-observe", lambda: structure.fetch_roles(guild_id)
        ),
        await governed(
            governor, guild_id, "channels-observe", lambda: structure.fetch_channels(guild_id)
        ),
    )


async def absent_plan(
    planning: PlanningService,
    authorization: ApplyActorAuthorizer,
    *,
    guild_id: int,
    actor: int,
    nodes: tuple[DesiredNode, ...],
    key: str,
) -> dict[str, Any]:
    draft, created = await planning.create(
        graph=DesiredStateGraph(guild_id, nodes),
        actor_user_id=actor,
        idempotency_key=f"stage08:{key}:create",
        correlation_id=uuid4(),
        operation_order_policy="STAGE08_STRUCTURAL",
    )
    if not created:
        raise RuntimeError("fresh cleanup plan unexpectedly replayed")
    return await validate_plan(planning, authorization, draft, actor=actor, key=key)


async def run_live() -> tuple[dict[str, int], dict[str, str]]:
    guild_a = int(os.environ["DISCORD_TEST_GUILD_A_ID"])
    guild_b = int(os.environ["DISCORD_TEST_GUILD_B_ID"])
    if guild_a == guild_b:
        raise RuntimeError("Stage 08 live validation requires two distinct sandbox Guilds")
    suffix = datetime.now(UTC).strftime("%H%M%S%f")[-10:]
    run_prefix = f"{PREFIX}{suffix}-"
    engine = create_database_engine(APP_URL, pool_size=4)
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    redis: Redis = create_redis_client(REDIS_URL)
    intents = discord.Intents.none()
    intents.members = True
    client = discord.Client(intents=intents)
    member_client = HttpDiscordMemberClient(bot_token=os.environ["DISCORD_BOT_TOKEN"])
    artifact_id: UUID | None = None
    portability_repository: PortabilityRepository | None = None
    try:
        await client.login(os.environ["DISCORD_BOT_TOKEN"])
        factory = create_session_factory(engine)
        runtime = RuntimeRepository(factory)
        plans = PlanningRepository(factory)
        auth_repository = AuthRepository(factory)
        read_models = Stage04Repository(factory)
        planning = PlanningService(plans, read_models)
        structure = DiscordPyStructureAdapter(client)
        mutable = CountingAdapter(DiscordPyMutableAdapter(client))
        lock = RedisGuildMutationLock(redis, ttl_seconds=30)
        guild_store = RedisGuildDiscoveryStore(redis, ttl_seconds=3600)
        membership_store = RedisActorMembershipStore(redis, ttl_seconds=3600)
        authorization = ApplyActorAuthorizer(
            AuthorizationService(
                auth=CachedGuildAuthContext(guild_store),  # type: ignore[arg-type]
                repository=auth_repository,
                membership_store=membership_store,
                member_client=member_client,
                freshness_seconds=3600,
                membership_singleflight=RedisSingleFlight(redis),
                metrics=runtime.metrics,
            )
        )
        governor = DiscordWorkloadGovernor(
            global_concurrency=2,
            per_guild_concurrency=1,
            max_queue_depth=64,
            distributed_coordinator=RedisDiscordWorkloadCoordinator(
                redis,
                global_concurrency=2,
                per_guild_concurrency=1,
                permit_ttl_seconds=30,
            ),
        )

        async def refresh_guild(guild_id: int) -> tuple[int, DiscordGuild]:
            return await refresh(
                guild_id=guild_id,
                client=client,
                structure=structure,
                governor=governor,
                runtime=runtime,
                auth=auth_repository,
                memberships=membership_store,
                admin_engine=admin_engine,
            )

        actor, discovery_a = await refresh_guild(guild_a)
        actor_b, discovery_b = await refresh_guild(guild_b)
        if actor != actor_b:
            raise RuntimeError("sandbox Guilds do not share the DID bot identity")
        await guild_store.put(actor, (discovery_a, discovery_b))

        async def refresh_and_publish(guild_id: int) -> None:
            nonlocal discovery_a, discovery_b
            refreshed_actor, discovery = await refresh_guild(guild_id)
            if refreshed_actor != actor:
                raise RuntimeError("Discord actor changed during the live run")
            if guild_id == guild_a:
                discovery_a = discovery
            else:
                discovery_b = discovery
            await guild_store.put(actor, (discovery_a, discovery_b))

        profiles = LanguageProfileRepository(factory)
        policies = ResourceLanguagePolicyRepository(factory)
        groups = TranslationGroupRepository(factory)
        providers = TranslationProviderBindingRepository(factory)
        scope_roles = VisibilityScopeLanguageRepository(factory)
        lifecycle = Stage08LifecycleRepository(factory)
        recovery_role_ids: dict[int, set[int]] = {guild_a: set(), guild_b: set()}
        async with admin_engine.connect() as connection:
            recovery_plans = (
                (
                    await connection.execute(
                        text(
                            "SELECT transfers.destination_guild_id,transfers.destination_plan_id "
                            "FROM cross_guild_transfers transfers JOIN user_portable_artifacts "
                            "artifacts ON artifacts.owner_discord_user_id="
                            "transfers.actor_discord_user_id AND artifacts.id="
                            "transfers.portable_artifact_id JOIN plans ON plans.guild_id="
                            "transfers.destination_guild_id AND plans.id="
                            "transfers.destination_plan_id WHERE transfers.actor_discord_user_id="
                            ":actor AND artifacts.name LIKE :prefix AND plans.status IN "
                            "('PARTIALLY_APPLIED','FAILED','INTERVENTION_REQUIRED')"
                        ),
                        {"actor": actor, "prefix": f"{PREFIX}%"},
                    )
                )
                .mappings()
                .all()
            )
        for recovery_plan in recovery_plans:
            destination_id = int(recovery_plan["destination_guild_id"])
            if destination_id not in recovery_role_ids:
                continue
            bindings = await plans.symbol_bindings(
                destination_id, UUID(str(recovery_plan["destination_plan_id"]))
            )
            recovery_role_ids[destination_id].update(
                int(binding["discord_id"])
                for binding in bindings
                if str(binding["resource_type"]) == "ROLE"
                and str(binding["status"]) == "BOUND"
                and binding["discord_id"] is not None
            )
        for guild_id in (guild_a, guild_b):
            roles, channels = await resources(structure, governor, guild_id)
            stale_role_ids = [
                int(row["role_id"])
                for row in roles
                if str(row["name"]).upper().startswith(PREFIX)
                or int(row["role_id"]) in recovery_role_ids[guild_id]
            ]
            stale_channel_ids = [
                int(row["channel_id"])
                for row in channels
                if str(row["name"]).upper().startswith(PREFIX)
            ]
            _, member = await read_models.guild_snapshot(guild_id, actor)
            grant_role_ids = sorted(recovery_role_ids[guild_id] - set(member.role_ids))
            if grant_role_ids:
                grant_draft, created = await planning.create(
                    graph=DesiredStateGraph(
                        guild_id,
                        tuple(
                            DesiredNode.build(
                                logical_key=f"stage08.recovery.member-role.{index}",
                                resource_type=ResourceType.MEMBER_ROLE,
                                discord_id=actor,
                                properties={
                                    "member_id": actor,
                                    "role_id": role_id,
                                    "assigned": True,
                                    "current_assigned": False,
                                },
                            )
                            for index, role_id in enumerate(grant_role_ids)
                        ),
                    ),
                    actor_user_id=actor,
                    idempotency_key=f"stage08:recover-grants:{guild_id}:{suffix}",
                    correlation_id=uuid4(),
                    operation_order_policy="STAGE08_STRUCTURAL",
                )
                if not created:
                    raise RuntimeError("fresh recovery grant plan unexpectedly replayed")
                grant_plan = await validate_plan(
                    planning,
                    authorization,
                    grant_draft,
                    actor=actor,
                    key=f"recover-grants-{guild_id}-{suffix}",
                )
                await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_id,
                    actor=actor,
                    plan=grant_plan,
                )
                await refresh_and_publish(guild_id)
            stale_channel_nodes = tuple(
                DesiredNode.build(
                    logical_key=f"stage08.recovery.channel.{index}",
                    resource_type=ResourceType.CHANNEL,
                    discord_id=channel_id,
                    presence=NodePresence.ABSENT,
                )
                for index, channel_id in enumerate(stale_channel_ids)
            )
            if stale_channel_nodes:
                recovery = await absent_plan(
                    planning,
                    authorization,
                    guild_id=guild_id,
                    actor=actor,
                    nodes=stale_channel_nodes,
                    key=f"recover-channels-{guild_id}-{suffix}",
                )
                await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_id,
                    actor=actor,
                    plan=recovery,
                )
                await refresh_and_publish(guild_id)
            stale_role_nodes = tuple(
                DesiredNode.build(
                    logical_key=f"stage08.recovery.role.{index}",
                    resource_type=ResourceType.ROLE,
                    discord_id=role_id,
                    presence=NodePresence.ABSENT,
                )
                for index, role_id in enumerate(stale_role_ids)
            )
            if stale_role_nodes:
                recovery = await absent_plan(
                    planning,
                    authorization,
                    guild_id=guild_id,
                    actor=actor,
                    nodes=stale_role_nodes,
                    key=f"recover-roles-{guild_id}-{suffix}",
                )
                await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_id,
                    actor=actor,
                    plan=recovery,
                )
                await refresh_and_publish(guild_id)
        language_service = LanguageProfileService(profiles, policies)
        topology = TranslationTopologyService(groups, providers, scope_roles, read_models)
        structural = Stage08StructuralPlanningService(
            planning=planning,
            read_models=read_models,
            groups=groups,
            languages=profiles,
            policies=policies,
            scope_roles=scope_roles,
            lifecycle=lifecycle,
        )
        provider_service = Stage08ProviderOrchestrationService(
            read_models=read_models, groups=groups, providers=providers
        )
        recovered_technical_roles = 0
        sandbox_scope_ids = {
            scope.id
            for scope, _, _ in await read_models.list_visibility_scopes(guild_a)
            if scope.scope_key.startswith(("stage08-alpha-", "stage08-beta-"))
        }
        if sandbox_scope_ids:
            await language_service.set_member_languages(
                guild_id=guild_a,
                discord_user_id=actor,
                language_ids=(),
                source="MANUAL",
            )
            (
                recovery_member_draft,
                _,
                recovery_member_evidence,
            ) = await structural.create_member_role_plan(
                guild_id=guild_a,
                member_id=actor,
                actor_user_id=actor,
                idempotency_key=f"{suffix}-recover-member",
                correlation_id=uuid4(),
            )
            if recovery_member_evidence["remove"]:
                recovery_member_plan = await validate_plan(
                    planning,
                    authorization,
                    recovery_member_draft,
                    actor=actor,
                    key=f"recover-member-{suffix}",
                )
                await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_a,
                    actor=actor,
                    plan=recovery_member_plan,
                )
                await refresh_and_publish(guild_a)
            for policy in await language_service.resource_policies(guild_id=guild_a):
                raw_scope_id = policy.get("visibility_scope_id")
                if raw_scope_id is None or UUID(str(raw_scope_id)) not in sandbox_scope_ids:
                    continue
                await language_service.upsert_resource_policy(
                    guild_id=guild_a,
                    resource_type=str(policy["resource_type"]),
                    discord_resource_id=int(policy["discord_resource_id"]),
                    explicit_language_profile_id=None,
                    inherit_language=False,
                    visibility_policy="OPEN_ALL",
                    visibility_scope_id=None,
                    custom_policy={},
                )
            for binding in await scope_roles.list_bindings(guild_a):
                if UUID(str(binding["visibility_scope_id"])) not in sandbox_scope_ids:
                    continue
                cleanup_draft, _, _ = await structural.create_scope_role_cleanup_plan(
                    guild_id=guild_a,
                    binding_id=UUID(str(binding["id"])),
                    actor_user_id=actor,
                    idempotency_key=f"{suffix}-recover-{binding['id']}",
                    correlation_id=uuid4(),
                )
                cleanup_plan = await validate_plan(
                    planning,
                    authorization,
                    cleanup_draft,
                    actor=actor,
                    key=f"recover-binding-{binding['id']}-{suffix}",
                )
                await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_a,
                    actor=actor,
                    plan=cleanup_plan,
                )
                recovered_technical_roles += 1
                await refresh_and_publish(guild_a)
        existing_languages = {
            str(row["code"]): row for row in await language_service.list_profiles(guild_id=guild_a)
        }
        languages: dict[str, dict[str, Any]] = {}
        for code, display_name in (
            ("fr", "French"),
            ("en", "English"),
            ("de", "German"),
            ("es", "Spanish"),
        ):
            language = existing_languages.get(code)
            if language is None:
                language = await language_service.create(
                    guild_id=guild_a, code=code, display_name=display_name
                )
            if not bool(language["enabled"]):
                raise RuntimeError("required sandbox language profile is disabled")
            languages[code] = language
        present = await providers.create(
            guild_id=guild_a,
            provider_type="existing_translation_bot",
            provider_instance_key=f"{run_prefix}present",
            provider_discord_user_id=actor,
            capabilities={"supports_hub_and_spoke": True, "max_languages_per_group": 8},
        )
        absent = await providers.create(
            guild_id=guild_a,
            provider_type="existing_translation_bot",
            provider_instance_key=f"{run_prefix}absent",
            capabilities={"supports_hub_and_spoke": True, "max_languages_per_group": 8},
        )
        group_one = await topology.create_group(
            guild_id=guild_a,
            name=f"{run_prefix}Guides",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            language_ids=tuple(
                UUID(str(languages[code]["id"])) for code in ("fr", "en", "de", "es")
            ),
            visibility_scope_id=None,
            source_language_profile_id=UUID(str(languages["fr"]["id"])),
            provider_binding_id=UUID(str(present["id"])),
        )
        group_two = await topology.create_group(
            guild_id=guild_a,
            name=f"{run_prefix}Support",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            language_ids=tuple(UUID(str(languages[code]["id"])) for code in ("fr", "en")),
            visibility_scope_id=None,
            source_language_profile_id=UUID(str(languages["fr"]["id"])),
            provider_binding_id=UUID(str(absent["id"])),
        )
        channel_group_one = await topology.create_channel_group(
            guild_id=guild_a,
            group_id=UUID(str(group_one["id"])),
            logical_key=f"stage08-guides-{suffix}",
            display_name="Guides",
            source_language_id=UUID(str(languages["fr"]["id"])),
        )
        channel_group_two = await topology.create_channel_group(
            guild_id=guild_a,
            group_id=UUID(str(group_two["id"])),
            logical_key=f"stage08-support-{suffix}",
            display_name="Support",
            source_language_id=UUID(str(languages["fr"]["id"])),
        )
        variant_plans = 0
        for group, channel_group, codes, label in (
            (group_one, channel_group_one, ("fr", "en", "de", "es"), "guides"),
            (group_two, channel_group_two, ("fr", "en"), "support"),
        ):
            for code in codes:
                draft, replayed, _ = await structural.create_variant_plan(
                    guild_id=guild_a,
                    group_id=UUID(str(group["id"])),
                    actor_user_id=actor,
                    variant_type="CHANNEL",
                    language_profile_id=UUID(str(languages[code]["id"])),
                    desired_name=f"{run_prefix}{label}-{code}".lower(),
                    channel_type=0,
                    translation_channel_group_id=UUID(str(channel_group["id"])),
                    idempotency_key=f"{suffix}-{label}-{code}",
                    correlation_id=uuid4(),
                )
                if replayed:
                    raise RuntimeError("fresh variant plan unexpectedly replayed")
                confirmed = await validate_plan(
                    planning,
                    authorization,
                    draft,
                    actor=actor,
                    key=f"variant-{label}-{code}-{suffix}",
                )
                status = await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_a,
                    actor=actor,
                    plan=confirmed,
                )
                if status != "APPLIED_WITH_PENDING_PROVIDER":
                    raise RuntimeError("provider-backed variant did not remain pending")
                variant_plans += 1
                await refresh_and_publish(guild_a)

        await provider_service.prepare_manual_configuration(
            guild_id=guild_a,
            group_id=UUID(str(group_one["id"])),
            binding_id=UUID(str(present["id"])),
        )
        verified = await provider_service.verify_manual_configuration(
            guild_id=guild_a,
            group_id=UUID(str(group_one["id"])),
            binding_id=UUID(str(present["id"])),
            confirmed_manual_configuration=True,
        )
        if verified["verification_state"] != "VERIFIED":
            raise RuntimeError("present provider was not authoritatively verified")
        ready_group = await topology.get_group(
            guild_id=guild_a, group_id=UUID(str(group_one["id"]))
        )
        routed = await topology.replace_routes(
            guild_id=guild_a,
            group_id=UUID(str(group_one["id"])),
            expected_version=int(ready_group["version"]),
            topology=TranslationGroupTopology.HUB_AND_SPOKE,
            hub_language_id=UUID(str(languages["fr"]["id"])),
            custom_routes=(),
        )
        if len(routed["routes"]) != 6:
            raise RuntimeError("four-language hub-and-spoke routes are incomplete")
        await provider_service.prepare_manual_configuration(
            guild_id=guild_a,
            group_id=UUID(str(group_two["id"])),
            binding_id=UUID(str(absent["id"])),
        )
        absent_preflight, _ = await provider_service.access_preflight(
            guild_id=guild_a,
            group_id=UUID(str(group_two["id"])),
            binding_id=UUID(str(absent["id"])),
        )
        if absent_preflight.allowed or absent_preflight.state != "NOT_INSTALLED":
            raise RuntimeError("absent provider did not fail closed")
        try:
            await provider_service.verify_manual_configuration(
                guild_id=guild_a,
                group_id=UUID(str(group_two["id"])),
                binding_id=UUID(str(absent["id"])),
                confirmed_manual_configuration=True,
            )
        except ValueError:
            pass
        else:
            raise RuntimeError("absent provider unexpectedly became READY")

        rule = (
            {
                "rule_type": "EXPLICIT_DID_MEMBERSHIP",
                "config": {},
                "priority": 1,
                "status": "ACTIVE",
            },
        )
        scope_alpha = await read_models.create_visibility_scope(
            guild_id=guild_a,
            actor_id=actor,
            scope_type=ScopeType.PROJECT,
            scope_key=f"stage08-alpha-{suffix}",
            name="Alpha",
            logical_group_id=None,
            config={},
            rules=rule,
            explicit_member_ids=(actor,),
        )
        scope_beta = await read_models.create_visibility_scope(
            guild_id=guild_a,
            actor_id=actor,
            scope_type=ScopeType.PROJECT,
            scope_key=f"stage08-beta-{suffix}",
            name="Beta",
            logical_group_id=None,
            config={},
            rules=rule,
            explicit_member_ids=(actor,),
        )
        workspace_one = await groups.workspace_group(
            guild_id=guild_a, group_id=UUID(str(group_one["id"]))
        )
        workspace_two = await groups.workspace_group(
            guild_id=guild_a, group_id=UUID(str(group_two["id"]))
        )
        language_codes = {str(row["id"]): code for code, row in languages.items()}
        variants_one = {
            language_codes[str(row["language_profile_id"])]: int(row["discord_channel_id"])
            for row in workspace_one["channel_variants"]
        }
        variants_two = {
            language_codes[str(row["language_profile_id"])]: int(row["discord_channel_id"])
            for row in workspace_two["channel_variants"]
        }

        async def apply_visibility(
            group_id: UUID,
            channel_id: int,
            language_code: str,
            scope_id: UUID,
            key: str,
        ) -> tuple[int, int]:
            await language_service.upsert_resource_policy(
                guild_id=guild_a,
                resource_type="CHANNEL",
                discord_resource_id=channel_id,
                explicit_language_profile_id=UUID(str(languages[language_code]["id"])),
                inherit_language=False,
                visibility_policy="SCOPE_AND_LANGUAGE",
                visibility_scope_id=scope_id,
                custom_policy={},
            )
            draft, replayed, budget = await structural.create_visibility_plan(
                guild_id=guild_a,
                group_id=group_id,
                actor_user_id=actor,
                resource_type="CHANNEL",
                discord_resource_id=channel_id,
                idempotency_key=f"{suffix}-{key}",
                correlation_id=uuid4(),
            )
            if replayed:
                raise RuntimeError("fresh visibility plan unexpectedly replayed")
            operations = await plans.operations(guild_a, UUID(str(draft["id"])))
            confirmed = await validate_plan(
                planning, authorization, draft, actor=actor, key=f"visibility-{key}-{suffix}"
            )
            await apply_plan(
                planning=planning,
                plans=plans,
                runtime=runtime,
                adapter=mutable,
                lock=lock,
                authorization=authorization,
                governor=governor,
                lifecycle=lifecycle,
                guild_id=guild_a,
                actor=actor,
                plan=confirmed,
            )
            return int(budget["role_delta"]), sum(
                str(row["operation_type"]) == "CREATE_ROLE" for row in operations
            )

        first_delta = await apply_visibility(
            UUID(str(group_one["id"])), variants_one["fr"], "fr", scope_alpha, "alpha-fr-one"
        )
        await refresh_and_publish(guild_a)
        reused_delta = await apply_visibility(
            UUID(str(group_two["id"])), variants_two["fr"], "fr", scope_alpha, "alpha-fr-two"
        )
        await refresh_and_publish(guild_a)
        second_delta = await apply_visibility(
            UUID(str(group_one["id"])), variants_one["en"], "en", scope_beta, "beta-en"
        )
        if first_delta != (1, 1) or reused_delta != (0, 0) or second_delta != (1, 1):
            raise RuntimeError("role budget did not prove create/reuse/create")
        await refresh_and_publish(guild_a)
        alpha_binding = await scope_roles.find_binding(
            guild_id=guild_a,
            visibility_scope_id=scope_alpha,
            language_profile_id=UUID(str(languages["fr"]["id"])),
        )
        beta_binding = await scope_roles.find_binding(
            guild_id=guild_a,
            visibility_scope_id=scope_beta,
            language_profile_id=UUID(str(languages["en"]["id"])),
        )
        if alpha_binding is None or beta_binding is None:
            raise RuntimeError("Scope x Language bindings were not materialized")
        technical_ids = {
            int(alpha_binding["discord_role_id"]),
            int(beta_binding["discord_role_id"]),
        }
        roles_a, _ = await resources(structure, governor, guild_a)
        technical_roles = [row for row in roles_a if int(row["role_id"]) in technical_ids]
        if len(technical_roles) != 2 or any(
            int(row["permissions"]) != 0
            or bool(row["hoist"])
            or bool(row["mentionable"])
            or bool(row["managed"])
            for row in technical_roles
        ):
            raise RuntimeError("technical roles do not have safe attributes")

        await language_service.set_member_languages(
            guild_id=guild_a,
            discord_user_id=actor,
            language_ids=(UUID(str(languages["fr"]["id"])), UUID(str(languages["en"]["id"]))),
            source="MANUAL",
        )
        member_draft, replayed, authority_many = await structural.create_member_role_plan(
            guild_id=guild_a,
            member_id=actor,
            actor_user_id=actor,
            idempotency_key=f"{suffix}-many",
            correlation_id=uuid4(),
        )
        if replayed or len(authority_many["assign"]) != 2:
            raise RuntimeError("many-language member plan is incomplete")
        member_plan = await validate_plan(
            planning, authorization, member_draft, actor=actor, key=f"member-many-{suffix}"
        )
        await apply_plan(
            planning=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            lifecycle=lifecycle,
            guild_id=guild_a,
            actor=actor,
            plan=member_plan,
        )
        await refresh_and_publish(guild_a)
        await language_service.set_member_languages(
            guild_id=guild_a,
            discord_user_id=actor,
            language_ids=(),
            source="MANUAL",
        )
        zero_draft, replayed, authority_zero = await structural.create_member_role_plan(
            guild_id=guild_a,
            member_id=actor,
            actor_user_id=actor,
            idempotency_key=f"{suffix}-zero",
            correlation_id=uuid4(),
        )
        if replayed or len(authority_zero["remove"]) != 2:
            raise RuntimeError("zero-language member plan is incomplete")
        zero_plan = await validate_plan(
            planning, authorization, zero_draft, actor=actor, key=f"member-zero-{suffix}"
        )
        await apply_plan(
            planning=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            lifecycle=lifecycle,
            guild_id=guild_a,
            actor=actor,
            plan=zero_plan,
        )
        await language_service.upsert_resource_policy(
            guild_id=guild_a,
            resource_type="CHANNEL",
            discord_resource_id=variants_one["de"],
            explicit_language_profile_id=UUID(str(languages["de"]["id"])),
            inherit_language=False,
            visibility_policy="OPEN_ALL",
            visibility_scope_id=None,
            custom_policy={},
        )
        resolved_open = await language_service.resolve_resource_language(
            guild_id=guild_a, channel_id=variants_one["de"], category_id=None
        )
        if resolved_open["source"] != "SELF":
            raise RuntimeError("open-all resource language did not resolve")
        await refresh_and_publish(guild_a)

        # COPY_AS_NEW deliberately has no destination scope mapping.  Remove the
        # source-only scope references from the portable selection without changing Discord.
        for channel_id in (variants_one["fr"], variants_two["fr"], variants_one["en"]):
            await language_service.upsert_resource_policy(
                guild_id=guild_a,
                resource_type="CHANNEL",
                discord_resource_id=channel_id,
                explicit_language_profile_id=None,
                inherit_language=False,
                visibility_policy="OPEN_ALL",
                visibility_scope_id=None,
                custom_policy={},
            )
        roles_a, channels_a = await resources(structure, governor, guild_a)
        source_before = fixture_hash(roles_a, channels_a, run_prefix)
        portability_repository = PortabilityRepository(
            factory,
            ArtifactCipher(
                InMemoryKeyProvider.from_base64(
                    base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"), version=1
                )
            ),
            metrics=runtime.metrics,
        )
        portability = PortabilityService(
            portability_repository,
            read_models,
            planning,
            plans,
            metrics=runtime.metrics,
            translation_groups=groups,
            translation_policies=policies,
            translation_providers=providers,
            translation_lifecycle=lifecycle,
        )
        artifact, created = await portability.export_live_translation_group(
            source_guild_id=guild_a,
            translation_group_id=UUID(str(group_one["id"])),
            actor_user_id=actor,
            kind=ArtifactKind.EXPORT_BUNDLE,
            name=f"{run_prefix}artifact",
            idempotency_key=f"{suffix}-export",
            correlation_id=uuid4(),
        )
        if not created:
            raise RuntimeError("fresh translation export unexpectedly replayed")
        artifact_id = UUID(str(artifact["id"]))
        artifact_bytes = await portability.export_file(actor, artifact_id)
        lowered = artifact_bytes.lower()
        if b"provider_discord_user_id" in lowered or b"token" in lowered:
            raise RuntimeError("portable artifact contains a forbidden provider fact")
        transfer, destination_draft, _ = await portability.compile_stored(
            actor_user_id=actor,
            artifact_id=artifact_id,
            destination_guild_id=guild_b,
            mode=CloneMode.COPY_AS_NEW,
            explicit_mappings=(),
            idempotency_key=f"{suffix}-copy",
            correlation_id=uuid4(),
        )
        if destination_draft is None:
            raise RuntimeError("fresh clone returned no destination plan")
        destination_plan = await validate_plan(
            planning, authorization, destination_draft, actor=actor, key=f"copy-{suffix}"
        )
        source_calls = mutable.calls[guild_a]
        clone_status = await apply_plan(
            planning=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            lifecycle=lifecycle,
            guild_id=guild_b,
            actor=actor,
            plan=destination_plan,
        )
        if clone_status != "SUCCEEDED" or mutable.calls[guild_a] != source_calls:
            raise RuntimeError("cross-Guild clone touched the source Guild")
        await refresh_and_publish(guild_b)
        finalized = await portability.finalize_transfer(
            actor_user_id=actor,
            transfer_id=UUID(str(transfer["id"])),
            correlation_id=uuid4(),
        )
        topology_result = dict(finalized["local_result_json"])["translation_topology"]
        if (
            topology_result is None
            or topology_result["source_translation_group_id_propagated"]
            or not topology_result["provider_bindings_omitted"]
            or UUID(str(topology_result["translation_group_id"])) == UUID(str(group_one["id"]))
        ):
            raise RuntimeError("destination translation topology is not independent")
        roles_after, channels_after = await resources(structure, governor, guild_a)
        source_after = fixture_hash(roles_after, channels_after, run_prefix)
        if source_before != source_after:
            raise RuntimeError("source fixture changed during destination clone")

        cleanup_plans = 0
        for guild_id in (guild_a, guild_b):
            live_roles, live_channels = await resources(structure, governor, guild_id)
            role_ids = [
                int(row["role_id"])
                for row in live_roles
                if str(row["name"]).upper().startswith(run_prefix.upper())
                and int(row["role_id"]) not in technical_ids
            ]
            channel_ids = [
                int(row["channel_id"])
                for row in live_channels
                if str(row["name"]).upper().startswith(run_prefix.upper())
            ]
            nodes = tuple(
                [
                    DesiredNode.build(
                        logical_key=f"stage08.cleanup.channel.{index}",
                        resource_type=ResourceType.CHANNEL,
                        discord_id=channel_id,
                        presence=NodePresence.ABSENT,
                    )
                    for index, channel_id in enumerate(channel_ids)
                ]
                + [
                    DesiredNode.build(
                        logical_key=f"stage08.cleanup.role.{index}",
                        resource_type=ResourceType.ROLE,
                        discord_id=role_id,
                        presence=NodePresence.ABSENT,
                    )
                    for index, role_id in enumerate(role_ids)
                ]
            )
            if nodes:
                cleanup = await absent_plan(
                    planning,
                    authorization,
                    guild_id=guild_id,
                    actor=actor,
                    nodes=nodes,
                    key=f"cleanup-resources-{guild_id}-{suffix}",
                )
                await apply_plan(
                    planning=planning,
                    plans=plans,
                    runtime=runtime,
                    adapter=mutable,
                    lock=lock,
                    authorization=authorization,
                    governor=governor,
                    lifecycle=lifecycle,
                    guild_id=guild_id,
                    actor=actor,
                    plan=cleanup,
                )
                cleanup_plans += 1
            await refresh_and_publish(guild_id)

        for channel_id in (variants_one["fr"], variants_two["fr"], variants_one["en"]):
            await language_service.upsert_resource_policy(
                guild_id=guild_a,
                resource_type="CHANNEL",
                discord_resource_id=channel_id,
                explicit_language_profile_id=None,
                inherit_language=False,
                visibility_policy="OPEN_ALL",
                visibility_scope_id=None,
                custom_policy={},
            )
        for binding, label in ((alpha_binding, "alpha-fr"), (beta_binding, "beta-en")):
            draft, replayed, evidence = await structural.create_scope_role_cleanup_plan(
                guild_id=guild_a,
                binding_id=UUID(str(binding["id"])),
                actor_user_id=actor,
                idempotency_key=f"{suffix}-{label}",
                correlation_id=uuid4(),
            )
            if (
                replayed
                or evidence["topology_references"] != 0
                or evidence["member_assignees"] != 0
            ):
                raise RuntimeError("technical role cleanup was not proven safe")
            cleanup = await validate_plan(
                planning, authorization, draft, actor=actor, key=f"cleanup-{label}-{suffix}"
            )
            await apply_plan(
                planning=planning,
                plans=plans,
                runtime=runtime,
                adapter=mutable,
                lock=lock,
                authorization=authorization,
                governor=governor,
                lifecycle=lifecycle,
                guild_id=guild_a,
                actor=actor,
                plan=cleanup,
            )
            cleanup_plans += 1
            await refresh_and_publish(guild_a)
        for guild_id in (guild_a, guild_b):
            live_roles, live_channels = await resources(structure, governor, guild_id)
            if any(
                str(row["name"]).upper().startswith(run_prefix.upper())
                for row in (*live_roles, *live_channels)
            ):
                raise RuntimeError("live cleanup left an owned Discord fixture")
        await portability_repository.delete_artifact(actor, artifact_id)
        artifact_id = None
        return (
            {
                "guilds_verified": 2,
                "languages_created": 4,
                "independent_same_pair_groups": 2,
                "variant_plans_applied": variant_plans,
                "provider_present_verified": 1,
                "provider_absent_failed_closed": 1,
                "hub_and_spoke_routes": len(routed["routes"]),
                "scope_language_roles_created": 2,
                "scope_language_roles_reused": 1,
                "member_roles_assigned": 2,
                "member_roles_removed": 2,
                "open_all_paths_verified": 1,
                "destination_translation_groups_created": 1,
                "stage05_plan_mutations": sum(mutable.calls.values()),
                "cleanup_plans_applied": cleanup_plans,
                "stale_technical_roles_recovered": recovered_technical_roles,
                "direct_discord_mutations": 0,
                "message_content_intent": 0,
            },
            {
                "run_prefix_sha256": hashlib.sha256(run_prefix.encode()).hexdigest(),
                "source_before_clone_sha256": source_before,
                "source_after_clone_sha256": source_after,
                "portable_artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            },
        )
    finally:
        if (
            artifact_id is not None
            and portability_repository is not None
            and client.user is not None
        ):
            with suppress(Exception):
                await portability_repository.delete_artifact(int(client.user.id), artifact_id)
        await client.close()
        await member_client.aclose()
        await redis.aclose()
        await engine.dispose()
        await admin_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 08 multilingual Discord live validation")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()
    load_local_environment(Path(".env.local"))
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if not arguments.include:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=missing,
            blocker="live validation was not explicitly requested",
        )
        return 0
    if missing:
        write_report(
            arguments.report,
            status="BLOCKED_LIVE_CREDENTIALS",
            checks=["all non-live gates remain independently executable"],
            missing=missing,
            blocker="required Discord sandbox credentials are unavailable",
        )
        return 2
    try:
        counts, hashes = asyncio.run(run_live())
    except LiveCapabilityBlocked as exc:
        capabilities = list(getattr(exc, "capabilities", ()))
        blocker = (
            f"required Discord permission unavailable for the control-plane bot: "
            f"{', '.join(capabilities)}"
            if capabilities
            else "required Discord privileged intent or permissions are unavailable"
        )
        write_report(
            arguments.report,
            status="BLOCKED_CAPABILITY_CONFIGURATION",
            checks=["live sandbox configuration failed closed"],
            missing=[],
            blocker=blocker,
            missing_capabilities=capabilities,
        )
        return 3
    except Exception as exc:
        write_report(
            arguments.report,
            status="FAIL",
            checks=[type(exc).__name__],
            missing=[],
            blocker="live Discord sandbox validation failed closed",
        )
        raise
    write_report(
        arguments.report,
        status="PASS",
        checks=[
            "all Discord REST reads and plan mutations traversed the workload governor",
            "two independent groups exercised FR/EN and FR/EN/DE/ES variants",
            "provider-present verification used authoritative bot and permission facts",
            "provider-absent manual verification failed closed",
            "Scope x Language roles were created lazily, reused, and permissionless",
            "many-language, zero-language, and open-all paths were exercised",
            "the Stage 06 to Stage 05 clone created an independent Guild B topology",
            "provider bindings, provider identity, tokens, and source IDs were omitted",
            "source fixture hashes remained identical across the clone",
            "owned fixtures and safe technical bindings were deleted through plans",
        ],
        missing=[],
        counts=counts,
        hashes=hashes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
