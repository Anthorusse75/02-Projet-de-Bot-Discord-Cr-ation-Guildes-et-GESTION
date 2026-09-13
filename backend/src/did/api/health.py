import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter, Request, Response, status

Probe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ReadinessProbes:
    database: Probe
    redis: Probe
    timeout_seconds: float


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, object]:
    probes: ReadinessProbes = request.app.state.readiness_probes
    try:
        database, redis = await asyncio.wait_for(
            asyncio.gather(probes.database(), probes.redis()),
            timeout=probes.timeout_seconds,
        )
    except TimeoutError:
        database, redis = False, False
    ready_state = database and redis
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready_state else "not_ready",
        "checks": {"database": database, "redis": redis},
    }


@router.get("/features")
async def features(request: Request) -> dict[str, object]:
    """Expose non-secret feature availability for the dashboard preflight.

    Optional services are reported rather than turned into mysterious 503s in
    the UI.  No token, key material, URL or tenant data is exposed here.
    """

    container = getattr(request.app.state, "services", None)
    return {
        "features": {
            "oauth": container is not None and getattr(container, "auth", None) is not None,
            "live_events": container is not None and getattr(container, "pubsub", None) is not None,
            "portability": container is not None and getattr(container, "portability", None) is not None,
        }
    }
