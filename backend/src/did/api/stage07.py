from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from did.api.dependencies import ApiProblem, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.api.stage05 import _plan_response
from did.domain.auth import AuthorizationScope, Capability
from did.localization import BOOTSTRAP_LOCALES, CATALOG_CONTENT_HASH, CATALOG_VERSION
from did.permissions.capabilities import BotCapabilityChecker, BotOperation, CapabilityOutcome

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


def _bot_capability_response(decision: Any) -> dict[str, Any]:
    value = asdict(decision)
    value["operation"] = decision.operation.value
    value["outcome"] = decision.outcome.value
    if decision.hierarchy is not None:
        value["hierarchy"] = {
            **asdict(decision.hierarchy),
            "outcome": decision.hierarchy.outcome.value,
            "bot_highest_role_id": (
                str(decision.hierarchy.bot_highest_role_id)
                if decision.hierarchy.bot_highest_role_id is not None
                else None
            ),
            "target_role_id": (
                str(decision.hierarchy.target_role_id)
                if decision.hierarchy.target_role_id is not None
                else None
            ),
        }
    return value


@router.get("/api/v1/guilds/{guild_id}/dashboard-capabilities")
async def dashboard_capabilities(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
    resource_id: str | None = Query(default=None),
    target_role_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Aggregate existing authorization and cached bot checks for the dashboard.

    This endpoint is deliberately read-only and cache-first.  It does not grant
    authority: every command endpoint remains responsible for its own final
    authorization and preflight checks.
    """

    parsed = parse_snowflake(guild_id)
    authorization = await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.TENANT_READ,
        scope=AuthorizationScope.guild(),
    )
    granted = authorization.capabilities
    user = {
        item.value: {
            "outcome": (
                CapabilityOutcome.CAN.value if item in granted else CapabilityOutcome.CANNOT.value
            ),
            "scope_kind": authorization.scope.kind.value,
            "scope_id": authorization.scope.scope_id,
            "causes": [] if item in granted else ["capability.user.not_granted"],
            "remediations": [],
        }
        for item in Capability
    }

    operations = list(BotOperation)
    bot: dict[str, dict[str, Any]] = {}
    if Capability.BOTS_AUDIT not in granted:
        bot = {
            operation.value: {
                "operation": operation.value,
                "outcome": CapabilityOutcome.UNKNOWN.value,
                "required_permissions": [],
                "causes": ["capability.user.bot_audit_required"],
                "remediations": [],
                "warnings": [],
                "hierarchy": None,
            }
            for operation in operations
        }
        return {
            "guild_id": str(parsed),
            "source": "AUTHORIZATION_AND_LOCAL_CACHE",
            "discord_rest_calls": 0,
            "user_capabilities": user,
            "scoped_capabilities": {
                "scope_kind": authorization.scope.kind.value,
                "scope_id": authorization.scope.scope_id,
                "capabilities": user,
            },
            "bot_operations": bot,
            "coverage": "UNKNOWN",
            "completeness": "UNKNOWN",
            "freshness": "UNKNOWN",
        }

    bot_id, installation_status = await container.stage04_repository.bot_identity(parsed)
    if bot_id is None:
        bot = {
            operation.value: {
                "operation": operation.value,
                "outcome": CapabilityOutcome.UNKNOWN.value,
                "required_permissions": [],
                "causes": ["capability.bot_identity_unknown"],
                "remediations": [],
                "warnings": [],
                "hierarchy": None,
            }
            for operation in operations
        }
        return {
            "guild_id": str(parsed),
            "source": "AUTHORIZATION_AND_LOCAL_CACHE",
            "discord_rest_calls": 0,
            "user_capabilities": user,
            "scoped_capabilities": {
                "scope_kind": authorization.scope.kind.value,
                "scope_id": authorization.scope.scope_id,
                "capabilities": user,
            },
            "bot_operations": bot,
            "coverage": "UNKNOWN",
            "completeness": "UNKNOWN",
            "freshness": "UNKNOWN",
        }

    guild, bot_member = await container.stage04_repository.guild_snapshot(parsed, bot_id)
    channel = guild.channel(parse_snowflake(resource_id)) if resource_id else None
    target_role = guild.role(parse_snowflake(target_role_id)) if target_role_id else None
    checker = BotCapabilityChecker()
    for operation in operations:
        decision = checker.check(
            operation=operation,
            guild=guild,
            bot=bot_member,
            channel=channel,
            target_role=target_role,
            installation_active=installation_status == "ACTIVE",
        )
        bot[operation.value] = _bot_capability_response(decision)
        container.runtime_repository.metrics.capability_check(decision.outcome.value)
    return {
        "guild_id": str(parsed),
        "source": "AUTHORIZATION_AND_LOCAL_CACHE",
        "discord_rest_calls": 0,
        "user_capabilities": user,
        "scoped_capabilities": {
            "scope_kind": authorization.scope.kind.value,
            "scope_id": authorization.scope.scope_id,
            "capabilities": user,
        },
        "bot_operations": bot,
        "coverage": guild.coverage.mode.value,
        "completeness": guild.coverage.mode.value,
        "freshness": guild.freshness.state.value,
    }


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
