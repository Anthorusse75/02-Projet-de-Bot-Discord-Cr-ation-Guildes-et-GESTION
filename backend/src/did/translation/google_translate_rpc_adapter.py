"""Real Google Translate Web RPC ("batchexecute") CampaignTranslationProvider
adapter -- the current PRODUCTION transport for Stage09 direct campaign
translation.

Transport history (see ``docs/90_handoffs/STAGE_09_HANDOFF.md`` for the full,
dated evidence trail): the originally selected transport,
``did.translation.googletrans_adapter.GoogletransCampaignTranslationProvider``
(the unofficial ``googletrans`` package's ``/translate_a/single`` endpoint),
was empirically found -- from multiple machines on the product owner's own
network, with the adapter's own fail-open defect already fixed -- to
consistently receive HTTP 429/403 from that specific endpoint. A completely
independent probe of Google's other public, unofficial web endpoint (the one
the Google Translate website itself calls from the browser), the
``batchexecute`` RPC framework, succeeded (HTTP 200, a genuine translation)
from the SAME machine at the SAME time. The problem is therefore specific to
the ``/translate_a/single`` transport, not a generic loss of connectivity --
so DID's production transport is switched to ``batchexecute`` here, while
``googletrans_adapter.py`` is kept only as historical/comparative code (see
its own module docstring) -- it is no longer constructed on any production or
live-qualification path.

**This is still an unofficial, unauthenticated, reverse-engineered private
Google web interface -- not a published/supported API, and not the paid
Google Cloud Translation API.** It can change or start rejecting requests at
any time, exactly like the previous transport did. Every response-parsing
assumption below is isolated to the small set of pure functions in this
module (never scattered through the application) specifically so that if
Google's actual response shape differs from what is assumed here, the fix is
a change to this one module, not a hunt through the codebase -- and so every
one of those assumptions is independently unit-testable without a real
network call (see backend/tests/unit/test_stage09_google_translate_rpc_adapter
.py). Any response that does not match the assumed shape -- wrong HTTP
status, missing RPC block, malformed outer or inner JSON, missing/empty
translated text, unexpected structure at any step -- fails closed with
:class:`~did.domain.translation_provider.TranslationProviderError`. There is
no untranslated-input fallback, no empty-string fallback, and no silent
provider switch: a provider failure here must never become an untranslated
delivery, exactly as required everywhere else in Stage09.

**Wire contract correction (post-merge external audit)**: the first revision
of this module invented its own request query-parameter set
(``source-path``, ``f.sid``, a fabricated ``bl`` version, ``hl``,
``_reqid``) and its own guess at the response shape (translated-sentence
groups directly at ``inner[0]``, detected language at ``inner[1]``).
Neither of those was ever actually verified against the real endpoint --
only the endpoint and RPC id were. An external audit caught this: the
product owner's own working implementation, and a one-call probe from the
SAME machine that gets HTTP 429 through ``googletrans``'s
``/translate_a/single``, use a different, narrower, and *empirically proven*
request contract (fixed ``bl=boq_translate-webserver_20201207.13_p0``, no
``source-path``/``f.sid``/``hl``/``_reqid``, an ``f.req`` envelope whose RPC
argument array has a second element ``[None]``, and a ``Referer`` header) and
a different response shape (translation content at ``parsed[1][0][0]``,
translated parts at ``translation_data[5]``, a spacing flag at
``translation_data[3]``, detected source at ``parsed[2]``) -- returning a
real, verified HTTP 200 translation. This module is now aligned to that
exact proven contract; the invented variant above is not retained anywhere.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from did.domain.translation_provider import (
    TranslationProviderError,
    TranslationResult,
    TranslationTimeoutError,
)
from did.translation.circuit_breaker import CircuitBreaker

#: The public, unauthenticated Google Translate web frontend's RPC endpoint
#: -- the same one https://translate.google.com itself calls from the
#: browser. Distinct from, and empirically more available than, the
#: `/translate_a/single` endpoint `googletrans` uses (see module docstring).
BATCHEXECUTE_URL = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"

#: The specific batchexecute RPC id that performs a text translation.
#: Reverse-engineered/community-documented, not published by Google.
RPC_ID = "MkEWBc"

_XSSI_PREFIX = ")]}'"

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: The Referer the real translate.google.com frontend sends for this RPC --
#: part of the product owner's own proven, same-machine HTTP-200 request
#: contract (see module docstring's "Wire contract correction" note).
_REFERER = "https://translate.google.com/"


def _build_query_params() -> dict[str, str]:
    """Query parameters for the batchexecute POST -- exactly the parameter
    set from the product owner's own proven, same-machine probe (HTTP 200,
    a genuine translation, from the exact network/IP that gets HTTP 429
    through ``googletrans``'s ``/translate_a/single``). Deliberately does
    NOT include ``source-path``, ``f.sid``, ``hl``, or ``_reqid`` -- an
    earlier revision of this module invented those without ever having
    empirical proof any of them were required or even accepted; see the
    module docstring's "Wire contract correction" note. The static
    ``bl=boq_translate-webserver_20201207.13_p0`` value is likewise the
    exact one from that proven probe, not a value guessed/derived here."""
    return {
        "rpcids": RPC_ID,
        "bl": "boq_translate-webserver_20201207.13_p0",
        "soc-app": "1",
        "soc-platform": "1",
        "soc-device": "1",
        "rt": "c",
    }


def build_form_data(text: str, source_language: str, target_language: str) -> dict[str, str]:
    """The batchexecute ``f.req`` form field -- exactly the double-encoded
    envelope shape from the product owner's own proven, same-machine probe
    (see module docstring). The RPC argument array's second element,
    ``[None]``, is part of that proven shape and is preserved verbatim even
    though its purpose is not independently understood from this sandbox --
    this is not a place to "simplify" away something empirically observed
    to work. ``ensure_ascii=False`` and compact ``(",", ":")`` separators
    match the proven contract's own JSON encoding exactly."""
    rpc_args = json.dumps(
        [[text, source_language, target_language, True], [None]],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    envelope = [[[RPC_ID, rpc_args, None, "generic"]]]
    request = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
    return {"f.req": request}


def _strip_xssi_prefix(raw_text: str) -> str:
    """batchexecute responses are prefixed with Google's standard XSSI
    protection line (``)]}'``) to stop the response being parsed as
    executable JavaScript if fetched via a ``<script>`` tag -- never
    meaningful payload, always stripped before any JSON parsing."""
    text = raw_text.lstrip()
    if text.startswith(_XSSI_PREFIX):
        return text[len(_XSSI_PREFIX) :]
    return text


def find_rpc_entry(response_text: str, *, rpc_id: str = RPC_ID) -> list[Any]:
    """Locates and returns the one ``["wrb.fr", rpc_id, <payload>, ...]``
    entry for ``rpc_id`` inside a batchexecute response body.

    batchexecute's real wire format prefixes each JSON chunk with its own
    byte-length on the preceding line -- this deliberately does NOT depend
    on parsing that length-prefix protocol precisely (a subtle off-by-one
    there would be a much worse failure mode than simply trying to parse
    every non-empty line as JSON and pattern-matching the ones that look
    like a "wrb.fr" RPC response entry, which is robust to that framing
    detail entirely). Raises :class:`TranslationProviderError` -- never
    returns a best-guess fallback -- if no matching entry is found anywhere
    in the response.
    """
    body = _strip_xssi_prefix(response_text)
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("["):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        for entry in parsed:
            if (
                isinstance(entry, list)
                and len(entry) >= 3
                and entry[0] == "wrb.fr"
                and entry[1] == rpc_id
            ):
                return entry
    raise TranslationProviderError(
        f"malformed batchexecute response: no {rpc_id!r} RPC block found in the response body"
    )


def parse_inner_payload(entry: list[Any]) -> Any:
    """The RPC entry's 3rd element (index 2) is itself a JSON-encoded
    string -- batchexecute's double-encoding convention -- parsed here into
    the actual translation payload. Fails closed on anything that is not a
    valid JSON string at that position."""
    if len(entry) < 3:
        raise TranslationProviderError(
            "malformed batchexecute response: RPC entry has too few elements"
        )
    payload_field = entry[2]
    if not isinstance(payload_field, str):
        raise TranslationProviderError(
            "malformed batchexecute response: RPC payload is not a JSON-encoded string"
        )
    try:
        return json.loads(payload_field)
    except json.JSONDecodeError as exc:
        raise TranslationProviderError(
            f"malformed batchexecute response: inner RPC payload is not valid JSON: {exc}"
        ) from exc


def _extract_translation_data(inner: Any) -> list[Any]:
    """Locates the proven real response's actual translation payload at
    ``inner[1][0][0]``: ``inner[1]`` is the top-level translation-result
    list, ``[0]`` its (single, Stage09 never batches multiple segments into
    one RPC call) segment entry, and that entry's own ``[0]`` is the
    ``translation_data`` list carrying both the translated parts (index 5)
    and the inter-part spacing flag (index 3). Fails closed with a specific
    message at each positional/type boundary -- never a bare index into an
    unvalidated value, since Python strings are themselves subscriptable
    and would otherwise let a malformed string-shaped value silently
    "succeed" instead of failing closed."""
    try:
        level1 = inner[1]
    except (TypeError, IndexError, KeyError) as exc:
        raise TranslationProviderError(
            "malformed batchexecute response: missing top-level translation result (index 1)"
        ) from exc
    if not isinstance(level1, list) or not level1:
        raise TranslationProviderError(
            "malformed batchexecute response: translation result (index 1) is not a non-empty list"
        )
    segment_entry = level1[0]
    if not isinstance(segment_entry, list) or not segment_entry:
        raise TranslationProviderError(
            "malformed batchexecute response: translation segment entry ([1][0]) "
            "is not a non-empty list"
        )
    translation_data = segment_entry[0]
    if not isinstance(translation_data, list):
        raise TranslationProviderError(
            "malformed batchexecute response: translation data ([1][0][0]) is not a list"
        )
    return translation_data


def extract_translated_text(inner: Any) -> str:
    """Reconstructs the translated text from the proven real response
    shape: ``translation_data[5]`` is the list of translated parts (each a
    ``[text, ...]``-shaped list), and ``translation_data[3]`` is a spacing
    flag -- truthy means parts are joined with a single space, falsy means
    they are concatenated directly. Fails closed (never returns an empty or
    partial-looking string silently, and never silently drops a malformed
    part) on any structural surprise or on a translated result that is
    empty. Deliberately stricter here than the reference implementation
    this was aligned to, which silently filters out malformed parts instead
    of failing -- Stage09's own fail-closed requirement takes precedence:
    a malformed part is treated as a malformed response, not as a part to
    skip."""
    translation_data = _extract_translation_data(inner)
    # Checked in index order (3 before 5) so both boundaries are reachable:
    # any translation_data long enough to have index 5 necessarily already
    # has index 3, so checking 5 first would make a "missing index 3"
    # failure unreachable in practice.
    try:
        spacing_flag = translation_data[3]
    except IndexError as exc:
        raise TranslationProviderError(
            "malformed batchexecute response: translation data is missing "
            "the spacing flag (index 3)"
        ) from exc
    use_spacing = bool(spacing_flag)
    try:
        parts = translation_data[5]
    except IndexError as exc:
        raise TranslationProviderError(
            "malformed batchexecute response: translation data is missing "
            "translated parts (index 5)"
        ) from exc
    if not isinstance(parts, list) or not parts:
        raise TranslationProviderError(
            "malformed batchexecute response: no translated parts present (index 5)"
        )

    translated_parts: list[str] = []
    for part in parts:
        if not isinstance(part, list) or not part or part[0] is None:
            raise TranslationProviderError(
                "malformed batchexecute response: malformed translated part"
            )
        candidate = part[0]
        if not isinstance(candidate, str):
            raise TranslationProviderError(
                "malformed batchexecute response: translated part is not text"
            )
        translated_parts.append(candidate)

    separator = " " if use_spacing else ""
    translated = separator.join(translated_parts).strip()
    if not translated:
        raise TranslationProviderError("malformed batchexecute response: translated text is empty")
    return translated


def extract_detected_source_language(inner: Any) -> str | None:
    """Best-effort only -- unlike the translated text itself, a missing or
    unexpected detected-source-language is not a failure (the caller
    already knows and passed the source language explicitly); this returns
    ``None`` rather than raising when it cannot be found. Located at
    ``inner[2]`` in the proven real response shape (not ``inner[1]``, which
    is the translation-result payload itself, see
    :func:`_extract_translation_data`)."""
    try:
        detected = inner[2]
    except (TypeError, IndexError, KeyError):
        return None
    if isinstance(detected, str) and detected:
        return detected
    return None


def parse_batchexecute_response(response_text: str, *, rpc_id: str = RPC_ID) -> TranslationResult:
    """Composes the full parsing pipeline (find RPC entry -> parse inner
    JSON -> extract translated text / detected language) into the single
    entrypoint the adapter below calls -- source/target language are filled
    in by the caller, since the response payload alone does not confirm
    which languages were requested."""
    entry = find_rpc_entry(response_text, rpc_id=rpc_id)
    inner = parse_inner_payload(entry)
    translated_text = extract_translated_text(inner)
    detected_source_language = extract_detected_source_language(inner)
    return TranslationResult(
        source_language="",  # overwritten by the adapter with the real requested value
        target_language="",  # overwritten by the adapter with the real requested value
        translated_text=translated_text,
        detected_source_language=detected_source_language,
    )


def _default_client_factory() -> httpx.AsyncClient:
    """The real, production ``httpx.AsyncClient`` construction -- plain
    HTTP/1.1 deliberately: this adapter makes a single POST per call, so
    HTTP/2's main benefit (multiplexed connection reuse) does not apply,
    and enabling it would depend on the ``h2`` package being a genuine,
    intentional dependency rather than one that happens to be present only
    because ``googletrans`` (kept for historical/comparative reasons, see
    ``googletrans_adapter.py``) transitively pulls in ``httpx[http2]``. If
    ``googletrans`` is ever removed entirely, this adapter's own dependency
    footprint must not have silently relied on that transitive package. The
    ``Referer`` header is part of the product owner's own proven request
    contract (see module docstring); the ``User-Agent`` value itself is a
    plausible desktop browser string, not independently byte-for-byte
    verified from that probe -- the empirically load-bearing pieces of the
    request are the endpoint, RPC id, query parameters, ``f.req`` envelope
    shape, and ``Referer``, all matched exactly."""
    return httpx.AsyncClient(headers={"User-Agent": _DEFAULT_USER_AGENT, "Referer": _REFERER})


class GoogleTranslateRpcCampaignTranslationProvider:
    """Structurally implements
    :class:`~did.domain.translation_provider.CampaignTranslationProvider`.

    The current PRODUCTION translation transport -- see module docstring for
    why this replaced ``GoogletransCampaignTranslationProvider``. Every
    resilience property that adapter had is retained here unchanged:
    positive timeout validation, ``max_attempts >= 1``, bounded retry with
    backoff, and circuit-breaker wrapping -- a corrupted or unreachable
    provider must fail closed, never return a silently wrong or partial
    translation.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        circuit_breaker: CircuitBreaker | None = None,
        client_factory: Callable[[], httpx.AsyncClient] = _default_client_factory,
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
        self._client_factory = client_factory
        self._sleep = sleep

    async def translate(
        self, text: str, *, source_language: str, target_language: str
    ) -> TranslationResult:
        async def attempt_all() -> TranslationResult:
            last_error: Exception | None = None
            for attempt in range(1, self._max_attempts + 1):
                try:
                    return await asyncio.wait_for(
                        self._call_rpc(text, source_language, target_language),
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

    async def _call_rpc(
        self, text: str, source_language: str, target_language: str
    ) -> TranslationResult:
        # A fresh client per real attempt, always closed here -- explicit,
        # deterministic lifecycle ownership (never a shared/long-lived
        # client that could leak across concurrent campaign fan-outs or
        # outlive this call). Injectable via `client_factory` for tests
        # that need to assert on close() being called, or to avoid any
        # real network/socket setup at all.
        client = self._client_factory()
        try:
            response = await client.post(
                BATCHEXECUTE_URL,
                params=_build_query_params(),
                data=build_form_data(text, source_language, target_language),
            )
        finally:
            await client.aclose()

        if not 200 <= response.status_code < 300:
            raise TranslationProviderError(
                f"Google Translate RPC transport failure: HTTP {response.status_code} "
                f"from {BATCHEXECUTE_URL}"
            )

        result = parse_batchexecute_response(response.text)
        return TranslationResult(
            source_language=source_language,
            target_language=target_language,
            translated_text=result.translated_text,
            detected_source_language=result.detected_source_language,
        )
