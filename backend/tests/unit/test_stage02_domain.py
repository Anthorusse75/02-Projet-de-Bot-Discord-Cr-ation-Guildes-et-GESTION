from datetime import UTC, datetime, timedelta

import pytest

from did.domain.auth import (
    DISCORD_ADMINISTRATOR,
    ActorMembership,
    Capability,
    PlatformRole,
    bootstrap_allowed,
    capabilities_for_role,
)


@pytest.mark.parametrize(
    ("owner", "permissions", "allowed"),
    [
        (True, 0, True),
        (False, DISCORD_ADMINISTRATOR, True),
        (False, 1 << 5, False),
        (False, 0, False),
    ],
)
def test_bootstrap_requires_owner_or_administrator(
    owner: bool, permissions: int, allowed: bool
) -> None:
    assert bootstrap_allowed(owner=owner, permissions=permissions) is allowed


def test_dashboard_roles_resolve_capabilities_without_granting_discord_permissions() -> None:
    assert Capability.RBAC_WRITE in capabilities_for_role(PlatformRole.TENANT_ADMIN)
    assert Capability.RBAC_WRITE not in capabilities_for_role(PlatformRole.READ_ONLY)
    assert all(isinstance(capability.value, str) for capability in Capability)


def test_authorization_freshness_is_distinct_from_display_age() -> None:
    membership = ActorMembership(
        guild_id=1,
        discord_user_id=2,
        role_ids=(3,),
        observed_at=datetime.now(UTC) - timedelta(seconds=121),
        source="TARGETED_REST",
    )
    assert not membership.is_fresh(max_age_seconds=120)
    assert membership.is_fresh(max_age_seconds=300)
