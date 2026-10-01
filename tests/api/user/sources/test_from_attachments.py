"""Tests for docsgpt/api/user/sources/from_attachments.py."""

import io
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.attachments import AttachmentsRepository


MODULE = "docsgpt.api.user.sources.from_attachments"


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
    ), patch(
        f"{MODULE}.StorageCreator.get_storage", return_value=storage
    ), patch(f"{MODULE}.ingest.apply_async", apply_async), patch(
        f"{MODULE}._audit_source_created"
    ):
        yield apply_async


def _attachment(conn, user, filename, *, content=b"hello", metadata=None, legacy=None):
    path = f"inputs/{user}/attachments/{uuid.uuid4()}/{filename}"
    row = AttachmentsRepository(conn).create(
        user,
        filename,
        path,
        content="text",
        token_count=10,
        metadata=metadata or {},
        legacy_mongo_id=legacy,
    )
    return row, path, content


def _post(app, body, user="alice"):
    from docsgpt.api.user.sources.from_attachments import SourceFromAttachments

    with app.test_request_context(
        "/api/sources/from_attachments", method="POST", json=body
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

    def test_copies_originals_and_queues_one_ingest(self, app, pg_conn):
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
        assert storage.files[f"{base_path}/report.pdf"] == b"%PDF"
        assert storage.files[f"{base_path}/data.csv"] == b"x,y"
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
        copied = {k: v for k, v in storage.files.items() if k.startswith(base_path + "/")}
        # Same member name twice: both kept, the second renamed.
        assert sorted(copied.values()) == [b"one", b"two"]
        assert len(copied) == 2
        assert not any(k.endswith(".zip") for k in copied)

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
        assert storage.removed
