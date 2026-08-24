from __future__ import annotations

from did.application.auth import AuthorizationService
from did.domain.auth import AuthorizationScope, Capability


class ApplyActorAuthorizer:
    """Worker-facing authorization port backed by the STAGE 02 decision engine."""

    def __init__(self, authorization: AuthorizationService) -> None:
        self._authorization = authorization

    async def authorize_apply(self, *, guild_id: int, actor_user_id: int) -> None:
        await self._authorization.authorize(
            discord_user_id=actor_user_id,
            guild_id=guild_id,
            capability=Capability.PLANS_APPLY,
            scope=AuthorizationScope.guild(),
            sensitive=True,
            require_active_installation=True,
            require_discovery=False,
        )
