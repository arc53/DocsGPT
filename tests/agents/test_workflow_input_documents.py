"""Workflow input-document bridge: uploaded attachments become run-scoped artifacts.

The agent pre-creates the ``workflow_runs`` row, re-persists each attachment's bytes
through the canonical artifact path (server-side size/sha256/storage key), and passes
the resulting references into the run as ``initial_inputs["input_documents"]`` so nodes
can read ``agent.input_documents``.
"""

from __future__ import annotations

import hashlib
import io
import uuid

import pytest
from sqlalchemy import text

from application.agents.workflow_agent import WorkflowAgent, _MAX_INPUT_DOCUMENTS
from application.agents.workflows.schemas import AgentNodeConfig
from application.agents.workflows.workflow_engine import (
    _EXTRACT_TRUNCATION_ID,
    WorkflowEngine,
)
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.local import LocalStorage
from application.storage.storage_creator import StorageCreator

pytestmark = pytest.mark.integration

OWNER = "user-bridge"
# A distinct caller for the shared-agent case (caller != workflow owner).
RUNNER = "user-runner"


def _wire(pg_engine, tmp_path, monkeypatch) -> LocalStorage:
    """Point storage + the db session at the ephemeral fixtures."""
    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(StorageCreator, "_instance", storage, raising=False)
    monkeypatch.setattr("application.storage.db.session.get_engine", lambda: pg_engine)
    return storage


def _make_workflow(pg_engine, owner: str = OWNER) -> str:
    """Insert an owned workflow row and return its id."""
    wf_id = str(uuid.uuid4())
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflows (id, user_id, name, current_graph_version) "
                "VALUES (CAST(:id AS uuid), :uid, :name, 1)"
            ),
            {"id": wf_id, "uid": owner, "name": "Bridge WF"},
        )
    return wf_id


def _stage_attachment(storage: LocalStorage, data: bytes, filename: str, mime: str) -> dict:
    """Write attachment bytes to storage and return the attachment dict shape."""
    upload_path = f"inputs/{OWNER}/attachments/{uuid.uuid4()}_{filename}"
    storage.save_file(io.BytesIO(data), upload_path)
    return {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "upload_path": upload_path,
        "path": upload_path,
        "mime_type": mime,
        "size": len(data),
        "user_id": OWNER,
    }


def _agent(workflow_id, attachments, owner: str = OWNER) -> WorkflowAgent:
    """Build a WorkflowAgent without invoking the LLM-creating base __init__."""
    agent = WorkflowAgent.__new__(WorkflowAgent)
    agent.workflow_id = workflow_id
    agent.workflow_owner = owner
    agent.decoded_token = {"sub": owner}
    agent.attachments = attachments
    agent.chat_history = []
    agent.retrieved_docs = []
    agent._workflow_data = None
    agent._engine = None
    agent._run_persisted = False
    agent._bridge_error = None
    return agent


_EMBEDDED_GRAPH = {
    "name": "Draft",
    "nodes": [
        {"id": "n1", "type": "start", "title": "Start"},
        {"id": "n2", "type": "end", "title": "End", "data": {}},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}


class _RecordingEngine(WorkflowEngine):
    """Engine that records initial_inputs and runs the run-row existence probe."""

    probe = None
    instances: list = []

    def __init__(self, graph, agent, workflow_run_id=None):
        super().__init__(graph, agent, workflow_run_id=workflow_run_id)
        self.captured_inputs = None
        _RecordingEngine.instances.append(self)

    def execute(self, initial_inputs, query):
        self.captured_inputs = initial_inputs
        if _RecordingEngine.probe is not None:
            _RecordingEngine.probe(self.workflow_run_id)
        self._initialize_state(initial_inputs, query)
        return iter(())


def _patch_engine(monkeypatch, probe=None) -> None:
    """Make ``_gen_inner`` build the recording engine and reset its capture state."""
    _RecordingEngine.instances = []
    _RecordingEngine.probe = probe
    monkeypatch.setattr(
        "application.agents.workflow_agent.WorkflowEngine", _RecordingEngine
    )


def test_attachments_bridge_to_run_scoped_artifacts(pg_engine, tmp_path, monkeypatch):
    """N attachments -> N run-scoped artifacts + input_documents refs; nodes can read them."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)

    a1 = b"report-one-bytes"
    a2 = b"second attachment payload"
    attachments = [
        _stage_attachment(storage, a1, "report.txt", "text/plain"),
        _stage_attachment(storage, a2, "data.csv", "text/csv"),
    ]
    agent = _agent(wf_id, attachments)

    run_seen = {}

    def _probe(run_id):
        with pg_engine.connect() as conn:
            run_seen["row"] = WorkflowRunsRepository(conn).get(run_id)

    _patch_engine(monkeypatch, probe=_probe)

    list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]

    # The run row existed BEFORE execute (so a mid-run download would authz).
    assert run_seen["row"] is not None
    assert run_seen["row"]["user_id"] == OWNER

    # initial_inputs carried the refs into the run.
    refs = engine.captured_inputs["input_documents"]
    assert len(refs) == 2
    assert {r["filename"] for r in refs} == {"report.txt", "data.csv"}
    assert all(r["artifact_id"] for r in refs)
    assert refs[0]["ref"] == "A1"
    assert refs[1]["ref"] == "A2"

    # N run-scoped artifacts persisted, parented to THIS run, server-computed size/sha256.
    run_id = engine.workflow_run_id
    with pg_engine.connect() as conn:
        repo = ArtifactsRepository(conn)
        by_name = {}
        for ref, payload in zip(refs, (a1, a2)):
            artifact = repo.get_artifact_in_parent(ref["artifact_id"], workflow_run_id=run_id)
            assert artifact is not None
            assert artifact["kind"] == "file"
            version = repo.get_version(ref["artifact_id"], 1)
            assert version["size"] == len(payload)
            assert version["sha256"] == hashlib.sha256(payload).hexdigest()
            by_name[version["filename"]] = version
    assert set(by_name) == {"report.txt", "data.csv"}
    assert by_name["report.txt"]["size"] == len(a1)

    # A node/template can read agent.input_documents from the engine state.
    context = engine._build_template_context()
    assert context["agent"]["input_documents"] == refs
    assert len(context["agent"]["input_documents"]) == 2

    # The bytes round-trip from storage (never entered state).
    with pg_engine.connect() as conn:
        v = ArtifactsRepository(conn).get_version(refs[0]["artifact_id"], 1)
    with storage.get_file(v["storage_path"]) as fh:
        assert fh.read() == a1


def test_shared_agent_run_and_artifacts_owned_by_caller(pg_engine, tmp_path, monkeypatch):
    """Shared agent (caller != owner): the run + bridged artifacts are owned by the caller.

    The workflow row is still resolved against its owner, but the run.user_id and
    the artifact owner are the caller, so quota is charged to the uploader and the
    caller (not the agent owner) can read the run's artifacts.
    """
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine, owner=OWNER)

    attachments = [_stage_attachment(storage, b"caller-doc", "c.txt", "text/plain")]
    agent = _agent(wf_id, attachments, owner=OWNER)
    # Simulate a shared-agent invocation: caller identity differs from the owner.
    agent.initial_user_id = RUNNER
    agent.user = RUNNER

    _patch_engine(monkeypatch)
    list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]
    run_id = engine.workflow_run_id

    with pg_engine.connect() as conn:
        run = WorkflowRunsRepository(conn).get(run_id)
        assert run is not None
        # The run is owned by the caller, not the workflow owner.
        assert run["user_id"] == RUNNER

        refs = engine.captured_inputs["input_documents"]
        assert len(refs) == 1
        owner_row = conn.execute(
            text("SELECT user_id FROM artifacts WHERE workflow_run_id = CAST(:r AS uuid)"),
            {"r": run_id},
        ).fetchone()
        assert owner_row[0] == RUNNER

    # authz: the caller can reach the run's artifacts; the agent owner cannot.
    # ``authorize_artifact`` uses the passed conn but reads ``request.args`` for a
    # share token, so it needs a request context.
    from flask import Flask

    from application.api.user.artifacts.authz import Principal, authorize_artifact

    app = Flask(__name__)
    with app.test_request_context():
        with pg_engine.connect() as conn:
            artifact = ArtifactsRepository(conn).get_artifact(refs[0]["artifact_id"])
            assert authorize_artifact(conn, artifact, Principal(user_id=RUNNER)) is True
            assert authorize_artifact(conn, artifact, Principal(user_id=OWNER)) is False


def test_code_state_excludes_chat_history(pg_engine, tmp_path, monkeypatch):
    """A code node's state.json projection omits the caller's chat_history."""
    _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)
    agent = _agent(wf_id, [], owner=OWNER)
    agent.chat_history = [{"prompt": "secret question", "response": "secret answer"}]

    _patch_engine(monkeypatch)
    list(agent._gen_inner("do it", log_context=None))
    engine = _RecordingEngine.instances[-1]

    projected = engine._json_safe_state()
    # chat_history is set in state but must never be staged for sandboxed code.
    assert "chat_history" in engine.state
    assert "chat_history" not in projected
    # Legitimate state (the query, node inputs) is still exposed.
    assert projected.get("query") == "do it"


def test_attachments_capped_per_run(pg_engine, tmp_path, monkeypatch):
    """More than the cap of attachments bridges only the cap; the rest are dropped."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)

    over = _MAX_INPUT_DOCUMENTS + 5
    attachments = [
        _stage_attachment(storage, f"doc-{i}".encode(), f"f{i}.txt", "text/plain")
        for i in range(over)
    ]
    agent = _agent(wf_id, attachments)
    _patch_engine(monkeypatch)

    list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]

    refs = engine.captured_inputs["input_documents"]
    assert len(refs) == _MAX_INPUT_DOCUMENTS

    run_id = engine.workflow_run_id
    with pg_engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM artifacts WHERE workflow_run_id = CAST(:r AS uuid)"
            ),
            {"r": run_id},
        ).scalar()
    assert n == _MAX_INPUT_DOCUMENTS


def test_run_row_precreated_before_execute(pg_engine, tmp_path, monkeypatch):
    """An owned workflow pre-inserts the run row keyed by the engine run id."""
    _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)
    agent = _agent(wf_id, [])
    _patch_engine(monkeypatch)

    list(agent._gen_inner("go", log_context=None))
    engine = _RecordingEngine.instances[-1]

    with pg_engine.connect() as conn:
        run = WorkflowRunsRepository(conn).get(engine.workflow_run_id)
    assert run is not None
    assert run["user_id"] == OWNER
    assert str(run["workflow_id"]) == wf_id
    # Finalized to a terminal status after the run completes.
    assert run["status"] == "completed"
    assert run["ended_at"] is not None


def test_unowned_workflow_creates_no_run_row(pg_engine, tmp_path, monkeypatch):
    """A draft/unowned workflow id never persists a run row and skips the bridge."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    # Embedded (draft) graph whose id is NOT an owned workflow row: the run
    # executes but no run row is persisted and the bridge is skipped.
    attachments = [_stage_attachment(storage, b"x", "f.txt", "text/plain")]
    agent = _agent(str(uuid.uuid4()), attachments)
    agent._workflow_data = _EMBEDDED_GRAPH
    _patch_engine(monkeypatch)

    list(agent._gen_inner("go", log_context=None))
    engine = _RecordingEngine.instances[-1]

    with pg_engine.connect() as conn:
        run = WorkflowRunsRepository(conn).get(engine.workflow_run_id)
        # No bridged artifacts either (would be orphaned without a parent row).
        n = conn.execute(
            text(
                "SELECT count(*) FROM artifacts WHERE workflow_run_id = CAST(:r AS uuid)"
            ),
            {"r": engine.workflow_run_id},
        ).scalar()
    assert run is None
    assert n == 0
    assert engine.captured_inputs["input_documents"] == []


def test_no_attachments_run_still_works(pg_engine, tmp_path, monkeypatch):
    """A run with no attachments produces empty input_documents and no artifacts."""
    _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)
    agent = _agent(wf_id, [])
    _patch_engine(monkeypatch)

    list(agent._gen_inner("go", log_context=None))
    engine = _RecordingEngine.instances[-1]

    assert engine.captured_inputs["input_documents"] == []
    with pg_engine.connect() as conn:
        run = WorkflowRunsRepository(conn).get(engine.workflow_run_id)
        n = conn.execute(
            text(
                "SELECT count(*) FROM artifacts WHERE workflow_run_id = CAST(:r AS uuid)"
            ),
            {"r": engine.workflow_run_id},
        ).scalar()
    assert run is not None
    assert n == 0


def test_quota_exceeded_fails_run_and_does_not_execute(pg_engine, tmp_path, monkeypatch):
    """Over quota: the bridge raises, an error is surfaced, the run is finalized FAILED,
    and the engine never executes with silently-missing documents."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)
    attachments = [_stage_attachment(storage, b"doc", "d.txt", "text/plain")]
    agent = _agent(wf_id, attachments)
    _patch_engine(monkeypatch)

    from application.sandbox.artifacts_capture import QuotaExceeded

    def _raise_quota(**kwargs):
        raise QuotaExceeded("artifact storage quota reached")

    monkeypatch.setattr(
        "application.sandbox.artifacts_capture.persist_new_artifact", _raise_quota
    )

    events = list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]

    # A fatal error was surfaced on the stream, flagged user_facing so the route's
    # sanitize_api_error does not rewrite the "quota" wording into a rate-limit message.
    errors = [e for e in events if e.get("type") == "error"]
    assert errors and "quota" in errors[0]["error"].lower()
    assert errors[0].get("user_facing") is True
    # The engine never executed (execute was not reached -> no captured inputs).
    assert engine.captured_inputs is None
    # The pre-created RUNNING row was finalized FAILED (not left dangling), and no
    # artifact rows were persisted for the run.
    with pg_engine.connect() as conn:
        run = WorkflowRunsRepository(conn).get(engine.workflow_run_id)
        n = conn.execute(
            text("SELECT count(*) FROM artifacts WHERE workflow_run_id = CAST(:r AS uuid)"),
            {"r": engine.workflow_run_id},
        ).scalar()
    assert run is not None
    assert run["status"] == "failed"
    assert n == 0


def test_oversize_declared_attachment_skipped_with_notice(pg_engine, tmp_path, monkeypatch):
    """A declared-oversize attachment is dropped with a surfaced notice; the run still proceeds."""
    from application.core.settings import settings

    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)
    att = _stage_attachment(storage, b"tiny", "big.txt", "text/plain")
    att["size"] = int(settings.ARTIFACT_MAX_BYTES) + 1  # declared past the per-file cap
    agent = _agent(wf_id, [att])
    _patch_engine(monkeypatch)

    events = list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]

    # The oversize doc was dropped -> no input documents bridged, but the run ran.
    assert engine.captured_inputs is not None
    assert engine.captured_inputs["input_documents"] == []
    # A non-fatal notice naming the dropped document was surfaced as a ``notice``
    # (NOT an ``error``, which is terminal client-side) so the run still completes.
    notices = [e for e in events if e.get("type") == "notice"]
    assert notices and "big.txt" in notices[0]["notice"]
    # It must not be an error event (that would fail the turn and disable reconnect).
    assert not [e for e in events if e.get("type") == "error"]
    # Nothing was persisted for the oversize doc.
    with pg_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM artifacts WHERE workflow_run_id = CAST(:r AS uuid)"),
            {"r": engine.workflow_run_id},
        ).scalar()
    assert n == 0


def test_read_attachment_bytes_closes_handle_on_bounded_read():
    """The bounded read pulls at most max_bytes+1 and always closes the storage handle."""

    class _Handle:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self.closed = False

        def read(self, n: int = -1) -> bytes:
            return self._data if n is None or n < 0 else self._data[:n]

        def close(self) -> None:
            self.closed = True

    handle = _Handle(b"x" * 100)

    class _Storage:
        def get_file(self, _path):
            return handle

    data = WorkflowAgent._read_attachment_bytes(_Storage(), "p", max_bytes=10)
    assert data == b"x" * 11  # bounded to max_bytes + 1 (backstops a lying size)
    assert handle.closed is True  # handle is never left open


def test_extract_parse_opts_out_of_sync_subtask_guard(monkeypatch):
    """_parse_document_text awaits with disable_sync_subtasks=False so it works inside a Celery worker."""
    agent = _agent(str(uuid.uuid4()), [])
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.agent = agent
    engine.workflow_run_id = "run-extract"

    import application.api.user.tasks as tasks

    captured: dict = {}

    class _FakeAsyncResult:
        def __init__(self):
            self.get_kwargs = None

        def get(self, timeout=None, disable_sync_subtasks=True):
            self.get_kwargs = {"timeout": timeout, "disable_sync_subtasks": disable_sync_subtasks}
            return {"status": "ok", "content": "parsed markdown"}

    def _apply_async(args=None, queue=None, **kw):
        result = _FakeAsyncResult()
        captured["result"] = result
        captured["args"] = args
        return result

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)

    out = engine._parse_document_text("artifact-xyz")

    assert out == "parsed markdown"
    # A prefork worker's task_join_will_block() is process-wide, so the await must
    # opt out of the guard or get() raises RuntimeError("Never call result.get()...").
    assert captured["result"].get_kwargs["disable_sync_subtasks"] is False
    # The run-scoped parent + resolved id reached the parsing task.
    assert captured["args"][0] == "artifact-xyz"
    assert captured["args"][1] == {"workflow_run_id": "run-extract"}


def _engine_for_parse(monkeypatch, get_impl):
    """Engine wired to a fake ``parse_document`` whose ``get`` is ``get_impl``."""
    import application.api.user.tasks as tasks

    agent = _agent(str(uuid.uuid4()), [])
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.agent = agent
    engine.workflow_run_id = "run-budget"

    captured: dict = {}

    class _FakeAsyncResult:
        def get(self, timeout=None, disable_sync_subtasks=True):
            captured.setdefault("timeouts", []).append(timeout)
            return get_impl(timeout)

    def _apply_async(args=None, queue=None, **kw):
        captured.setdefault("limits", []).append(kw)
        return _FakeAsyncResult()

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)
    return engine, captured


def test_parse_await_is_clamped_to_the_node_budget(monkeypatch):
    """A node's parses share one wall clock; they do not each get a full window.

    WORKFLOW_NODE_EXTRACT_MAX_FILES documents serialized at the full per-document
    window would hold a web threadpool slot for max_files x the maximum timeout.
    """
    import time

    engine, captured = _engine_for_parse(
        monkeypatch, lambda timeout: {"status": "ok", "content": "md"}
    )

    # 100s of a 900s budget already spent by earlier documents in this node.
    deadline = time.monotonic() + 100.0
    out = engine._parse_document_text(
        "artifact-1", size=25 * 1024 * 1024, deadline=deadline
    )

    assert out == "md"
    granted = captured["timeouts"][0]
    assert 0 < granted <= 100.0, "the await must not outlive the node's budget"


def test_parse_is_skipped_once_the_node_budget_is_spent(monkeypatch, caplog):
    """An exhausted budget skips the document instead of starting a new window."""
    import logging
    import time

    def _never_called(timeout):
        raise AssertionError("no parse may be enqueued past the budget")

    engine, captured = _engine_for_parse(monkeypatch, _never_called)

    with caplog.at_level(logging.WARNING):
        out = engine._parse_document_text(
            "artifact-2", size=1024, deadline=time.monotonic() - 1.0
        )

    assert out is None
    assert not captured.get("timeouts")
    assert "budget" in caplog.text


def test_parse_without_a_deadline_keeps_the_size_scaled_window(monkeypatch):
    """The per-document scaling is the point of the feature; keep it intact."""
    from application.api.user.tasks import parse_timeout_for_size

    engine, captured = _engine_for_parse(
        monkeypatch, lambda timeout: {"status": "ok", "content": "md"}
    )

    size = 13 * 1024 * 1024
    engine._parse_document_text("artifact-3", size=size)

    assert captured["timeouts"][0] == parse_timeout_for_size(size)


def test_node_extract_path_capped_with_truncation_note(pg_engine, tmp_path, monkeypatch):
    """A node referencing more docs than the extract cap parses only up to the cap and notes the rest."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)

    # docx is non-native (no vision) and not inline-text, so each routes through
    # the blocking parsing worker -- the path the per-node cap must bound.
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    attachments = [
        _stage_attachment(storage, f"doc-{i}".encode(), f"f{i}.docx", docx)
        for i in range(4)
    ]
    agent = _agent(wf_id, attachments)
    _patch_engine(monkeypatch)
    list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]

    # Cap the blocking-extract path below the doc count so the overflow truncates.
    from application.core.settings import settings

    monkeypatch.setattr(settings, "WORKFLOW_NODE_EXTRACT_MAX_FILES", 2, raising=False)

    # Stub the parsing worker so each non-text doc "parses" without a broker, and
    # count the blocking calls to prove the overflow docs are never enqueued.
    import application.api.user.tasks as tasks

    parse_calls = {"n": 0}

    class _R:
        def get(self, timeout=None, disable_sync_subtasks=True):
            return {"status": "ok", "content": "PARSED"}

    def _apply_async(args=None, queue=None, **kw):
        parse_calls["n"] += 1
        return _R()

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)

    node_config = AgentNodeConfig(input_documents=["*"])
    out = engine._materialize_node_attachments(node_config, "Reviewer", supported_types=[])

    notes = [a for a in out if a.get("id") == _EXTRACT_TRUNCATION_ID]
    extracted = [a for a in out if a.get("id") != _EXTRACT_TRUNCATION_ID]
    # Only the cap was extracted; the remaining docs were never sent to the worker.
    assert len(extracted) == 2
    assert parse_calls["n"] == 2
    # A single non-fatal truncation note is appended to the node's inlined text.
    assert len(notes) == 1
    assert notes[0]["mime_type"] == "text/plain"
    assert "omitted" in notes[0]["content"].lower()


def test_node_extract_cap_bounds_parse_attempts_even_when_every_parse_times_out(
    pg_engine, tmp_path, monkeypatch
):
    """The cap must bound parse ATTEMPTS, not successes: a degraded backend where every
    parse times out (~120s each) must still issue at most the cap's worth of blocking calls."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError

    storage = _wire(pg_engine, tmp_path, monkeypatch)
    wf_id = _make_workflow(pg_engine)

    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    attachments = [
        _stage_attachment(storage, f"doc-{i}".encode(), f"f{i}.docx", docx)
        for i in range(4)
    ]
    agent = _agent(wf_id, attachments)
    _patch_engine(monkeypatch)
    list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]

    from application.core.settings import settings

    monkeypatch.setattr(settings, "WORKFLOW_NODE_EXTRACT_MAX_FILES", 2, raising=False)

    import application.api.user.tasks as tasks

    parse_calls = {"n": 0}

    class _R:
        def get(self, timeout=None, disable_sync_subtasks=True):
            raise CeleryTimeoutError()  # the ~120s worst case the cap must bound

    def _apply_async(args=None, queue=None, **kw):
        parse_calls["n"] += 1
        return _R()

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)

    node_config = AgentNodeConfig(input_documents=["*"])
    out = engine._materialize_node_attachments(node_config, "Reviewer", supported_types=[])

    # Every parse timed out (nothing extracted), but blocking attempts were bounded.
    extracted = [a for a in out if a.get("id") != _EXTRACT_TRUNCATION_ID]
    assert extracted == []
    assert parse_calls["n"] == 2  # not 4 -- failed parses still consume cap budget
    notes = [a for a in out if a.get("id") == _EXTRACT_TRUNCATION_ID]
    assert len(notes) == 1


# ---------------------------------------------------------------------------
# Reuse of the text ``store_attachment`` already extracted (no double OCR)
# ---------------------------------------------------------------------------

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_OK_EXTRACTION = {
    "status": "ok",
    "parser": "DoclingParser",
    "truncated": False,
    "original_tokens": 12,
    "stored_tokens": 12,
}


def _with_extraction(attachment: dict, content, extraction=_OK_EXTRACTION) -> dict:
    """Add the ``content`` + ``metadata.extraction`` shape ``store_attachment`` persists."""
    attachment["content"] = content
    attachment["metadata"] = {} if extraction is None else {"extraction": dict(extraction)}
    return attachment


def _forbid_parse(monkeypatch) -> None:
    """Make any enqueue of the parsing worker a hard failure."""
    import application.api.user.tasks as tasks

    def _apply_async(*a, **k):
        raise AssertionError("the document must not be re-parsed")

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)


def _count_parses(monkeypatch, calls: dict) -> None:
    """Stub the parsing worker so each blocking parse succeeds and is counted."""
    import application.api.user.tasks as tasks

    class _R:
        def get(self, timeout=None, disable_sync_subtasks=True):
            return {"status": "ok", "content": "PARSED"}

    def _apply_async(args=None, queue=None, **kw):
        calls["n"] = calls.get("n", 0) + 1
        return _R()

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)


def _bridged_engine(pg_engine, tmp_path, monkeypatch, attachments):
    """Run the bridge for ``attachments`` and return (engine, refs)."""
    wf_id = _make_workflow(pg_engine)
    agent = _agent(wf_id, attachments)
    _patch_engine(monkeypatch)
    list(agent._gen_inner("summarize", log_context=None))
    engine = _RecordingEngine.instances[-1]
    return engine, engine.captured_inputs["input_documents"]


def test_preextracted_attachment_text_is_reused_without_reparsing(
    pg_engine, tmp_path, monkeypatch
):
    """An attachment already parsed at upload time is inlined verbatim; the worker is never called."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    att = _with_extraction(
        _stage_attachment(storage, b"PK-docx-bytes", "scan.docx", DOCX_MIME),
        "PRE-EXTRACTED OCR TEXT",
    )
    engine, refs = _bridged_engine(pg_engine, tmp_path, monkeypatch, [att])

    # The text rides on the engine only -- never in the persisted run state/refs.
    aid = refs[0]["artifact_id"]
    assert engine.preextracted_text == {aid: "PRE-EXTRACTED OCR TEXT"}
    assert set(refs[0]) == {"artifact_id", "ref", "filename", "mime_type"}
    assert "content" not in str(engine.state["input_documents"])

    _forbid_parse(monkeypatch)
    out = engine._materialize_node_attachments(
        AgentNodeConfig(input_documents=["*"]), "Reviewer", supported_types=[]
    )

    assert out == [{"id": aid, "mime_type": "text/plain", "content": "PRE-EXTRACTED OCR TEXT"}]


def test_preextracted_text_is_bounded_head_and_tail(pg_engine, tmp_path, monkeypatch):
    """Reused text goes through the same head+tail window as the inline-text path."""
    from application.parser.document_reader import _TEXT_MAX_BYTES

    storage = _wire(pg_engine, tmp_path, monkeypatch)
    big = "A" * (_TEXT_MAX_BYTES * 3)
    att = _with_extraction(
        _stage_attachment(storage, b"PK-docx-bytes", "huge.docx", DOCX_MIME), big
    )
    engine, _ = _bridged_engine(pg_engine, tmp_path, monkeypatch, [att])

    _forbid_parse(monkeypatch)
    out = engine._materialize_node_attachments(
        AgentNodeConfig(input_documents=["*"]), "Reviewer", supported_types=[]
    )

    content = out[0]["content"]
    assert "...[truncated" in content
    assert len(content.encode("utf-8")) < _TEXT_MAX_BYTES + 200


def test_truncated_attachment_text_falls_through_to_parse(pg_engine, tmp_path, monkeypatch):
    """A row cut at ATTACHMENT_MAX_TOKENS lost its tail, so the node re-parses instead."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    att = _with_extraction(
        _stage_attachment(storage, b"PK-docx-bytes", "long.docx", DOCX_MIME),
        "HEAD ONLY",
        extraction={**_OK_EXTRACTION, "truncated": True},
    )
    engine, _ = _bridged_engine(pg_engine, tmp_path, monkeypatch, [att])

    assert engine.preextracted_text == {}
    calls: dict = {}
    _count_parses(monkeypatch, calls)
    out = engine._materialize_node_attachments(
        AgentNodeConfig(input_documents=["*"]), "Reviewer", supported_types=[]
    )

    assert calls["n"] == 1
    assert out[0]["content"] == "PARSED"


def test_failed_or_empty_attachment_text_falls_through_to_parse(
    pg_engine, tmp_path, monkeypatch
):
    """An empty/whitespace ``content`` (or a failed extraction) is never reused."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    empty = _with_extraction(
        _stage_attachment(storage, b"PK-a", "empty.docx", DOCX_MIME), "   "
    )
    failed = _with_extraction(
        _stage_attachment(storage, b"PK-b", "failed.docx", DOCX_MIME),
        None,
        extraction={"status": "failed", "parser": None, "truncated": False, "error": "boom"},
    )
    engine, _ = _bridged_engine(pg_engine, tmp_path, monkeypatch, [empty, failed])

    assert engine.preextracted_text == {}
    calls: dict = {}
    _count_parses(monkeypatch, calls)
    out = engine._materialize_node_attachments(
        AgentNodeConfig(input_documents=["*"]), "Reviewer", supported_types=[]
    )

    assert calls["n"] == 2
    assert [a["content"] for a in out] == ["PARSED", "PARSED"]


def test_legacy_row_without_extraction_metadata_is_trusted(pg_engine, tmp_path, monkeypatch):
    """A pre-``extraction`` row with non-empty content is reused (nothing records otherwise)."""
    storage = _wire(pg_engine, tmp_path, monkeypatch)
    att = _stage_attachment(storage, b"PK-docx-bytes", "legacy.docx", DOCX_MIME)
    att["content"] = "LEGACY TEXT"  # no ``metadata`` key at all
    engine, refs = _bridged_engine(pg_engine, tmp_path, monkeypatch, [att])

    assert engine.preextracted_text == {refs[0]["artifact_id"]: "LEGACY TEXT"}
    _forbid_parse(monkeypatch)
    out = engine._materialize_node_attachments(
        AgentNodeConfig(input_documents=["*"]), "Reviewer", supported_types=[]
    )
    assert out[0]["content"] == "LEGACY TEXT"


def test_preextracted_docs_do_not_consume_the_extract_cap(pg_engine, tmp_path, monkeypatch):
    """Reused text costs no blocking parse, so it must not spend the per-node parse budget."""
    from application.core.settings import settings

    storage = _wire(pg_engine, tmp_path, monkeypatch)
    attachments = [
        _with_extraction(
            _stage_attachment(storage, b"PK-0", "pre0.docx", DOCX_MIME), "REUSED 0"
        ),
        _with_extraction(
            _stage_attachment(storage, b"PK-1", "pre1.docx", DOCX_MIME), "REUSED 1"
        ),
        _stage_attachment(storage, b"PK-2", "raw2.docx", DOCX_MIME),
        _stage_attachment(storage, b"PK-3", "raw3.docx", DOCX_MIME),
    ]
    engine, _ = _bridged_engine(pg_engine, tmp_path, monkeypatch, attachments)

    monkeypatch.setattr(settings, "WORKFLOW_NODE_EXTRACT_MAX_FILES", 2, raising=False)
    calls: dict = {}
    _count_parses(monkeypatch, calls)

    out = engine._materialize_node_attachments(
        AgentNodeConfig(input_documents=["*"]), "Reviewer", supported_types=[]
    )

    # All four documents made it in: the two reused ones did not spend cap budget,
    # so both remaining documents still fit the cap of 2 blocking parses.
    assert [a["content"] for a in out] == ["REUSED 0", "REUSED 1", "PARSED", "PARSED"]
    assert calls["n"] == 2
    assert not [a for a in out if a.get("id") == _EXTRACT_TRUNCATION_ID]


@pytest.mark.parametrize(
    "attachment,expected",
    [
        ({"content": "text", "metadata": {"extraction": {"status": "ok", "truncated": False}}}, "text"),
        ({"content": "text", "metadata": {"extraction": {"status": "ok", "truncated": True}}}, None),
        ({"content": "text", "metadata": {"extraction": {"status": "failed"}}}, None),
        ({"content": "text", "metadata": {}}, "text"),
        ({"content": "text"}, "text"),
        ({"content": "text", "metadata": {"extraction": "nope"}}, None),
        ({"content": "", "metadata": {"extraction": {"status": "ok", "truncated": False}}}, None),
        ({"content": None}, None),
        ({}, None),
    ],
)
def test_usable_attachment_text_matrix(attachment, expected):
    """Only whole, successfully-extracted, non-empty text is eligible for reuse."""
    assert WorkflowAgent._usable_attachment_text(attachment) == expected
