"""Discord-safe message parser (WP7).

Splits raw Discord message content into an ordered sequence of ``TextNode``
(free linguistic text, safe to send to translation) and ``ProtectedNode``
(technical tokens whose Discord meaning would be destroyed by translation).

Design decision (documented in ``docs/90_handoffs/STAGE_09_HANDOFF.md``):
Markdown *emphasis* delimiters (``**bold**``, ``_italic_``, ``~~strike~~``,
``||spoiler||``, block quotes) are treated as ordinary text, not as
``ProtectedNode`` boundaries. Protecting each delimiter individually would
shred sentences into single-character fragments and destroy the linguistic
context translation quality depends on -- the opposite of the goal ("the
goal is NOT to split every TEXT fragment independently"). Code
blocks/inline code, which *would* be corrupted by translation touching their
contents, are protected as whole atomic units instead. The post-translation
validator (``protector.py``) additionally checks that emphasis-marker counts
stay balanced as a structural (not fingerprint) integrity signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ProtectedKind(StrEnum):
    URL = "URL"
    USER_MENTION = "USER_MENTION"
    ROLE_MENTION = "ROLE_MENTION"
    CHANNEL_MENTION = "CHANNEL_MENTION"
    EVERYONE_HERE = "EVERYONE_HERE"
    TIMESTAMP = "TIMESTAMP"
    CUSTOM_EMOJI = "CUSTOM_EMOJI"
    CODE_BLOCK = "CODE_BLOCK"
    INLINE_CODE = "INLINE_CODE"
    SLASH_COMMAND = "SLASH_COMMAND"
    TEMPLATE_VARIABLE = "TEMPLATE_VARIABLE"
    GLOSSARY_TERM = "GLOSSARY_TERM"


@dataclass(frozen=True, slots=True)
class TextNode:
    text: str


@dataclass(frozen=True, slots=True)
class ProtectedNode:
    kind: ProtectedKind
    value: str


MessageNode = TextNode | ProtectedNode

# Order matters: this is alternation priority, not just precedence -- code
# spans are matched before anything that could appear inside them, and the
# distinct leading characters of the other groups (`<`, `@`, `{{`, `http`)
# keep the remaining alternatives effectively unambiguous.
_SNOWFLAKE = r"\d{15,20}"
_TOKEN_PATTERN = re.compile(
    r"(?P<CODE_BLOCK>```.*?```)"
    r"|(?P<INLINE_CODE>``.+?``|`[^`\n]+`)"
    r"|(?P<USER_MENTION><@!?" + _SNOWFLAKE + r">)"
    r"|(?P<ROLE_MENTION><@&" + _SNOWFLAKE + r">)"
    r"|(?P<CHANNEL_MENTION><#" + _SNOWFLAKE + r">)"
    r"|(?P<CUSTOM_EMOJI><a?:\w{2,32}:" + _SNOWFLAKE + r">)"
    r"|(?P<TIMESTAMP><t:-?\d{1,17}(?::[tTdDfFR])?>)"
    r"|(?P<SLASH_COMMAND></[\w-][\w -]{0,98}:" + _SNOWFLAKE + r">)"
    r"|(?P<EVERYONE_HERE>@(?:everyone|here))"
    r"|(?P<TEMPLATE_VARIABLE>\{\{[a-zA-Z_][a-zA-Z0-9_]*\}\})"
    r"|(?P<URL>https?://[^\s<>\[\]()\"']+)",
    re.DOTALL,
)

_EMPHASIS_MARKERS = ("**", "__", "~~", "||")

# REQ-MSG-025 (external review, remediation): the URL alternative has no
# closing delimiter of its own (unlike `<@...>`, `` `...` ``, `{{...}}`),
# so it is the only ProtectedKind vulnerable to a translation engine gluing
# adjacent punctuation directly onto it with no separating whitespace --
# observed live: googletrans regularly drops the space before a
# sentence-final "." (or ",", ";", ":", "!", "?") when a URL placeholder
# ends up as the last token before that punctuation in the target word
# order. Without this trim, the greedy URL character class (which must
# legitimately include "." for domains/paths) would silently absorb that
# glued punctuation into the URL value on reparse, producing a value that
# no longer matches what was originally protected -- flagged as a
# hallucinated/invented protected token by
# ``protector.validate_reparsed_structure`` and correctly failing closed,
# but avoidable since the punctuation was never part of the URL.
#
# This mirrors the standard "trailing punctuation trim" heuristic used by
# production URL auto-linkers (GitHub, Slack, Twitter): strip *trailing*
# sentence punctuation one character at a time, never touching characters
# that are part of the URL's own required syntax (scheme, host, path). It
# is applied identically at initial parse time and at reparse time, so the
# same input always yields the same protected value regardless of which
# side of a translation round trip it is parsed on.
_URL_TRAILING_PUNCTUATION = ".,;:!?"
_URL_MIN_LENGTH_AFTER_TRIM = len("https://x")


def _trim_url_trailing_punctuation(value: str) -> str:
    end = len(value)
    while end > _URL_MIN_LENGTH_AFTER_TRIM and value[end - 1] in _URL_TRAILING_PUNCTUATION:
        end -= 1
    return value[:end]


def parse(content: str) -> tuple[MessageNode, ...]:
    """Tokenize raw Discord message content into TEXT/PROTECTED nodes."""
    nodes: list[MessageNode] = []
    cursor = 0
    for match in _TOKEN_PATTERN.finditer(content):
        start, end = match.span()
        assert match.lastgroup is not None
        kind = ProtectedKind(match.lastgroup)
        value = match.group()
        if kind is ProtectedKind.URL:
            trimmed = _trim_url_trailing_punctuation(value)
            if len(trimmed) < len(value):
                end -= len(value) - len(trimmed)
                value = trimmed
        if start > cursor:
            nodes.append(TextNode(content[cursor:start]))
        nodes.append(ProtectedNode(kind=kind, value=value))
        cursor = end
    if cursor < len(content):
        nodes.append(TextNode(content[cursor:]))
    return tuple(nodes)


def render(nodes: tuple[MessageNode, ...]) -> str:
    """Inverse of :func:`parse` -- concatenate node values back to raw text."""
    parts: list[str] = []
    for node in nodes:
        parts.append(node.text if isinstance(node, TextNode) else node.value)
    return "".join(parts)


def emphasis_marker_counts(content: str) -> dict[str, int]:
    """Count Markdown emphasis delimiters for the structural balance check.

    Single ``*`` and ``_`` are intentionally excluded: they are ambiguous
    with ordinary punctuation/apostrophes across languages and are not a
    reliable structural signal.
    """
    return {marker: content.count(marker) for marker in _EMPHASIS_MARKERS}
