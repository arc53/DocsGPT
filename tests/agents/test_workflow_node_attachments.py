"""Unit tests for native/extracted document passing to workflow AGENT nodes.

These exercise the engine's ``_materialize_node_attachments`` policy and the
``_execute_agent_node`` wiring with a fake artifacts repo (no live DB / storage /
sandbox / LLM). The run-scoped authz gate, the auto/native/extract policy matrix,
the caps, and the no-selection regression path are all covered here.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from application.agents.workflows.node_agent import WorkflowNodeAgentFactory
from application.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowGraph,
    WorkflowNode,
)
from application.agents.workflows.workflow_engine import WorkflowEngine
from application.storage.db.repositories.artifacts import ArtifactsRepository

RUN_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _patch_repo(monkeypatch, artifacts: Dict[str, Dict[str, Any]], run_id: str = RUN_ID) -> None:
    """Patch db_readonly + the three repo methods the engine calls so it reads the fake data.

    The repo CLASS is left intact (transitive ``from ... import ArtifactsRepository``
    bindings are untouched); only the methods the resolver uses are redirected, which
    monkeypatch reverts cleanly on teardown.
    """
    # 1-based position order = insertion order of ids belonging to this run.
    positions = [aid for aid, a in artifacts.items() if a.get("run_id") == run_id]

    def _at_position(self, n, *, conversation_id=None, workflow_run_id=None):
        if workflow_run_id != run_id or not isinstance(n, int) or n < 1 or n > len(positions):
            return None
        return positions[n - 1]

    def _in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
        art = artifacts.get(artifact_id)
        if art is None or art.get("run_id") != workflow_run_id:
            return None
        return {"current_version": art["current_version"], "title": art.get("title")}

    def _version(self, artifact_id, version):
        art = artifacts.get(artifact_id)
        return art["versions"].get(version) if art is not None else None

    @contextlib.contextmanager
    def _fake_db_readonly():
        yield object()

    monkeypatch.setattr("application.storage.db.session.db_readonly", _fake_db_readonly)
    monkeypatch.setattr(ArtifactsRepository, "__init__", lambda self, conn=None: None)
    monkeypatch.setattr(ArtifactsRepository, "artifact_id_at_position", _at_position)
    monkeypatch.setattr(ArtifactsRepository, "get_artifact_in_parent", _in_parent)
    monkeypatch.setattr(ArtifactsRepository, "get_version", _version)


def _artifact(run_id, mime, *, filename="doc", size=10, version=1, storage_path=None):
    """Build a fake artifact record with a single current version."""
    aid = str(uuid.uuid4())
    return aid, {
        "run_id": run_id,
        "current_version": version,
        "title": filename,
        "versions": {
            version: {
                "storage_path": storage_path or f"store/{aid}",
                "mime_type": mime,
                "filename": filename,
                "size": size,
            }
        },
    }


def _engine(monkeypatch, run_id: str = RUN_ID) -> WorkflowEngine:
    graph = WorkflowGraph(workflow=Workflow(name="Attach Test"), nodes=[], edges=[])
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="test-key",
        chat_history=[],
        user="user-1",
        decoded_token={"sub": "user-1"},
    )
    return WorkflowEngine(graph, agent, workflow_run_id=run_id)


# Provider supported-types lists, mirroring what ``llm.get_supported_attachment_types()``
# returns -- the engine now decides native-eligibility from this same source.
VISION_TYPES = ["image/png", "image/jpeg"]
TEXT_TYPES: list = []


# ---------------------------------------------------------------------------
# _resolve_input_artifact_ids: tokens, lists, refs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_star_token_expands_to_all_input_documents(monkeypatch):
    """``*`` expands to every ref in state['input_documents']."""
    eng = _engine(monkeypatch)
    eng.state["input_documents"] = [
        {"artifact_id": "aaa"}, {"artifact_id": "bbb"}, {"not": "a ref"},
    ]
    assert eng._resolve_input_artifact_ids(["*"]) == ["aaa", "bbb"]
    assert eng._resolve_input_artifact_ids(["input_documents"]) == ["aaa", "bbb"]


@pytest.mark.unit
def test_state_var_single_ref_and_list_of_refs(monkeypatch):
    """A state var may hold a single ref dict or a list of ref dicts."""
    eng = _engine(monkeypatch)
    eng.state["one"] = {"artifact_id": "x1"}
    eng.state["many"] = [{"artifact_id": "y1"}, {"artifact_id": "y2"}]
    assert eng._resolve_input_artifact_ids(["one"]) == ["x1"]
    assert eng._resolve_input_artifact_ids(["many"]) == ["y1", "y2"]


@pytest.mark.unit
def test_raw_id_and_short_ref_pass_through(monkeypatch):
    """A raw id or short ref that is not a state key passes through verbatim."""
    eng = _engine(monkeypatch)
    assert eng._resolve_input_artifact_ids(["A1", "abc-id"]) == ["A1", "abc-id"]


# ---------------------------------------------------------------------------
# _materialize_node_attachments: policy matrix
# ---------------------------------------------------------------------------


def _node_config(**kwargs):
    from application.agents.workflows.schemas import AgentNodeConfig

    return AgentNodeConfig(**kwargs)


@pytest.mark.unit
def test_auto_image_goes_native_for_vision_model(monkeypatch):
    """auto + image mime + vision model -> a native attachment {id, mime_type, path}."""
    aid, rec = _artifact(RUN_ID, "image/png", filename="chart.png")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)

    assert out == [{"id": aid, "mime_type": "image/png", "path": rec["versions"][1]["storage_path"]}]


@pytest.mark.unit
def test_auto_pdf_native_when_model_supports_images(monkeypatch):
    """auto + PDF + vision (image) model -> native (synthetic PDF-to-image path)."""
    aid, rec = _artifact(RUN_ID, "application/pdf", filename="r.pdf")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)

    assert out[0]["mime_type"] == "application/pdf"
    assert "path" in out[0] and "content" not in out[0]


@pytest.mark.unit
def test_auto_text_only_model_extracts_to_content(monkeypatch):
    """auto + text-only model -> extracted/inlined text content, non-native mime."""
    aid, rec = _artifact(RUN_ID, "text/plain", filename="notes.txt")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _FakeStorage(b"hello world")),
    )
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", TEXT_TYPES)

    assert out == [{"id": aid, "mime_type": "text/plain", "content": "hello world"}]


@pytest.mark.unit
def test_extract_always_inlines_text_even_for_vision_model(monkeypatch):
    """file_passing=extract inlines text even when the model could take it natively."""
    aid, rec = _artifact(RUN_ID, "text/markdown", filename="r.md")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _FakeStorage(b"# Title")),
    )
    cfg = _node_config(input_documents=[aid], file_passing="extract")

    out = eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)

    assert out == [{"id": aid, "mime_type": "text/plain", "content": "# Title"}]


@pytest.mark.unit
def test_native_on_unsupported_mime_raises(monkeypatch):
    """file_passing=native on a mime the model can't read raises a clear error."""
    aid, rec = _artifact(RUN_ID, "application/pdf", filename="r.pdf")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    cfg = _node_config(input_documents=[aid], file_passing="native", model_id="gpt-4o-mini")

    with pytest.raises(ValueError, match="cannot read"):
        eng._materialize_node_attachments(cfg, "MyNode", TEXT_TYPES)


@pytest.mark.unit
def test_extract_non_text_uses_parse_worker(monkeypatch):
    """A non-text mime under extract routes through the parsing-worker path (no sandbox)."""
    aid, rec = _artifact(RUN_ID, "application/vnd.openxmlformats", filename="r.docx")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    monkeypatch.setattr(
        WorkflowEngine, "_parse_document_text", lambda self, artifact_id: "EXTRACTED MD"
    )
    cfg = _node_config(input_documents=[aid], file_passing="extract")

    out = eng._materialize_node_attachments(cfg, "Node", TEXT_TYPES)

    assert out == [{"id": aid, "mime_type": "text/plain", "content": "EXTRACTED MD"}]


# ---------------------------------------------------------------------------
# Security: cross-run / forged refs are rejected, never attached
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cross_run_artifact_is_rejected(monkeypatch):
    """An artifact belonging to a different run yields None at the gate -> ValueError."""
    aid, rec = _artifact("99999999-9999-9999-9999-999999999999", "image/png")
    _patch_repo(monkeypatch, {aid: rec})  # run scope is RUN_ID; artifact is in another run
    eng = _engine(monkeypatch)
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    with pytest.raises(ValueError, match="not found in this run"):
        eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)


@pytest.mark.unit
def test_forged_uuid_is_rejected(monkeypatch):
    """A forged uuid never matches the run-scoped gate -> ValueError, nothing attached."""
    aid, rec = _artifact(RUN_ID, "image/png")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    forged = str(uuid.uuid4())
    cfg = _node_config(input_documents=[forged], file_passing="auto")

    with pytest.raises(ValueError, match="not found in this run"):
        eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_native_file_cap_bounds_native_then_extracts(monkeypatch):
    """More than the native cap: the first N go native, the rest are extracted."""
    monkeypatch.setattr(
        "application.core.settings.settings.WORKFLOW_NODE_NATIVE_MAX_FILES", 2, raising=False
    )
    artifacts = {}
    ids = []
    for i in range(4):
        aid, rec = _artifact(RUN_ID, "image/png", filename=f"i{i}.png")
        artifacts[aid] = rec
        ids.append(aid)
    _patch_repo(monkeypatch, artifacts)
    eng = _engine(monkeypatch)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _FakeStorage(b"img-bytes")),
    )
    # extract of a non-text image routes through the parsing worker; stub it so it returns text.
    monkeypatch.setattr(
        WorkflowEngine, "_parse_document_text", lambda self, artifact_id: "fallback text"
    )
    cfg = _node_config(input_documents=ids, file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)

    native = [a for a in out if "path" in a]
    extracted = [a for a in out if "content" in a]
    assert len(native) == 2
    assert len(extracted) == 2


@pytest.mark.unit
def test_oversize_file_is_skipped(monkeypatch):
    """A file past the per-file byte ceiling is dropped, not attached."""
    monkeypatch.setattr(
        "application.core.settings.settings.SANDBOX_MAX_INPUT_BYTES", 5, raising=False
    )
    aid, rec = _artifact(RUN_ID, "image/png", size=999)
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)

    assert out == []


@pytest.mark.unit
def test_oversize_text_skipped_by_post_read_guard_when_size_missing(monkeypatch):
    """A NULL/missing version size skips the pre-read cap; the post-read byte guard still drops it."""
    monkeypatch.setattr(
        "application.core.settings.settings.SANDBOX_MAX_INPUT_BYTES", 5, raising=False
    )
    # size=None bypasses the ``isinstance(size, int)`` pre-read check; the actual
    # bytes (longer than the 5-byte cap) must be rejected after reading.
    aid, rec = _artifact(RUN_ID, "text/plain", filename="big.txt", size=None)
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _FakeStorage(b"way over the cap")),
    )
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", TEXT_TYPES)

    assert out == []


@pytest.mark.unit
def test_large_under_cap_text_is_windowed_not_inlined_whole(monkeypatch):
    """A large-but-under-cap text file is bounded to a head+tail window, not inlined whole."""
    from application.parser.document_reader import _TEXT_MAX_BYTES as _MARKDOWN_MAX_BYTES

    big_text = ("A" * (_MARKDOWN_MAX_BYTES * 3)).encode("utf-8")
    aid, rec = _artifact(RUN_ID, "text/plain", filename="notes.txt", size=len(big_text))
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        staticmethod(lambda: _FakeStorage(big_text)),
    )
    cfg = _node_config(input_documents=[aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", TEXT_TYPES)

    assert len(out) == 1
    content = out[0]["content"]
    assert "...[truncated" in content
    # Bounded to roughly the window, far below the whole 3x payload.
    assert len(content.encode("utf-8")) < _MARKDOWN_MAX_BYTES + 200


@pytest.mark.unit
def test_duplicate_refs_attach_once(monkeypatch):
    """A duplicated/expanded ref resolves once so the same artifact is not attached twice."""
    aid, rec = _artifact(RUN_ID, "image/png", filename="dup.png")
    _patch_repo(monkeypatch, {aid: rec})
    eng = _engine(monkeypatch)
    eng.state["input_documents"] = [{"artifact_id": aid}]
    cfg = _node_config(input_documents=["*", aid], file_passing="auto")

    out = eng._materialize_node_attachments(cfg, "Node", VISION_TYPES)

    assert out == [{"id": aid, "mime_type": "image/png", "path": rec["versions"][1]["storage_path"]}]


# ---------------------------------------------------------------------------
# _execute_agent_node wiring
# ---------------------------------------------------------------------------


class _StubLLM:
    """Minimal LLM stub exposing the provider's supported-types list (the native source)."""

    def __init__(self, supported_types):
        self._supported_types = supported_types

    def get_supported_attachment_types(self):
        return self._supported_types


class _StubNodeAgent:
    """Captures the factory kwargs and yields a fixed answer (no LLM call)."""

    def __init__(self, *, supported_types=None, **kwargs):
        self.kwargs = kwargs
        self.tool_executor = None
        self.attachments = []
        self.llm = _StubLLM(supported_types if supported_types is not None else [])

    def gen(self, _prompt):
        yield {"answer": "ok"}


def _agent_node(input_documents=None, file_passing="auto", node_id="agent_1") -> WorkflowNode:
    config = {
        "agent_type": "classic",
        "system_prompt": "You are a helpful assistant.",
        "prompt_template": "",
        "stream_to_user": False,
        "tools": [],
    }
    if input_documents is not None:
        config["input_documents"] = input_documents
        config["file_passing"] = file_passing
    return WorkflowNode(
        id=node_id,
        workflow_id="wf-1",
        type=NodeType.AGENT,
        title="Agent",
        position={"x": 0, "y": 0},
        config=config,
    )


def _patch_capabilities(monkeypatch):
    """Stub provider/api-key resolution (capabilities are only fetched for json_schema nodes)."""
    monkeypatch.setattr(
        "application.core.model_utils.get_model_capabilities",
        lambda model_id, user_id=None: None,
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_provider_from_model_id",
        lambda model_id, user_id=None: "openai",
    )
    monkeypatch.setattr(
        "application.core.model_utils.get_api_key_for_provider", lambda _p: "k"
    )


@pytest.mark.unit
def test_execute_agent_node_assigns_native_attachment_from_provider_types(monkeypatch):
    """A node with input_documents assigns a native attachment, decided from the provider's types."""
    aid, rec = _artifact(RUN_ID, "image/png", filename="c.png")
    _patch_repo(monkeypatch, {aid: rec})
    _patch_capabilities(monkeypatch)
    eng = _engine(monkeypatch)

    captured: dict = {}
    created: list = []

    def _create(**kwargs):
        captured.update(kwargs)
        agent = _StubNodeAgent(supported_types=VISION_TYPES, **kwargs)
        created.append(agent)
        return agent

    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(_create))

    node = _agent_node(input_documents=[aid], file_passing="auto")
    list(eng._execute_agent_node(node))

    # Attachments are assigned post-construction (BaseAgent reads them at gen time),
    # not passed through factory_kwargs.
    assert "attachments" not in captured
    assert created[0].attachments == [
        {"id": aid, "mime_type": "image/png", "path": rec["versions"][1]["storage_path"]}
    ]


@pytest.mark.unit
def test_execute_agent_node_native_decision_tracks_provider_types(monkeypatch):
    """A mime the provider does NOT support falls back to extracted text under ``auto``."""
    aid, rec = _artifact(RUN_ID, "image/png", filename="c.png")
    _patch_repo(monkeypatch, {aid: rec})
    _patch_capabilities(monkeypatch)
    monkeypatch.setattr(
        WorkflowEngine, "_parse_document_text", lambda self, artifact_id: "EXTRACTED"
    )
    eng = _engine(monkeypatch)

    created: list = []

    def _create(**kwargs):
        # Provider reports NO native types, so the registry-agnostic decision
        # must extract rather than send a native-but-empty attachment.
        agent = _StubNodeAgent(supported_types=[], **kwargs)
        created.append(agent)
        return agent

    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(_create))

    node = _agent_node(input_documents=[aid], file_passing="auto")
    list(eng._execute_agent_node(node))

    assert created[0].attachments == [
        {"id": aid, "mime_type": "text/plain", "content": "EXTRACTED"}
    ]


@pytest.mark.unit
def test_execute_agent_node_without_documents_has_no_attachments(monkeypatch):
    """A node without input_documents leaves attachments empty (no regression)."""
    _patch_capabilities(monkeypatch)
    eng = _engine(monkeypatch)

    captured: dict = {}
    created: list = []

    def _create(**kwargs):
        captured.update(kwargs)
        agent = _StubNodeAgent(supported_types=VISION_TYPES, **kwargs)
        created.append(agent)
        return agent

    monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(_create))

    node = _agent_node(input_documents=None)
    list(eng._execute_agent_node(node))

    assert "attachments" not in captured
    assert created[0].attachments == []


class _FakeStorage:
    """Minimal storage stub: get_file(path).read() -> fixed bytes."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def get_file(self, _path):
        return _FakeFile(self._data)


class _FakeFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data
