"""WP12: real per-delivery content rendering, composing every already-built
Stage 09 safety primitive into the single path a delivery's content is
actually decided through.

Two independent placeholder-protection layers compose here, applied as two
sequential mask/translate-or-not/restore round trips rather than merged into
one shared node list -- deliberately, to avoid the position-remapping
problem of threading two separate ``restore_overrides`` maps (one from
``did.messaging.template_variables.resolve_template_variables``, one from
``did.campaigns.glossary.apply_glossary_protection``) through node lists
that can each independently reshape (split/merge) TextNode content. Each
layer instead consumes and produces a plain string, so layer 2 simply
reparses layer 1's already-masked output as ordinary text:

1. **Template-variable layer**: resolves ``{{var}}`` per its declared
   ``TemplateVariableType`` (TRANSLATABLE_TEXT is inlined as plain text;
   NON_TRANSLATABLE/LOCALIZED_VALUE/PROTECTED stay protected), producing a
   masked string. Native protected tokens (URL/mention/timestamp/etc) are
   masked in this same pass, since ``protect()`` always masks every
   ``ProtectedNode`` regardless of kind.
2. **Glossary layer**: reparses that masked string (the placeholders from
   layer 1 are opaque alnum tokens no real glossary term can match) and
   protects any matching glossary term, optionally with a forced-
   translation restore override.

Only the fully layer-2-masked text is ever handed to a translation
provider. Restoration reverses the layers in order (glossary first, then
template), each via ``did.messaging.protector.validate_full_pipeline`` --
the same fail-closed, reparse-and-compare, structural-balance gate used
everywhere else in Stage 09. A caller that passes ``translate_masked_text=
None`` gets a source-language (untranslated) rendering that still resolves
template variables and glossary-protects the content -- both are always
required, translation is not.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from did.campaigns.glossary import apply_glossary_protection, resolve_applicable_entries
from did.domain.campaigns import GlossaryEntry
from did.messaging.message_model import MessageModel
from did.messaging.parser import parse
from did.messaging.protector import protect, validate_full_pipeline
from did.messaging.template_variables import TemplateVariableDefinition, resolve_template_variables
from did.messaging.translation_policy import (
    FieldPath,
    TranslationUnit,
    apply_translated_units,
    extract_translatable_units,
)

#: Translates already placeholder-masked text -- the same contract as
#: did.translation.segmentation.translate_masked_text's inner Translate
#: callable, reused here at the orchestration layer.
TranslateMaskedText = Callable[[str], Awaitable[str]]


async def render_field_text(
    unit: TranslationUnit,
    *,
    target_language: str,
    campaign_id: UUID,
    guild_id: int | None,
    template_variable_definitions: dict[str, TemplateVariableDefinition],
    glossary_entries: tuple[GlossaryEntry, ...],
    translate_masked_text: TranslateMaskedText | None,
) -> str:
    """Render exactly one translatable unit's final text -- see the module
    docstring for the two-layer design. ``translate_masked_text=None``
    yields a source-language rendering (template variables and glossary
    still resolved/protected; no translation call made)."""
    original_nodes = parse(unit.text)
    resolved_nodes, template_overrides = resolve_template_variables(
        original_nodes, template_variable_definitions, target_language=target_language
    )
    template_protection = protect(resolved_nodes, restore_overrides=template_overrides)

    glossary_source_nodes = parse(template_protection.masked_text)
    resolved_entries = resolve_applicable_entries(
        glossary_entries,
        campaign_id=campaign_id,
        target_language_code=target_language,
        guild_id=guild_id,
    )
    glossary_result = apply_glossary_protection(glossary_source_nodes, resolved_entries)
    glossary_protection = protect(
        glossary_result.nodes, restore_overrides=glossary_result.restore_overrides
    )

    if translate_masked_text is None:
        translated_masked = glossary_protection.masked_text
    else:
        translated_masked = await translate_masked_text(glossary_protection.masked_text)

    # The template layer's own placeholders are still present, as opaque
    # literal text, inside the glossary layer's input/output -- they are
    # not this (glossary) layer's concern (the template layer's own
    # validate_full_pipeline call below verifies them); without this,
    # validate_and_restore would wrongly flag them as invented/unknown
    # tokens, since both layers share the same placeholder token shape.
    template_placeholders = frozenset(fp.placeholder for fp in template_protection.fingerprints)
    after_glossary_restore = validate_full_pipeline(
        glossary_source_nodes,
        translated_masked,
        glossary_protection,
        foreign_placeholders=template_placeholders,
    )
    final_text = validate_full_pipeline(resolved_nodes, after_glossary_restore, template_protection)
    return final_text


async def render_message_model(
    source_model: MessageModel,
    *,
    target_language: str,
    campaign_id: UUID,
    guild_id: int | None,
    template_variable_definitions: dict[str, TemplateVariableDefinition],
    glossary_entries: tuple[GlossaryEntry, ...],
    translate_masked_text: TranslateMaskedText | None,
) -> MessageModel:
    """The single path any Stage 09 delivery's final content is decided
    through: extract every REQ-MSG-013 typed translatable field, render
    each through the two-layer template-variable/glossary/(optional
    translation) pipeline above, and rebuild the model -- technical fields
    (url, color, custom_id, button style, component structure) are never
    touched, exactly as ``did.messaging.translation_policy`` already
    guarantees. Any failure (integrity violation, translation provider
    error) propagates -- there is no silent fallback to untranslated source
    text for a destination that was supposed to be translated."""
    units = extract_translatable_units(source_model)
    rendered: dict[FieldPath, str] = {}
    for unit in units:
        rendered[unit.path] = await render_field_text(
            unit,
            target_language=target_language,
            campaign_id=campaign_id,
            guild_id=guild_id,
            template_variable_definitions=template_variable_definitions,
            glossary_entries=glossary_entries,
            translate_masked_text=translate_masked_text,
        )
    return apply_translated_units(source_model, rendered)
