from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from did.api.health import ReadinessProbes
from did.api.health import router as health_router
from did.api.middleware import CorrelationIdMiddleware
from did.infrastructure.database import create_database_engine, database_is_ready
from did.infrastructure.logging import configure_logging
from did.infrastructure.redis import create_redis_client, redis_is_ready
from did.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
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
        try:
            yield
        finally:
            await redis_client.aclose()
            await engine.dispose()

    configure_logging(configured.log_level)
    application = FastAPI(
        title="Discord Infrastructure Designer",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(health_router)
    return application


app = create_app()
