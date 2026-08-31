"""A minimal, dependency-free circuit breaker (WP9).

CLOSED -- calls pass through; each failure increments a counter, each
success resets it. After ``failure_threshold`` consecutive failures the
breaker trips OPEN: every call fails fast with
:class:`TranslationCircuitOpenError` without invoking the wrapped callable
at all, until ``cooldown_seconds`` has elapsed. Then HALF_OPEN admits calls
again as probes: success closes the breaker, failure reopens it and
restarts the cooldown. Known simplification: concurrent callers can all
observe HALF_OPEN and all probe at once (no single-probe admission lock) --
acceptable for a benchmark/campaign-send workload where the worst case is a
few extra requests during recovery, not an incorrect translation.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from did.domain.translation_provider import TranslationCircuitOpenError

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0
    _state: CircuitState = CircuitState.CLOSED
    _consecutive_failures: int = 0
    _opened_at: float | None = None
    _clock: Callable[[], float] = time.monotonic

    @property
    def state(self) -> CircuitState:
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if self._clock() - self._opened_at >= self.cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        current = self.state
        if current is CircuitState.OPEN:
            raise TranslationCircuitOpenError(
                f"circuit open: {self._consecutive_failures} consecutive failures, "
                f"retry after cooldown"
            )
        try:
            result = await operation()
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def _on_success(self) -> None:
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def _on_failure(self) -> None:
        self._consecutive_failures += 1
        was_half_open = self._state is CircuitState.OPEN and self.state is CircuitState.HALF_OPEN
        if was_half_open or self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
