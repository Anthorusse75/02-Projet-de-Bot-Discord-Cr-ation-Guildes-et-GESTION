from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from did.api.main import create_app
from did.api.stage07 import application_commands_localization_status
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


def test_stage07_routes_and_application_command_scope_are_explicit() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/v1/ui/locales" in paths
    assert "/api/v1/ui/locales/{locale}/catalog/{catalog_version}" in paths
    assert "get" in paths["/api/v1/guilds/{guild_id}/plans"]
    assert "/api/v1/guilds/{guild_id}/audit" in paths
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
