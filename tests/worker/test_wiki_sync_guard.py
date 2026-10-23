"""A wiki never syncs.

A sync wipes the source's index and re-embeds what the loader reads, then
rewrites its directory structure: on a wiki that throws away the pages'
chunks and replaces them with the original remote content. Converting a
source to a wiki clears its schedule, and every sync path skips a wiki
whose schedule survived (an older conversion, or a direct write).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.sources import SourcesRepository

WIKI_CONFIG = {"kind": "wiki"}


@pytest.mark.unit
class TestSyncSkipsAWiki:
    def test_sync_does_not_run_the_remote_worker_on_a_wiki(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "handbook",
            user_id="erin",
            type="website",
            sync_frequency="weekly",
            remote_data={"entries": [{"url": "https://example.com/", "mode": "page"}]},
            config=WIKI_CONFIG,
        )
        remote = MagicMock(name="remote_worker")
        monkeypatch.setattr(worker, "remote_worker", remote)

        result = worker.sync(
            task_self,
            {"entries": [{"url": "https://example.com/", "mode": "page"}]},
            "handbook",
            "erin",
            "website",
            "weekly",
            "classic",
            str(src["id"]),
        )

        assert result == {"status": "skipped", "reason": "wiki"}
        remote.assert_not_called()

    def test_scheduled_sync_skips_a_wiki(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        SourcesRepository(pg_conn).create(
            "handbook",
            user_id="erin",
            type="url",
            sync_frequency="weekly",
            remote_data={"url": "http://example.com"},
            config=WIKI_CONFIG,
        )
        sync = MagicMock(name="sync", return_value={"status": "success"})
        monkeypatch.setattr(worker, "sync", sync)

        counts = worker.sync_worker(task_self, "weekly")

        sync.assert_not_called()
        assert counts["sync_skipped"] == 1

    def test_scheduled_sync_skips_a_wiki_from_a_connector(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        cid = pg_conn.execute(text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status) "
            "VALUES ('erin', 'google_drive', 'google_drive', 'oauth', 'connected') RETURNING id"
        )).scalar()
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, config) "
            "VALUES ('erin', 'Drive', 'connector:file', 'weekly', CAST(:c AS uuid), "
            "CAST(:cfg AS jsonb))"
        ), {"c": str(cid), "cfg": '{"kind": "wiki"}'})
        delay = MagicMock(name="sync_connector_source.delay")
        monkeypatch.setattr("docsgpt.api.user.tasks.sync_connector_source.delay", delay)

        counts = worker.sync_worker(task_self, "weekly")

        delay.assert_not_called()
        assert counts["sync_skipped"] == 1

    def test_connector_sync_skips_a_wiki(self, pg_conn, patch_worker_db, monkeypatch):
        from docsgpt import worker

        cid = pg_conn.execute(text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status) "
            "VALUES ('erin', 'google_drive', 'google_drive', 'oauth', 'connected') RETURNING id"
        )).scalar()
        source = pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, config) "
            "VALUES ('erin', 'Drive', 'connector:file', 'weekly', CAST(:c AS uuid), "
            "CAST(:cfg AS jsonb)) RETURNING id"
        ), {"c": str(cid), "cfg": '{"kind": "wiki"}'}).scalar()
        ingest = MagicMock(name="ingest_connector")
        monkeypatch.setattr(worker, "ingest_connector", ingest)

        result = worker.sync_connector_source(MagicMock(), str(source))

        assert result == {"status": "skipped", "reason": "wiki"}
        ingest.assert_not_called()

    def test_manual_connector_sync_skips_a_wiki(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        """The connector route's Sync now runs ``ingest_connector`` directly."""
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Drive",
            user_id="erin",
            type="connector:file",
            sync_frequency="never",
            config=WIKI_CONFIG,
        )
        creator = MagicMock(name="ConnectorCreator.create_connector")
        monkeypatch.setattr(
            "docsgpt.parser.connectors.connector_creator.ConnectorCreator.create_connector",
            creator,
        )

        result = worker.ingest_connector(
            task_self,
            "Drive",
            "erin",
            "google_drive",
            operation_mode="sync",
            doc_id=str(src["id"]),
        )

        assert result == {"status": "skipped", "reason": "wiki"}
        creator.assert_not_called()

    def test_connector_sync_does_not_run_when_the_row_cant_be_read(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        """Unread, the row might be a wiki: the sync must not replace its pages."""
        from contextlib import contextmanager

        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Drive", user_id="erin", type="connector:file", sync_frequency="never", config=WIKI_CONFIG,
        )

        @contextmanager
        def broken():
            raise RuntimeError("database unavailable")
            yield

        monkeypatch.setattr(worker, "db_readonly", broken)
        monkeypatch.setattr(worker, "publish_user_event", lambda *a, **k: None)
        creator = MagicMock(name="ConnectorCreator.create_connector")
        monkeypatch.setattr(
            "docsgpt.parser.connectors.connector_creator.ConnectorCreator.create_connector",
            creator,
        )

        result = worker.ingest_connector(
            task_self, "Drive", "erin", "google_drive", operation_mode="sync", doc_id=str(src["id"]),
        )

        assert result["status"] == "error"
        creator.assert_not_called()
