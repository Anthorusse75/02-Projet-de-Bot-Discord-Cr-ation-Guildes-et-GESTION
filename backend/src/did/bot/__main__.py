from did.runtime import main
from did.settings import Settings


def _validate_bot_settings() -> None:
    settings = Settings()
    if settings.discord_bot_token is None:
        raise SystemExit(
            "DID bot startup aborted: DISCORD_BOT_TOKEN is not configured. "
            "The Gateway process is required for automatic Guild discovery."
        )


if __name__ == "__main__":
    _validate_bot_settings()
    main("bot")
