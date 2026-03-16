from types import SimpleNamespace

from application.agents.workflows.schemas import Workflow, WorkflowGraph
from application.agents.workflows.workflow_engine import WorkflowEngine


def create_engine() -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Template Test"), nodes=[], edges=[])
    agent = SimpleNamespace(
        user="user-1",
        request_id="req-1",
        retrieved_docs=[
            {"title": "Doc A", "text": "Summary A"},
            {"title": "Doc B", "text": "Summary B"},
        ],
    )
    return WorkflowEngine(graph, agent)


def test_workflow_template_supports_agent_namespace_and_legacy_variables():
    engine = create_engine()
    engine.state = {"query": "Hello", "chat_history": "[]", "ticket_id": 42}

    rendered = engine._format_template(
        "{{ agent.query }}|{{ agent.ticket_id }}|{{ query }}|{{ ticket_id }}"
    )

    assert rendered == "Hello|42|Hello|42"


def test_workflow_template_supports_global_namespaces():
    engine = create_engine()
    engine.state = {"query": "Hello"}

    rendered = engine._format_template(
        "{{ source.count }}|{{ source.summaries }}|{{ system.request_id }}"
    )

    assert rendered.startswith("2|")
    assert "Doc A" in rendered
    assert "Summary A" in rendered
    assert rendered.endswith("|req-1")


def test_workflow_template_handles_namespace_conflicts_with_agent_prefix():
    engine = create_engine()
    engine.state = {"source": "user-defined-source"}

    rendered = engine._format_template(
        "{{ agent.source }}|{{ agent_source }}|{{ source.count }}"
    )

    assert rendered.startswith("user-defined-source|user-defined-source|")


def test_workflow_template_gracefully_handles_invalid_template_syntax():
    engine = create_engine()
    engine.state = {"query": "Hello"}

    invalid_template = "{{ agent.query "
    rendered = engine._format_template(invalid_template)

    assert rendered == invalid_template
