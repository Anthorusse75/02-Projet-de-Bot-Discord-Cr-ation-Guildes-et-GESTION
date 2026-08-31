from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from did.domain.translation_topology import (
    ProviderConfigurationMode,
    TranslationProviderCapabilities,
)

CapabilityProbe = Callable[[int], Awaitable[dict[str, Any] | None]]
HealthProbe = Callable[[int], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class NonInvasiveExistingBotProvider:
    """Read-only adapter for an existing translation bot.

    It deliberately has no bot token, write client, or external schema dependency.
    Configuration remains manual unless a future separately-audited interface exists.
    """

    capability_probe: CapabilityProbe
    health_probe: HealthProbe

    async def capabilities(self, guild_id: int) -> TranslationProviderCapabilities:
        observed = await self.capability_probe(guild_id)
        if observed is None:
            return TranslationProviderCapabilities(
                configuration_mode=ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED,
                requires_manual_configuration=True,
                health="UNKNOWN",
            )
        return TranslationProviderCapabilities(
            supports_hub_and_spoke=bool(observed.get("supports_hub_and_spoke", False)),
            supports_full_mesh=bool(observed.get("supports_full_mesh", False)),
            supports_custom=bool(observed.get("supports_custom", False)),
            supports_message_edits=bool(observed.get("supports_message_edits", False)),
            supports_message_deletes=bool(observed.get("supports_message_deletes", False)),
            supports_attachments=bool(observed.get("supports_attachments", False)),
            supports_embeds=bool(observed.get("supports_embeds", False)),
            supports_threads=bool(observed.get("supports_threads", False)),
            requires_message_content=bool(observed.get("requires_message_content", False)),
            max_languages_per_group=(
                int(observed["max_languages_per_group"])
                if observed.get("max_languages_per_group") is not None
                else None
            ),
            configuration_mode=ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED,
            requires_manual_configuration=True,
            health=str(observed.get("health", "UNKNOWN")),
            discord_bot_present=bool(observed.get("discord_bot_present", False)),
            bot_permissions=tuple(str(item) for item in observed.get("bot_permissions", ())),
        )

    async def validate_group(self, desired_group: object) -> list[dict[str, object]]:
        del desired_group
        return []

    async def prepare_configuration(self, desired_group: object) -> dict[str, object]:
        del desired_group
        return {
            "instructions": [
                "Open the existing provider's own configuration interface.",
                "Map each DID variant using its explicit Discord channel identifier.",
                "Return to DID and run provider access and route verification.",
            ],
            "automatic_mutation_performed": False,
            "token_shared": False,
        }

    async def observe_health(self, guild_id: int) -> dict[str, object]:
        return await self.health_probe(guild_id)
