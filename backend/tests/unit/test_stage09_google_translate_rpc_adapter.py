"""Deterministic, offline coverage for the Google Translate Web RPC
("batchexecute") CampaignTranslationProvider adapter -- the current
production translation transport for Stage09 (see
did.translation.google_translate_rpc_adapter's own module docstring for the
full transport-switch rationale, including the "Wire contract correction"
note this file's fixtures are aligned to).

No real network call is ever made here: httpx.MockTransport stands in for
the real Google endpoint, giving full control over both the HTTP-level
behavior (status codes, timeouts, transport errors) and the exact response
body shape, so every fail-closed path -- malformed response, missing RPC
block, empty translation, non-2xx status, timeout -- is exercised
deterministically. This proves the MECHANICS of the adapter (parsing,
retry, circuit breaker, client lifecycle, fail-closed behavior).

Critically, the canonical response fixture below (`_build_inner` /
`_build_response_body`) is built to the STRUCTURAL SHAPE the product owner's
own real, same-machine HTTP-200 probe proved -- translation content at
``inner[1][0][0]`` ("translation_data"), translated parts at
``translation_data[5]``, a spacing flag at ``translation_data[3]``, detected
source at ``inner[2]`` -- not a shape invented to match whatever the parser
happened to assume. An earlier revision of both this adapter and this test
file used a shape that only matched the parser's own assumptions, which is
circular evidence and was flagged by external audit; it has been replaced
here. These tests still do not and cannot prove Google's real endpoint
returns exactly this shape on every call -- that is what the product
owner's real-network smoke test is for (see
backend/tests/network/test_stage09_translation_network.py).
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from did.campaigns.rendering import render_field_text
from did.domain.translation_provider import (
    TranslationCircuitOpenError,
    TranslationProviderError,
    TranslationTimeoutError,
)
from did.messaging.protector import IntegrityViolation
from did.messaging.translation_policy import FieldPath, TranslatableFieldKind, TranslationUnit
from did.translation.circuit_breaker import CircuitBreaker
from did.translation.google_translate_rpc_adapter import (
    _DEFAULT_USER_AGENT,
    _REFERER,
    GoogleTranslateRpcCampaignTranslationProvider,
    _default_client_factory,
    build_form_data,
    extract_detected_source_language,
    extract_translated_text,
    find_rpc_entry,
    parse_batchexecute_response,
    parse_inner_payload,
)

pytestmark = [pytest.mark.security]

CAMPAIGN_ID = uuid4()
GUILD_ID = 990000101


async def _no_sleep(_seconds: float) -> None:
    return None


def _build_inner(
    translated_parts: list[str] | None,
    *,
    use_spacing: bool = True,
    detected_source: str | None = "en",
) -> list[object]:
    """The canonical CAPTURED-shape inner payload: ``inner[1][0][0]`` is the
    ``translation_data`` list (index 3 the spacing flag, index 5 the
    translated parts), ``inner[2]`` the optional detected source language.
    ``inner[0]`` is left ``None`` -- unused/unmodeled here, exactly as in
    the real captured response, where its content is never consumed by this
    adapter."""
    parts: list[object] = [] if translated_parts is None else [[part] for part in translated_parts]
    translation_data: list[object] = [None, None, None, use_spacing, None, parts]
    segment_entry = [translation_data]
    level1 = [segment_entry]
    inner: list[object] = [None, level1]
    if detected_source is not None:
        inner.append(detected_source)
    return inner


def _wrap_inner(inner: object, *, rpc_id: str = "MkEWBc") -> str:
    """Wraps an arbitrary (possibly deliberately malformed) inner payload
    object into a full batchexecute response body -- the XSSI-prefixed,
    ``wrb.fr``-entry-carrying outer envelope, unaffected by the wire
    contract correction (only the inner payload's own shape changed)."""
    inner_json = json.dumps(inner)
    entry = ["wrb.fr", rpc_id, inner_json, None, None, None, "generic"]
    chunk_line = json.dumps([entry])
    return f")]}}'\n\n{chunk_line}\n"


def _build_response_body(
    translated_parts: list[str] | None,
    *,
    use_spacing: bool = True,
    detected_source: str | None = "en",
    rpc_id: str = "MkEWBc",
) -> str:
    """Builds a full batchexecute response body in the canonical captured
    shape -- see ``_build_inner``."""
    inner = _build_inner(translated_parts, use_spacing=use_spacing, detected_source=detected_source)
    return _wrap_inner(inner, rpc_id=rpc_id)


class _TrackedClient(httpx.AsyncClient):
    """A real httpx.AsyncClient wired to a MockTransport, with its own
    close tracked -- proves the adapter's client lifecycle (item 5: exact
    client cleanup/lifecycle) without needing a hand-rolled fake."""

    def __init__(self, transport: httpx.MockTransport) -> None:
        super().__init__(
            transport=transport, headers={"User-Agent": _DEFAULT_USER_AGENT, "Referer": _REFERER}
        )
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


class TestBuildFormData:
    """Item D: the request contract is asserted exactly, never normalized
    away -- the product owner's own proven envelope has RPC arguments
    shaped ``[[TEXT, SOURCE, TARGET, True], [None]]``, not the bare
    ``[TEXT, SOURCE, TARGET, True]`` an earlier revision sent."""

    def test_f_req_decodes_to_exactly_the_proven_envelope(self) -> None:
        data = build_form_data("Hello world", "en", "fr")
        envelope = json.loads(data["f.req"])
        assert len(envelope) == 1
        assert len(envelope[0]) == 1
        rpc_call = envelope[0][0]
        assert rpc_call[0] == "MkEWBc"
        assert rpc_call[2] is None
        assert rpc_call[3] == "generic"
        rpc_args = json.loads(rpc_call[1])
        assert rpc_args == [["Hello world", "en", "fr", True], [None]]

    def test_unicode_text_survives_the_encoding_round_trip(self) -> None:
        data = build_form_data("Café ünïcödé 日本語", "en", "fr")
        envelope = json.loads(data["f.req"])
        rpc_args = json.loads(envelope[0][0][1])
        assert rpc_args[0][0] == "Café ünïcödé 日本語"

    def test_f_req_is_compact_and_preserves_non_ascii_bytes(self) -> None:
        data = build_form_data("Café", "en", "fr")
        # compact separators (",", ":") -- no incidental whitespace
        assert " " not in data["f.req"]
        # ensure_ascii=False -- the literal accented character survives,
        # not a \uXXXX escape
        assert "Café" in data["f.req"]
        assert "\\u00e9" not in data["f.req"]


class TestParseBatchexecuteResponsePipeline:
    def test_valid_response_extracts_translated_text_and_detected_language(self) -> None:
        body = _build_response_body(["Bonjour le monde"], detected_source="en")
        result = parse_batchexecute_response(body)
        assert result.translated_text == "Bonjour le monde"
        assert result.detected_source_language == "en"

    def test_multiple_parts_with_spacing_true_are_joined_with_a_space(self) -> None:
        body = _build_response_body(["First", "Second"], use_spacing=True)
        result = parse_batchexecute_response(body)
        assert result.translated_text == "First Second"

    def test_multiple_parts_with_spacing_false_are_concatenated_directly(self) -> None:
        body = _build_response_body(["First", "Second"], use_spacing=False)
        result = parse_batchexecute_response(body)
        assert result.translated_text == "FirstSecond"

    def test_detected_source_present(self) -> None:
        body = _build_response_body(["Bonjour"], detected_source="en")
        result = parse_batchexecute_response(body)
        assert result.detected_source_language == "en"

    def test_detected_source_absent_returns_none_not_an_error(self) -> None:
        body = _build_response_body(["Bonjour"], detected_source=None)
        result = parse_batchexecute_response(body)
        assert result.translated_text == "Bonjour"
        assert result.detected_source_language is None

    @pytest.mark.parametrize(
        ("text", "lang"),
        [
            ("La campagne sera publiée demain matin.", "fr"),
            ("Die Kampagne wird morgen früh veröffentlicht.", "de"),
            ("La campaña se publicará mañana por la mañana.", "es"),
            ("The campaign will be published tomorrow morning.", "en"),
        ],
    )
    def test_unicode_translated_text_survives_every_language(self, text: str, lang: str) -> None:
        body = _build_response_body([text], detected_source="en")
        result = parse_batchexecute_response(body)
        assert result.translated_text == text
        assert result.detected_source_language == "en"

    def test_missing_rpc_block_fails_closed(self) -> None:
        body = ')]}\'\n\n[["wrb.fr","SomeOtherRpc","{}",null,null,null,"generic"]]\n'
        with pytest.raises(TranslationProviderError, match="no 'MkEWBc' RPC block"):
            parse_batchexecute_response(body)

    def test_garbage_response_body_fails_closed(self) -> None:
        with pytest.raises(TranslationProviderError, match="no 'MkEWBc' RPC block"):
            parse_batchexecute_response("this is not batchexecute output at all")

    def test_malformed_outer_json_lines_are_skipped_not_crashed_on(self) -> None:
        # A line that starts with "[" but is not valid JSON must never raise
        # a raw JSONDecodeError out of this pipeline -- it is simply not a
        # candidate line, and parsing continues to look for a real match.
        garbage_then_valid = "[not valid json\n" + _build_response_body(["OK"])
        result = parse_batchexecute_response(garbage_then_valid)
        assert result.translated_text == "OK"

    def test_entry_with_non_string_payload_fails_closed(self) -> None:
        entry = ["wrb.fr", "MkEWBc", 12345, None, None, None, "generic"]
        chunk_line = json.dumps([entry])
        body = f")]}}'\n\n{chunk_line}\n"
        with pytest.raises(TranslationProviderError, match="not a JSON-encoded string"):
            parse_batchexecute_response(body)

    def test_malformed_inner_json_fails_closed(self) -> None:
        entry = ["wrb.fr", "MkEWBc", "{not valid json", None, None, None, "generic"]
        chunk_line = json.dumps([entry])
        body = f")]}}'\n\n{chunk_line}\n"
        with pytest.raises(TranslationProviderError, match="not valid JSON"):
            parse_batchexecute_response(body)

    def test_malformed_top_level_translation_result_fails_closed(self) -> None:
        """``inner[1]`` (a.k.a. "[1]") must be a non-empty list."""
        inner = [None, "not-a-list", "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match=r"translation result \(index 1\)"):
            parse_batchexecute_response(body)

    def test_missing_top_level_translation_result_fails_closed(self) -> None:
        inner: list[object] = [None]  # inner[1] itself raises IndexError
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match="missing top-level translation result"):
            parse_batchexecute_response(body)

    def test_malformed_segment_entry_fails_closed(self) -> None:
        """``inner[1][0]`` (a.k.a. "[1][0]") must be a non-empty list."""
        inner = [None, ["not-a-list-segment"], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match=r"segment entry \(\[1\]\[0\]\)"):
            parse_batchexecute_response(body)

    def test_malformed_translation_data_fails_closed(self) -> None:
        """``inner[1][0][0]`` (a.k.a. "[1][0][0]") must be a list."""
        inner = [None, [["not-a-list-translation-data"]], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(
            TranslationProviderError, match=r"translation data \(\[1\]\[0\]\[0\]\) is not a list"
        ):
            parse_batchexecute_response(body)

    def test_missing_spacing_flag_index_fails_closed(self) -> None:
        translation_data: list[object] = [None, None, None]  # length 3: no index 3
        inner = [None, [[translation_data]], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match="missing the spacing flag"):
            parse_batchexecute_response(body)

    def test_missing_translated_parts_index_fails_closed(self) -> None:
        translation_data: list[object] = [None, None, None, True]  # length 4: no index 5
        inner = [None, [[translation_data]], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match="missing translated parts"):
            parse_batchexecute_response(body)

    def test_empty_parts_list_fails_closed(self) -> None:
        body = _build_response_body(None)  # translation_data[5] == []
        with pytest.raises(TranslationProviderError, match="no translated parts present"):
            parse_batchexecute_response(body)

    def test_invalid_part_structure_fails_closed(self) -> None:
        translation_data: list[object] = [None, None, None, True, None, ["not-a-list-part"]]
        inner = [None, [[translation_data]], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match="malformed translated part"):
            parse_batchexecute_response(body)

    def test_part_with_none_text_fails_closed(self) -> None:
        translation_data: list[object] = [None, None, None, True, None, [[None]]]
        inner = [None, [[translation_data]], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match="malformed translated part"):
            parse_batchexecute_response(body)

    def test_non_string_translated_part_fails_closed(self) -> None:
        translation_data: list[object] = [None, None, None, True, None, [[12345]]]
        inner = [None, [[translation_data]], "en"]
        body = _wrap_inner(inner)
        with pytest.raises(TranslationProviderError, match="is not text"):
            parse_batchexecute_response(body)

    def test_empty_translated_text_fails_closed(self) -> None:
        body = _build_response_body([""])
        with pytest.raises(TranslationProviderError, match="translated text is empty"):
            parse_batchexecute_response(body)

    def test_whitespace_only_translated_text_fails_closed(self) -> None:
        body = _build_response_body(["   "])
        with pytest.raises(TranslationProviderError, match="translated text is empty"):
            parse_batchexecute_response(body)


class TestIndividualPipelineFunctions:
    """Item 2's own requirement: request payload construction, HTTP request,
    response extraction, inner RPC JSON parsing, and translated-segment
    reconstruction must each be independently testable, not only through
    the composed pipeline above."""

    def test_find_rpc_entry_returns_the_matching_entry(self) -> None:
        body = _build_response_body(["Bonjour"])
        entry = find_rpc_entry(body)
        assert entry[0] == "wrb.fr"
        assert entry[1] == "MkEWBc"

    def test_find_rpc_entry_raises_when_absent(self) -> None:
        with pytest.raises(TranslationProviderError):
            find_rpc_entry(")]}'\n\n[]\n")

    def test_parse_inner_payload_round_trips_a_real_entry(self) -> None:
        body = _build_response_body(["Bonjour"], detected_source="en")
        entry = find_rpc_entry(body)
        inner = parse_inner_payload(entry)
        assert inner[2] == "en"

    def test_extract_translated_text_from_a_pre_parsed_inner_payload(self) -> None:
        inner = _build_inner(["Bonjour"], detected_source=None)
        assert extract_translated_text(inner) == "Bonjour"

    def test_extract_detected_source_language_from_a_pre_parsed_inner_payload(self) -> None:
        inner = _build_inner(["Bonjour"], detected_source="en")
        assert extract_detected_source_language(inner) == "en"


class TestExactRequestContract:
    """Item D: assert the request the adapter actually sends decodes to
    exactly the product owner's own proven contract -- endpoint, RPC id,
    query parameters, ``f.req`` envelope shape, and ``Referer`` header. No
    test here normalizes away a mismatch."""

    async def test_actual_http_request_carries_exactly_the_proven_query_parameters(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text=_build_response_body(["Bonjour"]))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)), sleep=_no_sleep
        )
        await provider.translate("Hello", source_language="en", target_language="fr")
        assert len(captured) == 1
        params = captured[0].url.params
        assert params["rpcids"] == "MkEWBc"
        assert params["bl"] == "boq_translate-webserver_20201207.13_p0"
        assert params["soc-app"] == "1"
        assert params["soc-platform"] == "1"
        assert params["soc-device"] == "1"
        assert params["rt"] == "c"
        # Deliberately absent: an earlier revision invented these without
        # empirical proof they were required or even accepted.
        assert "source-path" not in params
        assert "f.sid" not in params
        assert "hl" not in params
        assert "_reqid" not in params

    async def test_actual_http_request_carries_the_proven_f_req_envelope(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text=_build_response_body(["Bonjour"]))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)), sleep=_no_sleep
        )
        await provider.translate("Hello world", source_language="en", target_language="fr")
        sent = httpx.QueryParams(captured[0].content.decode())
        envelope = json.loads(sent["f.req"])
        rpc_call = envelope[0][0]
        assert rpc_call[0] == "MkEWBc"
        rpc_args = json.loads(rpc_call[1])
        assert rpc_args == [["Hello world", "en", "fr", True], [None]]

    def test_default_client_factory_sets_the_proven_referer_header(self) -> None:
        client = _default_client_factory()
        try:
            assert client.headers["referer"] == "https://translate.google.com/"
        finally:
            asyncio.run(client.aclose())

    async def test_actual_http_request_carries_the_proven_referer_header(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text=_build_response_body(["Bonjour"]))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)), sleep=_no_sleep
        )
        await provider.translate("Hello", source_language="en", target_language="fr")
        assert captured[0].headers["referer"] == "https://translate.google.com/"


class TestGoogleTranslateRpcCampaignTranslationProviderHttp:
    """HTTP-level behavior via a real httpx.AsyncClient bound to
    httpx.MockTransport -- no real network, full control over status codes,
    timeouts, and transport-level failures."""

    async def test_successful_translation_returns_result_and_closes_the_client(self) -> None:
        body = _build_response_body(["Bonjour le monde"], detected_source="en")
        tracked: list[_TrackedClient] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body)

        def factory() -> httpx.AsyncClient:
            client = _TrackedClient(httpx.MockTransport(handler))
            tracked.append(client)
            return client

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=factory, sleep=_no_sleep
        )
        result = await provider.translate("Hello world", source_language="en", target_language="fr")
        assert result.translated_text == "Bonjour le monde"
        assert result.source_language == "en"
        assert result.target_language == "fr"
        assert result.detected_source_language == "en"
        assert len(tracked) == 1
        assert tracked[0].closed is True

    async def test_http_429_is_retried_then_fails_closed_as_provider_error(self) -> None:
        calls = 0
        tracked: list[_TrackedClient] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        def factory() -> httpx.AsyncClient:
            nonlocal calls
            calls += 1
            client = _TrackedClient(httpx.MockTransport(handler))
            tracked.append(client)
            return client

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=factory, sleep=_no_sleep, max_attempts=3
        )
        with pytest.raises(TranslationProviderError, match="HTTP 429"):
            await provider.translate("Hi", source_language="en", target_language="fr")
        assert calls == 3  # never more than the configured bound
        assert all(client.closed for client in tracked)

    async def test_http_403_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=1,
        )
        with pytest.raises(TranslationProviderError, match="HTTP 403"):
            await provider.translate("Hi", source_language="en", target_language="fr")

    async def test_http_5xx_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="service unavailable")

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=1,
        )
        with pytest.raises(TranslationProviderError, match="HTTP 503"):
            await provider.translate("Hi", source_language="en", target_language="fr")

    async def test_malformed_response_body_fails_closed_through_the_full_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not batchexecute output")

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=1,
        )
        with pytest.raises(TranslationProviderError):
            await provider.translate("Hi", source_language="en", target_language="fr")

    async def test_generic_transport_error_is_wrapped_as_provider_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated connection failure", request=request)

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=1,
        )
        with pytest.raises(TranslationProviderError):
            await provider.translate("Hi", source_language="en", target_language="fr")

    async def test_timeout_raises_translation_timeout_error_and_still_closes_client(self) -> None:
        async def slow_handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1.0)
            return httpx.Response(200, text="unused")

        tracked: list[_TrackedClient] = []

        def factory() -> httpx.AsyncClient:
            client = _TrackedClient(httpx.MockTransport(slow_handler))
            tracked.append(client)
            return client

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=factory, sleep=_no_sleep, timeout_seconds=0.05, max_attempts=1
        )
        with pytest.raises(TranslationTimeoutError):
            await provider.translate("Hi", source_language="en", target_language="fr")
        assert tracked[0].closed is True

    async def test_constructor_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            GoogleTranslateRpcCampaignTranslationProvider(timeout_seconds=0)

    async def test_constructor_rejects_non_positive_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts must be at least 1"):
            GoogleTranslateRpcCampaignTranslationProvider(max_attempts=0)


class TestCircuitBreakerIntegration:
    async def test_repeated_failures_open_the_circuit_and_stop_calling_the_transport(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(429, text="rate limited")

        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)),
            sleep=_no_sleep,
            max_attempts=1,
            circuit_breaker=breaker,
        )
        with pytest.raises(TranslationProviderError):
            await provider.translate("Hi", source_language="en", target_language="fr")
        calls_after_first_failure = calls

        with pytest.raises(TranslationCircuitOpenError):
            await provider.translate("Hi", source_language="en", target_language="fr")
        # The transport was never reached the second time -- the circuit
        # failed fast instead.
        assert calls == calls_after_first_failure


class TestPlaceholderMutationEndToEndThroughTheRealAdapter:
    """Item 13's explicit callout: a provider output that mutates a DIDPH
    token must still reach did.messaging.protector's validator through THIS
    adapter specifically (not just proven generically against a fake
    translate_masked_text elsewhere), be rejected, and recover via bounded
    integrity retry with fresh placeholders -- or remain fail-closed if the
    corruption persists."""

    UNIT = TranslationUnit(
        FieldPath(TranslatableFieldKind.CONTENT), "Ping <@123456789012345678> now."
    )

    def _corrupt_placeholder_in_text(self, masked_text: str) -> str:
        import re

        match = re.search(r"DIDPH(\d{4})Q([0-9A-F]{8})ZH", masked_text)
        assert match is not None
        index, nonce = match.group(1), match.group(2)
        flipped = "1" if nonce[-1] != "1" else "2"
        mutated = f"DIDPH{index}Q{nonce[:-1]}{flipped}ZH"
        return masked_text[: match.start()] + mutated + masked_text[match.end() :]

    async def test_persistent_corruption_from_the_real_adapter_remains_fail_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            sent = json.loads(httpx.QueryParams(request.content.decode()).get("f.req") or "{}")
            rpc_args = json.loads(sent[0][0][1])
            corrupted = self._corrupt_placeholder_in_text(rpc_args[0][0])
            return httpx.Response(200, text=_build_response_body([corrupted]))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)), sleep=_no_sleep
        )

        async def translate_masked_text(masked_text: str) -> str:
            result = await provider.translate(
                masked_text, source_language="en", target_language="fr"
            )
            return result.translated_text

        with pytest.raises(IntegrityViolation):
            await render_field_text(
                self.UNIT,
                target_language="fr",
                campaign_id=CAMPAIGN_ID,
                guild_id=GUILD_ID,
                template_variable_definitions={},
                glossary_entries=(),
                translate_masked_text=translate_masked_text,
            )

    async def test_recovers_when_only_the_first_real_call_is_corrupted(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            sent = json.loads(httpx.QueryParams(request.content.decode()).get("f.req") or "{}")
            rpc_args = json.loads(sent[0][0][1])
            text = rpc_args[0][0]
            if call_count == 1:
                text = self._corrupt_placeholder_in_text(text)
            return httpx.Response(200, text=_build_response_body([text]))

        provider = GoogleTranslateRpcCampaignTranslationProvider(
            client_factory=lambda: _TrackedClient(httpx.MockTransport(handler)), sleep=_no_sleep
        )

        async def translate_masked_text(masked_text: str) -> str:
            result = await provider.translate(
                masked_text, source_language="en", target_language="fr"
            )
            return result.translated_text

        result = await render_field_text(
            self.UNIT,
            target_language="fr",
            campaign_id=CAMPAIGN_ID,
            guild_id=GUILD_ID,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text=translate_masked_text,
        )
        assert result == "Ping <@123456789012345678> now."
        assert call_count == 2
