"""REQ-MSG-007/013: double-translation safety for Translation Group
publication modes.

Uses REAL Stage08 Translation Group/provider-binding state
(``translation_groups.provider_binding_id`` and
``translation_provider_bindings.status``) -- but no code path here modifies
or coordinates with the external translation bot itself, and no capability
model anywhere in Stage08 records whether a specific bound provider
re-translates bot-authored messages (a fact genuinely outside this
system's visibility: it depends entirely on that third-party bot's own,
externally-configured behavior). Given that hard boundary, this module
never guesses: ``DID_TRANSLATED_FANOUT``/``SELECTED_LANGUAGES`` (the two
modes where DID itself posts destination-language messages) are only ever
considered safe non-invasively when no ACTIVE external provider is bound to
watch the same Translation Group -- whenever one might be active, this
fails closed to ``MANUAL_CONFIGURATION_REQUIRED`` rather than silently
risking a re-translation loop. ``SOURCE_ONLY``/``EXISTING_PROVIDER`` are
always safe: DID never posts a DID-translated destination in either mode,
so there is nothing for any external provider to ever see twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from did.domain.campaigns import TranslationPublicationMode

#: Provider binding statuses that mean the bound provider is not currently
#: active/watching -- DID's own fan-out cannot be re-translated by
#: something that is not running. Every other status (READY, DEGRADED,
#: ERROR, UNKNOWN, MANUAL_CONFIGURATION_REQUIRED) means the provider
#: exists and might still be watching -- DID cannot verify that without
#: modifying it, so those all fail closed.
_INACTIVE_PROVIDER_STATUSES = frozenset({"DISABLED"})

_DID_TRANSLATED_MODES = frozenset(
    {
        TranslationPublicationMode.DID_TRANSLATED_FANOUT,
        TranslationPublicationMode.SELECTED_LANGUAGES,
    }
)


class TranslationGroupSafetyDecision(StrEnum):
    SAFE = "SAFE"
    MANUAL_CONFIGURATION_REQUIRED = "MANUAL_CONFIGURATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class TranslationGroupSafetyResult:
    decision: TranslationGroupSafetyDecision
    reason: str

    @property
    def is_safe(self) -> bool:
        return self.decision is TranslationGroupSafetyDecision.SAFE


def evaluate_translation_group_safety(
    *,
    publication_mode: TranslationPublicationMode,
    provider_binding_status: str | None,
) -> TranslationGroupSafetyResult:
    """``provider_binding_status`` is ``None`` when the Translation Group
    has no ``provider_binding_id`` at all (no external provider ever
    configured) -- otherwise the real, current
    ``translation_provider_bindings.status`` value for that binding."""
    if publication_mode not in _DID_TRANSLATED_MODES:
        # SOURCE_ONLY / EXISTING_PROVIDER: DID never publishes a
        # DID-translated destination in either mode.
        return TranslationGroupSafetyResult(
            TranslationGroupSafetyDecision.SAFE,
            "DID publishes only the source channel in this publication mode; "
            "no DID-translated destination exists for an external provider to re-translate.",
        )
    if provider_binding_status is None:
        return TranslationGroupSafetyResult(
            TranslationGroupSafetyDecision.SAFE,
            "No external translation provider is bound to this Translation Group.",
        )
    if provider_binding_status in _INACTIVE_PROVIDER_STATUSES:
        return TranslationGroupSafetyResult(
            TranslationGroupSafetyDecision.SAFE,
            "The bound external provider is explicitly DISABLED and cannot "
            "re-translate DID's own destination-language posts.",
        )
    return TranslationGroupSafetyResult(
        TranslationGroupSafetyDecision.MANUAL_CONFIGURATION_REQUIRED,
        "An external translation provider is bound to this Translation Group "
        f"(status={provider_binding_status}) and DID cannot verify, without modifying that "
        "provider, whether it will re-translate DID's own destination-language posts. "
        "Disable the provider binding, or manually configure the external provider to "
        "ignore DID-authored messages, before enabling DID-translated fan-out.",
    )


async def load_provider_binding_status(
    provider_bindings: Any, *, guild_id: int, provider_binding_id: Any
) -> str | None:
    """Reads the REAL current status of a Translation Group's bound
    provider, if any. ``provider_bindings`` is a
    ``did.infrastructure.stage08_repository.TranslationProviderBindingRepository``
    (typed loosely here to avoid a hard import-time dependency on Stage08's
    repository module from this pure-decision module's own test surface)."""
    if provider_binding_id is None:
        return None
    binding = await provider_bindings.get(guild_id=guild_id, binding_id=provider_binding_id)
    return str(binding["status"])
