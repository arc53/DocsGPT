"""Tests for ``file_passing: lines`` and the ``documents`` state key.

The engine reads each input document once per run into ``[D#:L#]`` numbered
text and hands every node the same numbering. Fakes stand in for the
artifacts repo, storage, the parsing queue, Redis and the sandbox.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
from docsgpt.agents.workflows.run_documents import (
    DocumentsTooLargeError,
    WorkflowDocumentError,
)
from docsgpt.agents.workflows.schemas import (
    AgentNodeConfig,
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from docsgpt.agents.workflows.workflow_engine import WorkflowEngine
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository

RUN_ID = "22222222-2222-2222-2222-222222222222"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _artifact(mime: str, filename: str, *, data: bytes = b"", sha256: str = None, version: int = 1):
    aid = str(uuid.uuid4())
    return aid, {
        "current_version": version,
        "title": filename,
        "versions": {
            version: {
                "storage_path": f"store/{aid}/v{version}",
                "mime_type": mime,
                "filename": filename,
                "size": len(data),
                "sha256": sha256,
                "data": data,
            }
        },
    }


def _patch_repo(monkeypatch, artifacts: Dict[str, Dict[str, Any]]) -> None:
    def _in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
        art = artifacts.get(artifact_id)
        if art is None or workflow_run_id != RUN_ID:
            return None
        return {"current_version": art["current_version"], "title": art["title"]}

    def _version(self, artifact_id, version):
        art = artifacts.get(artifact_id)
        return art["versions"].get(version) if art else None

    @contextlib.contextmanager
    def _fake_db_readonly():
        yield object()

    monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _fake_db_readonly)
    monkeypatch.setattr(ArtifactsRepository, "__init__", lambda self, conn=None: None)
    monkeypatch.setattr(ArtifactsRepository, "artifact_id_at_position", lambda self, n, **kw: None)
    monkeypatch.setattr(ArtifactsRepository, "resolve_id_by_ref_seq", lambda self, n, **kw: None, raising=False)
    monkeypatch.setattr(ArtifactsRepository, "get_artifact_in_parent", _in_parent)
    monkeypatch.setattr(ArtifactsRepository, "get_version", _version)

    class _Storage:
        def get_file(self, path):
            for art in artifacts.values():
                for version in art["versions"].values():
                    if version["storage_path"] == path:
                        return SimpleNamespace(read=lambda *a, d=version["data"]: d, close=lambda: None)
            raise FileNotFoundError(path)

    monkeypatch.setattr(
        "docsgpt.storage.storage_creator.StorageCreator.get_storage", staticmethod(lambda: _Storage())
    )


class _FakeAsyncResult:
    def __init__(self, result=None, error: Exception = None):
        self._result = result
        self._error = error

    def get(self, timeout=None, disable_sync_subtasks=True):
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture()
def parse_queue(monkeypatch):
    """Stand-in for the ``parse_document`` task; records each dispatch."""
    import docsgpt.api.user.tasks as tasks

    calls: List[Dict[str, Any]] = []
    replies: Dict[str, Any] = {}

    def _apply_async(args=None, queue=None, **kwargs):
        calls.append({"args": args, "queue": queue, "kwargs": kwargs})
        reply = replies.get(args[0], {"status": "ok", "lines": [f"parsed {args[0][:4]}"], "tables": []})
        if isinstance(reply, Exception):
            return _FakeAsyncResult(error=reply)
        return _FakeAsyncResult(reply)

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)
    return SimpleNamespace(calls=calls, replies=replies)


class _FakeRedis:
    def __init__(self):
        self.store: Dict[str, bytes] = {}
        self.ttls: Dict[str, int] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: None)


def _engine(input_ids: List[str] = ()) -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Lines"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="k",
        chat_history=[],
        user="user-1",
        decoded_token={"sub": "user-1"},
    )
    engine = WorkflowEngine(graph, agent, workflow_run_id=RUN_ID)
    engine.state["input_documents"] = [{"artifact_id": aid} for aid in input_ids]
    return engine


def _lines_config(documents=("*",)) -> AgentNodeConfig:
    return AgentNodeConfig(input_documents=list(documents), file_passing="lines")


# ---------------------------------------------------------------------------
# Numbering and attachments
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_accepts_lines():
    assert AgentNodeConfig(file_passing="lines").file_passing == "lines"


@pytest.mark.unit
def test_lines_attachment_numbers_each_document(monkeypatch, parse_queue):
    a1, r1 = _artifact("text/plain", "notes.txt", data=b"first\n\nsecond")
    a2, r2 = _artifact("text/csv", "items.csv", data=b"Item,Qty\nBolt,10")
    _patch_repo(monkeypatch, {a1: r1, a2: r2})
    engine = _engine([a1, a2])

    out = engine._materialize_node_attachments(_lines_config(), "Extract", [])

    assert [a["id"] for a in out] == [a1, a2]
    assert all(a["mime_type"] == "text/plain" for a in out)
    assert out[0]["content"].endswith("[D1:L1] first\n[D1:L2] second")
    assert out[1]["content"].endswith("[D2:L1] Item | Qty\n[D2:L2] Bolt | 10")
    assert "items.csv" in out[1]["content"]
    # Text formats are read in-process, never sent to the parsing queue.
    assert parse_queue.calls == []


@pytest.mark.unit
def test_document_number_follows_input_documents_not_the_node_selection(monkeypatch, parse_queue):
    a1, r1 = _artifact("text/plain", "a.txt", data=b"alpha")
    a2, r2 = _artifact("text/plain", "b.txt", data=b"beta")
    _patch_repo(monkeypatch, {a1: r1, a2: r2})
    engine = _engine([a1, a2])

    out = engine._materialize_node_attachments(_lines_config([a2]), "Second only", [])

    assert len(out) == 1
    assert out[0]["content"].endswith("[D2:L1] beta")
    assert [d["id"] for d in engine.state["documents"]] == ["D2"]


@pytest.mark.unit
def test_documents_outside_the_run_inputs_are_numbered_after_them(monkeypatch, parse_queue):
    a1, r1 = _artifact("text/plain", "a.txt", data=b"alpha")
    produced, r2 = _artifact("text/plain", "report.txt", data=b"made by code")
    _patch_repo(monkeypatch, {a1: r1, produced: r2})
    engine = _engine([a1])
    engine.state["report"] = {"artifact_id": produced}

    engine._materialize_node_attachments(_lines_config(["report", "*"]), "Node", [])

    assert [(d["id"], d["artifact_id"]) for d in engine.state["documents"]] == [("D1", a1), ("D2", produced)]


@pytest.mark.unit
def test_binary_documents_parse_on_the_parsing_queue(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    parse_queue.replies[aid] = {
        "status": "ok",
        "lines": ["3.2. Delivery time", "Item | Qty | Price"],
        "tables": [{"first_line": 2, "last_line": 2, "header": ["Item", "Qty", "Price"]}],
    }
    engine = _engine([aid])

    out = engine._materialize_node_attachments(_lines_config(), "Node", [])

    assert len(parse_queue.calls) == 1
    call = parse_queue.calls[0]
    assert call["args"][0] == aid
    assert call["args"][1] == {"workflow_run_id": RUN_ID}
    assert call["args"][3]["output"] == "lines"
    assert out[0]["content"].endswith("[D1:L1] 3.2. Delivery time\n[D1:L2] Item | Qty | Price")
    entry = engine.state["documents"][0]
    assert entry["tables"] == [{"first_line": 2, "last_line": 2, "header": ["Item", "Qty", "Price"]}]
    assert entry["line_count"] == 2
    assert entry["filename"] == "contract.docx"
    assert entry["mime_type"] == DOCX


@pytest.mark.unit
def test_two_nodes_in_one_run_parse_each_document_once(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    engine = _engine([aid])

    first = engine._materialize_node_attachments(_lines_config(), "First", [])
    second = engine._materialize_node_attachments(_lines_config(), "Second", [])
    engine._format_template("{{ documents[0].text }}")

    assert len(parse_queue.calls) == 1
    assert first == second


@pytest.mark.unit
def test_a_new_artifact_version_is_parsed_again(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    engine = _engine([aid])
    engine._materialize_node_attachments(_lines_config(), "First", [])

    rec["versions"][2] = dict(rec["versions"][1], storage_path=f"store/{aid}/v2")
    rec["current_version"] = 2
    engine._materialize_node_attachments(_lines_config(), "Second", [])

    assert len(parse_queue.calls) == 2


@pytest.mark.unit
def test_several_documents_are_dispatched_before_any_is_awaited(monkeypatch, parse_queue):
    a1, r1 = _artifact(DOCX, "a.docx", data=b"PK1")
    a2, r2 = _artifact(DOCX, "b.docx", data=b"PK2")
    _patch_repo(monkeypatch, {a1: r1, a2: r2})
    order: List[str] = []
    real_apply = parse_queue.calls

    import docsgpt.api.user.tasks as tasks

    def _apply_async(args=None, queue=None, **kwargs):
        order.append(f"dispatch {args[0]}")
        real_apply.append(args)

        class _Result:
            def get(self, timeout=None, disable_sync_subtasks=True):
                order.append(f"await {args[0]}")
                return {"status": "ok", "lines": ["x"], "tables": []}

        return _Result()

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)
    engine = _engine([a1, a2])

    engine._materialize_node_attachments(_lines_config(), "Node", [])

    assert order == [f"dispatch {a1}", f"dispatch {a2}", f"await {a1}", f"await {a2}"]


# ---------------------------------------------------------------------------
# Failures are explicit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_failed_parse_fails_the_node_naming_the_document(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    parse_queue.replies[aid] = {"status": "error", "error": "could not read the docx document."}
    engine = _engine([aid])

    with pytest.raises(WorkflowDocumentError, match=r'"contract\.docx".*could not read the docx document'):
        engine._materialize_node_attachments(_lines_config(), "Node", [])


@pytest.mark.unit
def test_a_parse_timeout_fails_the_node(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    parse_queue.replies[aid] = TimeoutError()
    engine = _engine([aid])

    with pytest.raises(WorkflowDocumentError, match="in time"):
        engine._materialize_node_attachments(_lines_config(), "Node", [])


@pytest.mark.unit
def test_a_document_missing_from_the_run_fails_the_node(monkeypatch, parse_queue):
    _patch_repo(monkeypatch, {})
    engine = _engine([])

    with pytest.raises(WorkflowDocumentError, match="not found in this run"):
        engine._materialize_node_attachments(_lines_config(["A7"]), "Node", [])


@pytest.mark.unit
def test_an_oversized_document_fails_instead_of_being_skipped(monkeypatch, parse_queue):
    from docsgpt.core.settings import settings

    aid, rec = _artifact("text/plain", "big.txt", data=b"x" * 64)
    _patch_repo(monkeypatch, {aid: rec})
    monkeypatch.setattr(settings, "DOCUMENT_PARSE_MAX_BYTES", 16)
    engine = _engine([aid])

    with pytest.raises(WorkflowDocumentError, match="too large"):
        engine._materialize_node_attachments(_lines_config(), "Node", [])


@pytest.mark.unit
def test_documents_that_do_not_fit_the_model_fail_with_a_size_error(monkeypatch, parse_queue):
    aid, rec = _artifact("text/plain", "big.txt", data=("word " * 400).encode())
    _patch_repo(monkeypatch, {aid: rec})
    monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda model_id, user_id=None: 200)
    engine = _engine([aid])
    attachments = engine._materialize_node_attachments(_lines_config(), "Node", [])

    with pytest.raises(DocumentsTooLargeError) as caught:
        engine._check_documents_fit(attachments, "system", "query", "small-model", "user-1")

    assert caught.value.available_tokens == 180
    assert caught.value.needed_tokens > 180
    assert "small-model" in str(caught.value)


@pytest.mark.unit
def test_documents_that_fit_pass_the_size_check(monkeypatch, parse_queue):
    aid, rec = _artifact("text/plain", "small.txt", data=b"short")
    _patch_repo(monkeypatch, {aid: rec})
    monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda model_id, user_id=None: 100_000)
    engine = _engine([aid])
    attachments = engine._materialize_node_attachments(_lines_config(), "Node", [])

    engine._check_documents_fit(attachments, "system", "query", "big-model", "user-1")


# ---------------------------------------------------------------------------
# Cross-run cache
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_line_text_is_cached_by_content_hash_across_runs(monkeypatch, parse_queue):
    redis = _FakeRedis()
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
    first_id, first = _artifact(DOCX, "contract.docx", data=b"PK...", sha256="abc123")
    second_id, second = _artifact(DOCX, "contract-copy.docx", data=b"PK...", sha256="abc123")
    _patch_repo(monkeypatch, {first_id: first, second_id: second})
    parse_queue.replies[first_id] = {"status": "ok", "lines": ["cached line"], "tables": []}

    _engine([first_id])._materialize_node_attachments(_lines_config(), "Node", [])
    out = _engine([second_id])._materialize_node_attachments(_lines_config(), "Node", [])

    assert len(parse_queue.calls) == 1
    assert out[0]["content"].endswith("[D1:L1] cached line")
    assert "contract-copy.docx" in out[0]["content"]
    assert len(redis.store) == 1 and all(ttl > 0 for ttl in redis.ttls.values())


@pytest.mark.unit
def test_a_zero_ttl_turns_the_cache_off(monkeypatch, parse_queue):
    from docsgpt.core.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
    monkeypatch.setattr(settings, "WORKFLOW_DOCUMENT_LINES_CACHE_TTL", 0)
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...", sha256="abc123")
    _patch_repo(monkeypatch, {aid: rec})

    _engine([aid])._materialize_node_attachments(_lines_config(), "Node", [])

    assert redis.store == {}


# ---------------------------------------------------------------------------
# State, templates and code nodes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_snapshots_keep_document_metadata_but_not_the_text(monkeypatch, parse_queue):
    aid, rec = _artifact("text/plain", "notes.txt", data=b"secret body")
    _patch_repo(monkeypatch, {aid: rec})
    engine = _engine([aid])
    engine._materialize_node_attachments(_lines_config(), "Node", [])

    assert "secret body" in engine.state["documents"][0]["text"]
    delta = engine._state_delta({})
    snapshot = engine.snapshot_state()
    for projected in (delta["documents"], snapshot["documents"]):
        assert projected == [
            {
                "id": "D1",
                "artifact_id": aid,
                "filename": "notes.txt",
                "mime_type": "text/plain",
                "line_count": 1,
                "tables": [],
            }
        ]
    assert "secret body" not in json.dumps(delta, default=str)
    assert "secret body" not in json.dumps(snapshot, default=str)


@pytest.mark.unit
def test_a_documents_value_the_workflow_set_itself_is_snapshotted_whole():
    engine = _engine([])
    engine.state["documents"] = [{"text": "my own list"}]

    assert engine.snapshot_state()["documents"] == [{"text": "my own list"}]


@pytest.mark.unit
def test_a_template_that_reads_documents_loads_every_input_document(monkeypatch, parse_queue):
    a1, r1 = _artifact("text/plain", "a.txt", data=b"alpha")
    a2, r2 = _artifact("text/plain", "b.txt", data=b"beta")
    _patch_repo(monkeypatch, {a1: r1, a2: r2})
    engine = _engine([a1, a2])

    rendered = engine._format_template(
        "{% for d in documents %}{{ d.id }}={{ d.line_count }};{% endfor %}{{ agent.documents[1].text }}"
    )

    assert rendered == "D1=1;D2=1;[D2:L1] beta"


@pytest.mark.unit
def test_a_template_that_only_mentions_the_word_does_not_load_documents(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "a.docx", data=b"PK")
    _patch_repo(monkeypatch, {aid: rec})
    engine = _engine([aid])

    assert engine._format_template("Summarize the documents for {{ query }}") == "Summarize the documents for "
    assert parse_queue.calls == []
    assert "documents" not in engine.state


class _FakeManager:
    def __init__(self):
        self.put_files = []

    def open(self, session_id, ttl=None):
        return session_id

    def put_file(self, session_id, dest_path, data):
        self.put_files.append((dest_path, data))

    def exec(self, session_id, code, timeout=None):
        return SimpleNamespace(ok=True, stdout="", runtime_invalidated=False, error_name=None, error_value=None)

    def close(self, session_id):
        pass


@pytest.mark.unit
def test_a_code_node_reads_documents_from_state_json(monkeypatch, parse_queue):
    aid, rec = _artifact("text/plain", "notes.txt", data=b"line one\nline two")
    _patch_repo(monkeypatch, {aid: rec})
    manager = _FakeManager()
    monkeypatch.setattr("docsgpt.sandbox.sandbox_creator.SandboxCreator.get_manager", lambda: manager)
    monkeypatch.setattr("docsgpt.sandbox.artifacts_capture.snapshot_signatures", lambda *a, **k: {})
    monkeypatch.setattr("docsgpt.sandbox.artifacts_capture.capture_artifacts", lambda *a, **k: [])
    engine = _engine([aid])
    node = WorkflowNode(
        id="code_1",
        workflow_id="wf",
        type=NodeType.CODE,
        title="Check",
        config={"code": "print(1)", "inputs": ["documents"]},
    )

    list(engine._execute_code_node(node))

    staged = dict(manager.put_files)
    assert list(staged) == ["state.json"]
    state = json.loads(staged["state.json"])
    assert state["documents"][0]["text"] == "[D1:L1] line one\n[D1:L2] line two"


# ---------------------------------------------------------------------------
# Agent node wiring
# ---------------------------------------------------------------------------


class _StubNodeAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.tool_executor = None
        self.attachments = []
        self.llm = SimpleNamespace(get_supported_attachment_types=lambda: ["image/png", "application/pdf"])

    def gen(self, _prompt):
        yield {"answer": "ok"}


def _agent_node(node_id: str = "agent_1", title: str = "Extract") -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        workflow_id="wf",
        type=NodeType.AGENT,
        title=title,
        config={
            "system_prompt": "Extract the terms.",
            "stream_to_user": False,
            "input_documents": ["*"],
            "file_passing": "lines",
        },
    )


@pytest.fixture()
def stub_agents(monkeypatch):
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _p: "k")
    created: List[_StubNodeAgent] = []

    def _create(**kwargs):
        agent = _StubNodeAgent(**kwargs)
        created.append(agent)
        return agent

    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(_create))
    return created


@pytest.mark.unit
def test_an_agent_node_gets_numbered_text_even_for_native_types(monkeypatch, parse_queue, stub_agents):
    aid, rec = _artifact("application/pdf", "report.pdf", data=b"%PDF")
    _patch_repo(monkeypatch, {aid: rec})
    parse_queue.replies[aid] = {"status": "ok", "lines": ["(p.1) Total due"], "tables": []}
    engine = _engine([aid])

    list(engine._execute_agent_node(_agent_node()))

    agent = stub_agents[0]
    assert agent.attachments[0]["mime_type"] == "text/plain"
    assert agent.attachments[0]["content"].endswith("[D1:L1] (p.1) Total due")
    assert "[D#:L#]" in agent.kwargs["prompt"]


@pytest.mark.unit
def test_an_oversized_run_fails_the_node_with_a_user_facing_size_error(monkeypatch, parse_queue, stub_agents):
    aid, rec = _artifact("text/plain", "big.txt", data=("word " * 400).encode())
    _patch_repo(monkeypatch, {aid: rec})
    monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda model_id, user_id=None: 200)
    start = WorkflowNode(id="start", workflow_id="wf", type=NodeType.START, title="Start")
    node = _agent_node()
    engine = _engine([aid])
    engine.graph = WorkflowGraph(
        workflow=Workflow(name="Lines"),
        nodes=[start, node],
        edges=[WorkflowEdge(id="e1", workflow_id="wf", source="start", target=node.id)],
    )

    events = list(engine._run_graph({"input_documents": engine.state["input_documents"]}, "go"))

    error = next(e for e in events if e.get("type") == "error")
    assert error["user_facing"] is True
    assert error["error"].startswith("Extract: ")
    assert "tokens" in error["error"]
    assert "code" not in error


@pytest.mark.unit
def test_two_agent_nodes_in_one_run_share_one_parse(monkeypatch, parse_queue, stub_agents):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    first, second = _agent_node("agent_1", "First"), _agent_node("agent_2", "Second")
    start = WorkflowNode(id="start", workflow_id="wf", type=NodeType.START, title="Start")
    engine = _engine([aid])
    engine.graph = WorkflowGraph(
        workflow=Workflow(name="Lines"),
        nodes=[start, first, second],
        edges=[
            WorkflowEdge(id="e1", workflow_id="wf", source="start", target=first.id),
            WorkflowEdge(id="e2", workflow_id="wf", source=first.id, target=second.id),
        ],
    )

    events = list(engine._run_graph({"input_documents": engine.state["input_documents"]}, "go"))

    assert not [e for e in events if e.get("type") == "error"]
    assert len(parse_queue.calls) == 1
    assert stub_agents[0].attachments == stub_agents[1].attachments
    for event in events:
        assert "parsed" not in json.dumps(event.get("state_delta", {}), default=str)


@pytest.mark.unit
def test_inside_a_celery_worker_documents_parse_in_process(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "contract.docx", data=b"PK...")
    _patch_repo(monkeypatch, {aid: rec})
    monkeypatch.setattr("docsgpt.celery_init.in_worker", lambda: True)
    inline_calls = []

    def _run_parse_document(artifact_id, parent, user_id, options):
        inline_calls.append((artifact_id, parent, user_id, options))
        return {"status": "ok", "lines": ["inline"], "tables": []}

    monkeypatch.setattr("docsgpt.worker.run_parse_document", _run_parse_document)
    engine = _engine([aid])

    out = engine._materialize_node_attachments(_lines_config(), "Node", [])

    assert parse_queue.calls == []
    assert inline_calls == [(aid, {"workflow_run_id": RUN_ID}, "user-1", {"output": "lines"})]
    assert out[0]["content"].endswith("[D1:L1] inline")


# ---------------------------------------------------------------------------
# Review follow-ups
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_cache_key_separates_identical_bytes_under_another_extension(monkeypatch, parse_queue):
    redis = _FakeRedis()
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
    data = b"Item,Qty\nBolt,10"
    as_txt, r1 = _artifact("text/plain", "data.txt", data=data, sha256="same")
    as_csv, r2 = _artifact("text/csv", "data.csv", data=data, sha256="same")
    _patch_repo(monkeypatch, {as_txt: r1, as_csv: r2})

    _engine([as_txt])._materialize_node_attachments(_lines_config(), "Node", [])
    out = _engine([as_csv])._materialize_node_attachments(_lines_config(), "Node", [])

    assert out[0]["content"].endswith("[D1:L1] Item | Qty\n[D1:L2] Bolt | 10")
    assert len(redis.store) == 2


@pytest.mark.unit
def test_snapshots_drop_table_header_values(monkeypatch, parse_queue):
    aid, rec = _artifact("text/csv", "people.csv", data=b"Alice Smith,555-0100\nBob,555-0101")
    _patch_repo(monkeypatch, {aid: rec})
    engine = _engine([aid])
    engine._materialize_node_attachments(_lines_config(), "Node", [])

    assert engine.state["documents"][0]["tables"][0]["header"] == ["Alice Smith", "555-0100"]
    assert engine.snapshot_state()["documents"][0]["tables"] == [{"first_line": 1, "last_line": 2}]
    assert "Alice" not in json.dumps(engine._state_delta({}), default=str)


@pytest.mark.unit
def test_a_code_node_that_does_not_ask_gets_no_document_text(monkeypatch, parse_queue):
    aid, rec = _artifact("text/plain", "notes.txt", data=b"private line")
    _patch_repo(monkeypatch, {aid: rec})
    manager = _FakeManager()
    monkeypatch.setattr("docsgpt.sandbox.sandbox_creator.SandboxCreator.get_manager", lambda: manager)
    monkeypatch.setattr("docsgpt.sandbox.artifacts_capture.snapshot_signatures", lambda *a, **k: {})
    monkeypatch.setattr("docsgpt.sandbox.artifacts_capture.capture_artifacts", lambda *a, **k: [])
    engine = _engine([aid])
    engine._materialize_node_attachments(_lines_config(), "Earlier node", [])
    node = WorkflowNode(id="code_1", workflow_id="wf", type=NodeType.CODE, title="Other", config={"code": "print(1)"})

    list(engine._execute_code_node(node))

    state = json.loads(dict(manager.put_files)["state.json"])
    assert "documents" not in state
    assert "private line" not in dict(manager.put_files)["state.json"].decode()


@pytest.mark.unit
def test_a_template_reading_a_workflow_owned_documents_value_reads_no_files(monkeypatch, parse_queue):
    aid, rec = _artifact(DOCX, "a.docx", data=b"PK")
    _patch_repo(monkeypatch, {aid: rec})
    engine = _engine([aid])
    engine.state["documents"] = ["mine"]

    assert engine._format_template("{{ documents[0] }}") == "mine"
    assert parse_queue.calls == []


@pytest.mark.unit
def test_the_cache_key_separates_identical_bytes_under_another_mime_type(monkeypatch, parse_queue):
    redis = _FakeRedis()
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
    as_text, r1 = _artifact("text/plain", "data.custom", data=b"hello", sha256="same")
    as_binary, r2 = _artifact("application/octet-stream", "data.custom", data=b"hello", sha256="same")
    _patch_repo(monkeypatch, {as_text: r1, as_binary: r2})
    parse_queue.replies[as_binary] = {"status": "error", "error": "unsupported file type '.custom'."}

    _engine([as_text])._materialize_node_attachments(_lines_config(), "Node", [])

    with pytest.raises(WorkflowDocumentError, match="unsupported file type"):
        _engine([as_binary])._materialize_node_attachments(_lines_config(), "Node", [])


@pytest.mark.unit
@pytest.mark.parametrize(
    "setting, before, after",
    [
        ("OCR_ENGINE", "tesseract", "rapidocr"),
        ("OCR_LANGS", "eng", "eng+deu"),
        ("OCR_RENDER_DPI", 200, 300),
        ("DOC_PARSER_ENGINE", "anydoc", "docling"),
    ],
)
def test_changing_a_parser_setting_misses_the_cache(monkeypatch, parse_queue, setting, before, after):
    from docsgpt.core.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
    aid, rec = _artifact(DOCX, "scan.docx", data=b"PK", sha256="same")
    _patch_repo(monkeypatch, {aid: rec})

    monkeypatch.setattr(settings, setting, before)
    _engine([aid])._materialize_node_attachments(_lines_config(), "Node", [])
    monkeypatch.setattr(settings, setting, after)
    _engine([aid])._materialize_node_attachments(_lines_config(), "Node", [])

    assert len(parse_queue.calls) == 2
    assert len(redis.store) == 2


@pytest.mark.unit
def test_a_credential_change_keeps_the_cache(monkeypatch, parse_queue):
    from docsgpt.core.settings import settings

    redis = _FakeRedis()
    monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
    aid, rec = _artifact(DOCX, "scan.docx", data=b"PK", sha256="same")
    _patch_repo(monkeypatch, {aid: rec})

    monkeypatch.setattr(settings, "OCR_DEEPSEEK_API_KEY", "old")
    _engine([aid])._materialize_node_attachments(_lines_config(), "Node", [])
    monkeypatch.setattr(settings, "OCR_DEEPSEEK_API_KEY", "rotated")
    _engine([aid])._materialize_node_attachments(_lines_config(), "Node", [])

    assert len(parse_queue.calls) == 1
