"""Unit tests for WP6: UNKNOWN_OUTCOME recovery decision logic.

The nonce-persistence/dedup facts this logic relies on are verified live
against the real Discord sandbox -- see
docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json -- this
file only tests the pure decision function.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from did.campaigns.delivery_reconciliation import (
    MAX_UNKNOWN_RETRY_ATTEMPTS,
    SAFE_RETRY_WINDOW,
    ReconciliationAction,
    decide_unknown_outcome_recovery,
    generate_delivery_nonce,
)

pytestmark = [pytest.mark.security]


class TestGenerateDeliveryNonce:
    def test_nonce_is_within_discord_length_limit(self) -> None:
        nonce = generate_delivery_nonce()
        assert len(nonce) <= 25

    def test_nonces_are_unique(self) -> None:
        nonces = {generate_delivery_nonce() for _ in range(1000)}
        assert len(nonces) == 1000


class TestDecideUnknownOutcomeRecovery:
    def test_recent_attempt_within_window_retries_with_same_nonce(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        decision = decide_unknown_outcome_recovery(
            attempted_at=now - timedelta(seconds=30), now=now, attempt_count=1
        )
        assert decision.action is ReconciliationAction.RETRY_WITH_SAME_NONCE

    def test_attempt_exactly_at_window_boundary_still_retries(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        decision = decide_unknown_outcome_recovery(
            attempted_at=now - SAFE_RETRY_WINDOW, now=now, attempt_count=1
        )
        assert decision.action is ReconciliationAction.RETRY_WITH_SAME_NONCE

    def test_attempt_past_window_requires_intervention(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        decision = decide_unknown_outcome_recovery(
            attempted_at=now - SAFE_RETRY_WINDOW - timedelta(seconds=1),
            now=now,
            attempt_count=1,
        )
        assert decision.action is ReconciliationAction.REQUIRE_INTERVENTION

    def test_too_many_ambiguous_attempts_requires_intervention_even_if_recent(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        decision = decide_unknown_outcome_recovery(
            attempted_at=now - timedelta(seconds=1),
            now=now,
            attempt_count=MAX_UNKNOWN_RETRY_ATTEMPTS + 1,
        )
        assert decision.action is ReconciliationAction.REQUIRE_INTERVENTION

    def test_attempt_count_at_bound_still_retries(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        decision = decide_unknown_outcome_recovery(
            attempted_at=now - timedelta(seconds=1),
            now=now,
            attempt_count=MAX_UNKNOWN_RETRY_ATTEMPTS,
        )
        assert decision.action is ReconciliationAction.RETRY_WITH_SAME_NONCE

    def test_decision_never_recommends_a_fresh_send(self) -> None:
        """There is no third action that starts a brand new nonce/attempt --
        recovery is always either retry-same-nonce or stop-and-escalate."""
        now = datetime(2026, 1, 1, tzinfo=UTC)
        for attempted_at in (now, now - timedelta(days=1)):
            for attempt_count in (0, 1, 10):
                decision = decide_unknown_outcome_recovery(
                    attempted_at=attempted_at, now=now, attempt_count=attempt_count
                )
                assert decision.action in (
                    ReconciliationAction.RETRY_WITH_SAME_NONCE,
                    ReconciliationAction.REQUIRE_INTERVENTION,
                )
