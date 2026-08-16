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
    count = await CachePurgeService(container.runtime_repository, container.hot_cache).purge(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        channel_ids=body.parsed_ids(),
        correlation_id=uuid4(),
    )
    return {"purged": count, "local_only": True, "discord_delete_calls": 0}


async def guild_events_socket(websocket: WebSocket, guild_id: str) -> None:
    container = getattr(websocket.app.state, "services", None)
    if not isinstance(container, ServiceContainer):
        await websocket.close(code=1013)
        return
    parsed = parse_snowflake(guild_id)
    session = await container.sessions.load(
        websocket.cookies.get(session_cookie_name(container.settings))
    )
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
    try:
        while True:
            event_task = asyncio.ensure_future(anext(subscription))
            receive_task = asyncio.create_task(websocket.receive())
            done, pending = await asyncio.wait(
                {event_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if receive_task in done:
                message = receive_task.result()
                if message["type"] == "websocket.disconnect":
                    break
                continue
            await websocket.send_json(event_task.result())
    except WebSocketDisconnect:
        return
    finally:
        await subscription.aclose()


def correlation_uuid(value: str | None) -> UUID:
    try:
        return UUID(value) if value else uuid4()
    except ValueError:
        return uuid4()
