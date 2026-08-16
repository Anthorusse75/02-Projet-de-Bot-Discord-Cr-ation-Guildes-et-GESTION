from did.tenancy import TenantContext, current_tenant, tenant_scope


def test_tenant_scope_is_nested_and_reset() -> None:
    outer = TenantContext(guild_id=100, user_id=10)
    inner = TenantContext(guild_id=200, user_id=20)
    assert current_tenant() is None
    with tenant_scope(outer):
        assert current_tenant() == outer
        with tenant_scope(inner):
            assert current_tenant() == inner
        assert current_tenant() == outer
    assert current_tenant() is None
