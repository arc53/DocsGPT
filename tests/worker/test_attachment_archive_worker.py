"""A zip attachment is unpacked into one attachment per member.

Runs the worker against a real ephemeral Postgres and local storage, so the
rows it writes are asserted as stored.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

import docsgpt.storage.db.engine as engine_module
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.session import db_readonly

USER = "zip-user"


class _StubTask:
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
def storage_dir(tmp_path, monkeypatch):
    from docsgpt.storage.local import LocalStorage

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(
        "docsgpt.storage.storage_creator.StorageCreator.get_storage",
        classmethod(lambda cls: storage),
    )
    return tmp_path


@pytest.fixture()
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "docsgpt.worker.publish_user_event",
        lambda user, kind, payload, scope=None: seen.append((kind, dict(payload))),
    )
    return seen


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buffer.getvalue()


def _upload(storage_dir, payload, filename="bundle.zip"):
    attachment_id = str(uuid.uuid4())
    rel_path = f"inputs/{USER}/attachments/{attachment_id}/{filename}"
    full = storage_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(payload)
    return {"filename": filename, "attachment_id": attachment_id, "path": rel_path, "metadata": {}}


def _run(info):
    from docsgpt.worker import attachment_worker

    return attachment_worker(_StubTask(), info, USER)


def _parent(info):
    with db_readonly() as conn:
        return AttachmentsRepository(conn).get_by_legacy_id(info["attachment_id"], USER)


def _members(parent_id):
    with db_readonly() as conn:
        rows = AttachmentsRepository(conn).list_for_user(USER)
    members = [r for r in rows if (r.get("metadata") or {}).get("parent_attachment_id") == str(parent_id)]
    return sorted(members, key=lambda r: r["metadata"]["archive_index"])


ENTRIES = [
    ("notes.txt", b"meeting notes about the budget"),
    ("docs/readme.md", b"# Readme\nproject overview"),
    ("tool.exe", bytes(range(256)) * 8),
    ("nested.zip", _zip([("inner.txt", b"inner text file")])),
]


@pytest.mark.usefixtures("wired_engine")
class TestZipAttachment:
    def test_members_become_their_own_parsed_attachments(self, storage_dir, events):
        info = _upload(storage_dir, _zip(ENTRIES))

        result = _run(info)

        parent = _parent(info)
        members = _members(parent["id"])
        assert [m["metadata"]["archive_path"] for m in members] == [
            "notes.txt", "docs/readme.md", "nested.zip/inner.txt",
        ]
        assert [m["filename"] for m in members] == ["notes.txt", "readme.md", "inner.txt"]
        assert "budget" in members[0]["content"]
        assert "inner text" in members[2]["content"]
        for member in members:
            assert member["metadata"]["extraction"]["status"] == "ok"
            assert member["content_hash"]
            assert (storage_dir / member["upload_path"]).is_file()
            assert member["upload_path"] != parent["upload_path"]
        assert result["attachment_id"] == info["attachment_id"]

    def test_parent_is_an_index_not_the_compressed_bytes(self, storage_dir, events):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run(info)

        parent = _parent(info)
        assert parent["mime_type"] == "application/zip"
        assert "PK" not in parent["content"]
        assert "notes.txt" in parent["content"] and "tool.exe" in parent["content"]
        archive = parent["metadata"]["archive"]
        assert archive["members"] == 3
        assert {"archive_path": "tool.exe", "reason": "unsupported_type"} in archive["skipped"]
        assert archive["skipped_count"] == 1
        assert parent["metadata"]["extraction"]["status"] == "ok"
        assert parent["content_hash"]

    def test_only_the_zip_reports_progress(self, storage_dir, events):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run(info)

        ids = {payload["attachment_id"] for _, payload in events}
        assert ids == {info["attachment_id"]}
        kinds = [kind for kind, _ in events]
        assert kinds[0] == "attachment.queued" and kinds[-1] == "attachment.completed"
        completed = events[-1][1]
        assert completed["archive"] == {"members": 3, "skipped": 1}
        assert completed["token_count"] > 0

    def test_a_retry_updates_the_same_member_rows(self, storage_dir, events):
        info = _upload(storage_dir, _zip(ENTRIES))

        _run(info)
        _run(info)

        assert len(_members(_parent(info)["id"])) == 3

    def test_a_zip_bomb_fails_the_upload(self, storage_dir, events):
        from docsgpt.worker import AttachmentRejectedError

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.txt", b"\0" * (5 * 1024 * 1024))
        info = _upload(storage_dir, buffer.getvalue())

        with pytest.raises(AttachmentRejectedError):
            _run(info)

        assert events[-1][0] == "attachment.failed"
        assert _parent(info)["metadata"]["extraction"]["status"] == "failed"
