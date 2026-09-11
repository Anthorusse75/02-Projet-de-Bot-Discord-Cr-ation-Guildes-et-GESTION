import logging
from unittest.mock import ANY, AsyncMock, MagicMock, create_autospec, patch

import pytest
from redis.asyncio import Redis

from did.application.auth.service import AuthorizationService
from did.application.installations.service import InstallationService
from did.domain.auth import AuthorizationScope, Capability
from did.infrastructure.auth_repository import AuthRepository
from did.infrastructure.logging import EventId
from did.infrastructure.runtime_redis import RedisRuntimeWakeup

GUILD_ID = 123456789012345678
ACTOR_USER_ID = 876543210987654321


def dependencies() -> tuple[
    AuthorizationService,
    AuthRepository,
    Redis,
    RedisRuntimeWakeup,
]:
    return (
        create_autospec(AuthorizationService, instance=True),
        create_autospec(AuthRepository, instance=True),
        MagicMock(spec=Redis),
        create_autospec(RedisRuntimeWakeup, instance=True),
    )


async def test_purge_tenant_emits_event_only_after_successful_delete() -> None:
    authorization, repository, redis, wakeup = dependencies()
    order: list[str] = []
    authorization.authorize.side_effect = lambda **_: order.append("authorize")
    repository.mark_uninstalled.side_effect = lambda *_: order.append("mark_uninstalled")
    wakeup.remove_job_guild.side_effect = lambda *_: order.append("remove_job_guild")
    repository.delete_tenant.side_effect = lambda *_: order.append("delete_tenant") or True
    service = InstallationService(
        authorization=authorization,
        repository=repository,
        redis=redis,
        runtime_wakeup=wakeup,
    )

    with (
        patch(
            "did.application.installations.service.purge_guild_namespace",
            new_callable=AsyncMock,
            side_effect=lambda *_: order.append("purge_guild_namespace"),
        ) as purge_namespace,
        patch(
            "did.application.installations.service.emit_event",
            side_effect=lambda *_args, **_kwargs: order.append("tenant_purged"),
        ) as tenant_purged,
    ):
        assert await service.purge_tenant(
            guild_id=GUILD_ID, actor_user_id=ACTOR_USER_ID
        ) is True

    assert order == [
        "authorize",
        "mark_uninstalled",
        "remove_job_guild",
        "purge_guild_namespace",
        "delete_tenant",
        "tenant_purged",
    ]
    authorization.authorize.assert_awaited_once_with(
        discord_user_id=ACTOR_USER_ID,
        guild_id=GUILD_ID,
        capability=Capability.RBAC_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    purge_namespace.assert_awaited_once_with(redis, GUILD_ID)
    tenant_purged.assert_called_once_with(
        ANY,
        logging.INFO,
        EventId.TENANT_PURGED,
        fields={"guild_id": GUILD_ID, "user_id": ACTOR_USER_ID},
    )

    failures = (("redis", "redis unavailable"), ("delete", "delete failed"))
    for failure, message in failures:
        failed_authorization, failed_repository, failed_redis, failed_wakeup = dependencies()
        if failure == "delete":
            failed_repository.delete_tenant.side_effect = RuntimeError(message)
        failed_service = InstallationService(
            authorization=failed_authorization,
            repository=failed_repository,
            redis=failed_redis,
            runtime_wakeup=failed_wakeup,
        )
        failed_purge = AsyncMock(
            side_effect=RuntimeError(message) if failure == "redis" else None
        )
        with (
            patch(
                "did.application.installations.service.purge_guild_namespace",
                new=failed_purge,
            ),
            patch("did.application.installations.service.emit_event") as failed_event,
            pytest.raises(RuntimeError, match=message),
        ):
            await failed_service.purge_tenant(
                guild_id=GUILD_ID, actor_user_id=ACTOR_USER_ID
            )
        failed_event.assert_not_called()


async def test_purge_tenant_redis_error_prevents_final_database_delete() -> None:
    authorization, repository, redis, wakeup = dependencies()
    service = InstallationService(
        authorization=authorization,
        repository=repository,
        redis=redis,
        runtime_wakeup=wakeup,
    )

    with (
        patch(
            "did.application.installations.service.purge_guild_namespace",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis unavailable"),
        ),
        pytest.raises(RuntimeError, match="redis unavailable"),
    ):
        await service.purge_tenant(guild_id=GUILD_ID, actor_user_id=ACTOR_USER_ID)

    authorization.authorize.assert_awaited_once()
    repository.mark_uninstalled.assert_awaited_once_with(GUILD_ID, ACTOR_USER_ID)
    wakeup.remove_job_guild.assert_awaited_once_with(GUILD_ID)
    repository.delete_tenant.assert_not_awaited()
