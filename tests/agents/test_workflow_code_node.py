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
    WorkflowEdge,
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
    def __init__(
        self,
        ok=True,
        stdout="",
        error_name=None,
        error_value=None,
        runtime_invalidated=False,
    ):
        self.status = "ok" if ok else "error"
        self.stdout = stdout
        self.stderr = ""
        self.error_name = error_name
        self.error_value = error_value
        self.runtime_invalidated = runtime_invalidated

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
    state = {
        "result": _Result(ok=True, stdout="ok"),
        "captured": [],
        "snapshot_calls": 0,
        "capture_calls": 0,
    }

    manager_holder = {}

    def _get_manager():
        manager = _FakeManager(state["result"])
        manager_holder["manager"] = manager
        return manager

    def _capture(*a, **k):
        state["capture_calls"] += 1
        return list(state["captured"])

    monkeypatch.setattr(
        "application.sandbox.sandbox_creator.SandboxCreator.get_manager", _get_manager
    )
    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.snapshot_signatures",
        lambda *a, **k: state.__setitem__("snapshot_calls", state["snapshot_calls"] + 1) or {},
    )
    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.capture_artifacts", _capture
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
    # The sandbox session is bound to the run id. It is NOT closed per node: the
    # session is shared across nodes and torn down once at end of the run (in
    # WorkflowEngine.execute), so a code node leaves it open.
    manager = patch_sandbox["manager_holder"]["manager"]
    assert manager.opened == ["11111111-1111-1111-1111-111111111111"]
    assert manager.closed == []


def test_code_node_no_artifacts_still_writes_status(patch_sandbox):
    engine = _engine()
    patch_sandbox["captured"] = []
    node = _code_node(output_variable="out", code="print('noop')")

    list(engine._execute_code_node(node))

    assert engine.state["out"] == {"artifacts": [], "status": "ok"}


def test_code_node_captures_when_run_persisted(patch_sandbox):
    # The default persisted run captures produced files into artifacts.
    engine = _engine()  # run_persisted defaults True
    patch_sandbox["captured"] = []
    node = _code_node(output_variable="out", code="print('x')")

    list(engine._execute_code_node(node))

    assert patch_sandbox["capture_calls"] == 1


def test_code_node_skips_capture_when_run_not_persisted(patch_sandbox):
    # An unsaved/draft run has no workflow_runs row, so capturing would create
    # orphan artifacts (403 on get/download): capture is skipped entirely and the
    # node emits the empty-artifacts shape. The sandbox still ran.
    engine = _engine()
    engine.run_persisted = False
    ref = {
        "artifact_id": "art-1", "version": 1, "filename": "r.pdf",
        "mime_type": "application/pdf", "size": 3,
    }
    patch_sandbox["captured"] = [ref]
    node = _code_node(output_variable="out", code="open('r.pdf','wb').write(b'x')")

    list(engine._execute_code_node(node))

    assert patch_sandbox["capture_calls"] == 0
    assert engine.state["out"] == {"artifacts": [], "status": "ok"}
    # The sandbox session still opened (only persistence was skipped) and is left open
    # for the run to reap -- the node never closes the shared run session.
    manager = patch_sandbox["manager_holder"]["manager"]
    assert manager.opened == ["11111111-1111-1111-1111-111111111111"]
    assert manager.closed == []


def test_execute_closes_run_session_once_at_end(monkeypatch):
    """The run-scoped sandbox session opened by a code node is closed once when execute() ends."""
    manager = _FakeManager(_Result(ok=True, stdout="ok"))
    monkeypatch.setattr(
        "application.sandbox.sandbox_creator.SandboxCreator.get_manager", lambda: manager
    )
    monkeypatch.setattr(
        "application.sandbox.sandbox_creator.SandboxCreator.peek_manager", lambda: manager
    )
    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.snapshot_signatures", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.capture_artifacts", lambda *a, **k: []
    )

    start = WorkflowNode(
        id="start_1", workflow_id="wf-1", type=NodeType.START, title="Start",
        position={"x": 0, "y": 0}, config={},
    )
    code = _code_node(node_id="code_1", output_variable="out", code="print('x')")
    edge = WorkflowEdge(id="e1", workflow_id="wf-1", source="start_1", target="code_1")
    graph = WorkflowGraph(workflow=Workflow(name="Close Once"), nodes=[start, code], edges=[edge])
    agent = SimpleNamespace(
        endpoint="stream", llm_name="openai", model_id="gpt-4o-mini", api_key="test-key",
        chat_history=[], user="user-code", decoded_token={"sub": "user-code"},
    )
    sid = "11111111-1111-1111-1111-111111111111"
    engine = WorkflowEngine(graph, agent, workflow_run_id=sid)

    list(engine.execute({}, "q"))

    # The code node opened the run session and left it open; execute() closed it
    # exactly once at the end of the run (not once per node).
    assert manager.opened == [sid]
    assert manager.closed == [sid]


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


def test_code_node_invalidated_runtime_skips_capture_and_preserves_timeout(patch_sandbox):
    engine = _engine()
    patch_sandbox["result"] = _Result(
        ok=False,
        error_name="TimeoutError",
        error_value="execution exceeded 30s",
        runtime_invalidated=True,
    )
    node = _code_node(code="while True: pass")

    with pytest.raises(ValueError, match="failed: TimeoutError: execution exceeded 30s"):
        list(engine._execute_code_node(node))

    assert patch_sandbox["capture_calls"] == 0


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


def test_materialize_code_inputs_rejects_oversize(monkeypatch):
    """A code-node input whose declared version ``size`` exceeds the cap raises before staging."""
    from contextlib import contextmanager

    from application.core.settings import settings

    monkeypatch.setattr(settings, "SANDBOX_MAX_INPUT_BYTES", 100, raising=False)
    monkeypatch.setattr(
        "application.agents.tools.artifact_ref.resolve_artifact_id",
        lambda repo, raw, **k: str(raw),
    )

    class _Repo:
        def __init__(self, conn):
            pass

        def get_artifact_in_parent(self, artifact_id, *, workflow_run_id=None, conversation_id=None):
            return {"id": artifact_id, "current_version": 1}

        def get_version(self, artifact_id, version):
            return {"filename": "big.csv", "size": 10_000, "storage_path": "p/big.csv"}

    @contextmanager
    def _readonly():
        yield object()

    class _Storage:
        def get_file(self, path):
            raise AssertionError("bytes must not be read when declared size exceeds the cap")

    monkeypatch.setattr(
        "application.storage.db.repositories.artifacts.ArtifactsRepository", _Repo
    )
    monkeypatch.setattr("application.storage.db.session.db_readonly", _readonly)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _Storage()),
    )

    engine = _engine()
    manager = _FakeManager(_Result(ok=True, stdout="ok"))
    with pytest.raises(ValueError, match="exceeds"):
        engine._materialize_code_inputs(manager, engine._session_id(), ["art-raw-id"], "user-code")
    assert manager.put_files == []  # nothing staged


def test_materialize_code_inputs_dedupes_same_filename(monkeypatch):
    """Two code-node inputs sharing a filename stage to DISTINCT inputs/ paths (no clobber)."""
    from contextlib import contextmanager

    monkeypatch.setattr(
        "application.agents.tools.artifact_ref.resolve_artifact_id",
        lambda repo, raw, **k: str(raw),
    )

    class _Repo:
        def __init__(self, conn):
            pass

        def get_artifact_in_parent(self, artifact_id, *, workflow_run_id=None, conversation_id=None):
            return {"id": artifact_id, "current_version": 1}

        def get_version(self, artifact_id, version):
            # Same filename, distinct stored bytes per input.
            return {"filename": "data.csv", "storage_path": f"p/{artifact_id}.csv"}

    @contextmanager
    def _readonly():
        yield object()

    class _Storage:
        def get_file(self, path):
            import io

            return io.BytesIO(path.encode())

    monkeypatch.setattr(
        "application.storage.db.repositories.artifacts.ArtifactsRepository", _Repo
    )
    monkeypatch.setattr("application.storage.db.session.db_readonly", _readonly)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _Storage()),
    )

    engine = _engine()
    manager = _FakeManager(_Result(ok=True, stdout="ok"))
    loaded = engine._materialize_code_inputs(
        manager, engine._session_id(), ["art-a", "art-b"], "user-code"
    )

    assert loaded == ["inputs/data.csv", "inputs/data-2.csv"]
    staged = dict(manager.put_files)
    assert set(staged) == {"inputs/data.csv", "inputs/data-2.csv"}
    assert staged["inputs/data.csv"] != staged["inputs/data-2.csv"]  # no clobber


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
