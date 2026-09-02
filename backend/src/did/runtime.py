import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid4

import discord

from did.application.auth import AuthorizationService
from did.application.lifecycle import run_until_stopped
from did.application.planning import ApplyActorAuthorizer, PlanningService
from did.application.reconciliation import (
    AdaptiveReconcilePolicy,
    DiscordSyncService,
    ReconcileScheduler,
)
from did.application.translation.lifecycle import Stage08PostVerificationMaterializer
from did.bot.gateway import DiscordGatewayClient
from did.campaigns.authorization import CampaignGuildAuthorizationChecker
from did.campaigns.dispatch import CampaignDeliveryExecutor
from did.campaigns.reconciliation_runtime import CampaignDeliveryReconciliationRuntime
from did.campaigns.runtime import CampaignSchedulerRuntime
from did.infrastructure.auth_repository import AuthRepository
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.discord import DiscordPyMutableAdapter, DiscordPyStructureAdapter
from did.infrastructure.discord_message_sender import DiscordPyMessageSender
from did.infrastructure.logging import EventId, configure_logging, emit_event
from did.infrastructure.planning_lock import RedisGuildMutationLock
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import (
    OutboxPublisher,
    RedisDiscordWorkloadCoordinator,
    RedisHotCache,
    RedisRuntimeWakeup,
    RedisSingleFlight,
    TenantPubSub,
)
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)
from did.oauth.discord import HttpDiscordMemberClient
from did.oauth.stores import (
    RedisActorMembershipStore,
)
from did.permissions.capabilities import BotCapabilityChecker
from did.settings import Settings
from did.translation.google_translate_rpc_adapter import (
    GoogleTranslateRpcCampaignTranslationProvider,
)
from did.worker.io import (
    ApplyPlanExecutor,
    DiscordWorkerRuntime,
    DiscordWorkloadGovernor,
    DurableDiscordIOWorker,
)


async def run_process(
    process_name: str,
    *,
    configured_settings: Settings | None = None,
    external_stop_event: asyncio.Event | None = None,
) -> None:
    settings = configured_settings or Settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    stop_event = external_stop_event or asyncio.Event()
    background_task: asyncio.Task[None] | None = None
    close_runtime: Callable[[], Awaitable[None]] | None = None
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:  # Windows event loops do not expose POSIX handlers.
            pass

    async def background_failure() -> BaseException | None:
        if background_task is None:
            return None
        result = (await asyncio.gather(background_task, return_exceptions=True))[0]
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            return result
        return None

    async def on_start() -> None:
        nonlocal background_task, close_runtime
        emit_event(
            logger,
            logging.INFO,
            EventId.PROCESS_STARTED,
            fields={"process": process_name},
        )
        if process_name == "bot" and settings.discord_bot_token is not None:
            engine = create_database_engine(settings.database_url.get_secret_value())
            repository = RuntimeRepository(create_session_factory(engine))
            gateway_client = DiscordGatewayClient(
                repository,
                enable_member_events=settings.discord_member_events_enabled,
                enable_campaign_message_events=settings.discord_campaign_message_events_enabled,
            )
            background_task = asyncio.create_task(
                gateway_client.start(settings.discord_bot_token.get_secret_value()),
                name="discord-gateway",
            )
            background_task.add_done_callback(lambda _: stop_event.set())

            async def close_bot() -> None:
                await gateway_client.close()
                failure = await background_failure()
                await engine.dispose()
                if failure is not None:
                    raise failure

            close_runtime = close_bot
        elif process_name == "worker":
            if settings.discord_bot_token is None:
                raise RuntimeError("worker requires a configured Discord bot token")
            engine = create_database_engine(settings.database_url.get_secret_value())
            redis = create_redis_client(settings.redis_url.get_secret_value())
            rest_client = discord.Client(intents=discord.Intents.none())
            worker_member: HttpDiscordMemberClient | None = None
            try:
                await rest_client.login(settings.discord_bot_token.get_secret_value())
                session_factory = create_session_factory(engine)
                repository = RuntimeRepository(session_factory)
                auth_repository = AuthRepository(session_factory)
                worker_member = HttpDiscordMemberClient(
                    bot_token=settings.discord_bot_token.get_secret_value()
                )
                worker_authorization = AuthorizationService(
                    auth=None,
                    repository=auth_repository,
                    membership_store=RedisActorMembershipStore(
                        redis, ttl_seconds=settings.authorization_freshness_seconds
                    ),
                    member_client=worker_member,
                    freshness_seconds=settings.authorization_freshness_seconds,
                    membership_singleflight=RedisSingleFlight(redis),
                    metrics=repository.metrics,
                )
                hot_cache = RedisHotCache(redis, metrics=repository.metrics)
                worker_id = f"worker-{uuid4().hex}"
                wakeup = RedisRuntimeWakeup(redis, reporter_id=worker_id)
                coordinator = RedisDiscordWorkloadCoordinator(
                    redis,
                    global_concurrency=settings.discord_global_concurrency,
                    per_guild_concurrency=settings.discord_per_guild_concurrency,
                    permit_ttl_seconds=settings.discord_distributed_permit_ttl_seconds,
                )
                governor = DiscordWorkloadGovernor(
                    global_concurrency=settings.discord_global_concurrency,
                    per_guild_concurrency=settings.discord_per_guild_concurrency,
                    max_queue_depth=settings.discord_workload_queue_limit,
                    distributed_coordinator=coordinator,
                )
                sync = DiscordSyncService(
                    adapter=DiscordPyStructureAdapter(rest_client),
                    repository=repository,
                    singleflight=RedisSingleFlight(redis),
                )
                planning_repository = PlanningRepository(session_factory)
                planning_service = PlanningService(
                    planning_repository,
                    Stage04Repository(session_factory),
                )
                campaigns_repository = CampaignsRepository(session_factory)
                message_sender = DiscordPyMessageSender(rest_client)
                worker = DurableDiscordIOWorker(
                    repository,
                    sync,
                    worker_id=worker_id,
                    lease_seconds=settings.discord_job_lease_seconds,
                    plan_executor=ApplyPlanExecutor(
                        planning_repository,
                        DiscordPyMutableAdapter(rest_client),
                        RedisGuildMutationLock(
                            redis,
                            ttl_seconds=settings.discord_job_lease_seconds,
                        ),
                        worker_id=worker_id,
                        authorization=ApplyActorAuthorizer(worker_authorization),
                        preflight=planning_service,
                        post_verification=Stage08PostVerificationMaterializer(
                            Stage08LifecycleRepository(session_factory)
                        ),
                    ),
                    campaign_delivery_executor=CampaignDeliveryExecutor(
                        campaigns_repository,
                        message_sender,
                        worker_id=worker_id,
                    ),
                )
                runtime = DiscordWorkerRuntime(
                    repository=repository,
                    worker=worker,
                    governor=governor,
                    outbox=OutboxPublisher(
                        repository,
                        TenantPubSub(redis),
                        hot_cache=hot_cache,
                        wakeup=wakeup,
                        publisher_id=worker_id,
                        lease_seconds=settings.discord_job_lease_seconds,
                    ),
                    wakeup=wakeup,
                    poll_interval_seconds=settings.discord_worker_poll_seconds,
                    recovery_interval_seconds=settings.discord_worker_recovery_seconds,
                    routing_batch_size=settings.discord_runtime_routing_batch_size,
                    dispatch_batch_size=settings.discord_worker_dispatch_batch_size,
                )
                # REQ-MSG-029: the same worker process also drains stalled/
                # ambiguous campaign deliveries (reconcile_one_stalled_delivery
                # was previously a complete, tested primitive nothing ever
                # called) -- runs alongside the durable job worker loop above
                # rather than as a separate, uncoordinated process type.
                reconciliation_runtime = CampaignDeliveryReconciliationRuntime(
                    campaigns_repository=campaigns_repository,
                    runtime_repository=repository,
                    sender=message_sender,
                    lease_owner=worker_id,
                    poll_interval_seconds=settings.discord_worker_recovery_seconds,
                )

                async def run_worker_and_reconciler() -> None:
                    await asyncio.gather(
                        runtime.run(stop_event), reconciliation_runtime.run(stop_event)
                    )

                background_task = asyncio.create_task(
                    run_worker_and_reconciler(), name="discord-worker-and-campaign-reconciler"
                )
                background_task.add_done_callback(lambda _: stop_event.set())
            except Exception:
                await rest_client.close()
                if worker_member is not None:
                    await worker_member.aclose()
                await redis.aclose()
                await engine.dispose()
                raise

            async def close_worker() -> None:
                stop_event.set()
                failure = await background_failure()
                await rest_client.close()
                if worker_member is not None:
                    await worker_member.aclose()
                await redis.aclose()
                await engine.dispose()
                if failure is not None:
                    raise failure

            close_runtime = close_worker
        elif process_name == "scheduler":
            engine = create_database_engine(settings.database_url.get_secret_value())
            redis = create_redis_client(settings.redis_url.get_secret_value())
            session_factory = create_session_factory(engine)
            repository = RuntimeRepository(session_factory)
            scheduler = ReconcileScheduler(
                repository,
                AdaptiveReconcilePolicy(
                    active_target=timedelta(seconds=settings.reconcile_active_target_seconds),
                    inactive_target=timedelta(seconds=settings.reconcile_inactive_target_seconds),
                ),
                wakeup=RedisRuntimeWakeup(redis),
                poll_interval_seconds=settings.reconcile_scheduler_poll_seconds,
                routing_batch_size=settings.discord_runtime_routing_batch_size,
            )
            runners: list[Awaitable[None]] = [scheduler.run(stop_event)]
            scheduler_member: HttpDiscordMemberClient | None = None
            admin_engine = None
            if settings.discord_bot_token is not None:
                # Stage09 campaign scheduling shares the exact same
                # live-authorization contract the "worker" process already
                # needs (a re-checked Guild capability/bot-can-send, never a
                # cached value) -- see did.campaigns.authorization
                # .CampaignGuildAuthorizationChecker. Without a configured
                # bot token, only the pre-existing structural
                # ReconcileScheduler runs, exactly as before this pass.
                admin_engine = create_database_engine(
                    settings.database_admin_url.get_secret_value()
                )
                admin_factory = create_session_factory(admin_engine)
                campaigns_repository = CampaignsRepository(session_factory)
                scheduler_member = HttpDiscordMemberClient(
                    bot_token=settings.discord_bot_token.get_secret_value()
                )
                scheduler_authorization = AuthorizationService(
                    auth=None,
                    repository=AuthRepository(session_factory),
                    membership_store=RedisActorMembershipStore(
                        redis, ttl_seconds=settings.authorization_freshness_seconds
                    ),
                    member_client=scheduler_member,
                    freshness_seconds=settings.authorization_freshness_seconds,
                    membership_singleflight=RedisSingleFlight(redis),
                    metrics=repository.metrics,
                )
                campaign_scheduler = CampaignSchedulerRuntime(
                    campaigns_repository=campaigns_repository,
                    runtime_repository=repository,
                    admin_factory=admin_factory,
                    language_profiles=LanguageProfileRepository(session_factory),
                    translation_groups=TranslationGroupRepository(session_factory),
                    checker=CampaignGuildAuthorizationChecker(
                        authorization=scheduler_authorization,
                        read_models=Stage04Repository(session_factory),
                        bot_checker=BotCapabilityChecker(),
                        translation_groups=TranslationGroupRepository(session_factory),
                    ),
                    translation_provider=GoogleTranslateRpcCampaignTranslationProvider(),
                    lease_owner=f"campaign-scheduler-{uuid4().hex}",
                    stage04_repository=Stage04Repository(session_factory),
                    provider_bindings=TranslationProviderBindingRepository(session_factory),
                    poll_interval_seconds=settings.reconcile_scheduler_poll_seconds,
                )
                runners.append(campaign_scheduler.run(stop_event))

            async def run_schedulers() -> None:
                await asyncio.gather(*runners)

            background_task = asyncio.create_task(
                run_schedulers(), name="campaign-and-reconcile-scheduler"
            )
            background_task.add_done_callback(lambda _: stop_event.set())

            async def close_scheduler() -> None:
                stop_event.set()
                failure = await background_failure()
                if scheduler_member is not None:
                    await scheduler_member.aclose()
                if admin_engine is not None:
                    await admin_engine.dispose()
                await redis.aclose()
                await engine.dispose()
                if failure is not None:
                    raise failure

            close_runtime = close_scheduler
        elif process_name not in {"api", "bot"}:
            raise ValueError(f"unsupported process: {process_name}")

    async def on_stop() -> None:
        if close_runtime is not None:
            await close_runtime()
        emit_event(
            logger,
            logging.INFO,
            EventId.PROCESS_STOPPED,
            fields={"process": process_name},
        )

    await run_until_stopped(stop_event, on_start=on_start, on_stop=on_stop)


def main(process_name: str) -> None:
    try:
        asyncio.run(run_process(process_name))
    except KeyboardInterrupt:
        return
