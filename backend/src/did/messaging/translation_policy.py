"""REQ-MSG-013: explicit, typed field-by-field MessageModel translation policy.

Translation must operate through named, typed paths into a
:class:`~did.messaging.message_model.MessageModel` -- never by walking
arbitrary JSON and translating every string it finds. This module is the
single source of truth for which ``MessageModel`` fields are linguistic
content (and therefore eligible for the parse/protect/translate/restore
pipeline in ``did.messaging.parser``/``did.messaging.protector``) and which
are technical Discord fields that must always be carried through byte-
identical to the source.

Translatable (each becomes one independent :class:`TranslationUnit`, run
through the same parser/protector/glossary/validator pipeline as plain
message content -- a URL or mention inside an embed description is still
protected exactly like one in the top-level content):

* message content
* embed title, description, footer text, author name
* embed field name and value (each field independently)
* button label

Explicitly NON-translatable, always copied through unchanged, never handed
to a translation engine at all:

* embed url, embed color
* button custom_id, button url, button style
* action row / component structure itself (row count, button count/order)
* the campaign's own technical identifiers (ids, keys, kinds) -- this
  module never even sees those; it operates purely on a ``MessageModel``
  value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from did.messaging.message_model import ComponentActionRow, Embed, EmbedField, MessageModel


class TranslatableFieldKind(StrEnum):
    CONTENT = "CONTENT"
    EMBED_TITLE = "EMBED_TITLE"
    EMBED_DESCRIPTION = "EMBED_DESCRIPTION"
    EMBED_FOOTER_TEXT = "EMBED_FOOTER_TEXT"
    EMBED_AUTHOR_NAME = "EMBED_AUTHOR_NAME"
    EMBED_FIELD_NAME = "EMBED_FIELD_NAME"
    EMBED_FIELD_VALUE = "EMBED_FIELD_VALUE"
    BUTTON_LABEL = "BUTTON_LABEL"


@dataclass(frozen=True, slots=True)
class FieldPath:
    """Identifies exactly one translatable string inside a MessageModel.
    Never constructed from a JSON walk -- always emitted by
    :func:`extract_translatable_units` from the model's own typed structure."""

    kind: TranslatableFieldKind
    embed_index: int | None = None
    field_index: int | None = None
    action_row_index: int | None = None
    button_index: int | None = None


@dataclass(frozen=True, slots=True)
class TranslationUnit:
    path: FieldPath
    text: str


def extract_translatable_units(model: MessageModel) -> tuple[TranslationUnit, ...]:
    """Enumerate every translatable string in ``model`` by typed path.
    Blank/None optional fields are skipped -- there is nothing to translate
    in a field the author never set."""
    units: list[TranslationUnit] = []
    if model.content.strip():
        units.append(TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), model.content))
    for embed_index, embed in enumerate(model.embeds):
        if embed.title and embed.title.strip():
            units.append(
                TranslationUnit(
                    FieldPath(TranslatableFieldKind.EMBED_TITLE, embed_index=embed_index),
                    embed.title,
                )
            )
        if embed.description and embed.description.strip():
            units.append(
                TranslationUnit(
                    FieldPath(TranslatableFieldKind.EMBED_DESCRIPTION, embed_index=embed_index),
                    embed.description,
                )
            )
        if embed.footer_text and embed.footer_text.strip():
            units.append(
                TranslationUnit(
                    FieldPath(TranslatableFieldKind.EMBED_FOOTER_TEXT, embed_index=embed_index),
                    embed.footer_text,
                )
            )
        if embed.author_name and embed.author_name.strip():
            units.append(
                TranslationUnit(
                    FieldPath(TranslatableFieldKind.EMBED_AUTHOR_NAME, embed_index=embed_index),
                    embed.author_name,
                )
            )
        for field_index, embed_field in enumerate(embed.fields):
            units.append(
                TranslationUnit(
                    FieldPath(
                        TranslatableFieldKind.EMBED_FIELD_NAME,
                        embed_index=embed_index,
                        field_index=field_index,
                    ),
                    embed_field.name,
                )
            )
            units.append(
                TranslationUnit(
                    FieldPath(
                        TranslatableFieldKind.EMBED_FIELD_VALUE,
                        embed_index=embed_index,
                        field_index=field_index,
                    ),
                    embed_field.value,
                )
            )
    for row_index, row in enumerate(model.action_rows):
        for button_index, button in enumerate(row.buttons):
            if button.label.strip():
                units.append(
                    TranslationUnit(
                        FieldPath(
                            TranslatableFieldKind.BUTTON_LABEL,
                            action_row_index=row_index,
                            button_index=button_index,
                        ),
                        button.label,
                    )
                )
    return tuple(units)


def apply_translated_units(model: MessageModel, translations: dict[FieldPath, str]) -> MessageModel:
    """Rebuild a MessageModel with ONLY the given typed paths' text replaced.
    Every non-translatable field (url, color, custom_id, button style,
    component structure/order/count) is carried through byte-identical from
    ``model`` via ``dataclasses.replace`` -- this function never touches
    them. A path present in ``model`` but absent from ``translations`` keeps
    its original text (e.g. the caller chose not to translate that unit)."""

    def _get(kind: TranslatableFieldKind, **coords: int) -> str | None:
        path = FieldPath(kind, **coords)
        return translations.get(path)

    new_content = _get(TranslatableFieldKind.CONTENT)
    content = new_content if new_content is not None else model.content

    new_embeds: list[Embed] = []
    for embed_index, embed in enumerate(model.embeds):
        new_fields: list[EmbedField] = []
        for field_index, embed_field in enumerate(embed.fields):
            name = _get(
                TranslatableFieldKind.EMBED_FIELD_NAME,
                embed_index=embed_index,
                field_index=field_index,
            )
            value = _get(
                TranslatableFieldKind.EMBED_FIELD_VALUE,
                embed_index=embed_index,
                field_index=field_index,
            )
            new_fields.append(
                replace(
                    embed_field,
                    name=name if name is not None else embed_field.name,
                    value=value if value is not None else embed_field.value,
                )
            )
        title = _get(TranslatableFieldKind.EMBED_TITLE, embed_index=embed_index)
        description = _get(TranslatableFieldKind.EMBED_DESCRIPTION, embed_index=embed_index)
        footer_text = _get(TranslatableFieldKind.EMBED_FOOTER_TEXT, embed_index=embed_index)
        author_name = _get(TranslatableFieldKind.EMBED_AUTHOR_NAME, embed_index=embed_index)
        new_embeds.append(
            replace(
                embed,
                title=title if title is not None else embed.title,
                description=description if description is not None else embed.description,
                footer_text=footer_text if footer_text is not None else embed.footer_text,
                author_name=author_name if author_name is not None else embed.author_name,
                fields=tuple(new_fields),
            )
        )

    new_rows: list[ComponentActionRow] = []
    for row_index, row in enumerate(model.action_rows):
        new_buttons = []
        for button_index, button in enumerate(row.buttons):
            label = _get(
                TranslatableFieldKind.BUTTON_LABEL,
                action_row_index=row_index,
                button_index=button_index,
            )
            new_buttons.append(replace(button, label=label if label is not None else button.label))
        new_rows.append(replace(row, buttons=tuple(new_buttons)))

    return replace(model, content=content, embeds=tuple(new_embeds), action_rows=tuple(new_rows))


TranslateUnit = Callable[[TranslationUnit], Awaitable[str]]


async def translate_message_model(
    model: MessageModel, *, translate_unit: TranslateUnit
) -> MessageModel:
    """Convenience orchestration: extract every translatable unit, translate
    each independently through ``translate_unit`` (expected to itself run
    the full parse/protect/translate/validate_full_pipeline gate -- this
    function does not bypass that, it only decides WHICH strings are
    eligible), and rebuild the model with exactly those fields replaced.
    A failure translating any single unit (``translate_unit`` raising) must
    propagate -- there is no per-field silent fallback to source text."""
    units = extract_translatable_units(model)
    translations = {unit.path: await translate_unit(unit) for unit in units}
    return apply_translated_units(model, translations)
