from datetime import timedelta
from unittest.mock import ANY, MagicMock, patch

import pytest


class TestIngestTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.ingest_worker")
    def test_calls_ingest_worker(self, mock_worker):
        from application.api.user.tasks import ingest

        mock_worker.return_value = {"status": "ok"}

        result = ingest("dir", ["pdf"], "job1", "user1", "/path", "file.pdf")

        mock_worker.assert_called_once_with(
            ANY, "dir", ["pdf"], "job1", "/path", "file.pdf", "user1",
            file_name_map=None,
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
            file_name_map=name_map,
        )


class TestIngestRemoteTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.remote_worker")
    def test_calls_remote_worker(self, mock_worker):
        from application.api.user.tasks import ingest_remote

        mock_worker.return_value = {"status": "ok"}

        result = ingest_remote({"url": "http://x"}, "job1", "user1", "web")

        mock_worker.assert_called_once_with(
            ANY, {"url": "http://x"}, "job1", "user1", "web"
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
        )
        assert result == {"status": "ok"}


class TestSetupPeriodicTasks:
    @pytest.mark.unit
    def test_registers_periodic_tasks(self):
        from application.api.user.tasks import setup_periodic_tasks

        sender = MagicMock()

        setup_periodic_tasks(sender)

        assert sender.add_periodic_task.call_count == 4

        calls = sender.add_periodic_task.call_args_list

        # daily
        assert calls[0][0][0] == timedelta(days=1)
        # weekly
        assert calls[1][0][0] == timedelta(weeks=1)
        # monthly
        assert calls[2][0][0] == timedelta(days=30)
        # pending_tool_state TTL cleanup (60s)
        assert calls[3][0][0] == timedelta(seconds=60)


class TestMcpOauthTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.mcp_oauth")
    def test_calls_mcp_oauth(self, mock_worker):
        from application.api.user.tasks import mcp_oauth_task

        mock_worker.return_value = {"url": "http://auth"}

        result = mcp_oauth_task({"server": "mcp"}, "user1")

        mock_worker.assert_called_once_with(ANY, {"server": "mcp"}, "user1")
        assert result == {"url": "http://auth"}


class TestMcpOauthStatusTask:
    @pytest.mark.unit
    @patch("application.api.user.tasks.mcp_oauth_status")
    def test_calls_mcp_oauth_status(self, mock_worker):
        from application.api.user.tasks import mcp_oauth_status_task

        mock_worker.return_value = {"status": "authorized"}

        result = mcp_oauth_status_task("task123")

        mock_worker.assert_called_once_with(ANY, "task123")
        assert result == {"status": "authorized"}
