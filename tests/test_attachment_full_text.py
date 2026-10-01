"""The side copy that keeps a cut attachment's whole extracted text."""

import io

import pytest

from docsgpt.attachment_full_text import (
    copy_full_text,
    full_text_location,
    full_text_tokens,
    load_full_text,
    store_full_text,
)
from docsgpt.utils import get_encoding

pytestmark = pytest.mark.unit


class _Storage:
    def __init__(self):
        self.files = {}

    def save_file(self, data, path, **kwargs):
        self.files[path] = data.read()
        return {}

    def get_file(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return io.BytesIO(self.files[path])


def _row(path="u/attachments/a/doc.txt", **extraction):
    return {"upload_path": path, "metadata": {"extraction": {"truncated": True, **extraction}}}


class TestStore:
    def test_a_zero_cap_keeps_nothing(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 0)
        storage = _Storage()
        assert store_full_text(storage, "u/doc.txt", "text", get_encoding(), 1) == {}
        assert storage.files == {}

    def test_a_multibyte_text_is_cut_on_a_character_boundary(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 7)
        storage = _Storage()
        info = store_full_text(storage, "u/doc.txt", "člen člen", get_encoding(), 4)
        saved = storage.files["u/doc.txt.extracted.txt"]
        assert len(saved) <= 7
        saved.decode("utf-8")
        assert info["full_text_cut"] is True


class TestCopy:
    def test_a_missing_source_drops_the_side_copy_keys(self):
        extraction = {"status": "ok", "full_text_path": "gone.extracted.txt", "full_text_tokens": 9}
        assert copy_full_text(_Storage(), extraction, "u/new.txt") == {"status": "ok"}

    def test_no_side_copy_is_left_as_it_is(self):
        assert copy_full_text(_Storage(), {"status": "ok"}, "u/new.txt") == {"status": "ok"}


class TestLocation:
    def test_only_a_copy_beside_the_rows_own_file_is_trusted(self):
        good = _row(full_text_path="u/attachments/a/doc.txt.extracted.txt", full_text_tokens=5)
        assert full_text_location(good) == "u/attachments/a/doc.txt.extracted.txt"
        assert full_text_tokens(good) == 5
        assert full_text_location(_row(full_text_path="other/doc.txt.extracted.txt")) is None
        assert full_text_location(_row(full_text_path="u/attachments/a/doc.txt")) is None

    def test_a_row_that_was_not_cut_has_none(self):
        row = _row(full_text_path="u/attachments/a/doc.txt.extracted.txt")
        row["metadata"]["extraction"]["truncated"] = False
        assert full_text_location(row) is None
        assert full_text_tokens({"metadata": None}) is None

    def test_an_unusable_token_count_reads_as_none(self):
        row = _row(full_text_path="u/attachments/a/doc.txt.extracted.txt", full_text_tokens="many")
        assert full_text_tokens(row) is None


class TestLoad:
    def test_a_missing_copy_loads_as_none(self):
        assert load_full_text(_Storage(), "nope.extracted.txt") is None

    def test_a_zero_cap_loads_nothing(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 0)
        storage = _Storage()
        storage.files["a.extracted.txt"] = b"text"
        assert load_full_text(storage, "a.extracted.txt") is None
