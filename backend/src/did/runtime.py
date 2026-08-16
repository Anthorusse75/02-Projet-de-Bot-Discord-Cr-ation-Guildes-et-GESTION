import asyncio
import logging
import signal

from did.application.lifecycle import run_until_stopped
from did.infrastructure.logging import EventId, configure_logging, emit_event
from did.settings import Settings


async def run_process(process_name: str) -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:  # Windows event loops do not expose POSIX handlers.
            pass

    async def on_start() -> None:
        emit_event(
            logger,
            logging.INFO,
            EventId.PROCESS_STARTED,
            fields={"process": process_name},
        )

    async def on_stop() -> None:
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
