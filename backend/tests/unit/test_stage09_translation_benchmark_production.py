"""Deterministic, offline coverage for scripts/run_translation_benchmark.py's
"production" measurement (item H of the googletrans placeholder-mutation
remediation mission): FULL_MASKED_MESSAGE wrapped in the same bounded
integrity retry did.campaigns.rendering.render_field_text applies to every
real delivery, and the benchmark's own PASS/BLOCKED/FAIL verdict gated on
that measurement rather than a raw single-attempt strategy.

No real network call is made -- a fake ``provider.translate`` stands in for
the retry/PASS-FAIL-logic tests, exactly like did.campaigns.rendering's own
retry tests (backend/tests/unit/test_stage09_rendering.py); the
transport-attempt-ACCOUNTING tests below instead drive the REAL
``GoogleTranslateRpcCampaignTranslationProvider`` against an
``httpx.MockTransport`` (still no real network call), because accounting
correctness depends on the adapter's own internal HTTP-level retry
behavior, which a fake provider that never touches HTTP cannot exercise --
see ``TestTransportAttemptAccounting``'s own docstring for why the earlier
``_FakeProvider``-based accounting tests were replaced.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from did.translation.circuit_breaker import CircuitBreaker
from did.translation.google_translate_rpc_adapter import (
    GoogleTranslateRpcCampaignTranslationProvider,
)
from run_translation_benchmark import (
    PRODUCTION_STRATEGY_LABEL,
    SegmentationStrategy,
    _overall_status,
    _run_one,
    _run_one_production,
    _summarize,
)

pytestmark = [pytest.mark.security]


async def _no_sleep(_seconds: float) -> None:
    return None


def _valid_response_body(translated_text: str, *, rpc_id: str = "MkEWBc") -> str:
    """A batchexecute response body in the real captured shape (see
    did.translation.google_translate_rpc_adapter's own module docstring
    and test_stage09_google_translate_rpc_adapter.py for the full proven
    contract this mirrors)."""
    translation_data = [None, None, None, True, None, [[translated_text]]]
    segment_entry = [translation_data]
    level1 = [segment_entry]
    inner = [None, level1, "en"]
    entry = ["wrb.fr", rpc_id, json.dumps(inner), None, None, None, "generic"]
    chunk_line = json.dumps([entry])
    return f")]}}'\n\n{chunk_line}\n"


def _extract_sent_text(request: httpx.Request) -> str:
    """Reads back the exact text a real POST attempt sent, so a MockTransport
    handler can echo it as the "translation" -- a trivially
    integrity-preserving same-text round trip, since the whole point of
    these tests is transport-attempt accounting, not translation content."""
    sent = httpx.QueryParams(request.content.decode())
    envelope = json.loads(sent["f.req"])
    rpc_args = json.loads(envelope[0][0][1])
    text = rpc_args[0][0]
    assert isinstance(text, str)
    return text


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


class TestTransportAttemptAccounting:
    """Third external-review finding: `provider_invocation_count` counted
    calls to the high-level `provider.translate(...)` PORT, which is not
    the same thing as real HTTP RPC POST attempts -- `GoogleTranslateRpc
    CampaignTranslationProvider.translate()` has its own bounded internal
    retry (`max_attempts`, default 3), so one logical `translate()` call
    can silently generate up to 3 real POSTs before returning or raising
    (the adapter's own deterministic HTTP-429-then-success test already
    proves this). The earlier version of this class used `_FakeProvider`,
    which never touches HTTP at all and therefore could not exercise (or
    catch a regression in) this accounting -- these tests instead drive
    the REAL `GoogleTranslateRpcCampaignTranslationProvider` against an
    `httpx.MockTransport` fake HTTP transport, so `count_transport_
    attempts()` (the mechanism `_run_one`/`_run_one_production` now use)
    observes real transport-layer attempts exactly as it would against a
    real network."""

    async def test_single_successful_call_counts_one_transport_attempt(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_valid_response_body(_extract_sent_text(request)))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is None
        assert record.retry_count == 0
        assert record.provider_invocation_count == 1

    async def test_transport_429_then_success_counts_both_attempts(self) -> None:
        """1 `provider.translate()` call, but the adapter's own internal
        retry makes 2 real POSTs -- `provider_invocation_count` must
        report 2, not 1."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, text=_valid_response_body(_extract_sent_text(request)))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is None
        assert record.retry_count == 0  # no INTEGRITY retry -- purely the adapter's own retry
        assert record.provider_invocation_count == 2
        assert call_count == 2

    async def test_two_429s_then_success_counts_all_three_attempts(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, text=_valid_response_body(_extract_sent_text(request)))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is None
        assert record.provider_invocation_count == 3
        assert call_count == 3

    async def test_persistent_429_exhausts_the_bound_and_counts_every_attempt(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is not None  # a real transport error, not an integrity failure
        assert record.provider_invocation_count == 3

    async def test_timeout_then_success_counts_both_attempts(self) -> None:
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(1.0)
                return httpx.Response(200, text="unused")
            return httpx.Response(200, text=_valid_response_body(_extract_sent_text(request)))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            timeout_seconds=0.05,
            max_attempts=2,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is None
        assert record.provider_invocation_count == 2

    async def test_circuit_already_open_counts_zero_new_attempts(self) -> None:
        """Once the circuit is open, the wrapped operation (and therefore
        `_call_rpc`, and therefore the real POST) is never invoked at all
        -- see `CircuitBreaker.call`. The next measurement must report 0
        new transport attempts, not a stale/carried-over count."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=1,
            circuit_breaker=breaker,
        )
        first = await _run_one_production(provider, _ITEM, "en", "fr")
        assert first.error is not None
        assert first.provider_invocation_count == 1  # trips the circuit open

        second = await _run_one_production(provider, _ITEM, "en", "fr")
        assert second.error is not None  # TranslationCircuitOpenError, fails fast
        assert second.provider_invocation_count == 0  # no HTTP attempt was made this time

    async def test_segmented_strategy_counts_every_segments_internal_retries(self) -> None:
        """3 real segments (SENTENCE_GROUPING on the 3-sentence corpus
        item), each needing one adapter-internal retry -- 6 real POSTs
        total, all within the ONE `count_transport_attempts()` context
        that wraps the whole measurement."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                return httpx.Response(429, text="rate limited")
            return httpx.Response(200, text=_valid_response_body(_extract_sent_text(request)))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one(
            provider, _MULTI_SENTENCE_ITEM, SegmentationStrategy.SENTENCE_GROUPING, "en", "fr"
        )
        assert record.error is None
        assert record.segment_count == 3
        assert record.provider_invocation_count == 6
        assert call_count == 6

    async def test_integrity_retry_includes_every_internal_transport_attempt(self) -> None:
        """attempt 1: POST #1 is a transient 429 (adapter-internal retry),
        POST #2 succeeds but with a corrupted placeholder (fails
        integrity, triggers a bounded INTEGRITY retry with fresh
        placeholders); attempt 2: POST #3 succeeds cleanly. 3 real POSTs
        total, spanning both retry mechanisms."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, text="rate limited")
            text = _extract_sent_text(request)
            if call_count == 2:
                text = _mutate_one_placeholder(text)
            return httpx.Response(200, text=_valid_response_body(text))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is None
        assert record.protected_integrity_ok is True
        assert record.retry_count == 1  # one bounded INTEGRITY retry
        assert record.provider_invocation_count == 3
        assert call_count == 3

    async def test_partial_segmentation_failure_counts_attempts_already_made(self) -> None:
        """Segment 1 succeeds in 1 POST; segment 2 exhausts the adapter's
        own 3-attempt bound and raises, stopping the strategy before
        segment 3 is ever attempted (segments translate strictly
        sequentially). Total real POSTs = 1 + 3 = 4; segment 3 contributes
        0. `segment_count` is correctly 0 (the strategy never completed),
        but `provider_invocation_count` must still report every attempt
        that was genuinely made."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, text=_valid_response_body(_extract_sent_text(request)))
            return httpx.Response(429, text="rate limited")

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one(
            provider, _MULTI_SENTENCE_ITEM, SegmentationStrategy.SENTENCE_GROUPING, "en", "fr"
        )
        assert record.error is not None
        assert record.segment_count == 0  # the strategy never completed
        assert record.provider_invocation_count == 4  # 1 (segment 1) + 3 (segment 2, exhausted)
        assert call_count == 4  # segment 3 was never attempted

    async def test_summarize_and_totals_reflect_real_attempts_not_translate_calls(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=3,
        )
        record = await _run_one_production(provider, _ITEM, "en", "fr")
        assert record.error is not None
        assert record.provider_invocation_count == 3  # NOT 1 (a single translate() call)

        summary = _summarize([record])
        bucket = summary[PRODUCTION_STRATEGY_LABEL]
        assert bucket["errors"] == 1
        assert bucket["provider_invocations"] == 3
        assert summary["_totals"]["provider_invocations_all_strategies"] == 3


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
