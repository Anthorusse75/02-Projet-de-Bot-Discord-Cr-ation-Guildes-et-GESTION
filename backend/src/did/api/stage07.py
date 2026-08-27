from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from did.api.dependencies import ApiProblem, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.api.stage05 import _plan_response
from did.domain.auth import AuthorizationScope, Capability
from did.localization import BOOTSTRAP_LOCALES, CATALOG_CONTENT_HASH, CATALOG_VERSION

router = APIRouter(tags=["stage-07-dashboard"])


def _etag(value: str) -> str:
    return f'"{value}"'


def _cache_headers(content_hash: str) -> dict[str, str]:
    return {
        "ETag": _etag(content_hash),
        "Cache-Control": "public, max-age=300, stale-while-revalidate=86400",
    }


@router.get("/api/v1/ui/catalog/version", response_model=None)
async def ui_catalog_version(request: Request, response: Response) -> dict[str, Any] | Response:
    tag = _etag(CATALOG_CONTENT_HASH)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=_cache_headers(CATALOG_CONTENT_HASH))
    response.headers.update(_cache_headers(CATALOG_CONTENT_HASH))
    return {
        "catalog_version": CATALOG_VERSION,
        "content_hash": CATALOG_CONTENT_HASH,
        "bootstrap_locales": [item["locale_code"] for item in BOOTSTRAP_LOCALES],
    }


@router.get("/api/v1/ui/locales", response_model=None)
async def ui_locales(request: Request, response: Response) -> dict[str, Any] | Response:
    container = getattr(request.app.state, "services", None)
    runtime: list[dict[str, Any]] = []
    repository = getattr(container, "localization_repository", None)
    if repository is not None:
        runtime = await repository.active_locales(CATALOG_VERSION)
    content_hash = CATALOG_CONTENT_HASH if not runtime else str(runtime[-1]["content_hash"])
    if request.headers.get("if-none-match") == _etag(content_hash):
        return Response(status_code=304, headers=_cache_headers(content_hash))
    response.headers.update(_cache_headers(content_hash))
    known = {str(item["locale_code"]): dict(item) for item in BOOTSTRAP_LOCALES}
    known.update({str(item["locale_code"]): item for item in runtime})
    return {"catalog_version": CATALOG_VERSION, "locales": list(known.values())}


@router.get("/api/v1/ui/locales/{locale}/catalog/{catalog_version}", response_model=None)
async def ui_locale_catalog(
    locale: str, catalog_version: str, request: Request, response: Response
) -> dict[str, Any] | Response:
    if catalog_version != CATALOG_VERSION:
        raise ApiProblem(
            status_code=404,
            code="UI_CATALOG_INCOMPATIBLE",
            message_key="errors.localization.catalogIncompatible",
        )
    container = getattr(request.app.state, "services", None)
    repository = getattr(container, "localization_repository", None)
    row = None if repository is None else await repository.active_pack(locale, catalog_version)
    if row is None:
        raise ApiProblem(
            status_code=404,
            code="UI_LOCALE_PACK_NOT_FOUND",
            message_key="errors.localization.packNotFound",
        )
    content_hash = str(row["content_hash"])
    if request.headers.get("if-none-match") == _etag(content_hash):
        return Response(status_code=304, headers=_cache_headers(content_hash))
    response.headers.update(_cache_headers(content_hash))
    return {
        "locale_code": locale,
        "catalog_version": catalog_version,
        "content_hash": content_hash,
        "coverage_count": int(row["coverage_count"]),
        "coverage_percent": float(Decimal(row["coverage_percent"])),
        "payload": row["payload_json"],
    }


async def _authorize(guild_id: int, session: Any, container: Any, capability: Capability) -> None:
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=guild_id,
        capability=capability,
        scope=AuthorizationScope.guild(),
    )


@router.get("/api/v1/guilds/{guild_id}/plans")
async def list_plans(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.PLANS_CREATE)
    rows = await container.planning_repository.list_plans(parsed, limit=limit)
    return {
        "guild_id": str(parsed),
        "source": "LOCAL_DATABASE",
        "plans": [_plan_response(row) for row in rows],
    }


@router.get("/api/v1/guilds/{guild_id}/audit")
async def list_audit(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.AUDIT_READ)
    rows = await container.runtime_repository.audit_events(parsed, limit=limit)
    return {
        "guild_id": str(parsed),
        "source": "LOCAL_DATABASE",
        "events": [
            {
                **row,
                "id": str(row["id"]),
                "target_id": str(row["target_id"]) if row["target_id"] is not None else None,
                "plan_id": str(row["plan_id"]) if row["plan_id"] is not None else None,
                "correlation_id": str(row["correlation_id"]),
            }
            for row in rows
        ],
    }


def application_commands_localization_status() -> dict[str, Any]:
    return {
        "status": "NOT_APPLICABLE",
        "command_count": 0,
        "reason": "NO_USER_FACING_APPLICATION_COMMANDS_REGISTERED",
    }
