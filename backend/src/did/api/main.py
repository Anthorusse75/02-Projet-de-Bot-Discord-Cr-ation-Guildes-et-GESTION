import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from did.api.auth import problem_response
from did.api.auth import router as auth_router
from did.api.dependencies import ApiProblem, ServiceContainer
from did.api.guilds import authorization_problem
from did.api.guilds import router as guilds_router
from did.api.health import ReadinessProbes
from did.api.health import router as health_router
from did.api.me import router as me_router
from did.api.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from did.api.runtime_cache import guild_events_socket
from did.api.runtime_cache import router as runtime_cache_router
from did.api.stage04 import router as stage04_router
from did.api.stage05 import invalid_planning_input
from did.api.stage05 import router as stage05_router
from did.api.stage06 import router as stage06_router
from did.api.stage07 import router as stage07_router
from did.api.stage08 import router as stage08_router
from did.application.auth import AuthorizationService, AuthService
from did.application.auth.service import AuthorizationDenied
from did.application.installations import InstallationService
from did.application.planning import PlanningService
from did.application.portability import PortabilityService
from did.application.translation import LanguageProfileService, TranslationTopologyService
from did.application.translation.planning import Stage08StructuralPlanningService
from did.infrastructure.auth_repository import AuthRepository
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    database_is_ready,
)
from did.infrastructure.localization_repository import LocalizationRepository
from did.infrastructure.logging import configure_logging
from did.infrastructure.planning_repository import (
    ConfirmationInvalid,
    PlanConflict,
    PlanningRepository,
    PlanNotFound,
)
from did.infrastructure.portability_repository import (
    PortabilityRepository,
    PortableArtifactIntegrityError,
    PortableArtifactNotFound,
    PortableQuotaExceeded,
    TransferNotFound,
)
from did.infrastructure.redis import create_redis_client, redis_is_ready
from did.infrastructure.runtime_redis import RedisHotCache, RedisSingleFlight, TenantPubSub
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04NotFound, Stage04Repository
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    ResourceLanguagePolicyRepository,
    Stage08AuditRepository,
    Stage08Conflict,
    Stage08NotFound,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
    VisibilityScopeLanguageRepository,
)
from did.oauth.crypto import TokenCipher, decode_encryption_key
from did.oauth.discord import (
    DiscordMemberClient,
    DiscordOAuthClient,
    HttpDiscordMemberClient,
    HttpDiscordOAuthClient,
)
from did.oauth.stores import (
    RedisActorMembershipStore,
    RedisGuildDiscoveryStore,
    RedisOAuthStateStore,
    RedisSessionStore,
)
from did.portability import ArtifactCipher, InMemoryKeyProvider, KeyUnavailable
from did.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    oauth_client: DiscordOAuthClient | None = None,
    member_client: DiscordMemberClient | None = None,
) -> FastAPI:
    configured = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(configured.database_url.get_secret_value())
        redis_client = create_redis_client(configured.redis_url.get_secret_value())
        application.state.readiness_probes = ReadinessProbes(
            database=lambda: database_is_ready(engine),
            redis=lambda: redis_is_ready(redis_client),
            timeout_seconds=configured.health_timeout_seconds,
        )
        owned_oauth: HttpDiscordOAuthClient | None = None
        owned_member: HttpDiscordMemberClient | None = None
        auth_config = (
            configured.discord_client_id,
            configured.discord_client_secret,
            configured.discord_oauth_redirect_uri,
            configured.session_secret,
            configured.oauth_token_encryption_key,
        )
        if all(value is not None for value in auth_config):
            selected_oauth = oauth_client
            if selected_oauth is None:
                assert configured.discord_client_id is not None
                assert configured.discord_client_secret is not None
                assert configured.discord_oauth_redirect_uri is not None
                owned_oauth = HttpDiscordOAuthClient(
                    client_id=configured.discord_client_id,
                    client_secret=configured.discord_client_secret.get_secret_value(),
                    redirect_uri=configured.discord_oauth_redirect_uri,
                )
                selected_oauth = owned_oauth
            selected_member = member_client
            if selected_member is None and configured.discord_bot_token is not None:
                owned_member = HttpDiscordMemberClient(
                    bot_token=configured.discord_bot_token.get_secret_value()
                )
                selected_member = owned_member
            assert configured.session_secret is not None
            assert configured.oauth_token_encryption_key is not None
            session_factory = create_session_factory(engine)
            repository = AuthRepository(session_factory)
            runtime_repository = RuntimeRepository(session_factory)
            sessions = RedisSessionStore(
                redis_client,
                session_secret=configured.session_secret.get_secret_value(),
                idle_ttl_seconds=configured.session_idle_ttl_seconds,
                absolute_ttl_seconds=configured.session_absolute_ttl_seconds,
            )
            guild_store = RedisGuildDiscoveryStore(
                redis_client, ttl_seconds=configured.guild_discovery_ttl_seconds
            )
            auth = AuthService(
                redis=redis_client,
                oauth_client=selected_oauth,
                repository=repository,
                cipher=TokenCipher(
                    decode_encryption_key(configured.oauth_token_encryption_key.get_secret_value()),
                    configured.oauth_token_key_version,
                ),
                state_store=RedisOAuthStateStore(
                    redis_client, ttl_seconds=configured.oauth_state_ttl_seconds
                ),
                session_store=sessions,
                guild_store=guild_store,
            )
            authorization = AuthorizationService(
                auth=auth,
                repository=repository,
                membership_store=RedisActorMembershipStore(
                    redis_client, ttl_seconds=configured.authorization_freshness_seconds
                ),
                member_client=selected_member,
                freshness_seconds=configured.authorization_freshness_seconds,
                membership_singleflight=RedisSingleFlight(redis_client),
                metrics=runtime_repository.metrics,
            )
            installations = InstallationService(authorization=authorization, repository=repository)
            planning_repository = PlanningRepository(session_factory)
            stage04_repository = Stage04Repository(session_factory)
            planning = PlanningService(planning_repository, stage04_repository)
            portability_repository = None
            portability = None
            localization_repository = LocalizationRepository(session_factory)
            stage08_language_repository = LanguageProfileRepository(session_factory)
            stage08_policy_repository = ResourceLanguagePolicyRepository(session_factory)
            stage08_group_repository = TranslationGroupRepository(session_factory)
            stage08_provider_repository = TranslationProviderBindingRepository(session_factory)
            stage08_visibility_repository = VisibilityScopeLanguageRepository(session_factory)
            stage08_lifecycle_repository = Stage08LifecycleRepository(session_factory)
            stage08_languages = LanguageProfileService(
                stage08_language_repository, stage08_policy_repository
            )
            stage08_topology = TranslationTopologyService(
                stage08_group_repository,
                stage08_provider_repository,
                stage08_visibility_repository,
                stage04_repository,
            )
            stage08_audit_repository = Stage08AuditRepository(session_factory)
            stage08_structural_planning = Stage08StructuralPlanningService(
                planning=planning,
                read_models=stage04_repository,
                groups=stage08_group_repository,
                languages=stage08_language_repository,
                policies=stage08_policy_repository,
                scope_roles=stage08_visibility_repository,
                lifecycle=stage08_lifecycle_repository,
            )
            if configured.artifact_encryption_key is not None:
                previous_keys: dict[int, str] = {}
                if configured.artifact_previous_encryption_keys is not None:
                    raw_previous = json.loads(
                        configured.artifact_previous_encryption_keys.get_secret_value()
                    )
                    if not isinstance(raw_previous, dict):
                        raise ValueError("artifact previous keyring must be a JSON object")
                    previous_keys = {int(key): str(value) for key, value in raw_previous.items()}
                provider = InMemoryKeyProvider.from_base64_keyring(
                    configured.artifact_encryption_key.get_secret_value(),
                    version=configured.artifact_encryption_key_version,
                    previous=previous_keys,
                )
                portability_repository = PortabilityRepository(
                    session_factory,
                    ArtifactCipher(provider),
                    max_artifacts_per_owner=configured.artifact_max_items_per_owner,
                    max_total_bytes_per_owner=configured.artifact_max_bytes_per_owner,
                    metrics=runtime_repository.metrics,
                )
                portability = PortabilityService(
                    portability_repository,
                    stage04_repository,
                    planning,
                    planning_repository,
                    clipboard_ttl_seconds=configured.artifact_clipboard_ttl_seconds,
                    export_ttl_seconds=configured.artifact_export_ttl_seconds,
                    metrics=runtime_repository.metrics,
                )
            application.state.services = ServiceContainer(
                settings=configured,
                repository=repository,
                auth=auth,
                authorization=authorization,
                installations=installations,
                sessions=sessions,
                runtime_repository=runtime_repository,
                hot_cache=RedisHotCache(redis_client, metrics=runtime_repository.metrics),
                pubsub=TenantPubSub(redis_client),
                stage04_repository=stage04_repository,
                planning_repository=planning_repository,
                planning=planning,
                portability_repository=portability_repository,
                portability=portability,
                localization_repository=localization_repository,
                stage08_language_repository=stage08_language_repository,
                stage08_policy_repository=stage08_policy_repository,
                stage08_group_repository=stage08_group_repository,
                stage08_provider_repository=stage08_provider_repository,
                stage08_visibility_repository=stage08_visibility_repository,
                stage08_languages=stage08_languages,
                stage08_topology=stage08_topology,
                stage08_audit_repository=stage08_audit_repository,
                stage08_structural_planning=stage08_structural_planning,
            )
        try:
            yield
        finally:
            if owned_oauth is not None:
                await owned_oauth.aclose()
            if owned_member is not None:
                await owned_member.aclose()
            await redis_client.aclose()
            await engine.dispose()

    configure_logging(configured.log_level)
    application = FastAPI(
        title="Discord Infrastructure Designer",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "X-Correlation-ID",
            "Idempotency-Key",
        ],
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(me_router)
    application.include_router(guilds_router)
    application.include_router(runtime_cache_router)
    application.include_router(stage04_router)
    application.include_router(stage05_router)
    application.include_router(stage06_router)
    application.include_router(stage07_router)
    application.include_router(stage08_router)
    application.add_api_websocket_route("/ws/v1/guilds/{guild_id}", guild_events_socket)

    @application.exception_handler(ApiProblem)
    async def handle_api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return problem_response(exc, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(AuthorizationDenied)
    async def handle_authorization_denied(
        request: Request, exc: AuthorizationDenied
    ) -> JSONResponse:
        problem = authorization_problem(exc)
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(Stage04NotFound)
    async def handle_stage04_not_found(request: Request, exc: Stage04NotFound) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message_key="errors.resource.notFound",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(PlanNotFound)
    async def handle_plan_not_found(request: Request, exc: PlanNotFound) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=404,
            code="PLAN_NOT_FOUND",
            message_key="errors.plans.notFound",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(PlanConflict)
    @application.exception_handler(ConfirmationInvalid)
    async def handle_plan_conflict(request: Request, exc: Exception) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=409,
            code="PLAN_CONFLICT",
            message_key="errors.plans.conflict",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(PortableArtifactNotFound)
    @application.exception_handler(TransferNotFound)
    async def handle_portability_not_found(request: Request, exc: Exception) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=404,
            code="PORTABLE_RESOURCE_NOT_FOUND",
            message_key="errors.portability.notFound",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(PortableQuotaExceeded)
    async def handle_portability_quota(request: Request, exc: Exception) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=409,
            code="PORTABLE_QUOTA_EXCEEDED",
            message_key="errors.portability.quotaExceeded",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(KeyUnavailable)
    async def handle_portability_key(request: Request, exc: Exception) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=503,
            code="PORTABLE_KEY_UNAVAILABLE",
            message_key="errors.portability.keyUnavailable",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(PortableArtifactIntegrityError)
    async def handle_portability_integrity(request: Request, exc: Exception) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=422,
            code="PORTABLE_ARTIFACT_INVALID",
            message_key="errors.portability.invalid",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(ValueError)
    async def handle_planning_value_error(request: Request, exc: ValueError) -> JSONResponse:
        problem = invalid_planning_input(exc)
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(Stage08NotFound)
    async def handle_stage08_not_found(request: Request, exc: Stage08NotFound) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=404,
            code="MULTILINGUAL_RESOURCE_NOT_FOUND",
            message_key="errors.translations.notFound",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    @application.exception_handler(Stage08Conflict)
    async def handle_stage08_conflict(request: Request, exc: Stage08Conflict) -> JSONResponse:
        del exc
        problem = ApiProblem(
            status_code=409,
            code="MULTILINGUAL_CONFLICT",
            message_key="errors.translations.conflict",
        )
        return problem_response(problem, getattr(request.state, "correlation_id", "unknown"))

    return application


app = create_app()
