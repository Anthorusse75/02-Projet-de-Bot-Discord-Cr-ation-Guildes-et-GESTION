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


def validate_condition_ast(node: object) -> None:
    """Raise if ``node`` uses any operator outside :class:`TriggerConditionOp`
    or is otherwise malformed. Call this before persisting a trigger.
    """
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
        if "path" not in node or not isinstance(node["path"], str) or not node["path"]:
            raise ConditionEvaluationError(f"{op} condition requires a non-empty 'path' string")
        if "value" not in node:
            raise ConditionEvaluationError(f"{op} condition requires a 'value'")
    elif op in (TriggerConditionOp.AND, TriggerConditionOp.OR):
        clauses = node.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            raise ConditionEvaluationError(f"{op} condition requires a non-empty 'clauses' list")
        for clause in clauses:
            validate_condition_ast(clause)
    elif op is TriggerConditionOp.NOT:
        if "clause" not in node:
            raise ConditionEvaluationError("NOT condition requires a 'clause'")
        validate_condition_ast(node["clause"])
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
    discord_resource_id: int | None
    causation_depth: int
    payload: Mapping[str, object]


def should_trigger(
    trigger: CampaignTrigger,
    source_bindings: Iterable[TriggerSourceBinding],
    context: TriggerEvaluationContext,
) -> bool:
    """The single REQ-MSG-027/030 gate: source authorization + depth bound +
    ancestor-loop guard + the allowlisted condition, all required.

    Exact-once *consumption* of a given (trigger_id, event_id) pair is
    additionally enforced by the ``message_campaign_trigger_consumptions``
    DB uniqueness constraint (WP1) -- this function is pure and does not
    itself guarantee idempotency across repeated calls.
    """
    if context.causation_depth > trigger.max_causation_depth:
        return False
    if str(trigger.campaign_id) in read_campaign_ancestry(context.payload):
        return False
    if not any(
        binding.matches(context.guild_id, context.discord_resource_id)
        for binding in source_bindings
    ):
        return False
    return evaluate_condition(trigger.condition_ast, context.payload)
