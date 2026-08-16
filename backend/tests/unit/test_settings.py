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
