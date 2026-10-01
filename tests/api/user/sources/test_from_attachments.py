"""Tests for docsgpt/api/user/sources/from_attachments.py."""

import io
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.attachments import AttachmentsRepository


MODULE = "docsgpt.api.user.sources.from_attachments"
# The Idempotency-Key claim helpers are shared with the upload route.
UPLOAD_MODULE = "docsgpt.api.user.sources.upload"


@pytest.fixture
def app():
    return Flask(__name__)


class FakeStorage:
    """In-memory storage with the methods the route uses."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.removed = []

    def get_file(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return io.BytesIO(self.files[path])

    def save_file(self, file_data, path, **kwargs):
        self.files[path] = file_data.read()
        return {"storage_type": "fake"}

    def file_exists(self, path):
        return path in self.files

    def get_file_size(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return len(self.files[path])

    def remove_directory(self, directory):
        self.removed.append(directory)
        for key in [k for k in self.files if k.startswith(directory + "/")]:
            del self.files[key]
        return True


@contextmanager
def _patched(conn, storage, task_id="task-1"):
    @contextmanager
    def _yield():
        yield conn

    apply_async = MagicMock(return_value=MagicMock(id=task_id))
    with patch(f"{MODULE}.db_session", _yield), patch(
        f"{MODULE}.db_readonly", _yield
    ), patch(f"{UPLOAD_MODULE}.db_session", _yield), patch(
        f"{UPLOAD_MODULE}.db_readonly", _yield
    ), patch(
        f"{MODULE}.StorageCreator.get_storage", return_value=storage
    ), patch(f"{MODULE}.ingest.apply_async", apply_async), patch(
        f"{MODULE}._audit_source_created"
    ):
        yield apply_async


def _attachment(conn, user, filename, *, content=b"hello", metadata=None, legacy=None, size=-1):
    path = f"inputs/{user}/attachments/{uuid.uuid4()}/{filename}"
    row = AttachmentsRepository(conn).create(
        user,
        filename,
        path,
        size=len(content) if size == -1 else size,
        content="text",
        token_count=10,
        metadata=metadata or {},
        legacy_mongo_id=legacy,
    )
    return row, path, content


def _post(app, body, user="alice", headers=None):
    from docsgpt.api.user.sources.from_attachments import SourceFromAttachments

    with app.test_request_context(
        "/api/sources/from_attachments", method="POST", json=body, headers=headers or {}
    ):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return SourceFromAttachments().post()


class TestDefaultName:
    def test_single_file_is_its_name(self):
        from docsgpt.api.user.sources.from_attachments import default_source_name

        assert default_source_name(["report.pdf"]) == "report.pdf"

    def test_several_files_name_the_first_and_count_the_rest(self):
        from docsgpt.api.user.sources.from_attachments import default_source_name

        assert default_source_name(["a.pdf", "b.csv", "c.png"]) == "a.pdf and 2 more"


class TestSourceFromAttachments:
    def test_requires_auth(self, app):
        response = _post(app, {"attachment_ids": ["x"]}, user=None)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "body",
        [{}, {"attachment_ids": []}, {"attachment_ids": "abc"}, {"attachment_ids": [1, 2]}],
    )
    def test_rejects_missing_or_malformed_ids(self, app, body):
        response = _post(app, body)
        assert response.status_code == 400

    def test_queues_one_ingest_that_copies_the_originals(self, app, pg_conn):
        user = "alice"
        a, a_path, a_bytes = _attachment(pg_conn, user, "report.pdf", content=b"%PDF")
        b, b_path, b_bytes = _attachment(pg_conn, user, "data.csv", content=b"x,y")
        storage = FakeStorage({a_path: a_bytes, b_path: b_bytes})

        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(a["id"]), str(b["id"])]}, user)

        assert response.status_code == 200, response.json
        body = response.json
        assert body["success"] is True
        assert body["task_id"] == "task-1"
        assert body["name"] == "report.pdf and 1 more"
        source_id = body["source_id"]
        uuid.UUID(source_id)

        apply_async.assert_called_once()
        kwargs = apply_async.call_args.kwargs
        _upload_folder, _formats, job_name, task_user = kwargs["args"]
        assert job_name == "report.pdf and 1 more"
        assert task_user == user
        assert kwargs["kwargs"]["source_id"] == source_id
        base_path = kwargs["kwargs"]["file_path"]
        # The worker copies the originals, not the request.
        assert sorted(storage.files) == sorted([a_path, b_path])
        assert kwargs["kwargs"]["copy_files"] == [
            {"from": a_path, "to": f"{base_path}/report.pdf"},
            {"from": b_path, "to": f"{base_path}/data.csv"},
        ]
        assert kwargs["kwargs"]["file_name_map"] == {
            "report.pdf": "report.pdf",
            "data.csv": "data.csv",
        }

    def test_uses_the_name_given(self, app, pg_conn):
        a, a_path, a_bytes = _attachment(pg_conn, "alice", "report.pdf")
        storage = FakeStorage({a_path: a_bytes})
        with _patched(pg_conn, storage) as apply_async:
            response = _post(
                app, {"attachment_ids": [str(a["id"])], "name": "  Q3 invoices "}, "alice"
            )
        assert response.status_code == 200
        assert response.json["name"] == "Q3 invoices"
        assert apply_async.call_args.kwargs["args"][2] == "Q3 invoices"

    def test_resolves_the_upload_handle_the_composer_holds(self, app, pg_conn):
        handle = str(uuid.uuid4())
        a, a_path, a_bytes = _attachment(pg_conn, "alice", "notes.md", legacy=handle)
        storage = FakeStorage({a_path: a_bytes})
        with _patched(pg_conn, storage):
            response = _post(app, {"attachment_ids": [handle]}, "alice")
        assert response.status_code == 200, response.json

    def test_refuses_another_users_attachment(self, app, pg_conn):
        a, a_path, a_bytes = _attachment(pg_conn, "bob", "secret.pdf")
        storage = FakeStorage({a_path: a_bytes})
        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(a["id"])]}, "alice")
        assert response.status_code == 404
        apply_async.assert_not_called()
        assert list(storage.files) == [a_path]

    def test_unknown_id_is_not_found(self, app, pg_conn):
        storage = FakeStorage()
        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(uuid.uuid4())]}, "alice")
        assert response.status_code == 404
        apply_async.assert_not_called()

    def test_zip_is_replaced_by_its_members(self, app, pg_conn):
        user = "alice"
        zip_row, zip_path, _ = _attachment(
            pg_conn, user, "bundle.zip", metadata={"archive": {"members": 2}}
        )
        m1, m1_path, m1_bytes = _attachment(
            pg_conn,
            user,
            "a.txt",
            content=b"one",
            metadata={"parent_attachment_id": str(zip_row["id"]), "archive_index": 0},
        )
        m2, m2_path, m2_bytes = _attachment(
            pg_conn,
            user,
            "a.txt",
            content=b"two",
            metadata={"parent_attachment_id": str(zip_row["id"]), "archive_index": 1},
        )
        storage = FakeStorage({m1_path: m1_bytes, m2_path: m2_bytes})

        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(zip_row["id"])]}, user)

        assert response.status_code == 200, response.json
        assert response.json["name"] == "bundle.zip"
        base_path = apply_async.call_args.kwargs["kwargs"]["file_path"]
        copies = apply_async.call_args.kwargs["kwargs"]["copy_files"]
        # Same member name twice: both kept, the second renamed.
        assert copies == [
            {"from": m1_path, "to": f"{base_path}/a.txt"},
            {"from": m2_path, "to": f"{base_path}/a-2.txt"},
        ]

    def test_records_the_source_on_each_attachment(self, app, pg_conn):
        a, a_path, a_bytes = _attachment(pg_conn, "alice", "report.pdf", metadata={"pages": 3})
        storage = FakeStorage({a_path: a_bytes})
        with _patched(pg_conn, storage):
            response = _post(app, {"attachment_ids": [str(a["id"])]}, "alice")
        assert response.status_code == 200
        row = AttachmentsRepository(pg_conn).get(str(a["id"]), "alice")
        assert row["metadata"]["knowledge_source_id"] == response.json["source_id"]
        assert row["metadata"]["pages"] == 3

    def test_missing_original_fails_without_queueing(self, app, pg_conn):
        a, _a_path, _ = _attachment(pg_conn, "alice", "gone.pdf")
        storage = FakeStorage()
        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(a["id"])]}, "alice")
        assert response.status_code == 500
        assert response.json["success"] is False
        apply_async.assert_not_called()

    def test_a_set_over_the_upload_request_limit_is_refused(self, app, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "UPLOAD_MAX_REQUEST_BYTES", 6)
        a, a_path, a_bytes = _attachment(pg_conn, "alice", "a.pdf", content=b"1234")
        b, b_path, b_bytes = _attachment(pg_conn, "alice", "b.pdf", content=b"5678")
        storage = FakeStorage({a_path: a_bytes, b_path: b_bytes})
        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(a["id"]), str(b["id"])]}, "alice")
        assert response.status_code == 413
        assert "6-byte" in response.json["message"]
        apply_async.assert_not_called()

    def test_a_row_without_a_recorded_size_is_measured_in_storage(self, app, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "UPLOAD_MAX_REQUEST_BYTES", 6)
        a, a_path, _ = _attachment(pg_conn, "alice", "a.pdf", content=b"1234567", size=None)
        storage = FakeStorage({a_path: b"1234567"})
        with _patched(pg_conn, storage) as apply_async:
            response = _post(app, {"attachment_ids": [str(a["id"])]}, "alice")
        assert response.status_code == 413
        apply_async.assert_not_called()


class TestIdempotencyKey:
    """A repeat with the same Idempotency-Key returns the first source."""

    def _dedup_row(self, conn, key):
        from sqlalchemy import text

        return conn.execute(
            text("SELECT task_id, task_name, status FROM task_dedup WHERE idempotency_key = :k"),
            {"k": key},
        ).fetchone()

    def test_a_repeat_returns_the_first_source_without_a_second_ingest(self, app, pg_conn):
        from docsgpt.storage.db.source_ids import derive_source_id

        a, a_path, a_bytes = _attachment(pg_conn, "alice", "report.pdf")
        storage = FakeStorage({a_path: a_bytes})
        body = {"attachment_ids": [str(a["id"])]}
        headers = {"Idempotency-Key": "k-1"}

        with _patched(pg_conn, storage) as apply_async:
            first = _post(app, body, "alice", headers)
            copied = dict(storage.files)
            second = _post(app, body, "alice", headers)

        assert first.status_code == 200, first.json
        assert second.status_code == 200, second.json
        apply_async.assert_called_once()
        assert storage.files == copied
        assert second.json["source_id"] == first.json["source_id"]
        assert second.json["task_id"] == first.json["task_id"]
        # The same id scheme as /api/upload: the worker lands on that source.
        assert first.json["source_id"] == str(derive_source_id("alice:k-1"))
        call = apply_async.call_args.kwargs
        assert call["task_id"] == first.json["task_id"]
        assert call["kwargs"]["idempotency_key"] == "alice:k-1"
        assert call["kwargs"]["source_id"] == first.json["source_id"]
        assert self._dedup_row(pg_conn, "alice:k-1")[1] == "ingest"

    def test_the_key_is_scoped_to_the_user(self, app, pg_conn):
        a, a_path, a_bytes = _attachment(pg_conn, "alice", "a.pdf")
        b, b_path, b_bytes = _attachment(pg_conn, "bob", "b.pdf")
        storage = FakeStorage({a_path: a_bytes, b_path: b_bytes})
        headers = {"Idempotency-Key": "same"}

        with _patched(pg_conn, storage) as apply_async:
            first = _post(app, {"attachment_ids": [str(a["id"])]}, "alice", headers)
            second = _post(app, {"attachment_ids": [str(b["id"])]}, "bob", headers)

        assert apply_async.call_count == 2
        assert first.json["source_id"] != second.json["source_id"]

    def test_a_failed_request_releases_the_key_for_a_retry(self, app, pg_conn):
        a, a_path, a_bytes = _attachment(pg_conn, "alice", "gone.pdf")
        storage = FakeStorage()
        headers = {"Idempotency-Key": "k-2"}

        with _patched(pg_conn, storage) as apply_async:
            failed = _post(app, {"attachment_ids": [str(a["id"])]}, "alice", headers)
            assert failed.status_code == 500
            assert self._dedup_row(pg_conn, "alice:k-2") is None

            storage.files[a_path] = a_bytes
            retried = _post(app, {"attachment_ids": [str(a["id"])]}, "alice", headers)

        assert retried.status_code == 200, retried.json
        apply_async.assert_called_once()

    def test_a_rejected_request_does_not_claim_the_key(self, app, pg_conn):
        with _patched(pg_conn, FakeStorage()):
            response = _post(app, {"attachment_ids": [str(uuid.uuid4())]}, "alice", {"Idempotency-Key": "k-3"})
        assert response.status_code == 404
        assert self._dedup_row(pg_conn, "alice:k-3") is None

    def test_an_oversized_key_is_refused(self, app, pg_conn):
        with _patched(pg_conn, FakeStorage()) as apply_async:
            response = _post(app, {"attachment_ids": ["x"]}, "alice", {"Idempotency-Key": "k" * 300})
        assert response.status_code == 400
        apply_async.assert_not_called()
