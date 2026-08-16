import os

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from did.api.main import create_app
from did.settings import AppEnvironment, Settings

pytestmark = pytest.mark.integration


async def test_ready_checks_real_postgres_and_redis() -> None:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=SecretStr(
            os.environ.get(
                "DID_DATABASE_URL",
                "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
            )
        ),
        database_admin_url=SecretStr(
            os.environ.get(
                "DID_DATABASE_ADMIN_URL",
                "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
            )
        ),
        redis_url=SecretStr(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")),
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": True, "redis": True},
    }
