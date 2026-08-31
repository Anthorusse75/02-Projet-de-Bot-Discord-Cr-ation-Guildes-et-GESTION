"""Real googletrans-backed CampaignTranslationProvider adapter (WP9).

``googletrans`` (unofficial, scrapes the public ``translate.google.com``
endpoint -- pinned ``googletrans==4.0.2`` in ``pyproject.toml``, no API key,
per its real published metadata; see ``docs/90_handoffs/STAGE_09_HANDOFF.md``
for the version/lockfile evidence) is instantiated and imported *only* in
this module. Nothing under ``did.domain`` or ``did.campaigns`` ever imports
it directly -- callers depend on the ``CampaignTranslationProvider`` Protocol
port in ``did.domain.translation_provider``.

Bounded timeout, bounded retry with backoff, and a circuit breaker all wrap
every call: a corrupted or unreachable provider must fail closed
(:class:`TranslationProviderError`), never return a silently wrong or
partial translation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from googletrans import Translator

from did.domain.translation_provider import (
    TranslationProviderError,
    TranslationResult,
    TranslationTimeoutError,
)
from did.translation.circuit_breaker import CircuitBreaker


class GoogletransCampaignTranslationProvider:
    """Structurally implements :class:`CampaignTranslationProvider`."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        circuit_breaker: CircuitBreaker | None = None,
        translator_factory: Callable[[], Translator] = Translator,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._circuit = circuit_breaker or CircuitBreaker()
        self._translator_factory = translator_factory
        self._sleep = sleep

    async def translate(
        self, text: str, *, source_language: str, target_language: str
    ) -> TranslationResult:
        async def attempt_all() -> TranslationResult:
            last_error: Exception | None = None
            for attempt in range(1, self._max_attempts + 1):
                try:
                    return await asyncio.wait_for(
                        self._call_googletrans(text, source_language, target_language),
                        timeout=self._timeout_seconds,
                    )
                except TimeoutError as exc:
                    last_error = TranslationTimeoutError(
                        f"translation timed out after {self._timeout_seconds}s "
                        f"(attempt {attempt}/{self._max_attempts})"
                    )
                    last_error.__cause__ = exc
                except Exception as exc:
                    last_error = TranslationProviderError(
                        f"translation provider error "
                        f"(attempt {attempt}/{self._max_attempts}): {exc}"
                    )
                    last_error.__cause__ = exc
                if attempt < self._max_attempts:
                    await self._sleep(self._retry_backoff_seconds * attempt)
            assert last_error is not None
            raise last_error

        return await self._circuit.call(attempt_all)

    async def _call_googletrans(
        self, text: str, source_language: str, target_language: str
    ) -> TranslationResult:
        translator = self._translator_factory()
        try:
            result = await translator.translate(text, src=source_language, dest=target_language)
        finally:
            close = getattr(translator, "client", None)
            if close is not None:
                await close.aclose()
        return TranslationResult(
            source_language=source_language,
            target_language=target_language,
            translated_text=result.text,
            detected_source_language=getattr(result, "src", None),
        )
