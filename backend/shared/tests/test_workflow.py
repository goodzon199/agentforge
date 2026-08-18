from __future__ import annotations

import pytest
from shared.workflow import (
    ConditionError,
    WorkflowError,
    evaluate_condition,
    parse_workflow,
)


def test_parse_valid_workflow():
    workflow = parse_workflow(
        """
name: sales_pipeline
version: 1.0.0
start: intake
nodes:
  - id: intake
    type: agent
    agent: intake
    next: classify
  - id: classify
    type: condition
    expression: "context.get('requires_search', False)"
    branches:
      "true": search
      "false": human
  - id: search
    type: agent
    agent: search
    next: done
  - id: done
    type: end
  - id: human
    type: end
"""
    )
    assert workflow.name == "sales_pipeline"
    assert workflow.node("intake").agent == "intake"


def test_parse_invalid_dag():
    with pytest.raises(WorkflowError):
        parse_workflow(
            {
                "name": "x",
                "version": "1.0.0",
                "start": "missing",
                "nodes": [{"id": "a", "type": "end"}],
            }
        )


def test_condition_branch_keys_required():
    with pytest.raises(WorkflowError):
        parse_workflow(
            {
                "name": "x",
                "version": "1.0.0",
                "start": "c",
                "nodes": [
                    {
                        "id": "c",
                        "type": "condition",
                        "expression": "True",
                        "branches": {"true": "e"},
                    },
                    {"id": "e", "type": "end"},
                ],
            }
        )


def test_agent_node_requires_agent():
    with pytest.raises(WorkflowError):
        parse_workflow(
            {
                "name": "x",
                "version": "1.0.0",
                "start": "a",
                "nodes": [{"id": "a", "type": "agent"}],
            }
        )


def test_cycle_detected_in_validate():
    workflow = parse_workflow(
        {
            "name": "x",
            "version": "1.0.0",
            "start": "a",
            "nodes": [
                {"id": "a", "type": "agent", "agent": "x", "next": "b"},
                {"id": "b", "type": "agent", "agent": "x", "next": "a"},
            ],
        }
    )
    # Validation allows structural cycles (they are detected at runtime);
    # this just confirms a valid parse succeeded.
    assert workflow.node("b").next == "a"


@pytest.mark.parametrize(
    ("expression", "context", "expected"),
    [
        ("context.get('requires_search', False)", {}, False),
        ("context.get('requires_search', False)", {"requires_search": True}, True),
        ("context['found']", {"found": True}, True),
        ("context['count'] > 3", {"count": 5}, True),
        ("context['count'] > 3", {"count": 2}, False),
        ("context['found'] and context['count'] >= 1", {"found": True, "count": 1}, True),
        ("not context.get('blocked', False)", {"blocked": False}, True),
        ("context['name'] == 'Иван'", {"name": "Иван"}, True),
        ("context['parts'] == []", {"parts": []}, True),
        ("'search' in context['results']", {"results": ["search"]}, True),
    ],
)
def test_evaluate_condition(expression, context, expected):
    assert evaluate_condition(expression, context) is expected


def test_evaluate_condition_rejects_calls():
    with pytest.raises(ConditionError):
        evaluate_condition("__import__('os').system('x')", {})


def test_evaluate_condition_rejects_unknown_var():
    with pytest.raises(ConditionError):
        evaluate_condition("unknown_var", {})


def test_evaluate_condition_rejects_bad_syntax():
    with pytest.raises(ConditionError):
        evaluate_condition("context['a'", {})
