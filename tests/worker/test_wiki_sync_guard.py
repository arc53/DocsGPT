"""A wiki never syncs.

A sync wipes the source's index and re-embeds what the loader reads, then
rewrites its directory structure: on a wiki that throws away the pages'
chunks and replaces them with the original remote content. Converting a
source to a wiki clears its schedule, and every sync path skips a wiki
whose schedule survived (an older conversion, or a direct write). The
manual syncs' guards are tested with their workers (``test_sync_keeps_settings``,
``test_ingest_connector``).
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt import worker
from docsgpt.storage.db.repositories.sources import SourcesRepository

WIKI_CONFIG = {"kind": "wiki"}


def _wiki_connector_source(pg_conn):
    cid = pg_conn.execute(text(
        "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status) "
        "VALUES ('erin', 'google_drive', 'google_drive', 'oauth', 'connected') RETURNING id"
    )).scalar()
    return pg_conn.execute(text(
        "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, config) "
        "VALUES ('erin', 'Drive', 'connector:file', 'weekly', CAST(:c AS uuid), "
        "CAST(:cfg AS jsonb)) RETURNING id"
    ), {"c": str(cid), "cfg": '{"kind": "wiki"}'}).scalar()


@pytest.mark.unit
class TestSyncSkipsAWiki:
    def test_scheduled_sync_skips_a_wiki(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
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
        _wiki_connector_source(pg_conn)
        delay = MagicMock(name="sync_connector_source.delay")
        monkeypatch.setattr("docsgpt.api.user.tasks.sync_connector_source.delay", delay)

        counts = worker.sync_worker(task_self, "weekly")

        delay.assert_not_called()
        assert counts["sync_skipped"] == 1

    def test_connector_sync_skips_a_wiki(self, pg_conn, patch_worker_db, monkeypatch):
        source = _wiki_connector_source(pg_conn)
        ingest = MagicMock(name="ingest_connector")
        monkeypatch.setattr(worker, "ingest_connector", ingest)

        result = worker.sync_connector_source(MagicMock(), str(source))

        assert result == {"status": "skipped", "reason": "wiki"}
        ingest.assert_not_called()

    def test_connector_sync_does_not_run_when_the_row_cant_be_read(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, published
    ):
        """Unread, the row might be a wiki: the sync must not replace its pages."""
        src = SourcesRepository(pg_conn).create(
            "Drive", user_id="erin", type="connector:file", sync_frequency="never", config=WIKI_CONFIG,
        )

        @contextmanager
        def broken():
            raise RuntimeError("database unavailable")
            yield

        monkeypatch.setattr(worker, "db_readonly", broken)
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
        assert published.kinds() == ["source.ingest.failed"]
