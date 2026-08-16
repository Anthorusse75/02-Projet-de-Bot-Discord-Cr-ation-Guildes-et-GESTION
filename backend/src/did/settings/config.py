from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed configuration loaded only on the backend."""

    model_config = SettingsConfigDict(
        env_prefix="DID_",
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://did_app:local_app_password@localhost:5432/did"),
        repr=False,
    )
    database_admin_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://did_admin:local_admin_password@localhost:5432/did"),
        repr=False,
    )
    redis_url: SecretStr = Field(
        default=SecretStr("redis://localhost:6379/0"),
        repr=False,
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    health_timeout_seconds: float = Field(default=2.0, gt=0.0, le=10.0)

    @model_validator(mode="after")
    def validate_backends(self) -> Self:
        database_url = self.database_url.get_secret_value()
        admin_url = self.database_admin_url.get_secret_value()
        redis_url = self.redis_url.get_secret_value()
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use postgresql+asyncpg")
        if not admin_url.startswith("postgresql+asyncpg://"):
            raise ValueError("database_admin_url must use postgresql+asyncpg")
        if not redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use redis:// or rediss://")
        if self.app_env is AppEnvironment.PRODUCTION:
            local_markers = ("localhost", "local_app_password", "local_admin_password")
            configured = (database_url, admin_url, redis_url)
            if any(marker in value for marker in local_markers for value in configured):
                raise ValueError("production configuration cannot use local defaults")
        return self

    def safe_summary(self) -> dict[str, str | float]:
        return {
            "app_env": self.app_env.value,
            "database_url": "[REDACTED]",
            "database_admin_url": "[REDACTED]",
            "redis_url": "[REDACTED]",
            "log_level": self.log_level,
            "health_timeout_seconds": self.health_timeout_seconds,
        }
