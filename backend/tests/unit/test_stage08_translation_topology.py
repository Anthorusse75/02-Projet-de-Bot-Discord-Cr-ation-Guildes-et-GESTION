from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from did.domain.translation_topology import (
    LanguageProfile,
    ProviderConfigurationMode,
    ResourceLanguageResolver,
    RouteDecision,
    RouteValidationError,
    TranslationChannelGroup,
    TranslationGroup,
    TranslationGroupTopology,
    TranslationProvider,
    TranslationProviderCapabilities,
    TranslationProviderRegistry,
    VisibilityPolicy,
    compile_scope_language_roles,
    member_language_set_is_valid,
    resolve_scope_language_role_key,
    validate_translation_routes,
)

GUILD_A = 42
GUILD_B = 99
NOW = datetime(2026, 8, 28, tzinfo=UTC)


def _profile(code: str) -> LanguageProfile:
    return LanguageProfile(
        id=uuid4(),
        guild_id=GUILD_A,
        code=code,
        display_name=code.upper(),
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def test_member_visible_languages_support_zero_one_or_many_without_primary_language() -> None:
    assert member_language_set_is_valid(()) is True
    assert member_language_set_is_valid(("fr",)) is True
    assert member_language_set_is_valid(("fr", "en", "de")) is True
    assert member_language_set_is_valid(("fr", "en")) is True


def test_resource_language_inheritance_resolved_explicitly_without_fallback() -> None:
    resolver = ResourceLanguageResolver()
    fr = _profile("fr")
    en = _profile("en")
    assert resolver.resolve(channel_language=None, category_language=None) == (None, "NONE")
    assert resolver.resolve(channel_language=fr, category_language=None) == (fr.id, "SELF")
    assert resolver.resolve(channel_language=None, category_language=en) == (en.id, "CATEGORY")
    assert resolver.resolve(channel_language=None, category_language=None) == (None, "NONE")


def test_two_groups_with_identical_languages_are_independent() -> None:
    fr = _profile("fr")
    en = _profile("en")
    left = TranslationGroup(
        id=uuid4(),
        guild_id=GUILD_A,
        name="Group A",
        topology=TranslationGroupTopology.HUB_AND_SPOKE,
        routing_mode=TranslationGroupTopology.HUB_AND_SPOKE,
        visibility_policy=VisibilityPolicy.OPEN_ALL,
        language_ids=(fr.id, en.id),
        provider_binding_id=None,
        status="ACTIVE",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    right = TranslationGroup(
        id=uuid4(),
        guild_id=GUILD_A,
        name="Group B",
        topology=TranslationGroupTopology.HUB_AND_SPOKE,
        routing_mode=TranslationGroupTopology.HUB_AND_SPOKE,
        visibility_policy=VisibilityPolicy.OPEN_ALL,
        language_ids=(fr.id, en.id),
        provider_binding_id=None,
        status="ACTIVE",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    assert left.id != right.id
    assert left.language_ids == right.language_ids
    assert left is not right


def test_route_validation_rejects_duplicates_cross_guild_and_loops() -> None:
    fr = _profile("fr")
    en = _profile("en")
    group_id = uuid4()

    with pytest.raises(RouteValidationError):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=group_id,
            language_ids=(fr.id, en.id),
            variants={
                "src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_id,
                    "language_profile_id": fr.id,
                    "discord_channel_id": 1,
                },
                "dst": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_id,
                    "language_profile_id": en.id,
                    "discord_channel_id": 2,
                },
            },
            routes=[
                {
                    "source_language_profile_id": fr.id,
                    "destination_language_profile_id": en.id,
                    "translation_group_id": group_id,
                },
                {
                    "source_language_profile_id": fr.id,
                    "destination_language_profile_id": en.id,
                    "translation_group_id": group_id,
                },
            ],
        )

    with pytest.raises(RouteValidationError):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=group_id,
            language_ids=(fr.id, en.id),
            variants={
                "src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_id,
                    "language_profile_id": fr.id,
                    "discord_channel_id": 1,
                },
                "dst": {
                    "guild_id": GUILD_B,
                    "translation_group_id": group_id,
                    "language_profile_id": en.id,
                    "discord_channel_id": 2,
                },
            },
            routes=[
                {
                    "source_language_profile_id": fr.id,
                    "destination_language_profile_id": en.id,
                    "translation_group_id": group_id,
                },
            ],
        )

    routes = validate_translation_routes(
        guild_id=GUILD_A,
        group_id=group_id,
        language_ids=(fr.id, en.id),
        variants={
            "src": {
                "guild_id": GUILD_A,
                "translation_group_id": group_id,
                "language_profile_id": fr.id,
                "discord_channel_id": 1,
            },
            "dst": {
                "guild_id": GUILD_A,
                "translation_group_id": group_id,
                "language_profile_id": en.id,
                "discord_channel_id": 2,
            },
        },
        routes=[
            {
                "source_language_profile_id": fr.id,
                "destination_language_profile_id": en.id,
                "translation_group_id": group_id,
            },
        ],
    )
    assert routes[0].decision is RouteDecision.ACCEPTED


def test_route_validation_requires_matching_translation_group_variants() -> None:
    fr = _profile("fr")
    en = _profile("en")
    group_a = uuid4()
    group_b = uuid4()

    accepted = validate_translation_routes(
        guild_id=GUILD_A,
        group_id=group_a,
        language_ids=(fr.id, en.id),
        variants={
            "a_src": {
                "guild_id": GUILD_A,
                "translation_group_id": group_a,
                "language_profile_id": fr.id,
                "discord_channel_id": 1,
            },
            "a_dst": {
                "guild_id": GUILD_A,
                "translation_group_id": group_a,
                "language_profile_id": en.id,
                "discord_channel_id": 2,
            },
        },
        routes=[
            {
                "source_language_profile_id": fr.id,
                "destination_language_profile_id": en.id,
                "translation_group_id": group_a,
            },
        ],
    )
    assert accepted[0].translation_group_id == group_a
    assert accepted[0].decision is RouteDecision.ACCEPTED

    with pytest.raises(RouteValidationError, match="translation_group_id"):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=group_a,
            language_ids=(fr.id, en.id),
            variants={
                "b_src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_b,
                    "language_profile_id": fr.id,
                    "discord_channel_id": 10,
                },
                "b_dst": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_b,
                    "language_profile_id": en.id,
                    "discord_channel_id": 20,
                },
            },
            routes=[
                {
                    "source_language_profile_id": fr.id,
                    "destination_language_profile_id": en.id,
                    "translation_group_id": group_a,
                },
            ],
        )

    with pytest.raises(RouteValidationError, match="translation_group_id"):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=group_a,
            language_ids=(fr.id, en.id),
            variants={
                "a_src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_a,
                    "language_profile_id": fr.id,
                    "discord_channel_id": 1,
                },
                "b_dst": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_b,
                    "language_profile_id": en.id,
                    "discord_channel_id": 20,
                },
            },
            routes=[
                {"source_language_profile_id": fr.id, "destination_language_profile_id": en.id},
            ],
        )


def test_provider_capabilities_require_manual_setup_when_unknown() -> None:
    provider = TranslationProviderCapabilities(
        supports_hub_and_spoke=True,
        supports_full_mesh=False,
        supports_custom=True,
        requires_manual_configuration=True,
        health="UNKNOWN",
        discord_bot_present=False,
        bot_permissions=(),
    )
    assert provider.is_capable_for(TranslationGroupTopology.HUB_AND_SPOKE) is True
    assert provider.is_capable_for(TranslationGroupTopology.FULL_MESH) is False
    assert provider.requires_manual_configuration is True


def test_scope_language_key_is_stable_and_reusable() -> None:
    scope_id = uuid4()
    lang_id = uuid4()
    first = resolve_scope_language_role_key(scope_id, lang_id)
    second = resolve_scope_language_role_key(scope_id, lang_id)
    assert first == second
    assert first.startswith("scope:")


def test_explicit_scope_language_binding_is_only_created_when_policy_requires_it() -> None:
    scope_id = uuid4()
    fr = _profile("fr")
    en = _profile("en")

    open_all = compile_scope_language_roles(
        guild_id=GUILD_A,
        scope_id=scope_id,
        member_language_ids=(fr.id, en.id),
        visibility_policy=VisibilityPolicy.OPEN_ALL,
    )
    assert open_all.requires_explicit_binding is False

    scoped = compile_scope_language_roles(
        guild_id=GUILD_A,
        scope_id=scope_id,
        member_language_ids=(fr.id, en.id),
        visibility_policy=VisibilityPolicy.SCOPE_AND_LANGUAGE,
    )
    assert scoped.requires_explicit_binding is True
    assert len(scoped.required_bindings) == 2
    assert scoped.required_bindings[0].language_profile_id in {fr.id, en.id}

    custom = compile_scope_language_roles(
        guild_id=GUILD_A,
        scope_id=scope_id,
        member_language_ids=(fr.id, en.id),
        visibility_policy=VisibilityPolicy.CUSTOM,
    )
    assert custom.requires_explicit_binding is False
    assert custom.required_bindings == ()


async def test_manual_configuration_is_not_treated_as_success() -> None:
    registry = TranslationProviderRegistry()
    provider: TranslationProvider = _ManualProvider()
    registry.register("existing_translation_bot", provider)

    capabilities = await registry.capabilities("existing_translation_bot", GUILD_A)
    assert (
        capabilities.configuration_mode is ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED
    )
    assert capabilities.requires_manual_configuration is True


def test_route_validation_rejects_routes_with_mismatched_group_id() -> None:
    fr = _profile("fr")
    en = _profile("en")
    group_a = uuid4()
    group_b = uuid4()

    with pytest.raises(RouteValidationError, match="translation_group_id"):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=group_a,
            language_ids=(fr.id, en.id),
            variants={
                "src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_a,
                    "language_profile_id": fr.id,
                    "discord_channel_id": 1,
                },
                "dst": {
                    "guild_id": GUILD_A,
                    "translation_group_id": group_a,
                    "language_profile_id": en.id,
                    "discord_channel_id": 2,
                },
            },
            routes=[
                {
                    "source_language_profile_id": fr.id,
                    "destination_language_profile_id": en.id,
                    "translation_group_id": group_b,
                }
            ],
        )


def test_translation_channel_group_rename_preserves_identity() -> None:
    before = TranslationChannelGroup(
        id=uuid4(),
        guild_id=GUILD_A,
        name="General channels",
        logical_group_key="guides:en",
        category_discord_id=12,
    )
    after = before.renamed("Renamed channels")
    assert after.id == before.id
    assert after.logical_group_key == before.logical_group_key
    assert after.name == "Renamed channels"


class _ManualProvider:
    async def capabilities(self, guild_id: int) -> TranslationProviderCapabilities:
        del guild_id
        return TranslationProviderCapabilities(
            supports_hub_and_spoke=True,
            supports_full_mesh=False,
            supports_custom=True,
            supports_message_edits=False,
            supports_message_deletes=False,
            supports_attachments=False,
            supports_embeds=False,
            supports_threads=False,
            max_languages_per_group=2,
            configuration_mode=ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED,
            requires_manual_configuration=True,
            health="UNKNOWN",
            discord_bot_present=False,
            bot_permissions=(),
        )

    async def validate_group(self, desired_group: object) -> list[dict[str, object]]:
        del desired_group
        return []

    async def prepare_configuration(self, desired_group: object) -> dict[str, object]:
        del desired_group
        return {}

    async def observe_health(self, guild_id: int) -> dict[str, object]:
        del guild_id
        return {"status": "UNKNOWN"}
