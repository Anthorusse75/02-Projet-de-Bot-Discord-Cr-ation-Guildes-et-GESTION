"""Unit tests for WP2: RRULE + IANA timezone recurrence, DST ambiguity/
nonexistence and bounded misfire catch-up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from did.campaigns.scheduling import (
    ScheduleEvaluationError,
    evaluate_one_shot,
    evaluate_recurring,
    evaluate_schedule,
    localize_wall_clock,
)
from did.domain.campaigns import (
    CampaignSchedule,
    DstAmbiguousPolicy,
    DstNonexistentPolicy,
    MisfirePolicy,
    ScheduleKind,
)

pytestmark = [pytest.mark.security]

PARIS = ZoneInfo("Europe/Paris")


def _recurring(**overrides: object) -> CampaignSchedule:
    fields: dict[str, object] = dict(
        id=uuid4(),
        owner_discord_user_id=1,
        campaign_id=uuid4(),
        schedule_kind=ScheduleKind.RECURRING,
        rrule="FREQ=DAILY",
        timezone="Europe/Paris",
        starts_at=datetime(2026, 1, 1, 9, 0, 0),
        catch_up_bound=3,
    )
    fields.update(overrides)
    return CampaignSchedule(**fields)  # type: ignore[arg-type]


class TestLocalizeWallClock:
    def test_ordinary_time_is_unambiguous(self) -> None:
        result = localize_wall_clock(
            datetime(2026, 6, 15, 9, 0, 0),
            PARIS,
            ambiguous_policy=DstAmbiguousPolicy.EARLIEST,
            nonexistent_policy=DstNonexistentPolicy.SHIFT_FORWARD,
        )
        assert result is not None
        assert result.astimezone(PARIS).replace(tzinfo=None) == datetime(2026, 6, 15, 9, 0, 0)

    def test_spring_forward_gap_skip_returns_none(self) -> None:
        # 2026-03-29 02:30 Europe/Paris does not exist (clocks jump 02:00->03:00)
        result = localize_wall_clock(
            datetime(2026, 3, 29, 2, 30, 0),
            PARIS,
            ambiguous_policy=DstAmbiguousPolicy.EARLIEST,
            nonexistent_policy=DstNonexistentPolicy.SKIP,
        )
        assert result is None

    def test_spring_forward_gap_shift_forward_lands_after_requested_time(self) -> None:
        result = localize_wall_clock(
            datetime(2026, 3, 29, 2, 30, 0),
            PARIS,
            ambiguous_policy=DstAmbiguousPolicy.EARLIEST,
            nonexistent_policy=DstNonexistentPolicy.SHIFT_FORWARD,
        )
        assert result is not None
        back = result.astimezone(PARIS).replace(tzinfo=None)
        assert back > datetime(2026, 3, 29, 2, 30, 0)

    def test_fall_back_duplicate_earliest_vs_latest_differ(self) -> None:
        # 2026-10-25 02:30 Europe/Paris occurs twice
        naive = datetime(2026, 10, 25, 2, 30, 0)
        earliest = localize_wall_clock(
            naive,
            PARIS,
            ambiguous_policy=DstAmbiguousPolicy.EARLIEST,
            nonexistent_policy=DstNonexistentPolicy.SHIFT_FORWARD,
        )
        latest = localize_wall_clock(
            naive,
            PARIS,
            ambiguous_policy=DstAmbiguousPolicy.LATEST,
            nonexistent_policy=DstNonexistentPolicy.SHIFT_FORWARD,
        )
        assert earliest is not None and latest is not None
        assert earliest < latest
        # both genuinely correspond to the same wall-clock reading
        assert earliest.astimezone(PARIS).replace(tzinfo=None) == naive
        assert latest.astimezone(PARIS).replace(tzinfo=None) == naive

    def test_fall_back_earliest_is_deterministic_across_calls(self) -> None:
        naive = datetime(2026, 10, 25, 2, 30, 0)
        results = {
            localize_wall_clock(
                naive,
                PARIS,
                ambiguous_policy=DstAmbiguousPolicy.EARLIEST,
                nonexistent_policy=DstNonexistentPolicy.SHIFT_FORWARD,
            )
            for _ in range(5)
        }
        assert len(results) == 1


class TestOneShot:
    def _schedule(self, fire_at: datetime) -> CampaignSchedule:
        return CampaignSchedule(
            id=uuid4(),
            owner_discord_user_id=1,
            campaign_id=uuid4(),
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=fire_at,
        )

    def test_future_fire_at_is_not_yet_due(self) -> None:
        schedule = self._schedule(datetime(2030, 1, 1, tzinfo=UTC))
        result = evaluate_one_shot(schedule, now=datetime(2026, 1, 1, tzinfo=UTC))
        assert result.due == ()

    def test_past_fire_at_is_due_exactly_once(self) -> None:
        schedule = self._schedule(datetime(2020, 1, 1, tzinfo=UTC))
        result = evaluate_one_shot(schedule, now=datetime(2026, 1, 1, tzinfo=UTC))
        assert len(result.due) == 1
        assert result.due[0].scheduled_for_utc == datetime(2020, 1, 1, tzinfo=UTC)

    def test_occurrence_key_is_stable_for_same_schedule(self) -> None:
        schedule = self._schedule(datetime(2020, 1, 1, tzinfo=UTC))
        r1 = evaluate_one_shot(schedule, now=datetime(2026, 1, 1, tzinfo=UTC))
        r2 = evaluate_one_shot(schedule, now=datetime(2026, 6, 1, tzinfo=UTC))
        assert r1.due[0].occurrence_key == r2.due[0].occurrence_key

    def test_one_shot_has_no_local_cursor_concept(self) -> None:
        """ONE_SHOT never uses RRULE/local-civil-time evaluation, so it must
        never emit a cursor value at all -- past or future fire_at."""
        future = self._schedule(datetime(2030, 1, 1, tzinfo=UTC))
        past = self._schedule(datetime(2020, 1, 1, tzinfo=UTC))
        now = datetime(2026, 1, 1, tzinfo=UTC)
        assert evaluate_one_shot(future, now=now).new_last_cursor_local is None
        assert evaluate_one_shot(past, now=now).new_last_cursor_local is None


class TestRecurringDailyOrdinary:
    def test_daily_recurrence_fires_once_per_day(self) -> None:
        # starts_at (== initial cursor) is exclusive, so with no prior firing
        # only June 2 09:00 falls strictly between June 1 09:00 and June 3 08:00.
        schedule = _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0))
        result = evaluate_recurring(schedule, now=datetime(2026, 6, 3, 8, 0, 0, tzinfo=PARIS))
        assert len(result.due) == 1

    def test_no_occurrence_before_first_start(self) -> None:
        schedule = _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0))
        result = evaluate_recurring(schedule, now=datetime(2026, 5, 30, tzinfo=PARIS))
        assert result.due == ()

    def test_next_fire_at_points_to_next_occurrence(self) -> None:
        schedule = _recurring(
            starts_at=datetime(2026, 6, 1, 9, 0, 0),
            last_cursor_local=datetime(2026, 6, 1, 9, 0, 0),
        )
        result = evaluate_recurring(schedule, now=datetime(2026, 6, 1, 10, 0, 0, tzinfo=PARIS))
        assert result.next_fire_at_utc is not None
        assert result.next_fire_at_utc.astimezone(PARIS).replace(tzinfo=None) == datetime(
            2026, 6, 2, 9, 0, 0
        )

    def test_occurrence_key_stable_across_restarts(self) -> None:
        schedule = _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0))
        r1 = evaluate_recurring(schedule, now=datetime(2026, 6, 2, 10, 0, 0, tzinfo=PARIS))
        r2 = evaluate_recurring(schedule, now=datetime(2026, 6, 2, 10, 0, 0, tzinfo=PARIS))
        assert [o.occurrence_key for o in r1.due] == [o.occurrence_key for o in r2.due]


class TestRecurringDstBehavior:
    def test_daily_9am_survives_spring_forward_transition(self) -> None:
        """A 09:00 daily recurrence is never in the DST gap (which starts at
        02:00 local), so it must keep firing normally through the
        transition -- no occurrence dropped, no duplicate."""
        schedule = _recurring(
            starts_at=datetime(2026, 3, 27, 9, 0, 0),
            catch_up_bound=10,
        )
        result = evaluate_recurring(schedule, now=datetime(2026, 3, 31, 12, 0, 0, tzinfo=PARIS))
        local_times = [o.scheduled_for_utc.astimezone(PARIS).hour for o in result.due]
        assert local_times == [9, 9, 9, 9]  # Mar 27, 28, 29 (transition day), 30

    def test_recurrence_landing_in_spring_forward_gap_is_skipped(self) -> None:
        schedule = _recurring(
            rrule="FREQ=DAILY",
            starts_at=datetime(2026, 3, 28, 2, 30, 0),
            dst_nonexistent_policy=DstNonexistentPolicy.SKIP,
            catch_up_bound=10,
        )
        result = evaluate_recurring(schedule, now=datetime(2026, 3, 30, 12, 0, 0, tzinfo=PARIS))
        # starts_at (Mar 28) is the exclusive cursor; Mar 29 02:30 does not
        # exist (DST gap) and is skipped, leaving only Mar 30 02:30 due.
        assert len(result.due) == 1

    def test_recurrence_landing_in_fall_back_duplicate_fires_once(self) -> None:
        """A naive implementation using local-time equality could double-fire
        on the repeated hour; the deterministic policy must always pick
        exactly one of the two real instants."""
        schedule = _recurring(
            rrule="FREQ=DAILY",
            starts_at=datetime(2026, 10, 20, 2, 30, 0),
            dst_ambiguous_policy=DstAmbiguousPolicy.EARLIEST,
            catch_up_bound=10,
        )
        result = evaluate_recurring(schedule, now=datetime(2026, 10, 27, 12, 0, 0, tzinfo=PARIS))
        # Oct 20..26 = 7 occurrences, none duplicated despite Oct 25 being the
        # fall-back day.
        assert len(result.due) == 7
        assert len({o.scheduled_for_utc for o in result.due}) == 7


class TestMisfireCatchUp:
    def test_backlog_within_bound_fires_all(self) -> None:
        schedule = _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0), catch_up_bound=5)
        result = evaluate_recurring(schedule, now=datetime(2026, 6, 4, 10, 0, 0, tzinfo=PARIS))
        assert len(result.due) == 3  # within bound of 5

    def test_skip_missed_keeps_only_newest_within_bound(self) -> None:
        schedule = _recurring(
            starts_at=datetime(2026, 6, 1, 9, 0, 0),
            catch_up_bound=2,
            misfire_policy=MisfirePolicy.SKIP_MISSED,
        )
        # June 2..11 = 10 candidates (starts_at itself is the exclusive
        # cursor), only the newest 2 should fire.
        result = evaluate_recurring(schedule, now=datetime(2026, 6, 11, 10, 0, 0, tzinfo=PARIS))
        assert len(result.due) == 2
        days = sorted(o.scheduled_for_utc.astimezone(PARIS).day for o in result.due)
        assert days == [10, 11]

    def test_skip_missed_zero_bound_fires_nothing(self) -> None:
        schedule = _recurring(
            starts_at=datetime(2026, 6, 1, 9, 0, 0),
            catch_up_bound=0,
            misfire_policy=MisfirePolicy.SKIP_MISSED,
        )
        result = evaluate_recurring(schedule, now=datetime(2026, 6, 5, 10, 0, 0, tzinfo=PARIS))
        assert result.due == ()

    def test_fire_once_immediately_collapses_backlog_to_single_occurrence(self) -> None:
        schedule = _recurring(
            starts_at=datetime(2026, 6, 1, 9, 0, 0),
            catch_up_bound=2,
            misfire_policy=MisfirePolicy.FIRE_ONCE_IMMEDIATELY,
        )
        result = evaluate_recurring(schedule, now=datetime(2026, 6, 11, 10, 0, 0, tzinfo=PARIS))
        assert len(result.due) == 1
        assert result.due[0].scheduled_for_utc.astimezone(PARIS).day == 11

    def test_process_restart_does_not_duplicate_occurrences(self) -> None:
        """Simulates a scheduler restart: re-evaluating with the same
        last_cursor_local/now must produce the identical occurrence set (same
        keys), which is what backs the DB uniqueness constraint."""
        schedule = _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0), catch_up_bound=10)
        now = datetime(2026, 6, 5, 10, 0, 0, tzinfo=PARIS)
        first = evaluate_recurring(schedule, now=now)
        second = evaluate_recurring(schedule, now=now)
        assert [o.occurrence_key for o in first.due] == [o.occurrence_key for o in second.due]


class TestDispatch:
    def test_evaluate_schedule_dispatches_one_shot(self) -> None:
        schedule = CampaignSchedule(
            id=uuid4(),
            owner_discord_user_id=1,
            campaign_id=uuid4(),
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        result = evaluate_schedule(schedule, now=datetime(2026, 1, 1, tzinfo=UTC))
        assert len(result.due) == 1

    def test_immediate_schedule_is_rejected_from_cursor_evaluation(self) -> None:
        schedule = CampaignSchedule(
            id=uuid4(),
            owner_discord_user_id=1,
            campaign_id=uuid4(),
            schedule_kind=ScheduleKind.IMMEDIATE,
        )
        with pytest.raises(ScheduleEvaluationError):
            evaluate_schedule(schedule, now=datetime(2026, 1, 1, tzinfo=UTC))


class TestNaiveAwareCursorGuard:
    """External-review finding: message_campaign_schedules.last_cursor_at
    was previously TIMESTAMPTZ while evaluate_recurring() treated it as a
    naive local wall-clock value alongside starts_at. Both the domain
    constructor and evaluate_recurring() itself now refuse an aware value,
    defense-in-depth against a row that somehow got persisted wrong."""

    def test_domain_constructor_rejects_aware_starts_at(self) -> None:
        with pytest.raises(ValueError, match="naive local wall-clock"):
            _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0, tzinfo=PARIS))

    def test_domain_constructor_rejects_aware_last_cursor_local(self) -> None:
        with pytest.raises(ValueError, match="naive local wall-clock"):
            _recurring(
                starts_at=datetime(2026, 6, 1, 9, 0, 0),
                last_cursor_local=datetime(2026, 6, 1, 9, 0, 0, tzinfo=PARIS),
            )

    def test_evaluate_recurring_defends_against_a_corrupted_aware_cursor(self) -> None:
        """Simulates a row loaded from a legacy/corrupted source that
        bypassed the domain constructor -- evaluate_recurring() must still
        refuse to silently mix naive and aware datetimes."""
        schedule = _recurring(starts_at=datetime(2026, 6, 1, 9, 0, 0))
        object.__setattr__(
            schedule, "last_cursor_local", datetime(2026, 6, 1, 9, 0, 0, tzinfo=PARIS)
        )
        with pytest.raises(ScheduleEvaluationError, match="naive local wall-clock"):
            evaluate_recurring(schedule, now=datetime(2026, 6, 3, 8, 0, 0, tzinfo=PARIS))
