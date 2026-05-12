from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import ANY, MagicMock, patch

import pytest


@contextmanager
def _patch_decorator_db(conn):
    """Route the decorator's own ``db_session`` / ``db_readonly`` at ``conn``."""

    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.idempotency.db_session", _yield
    ), patch(
        "application.api.user.idempotency.db_readonly", _yield
    ):
        yield


class TestIngestTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.ingest_worker")
    def test_calls_ingest_worker(self, mock_worker):
        from application.api.user.tasks import ingest

        mock_worker.return_value = {"status": "ok"}

        result = ingest("dir", ["pdf"], "job1", "user1", "/path", "file.pdf")

        mock_worker.assert_called_once_with(
            ANY, "dir", ["pdf"], "job1", "/path", "file.pdf", "user1",
            file_name_map=None, idempotency_key=None, source_id=None,
        )
        assert result == {"status": "ok"}

    @pytest.mark.unit
    @patch("application.api.user.tasks.ingest_worker")
    def test_passes_file_name_map(self, mock_worker):
        from application.api.user.tasks import ingest

        mock_worker.return_value = {"status": "ok"}
        name_map = {"a.pdf": "b.pdf"}

        ingest("dir", ["pdf"], "job1", "user1", "/path", "file.pdf",
               file_name_map=name_map)

        mock_worker.assert_called_once_with(
            ANY, "dir", ["pdf"], "job1", "/path", "file.pdf", "user1",
            file_name_map=name_map, idempotency_key=None, source_id=None,
        )


class TestIngestRemoteTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.remote_worker")
    def test_calls_remote_worker(self, mock_worker):
        from application.api.user.tasks import ingest_remote

        mock_worker.return_value = {"status": "ok"}

        result = ingest_remote({"url": "http://x"}, "job1", "user1", "web")

        mock_worker.assert_called_once_with(
            ANY, {"url": "http://x"}, "job1", "user1", "web",
            idempotency_key=None, source_id=None,
        )
        assert result == {"status": "ok"}


class TestReingestSourceTask:
    @pytest.mark.unit
    @patch("application.worker.reingest_source_worker")
    def test_calls_reingest_worker(self, mock_worker):
        from application.api.user.tasks import reingest_source_task

        mock_worker.return_value = {"status": "ok"}

        result = reingest_source_task("source123", "user1")

        mock_worker.assert_called_once_with(ANY, "source123", "user1")
        assert result == {"status": "ok"}


class TestScheduleSyncsTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.sync_worker")
    def test_calls_sync_worker(self, mock_worker):
        from application.api.user.tasks import schedule_syncs

        mock_worker.return_value = {"status": "ok"}

        result = schedule_syncs("daily")

        mock_worker.assert_called_once_with(ANY, "daily")
        assert result == {"status": "ok"}


class TestSyncSourceTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.sync")
    def test_calls_sync(self, mock_sync):
        from application.api.user.tasks import sync_source

        mock_sync.return_value = {"status": "ok"}

        result = sync_source(
            {"data": 1}, "job1", "user1", "web", "daily", "classic", "doc1"
        )

        mock_sync.assert_called_once_with(
            ANY, {"data": 1}, "job1", "user1", "web", "daily", "classic", "doc1"
        )
        assert result == {"status": "ok"}


class TestStoreAttachmentTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.attachment_worker")
    def test_calls_attachment_worker(self, mock_worker):
        from application.api.user.tasks import store_attachment

        mock_worker.return_value = {"status": "ok"}

        result = store_attachment({"file": "info"}, "user1")

        mock_worker.assert_called_once_with(ANY, {"file": "info"}, "user1")
        assert result == {"status": "ok"}


class TestProcessAgentWebhookTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.agent_webhook_worker")
    def test_calls_agent_webhook_worker(self, mock_worker):
        from application.api.user.tasks import process_agent_webhook

        mock_worker.return_value = {"status": "ok"}

        result = process_agent_webhook("agent123", {"event": "test"})

        mock_worker.assert_called_once_with(ANY, "agent123", {"event": "test"})
        assert result == {"status": "ok"}


class TestIngestConnectorTask:
    @pytest.mark.unit
    @patch("application.worker.ingest_connector")
    def test_calls_ingest_connector_defaults(self, mock_worker):
        from application.api.user.tasks import ingest_connector_task

        mock_worker.return_value = {"status": "ok"}

        result = ingest_connector_task("job1", "user1", "gdrive")

        mock_worker.assert_called_once_with(
            ANY,
            "job1",
            "user1",
            "gdrive",
            session_token=None,
            file_ids=None,
            folder_ids=None,
            recursive=True,
            retriever="classic",
            operation_mode="upload",
            doc_id=None,
            sync_frequency="never",
            idempotency_key=None,
            source_id=None,
        )
        assert result == {"status": "ok"}

    @pytest.mark.unit
    @patch("application.worker.ingest_connector")
    def test_calls_ingest_connector_custom(self, mock_worker):
        from application.api.user.tasks import ingest_connector_task

        mock_worker.return_value = {"status": "ok"}

        result = ingest_connector_task(
            "job1",
            "user1",
            "sharepoint",
            session_token="tok",
            file_ids=["f1"],
            folder_ids=["d1"],
            recursive=False,
            retriever="duckdb",
            operation_mode="sync",
            doc_id="doc1",
            sync_frequency="daily",
        )

        mock_worker.assert_called_once_with(
            ANY,
            "job1",
            "user1",
            "sharepoint",
            session_token="tok",
            file_ids=["f1"],
            folder_ids=["d1"],
            recursive=False,
            retriever="duckdb",
            operation_mode="sync",
            doc_id="doc1",
            sync_frequency="daily",
            idempotency_key=None,
            source_id=None,
        )
        assert result == {"status": "ok"}


class TestSetupPeriodicTasks:
    @pytest.mark.unit
    def test_registers_periodic_tasks(self):
        from application.api.user.tasks import setup_periodic_tasks

        sender = MagicMock()

        setup_periodic_tasks(sender)

        assert sender.add_periodic_task.call_count == 8

        calls = sender.add_periodic_task.call_args_list

        # daily
        assert calls[0][0][0] == timedelta(days=1)
        # weekly
        assert calls[1][0][0] == timedelta(weeks=1)
        # monthly
        assert calls[2][0][0] == timedelta(days=30)
        # pending_tool_state TTL cleanup (60s)
        assert calls[3][0][0] == timedelta(seconds=60)
        assert calls[3][1].get("name") == "cleanup-pending-tool-state"
        # idempotency dedup TTL cleanup (1h)
        assert calls[4][0][0] == timedelta(hours=1)
        assert calls[4][1].get("name") == "cleanup-idempotency-dedup"
        # reconciliation sweep (30s)
        assert calls[5][0][0] == timedelta(seconds=30)
        assert calls[5][1].get("name") == "reconciliation"
        # version-check (every 7h)
        assert calls[6][0][0] == timedelta(hours=7)
        # message_events retention sweep (24h)
        assert calls[7][0][0] == timedelta(hours=24)
        assert calls[7][1].get("name") == "cleanup-message-events"


class TestMcpOauthTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.mcp_oauth")
    def test_calls_mcp_oauth(self, mock_worker):
        from application.api.user.tasks import mcp_oauth_task

        mock_worker.return_value = {"url": "http://auth"}

        result = mcp_oauth_task({"server": "mcp"}, "user1")

        mock_worker.assert_called_once_with(ANY, {"server": "mcp"}, "user1")
        assert result == {"url": "http://auth"}


class TestDurableTaskRetryPolicy:
    """The long-running tasks share a uniform retry policy."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "task_name",
        [
            "ingest",
            "ingest_remote",
            "reingest_source_task",
            "store_attachment",
            "process_agent_webhook",
            "ingest_connector_task",
        ],
    )
    def test_task_has_retry_config(self, task_name):
        import application.api.user.tasks as tasks_module

        task = getattr(tasks_module, task_name)
        assert task.acks_late is True
        assert Exception in task.autoretry_for
        assert task.retry_backoff is True
        assert task.retry_kwargs == {"max_retries": 3, "countdown": 60}

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "task_name",
        [
            "schedule_syncs",
            "sync_source",
            "mcp_oauth_task",
            "cleanup_pending_tool_state",
            "reconciliation_task",
            "version_check_task",
        ],
    )
    def test_short_periodic_tasks_have_no_retry_config(self, task_name):
        import application.api.user.tasks as tasks_module

        task = getattr(tasks_module, task_name)
        assert not getattr(task, "autoretry_for", None)


class TestProcessAgentWebhookIdempotency:
    """Wrapper short-circuits a second call with the same key on the durable webhook task."""

    @pytest.mark.unit
    def test_repeat_with_same_key_short_circuits(self, pg_conn):
        from application.api.user.tasks import process_agent_webhook

        worker_calls = []

        def _fake_worker(self, agent_id, payload):
            worker_calls.append((agent_id, payload))
            return {"status": "success", "result": {"answer": "ok"}}

        with _patch_decorator_db(pg_conn), patch(
            "application.api.user.tasks.agent_webhook_worker",
            side_effect=_fake_worker,
        ):
            first = process_agent_webhook(
                "agent", {"event": "x"}, idempotency_key="dur-k1",
            )
            second = process_agent_webhook(
                "agent", {"event": "x"}, idempotency_key="dur-k1",
            )

        assert first == {"status": "success", "result": {"answer": "ok"}}
        assert second == first
        assert len(worker_calls) == 1


class TestCleanupPendingToolState:
    """Janitor reverts stale 'resuming' rows and deletes TTL-expired rows."""

    @pytest.mark.unit
    def test_reverts_stale_and_deletes_expired(self, pg_conn):
        from sqlalchemy import text as _text

        from application.api.user.tasks import cleanup_pending_tool_state
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )
        from application.storage.db.repositories.pending_tool_state import (
            PendingToolStateRepository,
        )

        repo = PendingToolStateRepository(pg_conn)

        def _sample() -> dict:
            return {
                "messages": [],
                "pending_tool_calls": [],
                "tools_dict": {},
                "tool_schemas": [],
                "agent_config": {},
            }

        # Pending and fresh — should be left alone.
        c1 = ConversationsRepository(pg_conn).create("u", "fresh-pending")
        repo.save_state(c1["id"], "u", **_sample())

        # Pending but already expired — should be deleted.
        c2 = ConversationsRepository(pg_conn).create("u", "expired-pending")
        repo.save_state(c2["id"], "u", **_sample(), ttl_seconds=0)

        # Resuming within grace — should stay 'resuming'.
        c3 = ConversationsRepository(pg_conn).create("u", "fresh-resuming")
        repo.save_state(c3["id"], "u", **_sample())
        repo.mark_resuming(c3["id"], "u")

        # Resuming past grace — should revert to 'pending'.
        c4 = ConversationsRepository(pg_conn).create("u", "stale-resuming")
        repo.save_state(c4["id"], "u", **_sample())
        repo.mark_resuming(c4["id"], "u")
        pg_conn.execute(
            _text(
                "UPDATE pending_tool_state "
                "SET resumed_at = clock_timestamp() "
                "             - make_interval(secs => 660) "
                "WHERE conversation_id = CAST(:conv_id AS uuid)"
            ),
            {"conv_id": c4["id"]},
        )

        from contextlib import contextmanager

        @contextmanager
        def _fake_begin():
            yield pg_conn

        fake_engine = MagicMock()
        fake_engine.begin = _fake_begin

        with patch(
            "application.storage.db.engine.get_engine",
            return_value=fake_engine,
        ):
            result = cleanup_pending_tool_state.run()

        assert result["reverted"] == 1
        assert result["deleted"] == 1

        # Final state assertions.
        assert repo.load_state(c1["id"], "u")["status"] == "pending"
        assert repo.load_state(c2["id"], "u") is None
        assert repo.load_state(c3["id"], "u")["status"] == "resuming"
        c4_row = repo.load_state(c4["id"], "u")
        assert c4_row["status"] == "pending"
        assert c4_row["resumed_at"] is None

    @pytest.mark.unit
    def test_skips_when_postgres_uri_missing(self, monkeypatch):
        from application.api.user.tasks import cleanup_pending_tool_state
        from application.core.settings import settings

        monkeypatch.setattr(settings, "POSTGRES_URI", None, raising=False)

        result = cleanup_pending_tool_state.run()
        assert result == {
            "deleted": 0,
            "reverted": 0,
            "skipped": "POSTGRES_URI not set",
        }


class TestIngestIdempotency:
    """Same short-circuit applies to the ingest task path."""

    @pytest.mark.unit
    def test_repeat_with_same_key_short_circuits(self, pg_conn):
        from application.api.user.tasks import ingest

        worker_calls = []

        def _fake_worker(self, directory, formats, job_name, file_path,
                         filename, user, file_name_map=None,
                         idempotency_key=None, source_id=None):
            worker_calls.append(filename)
            return {"status": "ok", "directory": directory}

        with _patch_decorator_db(pg_conn), patch(
            "application.api.user.tasks.ingest_worker",
            side_effect=_fake_worker,
        ):
            first = ingest(
                "dir", ["pdf"], "job1", "user1", "/path", "file.pdf",
                idempotency_key="dur-ing-1",
            )
            second = ingest(
                "dir", ["pdf"], "job1", "user1", "/path", "file.pdf",
                idempotency_key="dur-ing-1",
            )

        assert first == second
        assert first == {"status": "ok", "directory": "dir"}
        assert len(worker_calls) == 1
