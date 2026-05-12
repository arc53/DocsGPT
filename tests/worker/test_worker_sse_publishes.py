"""SSE publish wiring tests for ``application.worker``.

Each worker function emits ``publish_user_event`` envelopes at its
queued / progress / completed / failed boundaries. The SSE frontend's
upload-toast, reingest-toast, attachment-toast, and MCP-OAuth toast all
depend on this exact emit sequence, so a regression that silently drops
a publish leaves the UI wedged on a stale "training" state until the
polling fallback rescues it.

These tests patch ``application.worker.publish_user_event`` with a
capture list and assert the ordered call args per worker. Broader
worker behaviour (PG side effects, pipeline correctness) is covered by
the per-task test files in this directory; here we focus narrowly on
the publish contract.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.sources import SourcesRepository


# ── helpers ──────────────────────────────────────────────────────────────


class _PublishCapture:
    """Drop-in replacement for ``publish_user_event``.

    Records every call as ``(user_id, event_type, payload, scope)`` so
    tests can assert ordering and envelope shape without caring about
    the Redis/journal side effects (covered separately in
    ``tests/test_events_substrate.py``).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    def __call__(
        self,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        scope: dict[str, Any] | None = None,
    ) -> None:
        # Defensive copy so mutations to the payload after publish (the
        # worker reuses some dicts) don't retro-edit our snapshot.
        self.calls.append((user_id, event_type, dict(payload), scope))

    def types(self) -> list[str]:
        return [call[1] for call in self.calls]


@pytest.fixture
def publishes(monkeypatch):
    """Patch ``publish_user_event`` in the worker module and yield the capture."""
    from application import worker

    cap = _PublishCapture()
    monkeypatch.setattr(worker, "publish_user_event", cap)
    return cap


def _patch_ingest_pipeline_min(monkeypatch, *, raise_in_pipeline: bool = False):
    """Minimal stubs so ``ingest_worker`` runs to completion in-process.

    Mirrors ``tests/worker/test_ingest_worker.py::_patch_ingest_pipeline``
    but exposes a knob to force a mid-pipeline exception so the
    ``failed`` branch can be reached without otherwise rewriting the
    function.
    """
    from application import worker

    fake_storage = MagicMock(name="storage")
    fake_storage.is_directory.return_value = False
    fake_storage.get_file.return_value = BytesIO(b"hello")
    monkeypatch.setattr(
        worker.StorageCreator, "get_storage", lambda: fake_storage
    )

    fake_reader = MagicMock(name="reader")
    fake_reader.load_data.return_value = [
        Document(text="hello body", extra_info={"source": "a.txt"})
    ]
    fake_reader.directory_structure = {
        "a.txt": {"type": "text/plain", "size_bytes": 5, "token_count": 2}
    }
    monkeypatch.setattr(
        worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
    )

    if raise_in_pipeline:
        def _boom(*a, **kw):
            raise RuntimeError("pipeline kaboom")

        monkeypatch.setattr(worker, "embed_and_store_documents", _boom)
    else:
        monkeypatch.setattr(
            worker,
            "embed_and_store_documents",
            lambda docs, full_path, source_id, task, **kw: None,
        )

    monkeypatch.setattr(
        worker, "upload_index", lambda full_path, file_data: None
    )


# ── ingest_worker ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestIngestWorkerPublishes:
    def test_happy_path_emits_queued_then_completed(
        self, patch_worker_db, task_self, monkeypatch, publishes
    ):
        from application import worker

        _patch_ingest_pipeline_min(monkeypatch)
        caller_source_id = str(uuid.uuid4())

        worker.ingest_worker(
            task_self,
            directory="inputs",
            formats=[".txt"],
            job_name="job1",
            file_path="inputs/eve/job1/a.txt",
            filename="a.txt",
            user="eve",
            retriever="classic",
            source_id=caller_source_id,
        )

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.completed",
        ]

        user, etype, payload, scope = publishes.calls[0]
        assert user == "eve"
        assert etype == "source.ingest.queued"
        assert payload["filename"] == "a.txt"
        assert payload["job_name"] == "job1"
        assert payload["operation"] == "upload"
        # ``source_id`` in the queued payload MUST match the value the
        # HTTP route returned to the frontend, otherwise the upload
        # toast cannot match the event back to its task.
        assert payload["source_id"] == caller_source_id
        assert scope == {"kind": "source", "id": caller_source_id}

        completed = publishes.calls[1][2]
        assert completed["source_id"] == caller_source_id
        assert completed["operation"] == "upload"
        assert "tokens" in completed

    def test_pipeline_failure_emits_queued_then_failed(
        self, patch_worker_db, task_self, monkeypatch, publishes
    ):
        from application import worker

        _patch_ingest_pipeline_min(monkeypatch, raise_in_pipeline=True)

        with pytest.raises(RuntimeError, match="pipeline kaboom"):
            worker.ingest_worker(
                task_self,
                directory="inputs",
                formats=[".txt"],
                job_name="job1",
                file_path="inputs/eve/job1/a.txt",
                filename="a.txt",
                user="eve",
                retriever="classic",
                idempotency_key="key-A",
            )

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.failed",
        ]
        queued_payload = publishes.calls[0][2]
        failed_payload = publishes.calls[1][2]
        # Same source_id across the queued/failed pair so the frontend
        # toast can correlate them.
        assert queued_payload["source_id"] == failed_payload["source_id"]
        # ``error`` is truncated to 1024 chars but our error message is
        # well under that.
        assert "pipeline kaboom" in failed_payload["error"]


# ── reingest_source_worker ───────────────────────────────────────────────


def _seed_source_for_reingest(pg_conn, *, user_id: str, name: str = "doc-set"):
    return SourcesRepository(pg_conn).create(
        name,
        user_id=user_id,
        type="local",
        retriever="classic",
        file_path=f"inputs/{user_id}/{name}",
        directory_structure={
            "stale.txt": {
                "type": "text/plain",
                "size_bytes": 10,
                "token_count": 5,
            }
        },
    )


def _stub_reingest_storage_and_vectorstore(monkeypatch):
    from application import worker

    fake_storage = MagicMock(name="storage")
    fake_storage.is_directory.return_value = True
    fake_storage.list_files.return_value = []
    monkeypatch.setattr(
        worker.StorageCreator, "get_storage", lambda: fake_storage
    )

    fake_store = MagicMock(name="vector_store")
    fake_store.get_chunks.return_value = []
    monkeypatch.setattr(
        "application.vectorstore.vector_creator.VectorCreator.create_vectorstore",
        lambda *a, **kw: fake_store,
    )
    return fake_store


@pytest.mark.unit
class TestReingestSourceWorkerPublishes:
    def test_with_changes_emits_queued_then_completed_with_chunk_counts(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, publishes
    ):
        from application import worker

        src = _seed_source_for_reingest(pg_conn, user_id="alice")
        source_id = str(src["id"])

        _stub_reingest_storage_and_vectorstore(monkeypatch)

        fake_reader = MagicMock(name="reader")
        fake_reader.load_data.return_value = []
        fake_reader.directory_structure = {
            "fresh.md": {
                "type": "text/markdown",
                "size_bytes": 42,
                "token_count": 17,
            }
        }
        fake_reader.file_token_counts = {"fresh.md": 17}
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
        )

        worker.reingest_source_worker(task_self, source_id, "alice")

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.completed",
        ]
        queued = publishes.calls[0][2]
        assert queued["operation"] == "reingest"
        assert queued["source_id"] == source_id
        assert queued["name"] == "doc-set"

        completed = publishes.calls[1][2]
        assert completed["operation"] == "reingest"
        # ``chunks_added`` / ``chunks_deleted`` are integer counters
        # the toast displays — keep them on the contract.
        assert "chunks_added" in completed
        assert "chunks_deleted" in completed
        # ``no_changes`` is only set on the early-return branch; the
        # full reingest path must not synthesize it.
        assert "no_changes" not in completed

    def test_no_changes_branch_still_emits_completed(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, publishes
    ):
        """The early-return ``No changes detected`` path is the only
        place a reingest can finish without going through the
        chunk-diff loop. If it didn't publish a terminal event the
        toast would hang on ``training`` forever.
        """
        from application import worker

        # Seed with the same directory_structure the reader will report,
        # so ``added_files`` and ``removed_files`` are both empty.
        repo = SourcesRepository(pg_conn)
        same_structure = {
            "unchanged.txt": {
                "type": "text/plain",
                "size_bytes": 7,
                "token_count": 3,
            }
        }
        src = repo.create(
            "stable-set",
            user_id="alice",
            type="local",
            retriever="classic",
            file_path="inputs/alice/stable-set",
            directory_structure=same_structure,
        )
        source_id = str(src["id"])

        _stub_reingest_storage_and_vectorstore(monkeypatch)

        fake_reader = MagicMock(name="reader")
        fake_reader.load_data.return_value = []
        fake_reader.directory_structure = same_structure
        fake_reader.file_token_counts = {"unchanged.txt": 3}
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
        )

        worker.reingest_source_worker(task_self, source_id, "alice")

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.completed",
        ]
        completed = publishes.calls[1][2]
        assert completed.get("no_changes") is True
        assert completed["chunks_added"] == 0
        assert completed["chunks_deleted"] == 0

    def test_failure_before_lookup_emits_failed_without_queued(
        self, patch_worker_db, task_self, monkeypatch, publishes
    ):
        """If the source lookup fails (row missing, PG hiccup) the
        ``queued`` publish has not yet happened — but the ``failed``
        publish at the outer except must still fire so the frontend
        toast doesn't wedge. The worker re-raises after publishing,
        which is the documented contract for Celery retry handling.
        """
        from application import worker

        with pytest.raises(ValueError, match="not found"):
            worker.reingest_source_worker(
                task_self,
                "00000000-0000-0000-0000-000000000000",
                "ghost",
            )

        # Lookup raises ValueError before the ``queued`` publish at
        # line ~787; the outer except fires the ``failed`` publish.
        assert publishes.types() == ["source.ingest.failed"]
        failed = publishes.calls[0][2]
        assert failed["operation"] == "reingest"
        # Pre-lookup, ``source_name`` is empty; payload should still
        # carry a ``name`` field (empty string) so the frontend doesn't
        # KeyError on the toast template.
        assert "name" in failed
        assert "error" in failed


# ── remote_worker (upload mode) ──────────────────────────────────────────


def _stub_remote_pipeline(monkeypatch, *, raise_in_pipeline: bool = False):
    from application import worker

    fake_loader = MagicMock(name="remote_loader")
    fake_loader.load_data.return_value = [
        Document(
            text="page body",
            extra_info={"file_path": "guides/setup.md", "title": "setup"},
            doc_id="d1",
        )
    ]
    monkeypatch.setattr(
        worker.RemoteCreator, "create_loader", lambda loader: fake_loader
    )

    if raise_in_pipeline:
        def _boom(*a, **kw):
            raise RuntimeError("remote-pipeline kaboom")

        monkeypatch.setattr(worker, "embed_and_store_documents", _boom)
    else:
        monkeypatch.setattr(
            worker,
            "embed_and_store_documents",
            lambda docs, full_path, source_id, task, **kw: None,
        )
    monkeypatch.setattr(
        worker, "upload_index", lambda full_path, file_data: None
    )


@pytest.mark.unit
class TestRemoteWorkerPublishes:
    def test_upload_happy_path(
        self, tmp_path, task_self, monkeypatch, publishes
    ):
        from application import worker

        _stub_remote_pipeline(monkeypatch)

        worker.remote_worker(
            task_self,
            {"urls": ["http://example.com"]},
            "my-remote",
            "bob",
            "crawler",
            directory=str(tmp_path / "temp"),
            operation_mode="upload",
        )

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.completed",
        ]
        queued = publishes.calls[0][2]
        completed = publishes.calls[1][2]
        assert queued["operation"] == "upload"
        assert queued["loader"] == "crawler"
        assert completed["operation"] == "upload"
        # ``source_id`` is the same across both envelopes.
        assert queued["source_id"] == completed["source_id"]

    def test_upload_failure_emits_failed(
        self, tmp_path, task_self, monkeypatch, publishes
    ):
        from application import worker

        _stub_remote_pipeline(monkeypatch, raise_in_pipeline=True)

        with pytest.raises(RuntimeError, match="remote-pipeline kaboom"):
            worker.remote_worker(
                task_self,
                {"urls": ["http://example.com"]},
                "my-remote",
                "bob",
                "crawler",
                directory=str(tmp_path / "temp"),
                operation_mode="upload",
            )

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.failed",
        ]
        failed = publishes.calls[1][2]
        assert "remote-pipeline kaboom" in failed["error"]


# ── ingest_connector ─────────────────────────────────────────────────────


def _stub_connector_pipeline(
    monkeypatch, *, files_downloaded: int = 1, empty_result: bool = False
):
    from application import worker

    fake_connector = MagicMock(name="connector")
    fake_connector.download_to_directory.return_value = {
        "files_downloaded": files_downloaded,
        "empty_result": empty_result,
    }
    monkeypatch.setattr(
        worker.ConnectorCreator,
        "is_supported",
        staticmethod(lambda s: True),
    )
    monkeypatch.setattr(
        worker.ConnectorCreator,
        "create_connector",
        staticmethod(lambda source_type, session_token: fake_connector),
    )

    fake_reader = MagicMock(name="reader")
    fake_reader.load_data.return_value = [
        Document(
            text="connector body",
            extra_info={
                "source": "connector/file.md",
                "file_path": "file.md",
            },
        )
    ]
    fake_reader.directory_structure = {
        "file.md": {
            "type": "text/markdown",
            "size_bytes": 12,
            "token_count": 3,
        }
    }
    monkeypatch.setattr(
        worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
    )

    monkeypatch.setattr(
        worker,
        "embed_and_store_documents",
        lambda docs, full_path, source_id, task, **kw: None,
    )
    monkeypatch.setattr(
        worker, "upload_index", lambda full_path, file_data: None
    )


@pytest.mark.unit
class TestIngestConnectorPublishes:
    def test_upload_happy_path(self, task_self, monkeypatch, publishes):
        from application import worker

        _stub_connector_pipeline(monkeypatch)

        worker.ingest_connector(
            task_self,
            "gdrive-folder",
            "dave",
            "google_drive",
            session_token="tok",
            file_ids=["f1"],
            folder_ids=[],
            operation_mode="upload",
        )

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.completed",
        ]
        completed = publishes.calls[1][2]
        assert completed["operation"] == "upload"
        # Loader name is the provider, not the worker function name.
        assert completed["loader"] == "google_drive"
        # ``no_changes`` is only set on the early-return branch.
        assert "no_changes" not in completed

    def test_no_files_downloaded_still_emits_completed(
        self, task_self, monkeypatch, publishes
    ):
        """The "connector returned no files" early-return path is
        otherwise silent; without the publish the toast wedges on
        ``training`` until polling rescues it.
        """
        from application import worker

        _stub_connector_pipeline(
            monkeypatch, files_downloaded=0, empty_result=True
        )

        worker.ingest_connector(
            task_self,
            "gdrive-folder",
            "dave",
            "google_drive",
            session_token="tok",
            file_ids=["f1"],
            folder_ids=[],
            operation_mode="upload",
        )

        assert publishes.types() == [
            "source.ingest.queued",
            "source.ingest.completed",
        ]
        completed = publishes.calls[1][2]
        assert completed.get("no_changes") is True
        assert completed["tokens"] == 0


# ── attachment_worker ────────────────────────────────────────────────────


@pytest.mark.unit
class TestAttachmentWorkerPublishes:
    def test_happy_path_emits_full_progress_sequence(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, publishes
    ):
        from application import worker

        fake_doc = Document(
            text="hello world",
            extra_info={"transcript_language": "en"},
        )
        fake_storage = MagicMock(name="storage")
        fake_storage.process_file.return_value = fake_doc
        monkeypatch.setattr(
            worker.StorageCreator, "get_storage", lambda: fake_storage
        )
        monkeypatch.setattr(
            worker, "get_default_file_extractor", lambda ocr_enabled=False: {}
        )

        file_info = {
            "filename": "notes.txt",
            "attachment_id": "507f1f77bcf86cd799439011",
            "path": "uploads/user1/notes.txt",
            "metadata": {"source": "chat"},
        }
        worker.attachment_worker(task_self, file_info, "user1")

        # Four publishes: queued + two progress + completed. The
        # progress events feed the percent-driven toast UI, so
        # missing one would leave the UI frozen at the prior stage.
        assert publishes.types() == [
            "attachment.queued",
            "attachment.processing.progress",
            "attachment.processing.progress",
            "attachment.completed",
        ]

        progress_a = publishes.calls[1][2]
        progress_b = publishes.calls[2][2]
        assert progress_a["current"] == 30
        assert progress_a["stage"] == "processing"
        assert progress_b["current"] == 80
        assert progress_b["stage"] == "storing"

        completed = publishes.calls[3][2]
        assert completed["filename"] == "notes.txt"
        assert completed["token_count"] > 0
        assert completed["mime_type"]  # populated from mimetypes

        # Scope ids are all the attachment_id verbatim.
        for _, _, _, scope in publishes.calls:
            assert scope == {
                "kind": "attachment",
                "id": file_info["attachment_id"],
            }

    def test_processing_failure_emits_failed_with_partial_progress(
        self, task_self, monkeypatch, publishes
    ):
        """``process_file`` raises mid-flow, AFTER the worker has
        already emitted the ``current=30`` progress envelope. The
        terminal ``failed`` must still arrive so the toast unwedges,
        even though no ``current=80`` progress will follow.
        """
        from application import worker

        fake_storage = MagicMock(name="storage")
        fake_storage.process_file.side_effect = RuntimeError("parse boom")
        monkeypatch.setattr(
            worker.StorageCreator, "get_storage", lambda: fake_storage
        )
        monkeypatch.setattr(
            worker, "get_default_file_extractor", lambda ocr_enabled=False: {}
        )

        file_info = {
            "filename": "notes.txt",
            "attachment_id": "507f1f77bcf86cd799439011",
            "path": "uploads/user1/notes.txt",
            "metadata": {"source": "chat"},
        }
        with pytest.raises(RuntimeError, match="parse boom"):
            worker.attachment_worker(task_self, file_info, "user1")

        # queued + the first progress envelope (current=30) + failed.
        # The current=80 publish never fires because ``process_file``
        # raises before reaching it.
        assert publishes.types() == [
            "attachment.queued",
            "attachment.processing.progress",
            "attachment.failed",
        ]
        assert publishes.calls[1][2]["current"] == 30
        failed = publishes.calls[2][2]
        assert "parse boom" in failed["error"]
        assert failed["filename"] == "notes.txt"


# ── mcp_oauth ────────────────────────────────────────────────────────────


def _stub_mcp_oauth_redis(monkeypatch):
    """Stand-in Redis whose ``setex`` is a no-op (covered separately)."""
    from application import worker

    fake_redis = MagicMock(name="redis_client")
    # Default setex behaviour: do nothing, return OK.
    fake_redis.setex.return_value = True
    monkeypatch.setattr(worker, "get_redis_instance", lambda: fake_redis)
    return fake_redis


def _make_fake_mcp_tool_class(
    *,
    tools: list[str] | None = None,
    discovery_raises: Exception | None = None,
    authorization_url: str | None = "https://idp.example.com/authorize?state=xyz",
):
    """Build a class that stands in for ``MCPTool`` in mcp_oauth.

    The worker constructs ``MCPTool(tool_config, user_id)`` then calls:

    - ``_client`` (attribute, falsy → triggers ``_setup_client``)
    - ``_setup_client()`` (sync, sets up the client)
    - ``_execute_with_client("list_tools")`` (async, returns anything)
    - ``get_actions_metadata()`` (sync, returns the tools list)

    The fake mirrors the real handshake: ``__init__`` lifts the
    ``oauth_redirect_publish`` callback out of ``tool_config`` and
    ``_setup_client`` invokes it with ``authorization_url`` — the same
    spot where the real ``DocsGPTOAuth.redirect_handler`` would fire it
    once the upstream OAuth provider mints the URL.

    The ``discovery_raises`` knob simulates a mid-flow failure inside
    the ``run_oauth_discovery`` coroutine. Setting
    ``authorization_url=None`` suppresses the redirect publish so the
    ``no user_id`` test path can assert the publisher is fully silent.
    """
    resolved_tools = list(tools) if tools is not None else ["tool_a", "tool_b"]

    class _FakeMCPTool:
        def __init__(self, tool_config: dict, user_id: str | None = None):
            self._client = None
            self._tool_config = tool_config
            self._user_id = user_id
            # Real ``MCPTool.__init__`` ``pop``s this key off the config
            # so it does not leak into the persisted tool config blob.
            # Mirror that behaviour so the test catches a regression
            # where the worker stops passing the callback through.
            self._oauth_redirect_publish = tool_config.pop(
                "oauth_redirect_publish", None
            )

        def _setup_client(self) -> None:
            self._client = object()
            # Simulate the real OAuth flow: ``DocsGPTOAuth.redirect_handler``
            # invokes the worker-provided callback the moment the
            # authorization URL is known. Doing it here keeps the
            # observable publish ordering identical to the real path:
            # ``in_progress`` → ``awaiting_redirect(url)`` → terminal.
            if (
                authorization_url is not None
                and callable(self._oauth_redirect_publish)
            ):
                self._oauth_redirect_publish(authorization_url)

        async def _execute_with_client(self, name: str):
            if discovery_raises is not None:
                raise discovery_raises
            return None

        def get_actions_metadata(self):
            return resolved_tools

    return _FakeMCPTool


@pytest.fixture
def _task_self_with_request_id():
    """``mcp_oauth`` reads ``self.request.id``; supply a stable one."""
    task = MagicMock(name="celery_task_self")
    task.request.id = "task-xyz"
    return task


def _patch_mcp_tool(monkeypatch, fake_tool_class) -> None:
    """Replace the ``MCPTool`` symbol the worker imports at call time.

    The worker runs ``from application.agents.tools.mcp_tool import MCPTool``
    inside the function body. Importing the real module is a circular
    dependency in this test process (it pulls in the user routes,
    which pull in the MCP namespace, which pulls in
    ``mcp_tool``), so we inject a stub module into ``sys.modules``
    BEFORE the import line is reached. Python will then resolve the
    inline import against our stub instead of evaluating the real
    file.
    """
    import sys
    import types

    stub = types.ModuleType("application.agents.tools.mcp_tool")
    stub.MCPTool = fake_tool_class
    monkeypatch.setitem(
        sys.modules, "application.agents.tools.mcp_tool", stub
    )


@pytest.mark.unit
class TestMcpOauthPublishes:
    def test_happy_path_emits_progress_sequence_and_completed(
        self, monkeypatch, publishes, _task_self_with_request_id
    ):
        from application import worker

        _stub_mcp_oauth_redis(monkeypatch)
        auth_url = "https://idp.example.com/authorize?state=happy-path"
        _patch_mcp_tool(
            monkeypatch,
            _make_fake_mcp_tool_class(
                tools=["alpha", "beta"], authorization_url=auth_url,
            ),
        )

        result = worker.mcp_oauth(
            _task_self_with_request_id,
            {"command": "node", "args": []},
            user_id="zoe",
        )

        assert result["success"] is True
        assert result["tools"] == ["alpha", "beta"]

        # Ordered emit: in_progress → awaiting_redirect → completed.
        # Any drift here changes the toast state machine.
        assert publishes.types() == [
            "mcp.oauth.in_progress",
            "mcp.oauth.awaiting_redirect",
            "mcp.oauth.completed",
        ]
        awaiting = publishes.calls[1][2]
        # The frontend opens the OAuth popup straight from this URL.
        # Without it the popup never opens and the user retries; the
        # test guards the contract that the SSE envelope is now the
        # source of truth for the authorization URL.
        assert awaiting["authorization_url"] == auth_url
        completed = publishes.calls[2][2]
        assert completed["tools"] == ["alpha", "beta"]
        assert completed["tools_count"] == 2
        # Every envelope carries the task_id so the toast can correlate
        # it to the original POST that kicked the OAuth off.
        for _, _, payload, scope in publishes.calls:
            assert payload["task_id"] == "task-xyz"
            assert scope == {"kind": "mcp_oauth", "id": "task-xyz"}

    def test_finish_oauth_failure_emits_failed(
        self, monkeypatch, publishes, _task_self_with_request_id
    ):
        """A failure inside the OAuth completion step is the most
        common failure mode (user cancels, provider 4xx). Must surface
        as a ``mcp.oauth.failed`` envelope so the toast unwedges.
        """
        from application import worker

        _stub_mcp_oauth_redis(monkeypatch)
        _patch_mcp_tool(
            monkeypatch,
            _make_fake_mcp_tool_class(
                discovery_raises=RuntimeError("oauth user cancelled")
            ),
        )

        result = worker.mcp_oauth(
            _task_self_with_request_id,
            {"command": "node", "args": []},
            user_id="zoe",
        )

        assert result["success"] is False
        # in_progress + awaiting_redirect + failed; no completed.
        assert publishes.types() == [
            "mcp.oauth.in_progress",
            "mcp.oauth.awaiting_redirect",
            "mcp.oauth.failed",
        ]
        failed = publishes.calls[-1][2]
        assert "oauth user cancelled" in failed["error"]

    def test_skips_publishes_when_user_id_missing(
        self, monkeypatch, publishes, _task_self_with_request_id
    ):
        """Legacy callers can invoke ``mcp_oauth`` without a user_id;
        the worker must not blow up but also must NOT publish to a
        synthetic / shared channel. Polling-based status remains the
        path of record in that case.
        """
        from application import worker

        _stub_mcp_oauth_redis(monkeypatch)
        _patch_mcp_tool(monkeypatch, _make_fake_mcp_tool_class())

        result = worker.mcp_oauth(
            _task_self_with_request_id,
            {"command": "node", "args": []},
            user_id=None,
        )

        assert result["success"] is True
        # ``publish_oauth`` short-circuits when ``user_id`` is falsy.
        assert publishes.calls == []
