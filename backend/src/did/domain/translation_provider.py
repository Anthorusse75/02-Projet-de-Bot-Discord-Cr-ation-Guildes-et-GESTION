"""Stage 09 campaign direct-translation port (WP9).

Distinct from Stage 08's ``TranslationProvider`` Protocol in
``translation_topology.py`` (which describes an *existing external bot's*
capabilities/configuration for Translation Channel Groups). This port is for
DID's own direct campaign translation: a single ``translate()`` call, no
vendor SDK type ever crosses into this module or any caller of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class TranslationProviderError(Exception):
    """Base class for every failure mode of a CampaignTranslationProvider."""


class TranslationTimeoutError(TranslationProviderError):
    pass


class TranslationCircuitOpenError(TranslationProviderError):
    """The provider has failed enough recently that calls fail fast without
    reaching the network at all."""


@dataclass(frozen=True, slots=True)
class TranslationResult:
    source_language: str
    target_language: str
    translated_text: str
    detected_source_language: str | None = None


@runtime_checkable
class CampaignTranslationProvider(Protocol):
    async def translate(
        self, text: str, *, source_language: str, target_language: str
    ) -> TranslationResult: ...
