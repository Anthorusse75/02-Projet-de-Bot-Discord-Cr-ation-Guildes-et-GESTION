from enum import StrEnum
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
        populate_by_name=True,
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
    discord_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_CLIENT_ID", "DID_DISCORD_CLIENT_ID"),
    )
    discord_client_secret: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("DISCORD_CLIENT_SECRET", "DID_DISCORD_CLIENT_SECRET"),
    )
    discord_bot_token: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("DISCORD_BOT_TOKEN", "DID_DISCORD_BOT_TOKEN"),
    )
    discord_oauth_redirect_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_REDIRECT_URI", "DID_DISCORD_OAUTH_REDIRECT_URI"),
    )
    session_secret: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("SESSION_SECRET", "DID_SESSION_SECRET"),
    )
    oauth_token_encryption_key: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices(
            "OAUTH_TOKEN_ENCRYPTION_KEY", "DID_OAUTH_TOKEN_ENCRYPTION_KEY"
        ),
    )
    oauth_token_key_version: int = Field(default=1, ge=1)
    artifact_encryption_key: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("ARTIFACT_ENCRYPTION_KEY", "DID_ARTIFACT_ENCRYPTION_KEY"),
    )
    artifact_encryption_key_version: int = Field(default=1, ge=1)
    artifact_previous_encryption_keys: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices(
            "ARTIFACT_PREVIOUS_ENCRYPTION_KEYS",
            "DID_ARTIFACT_PREVIOUS_ENCRYPTION_KEYS",
        ),
    )
    artifact_clipboard_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    artifact_export_ttl_seconds: int = Field(default=2592000, ge=3600, le=7776000)
    artifact_max_items_per_owner: int = Field(default=100, ge=1, le=1000)
    artifact_max_bytes_per_owner: int = Field(default=25000000, ge=2097152, le=250000000)
    session_idle_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    session_absolute_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)
    oauth_state_ttl_seconds: int = Field(default=300, ge=60, le=900)
    guild_discovery_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    authorization_freshness_seconds: int = Field(default=120, ge=15, le=900)
    discord_member_events_enabled: bool = False
    #: ADR-008 does not forbid a NON-privileged Gateway intent for a
    #: documented feature -- REQ-MSG-030's campaign-message-ancestry
    #: producing side needs GUILD_MESSAGES (receives MESSAGE_CREATE/
    #: UPDATE/DELETE) to detect the bot's own resulting message re-entering
    #: ingestion. This does NOT request the privileged MESSAGE_CONTENT
    #: intent -- normalize_gateway_dispatch never extracts content/embeds/
    #: attachments/components from a message payload regardless, only
    #: structural identity (message_id/channel_id/author). Off by default,
    #: same "explicit opt-in" posture as discord_member_events_enabled.
    #:
    #: There is deliberately no "enable MESSAGE_CONTENT" counterpart setting
    #: (Option B, see did.campaigns.message_content_policy's module
    #: docstring): the privileged intent is never requested by this engine
    #: at all, because no code path anywhere in the Campaign Engine ever
    #: extracts content/embeds/attachments regardless of which intents are
    #: active -- a setting that requested it would ask an operator to clear
    #: Discord's privileged-intent verification for a real capability grant
    #: this engine could never actually exercise.
    discord_campaign_message_events_enabled: bool = False
    discord_global_concurrency: int = Field(default=4, ge=1, le=32)
    discord_per_guild_concurrency: int = Field(default=1, ge=1, le=8)
    discord_workload_queue_limit: int = Field(default=1000, ge=10, le=100000)
    discord_worker_poll_seconds: float = Field(default=0.25, ge=0.05, le=10.0)
    discord_worker_recovery_seconds: float = Field(default=2.0, ge=0.1, le=300.0)
    discord_runtime_routing_batch_size: int = Field(default=256, ge=1, le=1000)
    discord_worker_dispatch_batch_size: int = Field(default=512, ge=1, le=10000)
    discord_job_lease_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    discord_distributed_permit_ttl_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    reconcile_active_target_seconds: int = Field(default=21600, ge=300, le=86400)
    reconcile_inactive_target_seconds: int = Field(default=86400, ge=3600, le=604800)
    reconcile_scheduler_poll_seconds: float = Field(default=5.0, ge=0.1, le=300.0)
    websocket_authorization_max_staleness_seconds: float = Field(default=300.0, ge=1.0, le=900.0)
    frontend_post_auth_path: str = "/"
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173",)

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
            required = {
                "discord_client_id": self.discord_client_id,
                "discord_client_secret": self.discord_client_secret,
                "discord_oauth_redirect_uri": self.discord_oauth_redirect_uri,
                "session_secret": self.session_secret,
                "oauth_token_encryption_key": self.oauth_token_encryption_key,
                "artifact_encryption_key": self.artifact_encryption_key,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("production auth configuration is incomplete")
        if not self.frontend_post_auth_path.startswith(
            "/"
        ) or self.frontend_post_auth_path.startswith("//"):
            raise ValueError("frontend_post_auth_path must be a local absolute path")
        return self

    def safe_summary(self) -> dict[str, str | float]:
        return {
            "app_env": self.app_env.value,
            "database_url": "[REDACTED]",
            "database_admin_url": "[REDACTED]",
            "redis_url": "[REDACTED]",
            "log_level": self.log_level,
            "health_timeout_seconds": self.health_timeout_seconds,
            "discord_client_id": "configured" if self.discord_client_id else "missing",
            "discord_client_secret": "[REDACTED]",
            "discord_bot_token": "[REDACTED]",
            "discord_oauth_redirect_uri": self.discord_oauth_redirect_uri or "missing",
            "session_secret": "[REDACTED]",
            "oauth_token_encryption_key": "[REDACTED]",
            "oauth_token_key_version": str(self.oauth_token_key_version),
            "artifact_encryption_key": "[REDACTED]",
            "artifact_encryption_key_version": str(self.artifact_encryption_key_version),
            "artifact_previous_encryption_keys": "[REDACTED]",
        }
