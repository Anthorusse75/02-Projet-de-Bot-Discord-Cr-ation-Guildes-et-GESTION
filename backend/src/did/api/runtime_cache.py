from __future__ import annotations

import asyncio
from datetime import date, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ConfigDict, Field

from did.api.dependencies import (
    ApiProblem,
    CsrfSessionDep,
    CurrentSessionDep,
    ServiceContainer,
    ServicesDep,
    session_cookie_name,
)
from did.api.guilds import parse_snowflake
from did.application.auth.service import AuthorizationDenied
from did.application.cache import CachePurgeService
from did.domain.auth import AuthorizationScope, Capability
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority

router = APIRouter(prefix="/api/v1/guilds", tags=["runtime-cache"])


class ChannelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_ids: list[str] = Field(min_length=1, max_length=500)

    def parsed_ids(self) -> list[int]:
        parsed = [parse_snowflake(value) for value in self.channel_ids]
        if len(set(parsed)) != len(parsed):
            raise ApiProblem(
                status_code=422,
                code="DUPLICATE_CHANNEL_ID",
                message_key="errors.cache.duplicateChannel",
            )
        return parsed


class PurgeRequest(ChannelSelection):
    confirm_local_only: bool
    confirm_resource_deleted: bool = False


def _api_value(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _channel_response(row: dict[str, object]) -> dict[str, object]:
    identifiers = {"guild_id", "channel_id", "parent_id"}
    return {
        key: (str(value) if key in identifiers and value is not None else _api_value(value))
        for key, value in row.items()
    }


@router.get("/{guild_id}/channels")
async def cached_channels(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
    include_hidden_deleted: bool = Query(default=False),
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_READ,
        scope=AuthorizationScope.guild(),
    )
    hot = await container.hot_cache.get_channels(parsed)
    if hot is None:
        hot = await container.runtime_repository.channels(
            parsed, session.discord_user_id, include_hidden_deleted=True
        )
        await container.hot_cache.put_channels(parsed, hot)
    visible = (
        hot
        if include_hidden_deleted
        else [row for row in hot if row.get("observability_state") == "VISIBLE"]
    )
    return {
        "guild_id": str(parsed),
        "source": "LOCAL_CACHE",
        "channels": [_channel_response(row) for row in visible],
    }


@router.post("/{guild_id}/cache/channels/refresh", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_channel_refresh(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, str]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_READ,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    job = WorkloadJob(
        uuid4(),
        parsed,
        "REFRESH_CHANNELS",
        "refresh:channels",
        WorkloadPriority.USER_REFRESH,
        datetime.now().astimezone(),
    )
    correlation_id = uuid4()
    job_id = await container.runtime_repository.enqueue_job(
        job,
        requested_by=session.discord_user_id,
        correlation_id=correlation_id,
    )
    return {"job_id": str(job_id), "status": "PENDING", "freshness": "UNCHANGED"}


@router.post("/{guild_id}/cache/channels/purge/preview")
async def preview_channel_purge(
    guild_id: str,
    body: ChannelSelection,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.CACHE_PURGE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    resources = await CachePurgeService(container.runtime_repository, container.hot_cache).preview(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        channel_ids=body.parsed_ids(),
    )
    return {
        "guild_id": str(parsed),
        "local_only": True,
        "discord_delete_calls": 0,
        "count": len(resources),
        "resources": resources,
    }


@router.post("/{guild_id}/cache/channels/purge")
async def purge_channels(
    guild_id: str,
    body: PurgeRequest,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    if not body.confirm_local_only:
        raise ApiProblem(
            status_code=409,
            code="CACHE_PURGE_CONFIRMATION_REQUIRED",
            message_key="errors.cache.confirmLocalOnly",
        )
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.CACHE_PURGE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    try:
        count = await CachePurgeService(container.runtime_repository, container.hot_cache).purge(
            guild_id=parsed,
            actor_user_id=session.discord_user_id,
            channel_ids=body.parsed_ids(),
            correlation_id=uuid4(),
            user_confirmed_deleted=body.confirm_resource_deleted,
        )
    except ValueError as exc:
        if "explicit deletion confirmation" not in str(exc):
            raise
        raise ApiProblem(
            status_code=409,
            code="RESOURCE_DELETION_CONFIRMATION_REQUIRED",
            message_key="errors.cache.confirmResourceDeleted",
        ) from exc
    return {"purged": count, "local_only": True, "discord_delete_calls": 0}


async def guild_events_socket(websocket: WebSocket, guild_id: str) -> None:
    container = getattr(websocket.app.state, "services", None)
    if not isinstance(container, ServiceContainer):
        await websocket.close(code=1013)
        return
    parsed = parse_snowflake(guild_id)
    session_token = websocket.cookies.get(session_cookie_name(container.settings))
    session = await container.sessions.load(session_token)
    if session is None:
        await websocket.close(code=4401)
        return
    try:
        await container.authorization.authorize(
            discord_user_id=session.discord_user_id,
            guild_id=parsed,
            capability=Capability.STRUCTURE_READ,
            scope=AuthorizationScope.guild(),
        )
    except AuthorizationDenied:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    subscription = container.pubsub.subscribe(parsed)

    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=100)

    async def pump_subscription() -> None:
        async for event in subscription:
            await queue.put(event)

    pump_task = asyncio.create_task(pump_subscription())
    loop = asyncio.get_running_loop()
    auth_lease_seconds = container.settings.websocket_authorization_max_staleness_seconds
    next_external_authorization = loop.time() + auth_lease_seconds
    try:
        while True:
            event_task = asyncio.create_task(queue.get())
            receive_task = asyncio.create_task(websocket.receive())
            auth_lease_task = asyncio.create_task(
                asyncio.sleep(max(0.0, next_external_authorization - loop.time()))
            )
            done, pending = await asyncio.wait(
                {event_task, receive_task, auth_lease_task, pump_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                if task is pump_task:
                    continue
                task.cancel()
            await asyncio.gather(
                *(task for task in pending if task is not pump_task),
                return_exceptions=True,
            )
            if pump_task in done:
                pump_task.result()
                break
            if auth_lease_task in done:
                close_code = await _socket_reauthorization_code(
                    container,
                    session_token=session_token,
                    expected_user_id=session.discord_user_id,
                    guild_id=parsed,
                    force_external=True,
                )
                if close_code is not None:
                    await websocket.close(code=close_code)
                    break
                next_external_authorization = loop.time() + auth_lease_seconds
                continue
            if receive_task in done:
                message = receive_task.result()
                if message["type"] == "websocket.disconnect":
                    break
                continue
            close_code = await _socket_reauthorization_code(
                container,
                session_token=session_token,
                expected_user_id=session.discord_user_id,
                guild_id=parsed,
                force_external=False,
            )
            if close_code is not None:
                await websocket.close(code=close_code)
                break
            await websocket.send_json(event_task.result())
    except WebSocketDisconnect:
        return
    finally:
        pump_task.cancel()
        await asyncio.gather(pump_task, return_exceptions=True)
        await subscription.aclose()


async def _socket_reauthorization_code(
    container: ServiceContainer,
    *,
    session_token: str | None,
    expected_user_id: int,
    guild_id: int,
    force_external: bool,
) -> int | None:
    refreshed = await container.sessions.load(session_token)
    if refreshed is None or refreshed.discord_user_id != expected_user_id:
        return 4401
    try:
        if force_external:
            await container.authorization.discovery(
                expected_user_id,
                guild_id,
                force_refresh=True,
            )
        await container.authorization.authorize(
            discord_user_id=expected_user_id,
            guild_id=guild_id,
            capability=Capability.STRUCTURE_READ,
            scope=AuthorizationScope.guild(),
        )
    except AuthorizationDenied:
        return 4403
    except Exception:
        if force_external:
            return 4403
        raise
    return None


def correlation_uuid(value: str | None) -> UUID:
    try:
        return UUID(value) if value else uuid4()
    except ValueError:
        return uuid4()
