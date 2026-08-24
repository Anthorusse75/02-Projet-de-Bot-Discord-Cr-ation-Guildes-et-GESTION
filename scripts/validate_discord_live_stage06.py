from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import discord
from redis.asyncio import Redis

from did.application.auth import AuthorizationService
from did.application.planning import ApplyActorAuthorizer, PlanningService
from did.application.portability import ArtifactKind, PortabilityService
from did.cloning import ArtifactSelection
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
from did.oauth.discord import HttpDiscordMemberClient
from did.oauth.models import DiscordGuild
from did.oauth.stores import RedisActorMembershipStore, RedisGuildDiscoveryStore
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)
from did.portability import (
    ArtifactCipher,
    ArtifactType,
    CloneMode,
    ExplicitMapping,
    InMemoryKeyProvider,
    PortableResourceType,
)
from did.worker.io.governor import DiscordWorkloadGovernor
from validate_discord_live_stage05 import (
    CachedGuildAuthContext,
    CountingAdapter,
    LiveCapabilityBlocked,
    apply_with_optional_crash,
    create_validated_plan,
    seed_snapshot,
)

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
PREFIX = "DID-STAGE06-TEST-"


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
                "stage": "06",
                "profile": "discord-live-cross-guild-portability",
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


class GuildCountingAdapter(CountingAdapter):
    def __init__(self, delegate: DiscordPyMutableAdapter) -> None:
        super().__init__(delegate)
        self.calls: Counter[int] = Counter()

    async def execute(self, **kwargs: Any) -> Any:
        self.calls[int(kwargs["guild_id"])] += 1
        return await super().execute(**kwargs)


class DestinationOnlyReadModels:
    def __init__(self, delegate: Stage04Repository, source_guild_id: int) -> None:
        self.delegate = delegate
        self.source_guild_id = source_guild_id

    async def guild_snapshot(self, guild_id: int, member_id: int) -> Any:
        if guild_id == self.source_guild_id:
            raise AssertionError("SOURCE_READ_AFTER_EXPORT")
        return await self.delegate.guild_snapshot(guild_id, member_id)


def prefixed_snapshot(roles: list[dict[str, Any]], channels: list[dict[str, Any]]) -> str:
    selected = {
        "roles": sorted(
            (
                {
                    "id": str(item["role_id"]),
                    "name": str(item["name"]),
                    "permissions": str(item["permissions"]),
                }
                for item in roles
                if str(item["name"]).upper().startswith(PREFIX)
            ),
            key=lambda item: str(item["id"]),
        ),
        "channels": sorted(
            (
                {
                    "id": str(item["channel_id"]),
                    "name": str(item["name"]),
                    "type": int(item["type"]),
                    "parent_id": str(item["parent_id"]) if item.get("parent_id") else None,
                }
                for item in channels
                if str(item["name"]).upper().startswith(PREFIX)
            ),
            key=lambda item: str(item["id"]),
        ),
    }
    return json.dumps(selected, sort_keys=True, separators=(",", ":"))


async def refresh_discovery(
    store: RedisGuildDiscoveryStore,
    actor: int,
    client: discord.Client,
    guild_ids: tuple[int, int],
) -> None:
    guilds = []
    for guild_id in guild_ids:
        guild = await client.fetch_guild(guild_id)
        guilds.append(
            DiscordGuild(
                guild_id=guild_id,
                name=guild.name,
                icon_hash=None,
                owner=guild.owner_id == actor,
                permissions=0,
            )
        )
    await store.put(actor, tuple(guilds))


async def cleanup_prefix(
    *,
    guild_id: int,
    suffix: str,
    structure: DiscordPyStructureAdapter,
    planning: PlanningService,
    plans: PlanningRepository,
    runtime: RuntimeRepository,
    adapter: GuildCountingAdapter,
    lock: RedisGuildMutationLock,
    authorization: ApplyActorAuthorizer,
    governor: DiscordWorkloadGovernor,
    admin_engine: Any,
    actor: int,
) -> int:
    roles = [
        item
        for item in await structure.fetch_roles(guild_id)
        if str(item["name"]).upper().startswith(PREFIX)
    ]
    channels = [
        item
        for item in await structure.fetch_channels(guild_id)
        if str(item["name"]).upper().startswith(PREFIX)
    ]
    if not roles and not channels:
        return 0
    category_keys = {
        int(item["channel_id"]): f"stage06.cleanup.category.{index}"
        for index, item in enumerate(channels)
        if int(item["type"]) == 4
    }
    nodes = [
        DesiredNode.build(
            logical_key=f"stage06.cleanup.role.{index}",
            resource_type=ResourceType.ROLE,
            discord_id=int(item["role_id"]),
            presence=NodePresence.ABSENT,
        )
        for index, item in enumerate(roles)
    ]
    for index, item in enumerate(channels):
        channel_id = int(item["channel_id"])
        parent_id = item.get("parent_id")
        relations = None
        if parent_id is not None and int(parent_id) in category_keys:
            relations = {
                "parent": ResourceReference(ReferenceKind.LOGICAL, category_keys[int(parent_id)])
            }
        nodes.append(
            DesiredNode.build(
                logical_key=category_keys.get(channel_id, f"stage06.cleanup.channel.{index}"),
                resource_type=(
                    ResourceType.CATEGORY if int(item["type"]) == 4 else ResourceType.CHANNEL
                ),
                discord_id=channel_id,
                presence=NodePresence.ABSENT,
                relations=relations,
            )
        )
    plan = await create_validated_plan(
        planning,
        graph=DesiredStateGraph(guild_id, tuple(nodes)),
        actor=actor,
        key=f"stage06-cleanup-{guild_id}-{suffix}-{uuid4()}",
        authorization=authorization,
    )
    await apply_with_optional_crash(
        service=planning,
        plans=plans,
        runtime=runtime,
        adapter=adapter,
        lock=lock,
        authorization=authorization,
        governor=governor,
        admin_engine=admin_engine,
        guild_id=guild_id,
        actor=actor,
        plan=plan,
        inject_crash=False,
    )
    return len(roles) + len(channels)


async def run_live() -> dict[str, int]:
    guild_a = int(os.environ["DISCORD_TEST_GUILD_A_ID"])
    guild_b = int(os.environ["DISCORD_TEST_GUILD_B_ID"])
    if guild_a == guild_b:
        raise RuntimeError("STAGE 06 live validation requires two distinct sandbox Guilds")
    suffix = datetime.now(UTC).strftime("%H%M%S%f")[-10:]
    role_name = f"{PREFIX}ROLE-{suffix}"
    category_name = f"{PREFIX}CATEGORY-{suffix}"
    channel_names = (
        f"{PREFIX}ONE-{suffix}".lower(),
        f"{PREFIX}TWO-{suffix}".lower(),
    )
    engine = create_database_engine(APP_URL, pool_size=4)
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    redis: Redis = create_redis_client(REDIS_URL)
    client = discord.Client(intents=discord.Intents.none())
    member_client = HttpDiscordMemberClient(bot_token=os.environ["DISCORD_BOT_TOKEN"])
    artifact_id: UUID | None = None
    repository: PortabilityRepository | None = None
    actor: int | None = None
    cleanup_count = 0
    try:
        await client.login(os.environ["DISCORD_BOT_TOKEN"])
        factory = create_session_factory(engine)
        runtime = RuntimeRepository(factory)
        plans = PlanningRepository(factory)
        auth_repository = AuthRepository(factory)
        read_models = Stage04Repository(factory)
        planning = PlanningService(plans, read_models)
        structure = DiscordPyStructureAdapter(client)
        mutable = GuildCountingAdapter(DiscordPyMutableAdapter(client))
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
            max_queue_depth=32,
            distributed_coordinator=RedisDiscordWorkloadCoordinator(
                redis,
                global_concurrency=2,
                per_guild_concurrency=1,
                permit_ttl_seconds=30,
            ),
        )
        for guild_id in (guild_a, guild_b):
            actor = await seed_snapshot(
                guild_id=guild_id,
                client=client,
                structure=structure,
                runtime=runtime,
                auth_repository=auth_repository,
                guild_store=guild_store,
                admin_engine=admin_engine,
            )
        assert actor is not None
        await refresh_discovery(guild_store, actor, client, (guild_a, guild_b))
        for guild_id in (guild_a, guild_b):
            cleanup_count += await cleanup_prefix(
                guild_id=guild_id,
                suffix=f"pre-{suffix}",
                structure=structure,
                planning=planning,
                plans=plans,
                runtime=runtime,
                adapter=mutable,
                lock=lock,
                authorization=authorization,
                governor=governor,
                admin_engine=admin_engine,
                actor=actor,
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
        await refresh_discovery(guild_store, actor, client, (guild_a, guild_b))

        graph = DesiredStateGraph(
            guild_a,
            (
                DesiredNode.build(
                    logical_key="stage06.source.role",
                    resource_type=ResourceType.ROLE,
                    symbol="stage06.source.role.symbol",
                    properties={"name": role_name, "permissions": "0"},
                ),
                DesiredNode.build(
                    logical_key="stage06.source.category",
                    resource_type=ResourceType.CATEGORY,
                    symbol="stage06.source.category.symbol",
                    properties={"name": category_name},
                ),
                *(
                    DesiredNode.build(
                        logical_key=f"stage06.source.channel.{index}",
                        resource_type=ResourceType.CHANNEL,
                        symbol=f"stage06.source.channel.{index}.symbol",
                        properties={"name": name, "type": 0},
                    )
                    for index, name in enumerate(channel_names)
                ),
            ),
        )
        source_plan = await create_validated_plan(
            planning,
            graph=graph,
            actor=actor,
            key=f"stage06-source-{suffix}",
            authorization=authorization,
        )
        await apply_with_optional_crash(
            service=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_a,
            actor=actor,
            plan=source_plan,
            inject_crash=False,
        )
        await seed_snapshot(
            guild_id=guild_a,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        await seed_snapshot(
            guild_id=guild_b,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        await refresh_discovery(guild_store, actor, client, (guild_a, guild_b))
        roles_a = await structure.fetch_roles(guild_a)
        channels_a = await structure.fetch_channels(guild_a)
        source_role = next(item for item in roles_a if item["name"] == role_name)
        source_category = next(item for item in channels_a if item["name"] == category_name)
        source_channels = [
            next(item for item in channels_a if item["name"] == channel_name)
            for channel_name in channel_names
        ]
        overwrite_graph = DesiredStateGraph(
            guild_a,
            (
                DesiredNode.build(
                    logical_key="stage06.source.role",
                    resource_type=ResourceType.ROLE,
                    discord_id=int(source_role["role_id"]),
                    properties={"name": role_name, "permissions": "0"},
                ),
                DesiredNode.build(
                    logical_key="stage06.source.category",
                    resource_type=ResourceType.CATEGORY,
                    discord_id=int(source_category["channel_id"]),
                    properties={"name": category_name, "type": 4},
                ),
                *(
                    DesiredNode.build(
                        logical_key=f"stage06.source.channel.{index}",
                        resource_type=ResourceType.CHANNEL,
                        discord_id=int(channel["channel_id"]),
                        properties={"name": channel["name"], "type": 0},
                        relations={
                            "parent": ResourceReference(
                                ReferenceKind.LOGICAL, "stage06.source.category"
                            )
                        },
                    )
                    for index, channel in enumerate(source_channels)
                ),
                DesiredNode.build(
                    logical_key="stage06.source.overwrite",
                    resource_type=ResourceType.OVERWRITE,
                    properties={"target_type": 0, "allow": "1024", "deny": "0"},
                    relations={
                        "channel": ResourceReference(
                            ReferenceKind.LOGICAL, "stage06.source.channel.0"
                        ),
                        "subject": ResourceReference(ReferenceKind.LOGICAL, "stage06.source.role"),
                    },
                ),
            ),
        )
        overwrite_plan = await create_validated_plan(
            planning,
            graph=overwrite_graph,
            actor=actor,
            key=f"stage06-source-overwrite-{suffix}",
            authorization=authorization,
        )
        await apply_with_optional_crash(
            service=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_a,
            actor=actor,
            plan=overwrite_plan,
            inject_crash=False,
        )
        await seed_snapshot(
            guild_id=guild_a,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        roles_a = await structure.fetch_roles(guild_a)
        channels_a = await structure.fetch_channels(guild_a)
        source_before = prefixed_snapshot(roles_a, channels_a)

        repository = PortabilityRepository(
            factory,
            ArtifactCipher(
                InMemoryKeyProvider.from_base64(
                    base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"), version=1
                )
            ),
            metrics=runtime.metrics,
        )
        portability = PortabilityService(
            repository, read_models, planning, plans, metrics=runtime.metrics
        )
        artifact_row, _ = await portability.export_live(
            source_guild_id=guild_a,
            actor_user_id=actor,
            selection=ArtifactSelection(
                ArtifactType.CATEGORY,
                category_ids=(int(source_category["channel_id"]),),
            ),
            kind=ArtifactKind.EXPORT_BUNDLE,
            name=f"{PREFIX}ARTIFACT-{suffix}",
            idempotency_key=f"stage06-export-{suffix}",
            correlation_id=uuid4(),
        )
        artifact_id = UUID(str(artifact_row["id"]))
        transfer, destination_plan, _ = await portability.compile_stored(
            actor_user_id=actor,
            artifact_id=artifact_id,
            destination_guild_id=guild_b,
            mode=CloneMode.COPY_AS_NEW,
            explicit_mappings=(),
            idempotency_key=f"stage06-copy-{suffix}",
            correlation_id=uuid4(),
        )
        await repository.audit_boundary(
            guild_id=guild_a,
            actor_user_id=actor,
            transfer_id=UUID(str(transfer["id"])),
            event_type="CROSS_GUILD_SOURCE_EXPORTED",
            artifact_hash=str(transfer["artifact_content_hash"]),
            correlation_id=uuid4(),
        )
        destination_plan = await create_validated_plan_from_draft(
            planning,
            authorization,
            destination_plan,
            actor=actor,
            key=f"stage06-copy-{suffix}",
        )
        source_calls_before_clone = mutable.calls[guild_a]
        await apply_with_optional_crash(
            service=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_b,
            actor=actor,
            plan=destination_plan,
            inject_crash=False,
        )
        if mutable.calls[guild_a] != source_calls_before_clone:
            raise RuntimeError("cross-Guild clone mutated the source Guild")
        await seed_snapshot(
            guild_id=guild_b,
            client=client,
            structure=structure,
            runtime=runtime,
            auth_repository=auth_repository,
            guild_store=guild_store,
            admin_engine=admin_engine,
        )
        roles_b = await structure.fetch_roles(guild_b)
        channels_b = await structure.fetch_channels(guild_b)
        destination_role = next(item for item in roles_b if item["name"] == role_name)
        destination_category = next(item for item in channels_b if item["name"] == category_name)
        if int(destination_role["role_id"]) == int(source_role["role_id"]):
            raise RuntimeError("destination role reused a source Discord ID")
        if int(destination_category["channel_id"]) == int(source_category["channel_id"]):
            raise RuntimeError("destination category reused a source Discord ID")

        _, portable_artifact = await repository.get_artifact(actor, artifact_id)
        role_ref = next(
            item.logical_key
            for item in portable_artifact.resources
            if item.resource_type is PortableResourceType.ROLE
        )
        destination_only = DestinationOnlyReadModels(read_models, guild_a)
        stored_service = PortabilityService(
            repository,
            destination_only,  # type: ignore[arg-type]
            planning,
            plans,
            metrics=runtime.metrics,
        )
        _, stored_plan, _ = await stored_service.compile_stored(
            actor_user_id=actor,
            artifact_id=artifact_id,
            destination_guild_id=guild_b,
            mode=CloneMode.COPY_AS_NEW,
            explicit_mappings=(
                ExplicitMapping(
                    role_ref,
                    guild_b,
                    str(destination_role["role_id"]),
                    PortableResourceType.ROLE,
                    True,
                ),
            ),
            idempotency_key=f"stage06-stored-{suffix}",
            correlation_id=uuid4(),
        )
        stored_plan = await create_validated_plan_from_draft(
            planning,
            authorization,
            stored_plan,
            actor=actor,
            key=f"stage06-stored-{suffix}",
        )
        await apply_with_optional_crash(
            service=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            guild_id=guild_b,
            actor=actor,
            plan=stored_plan,
            inject_crash=False,
        )
        source_after = prefixed_snapshot(
            await structure.fetch_roles(guild_a), await structure.fetch_channels(guild_a)
        )
        if source_after != source_before:
            raise RuntimeError("source structure changed during destination cloning")

        cleanup_count += await cleanup_prefix(
            guild_id=guild_b,
            suffix=f"post-b-{suffix}",
            structure=structure,
            planning=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            actor=actor,
        )
        cleanup_count += await cleanup_prefix(
            guild_id=guild_a,
            suffix=f"post-a-{suffix}",
            structure=structure,
            planning=planning,
            plans=plans,
            runtime=runtime,
            adapter=mutable,
            lock=lock,
            authorization=authorization,
            governor=governor,
            admin_engine=admin_engine,
            actor=actor,
        )
        await repository.delete_artifact(actor, artifact_id)
        artifact_id = None
        for guild_id in (guild_a, guild_b):
            if any(
                str(item["name"]).upper().startswith(PREFIX)
                for item in await structure.fetch_roles(guild_id)
            ) or any(
                str(item["name"]).upper().startswith(PREFIX)
                for item in await structure.fetch_channels(guild_id)
            ):
                raise RuntimeError("STAGE 06 live cleanup left a prefixed resource")
        return {
            "source_fixture_resources": 4,
            "destination_copy_plans": 2,
            "explicit_role_mappings": 1,
            "new_destination_ids_verified": 2,
            "source_mutations_during_clone": 0,
            "source_read_after_export": 0,
            "cleanup_resources": cleanup_count,
            "artifacts_purged": 1,
        }
    finally:
        if artifact_id is not None and actor is not None:
            try:
                if repository is not None:
                    await repository.delete_artifact(actor, artifact_id)
            except Exception:
                artifact_id = None
        await client.close()
        await member_client.aclose()
        await redis.aclose()
        await engine.dispose()
        await admin_engine.dispose()


async def create_validated_plan_from_draft(
    service: PlanningService,
    authorization: ApplyActorAuthorizer,
    plan: dict[str, Any],
    *,
    actor: int,
    key: str,
) -> dict[str, Any]:
    guild_id = int(plan["guild_id"])
    plan_id = UUID(str(plan["id"]))
    correlation_id = uuid4()
    await authorization.authorize_apply(guild_id=guild_id, actor_user_id=actor)
    validated, preflight = await service.validate(
        guild_id=guild_id,
        plan_id=plan_id,
        actor_user_id=actor,
        expected_version=int(plan["state_version"]),
        correlation_id=correlation_id,
        actor_authorization_fresh=True,
    )
    if not preflight.allowed:
        if all(error.startswith("capability.permission_missing") for error in preflight.errors):
            raise LiveCapabilityBlocked("sandbox bot lacks structural mutation capabilities")
        raise RuntimeError(f"live portability preflight blocked: {','.join(preflight.errors)}")
    return await service.confirm(
        guild_id=guild_id,
        plan_id=plan_id,
        actor_user_id=actor,
        idempotency_key=f"{key}-confirm",
        expected_version=int(validated["state_version"]),
        supplied_plan_hash=str(validated["plan_hash"]),
        reinforced_acknowledgement=True,
        correlation_id=correlation_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 06 cross-Guild live validation")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()
    load_local_environment(Path(".env.local"))
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    skipped = [
        "live RECONCILE is not forced; exact bounded delete scope is integration-tested",
        "bot/webhook incompatibilities are security-tested without unsafe live fixtures",
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
            checks=["source/destination cache seeded", "plan preflight failed closed"],
            missing=[],
            skipped=skipped,
            counts={"discord_mutations_after_denial": 0},
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
            "source fixtures created only by STAGE 05 plan",
            "LIVE export produced immutable encrypted artifact",
            "Dependency Graph and Mapping Resolver compiled a destination-only plan",
            "COPY_AS_NEW created distinct destination Discord IDs",
            "explicit existing-role mapping was confirmed",
            "stored artifact compiled and applied with source reader fail-if-called",
            "source snapshot remained byte-identical during destination clones",
            "mutable adapter recorded zero source calls during clone",
            "source and destination cleanup used audited STAGE 05 plans",
            "artifact and owned transfers were purged",
        ],
        missing=[],
        skipped=skipped,
        counts=counts,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
