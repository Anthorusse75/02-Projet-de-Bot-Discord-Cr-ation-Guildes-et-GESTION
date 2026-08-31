from __future__ import annotations

import logging
from uuid import UUID

from did.infrastructure.logging import EventId, emit_event
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.planning.models import PostVerificationOutcome

logger = logging.getLogger(__name__)


class Stage08PostVerificationMaterializer:
    """Commit Stage 08 logical state only after Stage 05 proves Discord state."""

    def __init__(self, repository: Stage08LifecycleRepository) -> None:
        self._repository = repository

    async def apply(
        self, *, guild_id: int, plan_id: UUID, correlation_id: UUID
    ) -> PostVerificationOutcome:
        del correlation_id
        try:
            _, provider_pending = await self._repository.apply_verified_intents(
                guild_id=guild_id, plan_id=plan_id
            )
        except Exception as error:
            emit_event(
                logger,
                logging.ERROR,
                EventId.STAGE08_POST_VERIFICATION_FAILED,
                fields={
                    "guild_id": guild_id,
                    "plan_id": str(plan_id),
                    "error_type": type(error).__name__,
                },
            )
            await self._repository.fail_pending_intents(
                guild_id=guild_id,
                plan_id=plan_id,
                error_code="STAGE08_POST_VERIFICATION_FAILED",
            )
            return PostVerificationOutcome.FAILED
        return (
            PostVerificationOutcome.PENDING_PROVIDER
            if provider_pending
            else PostVerificationOutcome.APPLIED
        )
