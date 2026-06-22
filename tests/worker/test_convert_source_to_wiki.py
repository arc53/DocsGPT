"""Tests for ``application.worker.convert_source_to_wiki_worker``.

The worker re-parses a source's stored originals into wiki pages and enqueues
a per-page re-embed. Storage, ``SimpleDirectoryReader``, and the re-embed task
are mocked so no real downloads or embeddings run; the ``sources`` /
``wiki_pages`` rows are real so the assertions read them back.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.wiki_pages import WikiPagesRepository


def _seed_source(pg_conn, config=None, file_path="inputs/alice/doc-set"):
    src = SourcesRepository(pg_conn).create(
        "doc-set",
        user_id="alice",
        type="local",
        retriever="classic",
        file_path=file_path,
        config=config or {},
        directory_structure={"a.md": {"type": "text/markdown", "size_bytes": 1}},
    )
    return str(src["id"])


def _patch_storage(monkeypatch, stored_files):
    """Storage whose directory holds ``stored_files`` (rel paths)."""
    from application import worker

    base = "inputs/alice/doc-set"
    storage = MagicMock(name="storage")
    storage.is_directory.side_effect = lambda p: p == base
    storage.list_files.return_value = [f"{base}/{f}" for f in stored_files]
    storage.get_file.return_value = MagicMock(read=lambda: b"x")
    monkeypatch.setattr(worker.StorageCreator, "get_storage", lambda: storage)
    return storage


def _patch_reader(monkeypatch, docs):
    from application import worker

    reader = MagicMock(name="reader")
    reader.load_data.return_value = docs
    monkeypatch.setattr(worker, "SimpleDirectoryReader", lambda *a, **kw: reader)
    return reader


@pytest.mark.unit
class TestConvertSourceToWikiWorker:
    def test_one_page_per_text_file(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_storage(monkeypatch, ["guide.md", "notes/intro.md", "logo.png"])
        _patch_reader(
            monkeypatch,
            [
                Document(text="guide body", extra_info={"source": "guide.md"}),
                Document(
                    text="intro body", extra_info={"source": "notes/intro.md"}
                ),
            ],
        )
        delay = MagicMock(name="reembed_delay")
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", delay
        )

        result = worker.convert_source_to_wiki_worker(
            task_self, source_id, "alice"
        )

        assert result["status"] == "converted"
        assert result["pages_created"] == 2

        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        by_path = {p["path"]: p for p in pages}
        assert set(by_path) == {"/guide.md", "/notes/intro.md"}
        assert by_path["/guide.md"]["content"] == "guide body"
        assert by_path["/guide.md"]["title"] == "guide.md"
        assert by_path["/notes/intro.md"]["title"] == "intro.md"

    def test_binaries_skipped_and_reported(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_storage(monkeypatch, ["guide.md", "logo.png", "scan.pdf"])
        _patch_reader(
            monkeypatch,
            [Document(text="guide body", extra_info={"source": "guide.md"})],
        )
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", MagicMock()
        )

        result = worker.convert_source_to_wiki_worker(
            task_self, source_id, "alice"
        )

        assert result["pages_created"] == 1
        skipped_files = {s["file"] for s in result["skipped"]}
        assert skipped_files == {"logo.png", "scan.pdf"}
        for entry in result["skipped"]:
            assert entry["reason"]

    def test_reembed_enqueued_per_page_with_per_page_key(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_storage(monkeypatch, ["a.md", "b.md"])
        _patch_reader(
            monkeypatch,
            [
                Document(text="aaa", extra_info={"source": "a.md"}),
                Document(text="bbb", extra_info={"source": "b.md"}),
            ],
        )
        delay = MagicMock(name="reembed_delay")
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", delay
        )

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert delay.call_count == 2
        keys = {c.kwargs["idempotency_key"] for c in delay.call_args_list}
        paths = {c.args[1] for c in delay.call_args_list}
        assert paths == {"/a.md", "/b.md"}
        for call in delay.call_args_list:
            assert call.args[0] == source_id
            assert call.kwargs["user"] == "alice"
            assert call.kwargs["idempotency_key"].startswith(
                f"reembed-wiki:{source_id}:"
            )
        assert len(keys) == 2

    def test_sets_kind_wiki_and_agentic_exposure(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.source_config import SourceConfig

        source_id = _seed_source(pg_conn)
        _patch_storage(monkeypatch, ["a.md"])
        _patch_reader(
            monkeypatch,
            [Document(text="aaa", extra_info={"source": "a.md"})],
        )
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", MagicMock()
        )

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        refreshed = SourcesRepository(pg_conn).get_any(source_id, "alice")
        cfg = SourceConfig.parse(refreshed.get("config"))
        assert cfg.kind == "wiki"
        assert cfg.retrieval.exposure == "agentic_tool"

    def test_preserves_non_default_exposure(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.source_config import SourceConfig

        source_id = _seed_source(
            pg_conn, config={"retrieval": {"exposure": "agentic_tool"}}
        )
        _patch_storage(monkeypatch, ["a.md"])
        _patch_reader(
            monkeypatch,
            [Document(text="aaa", extra_info={"source": "a.md"})],
        )
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", MagicMock()
        )

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        refreshed = SourcesRepository(pg_conn).get_any(source_id, "alice")
        cfg = SourceConfig.parse(refreshed.get("config"))
        assert cfg.kind == "wiki"
        assert cfg.retrieval.exposure == "agentic_tool"

    def test_no_pages_leaves_kind_and_structure(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.source_config import SourceConfig

        original_structure = {"a.md": {"type": "text/markdown", "size_bytes": 1}}
        source_id = _seed_source(pg_conn)
        _patch_storage(monkeypatch, ["logo.png", "scan.pdf"])
        _patch_reader(monkeypatch, [])
        rebuild = MagicMock(name="rebuild")
        monkeypatch.setattr(
            worker, "rebuild_wiki_directory_structure", rebuild
        )
        delay = MagicMock(name="reembed_delay")
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", delay
        )

        result = worker.convert_source_to_wiki_worker(
            task_self, source_id, "alice"
        )

        assert result["status"] == "no_pages"
        assert result["pages_created"] == 0
        assert result["skipped"]
        rebuild.assert_not_called()
        delay.assert_not_called()

        refreshed = SourcesRepository(pg_conn).get_any(source_id, "alice")
        assert SourceConfig.parse(refreshed.get("config")).kind != "wiki"
        assert refreshed.get("directory_structure") == original_structure

    def test_traversal_filename_skipped(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_storage(monkeypatch, ["ok.md", "../evil.md"])
        _patch_reader(
            monkeypatch,
            [
                Document(text="good", extra_info={"source": "ok.md"}),
                Document(text="bad", extra_info={"source": "../evil.md"}),
            ],
        )
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", MagicMock()
        )

        result = worker.convert_source_to_wiki_worker(
            task_self, source_id, "alice"
        )

        assert result["pages_created"] == 1
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/ok.md"}
        skipped = {(s["file"], s["reason"]) for s in result["skipped"]}
        assert ("../evil.md", "invalid path") in skipped

    def test_parse_failure_reason_distinct_from_binary(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        # broken.md has a supported extension but produced no doc (parse/read
        # failure); blob.bin is an unsupported/binary file.
        _patch_storage(monkeypatch, ["guide.md", "broken.md", "blob.bin"])
        _patch_reader(
            monkeypatch,
            [Document(text="guide body", extra_info={"source": "guide.md"})],
        )
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", MagicMock()
        )

        result = worker.convert_source_to_wiki_worker(
            task_self, source_id, "alice"
        )

        reasons = {s["file"]: s["reason"] for s in result["skipped"]}
        assert reasons["broken.md"] == "could not read/parse"
        assert reasons["blob.bin"] == "no extractable text"

    def test_already_wiki_returns_early(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn, config={"kind": "wiki"})
        reader = MagicMock(name="reader")
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader", lambda *a, **kw: reader
        )
        delay = MagicMock(name="reembed_delay")
        monkeypatch.setattr(
            "application.api.user.tasks.reembed_wiki_page.delay", delay
        )

        result = worker.convert_source_to_wiki_worker(
            task_self, source_id, "alice"
        )

        assert result["status"] == "already_wiki"
        reader.load_data.assert_not_called()
        delay.assert_not_called()
