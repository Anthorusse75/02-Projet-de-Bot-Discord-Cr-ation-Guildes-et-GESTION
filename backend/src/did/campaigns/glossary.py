"""Glossary application: DO_NOT_TRANSLATE / FORCED_TRANSLATION terms (WP8).

Glossary terms are applied by reusing the parser/protector's PROTECTED node
machinery (``ProtectedKind.GLOSSARY_TERM``) rather than doing a raw string
substitution after translation -- this is a deliberate choice, not an
accident: a post-translation find/replace can land mid-word or split a
grammatically-inflected form the target language produced, corrupting
output. Protecting the *source* term before translation and letting the
existing fail-closed placeholder-integrity check (``protector.py``) validate
the round trip gives glossary terms the exact same safety guarantee as
mentions, URLs and code blocks.

Priority (documented decision, most specific wins, REQ-MSG-014's
"langue/scope/template" dimensions): ``CAMPAIGN`` scope (the "template"
tier -- a campaign's own message content) beats ``GUILD`` scope (a
Guild-wide vocabulary shared by every campaign targeting that Guild) beats
``GLOBAL_USER`` scope; within a scope, a language-specific entry beats a
language-agnostic one; ties broken by longest ``source_term``. Matching is
leftmost-first among non-overlapping spans; at a given start position, the
highest-priority (specificity-sorted) candidate wins.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from did.domain.campaigns import GlossaryBehavior, GlossaryEntry, GlossaryMatchMode, GlossaryScope
from did.messaging.parser import MessageNode, ProtectedKind, ProtectedNode, TextNode


def resolve_applicable_entries(
    entries: Iterable[GlossaryEntry],
    *,
    campaign_id: UUID,
    target_language_code: str,
    guild_id: int | None = None,
) -> list[GlossaryEntry]:
    """Filter to entries usable for this campaign/(optional) Guild/target-
    language triple, most specific first (see module docstring).

    ``guild_id`` should be supplied whenever the delivery has a known
    destination Guild (almost always) so GUILD-scoped entries for that
    Guild are included; omit it only when resolving glossary terms with no
    Guild context yet (e.g. a source-only preview).
    """
    applicable = [
        entry
        for entry in entries
        if (
            (entry.scope_kind is GlossaryScope.CAMPAIGN and entry.campaign_id == campaign_id)
            or (
                entry.scope_kind is GlossaryScope.GUILD
                and guild_id is not None
                and entry.guild_id == guild_id
            )
            or entry.scope_kind is GlossaryScope.GLOBAL_USER
        )
        and entry.target_language_code in (None, target_language_code)
    ]
    return sorted(applicable, key=lambda e: e.specificity(), reverse=True)


def _compile_pattern(entries: Sequence[GlossaryEntry]) -> re.Pattern[str] | None:
    if not entries:
        return None
    alternatives = []
    for index, entry in enumerate(entries):
        escaped = re.escape(entry.source_term)
        if entry.match_mode is GlossaryMatchMode.CASE_INSENSITIVE:
            body = f"(?i:{escaped})"
        else:
            body = escaped
        alternatives.append(f"(?P<e{index}>\\b{body}\\b)")
    return re.compile("|".join(alternatives))


@dataclass(frozen=True, slots=True)
class GlossaryApplication:
    nodes: tuple[MessageNode, ...]
    #: position (index into `nodes`) -> restore value override, for
    #: protector.protect()'s restore_overrides parameter.
    restore_overrides: dict[int, str]
    matched_term_count: int


def apply_glossary_protection(
    nodes: tuple[MessageNode, ...], resolved_entries: Sequence[GlossaryEntry]
) -> GlossaryApplication:
    pattern = _compile_pattern(resolved_entries)
    new_nodes: list[MessageNode] = []
    restore_overrides: dict[int, str] = {}
    matched = 0

    if pattern is None:
        return GlossaryApplication(nodes=nodes, restore_overrides={}, matched_term_count=0)

    for node in nodes:
        if not isinstance(node, TextNode) or not node.text:
            new_nodes.append(node)
            continue
        cursor = 0
        for match in pattern.finditer(node.text):
            start, end = match.span()
            if start < cursor:
                continue  # overlapping with an already-consumed span
            if start > cursor:
                new_nodes.append(TextNode(node.text[cursor:start]))
            group_index = next(i for i, g in enumerate(match.groups()) if g is not None)
            entry = resolved_entries[group_index]
            position = len(new_nodes)
            new_nodes.append(ProtectedNode(kind=ProtectedKind.GLOSSARY_TERM, value=match.group()))
            if entry.behavior is GlossaryBehavior.FORCED_TRANSLATION:
                assert entry.forced_translation is not None
                restore_overrides[position] = entry.forced_translation
            matched += 1
            cursor = end
        if cursor < len(node.text):
            new_nodes.append(TextNode(node.text[cursor:]))

    return GlossaryApplication(
        nodes=tuple(new_nodes), restore_overrides=restore_overrides, matched_term_count=matched
    )


def matched_source_terms(entries: Sequence[GlossaryEntry], text: str) -> tuple[str, ...]:
    """REQ-MSG-022 simulation/preview integration (mission section 11):
    which of ``entries`` (already narrowed to what is applicable via
    :func:`resolve_applicable_entries`) literally appear in ``text`` --
    a preview-time authoring aid so an author can see which of their
    configured glossary terms would actually be protected, not merely
    that terms exist. Checked one entry at a time (never the combined
    :func:`_compile_pattern` used for the real fan-out-time application) so
    the result names every matching entry, not just the first overlapping
    span at each position -- this is a preview list, not a rendering."""
    matched: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        pattern = _compile_pattern([entry])
        if pattern is not None and pattern.search(text) and entry.source_term not in seen:
            matched.append(entry.source_term)
            seen.add(entry.source_term)
    return tuple(matched)
