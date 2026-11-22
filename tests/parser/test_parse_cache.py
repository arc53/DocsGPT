"""The parse cache: a user's identical file is parsed once, whatever source it is ingested into."""

from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Union

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.parser import parse_cache
from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError
from docsgpt.parser.file.bulk import SimpleDirectoryReader


class CountingParser(BaseParser):
    """Stands in for an OCR parser: counts its calls and returns what it is told to."""

    def __init__(self, output: Union[str, List[str]] = "scanned text", metadata: Optional[Dict] = None,
                 error: Optional[Exception] = None) -> None:
        super().__init__()
        self.output = output
        self.metadata = metadata if metadata is not None else {"parse_engine": "fake", "pdf_pages": 2}
        self.error = error
        self.calls = 0
        self.inits = 0

    def _init_parser(self) -> Dict:
        self.inits += 1
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output

    def get_file_metadata(self, file: Path) -> Dict:
        return dict(self.metadata)


class MemoryStorage:
    def __init__(self) -> None:
        self.files: Dict[str, bytes] = {}

    def save_file(self, file_data, path: str, **kwargs) -> dict:
        self.files[path] = file_data.read()
        return {"path": path}

    def get_file(self, path: str):
        if path not in self.files:
            raise FileNotFoundError(path)
        return io.BytesIO(self.files[path])

    def delete_file(self, path: str) -> bool:
        return self.files.pop(path, None) is not None


@pytest.fixture
def storage(monkeypatch):
    store = MemoryStorage()
    monkeypatch.setattr(parse_cache, "_storage", lambda: store)
    return store


@pytest.fixture
def cache_db(pg_conn, monkeypatch, storage):
    """The cache on: its database is the test's transaction, its storage in memory."""

    @contextmanager
    def _use_pg_conn():
        yield pg_conn

    monkeypatch.setattr(parse_cache, "db_session", _use_pg_conn)
    monkeypatch.setattr(settings, "PARSE_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "POSTGRES_URI", "postgresql://stub", raising=False)
    return pg_conn


def _folder(root: Path, name: str, files: Dict[str, bytes]) -> Path:
    folder = root / name
    for rel, data in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return folder


def _read(folder: Path, parser: BaseParser, user: Optional[str] = "alice", suffix: str = ".pdf"):
    reader = SimpleDirectoryReader(
        input_dir=str(folder),
        file_extractor={suffix: parser},
        file_metadata=lambda name: {"title": name},
        parse_cache_user=user,
    )
    return reader, reader.load_data()


def _rows(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM parsed_files")).scalar()


class TestReuse:
    def test_the_same_file_in_two_sources_is_parsed_once_with_identical_documents(self, tmp_path, cache_db):
        parser = CountingParser(output=["page one", "page two"])
        first, first_docs = _read(_folder(tmp_path, "one", {"scan.pdf": b"%PDF same bytes"}), parser)
        second, second_docs = _read(_folder(tmp_path, "two", {"nested/copy.pdf": b"%PDF same bytes"}), parser)

        assert parser.calls == 1
        assert (first.cache_hits, second.cache_hits) == (0, 1)
        assert [d.text for d in first_docs] == [d.text for d in second_docs] == ["page one", "page two"]
        # What depends on where the file is comes from this read, never the cache.
        assert {d.extra_info["source"] for d in second_docs} == {"nested/copy.pdf"}
        assert {d.extra_info["title"] for d in second_docs} == {"copy.pdf"}
        strip = ("source", "title")
        assert [{k: v for k, v in d.extra_info.items() if k not in strip} for d in first_docs] == [
            {k: v for k, v in d.extra_info.items() if k not in strip} for d in second_docs
        ]

    def test_a_hit_skips_the_parser_init_too(self, tmp_path, cache_db):
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), CountingParser())
        fresh = CountingParser()
        _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), fresh)
        assert (fresh.calls, fresh.inits) == (0, 0)

    def test_different_bytes_miss(self, tmp_path, cache_db):
        parser = CountingParser()
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        _read(_folder(tmp_path, "two", {"a.pdf": b"y"}), parser)
        assert parser.calls == 2

    def test_another_users_identical_file_is_not_reused(self, tmp_path, cache_db):
        parser = CountingParser()
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser, user="alice")
        reader, _ = _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), parser, user="bob")
        assert parser.calls == 2
        assert reader.cache_hits == 0

    @pytest.mark.parametrize(
        "setting, value",
        [("OCR_ENGINE", "deepseek"), ("OCR_DEEPSEEK_MODEL", "other-ocr-model"), ("OCR_RENDER_DPI", 300),
         ("OCR_LANGS", "eng+deu"), ("DOC_PARSER_ENGINE", "docling")],
    )
    def test_a_different_ocr_engine_model_or_dpi_misses(self, tmp_path, cache_db, monkeypatch, setting, value):
        monkeypatch.setattr(settings, "OCR_ENABLED", True)
        monkeypatch.setattr(settings, "OCR_BACKEND", "native")
        monkeypatch.setattr(settings, "OCR_ENGINE", "deepseek")
        monkeypatch.setattr(settings, "OCR_DEEPSEEK_PROVIDER", "vllm")
        parser = CountingParser()
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        if setting == "OCR_ENGINE":
            value = "tesseract"
        monkeypatch.setattr(settings, setting, value)
        _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), parser)
        assert parser.calls == 2

    def test_a_different_parser_class_misses(self, tmp_path, cache_db):
        class OtherParser(CountingParser):
            pass

        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), CountingParser())
        other = OtherParser()
        _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), other)
        assert other.calls == 1


class TestWhatIsStored:
    def test_a_failed_parse_is_not_cached(self, tmp_path, cache_db):
        failing = CountingParser(error=DocumentParseError("OCR rate limited"))
        with pytest.raises(DocumentParseError):
            _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), failing)
        assert _rows(cache_db) == 0
        good = CountingParser()
        _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), good)
        assert good.calls == 1

    def test_a_partly_ocrd_file_is_not_cached(self, tmp_path, cache_db):
        partial = CountingParser(metadata={"ocr_pages": 3, "ocr_pages_failed": 1})
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), partial)
        assert _rows(cache_db) == 0
        _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), partial)
        assert partial.calls == 2

    def test_cheap_text_formats_are_not_cached(self, tmp_path, cache_db):
        parser = CountingParser()
        _read(_folder(tmp_path, "one", {"a.md": b"# hi"}), parser, suffix=".md")
        _read(_folder(tmp_path, "two", {"a.md": b"# hi"}), parser, suffix=".md")
        assert parser.calls == 2
        assert _rows(cache_db) == 0

    def test_nul_bytes_are_stripped_before_postgres(self, tmp_path, cache_db):
        parser = CountingParser(output="a\x00b", metadata={"note": "c\x00d"})
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        _, docs = _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), parser)
        assert parser.calls == 1
        assert docs[0].text == "ab"
        assert docs[0].extra_info["note"] == "cd"

    def test_page_counts_are_recorded(self, tmp_path, cache_db):
        parser = CountingParser(metadata={"pdf_pages": 4, "ocr_pages": 3, "ocr_requests": 3})
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        row = cache_db.execute(text("SELECT page_count, billed_pages FROM parsed_files")).one()
        assert tuple(row) == (4, 3)

    def test_a_large_parse_goes_to_storage(self, tmp_path, cache_db, storage, monkeypatch):
        monkeypatch.setattr(parse_cache, "INLINE_MAX_BYTES", 10)
        parser = CountingParser(output=["x" * 50, "y" * 50])
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        content, path = cache_db.execute(text("SELECT content, storage_path FROM parsed_files")).one()
        assert content is None
        assert path in storage.files and path.startswith("parse_cache/")
        assert "alice" not in path

        _, docs = _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), parser)
        assert parser.calls == 1
        assert [d.text for d in docs] == ["x" * 50, "y" * 50]

    def test_a_missing_storage_file_is_a_miss(self, tmp_path, cache_db, storage, monkeypatch):
        monkeypatch.setattr(parse_cache, "INLINE_MAX_BYTES", 10)
        parser = CountingParser(output="z" * 50)
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        storage.files.clear()
        _, docs = _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), parser)
        assert parser.calls == 2
        assert docs[0].text == "z" * 50


class TestStorageFiles:
    def test_a_failed_row_write_removes_its_file(self, tmp_path, cache_db, storage, monkeypatch):
        from docsgpt.storage.db.repositories.parsed_files import ParsedFilesRepository

        monkeypatch.setattr(parse_cache, "INLINE_MAX_BYTES", 10)
        monkeypatch.setattr(
            ParsedFilesRepository, "store", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("commit failed")),
        )
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), CountingParser(output="z" * 50))
        assert storage.files == {}

    def test_a_replaced_parse_leaves_one_file(self, tmp_path, cache_db, storage, monkeypatch):
        monkeypatch.setattr(parse_cache, "INLINE_MAX_BYTES", 10)
        parser = CountingParser(output="z" * 50)
        cache = parse_cache.ParseCache("alice")
        cache.store("sha", parser, "z" * 50, {})
        cache.store("sha", parser, "w" * 50, {})
        [path] = storage.files
        assert cache_db.execute(text("SELECT storage_path FROM parsed_files")).scalar() == path


class TestOff:
    def test_disabled_never_reads_or_writes(self, tmp_path, cache_db, monkeypatch):
        monkeypatch.setattr(settings, "PARSE_CACHE_ENABLED", False)

        def _boom():
            raise AssertionError("the cache must not touch the database")

        monkeypatch.setattr(parse_cache, "db_session", _boom)
        parser = CountingParser()
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser)
        _read(_folder(tmp_path, "two", {"a.pdf": b"x"}), parser)
        assert parser.calls == 2

    def test_no_user_never_reads_or_writes(self, tmp_path, cache_db, monkeypatch):
        monkeypatch.setattr(parse_cache, "db_session", lambda: (_ for _ in ()).throw(AssertionError("no")))
        parser = CountingParser()
        _read(_folder(tmp_path, "one", {"a.pdf": b"x"}), parser, user=None)
        assert parser.calls == 1

    def test_a_database_failure_parses_as_without_a_cache(self, tmp_path, cache_db, monkeypatch):
        calls = []

        @contextmanager
        def _down():
            calls.append(1)
            raise RuntimeError("database down")
            yield  # pragma: no cover

        monkeypatch.setattr(parse_cache, "db_session", _down)
        parser = CountingParser()
        _, docs = _read(_folder(tmp_path, "one", {"a.pdf": b"x", "b.pdf": b"y"}), parser)
        assert parser.calls == 2
        assert len(docs) == 2
        # One failure turns the cache off for the rest of the read.
        assert len(calls) == 1


class TestCleanup:
    def test_cleanup_deletes_stale_rows_and_their_files(self, tmp_path, cache_db, storage, monkeypatch):
        monkeypatch.setattr(parse_cache, "INLINE_MAX_BYTES", 10)
        _read(_folder(tmp_path, "one", {"old.pdf": b"old"}), CountingParser(output="o" * 50))
        cache_db.execute(text("UPDATE parsed_files SET last_used_at = now() - interval '100 days'"))
        _read(_folder(tmp_path, "two", {"new.pdf": b"new"}), CountingParser(output="n"))
        assert len(storage.files) == 1

        assert parse_cache.cleanup_stale_parses(90) == {"deleted": 1, "ttl_days": 90}
        assert storage.files == {}
        assert _rows(cache_db) == 1
