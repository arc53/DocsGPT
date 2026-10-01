"""Storing /v1 inline files as the agent owner's attachment rows."""

import hashlib
import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.v1 import attachments as ingest
from docsgpt.api.v1.translator import InlineFile

pytestmark = pytest.mark.unit


def _file(data: bytes, name: str = "a.pdf", mime: str = "application/pdf") -> InlineFile:
    return InlineFile(
        data=data, filename=name, mime_type=mime, content_hash=hashlib.sha256(data).hexdigest(), kind="file"
    )


class _Result:
    def __init__(self, outcome=None):
        self.outcome = outcome
        self.timeouts = []

    def get(self, timeout=None, disable_sync_subtasks=True):
        self.timeouts.append(timeout)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return {"ok": True}


@pytest.fixture
def storage():
    store = MagicMock()
    store.save_file.return_value = {"storage_type": "local"}
    with patch.object(ingest, "_storage", return_value=store):
        yield store


@pytest.fixture
def task():
    with patch.object(ingest, "_dispatch_parse") as dispatch:
        dispatch.return_value = _Result()
        yield dispatch


class TestReuse:
    def test_bytes_the_user_already_sent_reuse_that_row(self, storage, task):
        pdf = _file(b"%PDF-1.4 same bytes")
        with patch.object(ingest, "_find_parsed", return_value={"id": "row-1"}) as find:
            converted = ingest.ingest_inline_files([pdf], "owner")

        assert converted == {pdf.content_hash: "row-1"}
        find.assert_called_once_with("owner", pdf.content_hash, archive=False)
        storage.save_file.assert_not_called()
        task.assert_not_called()


class TestNewFiles:
    def test_new_bytes_are_stored_and_parsed_by_the_worker(self, storage, task):
        pdf = _file(b"%PDF-1.4 new bytes", name="PRILOGA_1.pdf")
        with patch.object(ingest, "_find_parsed", return_value=None):
            converted = ingest.ingest_inline_files([pdf], "owner")

        file_info, user = task.call_args.args[:2]
        assert user == "owner"
        assert converted == {pdf.content_hash: file_info["attachment_id"]}
        assert file_info["filename"] == "PRILOGA_1.pdf"
        assert file_info["path"].endswith(f"/attachments/{file_info['attachment_id']}/PRILOGA_1.pdf")
        saved = storage.save_file.call_args.args[0]
        assert saved.filename == "PRILOGA_1.pdf"

    def test_files_are_dispatched_together_then_awaited(self, storage, task):
        files = [_file(f"%PDF-1.4 {i}".encode(), name=f"f{i}.pdf") for i in range(3)]
        results = [_Result(), _Result(), _Result()]
        task.side_effect = results
        with patch.object(ingest, "_find_parsed", return_value=None):
            converted = ingest.ingest_inline_files(files, "owner")

        assert len(converted) == 3
        assert all(r.timeouts for r in results)

    def test_a_failed_or_slow_parse_is_left_out(self, storage, task):
        good, bad = _file(b"%PDF good", name="g.pdf"), _file(b"%PDF bad", name="b.pdf")
        task.side_effect = [_Result(), _Result(TimeoutError("slow"))]
        with patch.object(ingest, "_find_parsed", return_value=None):
            converted = ingest.ingest_inline_files([good, bad], "owner")

        assert list(converted) == [good.content_hash]

    def test_an_oversized_file_is_left_out(self, storage, task, monkeypatch):
        monkeypatch.setattr(ingest.settings, "UPLOAD_MAX_FILE_BYTES", 10)
        with patch.object(ingest, "_find_parsed", return_value=None):
            assert ingest.ingest_inline_files([_file(b"x" * 11)], "owner") == {}
        task.assert_not_called()

    def test_binary_without_a_parser_is_left_out(self, storage, task):
        blob = _file(b"\x00\x01\x02binary" * 50, name="clip.mp4", mime="video/mp4")
        with patch.object(ingest, "_find_parsed", return_value=None):
            assert ingest.ingest_inline_files([blob], "owner") == {}
        task.assert_not_called()

    def test_a_lookup_failure_does_not_block_the_upload(self, storage, task):
        pdf = _file(b"%PDF lookup fails")
        with patch.object(ingest, "_find_parsed", side_effect=RuntimeError("db down")):
            converted = ingest.ingest_inline_files([pdf], "owner")
        assert pdf.content_hash in converted


def _zip_file(name: str = "bundle.zip") -> InlineFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("a.txt", "inside")
    return _file(buffer.getvalue(), name=name, mime="application/zip")


class TestZips:
    @pytest.fixture(autouse=True)
    def _no_poll_wait(self, monkeypatch):
        monkeypatch.setattr(ingest, "_ARCHIVE_POLL_SECONDS", 0.001)

    def test_a_zip_is_reused_only_from_an_earlier_zip(self, storage, task):
        bundle = _zip_file()
        with patch.object(ingest, "_find_parsed", return_value={"id": "zip-row"}) as find:
            converted = ingest.ingest_inline_files([bundle], "owner")

        find.assert_called_once_with("owner", bundle.content_hash, archive=True)
        assert converted == {bundle.content_hash: "zip-row"}

    def test_a_zip_counts_as_parsed_once_its_members_finish(self, storage, task):
        bundle = _zip_file()
        states = iter(["processing", "processing", "complete"])
        with patch.object(ingest, "_find_parsed", return_value=None), patch.object(
            ingest, "_archive_status", side_effect=lambda user, attachment_id: next(states)
        ) as status:
            converted = ingest.ingest_inline_files([bundle], "owner")

        file_info = task.call_args.args[0]
        assert converted == {bundle.content_hash: file_info["attachment_id"]}
        assert status.call_count == 3
        assert status.call_args.args == ("owner", file_info["attachment_id"])

    def test_a_zip_still_unpacking_at_the_deadline_is_left_out(self, storage, task, monkeypatch):
        monkeypatch.setattr(ingest, "_parse_timeout", lambda size: 0.05)
        bundle, pdf = _zip_file(), _file(b"%PDF beside the zip", name="p.pdf")
        with patch.object(ingest, "_find_parsed", return_value=None), patch.object(
            ingest, "_archive_status", return_value="processing"
        ):
            converted = ingest.ingest_inline_files([bundle, pdf], "owner")

        assert list(converted) == [pdf.content_hash]

    def test_a_non_zip_never_waits_on_archive_state(self, storage, task):
        with patch.object(ingest, "_find_parsed", return_value=None), patch.object(
            ingest, "_archive_status"
        ) as status:
            ingest.ingest_inline_files([_file(b"%PDF plain")], "owner")

        status.assert_not_called()
