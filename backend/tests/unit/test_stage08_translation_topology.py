from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from did.domain.translation_topology import (
    LanguageProfile,
    ResourceLanguageResolver,
    RouteDecision,
    RouteValidationError,
    TranslationGroup,
    TranslationGroupTopology,
    TranslationProviderCapabilities,
    VisibilityPolicy,
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
    with pytest.raises(RouteValidationError):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=uuid4(),
            language_ids=(fr.id, en.id),
            variants={
                "src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": uuid4(),
                    "language_profile_id": fr.id,
                    "discord_channel_id": 1,
                },
                "dst": {
                    "guild_id": GUILD_A,
                    "translation_group_id": uuid4(),
                    "language_profile_id": en.id,
                    "discord_channel_id": 2,
                },
            },
            routes=[
                {"source_language_profile_id": fr.id, "destination_language_profile_id": en.id},
                {"source_language_profile_id": fr.id, "destination_language_profile_id": en.id},
            ],
        )
    with pytest.raises(RouteValidationError):
        validate_translation_routes(
            guild_id=GUILD_A,
            group_id=uuid4(),
            language_ids=(fr.id, en.id),
            variants={
                "src": {
                    "guild_id": GUILD_A,
                    "translation_group_id": uuid4(),
                    "language_profile_id": fr.id,
                    "discord_channel_id": 1,
                },
                "dst": {
                    "guild_id": GUILD_B,
                    "translation_group_id": uuid4(),
                    "language_profile_id": en.id,
                    "discord_channel_id": 2,
                },
            },
            routes=[
                {"source_language_profile_id": fr.id, "destination_language_profile_id": en.id},
            ],
        )
    routes = validate_translation_routes(
        guild_id=GUILD_A,
        group_id=uuid4(),
        language_ids=(fr.id, en.id),
        variants={
            "src": {
                "guild_id": GUILD_A,
                "translation_group_id": uuid4(),
                "language_profile_id": fr.id,
                "discord_channel_id": 1,
            },
            "dst": {
                "guild_id": GUILD_A,
                "translation_group_id": uuid4(),
                "language_profile_id": en.id,
                "discord_channel_id": 2,
            },
        },
        routes=[
            {"source_language_profile_id": fr.id, "destination_language_profile_id": en.id},
        ],
    )
    assert routes[0].decision is RouteDecision.ACCEPTED


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
