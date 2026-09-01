"""Stage 09 domain: campaign lifecycle, schedule, triggers, targets and deliveries.

Every entity here follows the Stage 08 convention: frozen/slotted dataclasses
with ``__post_init__`` validation, pure ``with_*``/transition methods instead
of in-place mutation, and a ``logical_*`` stable identity where reconciliation
across Discord-side recreation matters. Campaign headers are Control-Plane
scoped (``owner_discord_user_id``, no ``guild_id``); everything that can
authorize or mutate a specific Guild (targets, trigger source bindings, event
dedup, deliveries) carries ``guild_id`` and is RLS-protected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PublicationMode(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    ONE_SHOT_DEFERRED = "ONE_SHOT_DEFERRED"
    RECURRING = "RECURRING"
    EVENT_TRIGGERED = "EVENT_TRIGGERED"


class LifecycleStatus(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED_ARMED = "SCHEDULED_ARMED"
    ACTIVE_RUNNING = "ACTIVE_RUNNING"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED_INTERVENTION = "FAILED_INTERVENTION"


#: Explicit allowed lifecycle transitions. Anything not listed here is
#: rejected by :meth:`MessageCampaign.transition_to` regardless of caller
#: intent -- there is no implicit/boolean campaign state.
_ALLOWED_TRANSITIONS: dict[LifecycleStatus, frozenset[LifecycleStatus]] = {
    LifecycleStatus.DRAFT: frozenset(
        {LifecycleStatus.SCHEDULED_ARMED, LifecycleStatus.ACTIVE_RUNNING, LifecycleStatus.CANCELLED}
    ),
    LifecycleStatus.SCHEDULED_ARMED: frozenset(
        {LifecycleStatus.ACTIVE_RUNNING, LifecycleStatus.PAUSED, LifecycleStatus.CANCELLED}
    ),
    LifecycleStatus.ACTIVE_RUNNING: frozenset(
        {
            LifecycleStatus.PAUSED,
            LifecycleStatus.CANCELLED,
            LifecycleStatus.COMPLETED,
            LifecycleStatus.FAILED_INTERVENTION,
        }
    ),
    LifecycleStatus.PAUSED: frozenset(
        {LifecycleStatus.ACTIVE_RUNNING, LifecycleStatus.SCHEDULED_ARMED, LifecycleStatus.CANCELLED}
    ),
    LifecycleStatus.CANCELLED: frozenset(),
    LifecycleStatus.COMPLETED: frozenset(),
    LifecycleStatus.FAILED_INTERVENTION: frozenset(
        {LifecycleStatus.ACTIVE_RUNNING, LifecycleStatus.CANCELLED}
    ),
}


class CampaignLifecycleError(ValueError):
    """Raised when a requested lifecycle transition is not allowed."""


class AttachmentPolicy(StrEnum):
    PRESERVE_EXISTING = "PRESERVE_EXISTING"
    REPLACE_ALL = "REPLACE_ALL"
    REMOVE_ALL = "REMOVE_ALL"


@dataclass(frozen=True, slots=True)
class MessageCampaign:
    id: UUID
    owner_discord_user_id: int
    logical_campaign_key: str
    name: str
    source_language_code: str
    message_model: dict[str, object]
    allowed_mentions_policy: dict[str, object]
    publication_mode: PublicationMode
    attachment_policy: AttachmentPolicy = AttachmentPolicy.PRESERVE_EXISTING
    lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.owner_discord_user_id <= 0:
            raise ValueError("owner_discord_user_id must be a positive Discord snowflake")
        if not self.name.strip():
            raise ValueError("campaign name must not be blank")
        if not self.source_language_code.strip():
            raise ValueError("source_language_code must not be blank")
        if self.version <= 0:
            raise ValueError("version must be positive")

    def transition_to(self, target: LifecycleStatus) -> MessageCampaign:
        """Return a new campaign moved to ``target``, or raise if disallowed.

        REQ-MSG-002/003: campaign state is an explicit enum with CAS
        (``version`` incremented on every accepted transition), never an
        ambiguous boolean combination.
        """
        allowed = _ALLOWED_TRANSITIONS[self.lifecycle_status]
        if target not in allowed:
            raise CampaignLifecycleError(
                f"cannot transition campaign from {self.lifecycle_status} to {target}"
            )
        from dataclasses import replace

        return replace(self, lifecycle_status=target, version=self.version + 1)


class ScheduleKind(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    ONE_SHOT = "ONE_SHOT"
    RECURRING = "RECURRING"


class MisfirePolicy(StrEnum):
    SKIP_MISSED = "SKIP_MISSED"
    FIRE_ONCE_IMMEDIATELY = "FIRE_ONCE_IMMEDIATELY"


class DstNonexistentPolicy(StrEnum):
    """Spring-forward: a wall-clock time that never occurs that day."""

    SHIFT_FORWARD = "SHIFT_FORWARD"
    SKIP = "SKIP"


class DstAmbiguousPolicy(StrEnum):
    """Fall-back: a wall-clock time that occurs twice that day."""

    EARLIEST = "EARLIEST"
    LATEST = "LATEST"


@dataclass(frozen=True, slots=True)
class CampaignSchedule:
    id: UUID
    owner_discord_user_id: int
    campaign_id: UUID
    schedule_kind: ScheduleKind
    fire_at: datetime | None = None
    rrule: str | None = None
    timezone: str | None = None
    starts_at: datetime | None = None
    misfire_policy: MisfirePolicy = MisfirePolicy.SKIP_MISSED
    dst_nonexistent_policy: DstNonexistentPolicy = DstNonexistentPolicy.SHIFT_FORWARD
    dst_ambiguous_policy: DstAmbiguousPolicy = DstAmbiguousPolicy.EARLIEST
    catch_up_bound: int = 1
    next_fire_at: datetime | None = None
    #: Naive local wall-clock cursor (interpreted via the schedule's own
    #: `timezone`, exactly like `starts_at`) -- never timezone-aware. See
    #: did.campaigns.scheduling for why mixing naive/aware here is a real bug
    #: class, not a style preference.
    last_cursor_local: datetime | None = None
    occurrence_count: int = 0
    version: int = 1

    def __post_init__(self) -> None:
        if self.owner_discord_user_id <= 0:
            raise ValueError("owner_discord_user_id must be positive")
        if self.schedule_kind is ScheduleKind.ONE_SHOT and self.fire_at is None:
            raise ValueError("ONE_SHOT schedule requires fire_at")
        if self.schedule_kind is ScheduleKind.RECURRING and (
            not self.rrule or not self.timezone or self.starts_at is None
        ):
            raise ValueError("RECURRING schedule requires rrule, timezone and starts_at")
        if not (0 <= self.catch_up_bound <= 50):
            raise ValueError("catch_up_bound must be between 0 and 50")
        if self.version <= 0:
            raise ValueError("version must be positive")
        if self.starts_at is not None and self.starts_at.tzinfo is not None:
            raise ValueError("starts_at must be a naive local wall-clock datetime")
        if self.last_cursor_local is not None and self.last_cursor_local.tzinfo is not None:
            raise ValueError("last_cursor_local must be a naive local wall-clock datetime")


class TriggerConditionOp(StrEnum):
    """Allowlisted condition AST operators. No arbitrary expression code."""

    ALWAYS = "ALWAYS"
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    CONTAINS = "CONTAINS"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


@dataclass(frozen=True, slots=True)
class CampaignTrigger:
    id: UUID
    owner_discord_user_id: int
    campaign_id: UUID
    event_type: str
    condition_ast: dict[str, object]
    max_causation_depth: int = 8
    version: int = 1
    #: REQ-MSG-020: explicit author declaration -- never inferred from
    #: event_type or the condition AST -- that this trigger's condition
    #: reads raw Discord message content (e.g. a "message contains X"
    #: check). Time-based/schedule-driven campaigns never set this; it is
    #: meaningful only for event-triggered campaigns. See
    #: did.campaigns.message_content_policy for the capability-blocker,
    #: simulation-warning and runtime fail-closed behavior this declaration
    #: drives -- declaring it here does not by itself enable
    #: MESSAGE_CONTENT anywhere.
    requires_message_content: bool = False

    def __post_init__(self) -> None:
        if self.owner_discord_user_id <= 0:
            raise ValueError("owner_discord_user_id must be positive")
        if not self.event_type.strip():
            raise ValueError("event_type must not be blank")
        if not (1 <= self.max_causation_depth <= 32):
            raise ValueError("max_causation_depth must be between 1 and 32")


class TriggerSourceScopeKind(StrEnum):
    GUILD = "GUILD"
    CHANNEL = "CHANNEL"
    CATEGORY = "CATEGORY"


@dataclass(frozen=True, slots=True)
class TriggerSourceBinding:
    """An explicit, per-Guild authorized source a trigger may react to.

    REQ-MSG-027/030: an ``event_type`` alone never authorizes a trigger. A
    campaign-side trigger only fires for an event whose ``guild_id`` (and,
    when scoped, ``discord_resource_id``) matches one of these rows for the
    triggering Guild.
    """

    id: UUID
    guild_id: int
    trigger_id: UUID
    source_scope_kind: TriggerSourceScopeKind
    discord_resource_id: int | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.source_scope_kind is TriggerSourceScopeKind.GUILD:
            if self.discord_resource_id is not None:
                raise ValueError("GUILD scope bindings must not carry a resource id")
        elif not self.discord_resource_id or self.discord_resource_id <= 0:
            raise ValueError("CHANNEL/CATEGORY scope bindings require a positive resource id")

    def matches(self, guild_id: int, discord_resource_id: int | None) -> bool:
        if guild_id != self.guild_id:
            return False
        if self.source_scope_kind is TriggerSourceScopeKind.GUILD:
            return True
        return discord_resource_id == self.discord_resource_id


class TargetKind(StrEnum):
    CHANNEL = "CHANNEL"
    TRANSLATION_GROUP = "TRANSLATION_GROUP"
    #: REQ-MSG-002: a Stage04 dashboard logical group -- reuses the
    #: existing Stage04 logical-group abstraction rather than inventing a
    #: parallel Discord hierarchy. Resolved to real, currently-existing
    #: channels at execution time by
    #: did.campaigns.logical_groups.expand_logical_group, never a cached
    #: snapshot from target-creation time.
    LOGICAL_GROUP = "LOGICAL_GROUP"


class TranslationPublicationMode(StrEnum):
    """WP12: how a Translation Group destination is published to.

    Never inferred -- the campaign author must pick one explicitly whenever
    ``target_kind`` is ``TRANSLATION_GROUP``.
    """

    SOURCE_ONLY = "SOURCE_ONLY"
    EXISTING_PROVIDER = "EXISTING_PROVIDER"
    DID_TRANSLATED_FANOUT = "DID_TRANSLATED_FANOUT"
    SELECTED_LANGUAGES = "SELECTED_LANGUAGES"


@dataclass(frozen=True, slots=True)
class CampaignTarget:
    id: UUID
    guild_id: int
    campaign_id: UUID
    target_kind: TargetKind
    discord_channel_id: int | None = None
    translation_group_id: UUID | None = None
    translation_publication_mode: TranslationPublicationMode | None = None
    selected_language_profile_ids: tuple[UUID, ...] = ()
    logical_group_id: UUID | None = None
    authorized_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.target_kind is TargetKind.CHANNEL:
            if not self.discord_channel_id or self.discord_channel_id <= 0:
                raise ValueError("CHANNEL target requires a positive discord_channel_id")
            if self.translation_group_id is not None:
                raise ValueError("CHANNEL target must not carry a translation_group_id")
            if self.logical_group_id is not None:
                raise ValueError("CHANNEL target must not carry a logical_group_id")
        elif self.target_kind is TargetKind.LOGICAL_GROUP:
            if self.logical_group_id is None:
                raise ValueError("LOGICAL_GROUP target requires logical_group_id")
            if self.discord_channel_id is not None:
                raise ValueError("LOGICAL_GROUP target must not carry discord_channel_id")
            if self.translation_group_id is not None:
                raise ValueError("LOGICAL_GROUP target must not carry a translation_group_id")
        else:
            if self.translation_group_id is None:
                raise ValueError("TRANSLATION_GROUP target requires translation_group_id")
            if self.discord_channel_id is not None:
                raise ValueError("TRANSLATION_GROUP target must not carry discord_channel_id")
            if self.logical_group_id is not None:
                raise ValueError("TRANSLATION_GROUP target must not carry a logical_group_id")
            if self.translation_publication_mode is None:
                raise ValueError("TRANSLATION_GROUP target requires an explicit publication mode")
            if (
                self.translation_publication_mode is TranslationPublicationMode.SELECTED_LANGUAGES
                and not self.selected_language_profile_ids
            ):
                raise ValueError("SELECTED_LANGUAGES publication requires at least one language")


class OccurrenceSource(StrEnum):
    SCHEDULE = "SCHEDULE"
    EVENT = "EVENT"


class OccurrenceStatus(StrEnum):
    PENDING_FANOUT = "PENDING_FANOUT"
    CLAIMED = "CLAIMED"
    FANNED_OUT = "FANNED_OUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class MessageOccurrence:
    id: UUID
    owner_discord_user_id: int
    campaign_id: UUID
    occurrence_key: str
    occurrence_source: OccurrenceSource
    scheduled_for: datetime | None = None
    source_event_id: UUID | None = None
    source_correlation_id: UUID | None = None
    #: REQ-MSG-030 producing side: the causation_depth of the event that
    #: caused this occurrence (0 for a SCHEDULE-sourced occurrence, which is
    #: its own causal root; the causing event's own causation_depth for an
    #: EVENT-sourced one). When this occurrence's own fan-out later sends a
    #: Discord message that re-enters ingestion, the resulting event's
    #: causation_depth must be this value + 1 -- durably carried here so
    #: that increment is still correct however long after fan-out the
    #: re-entrant Gateway event actually arrives.
    source_causation_depth: int = 0
    #: REQ-MSG-030 producing side: the full set of campaign ids that
    #: causally contributed to this occurrence -- always includes this
    #: occurrence's own campaign_id, plus (for an EVENT-sourced occurrence)
    #: every campaign already present in the causing event's own ancestry.
    #: This is the exact set that must be attached to any Discord message
    #: this occurrence's fan-out sends, so a later self/cross-campaign loop
    #: through that message is detected by
    #: did.campaigns.causality.should_trigger exactly as it would be for
    #: any other event -- never computed from scratch after the fact, since
    #: the causing event's own payload will typically no longer be
    #: available by then.
    source_ancestry: frozenset[str] = frozenset()
    status: OccurrenceStatus = OccurrenceStatus.PENDING_FANOUT

    def __post_init__(self) -> None:
        if self.owner_discord_user_id <= 0:
            raise ValueError("owner_discord_user_id must be positive")
        if not self.occurrence_key:
            raise ValueError("occurrence_key must not be blank")
        if self.occurrence_source is OccurrenceSource.SCHEDULE and self.scheduled_for is None:
            raise ValueError("SCHEDULE occurrences require scheduled_for")
        if self.source_causation_depth < 0:
            raise ValueError("source_causation_depth must not be negative")
        if self.occurrence_source is OccurrenceSource.EVENT and self.source_event_id is None:
            raise ValueError("EVENT occurrences require source_event_id")


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"
    #: The owned-delete product flow's terminal state (REQ-MSG owned
    #: delete/edit) -- reached only from SENT, via a real (or confirmed
    #: already-happened) Discord deletion; never a substitute for FAILED.
    DELETED = "DELETED"


#: A delivery never blindly resends once it has left PENDING/CLAIMED: an
#: UNKNOWN outcome only ever moves to INTERVENTION_REQUIRED (never back to
#: PENDING) unless reconciliation evidence proves the send did not happen.
_DELIVERY_TRANSITIONS: dict[DeliveryStatus, frozenset[DeliveryStatus]] = {
    DeliveryStatus.PENDING: frozenset({DeliveryStatus.CLAIMED}),
    DeliveryStatus.CLAIMED: frozenset({DeliveryStatus.SENDING, DeliveryStatus.PENDING}),
    DeliveryStatus.SENDING: frozenset(
        {DeliveryStatus.SENT, DeliveryStatus.FAILED, DeliveryStatus.UNKNOWN}
    ),
    DeliveryStatus.SENT: frozenset({DeliveryStatus.DELETED}),
    DeliveryStatus.FAILED: frozenset({DeliveryStatus.PENDING}),
    DeliveryStatus.UNKNOWN: frozenset(
        {DeliveryStatus.INTERVENTION_REQUIRED, DeliveryStatus.SENT, DeliveryStatus.FAILED}
    ),
    DeliveryStatus.INTERVENTION_REQUIRED: frozenset({DeliveryStatus.SENT, DeliveryStatus.FAILED}),
    DeliveryStatus.DELETED: frozenset(),
}


class DeliveryTransitionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MessageDelivery:
    id: UUID
    guild_id: int
    campaign_id: UUID
    occurrence_id: UUID
    target_id: UUID
    delivery_key: str
    discord_channel_id: int
    allowed_mentions_snapshot: dict[str, object]
    language_profile_id: UUID | None = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    discord_message_id: int | None = None
    discord_nonce: str | None = None
    content_snapshot: dict[str, object] | None = None
    attempt_count: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if not self.delivery_key:
            raise ValueError("delivery_key must not be blank")
        if self.discord_channel_id <= 0:
            raise ValueError("discord_channel_id must be positive")
        if self.attempt_count < 0:
            raise ValueError("attempt_count must not be negative")

    def transition_to(self, target: DeliveryStatus) -> MessageDelivery:
        allowed = _DELIVERY_TRANSITIONS[self.status]
        if target not in allowed:
            raise DeliveryTransitionError(
                f"cannot transition delivery from {self.status} to {target}"
            )
        from dataclasses import replace

        return replace(self, status=target)


class GlossaryScope(StrEnum):
    GLOBAL_USER = "GLOBAL_USER"
    GUILD = "GUILD"
    CAMPAIGN = "CAMPAIGN"


class GlossaryBehavior(StrEnum):
    DO_NOT_TRANSLATE = "DO_NOT_TRANSLATE"
    FORCED_TRANSLATION = "FORCED_TRANSLATION"


class GlossaryMatchMode(StrEnum):
    EXACT = "EXACT"
    CASE_INSENSITIVE = "CASE_INSENSITIVE"


#: Most specific first. CAMPAIGN is the "template" tier from REQ-MSG-014's
#: "par langue/scope/template" wording -- a campaign's own message content
#: is its template. GUILD sits between CAMPAIGN and GLOBAL_USER: a
#: Guild-wide vocabulary shared by every campaign targeting that Guild,
#: regardless of which of the owner's campaigns is asking.
_SCOPE_RANK: dict[GlossaryScope, int] = {
    GlossaryScope.CAMPAIGN: 2,
    GlossaryScope.GUILD: 1,
    GlossaryScope.GLOBAL_USER: 0,
}


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """A DO_NOT_TRANSLATE / FORCED_TRANSLATION term.

    Priority (most specific wins, see docs/90_handoffs/STAGE_09_HANDOFF.md):
    ``CAMPAIGN`` scope beats ``GUILD`` scope beats ``GLOBAL_USER`` scope;
    within a scope, an entry naming a specific ``target_language_code``
    beats a language-agnostic entry (``target_language_code is None``);
    ties broken by longest ``source_term`` match. Every entry is still
    authored by an owner (``owner_discord_user_id``, for authorship/audit),
    but a ``GUILD`` entry is *visible* under that Guild's RLS context (any
    of the Guild's authorized campaign owners), not only its author --
    see migration ``0024_stage_09`` for the dual-condition RLS policy.
    """

    id: UUID
    owner_discord_user_id: int
    scope_kind: GlossaryScope
    source_term: str
    behavior: GlossaryBehavior
    campaign_id: UUID | None = None
    guild_id: int | None = None
    target_language_code: str | None = None
    forced_translation: str | None = None
    match_mode: GlossaryMatchMode = GlossaryMatchMode.CASE_INSENSITIVE

    def __post_init__(self) -> None:
        if self.owner_discord_user_id <= 0:
            raise ValueError("owner_discord_user_id must be positive")
        if not self.source_term.strip():
            raise ValueError("source_term must not be blank")
        if self.scope_kind is GlossaryScope.CAMPAIGN:
            if self.campaign_id is None:
                raise ValueError("CAMPAIGN scope requires campaign_id")
            if self.guild_id is not None:
                raise ValueError("CAMPAIGN scope must not carry guild_id")
        elif self.scope_kind is GlossaryScope.GUILD:
            if self.guild_id is None or self.guild_id <= 0:
                raise ValueError("GUILD scope requires a positive guild_id")
            if self.campaign_id is not None:
                raise ValueError("GUILD scope must not carry campaign_id")
        else:  # GLOBAL_USER
            if self.campaign_id is not None or self.guild_id is not None:
                raise ValueError("GLOBAL_USER scope must not carry campaign_id or guild_id")
        if self.behavior is GlossaryBehavior.FORCED_TRANSLATION and not self.forced_translation:
            raise ValueError("FORCED_TRANSLATION requires forced_translation text")
        if self.behavior is GlossaryBehavior.DO_NOT_TRANSLATE and self.forced_translation:
            raise ValueError("DO_NOT_TRANSLATE must not carry forced_translation text")

    def specificity(self) -> tuple[int, int, int]:
        """Higher tuples win. Used to sort candidate matches deterministically."""
        language_rank = 1 if self.target_language_code is not None else 0
        return (_SCOPE_RANK[self.scope_kind], language_rank, len(self.source_term))


@dataclass(frozen=True, slots=True)
class ApprovedVariant:
    id: UUID
    owner_discord_user_id: int
    campaign_id: UUID
    target_language_code: str
    source_fingerprint: str
    localized_message_model: dict[str, object]
    approved_by_discord_user_id: int
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.owner_discord_user_id <= 0:
            raise ValueError("owner_discord_user_id must be positive")
        if not self.target_language_code.strip():
            raise ValueError("target_language_code must not be blank")
        if len(self.source_fingerprint) != 64:
            raise ValueError("source_fingerprint must be a 64-character hex digest")

    def is_stale_for(self, current_source_fingerprint: str) -> bool:
        """REQ-MSG-016/017: reuse only while the source fingerprint still matches."""
        return current_source_fingerprint != self.source_fingerprint
