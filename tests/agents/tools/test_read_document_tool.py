"""Unit tests for ReadDocumentTool: run-scoped input gate, enqueue+await, timeout/failure, schema, metadata.

The parse task is mocked (``parse_document.apply_async(...).get``) so no live
worker / DB / storage is touched; these cover the pre-enqueue run-scoped gate
(reject cross-tenant before enqueue), the await + degrade behavior, json_schema
validation, and the surfaced action params.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
import uuid
from typing import Any, Dict, Optional

import pytest

import application.agents.tools.read_document as rd
from application.agents.tools.read_document import ReadDocumentTool

_ART_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Run-scoped input resolution (mocks the repo gate)
# ---------------------------------------------------------------------------
def _stub_repo(
    monkeypatch, *, found: bool, conv: Optional[str], run: Optional[str],
    size: Optional[int] = None,
):
    class _Repo:
        def __init__(self, conn):
            pass

        def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
            if not found or n != 1:
                return None
            if conv is not None and conversation_id != conv:
                return None
            if run is not None and workflow_run_id != run:
                return None
            return _ART_ID

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            if not found:
                return None
            if conv is not None and conversation_id != conv:
                return None
            if run is not None and workflow_run_id != run:
                return None
            return {"id": artifact_id, "current_version": 1, "title": "statement.pdf"}

        def get_version(self, artifact_id, version):
            return {"storage_path": "s/1", "mime_type": "application/pdf", "size": size}

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(rd, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(rd, "ArtifactsRepository", _Repo)


class _FakeAsyncResult:
    def __init__(self, payload=None, exc=None):
        self._payload = payload
        self._exc = exc
        self.get_kwargs = None

    def get(self, timeout=None, disable_sync_subtasks=True):
        # ``read_document`` must pass ``disable_sync_subtasks=False`` so the await
        # works from inside a Celery worker (headless/scheduled agents).
        self.get_kwargs = {
            "timeout": timeout,
            "disable_sync_subtasks": disable_sync_subtasks,
        }
        if self._exc is not None:
            raise self._exc
        return self._payload


def _patch_task(monkeypatch, *, payload=None, exc=None):
    """Patch parse_document.apply_async so no broker is touched; capture call args."""
    import application.api.user.tasks as tasks

    captured: Dict[str, Any] = {}

    def _apply_async(args=None, queue=None, **kw):
        captured["args"] = args
        captured["queue"] = queue
        captured["limits"] = kw
        result = _FakeAsyncResult(payload=payload, exc=exc)
        captured["result"] = result
        return result

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)
    return captured


def _tool(**config) -> ReadDocumentTool:
    base = {"conversation_id": "conv-1", "tool_id": "t-1"}
    base.update(config)
    return ReadDocumentTool(tool_config=base, user_id="u-1")


# ---------------------------------------------------------------------------
# Guards + metadata
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_unknown_action_rejected():
    out = _tool().execute_action("nope", input="a")
    assert out["status"] == "error" and "unknown action" in out["error"]


@pytest.mark.unit
def test_requires_user_and_parent():
    no_user = ReadDocumentTool({"conversation_id": "c"}, user_id=None)
    assert "user_id" in no_user.execute_action("read_document", input="a")["error"]
    no_parent = ReadDocumentTool({}, user_id="u")
    assert "conversation_id" in no_parent.execute_action("read_document", input="a")["error"]


@pytest.mark.unit
def test_input_required():
    assert "input artifact id is required" in _tool().execute_action("read_document", input="  ")["error"]


@pytest.mark.unit
def test_internal_flag_hides_from_catalog_only():
    # internal=True hides read_document from the Add-Tool catalog; it must
    # still instantiate (the synthetic-id execution path doesn't filter it).
    assert ReadDocumentTool.internal is True
    inst = ReadDocumentTool({"conversation_id": "c"}, user_id="u")
    assert inst.user_id == "u"


@pytest.mark.unit
def test_workflow_node_loads_read_document_run_scoped(monkeypatch):
    # A workflow node stamps workflow_run_id into the tool config; the tool
    # binds to the run (not a conversation) so the run-scoped artifact gate
    # applies. Mirrors ToolExecutor._get_or_load_tool stamping run + user.
    _stub_repo(monkeypatch, found=True, conv=None, run="run-9")
    captured = _patch_task(monkeypatch, payload={"status": "ok", "content": "x", "truncated": False})

    tool = ReadDocumentTool(
        tool_config={"workflow_run_id": "run-9", "tool_id": "t-1"}, user_id="u-1"
    )
    out = tool.execute_action("read_document", input=_ART_ID, persist=False)
    assert out["status"] == "ok"
    # The worker parent is the run, not a conversation.
    assert captured["args"][1] == {"workflow_run_id": "run-9"}
    assert captured["args"][2] == "u-1"


@pytest.mark.unit
def test_action_metadata_surfaces_new_params():
    meta = _tool().get_actions_metadata()[0]
    assert meta["name"] == "read_document"
    props = meta["parameters"]["properties"]
    for key in ("input", "output", "ocr", "pages", "engine", "max_chars", "include_tables", "persist", "json_schema"):
        assert key in props, key
    assert meta["parameters"]["required"] == ["input"]
    # No sandbox/Docling wording in the action description.
    assert "sandbox" not in meta["description"].lower()
    assert "docling" not in meta["description"].lower()


# ---------------------------------------------------------------------------
# Enqueue + await happy path
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_resolves_input_then_enqueues_and_returns_payload(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    payload = {"status": "ok", "output": "markdown", "content": "# Hi", "truncated": False}
    captured = _patch_task(monkeypatch, payload=payload)

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)

    assert out["status"] == "ok"
    assert out["content"] == "# Hi"
    # The task got the resolved id, the run-scoped parent, the user, and the parsing queue.
    assert captured["args"][0] == _ART_ID
    assert captured["args"][1] == {"conversation_id": "conv-1"}
    assert captured["args"][2] == "u-1"
    assert captured["queue"] == rd.settings.DOCUMENT_PARSE_QUEUE
    options = captured["args"][3]
    assert options["output"] == "markdown" and options["persist"] is False
    # The await must opt out of Celery's worker-self-deadlock guard, else it
    # raises RuntimeError from inside a prefork worker (headless/scheduled agents).
    assert captured["result"].get_kwargs["disable_sync_subtasks"] is False


@pytest.mark.unit
def test_short_ref_input_resolves(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    captured = _patch_task(monkeypatch, payload={"status": "ok", "content": "x", "truncated": False})

    out = _tool().execute_action("read_document", input="A1", persist=False)
    assert out["status"] == "ok"
    # The short ref was resolved to the real id BEFORE enqueue.
    assert captured["args"][0] == _ART_ID


@pytest.mark.unit
def test_artifact_ref_sets_last_artifact_id(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    payload = {"status": "ok", "content": "x", "truncated": False,
               "artifact": {"artifact_id": "new-art", "version": 1}}
    _patch_task(monkeypatch, payload=payload)

    tool = _tool()
    out = tool.execute_action("read_document", input=_ART_ID)
    assert out["artifact"]["artifact_id"] == "new-art"
    assert tool.get_artifact_id("read_document") == "new-art"


# ---------------------------------------------------------------------------
# Size-scaled parse window
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_parse_window_scales_with_the_input_size(monkeypatch):
    """A large input widens the await AND the task's per-call Celery time limits."""
    from application.api.user.tasks import parse_task_time_limits, parse_timeout_for_size

    size = 8 * 1024 * 1024
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None, size=size)
    captured = _patch_task(monkeypatch, payload={"status": "ok", "content": "x"})

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)

    expected = parse_timeout_for_size(size)
    assert out["status"] == "ok"
    assert captured["result"].get_kwargs["timeout"] == expected
    # The task's import-time soft limit is the BASE timeout, so the per-call limits
    # must be raised too or the worker kills the parse the caller is still awaiting.
    assert captured["limits"] == parse_task_time_limits(expected)
    assert captured["limits"]["soft_time_limit"] > rd.settings.DOCUMENT_PARSE_TIMEOUT


@pytest.mark.unit
def test_parse_window_falls_back_to_the_base_timeout_without_a_size(monkeypatch):
    """An unknown input size keeps the configured base timeout as the floor."""
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None, size=None)
    captured = _patch_task(monkeypatch, payload={"status": "ok", "content": "x"})

    _tool().execute_action("read_document", input=_ART_ID, persist=False)

    base = float(rd.settings.DOCUMENT_PARSE_TIMEOUT)
    assert captured["result"].get_kwargs["timeout"] == base
    assert captured["limits"]["soft_time_limit"] == int(base)


# ---------------------------------------------------------------------------
# Cross-tenant: rejected BEFORE enqueue
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_cross_tenant_rejected_before_enqueue(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-OTHER", run=None)
    enqueued = {"called": False}

    import application.api.user.tasks as tasks

    def _apply_async(*a, **k):
        enqueued["called"] = True
        raise AssertionError("must not enqueue a cross-tenant input")

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)
    assert out["status"] == "error" and "not found in this conversation/run" in out["error"]
    assert enqueued["called"] is False


@pytest.mark.unit
def test_missing_input_rejected_before_enqueue(monkeypatch):
    _stub_repo(monkeypatch, found=False, conv="conv-1", run=None)
    import application.api.user.tasks as tasks
    monkeypatch.setattr(
        tasks.parse_document, "apply_async",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enqueue")),
    )
    out = _tool().execute_action("read_document", input="ghost", persist=False)
    assert out["status"] == "error" and "not found" in out["error"]


# ---------------------------------------------------------------------------
# Timeout + task failure degrade to an error result (never hang/raise)
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_timeout_degrades_to_error(monkeypatch):
    from celery.exceptions import TimeoutError as CeleryTimeoutError

    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_task(monkeypatch, exc=CeleryTimeoutError("timed out"))

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)
    assert out["status"] == "error" and "timed out" in out["error"]


@pytest.mark.unit
def test_task_failure_degrades_to_error(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_task(monkeypatch, exc=RuntimeError("worker blew up"))

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)
    assert out["status"] == "error" and "document parsing failed" in out["error"]


# ---------------------------------------------------------------------------
# json_schema validation
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_json_schema_validation_passes(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    payload = {"status": "ok", "content": "x", "truncated": False,
               "structured": {"texts": [{}], "schema_name": "DoclingDocument"}}
    _patch_task(monkeypatch, payload=payload)
    schema = {"type": "object", "required": ["texts"], "properties": {"texts": {"type": "array"}}}

    out = _tool().execute_action("read_document", input=_ART_ID, output="structured",
                                 json_schema=schema, persist=False)
    assert out["status"] == "ok"


@pytest.mark.unit
def test_json_schema_validation_fails_cleanly(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    payload = {"status": "ok", "content": "x", "truncated": False, "structured": {"texts": [{}]}}
    _patch_task(monkeypatch, payload=payload)
    schema = {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number"}}}

    out = _tool().execute_action("read_document", input=_ART_ID, output="structured",
                                 json_schema=schema, persist=False)
    assert out["status"] == "error" and "did not match json_schema" in out["error"]


@pytest.mark.unit
def test_malformed_json_schema_rejected_before_enqueue(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    import application.api.user.tasks as tasks
    monkeypatch.setattr(
        tasks.parse_document, "apply_async",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enqueue")),
    )
    out = _tool().execute_action("read_document", input=_ART_ID, json_schema={"properties": {}}, persist=False)
    assert out["status"] == "error" and "invalid json_schema" in out["error"]


# ---------------------------------------------------------------------------
# Worker-context: parse INLINE inside a Celery worker; dispatch from the web
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_dispatch_inline_when_in_worker(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    # Inside a worker current_task is truthy -> parse inline, never enqueue (else the
    # parsing queue self-deadlocks the worker that also serves it).
    monkeypatch.setattr(rd, "current_task", object())

    import application.api.user.tasks as tasks
    monkeypatch.setattr(
        tasks.parse_document, "apply_async",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enqueue inside a worker")),
    )

    import application.worker as worker
    called: Dict[str, Any] = {}

    def _fake_run(artifact_id, parent, user_id, options):
        called["args"] = (artifact_id, parent, user_id)
        called["options"] = options
        return {"status": "ok", "content": "inline", "truncated": False}

    monkeypatch.setattr(worker, "run_parse_document", _fake_run)

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)
    assert out["status"] == "ok" and out["content"] == "inline"
    # Same auth re-resolution + parent shape as the dispatch path.
    assert called["args"] == (_ART_ID, {"conversation_id": "conv-1"}, "u-1")
    assert called["options"]["persist"] is False


@pytest.mark.unit
def test_dispatch_enqueues_when_not_in_worker(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    # Web process: current_task falsy -> dispatch to the parsing queue, never inline.
    monkeypatch.setattr(rd, "current_task", None)
    captured = _patch_task(monkeypatch, payload={"status": "ok", "content": "queued", "truncated": False})

    import application.worker as worker
    monkeypatch.setattr(
        worker, "run_parse_document",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("web path must dispatch, not inline")),
    )

    out = _tool().execute_action("read_document", input=_ART_ID, persist=False)
    assert out["status"] == "ok" and out["content"] == "queued"
    assert captured["args"][0] == _ART_ID
    assert captured["args"][1] == {"conversation_id": "conv-1"}


# ---------------------------------------------------------------------------
# The inline (in-worker) parse is time-bounded too
#
# The inline branch has no Celery time limit of its own, so an unbounded parse
# would pin the agent's worker slot until the OUTER task's limit (if any) kills
# the whole run. It must degrade on the SAME window the dispatch branch awaits.
# ---------------------------------------------------------------------------
_TIMED_OUT = "document parsing timed out after"


def _inline(monkeypatch, run_parse, *, timeout=0.2) -> ReadDocumentTool:
    """Drive the inline branch (current_task truthy) with a patched parse window."""
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    monkeypatch.setattr(rd, "current_task", object())

    import application.api.user.tasks as tasks
    monkeypatch.setattr(
        tasks.parse_document, "apply_async",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enqueue inside a worker")),
    )
    monkeypatch.setattr(tasks, "parse_timeout_for_size", lambda size: timeout)

    import application.worker as worker
    monkeypatch.setattr(worker, "run_parse_document", run_parse)
    return _tool()


@pytest.mark.unit
def test_inline_parse_within_the_window_returns_its_result(monkeypatch):
    seen: Dict[str, Any] = {}

    def _run(artifact_id, parent, user_id, options):
        seen["thread"] = threading.current_thread()
        seen["armed"] = signal.getitimer(signal.ITIMER_REAL)
        time.sleep(0.05)
        return {"status": "ok", "content": "inline", "truncated": False}

    before = signal.getsignal(signal.SIGALRM)
    tool = _inline(monkeypatch, _run, timeout=0.5)
    out = tool.execute_action("read_document", input=_ART_ID, persist=False)

    assert out["status"] == "ok" and out["content"] == "inline"
    # Signal strategy: the parse runs on the calling (main) thread under an armed timer,
    assert seen["thread"] is threading.main_thread()
    assert seen["armed"][0] > 0
    # and the handler + timer are restored even though the parse returned early.
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@pytest.mark.unit
def test_inline_parse_times_out_on_the_signal_path(monkeypatch, caplog):
    seen: Dict[str, Any] = {}

    def _run(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        time.sleep(0.5)
        seen["finished"] = True
        return {"status": "ok", "content": "too late"}

    before = signal.getsignal(signal.SIGALRM)
    tool = _inline(monkeypatch, _run, timeout=0.2)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="application.agents.tools.read_document"):
        out = tool.execute_action("read_document", input=_ART_ID, persist=False)
    elapsed = time.monotonic() - started

    # Same error shape the worker returns on its soft limit.
    assert out == {"status": "error", "error": f"{_TIMED_OUT} {int(0.2)}s."}
    # SIGALRM actually INTERRUPTS the parse, freeing the slot (it does not merely abandon it).
    assert elapsed < 0.45
    assert seen["thread"] is threading.main_thread()
    assert "finished" not in seen
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert any("timed out" in rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING")


@pytest.mark.unit
def test_inline_parse_times_out_on_the_thread_path(monkeypatch, caplog):
    """Off the main thread (gevent/threads pools, Windows) the timer is unusable."""
    seen: Dict[str, Any] = {}

    def _run(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        time.sleep(0.5)
        seen["finished"] = True
        return {"status": "ok", "content": "too late"}

    tool = _inline(monkeypatch, _run, timeout=0.2)
    main_handler = signal.getsignal(signal.SIGALRM)
    box: Dict[str, Any] = {}

    def _call():
        box["out"] = tool.execute_action("read_document", input=_ART_ID, persist=False)

    with caplog.at_level(logging.WARNING, logger="application.agents.tools.read_document"):
        caller = threading.Thread(target=_call, name="fake-worker-pool-thread")
        caller.start()
        caller.join(2.0)

    assert not caller.is_alive()
    assert box["out"] == {"status": "error", "error": f"{_TIMED_OUT} {int(0.2)}s."}
    # The parse ran in the helper executor, not on the caller's thread...
    assert seen["thread"].name.startswith("read-document-inline")
    assert "finished" not in seen
    # ...and the orphan cannot be interrupted, which the warning must say.
    assert any("keeps running" in rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING")
    # The main thread's signal state was never touched from the worker thread.
    assert signal.getsignal(signal.SIGALRM) is main_handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@pytest.mark.unit
def test_inline_parse_falls_back_to_a_thread_when_sigalrm_is_taken(monkeypatch):
    """A foreign SIGALRM handler must not be clobbered; use the thread strategy instead."""
    seen: Dict[str, Any] = {}

    def _run(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        return {"status": "ok", "content": "threaded", "truncated": False}

    def _foreign(signum, frame):  # pragma: no cover - must never be invoked
        raise AssertionError("foreign SIGALRM handler fired")

    tool = _inline(monkeypatch, _run, timeout=0.5)
    previous = signal.signal(signal.SIGALRM, _foreign)
    try:
        out = tool.execute_action("read_document", input=_ART_ID, persist=False)
        still_installed = signal.getsignal(signal.SIGALRM)
    finally:
        signal.signal(signal.SIGALRM, previous)

    assert out["status"] == "ok" and out["content"] == "threaded"
    assert seen["thread"].name.startswith("read-document-inline")
    assert still_installed is _foreign


@pytest.mark.unit
def test_inline_signal_timer_does_not_fire_after_a_fast_parse(monkeypatch):
    before = signal.getsignal(signal.SIGALRM)
    tool = _inline(monkeypatch, lambda *a, **k: {"status": "ok", "content": "fast"}, timeout=0.2)
    out = tool.execute_action("read_document", input=_ART_ID, persist=False)

    assert out["status"] == "ok" and out["content"] == "fast"
    # A leaked timer would raise inside this sleep, well past the window.
    time.sleep(0.3)
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@pytest.mark.unit
def test_inline_parse_failure_still_degrades_to_error(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("docling blew up")

    tool = _inline(monkeypatch, _boom, timeout=0.5)
    out = tool.execute_action("read_document", input=_ART_ID, persist=False)

    assert out["status"] == "error"
    assert "document parsing failed" in out["error"] and "docling blew up" in out["error"]
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@pytest.mark.unit
@pytest.mark.parametrize("window", [0, None])
def test_inline_parse_runs_unbounded_without_a_positive_window(monkeypatch, window):
    seen: Dict[str, Any] = {}

    def _run(*args, **kwargs):
        seen["thread"] = threading.current_thread()
        seen["armed"] = signal.getitimer(signal.ITIMER_REAL)
        seen["handler"] = signal.getsignal(signal.SIGALRM)
        return {"status": "ok", "content": "unbounded", "truncated": False}

    before = signal.getsignal(signal.SIGALRM)
    tool = _inline(monkeypatch, _run, timeout=window)
    out = tool.execute_action("read_document", input=_ART_ID, persist=False)

    assert out["status"] == "ok" and out["content"] == "unbounded"
    # Called directly: no timer armed, no handler swapped, no helper thread.
    assert seen["armed"] == (0.0, 0.0)
    assert seen["handler"] is before
    assert seen["thread"] is threading.main_thread()


@pytest.mark.unit
def test_inline_timeout_is_not_swallowed_by_the_parser_catch_all(monkeypatch, caplog):
    """``parse_document_bytes`` wraps the parse in ``except Exception`` and returns an error dict.

    The interrupt must fly straight through that catch-all (and still run its ``finally``
    cleanup) so the caller reports the shared timed-out shape, not "parsing failed: ...".
    """
    seen: Dict[str, Any] = {}

    def _run(*args, **kwargs):
        try:
            time.sleep(0.5)
            return {"status": "ok", "content": "too late"}
        except Exception as exc:  # mirrors parser/document_reader.py's catch-all
            return {"status": "error", "error": f"parsing failed: {type(exc).__name__}: {exc}"}
        finally:
            seen["cleaned_up"] = True

    tool = _inline(monkeypatch, _run, timeout=0.2)
    with caplog.at_level(logging.WARNING, logger="application.agents.tools.read_document"):
        out = tool.execute_action("read_document", input=_ART_ID, persist=False)

    assert out == {"status": "error", "error": f"{_TIMED_OUT} {int(0.2)}s."}
    assert seen["cleaned_up"] is True
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
