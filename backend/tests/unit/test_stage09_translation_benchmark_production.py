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
    SegmentationStrategy,
    _overall_status,
    _run_one,
    _run_one_production,
    _summarize,
)

pytestmark = [pytest.mark.security]

_ITEM = {"id": "test-item", "class": "plain_prose", "content": "Ping <@123456789012345678> now."}
#: Three real sentences, each split into its own SENTENCE_GROUPING segment
#: (see did.translation.segmentation._SENTENCE_BOUNDARY) -- 3 distinct real
#: provider calls, none of them a bare-repeat of the same text.
_MULTI_SENTENCE_ITEM = {
    "id": "test-item-multi",
    "class": "multi_sentence_paragraph",
    "content": "First sentence here. Second sentence here! Third sentence here?",
}


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


class TestProviderInvocationAccounting:
    """External-review finding: `_summarize()` used to derive
    `provider_invocations` from `record.segment_count` -- the structural
    segmentation of the FINAL candidate only -- which silently under-counts
    real provider calls whenever a bounded retry occurred (an earlier,
    failed attempt's call vanished from the count) or a multi-segment
    strategy failed partway through (calls already made before the failure
    vanished too). These tests prove the fix: `provider_invocation_count`
    is the exact, explicit count of every real call attempted, independent
    of `segment_count` and counted even on error/exhaustion."""

    async def test_production_success_without_retry_counts_exactly_one_call(self) -> None:
        async def _identity(text: str) -> str:
            return text

        provider = _FakeProvider(_identity)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.provider_invocation_count == 1
        assert provider.calls == 1

    async def test_one_corruption_then_success_counts_both_real_calls(self) -> None:
        """The exact bug report: attempt 1 calls googletrans and fails
        integrity, attempt 2 calls googletrans and succeeds -- actual
        provider calls = 2, and `segment_count` on the returned record
        (which reflects only the winning attempt) must never be mistaken
        for this count again."""
        calls = 0

        async def _corrupt_first(text: str) -> str:
            nonlocal calls
            calls += 1
            return _mutate_one_placeholder(text) if calls == 1 else text

        provider = _FakeProvider(_corrupt_first)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.retry_count == 1
        assert record.provider_invocation_count == 2
        assert record.segment_count == 1  # structural only -- the winning attempt's shape
        assert provider.calls == 2

    async def test_persistent_corruption_counts_every_attempted_call(self) -> None:
        """The second bug report: both bounded attempts call googletrans
        and both fail integrity -- actual provider calls = 2, even though
        the exhausted record's `segment_count` is 0."""

        async def _always_corrupt(text: str) -> str:
            return _mutate_one_placeholder(text)

        provider = _FakeProvider(_always_corrupt)
        record = await _run_one_production(provider, _ITEM, "en", "fr", max_integrity_attempts=2)
        assert record.protected_integrity_ok is False
        assert record.provider_invocation_count == 2
        assert record.segment_count == 0  # structural field, never the call count
        assert provider.calls == 2

    async def test_transport_exception_on_first_invocation_still_counts_that_call(self) -> None:
        async def _raise(text: str) -> str:
            raise RuntimeError("simulated transport failure")

        provider = _FakeProvider(_raise)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error == "simulated transport failure"
        assert record.provider_invocation_count == 1
        assert provider.calls == 1

    async def test_segmented_comparative_strategy_reports_the_real_call_count(self) -> None:
        """A raw comparative strategy (never retried) that splits into
        multiple real segments must report exactly that many real calls --
        not conflated with `segment_count`, even though they happen to be
        equal here (no failure occurred)."""

        async def _identity(text: str) -> str:
            return text

        provider = _FakeProvider(_identity)
        record = await _run_one(
            provider,
            _MULTI_SENTENCE_ITEM,
            SegmentationStrategy.SENTENCE_GROUPING,
            "en",
            "fr",
        )
        assert record.error is None
        assert record.segment_count == 3
        assert record.provider_invocation_count == 3
        assert provider.calls == 3

    async def test_segmented_strategy_failing_partway_still_reports_calls_already_made(
        self,
    ) -> None:
        """The mission's own explicit scenario: a segmented strategy fails
        after one or more successful segment calls -- every call already
        attempted before the failure must still be counted, never reset to
        0 alongside the (correctly) zeroed `segment_count`."""
        calls = 0

        async def _fail_on_second_segment(text: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated mid-segmentation transport failure")
            return text

        provider = _FakeProvider(_fail_on_second_segment)
        record = await _run_one(
            provider,
            _MULTI_SENTENCE_ITEM,
            SegmentationStrategy.SENTENCE_GROUPING,
            "en",
            "fr",
        )
        assert record.error is not None
        assert record.segment_count == 0  # the strategy never completed
        assert record.provider_invocation_count == 2  # but 2 real calls were already made
        assert provider.calls == 2

    async def test_summarize_counts_invocations_from_error_records_too(self) -> None:
        """The `_summarize()` half of the same bug: error records used to
        be skipped entirely (a `continue` before the accumulation line),
        silently dropping their real invocation count from the aggregate."""

        async def _raise(text: str) -> str:
            raise RuntimeError("boom")

        provider = _FakeProvider(_raise)
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.provider_invocation_count == 1
        summary = _summarize([record])
        bucket = summary[PRODUCTION_STRATEGY_LABEL]
        assert bucket["errors"] == 1
        assert bucket["provider_invocations"] == 1

    async def test_totals_aggregate_the_explicit_counter_across_records(self) -> None:
        async def _identity(text: str) -> str:
            return text

        provider = _FakeProvider(_identity)
        record_a = await _run_one_production(provider, _ITEM, "en", "fr")
        record_b = await _run_one(
            provider, _MULTI_SENTENCE_ITEM, SegmentationStrategy.SENTENCE_GROUPING, "en", "fr"
        )
        summary = _summarize([record_a, record_b])
        assert summary["_totals"]["provider_invocations_all_strategies"] == 1 + 3


class TestMaxIntegrityAttemptsValidation:
    @pytest.mark.parametrize("invalid", [0, -1, -3])
    async def test_run_one_production_rejects_non_positive_bound(self, invalid: int) -> None:
        async def _identity(text: str) -> str:
            return text

        provider = _FakeProvider(_identity)
        with pytest.raises(ValueError, match="max_integrity_attempts must be at least 1"):
            await _run_one_production(provider, _ITEM, "en", "fr", max_integrity_attempts=invalid)


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
