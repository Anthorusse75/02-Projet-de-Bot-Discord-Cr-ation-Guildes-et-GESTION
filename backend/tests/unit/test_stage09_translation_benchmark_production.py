"""Deterministic, offline coverage for scripts/run_translation_benchmark.py's
"production" measurement (item H of the googletrans placeholder-mutation
remediation mission): FULL_MASKED_MESSAGE wrapped in the same bounded
integrity retry did.campaigns.rendering.render_field_text applies to every
real delivery, and the benchmark's own PASS/BLOCKED/FAIL verdict gated on
that measurement rather than a raw single-attempt strategy.

No real network call is made -- a fake ``provider.translate`` stands in,
exactly like did.campaigns.rendering's own retry tests
(backend/tests/unit/test_stage09_rendering.py), which is what actually
proves this mechanism deterministically; this file additionally proves the
BENCHMARK SCRIPT's own (separate, corpus-shaped) implementation of the same
mechanism is correct and reports honestly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from run_translation_benchmark import (
    PRODUCTION_STRATEGY_LABEL,
    _overall_status,
    _run_one_production,
    _summarize,
)

pytestmark = [pytest.mark.security]

_ITEM = {"id": "test-item", "class": "plain_prose", "content": "Ping <@123456789012345678> now."}


def _mutate_one_placeholder(text: str) -> str:
    match = re.search(r"DIDPH(\d{4})Q([0-9A-F]{8})ZH", text)
    assert match is not None
    index, nonce = match.group(1), match.group(2)
    flipped = "1" if nonce[-1] != "1" else "2"
    mutated = f"DIDPH{index}Q{nonce[:-1]}{flipped}ZH"
    return text[: match.start()] + mutated + text[match.end() :]


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.translated_text = text


class _FakeProvider:
    def __init__(self, translate_fn) -> None:  # type: ignore[no-untyped-def]
        self._translate_fn = translate_fn
        self.calls = 0

    async def translate(
        self, text: str, *, source_language: str, target_language: str
    ) -> _FakeResult:
        self.calls += 1
        return _FakeResult(await self._translate_fn(text))


class TestRunOneProduction:
    async def test_no_corruption_succeeds_with_zero_retries(self) -> None:
        async def _identity(text: str) -> str:
            return text

        provider = _FakeProvider(_identity)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.protected_integrity_ok is True
        assert record.error is None
        assert record.retry_count == 0
        assert record.strategy == PRODUCTION_STRATEGY_LABEL

    async def test_one_corruption_then_success_recovers_with_one_retry(self) -> None:
        calls = 0

        async def _corrupt_first(text: str) -> str:
            nonlocal calls
            calls += 1
            return _mutate_one_placeholder(text) if calls == 1 else text

        provider = _FakeProvider(_corrupt_first)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.protected_integrity_ok is True
        assert record.retry_count == 1
        assert calls == 2

    async def test_persistent_corruption_fails_closed_within_the_bound(self) -> None:
        async def _always_corrupt(text: str) -> str:
            return _mutate_one_placeholder(text)

        provider = _FakeProvider(_always_corrupt)
        record = await _run_one_production(provider, _ITEM, "en", "fr", max_integrity_attempts=2)
        assert record.protected_integrity_ok is False
        assert record.error is None  # an integrity failure, not a transport error
        assert record.retry_count == 1  # max_integrity_attempts - 1
        assert provider.calls == 2  # never more than the configured bound

    async def test_transport_failure_is_recorded_as_an_error_not_an_integrity_failure(self) -> None:
        async def _raise(text: str) -> str:
            raise RuntimeError("simulated transport failure")

        provider = _FakeProvider(_raise)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error == "simulated transport failure"
        assert record.protected_integrity_ok is None


class TestOverallStatusGatesOnProduction:
    def test_pass_requires_the_production_bucket_specifically(self) -> None:
        summary = {
            PRODUCTION_STRATEGY_LABEL: {
                "errors": 0,
                "measurement_records": 10,
                "protected_integrity_rate": 1.0,
                "measurements_that_retried": 1,
            },
            "FULL_MASKED_MESSAGE": {
                "errors": 0,
                "measurement_records": 10,
                # Deliberately below 100% -- the real 311/312 finding that
                # motivated this remediation -- and must NOT block PASS,
                # since the verdict is gated on the retried production
                # bucket, not this raw comparative one.
                "protected_integrity_rate": 311 / 312,
            },
        }
        status, _ = _overall_status(summary)
        assert status == "PASS"

    def test_fail_when_production_bucket_itself_is_below_100_percent(self) -> None:
        summary = {
            PRODUCTION_STRATEGY_LABEL: {
                "errors": 0,
                "measurement_records": 10,
                "protected_integrity_rate": 0.9,
                "measurements_that_retried": 3,
            },
        }
        status, reason = _overall_status(summary)
        assert status == "FAIL"
        assert "100%" in reason

    def test_blocked_when_production_bucket_has_transport_errors(self) -> None:
        summary = {
            PRODUCTION_STRATEGY_LABEL: {
                "errors": 2,
                "measurement_records": 10,
                "protected_integrity_rate": 1.0,
                "measurements_that_retried": 0,
            },
        }
        status, _ = _overall_status(summary)
        assert status == "BLOCKED"

    def test_blocked_when_production_bucket_is_entirely_absent(self) -> None:
        status, _ = _overall_status({})
        assert status == "BLOCKED"


class TestSummarizeTracksRetries:
    async def test_retry_counts_are_aggregated_per_strategy(self) -> None:
        calls = 0

        async def _corrupt_first(text: str) -> str:
            nonlocal calls
            calls += 1
            return _mutate_one_placeholder(text) if calls == 1 else text

        provider = _FakeProvider(_corrupt_first)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        summary = _summarize([record])
        bucket = summary[PRODUCTION_STRATEGY_LABEL]
        assert bucket["measurements_that_retried"] == 1
        assert bucket["total_retry_attempts"] == 1
