"""Tests for ``index_attachment_worker``: embedding a chat attachment in the
background into its own hidden source, so attachments_search can rank by
meaning once it is done.
"""

from __future__ import annotations

import uuid

import pytest

import docsgpt.storage.db.engine as engine_module
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.repositories.sources import (
    ATTACHMENT_SOURCE_TYPE,
    SourcesRepository,
)
from docsgpt.storage.db.session import db_readonly, db_session

USER = "index-user"


class _StubTask:
    request = type("Req", (), {"id": "task-1"})()

    def update_state(self, *args, **kwargs):
        pass


@pytest.fixture()
def wired_engine(pg_engine, monkeypatch):
    monkeypatch.setattr(engine_module, "_engine", None)
    eng = engine_module.get_engine()
    yield eng
    eng.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)


@pytest.fixture()
def embedded(monkeypatch):
    """Capture what would be embedded instead of calling a model."""
    calls = []

    def _embed(docs, folder_name, source_id, task_status, **kwargs):
        calls.append({"docs": docs, "source_id": source_id, "kwargs": kwargs})

    monkeypatch.setattr("docsgpt.worker.embed_and_store_documents", _embed)
    monkeypatch.setattr("docsgpt.worker.assert_index_complete", lambda source_id: None)
    return calls


def _attachment(content="hello world " * 400, status="ok", user=USER):
    with db_session() as conn:
        return AttachmentsRepository(conn).create(
            user,
            "report.pdf",
            "/uploads/report.pdf",
            mime_type="application/pdf",
            content=content,
            token_count=len(content.split()),
            metadata={"extraction": {"status": status}, "index": {"status": "pending"}},
            legacy_mongo_id=str(uuid.uuid4()),
        )


def _row(attachment_id, user=USER):
    with db_readonly() as conn:
        return AttachmentsRepository(conn).get(str(attachment_id), user)


def _run(attachment_id, user=USER):
    from docsgpt.worker import index_attachment_worker

    return index_attachment_worker(_StubTask(), str(attachment_id), user)


@pytest.mark.usefixtures("wired_engine")
class TestIndexAttachment:
    def test_embeds_chunks_with_offsets_into_a_hidden_source(self, embedded):
        row = _attachment()

        result = _run(row["id"])

        assert result["status"] == "done"
        index = _row(row["id"])["metadata"]["index"]
        assert index["status"] == "done"
        assert index["chunks"] == len(embedded[0]["docs"])
        source_id = index["source_id"]
        assert embedded[0]["source_id"] == source_id
        first = embedded[0]["docs"][0]
        assert first.metadata["offset"] == 0
        assert first.metadata["attachment_id"] == str(row["id"])
        with db_readonly() as conn:
            source = SourcesRepository(conn).get(source_id, USER)
            listed = SourcesRepository(conn).list_for_user(USER)
        assert source["type"] == ATTACHMENT_SOURCE_TYPE
        assert listed == []

    def test_accepts_the_upload_handle(self, embedded):
        row = _attachment()

        _run(row["legacy_mongo_id"])

        assert _row(row["id"])["metadata"]["index"]["status"] == "done"

    def test_rerun_reuses_the_source(self, embedded):
        row = _attachment()

        _run(row["id"])
        _run(row["id"])

        assert embedded[0]["source_id"] == embedded[1]["source_id"]

    def test_file_without_text_is_skipped(self, embedded):
        row = _attachment(content="", status="no_text")

        assert _run(row["id"])["status"] == "skipped"
        assert _row(row["id"])["metadata"]["index"]["status"] == "skipped"
        assert embedded == []

    def test_embed_failure_is_recorded_and_raised(self, monkeypatch):
        row = _attachment()

        def _boom(*args, **kwargs):
            raise RuntimeError("embedding service down")

        monkeypatch.setattr("docsgpt.worker.embed_and_store_documents", _boom)
        with pytest.raises(RuntimeError):
            _run(row["id"])
        assert _row(row["id"])["metadata"]["index"]["status"] == "failed"

    def test_other_users_attachment_is_not_indexed(self, embedded):
        row = _attachment(user="someone-else")

        assert _run(row["id"], user=USER)["status"] == "missing"
        assert embedded == []


@pytest.mark.usefixtures("wired_engine")
class TestPurgeAttachmentIndexes:
    def test_deletes_the_index_and_the_hidden_source(self, embedded, monkeypatch):
        from docsgpt.worker import purge_attachment_indexes_worker

        row = _attachment()
        _run(row["id"])
        source_id = _row(row["id"])["metadata"]["index"]["source_id"]
        deleted = []

        class _Store:
            def delete_index(self):
                deleted.append(source_id)

        monkeypatch.setattr("docsgpt.worker.settings.VECTOR_STORE", "pgvector")
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore",
            lambda *a, **k: _Store(),
        )

        result = purge_attachment_indexes_worker(_StubTask(), [str(row["id"])], USER)

        assert result == {"purged": 1}
        assert deleted == [source_id]
        with db_readonly() as conn:
            assert SourcesRepository(conn).get(source_id, USER) is None
        assert _row(row["id"])["metadata"]["index"] == {"status": "purged"}

    def test_attachments_without_an_index(self, embedded):
        from docsgpt.worker import purge_attachment_indexes_worker

        row = _attachment(content="", status="no_text")
        assert purge_attachment_indexes_worker(_StubTask(), [str(row["id"])], USER) == {"purged": 0}

    def test_never_touches_another_users_rows(self, embedded):
        from docsgpt.worker import purge_attachment_indexes_worker

        row = _attachment(user="someone-else")
        purge_attachment_indexes_worker(_StubTask(), [str(row["id"])], USER)
        assert _row(row["id"], user="someone-else")["metadata"]["index"] == {"status": "pending"}
