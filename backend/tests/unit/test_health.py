from httpx import ASGITransport, AsyncClient

from did.api.health import ReadinessProbes
from did.api.main import create_app


async def _yes() -> bool:
    return True


async def _no() -> bool:
    return False


async def test_liveness_and_correlation_id() -> None:
    application = create_app()
    application.state.readiness_probes = ReadinessProbes(_yes, _yes, 0.1)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}
    assert response.headers["X-Correlation-ID"]


async def test_readiness_fails_when_a_dependency_is_down() -> None:
    application = create_app()
    application.state.readiness_probes = ReadinessProbes(_yes, _no, 0.1)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": True, "redis": False}
