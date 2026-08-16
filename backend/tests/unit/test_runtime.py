import pytest

from did import runtime


@pytest.mark.parametrize("process_name", ["bot", "worker", "scheduler"])
async def test_skeleton_processes_start_and_stop_without_discord_token(
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
    await runtime.run_process(process_name)
    assert events == [process_name]
