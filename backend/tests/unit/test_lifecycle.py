import asyncio

from did.application.lifecycle import run_until_stopped


async def test_skeleton_lifecycle_starts_and_stops_cleanly() -> None:
    events: list[str] = []
    stop = asyncio.Event()

    async def on_start() -> None:
        events.append("started")
        stop.set()

    async def on_stop() -> None:
        events.append("stopped")

    await run_until_stopped(stop, on_start=on_start, on_stop=on_stop)
    assert events == ["started", "stopped"]
