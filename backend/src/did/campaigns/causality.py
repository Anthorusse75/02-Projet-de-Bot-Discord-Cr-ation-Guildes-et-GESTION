"""Event trigger causality: allowlisted condition AST, depth and ancestor
loop guards (WP3).

REQ-MSG-027/030: an ``event_type`` alone never authorizes a trigger --
:func:`should_trigger` requires an explicit :class:`TriggerSourceBinding`
match (see ``did.domain.campaigns``) in addition to the condition AST, the
causation-depth bound and the ancestor-loop check below. The condition AST
only ever walks a small allowlisted operator set (``did.domain.campaigns
.TriggerConditionOp``) against the event payload -- there is no code
execution path here, by construction: nothing in this module ever calls
``eval``/``exec``/``compile`` or imports a template engine.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from did.domain.campaigns import CampaignTrigger, TriggerConditionOp, TriggerSourceBinding

#: Key inside an EventEnvelope's ``payload`` dict carrying the set of
#: campaign ids that causally contributed to this event. Deliberately stored
#: in the existing generic payload rather than adding a field to the shared
#: Stage03 EventEnvelope -- campaign ancestry is a Stage09-specific concern.
ANCESTRY_PAYLOAD_KEY = "did_campaign_ancestry"


class ConditionEvaluationError(ValueError):
    pass


def read_campaign_ancestry(payload: Mapping[str, object]) -> frozenset[str]:
    raw = payload.get(ANCESTRY_PAYLOAD_KEY, ())
    if not isinstance(raw, list | tuple | set | frozenset):
        return frozenset()
    return frozenset(str(item) for item in raw)


def with_campaign_ancestry(payload: Mapping[str, object], campaign_id: UUID) -> dict[str, object]:
    """Return a new payload tagging ``campaign_id`` as a causal ancestor.

    Every event a campaign delivery/occurrence emits (WP13's outbox publish)
    must be built through this so a downstream trigger bound to the *same*
    campaign can detect and refuse an ancestor loop.
    """
    updated = frozenset(read_campaign_ancestry(payload) | {str(campaign_id)})
    return {**payload, ANCESTRY_PAYLOAD_KEY: sorted(updated)}


def _resolve_path(payload: Mapping[str, object], path: str) -> object:
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


#: Pathological-input bounds (WP3 remediation): a stored condition AST can
#: never grow unbounded, regardless of who authored it.
MAX_CONDITION_AST_DEPTH = 10
MAX_CONDITION_AST_NODES = 100
MAX_CONDITION_CLAUSES_PER_NODE = 20
MAX_CONDITION_PATH_LENGTH = 200
MAX_CONDITION_VALUE_STRING_LENGTH = 2000


def validate_condition_ast(node: object) -> None:
    """Raise if ``node`` uses any operator outside :class:`TriggerConditionOp`,
    is otherwise malformed, or exceeds the pathological-input bounds above
    (depth/node count/clause count/path or value size). Call this before
    persisting a trigger -- it must be impossible for an invalid or
    oversized AST to reach durable state through the canonical create/update
    path.
    """
    _validate_condition_ast(node, depth=1, node_count=[0])


def _validate_condition_ast(node: object, *, depth: int, node_count: list[int]) -> None:
    if depth > MAX_CONDITION_AST_DEPTH:
        raise ConditionEvaluationError(
            f"condition AST exceeds maximum depth of {MAX_CONDITION_AST_DEPTH}"
        )
    node_count[0] += 1
    if node_count[0] > MAX_CONDITION_AST_NODES:
        raise ConditionEvaluationError(
            f"condition AST exceeds maximum node count of {MAX_CONDITION_AST_NODES}"
        )

    if not isinstance(node, dict) or "op" not in node:
        raise ConditionEvaluationError("condition node must be an object with an 'op' key")
    try:
        op = TriggerConditionOp(node["op"])
    except ValueError as exc:
        raise ConditionEvaluationError(f"disallowed condition operator: {node['op']!r}") from exc

    comparison_ops = (
        TriggerConditionOp.EQUALS,
        TriggerConditionOp.NOT_EQUALS,
        TriggerConditionOp.CONTAINS,
    )
    if op in comparison_ops:
        path = node.get("path")
        if not isinstance(path, str) or not path:
            raise ConditionEvaluationError(f"{op} condition requires a non-empty 'path' string")
        if len(path) > MAX_CONDITION_PATH_LENGTH:
            raise ConditionEvaluationError(
                f"{op} condition 'path' exceeds {MAX_CONDITION_PATH_LENGTH} characters"
            )
        if "value" not in node:
            raise ConditionEvaluationError(f"{op} condition requires a 'value'")
        value = node["value"]
        if isinstance(value, str) and len(value) > MAX_CONDITION_VALUE_STRING_LENGTH:
            raise ConditionEvaluationError(
                f"{op} condition 'value' exceeds {MAX_CONDITION_VALUE_STRING_LENGTH} characters"
            )
    elif op in (TriggerConditionOp.AND, TriggerConditionOp.OR):
        clauses = node.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            raise ConditionEvaluationError(f"{op} condition requires a non-empty 'clauses' list")
        if len(clauses) > MAX_CONDITION_CLAUSES_PER_NODE:
            raise ConditionEvaluationError(
                f"{op} condition exceeds {MAX_CONDITION_CLAUSES_PER_NODE} clauses"
            )
        for clause in clauses:
            _validate_condition_ast(clause, depth=depth + 1, node_count=node_count)
    elif op is TriggerConditionOp.NOT:
        if "clause" not in node:
            raise ConditionEvaluationError("NOT condition requires a 'clause'")
        _validate_condition_ast(node["clause"], depth=depth + 1, node_count=node_count)
    # ALWAYS: no further shape to validate.


def evaluate_condition(node: Mapping[str, object], payload: Mapping[str, object]) -> bool:
    """Evaluate an already-validated condition AST. Never executes code."""
    raw_op = node["op"]
    assert isinstance(raw_op, str)
    op = TriggerConditionOp(raw_op)

    if op is TriggerConditionOp.ALWAYS:
        return True
    comparison_ops = (
        TriggerConditionOp.EQUALS,
        TriggerConditionOp.NOT_EQUALS,
        TriggerConditionOp.CONTAINS,
    )
    if op in comparison_ops:
        path = node["path"]
        assert isinstance(path, str)
        actual = _resolve_path(payload, path)
        expected = node["value"]
        if op is TriggerConditionOp.EQUALS:
            return actual == expected
        if op is TriggerConditionOp.NOT_EQUALS:
            return actual != expected
        # CONTAINS
        if isinstance(actual, str):
            return isinstance(expected, str) and expected in actual
        if isinstance(actual, list | tuple | set | frozenset):
            return expected in actual
        return False
    if op is TriggerConditionOp.AND:
        clauses = node["clauses"]
        assert isinstance(clauses, list)
        return all(evaluate_condition(clause, payload) for clause in clauses)
    if op is TriggerConditionOp.OR:
        clauses = node["clauses"]
        assert isinstance(clauses, list)
        return any(evaluate_condition(clause, payload) for clause in clauses)
    if op is TriggerConditionOp.NOT:
        clause = node["clause"]
        assert isinstance(clause, dict)
        return not evaluate_condition(clause, payload)
    raise ConditionEvaluationError(f"disallowed condition operator: {op}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class TriggerEvaluationContext:
    event_id: UUID
    guild_id: int
    #: The real Gateway dispatch type of the event being evaluated (e.g.
    #: "GUILD_MEMBER_ADD"). REQ-MSG-027 external-review finding: an
    #: event_type mismatch must be rejected here, not merely assumed
    #: pre-filtered by the caller -- a trigger configured for event_type X
    #: must never fire off an event of a different type Y just because a
    #: source binding and condition AST happen to match its payload shape.
    event_type: str
    discord_resource_id: int | None
    causation_depth: int
    payload: Mapping[str, object]
    #: REQ-MSG-020 runtime fail-closed gate: whether raw Discord message
    #: content was actually captured/available for the event this context
    #: represents (e.g. the MESSAGE_CONTENT privileged intent was enabled
    #: and active for this Guild at the moment the event was received).
    #: Defaults to True since most events/triggers never care -- only a
    #: trigger that itself declares ``requires_message_content=True`` ever
    #: consults this field.
    message_content_available: bool = True


def should_trigger(
    trigger: CampaignTrigger,
    source_bindings: Iterable[TriggerSourceBinding],
    context: TriggerEvaluationContext,
) -> bool:
    """The single REQ-MSG-027/030 gate: source authorization + depth bound +
    ancestor-loop guard + the allowlisted condition, all required.

    REQ-MSG-020 fail-closed addition: a trigger that declares
    ``requires_message_content=True`` never even reaches condition
    evaluation when ``context.message_content_available`` is False -- the
    condition AST could reference message-content fields that are simply
    absent from ``context.payload`` in that case, and evaluating it as if
    they were merely "not equal"/"not containing" would be a silent
    correctness failure, not a safe default. This is purely a runtime
    consumer-side gate; it never toggles any Discord-facing intent itself.

    Exact-once *consumption* of a given (trigger_id, event_id) pair is
    additionally enforced by the ``message_campaign_trigger_consumptions``
    DB uniqueness constraint (WP1) -- this function is pure and does not
    itself guarantee idempotency across repeated calls.
    """
    if trigger.event_type != context.event_type:
        return False
    if context.causation_depth > trigger.max_causation_depth:
        return False
    if str(trigger.campaign_id) in read_campaign_ancestry(context.payload):
        return False
    if not any(
        binding.matches(context.guild_id, context.discord_resource_id)
        for binding in source_bindings
    ):
        return False
    if trigger.requires_message_content and not context.message_content_available:
        return False
    return evaluate_condition(trigger.condition_ast, context.payload)
