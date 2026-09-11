"""RRULE + IANA timezone recurrence evaluation with deterministic DST and
misfire behavior (WP2).

The RRULE is always expanded in **local civil (wall-clock) time** -- "every
day at 09:00 Europe/Paris" must keep firing at 09:00 local time across DST
transitions, not at a fixed UTC offset. Each candidate local occurrence is
converted to an absolute UTC instant through :func:`localize_wall_clock`,
which resolves DST ambiguity/nonexistence per the schedule's own policy
instead of relying on whatever a given platform's tz database does by
default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from did.domain.campaigns import (
    CampaignSchedule,
    DstAmbiguousPolicy,
    DstNonexistentPolicy,
    MisfirePolicy,
    ScheduleKind,
)


class ScheduleEvaluationError(ValueError):
    pass


def localize_wall_clock(
    naive_local: datetime,
    tz: ZoneInfo,
    *,
    ambiguous_policy: DstAmbiguousPolicy,
    nonexistent_policy: DstNonexistentPolicy,
) -> datetime | None:
    """Resolve one naive local wall-clock instant to an absolute UTC instant.

    Uses PEP 495 ``fold`` to disambiguate: if both interpretations produce
    the same UTC instant, the time is ordinary. If both round-trip back to
    the same requested wall-clock time but differ in UTC, the wall-clock
    time is a genuine fall-back duplicate (``ambiguous_policy`` picks
    earliest/latest real instant). Otherwise the wall-clock time never
    occurred at all (spring-forward gap): ``SKIP`` drops it (returns
    ``None``), ``SHIFT_FORWARD`` returns the interpretation whose local
    round-trip lands *after* the requested time (the natural "clock jumped
    past this moment" continuation).
    """
    fold0 = naive_local.replace(tzinfo=tz, fold=0).astimezone(UTC)
    fold1 = naive_local.replace(tzinfo=tz, fold=1).astimezone(UTC)
    if fold0 == fold1:
        return fold0

    back0 = fold0.astimezone(tz).replace(tzinfo=None)
    back1 = fold1.astimezone(tz).replace(tzinfo=None)

    if back0 == naive_local and back1 == naive_local:
        return (
            min(fold0, fold1)
            if ambiguous_policy is DstAmbiguousPolicy.EARLIEST
            else max(fold0, fold1)
        )

    if nonexistent_policy is DstNonexistentPolicy.SKIP:
        return None
    return fold0 if back0 > naive_local else fold1


@dataclass(frozen=True, slots=True)
class DueOccurrence:
    scheduled_for_utc: datetime
    #: Deterministic across restarts/redelivery: derived only from the
    #: schedule's own identity and the local wall-clock instant, never from
    #: wall-clock "now" -- this is what backs the DB uniqueness constraint
    #: that prevents duplicate occurrence creation after a scheduler crash.
    occurrence_key: str


@dataclass(frozen=True, slots=True)
class ScheduleEvaluation:
    due: tuple[DueOccurrence, ...]
    #: None for ONE_SHOT (which has no local-cursor concept at all -- it
    #: fires once and is done); always naive-local for RECURRING.
    new_last_cursor_local: datetime | None
    next_fire_at_utc: datetime | None


def _occurrence_key(schedule: CampaignSchedule, local_instant: datetime) -> str:
    return f"schedule:{schedule.id}:{local_instant.isoformat()}"


def evaluate_one_shot(schedule: CampaignSchedule, *, now: datetime) -> ScheduleEvaluation:
    assert schedule.schedule_kind is ScheduleKind.ONE_SHOT
    assert schedule.fire_at is not None
    if schedule.fire_at > now:
        return ScheduleEvaluation(
            due=(), new_last_cursor_local=None, next_fire_at_utc=schedule.fire_at
        )
    key = f"schedule:{schedule.id}:one-shot"
    return ScheduleEvaluation(
        due=(DueOccurrence(scheduled_for_utc=schedule.fire_at, occurrence_key=key),),
        new_last_cursor_local=None,
        next_fire_at_utc=None,
    )


def evaluate_recurring(schedule: CampaignSchedule, *, now: datetime) -> ScheduleEvaluation:
    """Advance a RECURRING schedule's cursor and return what is due to fire.

    Bounded catch-up: at most ``catch_up_bound`` missed occurrences are
    replayed under ``SKIP_MISSED`` (the newest ones; older backlog is
    permanently skipped, never fired). ``FIRE_ONCE_IMMEDIATELY`` collapses
    *any* backlog into exactly one occurrence (the most recent missed slot)
    so a long outage never floods Guilds with a burst of stale sends.
    """
    assert schedule.schedule_kind is ScheduleKind.RECURRING
    assert schedule.rrule and schedule.timezone and schedule.starts_at is not None
    tz = ZoneInfo(schedule.timezone)

    try:
        rule = rrulestr(schedule.rrule, dtstart=schedule.starts_at)
    except (ValueError, TypeError) as exc:
        raise ScheduleEvaluationError(f"invalid RRULE: {exc}") from exc

    if schedule.last_cursor_local is not None and schedule.last_cursor_local.tzinfo is not None:
        raise ScheduleEvaluationError(
            "last_cursor_local must be naive local wall-clock, not timezone-aware -- "
            "mixing it with starts_at would silently corrupt RRULE evaluation"
        )
    now_local = now.astimezone(tz).replace(tzinfo=None)
    cursor_local = schedule.last_cursor_local or schedule.starts_at

    candidates: list[datetime] = list(
        rule.between(cursor_local, now_local + timedelta(microseconds=1), inc=False)
    )

    if len(candidates) > schedule.catch_up_bound:
        if schedule.misfire_policy is MisfirePolicy.FIRE_ONCE_IMMEDIATELY:
            candidates = candidates[-1:]
        else:  # SKIP_MISSED
            candidates = candidates[-schedule.catch_up_bound :] if schedule.catch_up_bound else []

    due: list[DueOccurrence] = []
    for local_instant in candidates:
        resolved = localize_wall_clock(
            local_instant,
            tz,
            ambiguous_policy=schedule.dst_ambiguous_policy,
            nonexistent_policy=schedule.dst_nonexistent_policy,
        )
        if resolved is None:
            continue  # SKIP nonexistent-time policy: this slot never fires
        due.append(
            DueOccurrence(
                scheduled_for_utc=resolved,
                occurrence_key=_occurrence_key(schedule, local_instant),
            )
        )

    next_local = rule.after(now_local, inc=False)
    next_fire_at_utc = (
        localize_wall_clock(
            next_local,
            tz,
            ambiguous_policy=schedule.dst_ambiguous_policy,
            nonexistent_policy=schedule.dst_nonexistent_policy,
        )
        if next_local is not None
        else None
    )

    return ScheduleEvaluation(
        due=tuple(due), new_last_cursor_local=now_local, next_fire_at_utc=next_fire_at_utc
    )


def evaluate_schedule(schedule: CampaignSchedule, *, now: datetime) -> ScheduleEvaluation:
    if schedule.schedule_kind is ScheduleKind.ONE_SHOT:
        return evaluate_one_shot(schedule, now=now)
    if schedule.schedule_kind is ScheduleKind.RECURRING:
        return evaluate_recurring(schedule, now=now)
    raise ScheduleEvaluationError(
        "IMMEDIATE schedules are fired directly at campaign activation, "
        "not through cursor-based evaluation"
    )
