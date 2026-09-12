from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from did.api.main import create_app
from did.settings import AppEnvironment, Settings

pytestmark = pytest.mark.security

PUBLIC_API_PATHS = {
    "/api/v1/ui/catalog/version",
    "/api/v1/ui/locales",
    "/api/v1/ui/locales/{locale}/catalog/{catalog_version}",
}
READ_ONLY_POST_ENDPOINTS = {
    "capacity_preflight",
    "compile_routes",
    "compile_visibility",
    "evaluate_permission",
    "explain_permission",
    "provider_access_preflight",
    "resolve_visibility_scope",
    "simple_compile",
    "simulate",
    "simulate_permission",
}


def api_routes() -> Iterator[APIRoute]:
    for included in create_app().routes:
        router = getattr(included, "original_router", None)
        if router is None:
            continue
        for route in router.routes:
            if isinstance(route, APIRoute):
                yield route


def dependency_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        names.add(getattr(dependency.call, "__name__", repr(dependency.call)))
        pending.extend(dependency.dependencies)
    return names


def test_every_private_api_route_requires_a_backend_session() -> None:
    private_routes = [
        route
        for route in api_routes()
        if route.path.startswith("/api/v1") and route.path not in PUBLIC_API_PATHS
    ]

    assert len(private_routes) >= 130
    assert not [
        f"{sorted(route.methods)} {route.path}"
        for route in private_routes
        if "current_session" not in dependency_names(route)
    ]


def test_every_state_changing_api_route_requires_csrf() -> None:
    routes = [route for route in api_routes() if route.path.startswith("/api/v1")]
    missing_csrf = {
        route.endpoint.__name__
        for route in routes
        if route.methods.intersection({"POST", "PUT", "PATCH", "DELETE"})
        and "csrf_session" not in dependency_names(route)
    }

    assert missing_csrf == READ_ONLY_POST_ENDPOINTS


async def test_security_headers_and_credentialed_cors_are_restrictive() -> None:
    application = create_app(
        Settings(_env_file=None, cors_allowed_origins=("https://dashboard.example",))
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="https://api.example"
    ) as client:
        response = await client.get("/health/live")
        trusted = await client.options(
            "/health/live",
            headers={
                "Origin": "https://dashboard.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        untrusted = await client.options(
            "/health/live",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert trusted.headers["access-control-allow-origin"] == "https://dashboard.example"
    assert trusted.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in untrusted.headers


@pytest.mark.parametrize(
    "origin",
    (
        "*",
        "file:///dashboard",
        "https://user:password@dashboard.example",
        "https://dashboard.example/path",
    ),
)
def test_cors_rejects_non_origin_and_wildcard_configuration(origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS origins"):
        Settings(_env_file=None, cors_allowed_origins=(origin,))


def test_production_rejects_insecure_cors_and_oauth_redirects() -> None:
    production = {
        "app_env": AppEnvironment.PRODUCTION,
        "database_url": SecretStr("postgresql+asyncpg://app:password@db/did"),
        "database_admin_url": SecretStr("postgresql+asyncpg://admin:password@db/did"),
        "redis_url": SecretStr("rediss://redis/0"),
        "discord_client_id": "123",
        "discord_client_secret": SecretStr("configured-outside-source"),
        "session_secret": SecretStr("configured-outside-source-material"),
        "oauth_token_encryption_key": SecretStr("configured-outside-source-material"),
        "artifact_encryption_key": SecretStr("configured-outside-source-material"),
    }
    with pytest.raises(ValidationError, match="production CORS origins must use HTTPS"):
        Settings(
            _env_file=None,
            **production,
            cors_allowed_origins=("http://dashboard.example",),
            discord_oauth_redirect_uri="https://dashboard.example/auth/discord/callback",
        )
    with pytest.raises(ValidationError, match="production Discord OAuth redirect URI"):
        Settings(
            _env_file=None,
            **production,
            cors_allowed_origins=("https://dashboard.example",),
            discord_oauth_redirect_uri="http://dashboard.example/auth/discord/callback",
        )
