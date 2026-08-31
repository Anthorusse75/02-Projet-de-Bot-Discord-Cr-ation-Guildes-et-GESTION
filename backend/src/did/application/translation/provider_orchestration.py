from __future__ import annotations

from typing import Any
from uuid import UUID

from did.application.translation.service import (
    ProviderAccessPreflight,
    TranslationProviderCoordinator,
)
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_repository import (
    Stage08NotFound,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)
from did.permissions import PermissionEvaluator
from did.permissions.models import DecisionStatus


class Stage08ProviderOrchestrationService:
    """Resolve provider eligibility from durable bindings and cache-first Discord facts."""

    def __init__(
        self,
        *,
        read_models: Stage04Repository,
        groups: TranslationGroupRepository,
        providers: TranslationProviderBindingRepository,
    ) -> None:
        self._read_models = read_models
        self._groups = groups
        self._providers = providers
        self._permissions = PermissionEvaluator()
        self._coordinator = TranslationProviderCoordinator()

    async def access_preflight(
        self, *, guild_id: int, group_id: UUID, binding_id: UUID
    ) -> tuple[ProviderAccessPreflight, dict[str, Any]]:
        group, binding = await self._authority(
            guild_id=guild_id,
            group_id=group_id,
            binding_id=binding_id,
        )
        provider_user_id = binding.get("provider_discord_user_id")
        capabilities = dict(binding.get("capabilities_json") or {})
        effective_by_variant: dict[int, int] = {}
        incomplete: list[str] = []
        active_variants = [
            variant for variant in group["channel_variants"] if str(variant["state"]) == "ACTIVE"
        ]
        if not active_variants:
            incomplete.append("NO_ACTIVE_VARIANTS")
        member = None
        if provider_user_id is not None:
            guild, member = await self._read_models.guild_snapshot(guild_id, int(provider_user_id))
            if member is not None:
                for variant in active_variants:
                    channel_id = int(variant["discord_channel_id"])
                    channel = guild.channel(channel_id)
                    if channel is None:
                        incomplete.append(f"channel:{channel_id}:missing")
                        continue
                    decision = self._permissions.evaluate(
                        guild=guild,
                        member=member,
                        resource=channel,
                        parent=(guild.channel(channel.parent_id) if channel.parent_id else None),
                    )
                    if decision.status is not DecisionStatus.COMPLETE:
                        incomplete.append(f"channel:{channel_id}:{decision.status.value}")
                        continue
                    effective_by_variant[channel_id] = decision.effective_bits
        result = self._coordinator.access_preflight(
            bot_present=member is not None and bool(member.is_bot),
            effective_permissions_by_variant=effective_by_variant,
            require_threads=bool(capabilities.get("supports_threads", False)),
            require_embeds=bool(capabilities.get("supports_embeds", False)),
            require_attachments=bool(capabilities.get("supports_attachments", False)),
        )
        if incomplete and result.allowed:
            result = ProviderAccessPreflight(
                False,
                "OBSERVABILITY_INCOMPLETE",
                result.missing_permissions,
                tuple(sorted((*result.warnings, "PROVIDER_ACCESS_INCOMPLETE"))),
                result.required_permissions,
            )
        return result, {
            "source": "DURABLE_BINDING_AND_STAGE04_CACHE",
            "binding_status": str(binding["status"]),
            "provider_discord_user_id_present": provider_user_id is not None,
            "active_variant_count": len(active_variants),
            "evaluated_variant_count": len(effective_by_variant),
            "incomplete": incomplete,
            "routing_supported": self._routing_supported(group, capabilities),
        }

    async def prepare_manual_configuration(
        self, *, guild_id: int, group_id: UUID, binding_id: UUID
    ) -> dict[str, Any]:
        group, binding = await self._authority(
            guild_id=guild_id,
            group_id=group_id,
            binding_id=binding_id,
        )
        capabilities = dict(binding.get("capabilities_json") or {})
        await self._providers.set_group_provider_state(
            guild_id=guild_id,
            group_id=group_id,
            binding_id=binding_id,
            provider_status="MANUAL_CONFIGURATION_REQUIRED",
            group_status="PROVIDER_PENDING",
            verified=False,
        )
        variants = [
            {
                "language_profile_id": str(row["language_profile_id"]),
                "discord_channel_id": str(row["discord_channel_id"]),
            }
            for row in group["channel_variants"]
            if str(row["state"]) == "ACTIVE"
        ]
        return {
            "state": "MANUAL_CONFIGURATION_REQUIRED",
            "verification_state": "PENDING_MANUAL_VERIFICATION",
            "instructions": [
                "Open the provider's own configuration interface.",
                "Configure only the explicit DID channel identifiers listed below.",
                "Return to DID and run the provider verification transition.",
            ],
            "variant_mappings": variants,
            "routing_mode": str(group["routing_mode"]),
            "routing_supported": self._routing_supported(group, capabilities),
            "automatic_mutation_performed": False,
            "token_shared": False,
            "authority": "DURABLE_GROUP_AND_PROVIDER_BINDING",
        }

    async def verify_manual_configuration(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        binding_id: UUID,
        confirmed_manual_configuration: bool,
    ) -> dict[str, Any]:
        if not confirmed_manual_configuration:
            raise ValueError("manual provider configuration must be explicitly confirmed")
        group, binding = await self._authority(
            guild_id=guild_id,
            group_id=group_id,
            binding_id=binding_id,
        )
        if str(binding["status"]) != "MANUAL_CONFIGURATION_REQUIRED":
            raise ValueError("provider is not awaiting manual verification")
        access, authority = await self.access_preflight(
            guild_id=guild_id,
            group_id=group_id,
            binding_id=binding_id,
        )
        capabilities = dict(binding.get("capabilities_json") or {})
        if not access.allowed or not self._routing_supported(group, capabilities):
            raise ValueError("provider verification failed authoritative access or routing checks")
        updated = await self._providers.set_group_provider_state(
            guild_id=guild_id,
            group_id=group_id,
            binding_id=binding_id,
            provider_status="READY",
            group_status="ACTIVE",
            verified=True,
        )
        return {
            "state": str(updated["status"]),
            "verification_state": "VERIFIED",
            "authority": authority,
            "automatic_mutation_performed": False,
            "token_shared": False,
        }

    async def _authority(
        self, *, guild_id: int, group_id: UUID, binding_id: UUID
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        group = await self._groups.workspace_group(guild_id=guild_id, group_id=group_id)
        if (
            group.get("provider_binding_id") is None
            or UUID(str(group["provider_binding_id"])) != binding_id
        ):
            raise Stage08NotFound("provider binding does not belong to this translation group")
        binding = await self._providers.get(guild_id=guild_id, binding_id=binding_id)
        return group, binding

    @staticmethod
    def _routing_supported(group: dict[str, Any], capabilities: dict[str, Any]) -> bool:
        capability_key = {
            "HUB_AND_SPOKE": "supports_hub_and_spoke",
            "FULL_MESH": "supports_full_mesh",
            "CUSTOM": "supports_custom",
        }[str(group["routing_mode"])]
        maximum = capabilities.get("max_languages_per_group")
        return bool(capabilities.get(capability_key, False)) and (
            maximum is None or len(group["languages"]) <= int(maximum)
        )
