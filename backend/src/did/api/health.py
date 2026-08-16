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
