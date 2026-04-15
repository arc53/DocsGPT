import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from application.agents.workflows.schemas import (
    AgentNodeConfig,
    AgentType,
    ConditionCase,
    ConditionNodeConfig,
    ExecutionStatus,
    NodeExecutionLog,
    NodeType,
    Position,
    StateOperation,
    Workflow,
    WorkflowCreate,
    WorkflowEdge,
    WorkflowEdgeCreate,
    WorkflowGraph,
    WorkflowNode,
    WorkflowNodeCreate,
    WorkflowRun,
    WorkflowRunCreate,
)


# ── Enum tests ───────────────────────────────────────────────────────────────


class TestNodeType:
    @pytest.mark.unit
    def test_values(self):
        assert NodeType.START == "start"
        assert NodeType.END == "end"
        assert NodeType.AGENT == "agent"
        assert NodeType.NOTE == "note"
        assert NodeType.STATE == "state"
        assert NodeType.CONDITION == "condition"

    @pytest.mark.unit
    def test_all_members(self):
        assert set(NodeType) == {
            NodeType.START,
            NodeType.END,
            NodeType.AGENT,
            NodeType.NOTE,
            NodeType.STATE,
            NodeType.CONDITION,
        }


class TestAgentType:
    @pytest.mark.unit
    def test_values(self):
        assert AgentType.CLASSIC == "classic"
        assert AgentType.REACT == "react"
        assert AgentType.AGENTIC == "agentic"
        assert AgentType.RESEARCH == "research"


class TestExecutionStatus:
    @pytest.mark.unit
    def test_values(self):
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.RUNNING == "running"
        assert ExecutionStatus.COMPLETED == "completed"
        assert ExecutionStatus.FAILED == "failed"


# ── Position ─────────────────────────────────────────────────────────────────


class TestPosition:
    @pytest.mark.unit
    def test_defaults(self):
        p = Position()
        assert p.x == 0.0
        assert p.y == 0.0

    @pytest.mark.unit
    def test_custom_values(self):
        p = Position(x=10.5, y=-3.2)
        assert p.x == 10.5
        assert p.y == -3.2

    @pytest.mark.unit
    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            Position(x=0, y=0, z=1)


# ── AgentNodeConfig ──────────────────────────────────────────────────────────


class TestAgentNodeConfig:
    @pytest.mark.unit
    def test_defaults(self):
        c = AgentNodeConfig()
        assert c.agent_type == AgentType.CLASSIC
        assert c.llm_name is None
        assert c.system_prompt == "You are a helpful assistant."
        assert c.prompt_template == ""
        assert c.output_variable is None
        assert c.stream_to_user is True
        assert c.tools == []
        assert c.sources == []
        assert c.chunks == "2"
        assert c.retriever == ""
        assert c.model_id is None
        assert c.json_schema is None

    @pytest.mark.unit
    def test_custom_values(self):
        c = AgentNodeConfig(
            agent_type=AgentType.REACT,
            llm_name="gpt-4",
            tools=["search"],
            sources=["src1"],
            chunks="5",
            model_id="m1",
            json_schema={"type": "object"},
        )
        assert c.agent_type == AgentType.REACT
        assert c.llm_name == "gpt-4"
        assert c.tools == ["search"]
        assert c.sources == ["src1"]
        assert c.chunks == "5"
        assert c.model_id == "m1"
        assert c.json_schema == {"type": "object"}

    @pytest.mark.unit
    def test_extra_fields_allowed(self):
        c = AgentNodeConfig(custom_field="value")
        assert c.custom_field == "value"


# ── ConditionCase / ConditionNodeConfig ──────────────────────────────────────


class TestConditionCase:
    @pytest.mark.unit
    def test_alias(self):
        c = ConditionCase(expression="x > 1", sourceHandle="handle-1")
        assert c.source_handle == "handle-1"

    @pytest.mark.unit
    def test_defaults(self):
        c = ConditionCase(sourceHandle="h")
        assert c.name is None
        assert c.expression == ""

    @pytest.mark.unit
    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            ConditionCase(sourceHandle="h", extra="nope")


class TestConditionNodeConfig:
    @pytest.mark.unit
    def test_defaults(self):
        c = ConditionNodeConfig()
        assert c.mode == "simple"
        assert c.cases == []

    @pytest.mark.unit
    def test_with_cases(self):
        c = ConditionNodeConfig(
            mode="advanced",
            cases=[{"expression": "x > 1", "sourceHandle": "h1"}],
        )
        assert c.mode == "advanced"
        assert len(c.cases) == 1
        assert c.cases[0].source_handle == "h1"


# ── StateOperation ───────────────────────────────────────────────────────────


class TestStateOperation:
    @pytest.mark.unit
    def test_defaults(self):
        s = StateOperation()
        assert s.expression == ""
        assert s.target_variable == ""

    @pytest.mark.unit
    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            StateOperation(expression="a", target_variable="b", extra="no")


# ── WorkflowEdgeCreate / WorkflowEdge ───────────────────────────────────────


class TestWorkflowEdgeCreate:
    @pytest.mark.unit
    def test_aliases(self):
        e = WorkflowEdgeCreate(
            id="e1",
            workflow_id="w1",
            source="n1",
            target="n2",
            sourceHandle="sh",
            targetHandle="th",
        )
        assert e.source_id == "n1"
        assert e.target_id == "n2"
        assert e.source_handle == "sh"
        assert e.target_handle == "th"

    @pytest.mark.unit
    def test_optional_handles_default_none(self):
        e = WorkflowEdgeCreate(id="e1", workflow_id="w1", source="n1", target="n2")
        assert e.source_handle is None
        assert e.target_handle is None


class TestWorkflowEdge:
    @pytest.mark.unit
    def test_objectid_conversion(self):
        oid = uuid.uuid4().hex
        e = WorkflowEdge(
            _id=oid,
            id="e1",
            workflow_id="w1",
            source="n1",
            target="n2",
        )
        assert e.mongo_id == str(oid)

    @pytest.mark.unit
    def test_string_id_passthrough(self):
        e = WorkflowEdge(
            _id="string-id",
            id="e1",
            workflow_id="w1",
            source="n1",
            target="n2",
        )
        assert e.mongo_id == "string-id"

    @pytest.mark.unit
    def test_none_id(self):
        e = WorkflowEdge(id="e1", workflow_id="w1", source="n1", target="n2")
        assert e.mongo_id is None

    @pytest.mark.unit
    def test_to_mongo_doc(self):
        e = WorkflowEdge(
            id="e1",
            workflow_id="w1",
            source="n1",
            target="n2",
            sourceHandle="sh",
            targetHandle="th",
        )
        doc = e.to_mongo_doc()
        assert doc == {
            "id": "e1",
            "workflow_id": "w1",
            "source_id": "n1",
            "target_id": "n2",
            "source_handle": "sh",
            "target_handle": "th",
        }


# ── WorkflowNodeCreate / WorkflowNode ───────────────────────────────────────


class TestWorkflowNodeCreate:
    @pytest.mark.unit
    def test_defaults(self):
        n = WorkflowNodeCreate(id="n1", workflow_id="w1", type=NodeType.AGENT)
        assert n.title == "Node"
        assert n.description is None
        assert n.position.x == 0.0
        assert n.position.y == 0.0
        assert n.config == {}

    @pytest.mark.unit
    def test_position_from_dict(self):
        n = WorkflowNodeCreate(
            id="n1",
            workflow_id="w1",
            type=NodeType.START,
            position={"x": 100, "y": 200},
        )
        assert isinstance(n.position, Position)
        assert n.position.x == 100
        assert n.position.y == 200

    @pytest.mark.unit
    def test_position_from_position_object(self):
        pos = Position(x=5, y=10)
        n = WorkflowNodeCreate(
            id="n1", workflow_id="w1", type=NodeType.END, position=pos
        )
        assert n.position is pos


class TestWorkflowNode:
    @pytest.mark.unit
    def test_objectid_conversion(self):
        oid = uuid.uuid4().hex
        n = WorkflowNode(
            _id=oid, id="n1", workflow_id="w1", type=NodeType.AGENT
        )
        assert n.mongo_id == str(oid)

    @pytest.mark.unit
    def test_to_mongo_doc(self):
        n = WorkflowNode(
            id="n1",
            workflow_id="w1",
            type=NodeType.AGENT,
            title="My Node",
            description="desc",
            position={"x": 10, "y": 20},
            config={"key": "val"},
        )
        doc = n.to_mongo_doc()
        assert doc == {
            "id": "n1",
            "workflow_id": "w1",
            "type": "agent",
            "title": "My Node",
            "description": "desc",
            "position": {"x": 10.0, "y": 20.0},
            "config": {"key": "val"},
        }


# ── WorkflowCreate / Workflow ───────────────────────────────────────────────


class TestWorkflowCreate:
    @pytest.mark.unit
    def test_defaults(self):
        w = WorkflowCreate()
        assert w.name == "New Workflow"
        assert w.description is None
        assert w.user is None

    @pytest.mark.unit
    def test_custom_values(self):
        w = WorkflowCreate(name="Test", description="d", user="u1")
        assert w.name == "Test"
        assert w.description == "d"
        assert w.user == "u1"


class TestWorkflow:
    @pytest.mark.unit
    def test_objectid_conversion(self):
        oid = uuid.uuid4().hex
        w = Workflow(_id=oid)
        assert w.id == str(oid)

    @pytest.mark.unit
    def test_string_id(self):
        w = Workflow(_id="abc")
        assert w.id == "abc"

    @pytest.mark.unit
    def test_none_id(self):
        w = Workflow()
        assert w.id is None

    @pytest.mark.unit
    def test_datetime_defaults(self):
        before = datetime.now(timezone.utc)
        w = Workflow()
        after = datetime.now(timezone.utc)
        assert before <= w.created_at <= after
        assert before <= w.updated_at <= after

    @pytest.mark.unit
    def test_to_mongo_doc(self):
        w = Workflow(name="W", description="d", user="u1")
        doc = w.to_mongo_doc()
        assert doc["name"] == "W"
        assert doc["description"] == "d"
        assert doc["user"] == "u1"
        assert "created_at" in doc
        assert "updated_at" in doc


# ── WorkflowGraph ───────────────────────────────────────────────────────────


class TestWorkflowGraph:
    @pytest.fixture
    def graph(self):
        workflow = Workflow(name="test")
        nodes = [
            WorkflowNode(id="start", workflow_id="w1", type=NodeType.START),
            WorkflowNode(id="agent1", workflow_id="w1", type=NodeType.AGENT),
            WorkflowNode(id="end", workflow_id="w1", type=NodeType.END),
        ]
        edges = [
            WorkflowEdge(
                id="e1", workflow_id="w1", source="start", target="agent1"
            ),
            WorkflowEdge(
                id="e2", workflow_id="w1", source="agent1", target="end"
            ),
        ]
        return WorkflowGraph(workflow=workflow, nodes=nodes, edges=edges)

    @pytest.mark.unit
    def test_get_node_by_id_found(self, graph):
        node = graph.get_node_by_id("agent1")
        assert node is not None
        assert node.id == "agent1"
        assert node.type == NodeType.AGENT

    @pytest.mark.unit
    def test_get_node_by_id_not_found(self, graph):
        assert graph.get_node_by_id("nonexistent") is None

    @pytest.mark.unit
    def test_get_start_node(self, graph):
        start = graph.get_start_node()
        assert start is not None
        assert start.id == "start"
        assert start.type == NodeType.START

    @pytest.mark.unit
    def test_get_start_node_missing(self):
        g = WorkflowGraph(
            workflow=Workflow(),
            nodes=[
                WorkflowNode(id="a", workflow_id="w", type=NodeType.AGENT),
            ],
        )
        assert g.get_start_node() is None

    @pytest.mark.unit
    def test_get_outgoing_edges(self, graph):
        edges = graph.get_outgoing_edges("start")
        assert len(edges) == 1
        assert edges[0].target_id == "agent1"

    @pytest.mark.unit
    def test_get_outgoing_edges_none(self, graph):
        edges = graph.get_outgoing_edges("end")
        assert edges == []

    @pytest.mark.unit
    def test_empty_graph(self):
        g = WorkflowGraph(workflow=Workflow())
        assert g.nodes == []
        assert g.edges == []
        assert g.get_start_node() is None


# ── NodeExecutionLog ─────────────────────────────────────────────────────────


class TestNodeExecutionLog:
    @pytest.mark.unit
    def test_required_fields(self):
        now = datetime.now(timezone.utc)
        log = NodeExecutionLog(
            node_id="n1",
            node_type="agent",
            status=ExecutionStatus.RUNNING,
            started_at=now,
        )
        assert log.node_id == "n1"
        assert log.completed_at is None
        assert log.error is None
        assert log.state_snapshot == {}

    @pytest.mark.unit
    def test_full_log(self):
        started = datetime.now(timezone.utc)
        completed = datetime.now(timezone.utc)
        log = NodeExecutionLog(
            node_id="n1",
            node_type="agent",
            status=ExecutionStatus.COMPLETED,
            started_at=started,
            completed_at=completed,
            error=None,
            state_snapshot={"key": "value"},
        )
        assert log.completed_at == completed
        assert log.state_snapshot == {"key": "value"}

    @pytest.mark.unit
    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            NodeExecutionLog(
                node_id="n",
                node_type="agent",
                status=ExecutionStatus.PENDING,
                started_at=datetime.now(timezone.utc),
                extra="no",
            )


# ── WorkflowRunCreate / WorkflowRun ─────────────────────────────────────────


class TestWorkflowRunCreate:
    @pytest.mark.unit
    def test_defaults(self):
        r = WorkflowRunCreate(workflow_id="w1")
        assert r.workflow_id == "w1"
        assert r.inputs == {}


class TestWorkflowRun:
    @pytest.mark.unit
    def test_defaults(self):
        r = WorkflowRun(workflow_id="w1")
        assert r.status == ExecutionStatus.PENDING
        assert r.inputs == {}
        assert r.outputs == {}
        assert r.steps == []
        assert r.completed_at is None

    @pytest.mark.unit
    def test_objectid_conversion(self):
        oid = uuid.uuid4().hex
        r = WorkflowRun(_id=oid, workflow_id="w1")
        assert r.id == str(oid)

    @pytest.mark.unit
    def test_to_mongo_doc(self):
        now = datetime.now(timezone.utc)
        log = NodeExecutionLog(
            node_id="n1",
            node_type="agent",
            status=ExecutionStatus.COMPLETED,
            started_at=now,
        )
        r = WorkflowRun(
            workflow_id="w1",
            status=ExecutionStatus.RUNNING,
            inputs={"q": "hello"},
            outputs={"a": "world"},
            steps=[log],
        )
        doc = r.to_mongo_doc()
        assert doc["workflow_id"] == "w1"
        assert doc["status"] == "running"
        assert doc["inputs"] == {"q": "hello"}
        assert doc["outputs"] == {"a": "world"}
        assert len(doc["steps"]) == 1
        assert doc["steps"][0]["node_id"] == "n1"
        assert doc["completed_at"] is None
