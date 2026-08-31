"""Unit tests for WP3: allowlisted condition AST, causation depth bound and
ancestor-loop guard.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from did.campaigns.causality import (
    ConditionEvaluationError,
    TriggerEvaluationContext,
    evaluate_condition,
    read_campaign_ancestry,
    should_trigger,
    validate_condition_ast,
    with_campaign_ancestry,
)
from did.domain.campaigns import CampaignTrigger, TriggerSourceBinding, TriggerSourceScopeKind

pytestmark = [pytest.mark.security]


class TestConditionValidation:
    def test_always_is_valid(self) -> None:
        validate_condition_ast({"op": "ALWAYS"})

    def test_disallowed_operator_rejected(self) -> None:
        with pytest.raises(ConditionEvaluationError, match="disallowed"):
            validate_condition_ast({"op": "EXEC", "code": "os.system('rm -rf /')"})

    def test_equals_requires_path_and_value(self) -> None:
        with pytest.raises(ConditionEvaluationError, match="path"):
            validate_condition_ast({"op": "EQUALS", "value": 1})

    def test_nested_and_or_not_validated_recursively(self) -> None:
        validate_condition_ast(
            {
                "op": "AND",
                "clauses": [
                    {"op": "EQUALS", "path": "event_type", "value": "MESSAGE_CREATE"},
                    {"op": "NOT", "clause": {"op": "CONTAINS", "path": "tags", "value": "spam"}},
                ],
            }
        )

    def test_and_rejects_invalid_nested_clause(self) -> None:
        with pytest.raises(ConditionEvaluationError):
            validate_condition_ast({"op": "AND", "clauses": [{"op": "PYTHON_EVAL"}]})

    def test_and_requires_nonempty_clauses(self) -> None:
        with pytest.raises(ConditionEvaluationError, match="clauses"):
            validate_condition_ast({"op": "AND", "clauses": []})

    def test_not_a_dict_rejected(self) -> None:
        with pytest.raises(ConditionEvaluationError):
            validate_condition_ast("import os; os.system('x')")


class TestConditionEvaluation:
    def test_always_is_true(self) -> None:
        assert evaluate_condition({"op": "ALWAYS"}, {}) is True

    def test_equals_matches_path(self) -> None:
        payload = {"channel": {"id": "123"}}
        assert evaluate_condition({"op": "EQUALS", "path": "channel.id", "value": "123"}, payload)
        assert not evaluate_condition(
            {"op": "EQUALS", "path": "channel.id", "value": "999"}, payload
        )

    def test_missing_path_resolves_to_none(self) -> None:
        assert not evaluate_condition({"op": "EQUALS", "path": "a.b.c", "value": "x"}, {})

    def test_not_equals(self) -> None:
        assert evaluate_condition({"op": "NOT_EQUALS", "path": "x", "value": "a"}, {"x": "b"})

    def test_contains_on_string(self) -> None:
        assert evaluate_condition(
            {"op": "CONTAINS", "path": "content", "value": "launch"},
            {"content": "campaign launch today"},
        )

    def test_contains_on_list(self) -> None:
        assert evaluate_condition(
            {"op": "CONTAINS", "path": "roles", "value": "vip"}, {"roles": ["vip", "member"]}
        )

    def test_and_or_not_composition(self) -> None:
        ast = {
            "op": "AND",
            "clauses": [
                {"op": "EQUALS", "path": "kind", "value": "join"},
                {
                    "op": "OR",
                    "clauses": [
                        {"op": "EQUALS", "path": "tier", "value": "gold"},
                        {"op": "EQUALS", "path": "tier", "value": "platinum"},
                    ],
                },
                {"op": "NOT", "clause": {"op": "EQUALS", "path": "banned", "value": True}},
            ],
        }
        assert evaluate_condition(ast, {"kind": "join", "tier": "gold", "banned": False})
        assert not evaluate_condition(ast, {"kind": "join", "tier": "bronze", "banned": False})
        assert not evaluate_condition(ast, {"kind": "join", "tier": "gold", "banned": True})


class TestAncestryTagging:
    def test_fresh_payload_has_empty_ancestry(self) -> None:
        assert read_campaign_ancestry({}) == frozenset()

    def test_tagging_adds_campaign_to_ancestry(self) -> None:
        campaign_id = uuid4()
        payload = with_campaign_ancestry({}, campaign_id)
        assert str(campaign_id) in read_campaign_ancestry(payload)

    def test_tagging_is_cumulative_across_hops(self) -> None:
        a, b = uuid4(), uuid4()
        payload = with_campaign_ancestry({}, a)
        payload = with_campaign_ancestry(payload, b)
        ancestry = read_campaign_ancestry(payload)
        assert str(a) in ancestry
        assert str(b) in ancestry


class TestShouldTrigger:
    def _trigger(self, **overrides: object) -> CampaignTrigger:
        fields: dict[str, object] = dict(
            id=uuid4(),
            owner_discord_user_id=1,
            campaign_id=uuid4(),
            event_type="MEMBER_JOIN",
            condition_ast={"op": "ALWAYS"},
            max_causation_depth=8,
        )
        fields.update(overrides)
        return CampaignTrigger(**fields)  # type: ignore[arg-type]

    def _guild_binding(self, trigger_id: object, guild_id: int) -> TriggerSourceBinding:
        return TriggerSourceBinding(
            id=uuid4(),
            guild_id=guild_id,
            trigger_id=trigger_id,  # type: ignore[arg-type]
            source_scope_kind=TriggerSourceScopeKind.GUILD,
        )

    def test_authorized_guild_with_matching_condition_triggers(self) -> None:
        trigger = self._trigger()
        binding = self._guild_binding(trigger.id, 111)
        context = TriggerEvaluationContext(
            event_id=uuid4(), guild_id=111, discord_resource_id=None, causation_depth=0, payload={}
        )
        assert should_trigger(trigger, [binding], context) is True

    def test_unbound_guild_b_cannot_trigger_guild_a_campaign(self) -> None:
        trigger = self._trigger()
        binding = self._guild_binding(trigger.id, 111)
        context = TriggerEvaluationContext(
            event_id=uuid4(), guild_id=222, discord_resource_id=None, causation_depth=0, payload={}
        )
        assert should_trigger(trigger, [binding], context) is False

    def test_event_type_alone_never_authorizes_without_any_binding(self) -> None:
        trigger = self._trigger()
        context = TriggerEvaluationContext(
            event_id=uuid4(), guild_id=111, discord_resource_id=None, causation_depth=0, payload={}
        )
        assert should_trigger(trigger, [], context) is False

    def test_depth_beyond_max_is_blocked(self) -> None:
        trigger = self._trigger(max_causation_depth=2)
        binding = self._guild_binding(trigger.id, 111)
        context = TriggerEvaluationContext(
            event_id=uuid4(), guild_id=111, discord_resource_id=None, causation_depth=3, payload={}
        )
        assert should_trigger(trigger, [binding], context) is False

    def test_depth_at_max_is_allowed(self) -> None:
        trigger = self._trigger(max_causation_depth=2)
        binding = self._guild_binding(trigger.id, 111)
        context = TriggerEvaluationContext(
            event_id=uuid4(), guild_id=111, discord_resource_id=None, causation_depth=2, payload={}
        )
        assert should_trigger(trigger, [binding], context) is True

    def test_ancestor_loop_is_blocked(self) -> None:
        trigger = self._trigger()
        binding = self._guild_binding(trigger.id, 111)
        looping_payload = with_campaign_ancestry({}, trigger.campaign_id)
        context = TriggerEvaluationContext(
            event_id=uuid4(),
            guild_id=111,
            discord_resource_id=None,
            causation_depth=1,
            payload=looping_payload,
        )
        assert should_trigger(trigger, [binding], context) is False

    def test_different_campaign_ancestry_does_not_block(self) -> None:
        trigger = self._trigger()
        binding = self._guild_binding(trigger.id, 111)
        other_campaign_payload = with_campaign_ancestry({}, uuid4())
        context = TriggerEvaluationContext(
            event_id=uuid4(),
            guild_id=111,
            discord_resource_id=None,
            causation_depth=1,
            payload=other_campaign_payload,
        )
        assert should_trigger(trigger, [binding], context) is True

    def test_condition_ast_must_also_match(self) -> None:
        trigger = self._trigger(
            condition_ast={"op": "EQUALS", "path": "tier", "value": "gold"}
        )
        binding = self._guild_binding(trigger.id, 111)
        context = TriggerEvaluationContext(
            event_id=uuid4(),
            guild_id=111,
            discord_resource_id=None,
            causation_depth=0,
            payload={"tier": "bronze"},
        )
        assert should_trigger(trigger, [binding], context) is False
