"""Extraction-provenance tests for ``attachment_worker``.

Every parse attempt must leave a queryable trace in ``attachments``:
``metadata.extraction`` records what happened (status, parser, truncation,
token counts, error) on success, truncation, and terminal failure alike.
Runs against a real ephemeral Postgres so the rows the worker writes are
asserted as stored, not as mocked calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import docsgpt.storage.db.engine as engine_module
from docsgpt.parser.file.base_parser import DocumentParseError
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.utils import get_encoding


class _StubTask:
    def update_state(self, *args, **kwargs):
        pass


class _Doc:
    def __init__(self, text):
        self.text = text
        self.extra_info = {}


@pytest.fixture()
def wired_engine(pg_engine, monkeypatch):
    """Point the app's module-level engine cache at the ephemeral DB."""
    monkeypatch.setattr(engine_module, "_engine", None)
    eng = engine_module.get_engine()
    yield eng
    eng.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)


@pytest.fixture()
def storage_dir(tmp_path, monkeypatch):
    """LocalStorage rooted at tmp_path, patched into the worker."""
    from docsgpt.storage.local import LocalStorage

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(
        "docsgpt.storage.storage_creator.StorageCreator.get_storage",
        classmethod(lambda cls: storage),
    )
    return tmp_path


def _run_worker(file_info, user="prov-user"):
    from docsgpt.worker import attachment_worker

    return attachment_worker(_StubTask(), file_info, user)


def _file_info(storage_dir, filename="doc.txt", content=b"hello attachment"):
    attachment_id = str(uuid.uuid4())
    rel_path = f"inputs/prov-user/attachments/{attachment_id}/{filename}"
    full = storage_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    return {
        "filename": filename,
        "attachment_id": attachment_id,
        "path": rel_path,
        "metadata": {"storage_type": "local"},
    }


def _fetch(attachment_id, user="prov-user"):
    with db_readonly() as conn:
        return AttachmentsRepository(conn).get_by_legacy_id(str(attachment_id), user)


def _count(user="prov-user"):
    with db_readonly() as conn:
        return len(AttachmentsRepository(conn).list_for_user(user))


@pytest.mark.usefixtures("wired_engine")
class TestSuccessProvenance:
    def test_ok_row_records_extraction_metadata(self, storage_dir):
        info = _file_info(storage_dir)

        result = _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row is not None
        extraction = (row["metadata"] or {}).get("extraction")
        assert extraction is not None
        assert extraction["status"] == "ok"
        assert extraction["truncated"] is False
        assert extraction["original_tokens"] == extraction["stored_tokens"]
        assert extraction["stored_tokens"] == row["token_count"]
        assert extraction.get("parser")
        assert "hello attachment" in row["content"]
        assert result["token_count"] == row["token_count"]

    def test_upload_metadata_keys_preserved(self, storage_dir):
        info = _file_info(storage_dir)

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        # The storage-level metadata written at upload time must survive
        # the extraction merge.
        assert row["metadata"]["storage_type"] == "local"


@pytest.mark.usefixtures("wired_engine")
class TestTruncationProvenance:
    def test_over_gate_content_truncated_in_token_units(self, storage_dir, monkeypatch):
        # Dense CJK: ~1.4 tokens/char, so a char-unit cut (the old
        # behavior) would store far more than 100k tokens.
        dense = "統計資料表格內容分析、報告書類文書處理系統。設計開發運用管理。\n" * 10000
        info = _file_info(storage_dir)
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc(dense)]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        extraction = row["metadata"]["extraction"]
        assert extraction["status"] == "ok"
        assert extraction["truncated"] is True
        assert extraction["stored_tokens"] == 100000
        assert extraction["original_tokens"] > 100000
        assert row["token_count"] == 100000
        # The stored content really is ~100k tokens, not a 250k-char cut
        # still worth 300k+ tokens.
        enc = get_encoding()
        assert len(enc.encode_ordinary(row["content"])) <= 100100

    def test_under_gate_content_not_truncated(self, storage_dir, monkeypatch):
        text = "plain short attachment content"
        info = _file_info(storage_dir)
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc(text)]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        extraction = row["metadata"]["extraction"]
        assert extraction["truncated"] is False
        assert row["content"] == text


@pytest.mark.usefixtures("wired_engine")
class TestFullTextSideCopy:
    """A cut attachment keeps its whole extracted text next to the original."""

    @staticmethod
    def _long_text():
        # Well past ATTACHMENT_MAX_TOKENS, with a marker only in the tail.
        return " ".join(f"word{i}" for i in range(60_000)) + " TAILMARKER-150"

    def _patch_reader(self, monkeypatch, text):
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc(text)]})(),
        )

    def test_the_whole_text_of_a_cut_file_is_stored_beside_it(self, storage_dir, monkeypatch):
        text = self._long_text()
        info = _file_info(storage_dir, filename="ordinance.txt")
        self._patch_reader(monkeypatch, text)

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        extraction = row["metadata"]["extraction"]
        assert extraction["truncated"] is True
        assert row["token_count"] == 100000
        assert "TAILMARKER-150" not in row["content"]
        assert extraction["full_text_path"] == info["path"] + ".extracted.txt"
        assert (storage_dir / extraction["full_text_path"]).read_text(encoding="utf-8") == text
        assert extraction["full_text_tokens"] == extraction["original_tokens"]
        assert extraction["full_text_bytes"] == len(text.encode("utf-8"))
        assert "full_text_cut" not in extraction

    def test_no_side_copy_when_the_text_fits(self, storage_dir, monkeypatch):
        info = _file_info(storage_dir)
        self._patch_reader(monkeypatch, "short text")

        _run_worker(info)

        extraction = _fetch(info["attachment_id"])["metadata"]["extraction"]
        assert "full_text_path" not in extraction
        assert not (storage_dir / (info["path"] + ".extracted.txt")).exists()

    def test_the_side_copy_is_capped_by_the_setting(self, storage_dir, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 500_000)
        info = _file_info(storage_dir, filename="ordinance.txt")
        self._patch_reader(monkeypatch, self._long_text())

        _run_worker(info)

        extraction = _fetch(info["attachment_id"])["metadata"]["extraction"]
        stored = (storage_dir / extraction["full_text_path"]).read_bytes()
        assert len(stored) <= 500_000
        assert extraction["full_text_bytes"] == len(stored)
        assert extraction["full_text_cut"] is True
        assert 100000 < extraction["full_text_tokens"] < extraction["original_tokens"]

    def test_a_zero_cap_keeps_no_side_copy(self, storage_dir, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 0)
        info = _file_info(storage_dir, filename="ordinance.txt")
        self._patch_reader(monkeypatch, self._long_text())

        _run_worker(info)

        extraction = _fetch(info["attachment_id"])["metadata"]["extraction"]
        assert extraction["truncated"] is True
        assert "full_text_path" not in extraction

    def test_a_failed_side_copy_never_fails_the_upload(self, storage_dir, monkeypatch):
        from docsgpt.storage.local import LocalStorage

        real_save = LocalStorage.save_file

        def _save(self, file_data, path, **kwargs):
            if path.endswith(".extracted.txt"):
                raise OSError("disk full")
            return real_save(self, file_data, path, **kwargs)

        monkeypatch.setattr(LocalStorage, "save_file", _save)
        info = _file_info(storage_dir, filename="ordinance.txt")
        self._patch_reader(monkeypatch, self._long_text())

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row["token_count"] == 100000
        assert "full_text_path" not in row["metadata"]["extraction"]

    def test_a_reused_parse_gets_its_own_side_copy(self, storage_dir, monkeypatch):
        text = self._long_text()
        self._patch_reader(monkeypatch, text)
        first = _file_info(storage_dir, filename="a.txt", content=b"same long bytes")
        second = _file_info(storage_dir, filename="b.txt", content=b"same long bytes")

        _run_worker(first)
        _run_worker(second)

        copy = _fetch(second["attachment_id"])["metadata"]["extraction"]
        assert copy["full_text_path"] == second["path"] + ".extracted.txt"
        assert (storage_dir / copy["full_text_path"]).read_text(encoding="utf-8") == text
        assert copy["full_text_tokens"] == copy["original_tokens"]
        assert copy["full_text_bytes"] == len(text.encode("utf-8"))


    def test_an_earlier_parse_without_a_side_copy_is_parsed_again(self, storage_dir, monkeypatch):
        from docsgpt.core.settings import settings

        text = self._long_text()
        calls = []

        def _reader(**kwargs):
            calls.append(kwargs.get("input_files"))
            return type("R", (), {"load_data": lambda self: [_Doc(text)]})()

        monkeypatch.setattr("docsgpt.worker.SimpleDirectoryReader", _reader)
        first = _file_info(storage_dir, filename="a.txt", content=b"same long bytes")
        second = _file_info(storage_dir, filename="b.txt", content=b"same long bytes")
        # The first upload predates side copies.
        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 0)
        _run_worker(first)
        monkeypatch.setattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 8_000_000)

        _run_worker(second)

        assert len(calls) == 2
        copy = _fetch(second["attachment_id"])["metadata"]
        assert "reused_from" not in copy
        assert copy["extraction"]["full_text_path"] == second["path"] + ".extracted.txt"


@pytest.mark.usefixtures("wired_engine")
class TestFailureProvenance:
    def test_terminal_parse_failure_writes_failed_row(self, storage_dir, monkeypatch):
        info = _file_info(storage_dir, filename="broken.xlsx")

        def _raise(**kwargs):
            raise DocumentParseError("Failed to parse broken.xlsx with docling: boom")

        monkeypatch.setattr("docsgpt.worker.SimpleDirectoryReader", _raise)

        with pytest.raises(DocumentParseError):
            _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row is not None, "terminal failure must leave a queryable row"
        assert row["content"] is None
        extraction = row["metadata"]["extraction"]
        assert extraction["status"] == "failed"
        assert "boom" in extraction["error"]
        # The parser's exception text must never masquerade as document
        # content.
        assert row["token_count"] is None

    def test_retry_then_success_upserts_single_row(self, storage_dir, monkeypatch):
        info = _file_info(storage_dir)
        calls = {"n": 0}

        def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient blip")
            return type("R", (), {"load_data": lambda self: [_Doc("recovered fine")]})()

        monkeypatch.setattr("docsgpt.worker.SimpleDirectoryReader", _flaky)

        with pytest.raises(RuntimeError):
            _run_worker(info)
        failed_row = _fetch(info["attachment_id"])
        assert failed_row["metadata"]["extraction"]["status"] == "failed"

        _run_worker(info)

        assert _count() == 1, "retry success must update the failure row, not add one"
        row = _fetch(info["attachment_id"])
        assert row["metadata"]["extraction"]["status"] == "ok"
        assert row["content"] == "recovered fine"

    def test_post_store_failure_does_not_clobber_ok_row(self, storage_dir):
        # An exception after the success write (e.g. event publishing) must
        # not replace stored content with a NULL-content failed row; the
        # extraction result is already durable.
        from docsgpt.worker import record_attachment_failure

        info = _file_info(storage_dir)
        _run_worker(info)

        record_attachment_failure("prov-user", info, RuntimeError("post-store blip"))

        row = _fetch(info["attachment_id"])
        assert row["metadata"]["extraction"]["status"] == "ok"
        assert "hello attachment" in row["content"]

    def test_failure_row_write_failure_does_not_mask_original_error(
        self, storage_dir, monkeypatch
    ):
        info = _file_info(storage_dir)

        def _raise(**kwargs):
            raise DocumentParseError("original parse error")

        monkeypatch.setattr("docsgpt.worker.SimpleDirectoryReader", _raise)
        monkeypatch.setattr(
            "docsgpt.worker.db_session",
            _raising_db_session,
        )

        with pytest.raises(DocumentParseError, match="original parse error"):
            _run_worker(info)


def _raising_db_session():
    raise ConnectionError("db down")


@pytest.mark.usefixtures("wired_engine")
class TestPoisonProvenance:
    def test_poison_guard_writes_failed_row(self):
        from docsgpt.api.user.tasks import _emit_attachment_poison_event

        attachment_id = str(uuid.uuid4())
        bound = {
            "user": "prov-user",
            "file_info": {
                "filename": "poison.pdf",
                "attachment_id": attachment_id,
                "path": "inputs/prov-user/attachments/x/poison.pdf",
            },
        }

        with patch("docsgpt.events.publisher.publish_user_event") as publish:
            _emit_attachment_poison_event("store_attachment", bound)

        payload = publish.call_args.args[2]
        assert payload["code"] == "repeated_failures"
        assert payload["error"] == "Processing stopped after repeated failures."
        row = _fetch(attachment_id)
        assert row is not None, "poison-guard trip must leave a queryable row"
        extraction = row["metadata"]["extraction"]
        assert extraction["status"] == "failed"
        assert "repeated failures" in extraction["error"]


def _blank_pdf_bytes(pages: int) -> bytes:
    """A real PDF with ``pages`` empty pages, built with pypdfium2."""
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    try:
        for _ in range(pages):
            pdf.new_page(612, 792)
        buffer = io.BytesIO()
        pdf.save(buffer)
    finally:
        pdf.close()
    return buffer.getvalue()


def _pdf_with_image_pages(pages: int, image_pages: int) -> bytes:
    """A PDF of ``pages`` text pages whose first ``image_pages`` also carry a raster image (a scan's page)."""
    import io

    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=(612, 792))
    for index in range(pages):
        if index < image_pages:
            image = io.BytesIO()
            Image.new("RGB", (64, 64), (240, 240, 240)).save(image, "PNG")
            image.seek(0)
            page.drawImage(ImageReader(image), 0, 0, 612, 792)
        page.drawString(72, 720, f"page {index + 1} text")
        page.showPage()
    page.save()
    return buffer.getvalue()


@pytest.mark.usefixtures("wired_engine")
class TestFingerprintProvenance:
    """The planner dedupes and sizes attachments from what the worker records."""

    def test_records_sha256_of_original_bytes_and_size(self, storage_dir):
        import hashlib

        payload = b"invoice 42, total 19.99\n"
        info = _file_info(storage_dir, content=payload)

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row["metadata"]["content_hash"] == hashlib.sha256(payload).hexdigest()
        assert row["size"] == len(payload)
        # Not a paged format: no page count is claimed.
        assert "page_count" not in row["metadata"]
        # The extraction record is untouched by the fingerprint.
        extraction = row["metadata"]["extraction"]
        assert {"truncated", "original_tokens", "stored_tokens"} <= set(extraction)

    def test_identical_bytes_hash_identically_across_uploads(self, storage_dir):
        first = _file_info(storage_dir, filename="a.txt", content=b"same bytes")
        second = _file_info(storage_dir, filename="b.txt", content=b"same bytes")

        _run_worker(first)
        _run_worker(second)

        assert (
            _fetch(first["attachment_id"])["metadata"]["content_hash"]
            == _fetch(second["attachment_id"])["metadata"]["content_hash"]
        )

    def test_pdf_records_page_count(self, storage_dir, monkeypatch):
        payload = _blank_pdf_bytes(3)
        info = _file_info(storage_dir, filename="report.pdf", content=payload)
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc("page text")]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row["metadata"]["page_count"] == 3
        assert row["metadata"]["image_page_count"] == 0

    def test_pdf_records_how_many_pages_carry_an_image(self, storage_dir, monkeypatch):
        # Providers read every page that carries an image as a page image, so
        # an OCR'd scan costs far more than its text; the planner needs the count.
        payload = _pdf_with_image_pages(5, 3)
        info = _file_info(storage_dir, filename="scan.pdf", content=payload)
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc("ocr text")]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row["metadata"]["page_count"] == 5
        assert row["metadata"]["image_page_count"] == 3

    def test_unreadable_pdf_still_gets_a_hash(self, storage_dir, monkeypatch):
        # A file pypdfium2 cannot open keeps its hash; the page count is
        # simply left out rather than failing the upload.
        payload = b"%PDF-1.4 not really a pdf"
        info = _file_info(storage_dir, filename="broken.pdf", content=payload)
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc("some text")]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row["metadata"]["content_hash"]
        assert "page_count" not in row["metadata"]
        assert "image_page_count" not in row["metadata"]


def _counting_reader(monkeypatch, text="parsed once"):
    """Patch the worker's reader with one that counts parses."""
    calls = []

    def _reader(**kwargs):
        calls.append(kwargs.get("input_files"))
        return type("R", (), {"load_data": lambda self: [_Doc(text)]})()

    monkeypatch.setattr("docsgpt.worker.SimpleDirectoryReader", _reader)
    return calls


@pytest.mark.usefixtures("wired_engine")
class TestContentHashReuse:
    """Identical bytes from the same user reuse the parsed text, each upload keeping its own row."""

    def test_hash_is_written_to_the_column(self, storage_dir):
        import hashlib

        payload = b"column hash"
        info = _file_info(storage_dir, content=payload)

        _run_worker(info)

        assert _fetch(info["attachment_id"])["content_hash"] == hashlib.sha256(payload).hexdigest()

    def test_second_upload_of_the_same_bytes_is_not_parsed_again(self, storage_dir, monkeypatch):
        calls = _counting_reader(monkeypatch)
        first = _file_info(storage_dir, filename="a.txt", content=b"same bytes")
        second = _file_info(storage_dir, filename="b.txt", content=b"same bytes")

        _run_worker(first)
        result = _run_worker(second)

        assert len(calls) == 1
        original, copy = _fetch(first["attachment_id"]), _fetch(second["attachment_id"])
        assert copy["id"] != original["id"]
        assert copy["filename"] == "b.txt"
        assert copy["upload_path"] == second["path"]
        assert copy["content"] == original["content"] == "parsed once"
        assert copy["token_count"] == original["token_count"]
        assert copy["content_hash"] == original["content_hash"]
        assert copy["metadata"]["extraction"] == original["metadata"]["extraction"]
        assert copy["metadata"]["reused_from"] == str(original["id"])
        assert copy["metadata"]["storage_type"] == "local"
        assert result["token_count"] == original["token_count"]

    def test_other_users_uploads_are_never_reused(self, storage_dir, monkeypatch):
        calls = _counting_reader(monkeypatch)
        mine = _file_info(storage_dir, content=b"shared bytes")
        theirs = _file_info(storage_dir, content=b"shared bytes")

        _run_worker(theirs, user="another-user")
        _run_worker(mine)

        assert len(calls) == 2
        assert "reused_from" not in _fetch(mine["attachment_id"])["metadata"]

    def test_a_failed_parse_is_not_reused(self, storage_dir, monkeypatch):
        first = _file_info(storage_dir, content=b"flaky bytes")
        monkeypatch.setattr(
            "docsgpt.worker.SimpleDirectoryReader",
            lambda **kwargs: (_ for _ in ()).throw(DocumentParseError("boom")),
        )
        with pytest.raises(DocumentParseError):
            _run_worker(first)

        calls = _counting_reader(monkeypatch, text="second try")
        second = _file_info(storage_dir, content=b"flaky bytes")
        _run_worker(second)

        assert len(calls) == 1
        assert _fetch(second["attachment_id"])["content"] == "second try"

    def test_a_zips_index_is_never_reused_for_another_file(self, storage_dir, monkeypatch):
        import hashlib

        from docsgpt.storage.db.session import db_session

        payload = b"bytes that were also sent as a zip"
        with db_session() as conn:
            AttachmentsRepository(conn).create(
                "prov-user", "bundle.zip", "/z", content="Archive bundle.zip: 1 file(s) unpacked",
                content_hash=hashlib.sha256(payload).hexdigest(),
                metadata={"archive": {"status": "complete"}},
            )
        calls = _counting_reader(monkeypatch, text="parsed text")
        info = _file_info(storage_dir, filename="bundle.txt", content=payload)

        _run_worker(info)

        assert len(calls) == 1
        assert _fetch(info["attachment_id"])["content"] == "parsed text"
