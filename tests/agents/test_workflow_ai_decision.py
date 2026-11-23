from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from docsgpt.agents.workflows.retry import TRANSIENT, DecisionUnavailableError, classify_failure
from docsgpt.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from docsgpt.agents.workflows.workflow_engine import WorkflowDecisionError, WorkflowEngine
from docsgpt.api.user.workflows.routes import validate_workflow_structure, workflow_graph_errors
from docsgpt.decisions.features import WORKFLOW_DECISION
from docsgpt.decisions.types import BatchResult
from docsgpt.decisions.testing import FakeDecider, installed


def _decision_config(**overrides) -> Dict[str, Any]:
    config = {
        "mode": "ai",
        "cases": [
            {"name": "Billing", "description": "Invoices and payments", "expression": "", "sourceHandle": "case_0"},
            {"name": "Support", "expression": "", "sourceHandle": "case_1"},
        ],
    }
    config.update(overrides)
    return config


def _decision_node(config: Dict[str, Any]) -> WorkflowNode:
    return WorkflowNode(id="decide", workflow_id="workflow-1", type=NodeType.CONDITION, title="Route", config=config)


def _engine(node: WorkflowNode, endpoint: str = "stream", retry_defaults=None) -> WorkflowEngine:
    graph = WorkflowGraph(
        workflow=Workflow(name="Decision Test", retry_defaults=retry_defaults),
        nodes=[node],
        edges=[
            WorkflowEdge(id="e0", workflow_id="workflow-1", source="decide", target="billing", sourceHandle="case_0"),
            WorkflowEdge(id="e1", workflow_id="workflow-1", source="decide", target="support", sourceHandle="case_1"),
            WorkflowEdge(id="e2", workflow_id="workflow-1", source="decide", target="fallback", sourceHandle="else"),
        ],
    )
    agent = SimpleNamespace(
        endpoint=endpoint,
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="test-key",
        chat_history=[],
        decoded_token={"sub": "user-1"},
    )
    engine = WorkflowEngine(graph, agent)
    engine.state["query"] = "Where is my invoice?"
    return engine


def _decide(config: Dict[str, Any], fake: FakeDecider, endpoint: str = "stream") -> WorkflowEngine:
    node = _decision_node(config)
    engine = _engine(node, endpoint=endpoint)
    with installed(fake):
        assert list(engine._execute_condition_node(node)) == []
    return engine


def test_routes_to_the_branch_the_model_picks():
    fake = FakeDecider({"branch": {"Billing": 0.9, "Support": 0.06, "other": 0.04}})

    engine = _decide(_decision_config(output_variable="route"), fake)

    assert engine._get_next_node_id("decide") == "billing"
    output = engine.state["node_decide_output"]
    assert output["branch"] == "Billing"
    assert output["confidence"] == pytest.approx(0.9)
    assert set(output["probabilities"]) == {"Billing", "Support", "other"}
    assert engine.state["route"] == output
    call = fake.calls[0]
    assert call.feature == WORKFLOW_DECISION
    assert call.budget.lane == "hot"
    assert call.requests[0].state == {"text": "Where is my invoice?"}
    question = call.requests[0].questions["branch"]
    assert question["type"] == "choice"
    assert question["criteria"] == {
        "Billing": "Invoices and payments",
        "Support": "Support",
        "other": "None of the above.",
    }


def test_asks_the_nodes_own_question_about_the_rendered_input():
    fake = FakeDecider({"branch": "Support"})

    engine = _decide(
        _decision_config(prompt_template="Ticket: {{ agent.query }}", instructions="Who should handle this ticket?"),
        fake,
    )

    request = fake.calls[0].requests[0]
    assert request.state == {"text": "Ticket: Where is my invoice?"}
    assert request.questions["branch"]["instructions"] == "Who should handle this ticket?"
    assert engine._get_next_node_id("decide") == "support"


def test_no_matching_branch_takes_else():
    engine = _decide(_decision_config(), FakeDecider({"branch": "other"}))

    assert engine._get_next_node_id("decide") == "fallback"
    assert engine.state["node_decide_output"]["branch"] is None


def test_an_unsure_answer_takes_else_below_the_minimum_confidence():
    fake = FakeDecider({"branch": {"Billing": 0.55, "Support": 0.45}})

    engine = _decide(_decision_config(min_confidence=0.7), fake)

    assert engine._get_next_node_id("decide") == "fallback"
    assert engine.state["node_decide_output"]["branch"] is None


def test_a_scheduled_run_asks_in_the_background_lane():
    fake = FakeDecider({"branch": "Billing"})

    _decide(_decision_config(), fake, endpoint="schedule")

    assert fake.calls[0].budget.lane == "background"


def test_a_model_still_loading_is_waited_for_in_the_background_lane():
    class LoadingOnce(FakeDecider):
        def decide_batch(self, requests, *, feature, budget=None):
            if not self.calls:
                self.calls.append(None)
                return BatchResult([None], ["loading"])
            return super().decide_batch(requests, feature=feature, budget=budget)

    fake = LoadingOnce({"branch": "Support"})

    engine = _decide(_decision_config(), fake)

    assert engine._get_next_node_id("decide") == "support"
    assert fake.calls[1].budget.lane == "background"


def test_an_unanswered_call_is_a_transient_failure():
    node = _decision_node(_decision_config())
    engine = _engine(node)

    with installed(FakeDecider(reasons={WORKFLOW_DECISION: "loading"})):
        with pytest.raises(DecisionUnavailableError, match="loading") as caught:
            list(engine._execute_condition_node(node))

    assert classify_failure(caught.value, "condition") == TRANSIENT


def test_the_model_turned_off_fails_the_node_plainly():
    node = _decision_node(_decision_config())
    engine = _engine(node)

    with pytest.raises(WorkflowDecisionError, match="decision model, which is off"):
        list(engine._execute_condition_node(node))


@pytest.mark.parametrize(
    ("cases", "message"),
    [
        ([{"name": " ", "expression": "", "sourceHandle": "case_0"}], "needs at least one branch with a name"),
        ([{"name": "Other", "expression": "", "sourceHandle": "case_0"}], "twice or"),
        (
            [{"name": f"b{i}", "expression": "", "sourceHandle": f"case_{i}"} for i in range(16)],
            "more than 15 branches",
        ),
    ],
)
def test_rejects_branches_the_model_cannot_take(cases: List[Dict[str, Any]], message: str):
    node = _decision_node(_decision_config(cases=cases))
    engine = _engine(node)

    with installed(FakeDecider()):
        with pytest.raises(WorkflowDecisionError, match=message):
            list(engine._execute_condition_node(node))


def test_retries_with_the_workflows_policy():
    node = _decision_node(_decision_config())
    engine = _engine(node, retry_defaults={"max_attempts": 3})

    assert engine._retry_policy(node).max_attempts == 3
    assert engine._retry_policy(_decision_node({"mode": "simple", "cases": []})).max_attempts == 1


def test_rule_modes_still_evaluate_cel():
    node = _decision_node(
        {"mode": "advanced", "cases": [{"expression": "query.contains('invoice')", "sourceHandle": "case_1"}]}
    )
    engine = _engine(node)

    list(engine._execute_condition_node(node))

    assert engine._get_next_node_id("decide") == "support"


def _decision_graph(cases: List[Dict[str, Any]], **config: Any):
    nodes = [
        {"id": "start", "type": "start", "title": "Start", "data": {}},
        {"id": "decide", "type": "condition", "title": "Route", "data": {"mode": "ai", "cases": cases, **config}},
        {"id": "end_a", "type": "end", "title": "A", "data": {}},
        {"id": "end_b", "type": "end", "title": "B", "data": {}},
    ]
    edges = [{"id": "e0", "source": "start", "target": "decide"}]
    edges += [
        {"id": f"e_{case['sourceHandle']}", "source": "decide", "target": "end_a", "sourceHandle": case["sourceHandle"]}
        for case in cases
    ]
    edges.append({"id": "e_else", "source": "decide", "target": "end_b", "sourceHandle": "else"})
    return nodes, edges


def test_validation_accepts_named_branches_without_expressions():
    nodes, edges = _decision_graph([{"name": "Billing", "description": "Invoices", "sourceHandle": "case_0"}])

    assert validate_workflow_structure(nodes, edges) == []


def test_validation_needs_a_name_for_a_connected_branch():
    nodes, edges = _decision_graph([{"name": "", "expression": "true", "sourceHandle": "case_0"}])

    errors = validate_workflow_structure(nodes, edges)

    assert any("at least one case with a name" in err for err in errors), errors
    assert any("has an outgoing edge but no name" in err for err in errors), errors


def test_validation_rejects_reserved_and_duplicate_names():
    nodes, edges = _decision_graph(
        [
            {"name": "other", "sourceHandle": "case_0"},
            {"name": "Billing", "sourceHandle": "case_1"},
            {"name": "billing ", "sourceHandle": "case_2"},
        ]
    )

    errors = validate_workflow_structure(nodes, edges)

    assert any("can't name a branch 'other'" in err for err in errors), errors
    assert any("more than one branch named 'billing'" in err for err in errors), errors


def test_validation_limits_branches_and_confidence():
    cases = [{"name": f"b{i}", "sourceHandle": f"case_{i}"} for i in range(16)]
    nodes, edges = _decision_graph(cases, min_confidence=1.5)

    errors = validate_workflow_structure(nodes, edges)

    assert "AI decision 'Route' can have at most 15 branches" in errors
    assert "AI decision 'Route' minimum confidence must be a number from 0 to 1" in errors


def test_validation_checks_retry_settings():
    nodes, edges = _decision_graph([{"name": "Billing", "sourceHandle": "case_0"}], retry={"max_attempts": "lots"})

    errors = validate_workflow_structure(nodes, edges)

    assert any(err.startswith("AI decision 'Route' retry") for err in errors), errors


def test_saving_a_graph_with_an_ai_decision_warms_the_model():
    nodes, edges = _decision_graph([{"name": "Billing", "sourceHandle": "case_0"}])
    fake = FakeDecider()

    with installed(fake):
        assert workflow_graph_errors({"nodes": nodes, "edges": edges}, draft=False, user_id="u1") == []

    assert fake.warmed == 1
