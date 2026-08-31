"""WP12/WP13: the real scheduler tick -- wires the already-fenced
``CampaignsRepository.claim_due_schedules``/``finalize_schedule_claim``
primitives and ``did.campaigns.scheduling``'s pure RRULE/misfire evaluation
into an actual claim -> evaluate -> reserve-occurrences -> fan-out ->
finalize-cursor cycle.

Deliberately narrow: this module owns exactly the schedule-specific
concerns (claiming, evaluating, cursor finalization). Everything needed to
actually expand an occurrence into deliveries (campaign/target/topology/
glossary/template-variable/translation-provider context) is supplied by the
caller through ``fan_out_for_occurrence`` -- an injected callback -- rather
than this module loading any of that itself, mirroring
``did.campaigns.activation.fan_out_occurrence``'s own "the caller already
knows how to load its context" contract. A real long-lived scheduler
process calls :func:`run_scheduler_tick` in a loop (e.g. every N seconds);
this module does not implement that outer loop/sleep timing itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from did.campaigns.activation import FanOutOutcome
from did.campaigns.scheduling import ScheduleEvaluationError, evaluate_one_shot, evaluate_recurring
from did.domain.campaigns import (
    CampaignSchedule,
    DstAmbiguousPolicy,
    DstNonexistentPolicy,
    MessageOccurrence,
    MisfirePolicy,
    OccurrenceSource,
    ScheduleKind,
)
from did.infrastructure.campaigns_repository import CampaignsRepository

#: Given a fully-reconstructed schedule and one due occurrence, load
#: whatever context is needed (campaign, targets, topology, glossary,
#: template variables, translation provider) and run
#: did.campaigns.activation.fan_out_occurrence, returning its outcome.
FanOutForOccurrence = Callable[[CampaignSchedule, MessageOccurrence], Awaitable[FanOutOutcome]]


@dataclass(frozen=True, slots=True)
class ScheduleTickError:
    schedule_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class SchedulerTickResult:
    schedules_claimed: int = 0
    occurrences_fanned_out: int = 0
    fan_out_outcomes: tuple[FanOutOutcome, ...] = field(default_factory=tuple)
    #: A schedule claimed but whose evaluation/fan-out raised -- its lease
    #: is deliberately left to expire naturally (never force-finalized on
    #: failure) so a future tick or another worker can retry it cleanly.
    errors: tuple[ScheduleTickError, ...] = field(default_factory=tuple)


def _schedule_from_claimed_row(row: dict[str, Any]) -> CampaignSchedule:
    return CampaignSchedule(
        id=row["id"],
        owner_discord_user_id=row["owner_discord_user_id"],
        campaign_id=row["campaign_id"],
        schedule_kind=ScheduleKind(row["schedule_kind"]),
        fire_at=row.get("fire_at"),
        rrule=row.get("rrule"),
        timezone=row.get("timezone"),
        starts_at=row.get("starts_at"),
        misfire_policy=MisfirePolicy(row["misfire_policy"]),
        dst_nonexistent_policy=DstNonexistentPolicy(row["dst_nonexistent_policy"]),
        dst_ambiguous_policy=DstAmbiguousPolicy(row["dst_ambiguous_policy"]),
        catch_up_bound=row["catch_up_bound"],
        last_cursor_local=row.get("last_cursor_local"),
        version=row["version"],
    )


async def run_scheduler_tick(
    *,
    repository: CampaignsRepository,
    admin_factory: async_sessionmaker[Any],
    lease_owner: str,
    now: datetime,
    fan_out_for_occurrence: FanOutForOccurrence,
    lease_seconds: float = 30.0,
    limit: int = 20,
) -> SchedulerTickResult:
    """One scheduler cycle: claim up to ``limit`` due schedules (already
    fenced by lease + owning-campaign-lifecycle -- see
    ``CampaignsRepository.claim_due_schedules``), evaluate each, fan out
    every due occurrence through the caller's ``fan_out_for_occurrence``
    callback (itself idempotent per occurrence -- see
    ``did.campaigns.activation.fan_out_occurrence``), and only then finalize
    the cursor -- fenced by the SAME lease token, so a worker that loses its
    lease mid-tick (crash, reclaim by another worker) can never advance a
    cursor for occurrences it may not have actually fanned out, and a
    restart simply reclaims the still-due schedule and reevaluates from the
    last durably-committed cursor.
    """
    claimed_rows = await repository.claim_due_schedules(
        admin_factory, now=now, lease_owner=lease_owner, lease_seconds=lease_seconds, limit=limit
    )
    fan_out_outcomes: list[FanOutOutcome] = []
    errors: list[ScheduleTickError] = []
    occurrences_fanned_out = 0

    for row in claimed_rows:
        try:
            schedule = _schedule_from_claimed_row(row)
            if schedule.schedule_kind is ScheduleKind.ONE_SHOT:
                evaluation = evaluate_one_shot(schedule, now=now)
            else:
                evaluation = evaluate_recurring(schedule, now=now)

            for due in evaluation.due:
                occurrence = MessageOccurrence(
                    id=_deterministic_occurrence_uuid(due.occurrence_key),
                    owner_discord_user_id=schedule.owner_discord_user_id,
                    campaign_id=schedule.campaign_id,
                    occurrence_key=due.occurrence_key,
                    occurrence_source=OccurrenceSource.SCHEDULE,
                    scheduled_for=due.scheduled_for_utc,
                )
                outcome = await fan_out_for_occurrence(schedule, occurrence)
                fan_out_outcomes.append(outcome)
                occurrences_fanned_out += 1

            finalized = await repository.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                row["lease_token"],
                now=now,
                new_last_cursor_local=evaluation.new_last_cursor_local,
                new_next_fire_at=evaluation.next_fire_at_utc,
            )
            if not finalized:
                errors.append(
                    ScheduleTickError(
                        schedule.id,
                        "lease lost or campaign no longer firing-eligible before finalize "
                        "-- cursor NOT advanced, occurrences already fanned out remain "
                        "durably idempotent for a future retry",
                    )
                )
        except ScheduleEvaluationError as exc:
            errors.append(ScheduleTickError(row["id"], f"evaluation failed: {exc}"))
        except Exception as exc:
            errors.append(ScheduleTickError(row["id"], f"unexpected error: {exc}"))

    return SchedulerTickResult(
        schedules_claimed=len(claimed_rows),
        occurrences_fanned_out=occurrences_fanned_out,
        fan_out_outcomes=tuple(fan_out_outcomes),
        errors=tuple(errors),
    )


def _deterministic_occurrence_uuid(occurrence_key: str) -> UUID:
    """A stable UUID derived from the schedule's own deterministic
    occurrence_key -- so a restart re-evaluating the same due instant
    builds the identical occurrence id, not just the same key string
    (belt-and-suspenders: UNIQUE(campaign_id, occurrence_key) is the actual
    source of truth for occurrence idempotency, exactly as in
    ``did.campaigns.event_consumer``)."""
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(NAMESPACE_URL, occurrence_key)
