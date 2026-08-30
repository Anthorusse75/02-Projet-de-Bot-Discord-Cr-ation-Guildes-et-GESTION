from __future__ import annotations

from uuid import UUID

from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository


class Stage08PostVerificationMaterializer:
    """Commit Stage 08 logical state only after Stage 05 proves Discord state."""

    def __init__(self, repository: Stage08LifecycleRepository) -> None:
        self._repository = repository

    async def apply(self, *, guild_id: int, plan_id: UUID, correlation_id: UUID) -> bool:
        del correlation_id
        try:
            await self._repository.apply_verified_intents(guild_id=guild_id, plan_id=plan_id)
        except Exception:
            await self._repository.fail_pending_intents(
                guild_id=guild_id,
                plan_id=plan_id,
                error_code="STAGE08_POST_VERIFICATION_FAILED",
            )
            return False
        return True
