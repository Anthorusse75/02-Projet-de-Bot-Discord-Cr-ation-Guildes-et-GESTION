"""REQ-MSG-018: explicit semantic typing for ``{{variable}}`` template
variables, resolved before the parse/protect/translate/restore pipeline.

``did.messaging.parser`` always recognizes ``{{var}}`` syntax as one opaque
``TEMPLATE_VARIABLE`` protected token -- structurally safe (never
mistranslated), but semantically flat: every variable was treated
identically regardless of what its value actually means. This module adds
the missing distinction, four explicit types:

* ``TRANSLATABLE_TEXT`` -- the variable's resolved value IS linguistic
  content and should participate in translation like any surrounding
  prose (e.g. a user-supplied campaign subtitle). Its value is inlined
  directly into the plain-text stream *before* protection -- it is never
  protected, and by the time ``protector.protect`` runs it is
  indistinguishable from text the author typed directly.
* ``NON_TRANSLATABLE`` -- the variable's value is fixed, technical-ish
  prose that must survive translation byte-identical regardless of target
  language (e.g. a legal disclaimer string, a fixed product name the
  author does not want re-translated). Protected; restores to the same
  value for every target language.
* ``LOCALIZED_VALUE`` -- the caller supplies an already-localized value per
  target language (e.g. a currency-formatted price, a pre-translated
  slogan chosen by the campaign author, not by the automatic translator).
  Protected so the translation engine never touches it; the *specific*
  value substituted depends on the current target language, resolved from
  the definition's ``values_by_language`` -- never invented or interpolated
  by this module.
* ``PROTECTED`` -- an opaque technical token (an id, a code, a URL
  fragment) that happens to be authored through template-variable syntax
  rather than being a native protected token kind. Behaves like
  ``NON_TRANSLATABLE`` in the pipeline (protected, same value for every
  language) but is kept as a distinct declared type since it represents a
  different authoring intent and must never be offered as "safe to
  translate" in any UI/preview surface built on top of this module.

A variable name present in the source text but absent from ``definitions``
is treated as ``NON_TRANSLATABLE`` by default (fail-safe: an undeclared
variable is never silently sent to translation) -- callers that want strict
validation should check :func:`undeclared_variable_names` themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from did.messaging.message_model import MessageModel
from did.messaging.parser import MessageNode, ProtectedKind, ProtectedNode, TextNode, parse
from did.messaging.translation_policy import extract_translatable_units

_TEMPLATE_VARIABLE_NAME = "TEMPLATE_VARIABLE"


class TemplateVariableType(StrEnum):
    TRANSLATABLE_TEXT = "TRANSLATABLE_TEXT"
    NON_TRANSLATABLE = "NON_TRANSLATABLE"
    LOCALIZED_VALUE = "LOCALIZED_VALUE"
    PROTECTED = "PROTECTED"


@dataclass(frozen=True, slots=True)
class TemplateVariableDefinition:
    name: str
    variable_type: TemplateVariableType
    #: Used by TRANSLATABLE_TEXT/NON_TRANSLATABLE/PROTECTED -- the same
    #: value regardless of target language. Must be None for LOCALIZED_VALUE.
    value: str | None = None
    #: Used only by LOCALIZED_VALUE -- one already-localized value per
    #: target language code. Must be None/empty for every other type.
    values_by_language: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("template variable name must not be blank")
        if self.variable_type is TemplateVariableType.LOCALIZED_VALUE:
            if not self.values_by_language:
                raise ValueError("LOCALIZED_VALUE requires a non-empty values_by_language map")
            if self.value is not None:
                raise ValueError("LOCALIZED_VALUE must not also carry a single `value`")
        else:
            if self.value is None:
                raise ValueError(f"{self.variable_type} requires a `value`")
            if self.values_by_language:
                raise ValueError(f"{self.variable_type} must not carry values_by_language")

    def resolve(self, *, target_language: str) -> str:
        if self.variable_type is TemplateVariableType.LOCALIZED_VALUE:
            assert self.values_by_language is not None
            try:
                return self.values_by_language[target_language]
            except KeyError as exc:
                raise MissingLocalizedValue(self.name, target_language) from exc
        assert self.value is not None
        return self.value


class MissingLocalizedValue(ValueError):
    def __init__(self, variable_name: str, target_language: str) -> None:
        super().__init__(
            f"template variable {variable_name!r} has no LOCALIZED_VALUE "
            f"for target language {target_language!r}"
        )
        self.variable_name = variable_name
        self.target_language = target_language


def _variable_name(raw: str) -> str:
    # raw is the full "{{name}}" token text.
    return raw[2:-2]


def undeclared_variable_names(nodes: tuple[MessageNode, ...]) -> frozenset[str]:
    """Names referenced in the text as ``{{var}}`` but missing from a
    definitions map -- callers may use this to reject a campaign at
    authoring time rather than rely on this module's fail-safe default."""
    return frozenset(
        _variable_name(node.value)
        for node in nodes
        if isinstance(node, ProtectedNode) and node.kind is ProtectedKind.TEMPLATE_VARIABLE
    )


def undeclared_template_variable_names_in_message_model(
    model: MessageModel, definitions: dict[str, TemplateVariableDefinition]
) -> frozenset[str]:
    """REQ-MSG-018 simulation/preview integration (mission section 10):
    every ``{{variable}}`` name referenced anywhere in ``model``'s
    translatable text (``did.messaging.translation_policy
    .extract_translatable_units`` -- never a raw JSON walk, and never a
    technical field like embed url/color or button custom_id/url) that has
    no declared definition. An undeclared variable still renders safely
    (fails closed to NON_TRANSLATABLE, see the module docstring) -- this is
    purely a preview-time authoring aid, never a hard block."""
    referenced: set[str] = set()
    for unit in extract_translatable_units(model):
        referenced |= undeclared_variable_names(parse(unit.text))
    return frozenset(referenced - set(definitions.keys()))


def resolve_template_variables(
    nodes: tuple[MessageNode, ...],
    definitions: dict[str, TemplateVariableDefinition],
    *,
    target_language: str,
) -> tuple[tuple[MessageNode, ...], dict[int, str]]:
    """Resolve every ``{{var}}`` node in ``nodes`` according to its declared
    type, returning (a) a new node sequence -- TRANSLATABLE_TEXT variables
    fully inlined as plain text, every other kind of node (including
    remaining protected variables) unchanged in shape -- and (b) a
    ``restore_overrides`` map (by position in the *returned* node sequence)
    ready to pass straight to ``protector.protect(new_nodes,
    restore_overrides=...)``. Feed the returned node sequence, not the
    original ``nodes``, to ``protector.validate_full_pipeline`` as its
    ``original_nodes`` argument -- it is the true post-resolution source of
    truth for structural/reparse comparison.

    An undeclared variable name defaults to NON_TRANSLATABLE, echoing its
    own literal ``{{name}}`` source text back (fail-safe: never guessed,
    never sent to translation) -- see :func:`undeclared_variable_names` to
    detect and reject these at authoring time instead.
    """
    new_nodes: list[MessageNode] = []
    restore_overrides: dict[int, str] = {}
    pending_text: list[str] = []

    def _flush_text() -> None:
        if pending_text:
            new_nodes.append(TextNode("".join(pending_text)))
            pending_text.clear()

    for node in nodes:
        if isinstance(node, TextNode):
            pending_text.append(node.text)
            continue
        if node.kind is not ProtectedKind.TEMPLATE_VARIABLE:
            _flush_text()
            new_nodes.append(node)
            continue

        name = _variable_name(node.value)
        definition = definitions.get(name)
        if definition is None:
            resolved_value = node.value  # fail-safe: echo the raw {{name}} syntax back
            variable_type = TemplateVariableType.NON_TRANSLATABLE
        else:
            resolved_value = definition.resolve(target_language=target_language)
            variable_type = definition.variable_type

        if variable_type is TemplateVariableType.TRANSLATABLE_TEXT:
            pending_text.append(resolved_value)
            continue

        _flush_text()
        position = len(new_nodes)
        new_nodes.append(node)
        restore_overrides[position] = resolved_value

    _flush_text()
    return tuple(new_nodes), restore_overrides
