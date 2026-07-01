"""Unit tests for the workflow ``code`` node and the pass-by-reference convention.

These exercise the engine's code-node logic with a fake sandbox manager and a
patched persistence helper (no live gateway / DB / storage), plus the
serialization round-trip and CEL branching on an artifact reference.
"""

import json
from types import SimpleNamespace

import pytest

from application.agents.workflow_agent import WorkflowAgent
from application.agents.workflows.cel_evaluator import evaluate_cel
from application.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowGraph,
    WorkflowNode,
)
from application.agents.workflows.workflow_engine import WorkflowEngine


def _engine() -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Code Node Test"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="test-key",
        chat_history=[],
        user="user-code",
        decoded_token={"sub": "user-code"},
    )
    return WorkflowEngine(graph, agent, workflow_run_id="11111111-1111-1111-1111-111111111111")


def _code_node(node_id="code_1", **config) -> WorkflowNode:
    base = {"code": "print('hi')"}
    base.update(config)
    return WorkflowNode(
        id=node_id,
        workflow_id="wf-1",
        type=NodeType.CODE,
        title="Code",
        position={"x": 0, "y": 0},
        config=base,
    )


class _Result:
    def __init__(self, ok=True, stdout="", error_name=None, error_value=None):
        self.status = "ok" if ok else "error"
        self.stdout = stdout
        self.stderr = ""
        self.error_name = error_name
        self.error_value = error_value

    @property
    def ok(self):
        return self.status == "ok"


class _FakeManager:
    """Records open/close/put_file/exec and returns a fixed result; no real sandbox."""

    def __init__(self, result):
        self._result = result
        self.opened = []
        self.closed = []
        self.put_files = []
        self.last_code = None

    def open(self, session_id, ttl=None):
        self.opened.append(session_id)
        return session_id

    def put_file(self, session_id, dest_path, data):
        self.put_files.append((dest_path, data))

    def exec(self, session_id, code, timeout=None):
        self.last_timeout = timeout
        self.last_code = code
        return self._result

    def close(self, session_id):
        self.closed.append(session_id)


@pytest.fixture()
def patch_sandbox(monkeypatch):
    """Patch the sandbox manager + capture helper; return knobs to drive them."""
    state = {"result": _Result(ok=True, stdout="ok"), "captured": [], "snapshot_calls": 0}

    manager_holder = {}

    def _get_manager():
        manager = _FakeManager(state["result"])
        manager_holder["manager"] = manager
        return manager

    monkeypatch.setattr(
        "application.sandbox.sandbox_creator.SandboxCreator.get_manager", _get_manager
    )
    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.snapshot_signatures",
        lambda *a, **k: state.__setitem__("snapshot_calls", state["snapshot_calls"] + 1) or {},
    )
    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.capture_artifacts",
        lambda *a, **k: list(state["captured"]),
    )
    state["manager_holder"] = manager_holder
    return state


def test_code_node_writes_artifact_reference_into_state(patch_sandbox):
    engine = _engine()
    ref = {
        "artifact_id": "art-1",
        "version": 1,
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size": 10,
    }
    patch_sandbox["captured"] = [ref]
    node = _code_node(output_variable="report", code="open('report.pdf','wb').write(b'x')")

    list(engine._execute_code_node(node))

    # The reference (JSON primitives only) lands under both keys; no bytes.
    assert engine.state["node_code_1_output"] == ref
    assert engine.state["report"] == ref
    assert all(not isinstance(v, (bytes, bytearray)) for v in engine.state["report"].values())
    # The sandbox session is bound to the run id and closed after the run.
    manager = patch_sandbox["manager_holder"]["manager"]
    assert manager.opened == ["11111111-1111-1111-1111-111111111111"]
    assert manager.closed == ["11111111-1111-1111-1111-111111111111"]


def test_code_node_no_artifacts_still_writes_status(patch_sandbox):
    engine = _engine()
    patch_sandbox["captured"] = []
    node = _code_node(output_variable="out", code="print('noop')")

    list(engine._execute_code_node(node))

    assert engine.state["out"] == {"artifacts": [], "status": "ok"}


def test_code_node_reads_prior_state_from_state_json(patch_sandbox):
    # Prior state is staged as DATA in state.json (workspace root = kernel cwd) so
    # node code reads it with json.load(open("state.json")) -- e.g. state["decision"].
    engine = _engine()
    engine.state["decision"] = {"pass": True, "score": 7}
    node = _code_node(
        output_variable="out",
        code="import json\nd = json.load(open('state.json'))\nprint(d['decision'])\n",
    )

    list(engine._execute_code_node(node))

    manager = patch_sandbox["manager_holder"]["manager"]
    staged = dict(manager.put_files)
    assert "state.json" in staged
    payload = json.loads(staged["state.json"].decode("utf-8"))
    assert payload["decision"] == {"pass": True, "score": 7}


def test_code_node_literal_braces_passed_verbatim_not_templated(patch_sandbox):
    # Proves code nodes are NOT Jinja-rendered: a literal ``{{ ... }}`` in the code
    # reaches exec() byte-for-byte (no injection path that interpolates state).
    engine = _engine()
    engine.state["decision"] = "INJECTED"
    literal = "x = '{{ agent.decision }}'\nprint(x)\n"
    node = _code_node(output_variable="out", code=literal)

    list(engine._execute_code_node(node))

    manager = patch_sandbox["manager_holder"]["manager"]
    assert manager.last_code == literal
    assert "INJECTED" not in manager.last_code


def test_code_node_failure_raises(patch_sandbox):
    engine = _engine()
    patch_sandbox["result"] = _Result(ok=False, error_name="ValueError", error_value="boom")
    node = _code_node(code="raise ValueError('boom')")

    with pytest.raises(ValueError, match="failed: ValueError: boom"):
        list(engine._execute_code_node(node))


def test_code_node_empty_code_raises(patch_sandbox):
    engine = _engine()
    node = _code_node(code="   ")
    with pytest.raises(ValueError, match="no code to execute"):
        list(engine._execute_code_node(node))


def test_code_node_json_schema_validates_decision(patch_sandbox):
    engine = _engine()
    patch_sandbox["result"] = _Result(ok=True, stdout='{"pass": true, "score": 5}')
    patch_sandbox["captured"] = []
    node = _code_node(
        output_variable="decision",
        code="print('{...}')",
        json_schema={
            "type": "object",
            "properties": {"pass": {"type": "boolean"}, "score": {"type": "integer"}},
            "required": ["pass"],
        },
    )

    list(engine._execute_code_node(node))

    assert engine.state["decision"] == {"pass": True, "score": 5}


def test_code_node_json_schema_rejects_non_json_stdout(patch_sandbox):
    engine = _engine()
    patch_sandbox["result"] = _Result(ok=True, stdout="not json")
    node = _code_node(
        json_schema={"type": "object"},
        code="print('x')",
    )
    with pytest.raises(ValueError, match="stdout was not valid JSON"):
        list(engine._execute_code_node(node))


def test_code_node_json_schema_merges_artifact_reference(patch_sandbox):
    engine = _engine()
    ref = {"artifact_id": "art-9", "version": 1, "filename": "r.pdf", "mime_type": "application/pdf", "size": 3}
    patch_sandbox["result"] = _Result(ok=True, stdout='{"pass": false}')
    patch_sandbox["captured"] = [ref]
    node = _code_node(
        output_variable="decision",
        json_schema={"type": "object", "properties": {"pass": {"type": "boolean"}}},
    )

    list(engine._execute_code_node(node))

    decision = engine.state["decision"]
    assert decision["pass"] is False
    assert decision["artifacts"] == [ref]


def test_code_node_timeout_clamped_to_cap(patch_sandbox, monkeypatch):
    from application.core.settings import settings

    monkeypatch.setattr(settings, "SANDBOX_EXEC_TIMEOUT", 30, raising=False)
    engine = _engine()
    node = _code_node(timeout=9999, code="print('x')")
    list(engine._execute_code_node(node))
    manager = patch_sandbox["manager_holder"]["manager"]
    assert manager.last_timeout == 30.0


def test_resolve_input_artifact_ids_from_state_refs_and_raw():
    engine = _engine()
    engine.state["report"] = {"artifact_id": "art-from-ref"}
    engine.state["not_a_ref"] = "plain string"
    ids = engine._resolve_input_artifact_ids(["report", "art-raw-id", "not_a_ref"])
    # A state var holding a ref resolves to its artifact_id; any other entry is
    # taken as a raw artifact id (the literal token, not a resolved value).
    assert ids == ["art-from-ref", "art-raw-id", "not_a_ref"]


# ---------------------------------------------------------------------------
# Pass-by-reference: survives serialization + CEL branches on the metadata.
# ---------------------------------------------------------------------------


def test_artifact_reference_survives_serialize_state_value():
    agent = WorkflowAgent.__new__(WorkflowAgent)
    ref = {
        "artifact_id": "art-1",
        "version": 2,
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size": 1234,
    }
    state = {"report": ref, "decision": {"pass": True, "artifacts": [ref]}}

    serialized = agent._serialize_state(state)

    # Every primitive survives untouched (no stringification of the dict ref).
    assert serialized["report"] == ref
    assert serialized["decision"]["pass"] is True
    assert serialized["decision"]["artifacts"][0] == ref


def test_cel_branches_on_artifact_metadata():
    state = {
        "report": {
            "artifact_id": "art-1",
            "size": 1234,
            "mime_type": "application/pdf",
        }
    }
    assert evaluate_cel('report.size > 0 && report.mime_type == "application/pdf"', state) is True
    assert evaluate_cel('report.mime_type == "text/plain"', state) is False
    assert evaluate_cel("report.size > 5000", state) is False
