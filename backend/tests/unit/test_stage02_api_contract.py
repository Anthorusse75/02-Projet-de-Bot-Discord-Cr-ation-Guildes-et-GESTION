from pydantic import SecretStr

from did.api.dependencies import secrets_compare, session_cookie_name
from did.api.guilds import parse_snowflake
from did.settings import AppEnvironment, Settings


def test_cookie_contract_is_host_only_secure_in_production() -> None:
    production = Settings(
        _env_file=None,
        app_env=AppEnvironment.PRODUCTION,
        database_url=SecretStr("postgresql+asyncpg://app:opaque@db/did"),
        database_admin_url=SecretStr("postgresql+asyncpg://admin:opaque@db/did"),
        redis_url=SecretStr("rediss://redis/0"),
        discord_client_id="1",
        discord_client_secret=SecretStr("configured-outside-source"),
        discord_oauth_redirect_uri="https://example.test/auth/discord/callback",
        session_secret=SecretStr("x" * 32),
        oauth_token_encryption_key=SecretStr("a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s"),
    )
    assert session_cookie_name(production) == "__Host-did_session"


def test_csrf_comparison_and_snowflake_transport() -> None:
    assert secrets_compare("same", "same")
    assert not secrets_compare("same", "different")
    assert str(parse_snowflake("9007199254740993")) == "9007199254740993"
