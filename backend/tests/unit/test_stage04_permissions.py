from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from itertools import permutations

import pytest

from did.api.stage04 import _decision_response
from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions import DEFAULT_PERMISSION_REGISTRY, PermissionEvaluator
from did.permissions.capabilities import (
    BotCapabilityChecker,
    BotOperation,
    CapabilityOutcome,
    hierarchy_diagnostic,
)
from did.permissions.models import DecisionStatus, PermissionOutcome, TraceStep
from did.permissions.views import (
    CategorySyncState,
    SimplePermissionConcept,
    category_sync_state,
    compile_simple_permissions,
    expert_model,
    simulate_overwrites,
    view_as_newcomer,
    view_as_role,
)

GUILD = 100
OWNER = 101
MEMBER = 102
ROLE_A = 200
ROLE_B = 201
CHANNEL = 300
THREAD = 301
NOW = datetime(2026, 8, 17, tzinfo=UTC)
REGISTRY = DEFAULT_PERMISSION_REGISTRY


def bits(*names: str) -> int:
    value = 0
    for name in names:
        value |= REGISTRY.value(name)
    return value


def freshness(state: FreshnessState = FreshnessState.FRESH, version: int = 1) -> FreshnessSnapshot:
    return FreshnessSnapshot(state, "GATEWAY", version, NOW, NOW, NOW)


def role(
    role_id: int,
    permissions: int,
    *,
    position: int = 1,
    managed: bool = False,
) -> RoleSnapshot:
    return RoleSnapshot(
        GUILD, role_id, f"role-{role_id}", position, permissions, managed, freshness()
    )


def overwrite(target_id: int, target_type: int, allow: int = 0, deny: int = 0) -> OverwriteSnapshot:
    return OverwriteSnapshot(GUILD, CHANNEL, target_id, target_type, allow, deny, NOW)


def channel(
    *overwrites: OverwriteSnapshot,
    channel_id: int = CHANNEL,
    channel_type: ChannelType = ChannelType.GUILD_TEXT,
    parent_id: int | None = None,
    complete: bool = True,
    observability: ObservabilityState = ObservabilityState.VISIBLE,
    state: FreshnessState = FreshnessState.FRESH,
    archived: bool | None = None,
    locked: bool | None = None,
) -> ChannelSnapshot:
    normalized = tuple(
        replace(item, channel_id=channel_id) if item.channel_id != channel_id else item
        for item in overwrites
    )
    return ChannelSnapshot(
        GUILD,
        channel_id,
        channel_type,
        1,
        parent_id,
        "resource",
        normalized,
        complete,
        observability,
        freshness(state),
        archived=archived,
        locked=locked,
    )


def guild(
    everyone_bits: int,
    *extra_roles: RoleSnapshot,
    channels: tuple[ChannelSnapshot, ...] = (),
    owner_id: int = OWNER,
    mode: CoverageMode = CoverageMode.FULL,
    state: FreshnessState = FreshnessState.FRESH,
    roles_complete: bool = True,
) -> GuildSnapshot:
    return GuildSnapshot(
        GUILD,
        owner_id,
        (role(GUILD, everyone_bits, position=0), *extra_roles),
        channels,
        CoverageSnapshot(
            GUILD,
            mode,
            state,
            "LOCAL_PROJECTION",
            1,
            known_channels=len(channels),
            visible_channels=len(channels),
            known_roles=1 + len(extra_roles),
            members_complete=True,
            overwrites_complete=True,
            threads_complete=True,
            gateway_continuity="CONNECTED",
        ),
        freshness(state),
        roles_complete=roles_complete,
        source_versions=("gateway:1", "projection:1"),
    )


def member(
    *role_ids: int,
    user_id: int = MEMBER,
    complete: bool = True,
    state: FreshnessState = FreshnessState.FRESH,
    private_threads: frozenset[int] = frozenset(),
    private_complete: bool = True,
) -> MemberSnapshot:
    return MemberSnapshot(
        GUILD,
        user_id,
        role_ids,
        complete,
        freshness(state),
        private_thread_memberships=private_threads,
        private_thread_memberships_complete=private_complete,
    )


def evaluate(
    snapshot: GuildSnapshot,
    subject: MemberSnapshot,
    resource: ChannelSnapshot | None = None,
    *,
    parent: ChannelSnapshot | None = None,
    requested: str | None = None,
):
    return PermissionEvaluator().evaluate(
        guild=snapshot,
        member=subject,
        resource=resource,
        parent=parent,
        requested_permission=requested,
    )


@pytest.mark.parametrize(
    ("everyone", "roles", "expected"),
    [
        (bits("VIEW_CHANNEL"), (), bits("VIEW_CHANNEL")),
        (0, (role(ROLE_A, bits("VIEW_CHANNEL")),), bits("VIEW_CHANNEL")),
        (
            bits("VIEW_CHANNEL"),
            (role(ROLE_A, bits("SEND_MESSAGES")), role(ROLE_B, bits("EMBED_LINKS"))),
            bits("VIEW_CHANNEL", "SEND_MESSAGES", "EMBED_LINKS"),
        ),
    ],
)
def test_official_base_permission_vectors(
    everyone: int, roles: tuple[RoleSnapshot, ...], expected: int
) -> None:
    decision = evaluate(guild(everyone, *roles), member(*(item.role_id for item in roles)))

    assert decision.calculated_bits == expected
    assert decision.effective_bits == expected
    assert decision.status is DecisionStatus.COMPLETE
    assert decision.trace[0].step is TraceStep.BASE_EVERYONE
    assert decision.trace[-1].after == decision.effective_bits


@pytest.mark.parametrize("administrator_source", ["everyone", "role"])
def test_administrator_bypasses_all_channel_and_member_denies(
    administrator_source: str,
) -> None:
    admin = bits("ADMINISTRATOR")
    everyone_bits = admin if administrator_source == "everyone" else 0
    extra = (role(ROLE_A, admin),) if administrator_source == "role" else ()
    subject = member(*(item.role_id for item in extra))
    resource = channel(
        overwrite(GUILD, 0, deny=REGISTRY.known_mask),
        overwrite(subject.user_id, 1, deny=REGISTRY.known_mask),
    )

    decision = evaluate(guild(everyone_bits, *extra), subject, resource)

    assert decision.calculated_bits == REGISTRY.known_mask
    assert decision.effective_bits & bits("VIEW_CHANNEL")
    assert not decision.effective_bits & bits("SPEAK")
    assert TraceStep.ADMINISTRATOR_BYPASS in {entry.step for entry in decision.trace}
    assert TraceStep.EVERYONE_OVERWRITE_DENY not in {entry.step for entry in decision.trace}
    assert "permissions.warning.administratorBypassesOverwrites" in decision.warnings


def test_owner_bypass_is_distinct_from_administrator() -> None:
    resource = channel(overwrite(GUILD, 0, deny=REGISTRY.known_mask))
    decision = evaluate(guild(0), member(user_id=OWNER), resource)

    assert decision.calculated_bits == REGISTRY.known_mask
    assert decision.effective_bits & bits("VIEW_CHANNEL")
    assert TraceStep.OWNER_BYPASS in {entry.step for entry in decision.trace}
    assert TraceStep.ADMINISTRATOR_BYPASS not in {entry.step for entry in decision.trace}


def test_official_overwrite_order_and_role_collision_allow_wins() -> None:
    view = bits("VIEW_CHANNEL")
    resource = channel(
        overwrite(GUILD, 0, allow=view),
        overwrite(ROLE_A, 0, deny=view),
        overwrite(ROLE_B, 0, allow=view),
        overwrite(MEMBER, 1, deny=view),
    )
    snapshot = guild(0, role(ROLE_A, 0), role(ROLE_B, 0))

    role_only = evaluate(snapshot, member(ROLE_A, ROLE_B, user_id=999), resource)
    with_member_deny = evaluate(snapshot, member(ROLE_A, ROLE_B), resource)
    member_allow = evaluate(
        snapshot,
        member(ROLE_A, ROLE_B),
        replace(
            resource,
            overwrites=(*resource.overwrites[:-1], overwrite(MEMBER, 1, allow=view)),
        ),
    )

    assert role_only.calculated_bits & view
    assert not with_member_deny.calculated_bits & view
    assert member_allow.calculated_bits & view
    assert [entry.step for entry in role_only.trace][-2:] == [
        TraceStep.ROLE_OVERWRITES_DENY_AGGREGATE,
        TraceStep.ROLE_OVERWRITES_ALLOW_AGGREGATE,
    ]


def test_role_and_overwrite_permutations_are_commutative() -> None:
    flags = (bits("VIEW_CHANNEL"), bits("SEND_MESSAGES"), bits("EMBED_LINKS"))
    roles = tuple(role(ROLE_A + index, value) for index, value in enumerate(flags))
    overwrites = tuple(
        overwrite(item.role_id, 0, allow=flags[index], deny=flags[(index + 1) % 3])
        for index, item in enumerate(roles)
    )
    results: set[int] = set()
    for role_order in permutations(roles):
        for overwrite_order in permutations(overwrites):
            snapshot = guild(0, *role_order)
            results.add(
                evaluate(
                    snapshot,
                    member(*(item.role_id for item in role_order)),
                    channel(*overwrite_order),
                ).calculated_bits
            )
    assert len(results) == 1


def test_implicit_view_send_and_connect_keep_calculated_bits_visible() -> None:
    send_dependents = bits("SEND_TTS_MESSAGES", "MENTION_EVERYONE", "ATTACH_FILES", "EMBED_LINKS")
    text_calculated = bits("SEND_MESSAGES") | send_dependents
    hidden = evaluate(guild(text_calculated), member(), channel())
    assert hidden.calculated_bits == text_calculated
    assert hidden.effective_bits == 0
    assert hidden.implicit_denials[0].missing_permission == "VIEW_CHANNEL"

    no_send = evaluate(guild(bits("VIEW_CHANNEL") | send_dependents), member(), channel())
    assert no_send.calculated_bits & send_dependents == send_dependents
    assert no_send.effective_bits & send_dependents == 0
    assert any(item.missing_permission == "SEND_MESSAGES" for item in no_send.implicit_denials)

    voice = channel(channel_type=ChannelType.GUILD_VOICE)
    no_connect = evaluate(guild(bits("VIEW_CHANNEL", "SPEAK", "STREAM")), member(), voice)
    assert no_connect.calculated_bits & bits("SPEAK", "STREAM")
    assert not no_connect.effective_bits & bits("SPEAK", "STREAM")


def test_thread_inherits_parent_and_requires_thread_send_permission() -> None:
    parent = channel(overwrite(GUILD, 0, allow=bits("VIEW_CHANNEL", "SEND_MESSAGES_IN_THREADS")))
    thread = channel(
        channel_id=THREAD,
        channel_type=ChannelType.PUBLIC_THREAD,
        parent_id=CHANNEL,
    )
    snapshot = guild(0, channels=(parent, thread))

    decision = evaluate(snapshot, member(), thread, parent=parent)

    assert decision.effective_bits & bits("VIEW_CHANNEL", "SEND_MESSAGES_IN_THREADS")
    assert not decision.effective_bits & bits("SEND_MESSAGES")
    assert TraceStep.THREAD_INHERITANCE in {entry.step for entry in decision.trace}


def test_private_thread_membership_is_fail_safe_and_manage_threads_bypasses_membership() -> None:
    parent = channel()
    thread = channel(
        channel_id=THREAD,
        channel_type=ChannelType.PRIVATE_THREAD,
        parent_id=CHANNEL,
    )
    base = bits("VIEW_CHANNEL", "SEND_MESSAGES_IN_THREADS")
    snapshot = guild(base, channels=(parent, thread))

    unknown = evaluate(snapshot, member(private_complete=False), thread, parent=parent)
    excluded = evaluate(snapshot, member(private_complete=True), thread, parent=parent)
    included = evaluate(
        snapshot,
        member(private_threads=frozenset({THREAD}), private_complete=True),
        thread,
        parent=parent,
    )
    moderator = evaluate(
        guild(base | bits("MANAGE_THREADS"), channels=(parent, thread)),
        member(private_complete=False),
        thread,
        parent=parent,
    )

    assert unknown.status is DecisionStatus.INCOMPLETE
    assert unknown.outcome is PermissionOutcome.UNKNOWN
    assert "permissions.private_thread_membership_unknown" in unknown.incomplete_reasons
    assert excluded.effective_bits == 0
    assert included.effective_bits & bits("VIEW_CHANNEL")
    assert moderator.status is DecisionStatus.COMPLETE


@pytest.mark.parametrize(
    ("resource", "member_state", "expected_reason"),
    [
        (
            channel(observability=ObservabilityState.ACCESS_LOST),
            FreshnessState.FRESH,
            "permissions.resource_not_currently_observable",
        ),
        (channel(complete=False), FreshnessState.FRESH, "permissions.overwrites_incomplete"),
        (channel(), FreshnessState.STALE, "coverage.member_roles_not_current"),
    ],
)
def test_missing_or_stale_inputs_never_claim_allow(
    resource: ChannelSnapshot, member_state: FreshnessState, expected_reason: str
) -> None:
    decision = evaluate(
        guild(bits("VIEW_CHANNEL")),
        member(state=member_state),
        resource,
        requested="VIEW_CHANNEL",
    )

    assert decision.status is DecisionStatus.INCOMPLETE
    assert decision.outcome is PermissionOutcome.UNKNOWN
    assert expected_reason in decision.incomplete_reasons


def test_unknown_role_and_missing_thread_parent_are_unknown_or_incomplete() -> None:
    unknown_role = evaluate(guild(bits("VIEW_CHANNEL")), member(999), requested="VIEW_CHANNEL")
    orphan = channel(
        channel_id=THREAD,
        channel_type=ChannelType.PUBLIC_THREAD,
        parent_id=CHANNEL,
    )
    missing_parent = evaluate(guild(bits("VIEW_CHANNEL")), member(), orphan)

    assert unknown_role.status is DecisionStatus.INCOMPLETE
    assert unknown_role.outcome is PermissionOutcome.UNKNOWN
    assert missing_parent.status is DecisionStatus.UNKNOWN


def test_unknown_future_channel_type_is_preserved_but_never_claimed_complete() -> None:
    future_channel = replace(channel(), channel_type=99)
    decision = evaluate(
        guild(bits("VIEW_CHANNEL")),
        member(),
        future_channel,
        requested="VIEW_CHANNEL",
    )
    assert decision.status is DecisionStatus.UNKNOWN
    assert decision.outcome is PermissionOutcome.UNKNOWN
    assert "permissions.channel_type_unknown" in decision.incomplete_reasons


def test_category_sync_compares_observed_overwrites_without_inventing_inheritance() -> None:
    common = overwrite(GUILD, 0, allow=bits("VIEW_CHANNEL"))
    category = channel(common, channel_id=400, channel_type=ChannelType.GUILD_CATEGORY)
    synced = channel(replace(common, channel_id=CHANNEL), parent_id=400)
    desynced = replace(synced, overwrites=())
    incomplete_category = replace(category, overwrites_complete=False)

    assert category_sync_state(synced, category) is CategorySyncState.SYNCED
    assert category_sync_state(desynced, category) is CategorySyncState.DESYNCED
    assert category_sync_state(synced, incomplete_category) is CategorySyncState.UNKNOWN


def test_unknown_future_bits_survive_engine_and_decimal_api_above_js_safe_integer() -> None:
    unknown = 1 << 80
    snapshot = guild(bits("VIEW_CHANNEL") | unknown)
    decision = evaluate(snapshot, member(), requested="VIEW_CHANNEL")
    payload = _decision_response(decision)

    assert decision.calculated_bits & unknown
    assert decision.unknown_bits == unknown
    assert REGISTRY.parse_api_bits(payload["calculated_bits"]) == decision.calculated_bits
    assert isinstance(payload["calculated_bits"], str)
    assert int(payload["calculated_bits"]) > 2**53


def test_view_as_modes_simple_expert_and_impact_are_pure() -> None:
    resource = channel()
    snapshot = guild(
        bits("VIEW_CHANNEL"),
        role(ROLE_A, bits("SEND_MESSAGES")),
        channels=(resource,),
    )
    as_role = view_as_role(snapshot, ROLE_A, freshness=freshness())
    newcomer = view_as_newcomer(snapshot, freshness=freshness())
    role_decision = evaluate(snapshot, as_role.member, resource)
    newcomer_decision = evaluate(snapshot, newcomer.member, resource)
    simple = compile_simple_permissions(
        (SimplePermissionConcept.VIEW, SimplePermissionConcept.WRITE)
    )
    expert = expert_model(role_decision, resource)
    proposed = (overwrite(GUILD, 0, deny=bits("VIEW_CHANNEL")),)
    impact = simulate_overwrites(
        evaluator=PermissionEvaluator(),
        guild=snapshot,
        channel=resource,
        subjects=(as_role.member, newcomer.member),
        proposed_overwrites=proposed,
    )

    assert as_role.synthetic and newcomer.synthetic
    assert as_role.member.user_id != snapshot.owner_id
    assert role_decision.calculated_bits & bits("SEND_MESSAGES")
    assert not newcomer_decision.calculated_bits & bits("SEND_MESSAGES")
    assert simple.allow_bits == bits("VIEW_CHANNEL", "SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS")
    assert expert.unknown_bits == 0
    assert impact.persisted is False
    assert len(impact.subjects) == 2
    assert all(item.removed_effective_bits & bits("VIEW_CHANNEL") for item in impact.subjects)


def test_capability_checker_separates_hierarchy_and_never_recommends_administrator() -> None:
    bot_role = role(ROLE_A, bits("MANAGE_ROLES"), position=5)
    lower = role(ROLE_B, 0, position=4)
    equal_above = role(199, 0, position=5)
    equal_below = role(202, 0, position=5)
    managed = role(203, 0, position=1, managed=True)
    snapshot = guild(0, bot_role, lower, equal_above, equal_below, managed)
    bot = member(ROLE_A)
    checker = BotCapabilityChecker()

    can = checker.check(
        operation=BotOperation.MANAGE_ROLE,
        guild=snapshot,
        bot=bot,
        target_role=lower,
    )
    cannot_equal = hierarchy_diagnostic(snapshot, bot, equal_above)
    can_equal = hierarchy_diagnostic(snapshot, bot, equal_below)
    cannot_managed = hierarchy_diagnostic(snapshot, bot, managed)
    missing = checker.check(
        operation=BotOperation.MANAGE_CHANNEL,
        guild=guild(0, role(ROLE_A, 0, position=5)),
        bot=bot,
    )

    assert can.outcome is CapabilityOutcome.CAN
    assert cannot_equal.outcome is CapabilityOutcome.CANNOT
    assert can_equal.outcome is CapabilityOutcome.CAN
    assert cannot_managed.reasons == ("capability.hierarchy.target_managed",)
    assert missing.outcome is CapabilityOutcome.CANNOT
    assert all("administrator" not in value for value in missing.remediations)


@pytest.mark.security
def test_cross_tenant_permission_inputs_are_rejected() -> None:
    foreign_member = replace(member(), guild_id=999)
    with pytest.raises(ValueError, match="tenant boundary"):
        evaluate(guild(0), foreign_member)
