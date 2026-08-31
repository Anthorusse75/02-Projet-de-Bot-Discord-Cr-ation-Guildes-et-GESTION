"""Unit tests for WP9: circuit breaker state machine and the googletrans
adapter's timeout/retry/circuit-breaker wiring. All deterministic, no
network -- the real-network smoke test lives in
test_stage09_translation_network.py, gated behind DID_ALLOW_NETWORK=1.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from did.domain.translation_provider import (
    TranslationCircuitOpenError,
    TranslationProviderError,
    TranslationTimeoutError,
)
from did.translation.circuit_breaker import CircuitBreaker, CircuitState
from did.translation.googletrans_adapter import GoogletransCampaignTranslationProvider

pytestmark = [pytest.mark.security]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_successful_calls_stay_closed(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3)

        async def ok() -> str:
            return "fine"

        for _ in range(10):
            assert await breaker.call(ok) == "fine"
        assert breaker.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_trips_open_after_threshold_consecutive_failures(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)

        async def fail() -> str:
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(fail)
        assert breaker.state is CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_fails_fast_without_calling_operation(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        calls = 0

        async def fail() -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)
        assert breaker.state is CircuitState.OPEN

        with pytest.raises(TranslationCircuitOpenError):
            await breaker.call(fail)
        assert calls == 1  # second call never reached the operation

    @pytest.mark.asyncio
    async def test_half_open_probe_after_cooldown_and_recovery(self) -> None:
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10, _clock=clock)

        async def fail() -> str:
            raise RuntimeError("boom")

        async def ok() -> str:
            return "recovered"

        with pytest.raises(RuntimeError):
            await breaker.call(fail)
        assert breaker.state is CircuitState.OPEN

        clock.advance(5)
        assert breaker.state is CircuitState.OPEN  # cooldown not elapsed yet

        clock.advance(6)
        # mypy narrows `breaker.state` as a stable Literal across statements;
        # it is in fact a time-varying property (cooldown just elapsed).
        assert breaker.state is CircuitState.HALF_OPEN  # type: ignore[comparison-overlap]

        result = await breaker.call(ok)
        assert result == "recovered"
        assert breaker.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_probe_failure_reopens_and_restarts_cooldown(self) -> None:
        clock = _FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=10, _clock=clock)

        async def fail() -> str:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await breaker.call(fail)
        clock.advance(11)
        assert breaker.state is CircuitState.HALF_OPEN

        with pytest.raises(RuntimeError):
            await breaker.call(fail)
        assert breaker.state is CircuitState.OPEN  # type: ignore[comparison-overlap]

        clock.advance(5)
        assert breaker.state is CircuitState.OPEN  # cooldown restarted, not yet elapsed


class TestGoogletransAdapterWiring:
    """Exercises retry/timeout/circuit-breaker plumbing with a fake
    translator factory -- proves the adapter's own logic without touching
    the network or the real googletrans package internals."""

    def _adapter(
        self,
        *,
        translate_fn: Callable[[str, str, str], Awaitable[str]],
        max_attempts: int = 3,
        timeout_seconds: float = 1.0,
        breaker: CircuitBreaker | None = None,
    ) -> GoogletransCampaignTranslationProvider:
        class _FakeResult:
            def __init__(self, text: str, src: str) -> None:
                self.text = text
                self.src = src

        class _FakeClientStub:
            async def aclose(self) -> None:
                return None

        class _FakeTranslator:
            def __init__(self) -> None:
                self.client = _FakeClientStub()

            async def translate(self, text: str, *, src: str, dest: str) -> _FakeResult:
                translated = await translate_fn(text, src, dest)
                return _FakeResult(translated, src)

        return GoogletransCampaignTranslationProvider(
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=0.001,
            circuit_breaker=breaker,
            translator_factory=_FakeTranslator,
            sleep=lambda _seconds: asyncio.sleep(0),
        )

    @pytest.mark.asyncio
    async def test_successful_translation_returns_result(self) -> None:
        async def translate_fn(text: str, src: str, dest: str) -> str:
            return f"[{dest}] {text}"

        adapter = self._adapter(translate_fn=translate_fn)
        result = await adapter.translate("hello", source_language="en", target_language="fr")
        assert result.translated_text == "[fr] hello"
        assert result.source_language == "en"
        assert result.target_language == "fr"

    @pytest.mark.asyncio
    async def test_transient_failure_then_success_is_retried(self) -> None:
        calls = 0

        async def translate_fn(text: str, src: str, dest: str) -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise RuntimeError("transient")
            return "recovered"

        adapter = self._adapter(translate_fn=translate_fn, max_attempts=3)
        result = await adapter.translate("hi", source_language="en", target_language="de")
        assert result.translated_text == "recovered"
        assert calls == 2

    @pytest.mark.asyncio
    async def test_exhausting_retries_raises_provider_error(self) -> None:
        async def translate_fn(text: str, src: str, dest: str) -> str:
            raise RuntimeError("always fails")

        adapter = self._adapter(translate_fn=translate_fn, max_attempts=2)
        with pytest.raises(TranslationProviderError):
            await adapter.translate("hi", source_language="en", target_language="de")

    @pytest.mark.asyncio
    async def test_slow_translation_times_out(self) -> None:
        async def translate_fn(text: str, src: str, dest: str) -> str:
            await asyncio.sleep(10)
            return "too slow"

        adapter = self._adapter(translate_fn=translate_fn, max_attempts=1, timeout_seconds=0.05)
        with pytest.raises(TranslationTimeoutError):
            await adapter.translate("hi", source_language="en", target_language="de")

    @pytest.mark.asyncio
    async def test_repeated_failures_open_the_circuit(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)

        async def translate_fn(text: str, src: str, dest: str) -> str:
            raise RuntimeError("down")

        adapter = self._adapter(translate_fn=translate_fn, max_attempts=1, breaker=breaker)
        with pytest.raises(TranslationProviderError):
            await adapter.translate("hi", source_language="en", target_language="de")

        with pytest.raises(TranslationCircuitOpenError):
            await adapter.translate("hi", source_language="en", target_language="de")
