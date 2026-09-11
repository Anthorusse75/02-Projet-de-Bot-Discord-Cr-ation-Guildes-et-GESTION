"""REQ-MSG-019: delivery-history retention.

No canonical retention duration is defined anywhere in the product's
normative specifications (they reference "selon la politique de rétention"
without a number) -- this module therefore defines a conservative,
documented default and requires any override to be explicitly bounded,
never an arbitrary or unbounded destructive duration.

Scope is deliberately narrow: only ``message_deliveries`` rows in a
genuinely terminal state (``SENT``/``FAILED``) are ever purged by age.
PENDING/CLAIMED/SENDING/UNKNOWN/INTERVENTION_REQUIRED records are not
history yet -- an unresolved or ambiguous delivery is never removed by this
policy regardless of how old it is; see
``CampaignsRepository.purge_terminal_deliveries``. The product must not
become a general Discord conversation archive: this module (and the table
it purges) never held raw incoming Discord message content in the first
place -- only what the Campaign Engine itself created/sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from did.infrastructure.campaigns_repository import CampaignsRepository

#: Bounds on a configurable retention_days value -- never unbounded.
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650  # ~10 years: a generous, but still finite, ceiling.

#: No normative duration is specified anywhere in the product's own
#: requirements; this is a conservative, explicitly documented default a
#: caller may override (within MIN/MAX_RETENTION_DAYS) or disable entirely
#: (retention_days=None) -- e.g. for a legal/operational hold -- per
#: REQ-DATA-002's "documented retention/purge policy" requirement.
DEFAULT_RETENTION_DAYS = 90


class InvalidRetentionPolicy(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    #: None explicitly disables purge (retention held indefinitely) --
    #: never the same thing as "unset"/"default": a caller must pass None
    #: deliberately.
    retention_days: int | None = DEFAULT_RETENTION_DAYS

    def __post_init__(self) -> None:
        if self.retention_days is None:
            return
        if not MIN_RETENTION_DAYS <= self.retention_days <= MAX_RETENTION_DAYS:
            raise InvalidRetentionPolicy(
                f"retention_days must be between {MIN_RETENTION_DAYS} and "
                f"{MAX_RETENTION_DAYS}, or None to disable purge (got "
                f"{self.retention_days})"
            )

    def cutoff(self, *, now: datetime) -> datetime | None:
        """The instant before which a terminal delivery becomes eligible
        for purge -- ``None`` when purge is disabled."""
        if self.retention_days is None:
            return None
        return now - timedelta(days=self.retention_days)


async def purge_expired_deliveries(
    repository: CampaignsRepository,
    policy: RetentionPolicy,
    *,
    guild_id: int,
    now: datetime,
    limit: int = 1000,
) -> int:
    """Apply ``policy`` to one Guild's terminal deliveries. Returns 0
    (a safe no-op, not an error) when the policy disables purge."""
    cutoff = policy.cutoff(now=now)
    if cutoff is None:
        return 0
    return await repository.purge_terminal_deliveries(guild_id, cutoff=cutoff, limit=limit)
