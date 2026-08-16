import pytest
from pydantic import SecretStr, ValidationError

from did.settings import AppEnvironment, Settings


def test_settings_repr_and_summary_redact_connections() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+asyncpg://user:very-secret@db/did"),
        database_admin_url=SecretStr("postgresql+asyncpg://admin:very-secret@db/did"),
        redis_url=SecretStr("redis://:very-secret@redis/0"),
    )
    rendered = repr(settings)
    summary = settings.safe_summary()
    assert "very-secret" not in rendered
    assert "very-secret" not in str(summary)
    assert summary["database_url"] == "[REDACTED]"


def test_production_rejects_local_defaults() -> None:
    with pytest.raises(ValidationError, match="production configuration"):
        Settings(_env_file=None, app_env=AppEnvironment.PRODUCTION)


def test_invalid_backend_schemes_fail_fast() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(_env_file=None, database_url=SecretStr("sqlite:///local.db"))


def test_stage02_secret_names_are_loaded_without_exposing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_CLIENT_ID", "123")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "<configured-outside-source>")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "<configured-outside-source>")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback")
    monkeypatch.setenv("SESSION_SECRET", "<configured-outside-source-material>")
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "<configured-outside-source-material>")

    settings = Settings(_env_file=None)

    assert settings.discord_client_id == "123"
    assert settings.discord_client_secret is not None
    assert settings.discord_bot_token is not None
    assert settings.session_secret is not None
    assert "configured-outside-source" not in repr(settings)
    assert "configured-outside-source" not in str(settings.safe_summary())
