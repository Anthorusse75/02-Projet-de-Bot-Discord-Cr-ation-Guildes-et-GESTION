import asyncio
import logging
import signal
from collections.abc import Awaitable

from did.application.lifecycle import run_until_stopped
from did.bot.gateway import DiscordGatewayClient
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.logging import EventId, configure_logging, emit_event
from did.infrastructure.runtime_repository import RuntimeRepository
from did.settings import Settings


async def run_process(process_name: str) -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    stop_event = asyncio.Event()
    background_task: asyncio.Task[None] | None = None
    close_runtime: Awaitable[None] | None = None
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:  # Windows event loops do not expose POSIX handlers.
            pass

    async def on_start() -> None:
        nonlocal background_task, close_runtime
        emit_event(
            logger,
            logging.INFO,
            EventId.PROCESS_STARTED,
            fields={"process": process_name},
        )
        if process_name == "bot" and settings.discord_bot_token is not None:
            engine = create_database_engine(settings.database_url.get_secret_value())
            repository = RuntimeRepository(create_session_factory(engine))
            client = DiscordGatewayClient(
                repository,
                enable_member_events=settings.discord_member_events_enabled,
            )
            background_task = asyncio.create_task(
                client.start(settings.discord_bot_token.get_secret_value()),
                name="discord-gateway",
            )
            background_task.add_done_callback(lambda _: stop_event.set())

            async def close_bot() -> None:
                await client.close()
                if background_task is not None:
                    await asyncio.gather(background_task, return_exceptions=True)
                await engine.dispose()

            close_runtime = close_bot()

    async def on_stop() -> None:
        if close_runtime is not None:
            await close_runtime
        emit_event(
            logger,
            logging.INFO,
            EventId.PROCESS_STOPPED,
            fields={"process": process_name},
        )

    await run_until_stopped(stop_event, on_start=on_start, on_stop=on_stop)


def main(process_name: str) -> None:
    try:
        asyncio.run(run_process(process_name))
    except KeyboardInterrupt:
        return
