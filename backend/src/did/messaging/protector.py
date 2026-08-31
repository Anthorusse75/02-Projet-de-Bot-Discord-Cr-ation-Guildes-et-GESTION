"""Placeholder protection/restoration/validation for Discord-safe translation.

REQ-MSG-010..013 / 023 / 025: technical tokens are replaced with
collision-resistant placeholders before the masked text is sent to any
translation engine, and restoration accepts only exact placeholder set
integrity. Any missing, duplicated or invented placeholder in the translated
text FAILS CLOSED -- the caller must not publish that localized variant.

Order is recorded in each fingerprint for diagnostics, but is *not* a hard
integrity gate: legitimate translation reorders words for target-language
grammar (e.g. German verb-final clauses, French post-posed adjectives), and
a placeholder standing in for an inline token moves with its clause. See the
module docstring in ``parser.py`` and ``docs/90_handoffs/STAGE_09_HANDOFF.md``
for the full reasoning. The exact-multiset check below (no missing, no
duplicate, no unknown placeholder) is what "order... where order is
meaningful" degrades to for this content type; it is still a hard fail-closed
gate, just not on relative position.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

from did.messaging.parser import MessageNode, ProtectedKind, ProtectedNode, TextNode
from did.messaging.parser import parse as parse_message

_PLACEHOLDER_PATTERN = re.compile(r"DIDPH[0-9]{4}Q[0-9A-F]{8}ZH")


def _make_placeholder(index: int) -> str:
    nonce = secrets.token_hex(4).upper()
    return f"DIDPH{index:04d}Q{nonce}ZH"


@dataclass(frozen=True, slots=True)
class PlaceholderFingerprint:
    placeholder: str
    kind: ProtectedKind
    order_index: int
    value_sha256: str
    restore_value: str


@dataclass(frozen=True, slots=True)
class ProtectionResult:
    masked_text: str
    fingerprints: tuple[PlaceholderFingerprint, ...]

    def restore_map(self) -> dict[str, str]:
        return {fp.placeholder: fp.restore_value for fp in self.fingerprints}


class IntegrityViolation(ValueError):
    """Raised when translated output fails placeholder/structural validation."""


def protect(
    nodes: tuple[MessageNode, ...],
    *,
    restore_overrides: dict[int, str] | None = None,
) -> ProtectionResult:
    """Replace PROTECTED nodes with placeholders; TEXT nodes pass through.

    ``restore_overrides`` maps a node index (position in ``nodes``) to a
    replacement restore value -- used by the glossary FORCED_TRANSLATION
    behavior (WP8), which protects a source term but restores a *different*
    string than the original value.
    """
    overrides = restore_overrides or {}
    parts: list[str] = []
    fingerprints: list[PlaceholderFingerprint] = []
    order_index = 0
    for position, node in enumerate(nodes):
        if isinstance(node, TextNode):
            parts.append(node.text)
            continue
        placeholder = _make_placeholder(order_index)
        restore_value = overrides.get(position, node.value)
        fingerprints.append(
            PlaceholderFingerprint(
                placeholder=placeholder,
                kind=node.kind,
                order_index=order_index,
                value_sha256=hashlib.sha256(node.value.encode("utf-8")).hexdigest(),
                restore_value=restore_value,
            )
        )
        parts.append(placeholder)
        order_index += 1
    return ProtectionResult(masked_text="".join(parts), fingerprints=tuple(fingerprints))


def validate_and_restore(
    translated_text: str,
    protection: ProtectionResult,
    *,
    foreign_placeholders: frozenset[str] = frozenset(),
) -> str:
    """Verify exact placeholder-set integrity, then restore original tokens.

    Raises :class:`IntegrityViolation` (fail closed) if any expected
    placeholder is missing, any placeholder is duplicated, or the text
    contains a placeholder-shaped token that was never issued (invented).

    ``foreign_placeholders`` (WP12, ``did.campaigns.rendering``'s layered
    template-variable/glossary composition): placeholder tokens that
    legitimately belong to a DIFFERENT, already-completed or still-pending
    ``protect()``/``validate_and_restore`` round trip layered around this
    one -- e.g. an outer layer's placeholder sitting, as opaque literal
    text, inside what this layer treats as ordinary TEXT content. They are
    excluded entirely from this call's missing/duplicated/invented checks
    (that layer's own ``validate_and_restore`` call is what verifies them),
    but are never altered by the restore step below either, since they are
    not in ``expected`` and therefore never matched by the ``replace()``
    loop -- they simply pass through untouched for the outer layer to
    resolve.
    """
    expected = {fp.placeholder: fp for fp in protection.fingerprints}
    found = _PLACEHOLDER_PATTERN.findall(translated_text)

    found_counts: dict[str, int] = {}
    for token in found:
        if token in foreign_placeholders:
            continue
        found_counts[token] = found_counts.get(token, 0) + 1

    unknown = sorted(set(found_counts) - set(expected))
    if unknown:
        raise IntegrityViolation(f"translation invented unknown placeholder token(s): {unknown}")

    missing = sorted(set(expected) - set(found_counts))
    if missing:
        raise IntegrityViolation(f"translation dropped protected placeholder(s): {missing}")

    duplicated = sorted(token for token, count in found_counts.items() if count > 1)
    if duplicated:
        raise IntegrityViolation(f"translation duplicated protected placeholder(s): {duplicated}")

    restored = translated_text
    for placeholder, fingerprint in expected.items():
        restored = restored.replace(placeholder, fingerprint.restore_value)
    return restored


def validate_structural_balance(source_text: str, restored_text: str) -> None:
    """Best-effort structural check: Markdown emphasis marker counts survived.

    This is a *signal*, recorded/enforced separately from placeholder
    integrity, since emphasis markers are ordinary text characters as far as
    the protector is concerned (see ``parser.py`` docstring).
    """
    from did.messaging.parser import emphasis_marker_counts

    before = emphasis_marker_counts(source_text)
    after = emphasis_marker_counts(restored_text)
    unbalanced = {
        marker: (before[marker], after[marker])
        for marker in before
        if before[marker] != after[marker]
    }
    if unbalanced:
        raise IntegrityViolation(f"markdown emphasis marker counts changed: {unbalanced}")


def validate_reparsed_structure(
    original_nodes: tuple[MessageNode, ...], restored_text: str
) -> None:
    """Reparse the fully-restored text and confirm it introduces no
    protected-token-shaped content that was not present in the original
    source.

    This is a distinct, independent check from placeholder-set validation:
    that check proves every *placeholder* survived intact; this one proves
    translation did not hallucinate a brand-new mention/URL/timestamp/etc
    into what used to be plain TEXT (e.g. a translation engine emitting
    literal ``<@...>``-shaped text it invented). ``AllowedMentionsCompiler``
    already defaults every delivery to zero mentions regardless, so this is
    defense-in-depth, not the primary mention-safety gate.
    """
    original_values = {n.value for n in original_nodes if isinstance(n, ProtectedNode)}
    reparsed = parse_message(restored_text)
    reparsed_values = {n.value for n in reparsed if isinstance(n, ProtectedNode)}
    invented = sorted(reparsed_values - original_values)
    if invented:
        raise IntegrityViolation(
            f"restored text contains protected-looking content not present "
            f"in the original source (possible hallucinated token): {invented}"
        )


def validate_full_pipeline(
    original_nodes: tuple[MessageNode, ...],
    translated_text: str,
    protection: ProtectionResult,
    *,
    foreign_placeholders: frozenset[str] = frozenset(),
) -> str:
    """The single production-grade validator: placeholder-set integrity +
    restoration, reparse-and-compare against the original source, and
    Markdown structural balance -- all fail-closed. Every caller (the
    delivery pipeline AND the WP10 benchmark) must use this, not just
    :func:`validate_and_restore` alone, so the benchmark measures the same
    guarantee production actually enforces.

    ``foreign_placeholders`` -- see :func:`validate_and_restore`; used only
    by ``did.campaigns.rendering``'s layered template-variable/glossary
    composition, where an outer layer's own placeholder tokens legitimately
    pass through this (inner) layer's text untouched.
    """
    restored = validate_and_restore(
        translated_text, protection, foreign_placeholders=foreign_placeholders
    )
    validate_reparsed_structure(original_nodes, restored)
    original_text = "".join(n.text if isinstance(n, TextNode) else n.value for n in original_nodes)
    validate_structural_balance(original_text, restored)
    return restored
