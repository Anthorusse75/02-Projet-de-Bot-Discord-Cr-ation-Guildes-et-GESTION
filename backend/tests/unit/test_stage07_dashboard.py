from __future__ import annotations

from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from did.api.main import create_app
from did.api.stage07 import application_commands_localization_status, dashboard_capabilities
from did.domain.auth import AuthorizationScope, Capability
from did.localization import CATALOG_VERSION, LocalePackInvalid, LocalePackValidator


async def test_public_catalog_contract_and_etag() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/v1/ui/catalog/version")
        cached = await client.get(
            "/api/v1/ui/catalog/version", headers={"If-None-Match": first.headers["etag"]}
        )
    assert first.status_code == 200
    assert first.json()["catalog_version"] == CATALOG_VERSION
    assert first.json()["bootstrap_locales"] == ["en", "fr", "de", "es"]
    assert cached.status_code == 304


async def test_locale_list_etag_covers_every_ordered_runtime_locale() -> None:
    class Repository:
        first_hash = "a" * 64

        async def active_locales(self, _: str) -> list[dict[str, object]]:
            return [
                {
                    "locale_code": "it",
                    "display_name": "Italiano",
                    "flag_code": "it",
                    "direction": "ltr",
                    "catalog_version": CATALOG_VERSION,
                    "status": "ACTIVE",
                    "coverage_count": 244,
                    "coverage_percent": 100,
                    "content_hash": self.first_hash,
                },
                {
                    "locale_code": "nl",
                    "display_name": "Nederlands",
                    "flag_code": "nl",
                    "direction": "ltr",
                    "catalog_version": CATALOG_VERSION,
                    "status": "ACTIVE",
                    "coverage_count": 244,
                    "coverage_percent": 100,
                    "content_hash": "b" * 64,
                },
            ]

    repository = Repository()
    app = create_app()
    app.state.services = SimpleNamespace(localization_repository=repository)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/v1/ui/locales")
        repository.first_hash = "c" * 64
        second = await client.get("/api/v1/ui/locales")
        stale = await client.get(
            "/api/v1/ui/locales", headers={"If-None-Match": first.headers["etag"]}
        )
    assert [item["locale_code"] for item in first.json()["locales"]] == [
        "de",
        "en",
        "es",
        "fr",
        "it",
        "nl",
    ]
    assert first.headers["etag"] != second.headers["etag"]
    assert stale.status_code == 200


def test_stage07_routes_and_application_command_scope_are_explicit() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/v1/ui/locales" in paths
    assert "/api/v1/ui/locales/{locale}/catalog/{catalog_version}" in paths
    assert "get" in paths["/api/v1/guilds/{guild_id}/plans"]
    assert "/api/v1/guilds/{guild_id}/audit" in paths
    assert "/api/v1/guilds/{guild_id}/dashboard-capabilities" in paths
    assert application_commands_localization_status() == {
        "status": "NOT_APPLICABLE",
        "command_count": 0,
        "reason": "NO_USER_FACING_APPLICATION_COMMANDS_REGISTERED",
    }


def test_runtime_pack_validator_is_fail_closed() -> None:
    validator = LocalePackValidator({"hello": ("name",), "close": ()})
    valid = validator.validate({"hello": "Bonjour {{name}}", "close": "Fermer"})
    assert valid.coverage_count == 2
    for payload in (
        {"hello": "Bonjour {{name}}"},
        {"hello": "Bonjour", "close": "Fermer"},
        {"hello": "Bonjour {{name}}", "close": "<script>x</script>"},
    ):
        try:
            validator.validate(payload)
        except LocalePackInvalid:
            pass
        else:
            raise AssertionError("invalid locale pack was accepted")


async def test_dashboard_capabilities_use_resolved_authority_and_fail_closed_bot_state() -> None:
    class Authorization:
        async def authorize(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                capabilities=frozenset({Capability.TENANT_READ, Capability.STRUCTURE_READ}),
                scope=AuthorizationScope.guild(),
            )

    class Repository:
        async def bot_identity(self, _: int) -> tuple[None, str]:
            return None, "ACTIVE"

    response = await dashboard_capabilities(
        "700000000000000001",
        SimpleNamespace(discord_user_id=700000000000000002),
        SimpleNamespace(
            authorization=Authorization(),
            stage04_repository=Repository(),
            runtime_repository=SimpleNamespace(metrics=SimpleNamespace()),
        ),
    )
    assert response["discord_rest_calls"] == 0
    assert response["user_capabilities"]["structure.read"]["outcome"] == "CAN"
    assert response["user_capabilities"]["structure.write"]["outcome"] == "CANNOT"
    assert response["bot_operations"]["CREATE_CHANNEL"]["outcome"] == "UNKNOWN"
    assert response["scoped_capabilities"]["scope_kind"] == "GUILD"
