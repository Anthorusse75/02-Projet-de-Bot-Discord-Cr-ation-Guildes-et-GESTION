"""WP6: delivery nonce generation and ambiguous-send (UNKNOWN_OUTCOME) recovery.

The critical failure case this module exists for: Discord accepted a
message, the worker process crashed (or the connection reset) before the
SENT status committed locally. On restart the delivery is UNKNOWN. Never
blindly resend a fresh message -- but a *same-nonce* retry is safe, per two
live probes against the real Discord sandbox (see
``docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json``):

1. ``Message.nonce`` is populated only from the immediate send response
   (``data.get('nonce')`` in discord.py's ``Message.__init__``, unconditional
   on payload shape) -- it is empirically **absent** on both
   ``fetch_message()`` and ``history()`` results. History-lookup-by-nonce
   reconciliation does not work against the real API and is not used here.
2. ``discord.py==2.7.1`` does not expose Discord's ``enforce_nonce`` REST
   field at all (grepped the installed package source: zero occurrences of
   "enforce_nonce"). However, sending the identical ``nonce`` + identical
   content twice in immediate succession, live, returned the **same message
   id both times** with only one message actually created in the channel --
   Discord's default (non-``enforce_nonce``) dedup heuristic held for a
   near-immediate retry.

Recovery strategy: on UNKNOWN_OUTCOME, retry the send using the delivery's
already-stored ``discord_nonce`` and its stored ``content_snapshot`` --
never a freshly re-rendered payload, which could legitimately differ (e.g.
if glossary/translation state changed) and defeat Discord's content-based
dedup matching. Whatever message id that retry returns -- freshly created or
Discord-deduped back to the original -- is used directly as the delivery's
final ``discord_message_id``; the two cases are indistinguishable from the
response and do not need to be, since either way exactly one message now
exists with that content and that id.

Because Discord's default dedup window is undocumented/best-effort (that is
precisely the guarantee ``enforce_nonce`` exists to make strict), the retry
is only attempted automatically within a conservative, bounded time window
since the original attempt, and only for a bounded number of ambiguous
attempts. Beyond either bound, the delivery goes to INTERVENTION_REQUIRED
rather than risk sending an actual duplicate on a stale assumption.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


def generate_delivery_nonce() -> str:
    """A 25-character nonce: comfortably under Discord's 25-character nonce
    field limit, collision-resistant (128 bits of entropy)."""
    return secrets.token_hex(16)[:25]


#: Conservative and deliberately not empirically pushed further (that would
#: need an hours-long live test against an undocumented heuristic). Retries
#: within this window rely on Discord's default nonce dedup; beyond it,
#: INTERVENTION_REQUIRED is the safe default. Tune only from further live
#: evidence, never from assumption.
SAFE_RETRY_WINDOW = timedelta(minutes=5)

#: A same-nonce retry can itself end up UNKNOWN again (another crash/timeout
#: mid-retry); this bounds how many such ambiguous attempts are tolerated
#: before requiring a human rather than retrying forever.
MAX_UNKNOWN_RETRY_ATTEMPTS = 3


class ReconciliationAction(StrEnum):
    RETRY_WITH_SAME_NONCE = "RETRY_WITH_SAME_NONCE"
    REQUIRE_INTERVENTION = "REQUIRE_INTERVENTION"


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    action: ReconciliationAction
    reason: str


def decide_unknown_outcome_recovery(
    *, attempted_at: datetime, now: datetime, attempt_count: int
) -> ReconciliationDecision:
    if attempt_count > MAX_UNKNOWN_RETRY_ATTEMPTS:
        return ReconciliationDecision(
            ReconciliationAction.REQUIRE_INTERVENTION,
            f"{attempt_count} ambiguous attempts already made, "
            f"exceeds bound of {MAX_UNKNOWN_RETRY_ATTEMPTS}",
        )
    if now - attempted_at <= SAFE_RETRY_WINDOW:
        return ReconciliationDecision(
            ReconciliationAction.RETRY_WITH_SAME_NONCE,
            "within the safe nonce-dedup retry window",
        )
    return ReconciliationDecision(
        ReconciliationAction.REQUIRE_INTERVENTION,
        "outside the safe nonce-dedup retry window -- "
        "Discord's default dedup guarantee is unverified past this bound",
    )
