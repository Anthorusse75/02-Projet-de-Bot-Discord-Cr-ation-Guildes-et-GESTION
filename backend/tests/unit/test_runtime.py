import pytest

from did import runtime
from did.settings import Settings


@pytest.mark.parametrize("process_name", ["bot", "scheduler"])
async def test_non_discord_processes_start_and_stop_without_discord_token(
    process_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    async def immediate_lifecycle(stop_event: object, *, on_start: object, on_stop: object) -> None:
        del stop_event
        assert callable(on_start)
        assert callable(on_stop)
        await on_start()
        events.append(process_name)
        await on_stop()

    monkeypatch.delenv("DID_DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(runtime, "run_until_stopped", immediate_lifecycle)
    await runtime.run_process(
        process_name,
        configured_settings=Settings(_env_file=None, discord_bot_token=None),
    )
    assert events == [process_name]


async def test_worker_fails_closed_without_discord_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def immediate_lifecycle(stop_event: object, *, on_start: object, on_stop: object) -> None:
        del stop_event, on_stop
        assert callable(on_start)
        await on_start()

    monkeypatch.setattr(runtime, "run_until_stopped", immediate_lifecycle)
    with pytest.raises(RuntimeError, match="requires a configured Discord bot token"):
        await runtime.run_process(
            "worker",
            configured_settings=Settings(_env_file=None, discord_bot_token=None),
        )
