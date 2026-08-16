import asyncio
from collections.abc import Awaitable, Callable

LifecycleHook = Callable[[], Awaitable[None]]


async def run_until_stopped(
    stop_event: asyncio.Event,
    *,
    on_start: LifecycleHook | None = None,
    on_stop: LifecycleHook | None = None,
) -> None:
    """Shared lifecycle contract for the Stage 01 skeleton processes."""
    if on_start is not None:
        await on_start()
    try:
        await stop_event.wait()
    finally:
        if on_stop is not None:
            await on_stop()
