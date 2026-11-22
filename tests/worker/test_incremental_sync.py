"""Connector and remote syncs change only what changed: added, changed, moved and removed files.

The loader, the vector store and the internal upload API are in-memory stand-ins;
the reader, the chunker and the ``sources`` row are real.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from docsgpt import worker
from docsgpt.parser import incremental
from docsgpt.parser.connectors.base import BaseConnectorLoader, FileEntry, SelectionListing
from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError, TransientParseError
from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.vectorstore.base import BaseVectorStore


# ---------------------------------------------------------------------------
# Stand-ins
# ---------------------------------------------------------------------------


class MemoryStore(BaseVectorStore):
    """A vector store held in a dict; counts what it embeds and how often it writes."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: Dict[str, Dict[str, Any]] = {}
        self.embedded: List[str] = []
        self.next_id = 0
        self.fail_adds = False
        self.listing_broken = False
        self.delete_calls = 0

    def search(self, *args, **kwargs):
        return []

    def _put(self, text: str, metadata: Optional[dict]) -> str:
        self.next_id += 1
        cid = str(self.next_id)
        self.chunks[cid] = {"doc_id": cid, "text": text, "metadata": dict(metadata or {})}
        self.embedded.append(text)
        return cid

    def add_texts(self, texts, metadatas=None, *args, **kwargs):
        metadatas = metadatas or [{} for _ in texts]
        return [self._put(t, m) for t, m in zip(texts, metadatas)]

    def add_chunk(self, text, metadata=None, *args, **kwargs):
        return self._put(text, metadata)

    def add_chunks(self, texts, metadatas=None):
        if self.fail_adds == "after_write":
            # The chunks land, then the store answers with an error.
            self.add_texts(texts, metadatas)
            raise RuntimeError("connection reset after the write")
        if self.fail_adds:
            raise RuntimeError("embedding service down")
        return self.add_texts(texts, metadatas)

    def get_chunks(self, *args, **kwargs):
        # Like pgvector, Qdrant, Milvus and MongoDB: a failed query reads as no chunks.
        if self.listing_broken:
            return []
        return [dict(c, metadata=dict(c["metadata"])) for c in self.chunks.values()]

    def _scan_chunks(self):
        if self.listing_broken:
            raise RuntimeError("statement timeout")
        return self.get_chunks()

    def delete_chunk(self, chunk_id, *args, **kwargs):
        return self.chunks.pop(str(chunk_id), None) is not None

    def delete_chunks(self, chunk_ids):
        self.delete_calls += 1
        return sum(1 for cid in chunk_ids if self.chunks.pop(str(cid), None) is not None)

    def delete_index(self, *args, **kwargs):
        self.chunks.clear()

    def update_chunks_metadata(self, updates):
        count = 0
        for cid, meta in updates.items():
            if cid in self.chunks:
                self.chunks[cid]["metadata"] = dict(meta)
                count += 1
        return count

    def by_source(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for cid, chunk in self.chunks.items():
            out.setdefault(chunk["metadata"].get("file_path") or chunk["metadata"].get("source"), []).append(cid)
        return out


class FakeDriveLoader(BaseConnectorLoader):
    """A connector whose files live in a dict; records every download."""

    def __init__(self, files: Dict[str, Dict[str, Any]]):
        self.connection_id = None
        self.files = files
        self.full_downloads = 0
        self.single_downloads: List[List[str]] = []
        self.download_failures: Dict[str, str] = {}
        self.listed = True

    def load_data(self, inputs):
        return []

    def list_selection(self, source_config):
        hidden = getattr(self, "hidden", set())
        return SelectionListing(
            entries=[
                FileEntry(id=fid, path=f["path"], version=f["version"], url=f"https://drive/{fid}")
                for fid, f in self.files.items()
                if fid not in hidden
            ],
            complete=not hidden,
            unread=len(hidden),
        )

    def sync_fingerprint(self, source_config):
        payload = sorted((f["path"], fid, f["version"]) for fid, f in self.files.items())
        return json.dumps(payload)

    def _write(self, local_dir: str, fid: str) -> None:
        target = Path(local_dir, self.files[fid]["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.files[fid]["text"])

    def download_to_directory(self, local_dir, source_config=None):
        self.full_downloads += 1
        failures = {}
        for fid in self.files:
            if fid in self.download_failures:
                failures[fid] = {"kind": self.download_failures[fid], "error": "refused"}
                continue
            self._write(local_dir, fid)
        downloaded = len(self.files) - len(failures)
        return {
            "files_downloaded": downloaded,
            "files_failed": len(failures),
            "empty_result": downloaded == 0,
            "sync_fingerprint": self.sync_fingerprint(source_config),
            "file_urls": {f["path"]: f"https://drive/{fid}" for fid, f in self.files.items()},
            "failures": failures,
        }

    def download_files(self, local_dir, file_ids):
        file_ids = list(file_ids)
        self.single_downloads.append(sorted(file_ids))
        failures = {}
        paths = {}
        for fid in file_ids:
            if fid in self.download_failures:
                failures[fid] = {"kind": self.download_failures[fid], "error": "refused"}
                continue
            self._write(local_dir, fid)
            paths[self.files[fid]["path"]] = fid
        return {
            "files_downloaded": len(paths),
            "files_failed": len(failures),
            "file_ids": paths,
            "file_urls": {p: f"https://drive/{fid}" for p, fid in paths.items()},
            "failures": failures,
        }


class FlakyParser(BaseParser):
    """Reads text files, failing the names in ``broken`` (``name -> "transient" | "permanent"``)."""

    def __init__(self) -> None:
        super().__init__()
        self.broken: Dict[str, str] = {}
        self.partial: set = set()
        self.parsed: List[str] = []

    def get_file_metadata(self, file):
        return {"ocr_pages_failed": 1} if Path(file).name in self.partial else {}

    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        name = Path(file).name
        self.parsed.append(name)
        if name in self.broken:
            error = TransientParseError if self.broken[name] == "transient" else DocumentParseError
            raise error(f"cannot read {name}")
        return Path(file).read_text()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _files(n: int = 5) -> Dict[str, Dict[str, Any]]:
    return {
        f"id{i}": {"path": os.path.join("Docs", f"doc{i}.md"), "version": "v1", "text": f"# Doc {i}\n\nbody {i} " * 20}
        for i in range(n)
    }


@pytest.fixture
def harness(pg_conn, patch_worker_db, task_self, published, monkeypatch):
    """A Drive-like source of five files, synced through the real worker with in-memory stand-ins."""
    store = MemoryStore()
    loader = FakeDriveLoader(_files())
    parser = FlakyParser()
    monkeypatch.setattr(incremental, "_sleep", lambda seconds: None)
    monkeypatch.setattr(worker.ConnectorCreator, "is_supported", staticmethod(lambda s: True))
    monkeypatch.setattr(
        worker.ConnectorCreator, "create_connector",
        staticmethod(lambda source_type, session_token=None, connection_id=None: loader),
    )
    monkeypatch.setattr(
        "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
    )
    monkeypatch.setattr(
        worker, "SimpleDirectoryReader",
        functools.partial(worker.SimpleDirectoryReader, file_extractor={".md": parser}),
    )

    def _embed(docs, folder, source_id, task, **kwargs):
        store.delete_index()
        store.add_texts([d.page_content for d in docs], [dict(d.metadata) for d in docs])

    monkeypatch.setattr(worker, "embed_and_store_documents", _embed)
    monkeypatch.setattr(worker, "assert_index_complete", lambda source_id: None)

    def _upload(full_path, file_data):
        # What the internal API stores for a sync (see docsgpt/api/internal/routes.py).
        repo = SourcesRepository(pg_conn)
        row = repo.get_for_update(file_data["id"])
        remote = dict(row.get("remote_data") or {})
        remote.pop("sync_fingerprint", None)
        if file_data.get("sync_fingerprint"):
            remote["sync_fingerprint"] = file_data["sync_fingerprint"]
        repo.update(file_data["id"], row["user_id"], {
            "directory_structure": json.loads(file_data["directory_structure"]),
            "tokens": file_data["tokens"],
            "remote_data": remote,
        })
        return {"status": "ok"}

    monkeypatch.setattr(worker, "upload_index", _upload)
    src = SourcesRepository(pg_conn).create(
        "drive", user_id="dave", type="connector:file", retriever="classic", sync_frequency="daily",
        remote_data={"provider": "google_drive", "folder_ids": ["root"], "file_ids": [], "recursive": True},
    )

    class H:
        pass

    h = H()
    h.store, h.loader, h.parser, h.events, h.pg = store, loader, parser, published, pg_conn
    h.source_id = str(src["id"])

    def sync(config=None, retry_failed=False):
        return worker.ingest_connector(
            task_self, "drive", "dave", "google_drive", session_token="tok", folder_ids=["root"],
            operation_mode="sync", doc_id=h.source_id, sync_frequency="daily", config=config,
            retry_failed=retry_failed,
        )

    def row():
        repo = SourcesRepository(pg_conn)
        return {**repo.get(h.source_id, "dave"), "remote_files": repo.get_remote_files(h.source_id)}

    def reset():
        loader.full_downloads = 0
        loader.single_downloads.clear()
        store.embedded.clear()
        parser.parsed.clear()

    h.sync, h.row, h.reset = sync, row, reset
    return h


def _set_config(h, config):
    SourcesRepository(h.pg).update(h.source_id, "dave", {"config": config})


# ---------------------------------------------------------------------------
# Part 3: only what changed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectorIncrementalSync:

    def test_a_source_without_a_manifest_syncs_in_full_once_and_stores_one(self, harness):
        harness.sync()
        assert harness.loader.full_downloads == 1
        manifest = harness.row()["remote_files"]
        assert manifest["kind"] == "connector"
        assert set(manifest["files"]) == {f"id{i}" for i in range(5)}

        harness.reset()
        result = harness.sync()

        assert result["status"] == "unchanged"
        assert harness.loader.full_downloads == 0 and harness.loader.single_downloads == []
        assert harness.store.embedded == []
        assert harness.events[-1][1]["no_changes"] is True

    def test_one_changed_file_downloads_and_replaces_only_its_chunks(self, harness):
        harness.sync()
        before = harness.store.by_source()
        changed = os.path.join("Docs", "doc2.md")
        harness.loader.files["id2"].update(version="v2", text="# Doc 2\n\nrewritten " * 20)
        harness.reset()

        result = harness.sync()

        assert result["incremental"] is True and result["files_changed"] == 1
        assert harness.loader.full_downloads == 0
        assert harness.loader.single_downloads == [["id2"]]
        assert harness.parser.parsed == ["doc2.md"]
        after = harness.store.by_source()
        for path, ids in before.items():
            if path != changed:
                assert after[path] == ids
        assert not set(after[changed]) & set(before[changed])
        assert all("rewritten" in harness.store.chunks[cid]["text"] for cid in after[changed])
        assert harness.row()["remote_files"]["files"]["id2"]["version"] == "v2"

    def test_added_removed_and_renamed_files(self, harness):
        harness.sync()
        before = harness.store.by_source()
        loader = harness.loader
        loader.files["new"] = {"path": os.path.join("Docs", "new.md"), "version": "v1", "text": "# New\n\nfresh " * 20}
        del loader.files["id0"]
        loader.files["id1"]["path"] = os.path.join("Docs", "Renamed", "one.md")
        harness.reset()

        result = harness.sync()

        assert (result["files_added"], result["files_removed"], result["files_moved"]) == (1, 1, 1)
        assert loader.single_downloads == [["new"]]
        after = harness.store.by_source()
        assert os.path.join("Docs", "doc0.md") not in after
        assert os.path.join("Docs", "new.md") in after
        renamed = os.path.join("Docs", "Renamed", "one.md")
        # The renamed file keeps its chunks: same ids, new path and title, nothing embedded for it.
        assert after[renamed] == before[os.path.join("Docs", "doc1.md")]
        meta = harness.store.chunks[after[renamed][0]]["metadata"]
        assert meta["source"] == renamed and meta["title"] == "one.md" and meta["url"] == "https://drive/id1"
        assert all("fresh" in text for text in harness.store.embedded)
        structure = incremental.structure_files(harness.row()["directory_structure"])
        assert renamed in structure and os.path.join("Docs", "doc0.md") not in structure

    def test_a_settings_change_syncs_in_full_once_then_incrementally_again(self, harness):
        harness.sync()
        _set_config(harness, {"chunking": {"strategy": "classic_chunk", "max_tokens": 600, "min_tokens": 50}})
        harness.reset()

        harness.sync(config={"chunking": {"strategy": "classic_chunk", "max_tokens": 600, "min_tokens": 50}})
        assert harness.loader.full_downloads == 1

        harness.reset()
        harness.loader.files["id3"]["version"] = "v2"
        harness.sync(config={"chunking": {"strategy": "classic_chunk", "max_tokens": 600, "min_tokens": 50}})
        assert harness.loader.full_downloads == 0
        assert harness.loader.single_downloads == [["id3"]]

    def test_a_loader_that_cannot_list_keeps_the_full_sync(self, harness, monkeypatch):
        plain = MagicMock(name="connector")
        plain.connection_id = None
        plain.download_to_directory.side_effect = harness.loader.download_to_directory
        plain.sync_fingerprint.return_value = None
        monkeypatch.setattr(
            worker.ConnectorCreator, "create_connector",
            staticmethod(lambda source_type, session_token=None, connection_id=None: plain),
        )
        harness.sync()
        harness.sync()
        assert plain.download_to_directory.call_count == 2
        assert harness.row()["remote_files"] is None

    def test_an_old_fingerprinted_source_records_a_manifest_without_rebuilding(self, harness):
        harness.sync()
        repo = SourcesRepository(harness.pg)
        repo.update(harness.source_id, "dave", {"remote_files": None})
        harness.reset()

        result = harness.sync()

        assert result["status"] == "unchanged"
        assert harness.loader.full_downloads == 0 and harness.store.embedded == []
        assert set(harness.row()["remote_files"]["files"]) == {f"id{i}" for i in range(5)}

    def test_a_sync_that_dies_part_way_is_redone_by_the_next(self, harness):
        harness.sync()
        harness.loader.files["id4"].update(version="v2", text="# Doc 4\n\nnew words " * 20)
        harness.store.fail_adds = True
        with pytest.raises(RuntimeError):
            harness.sync()
        # The changed file is pending: no version, so the next sync redoes it.
        assert harness.row()["remote_files"]["files"]["id4"]["version"] is None

        harness.store.fail_adds = False
        harness.reset()
        harness.sync()

        assert harness.loader.single_downloads == [["id4"]]
        path = os.path.join("Docs", "doc4.md")
        assert all("new words" in harness.store.chunks[cid]["text"] for cid in harness.store.by_source()[path])
        assert harness.row()["remote_files"]["files"]["id4"]["version"] == "v2"


# ---------------------------------------------------------------------------
# Part 1: failed files keep the fingerprint and are retried alone
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectorFailedFiles:

    def test_an_unparsed_file_keeps_the_fingerprint_and_is_recorded(self, harness):
        harness.parser.broken["doc3.md"] = "transient"

        result = harness.sync()

        row = harness.row()
        assert row["remote_data"]["sync_fingerprint"]
        [failed] = row["remote_data"]["failed_files"]
        assert (failed["id"], failed["kind"], failed["attempts"]) == ("id3", "transient", 1)
        assert failed["path"] == os.path.join("Docs", "doc3.md")
        assert "id3" not in row["remote_files"]["files"]
        assert result["files_failed"] == 1
        assert harness.events[-1][1]["files_failed"] == 1

    def test_the_next_sync_retries_only_the_failed_file(self, harness):
        harness.parser.broken["doc3.md"] = "transient"
        harness.sync()
        before = harness.store.by_source()
        harness.parser.broken.clear()
        harness.reset()

        harness.sync()

        assert harness.loader.full_downloads == 0
        assert harness.loader.single_downloads == [["id3"]]
        after = harness.store.by_source()
        assert os.path.join("Docs", "doc3.md") in after
        for path, ids in before.items():
            assert after[path] == ids
        assert "failed_files" not in harness.row()["remote_data"]

        harness.reset()
        harness.sync()
        assert harness.store.by_source() == after
        assert harness.loader.single_downloads == []

    def test_a_download_failure_is_retried_alone(self, harness):
        harness.loader.download_failures["id1"] = "transient"
        harness.sync()
        assert [f["id"] for f in harness.row()["remote_data"]["failed_files"]] == ["id1"]
        harness.loader.download_failures.clear()
        harness.reset()

        harness.sync()

        assert harness.loader.single_downloads == [["id1"]]
        assert "failed_files" not in harness.row()["remote_data"]

    def test_a_transient_failure_stops_after_three_attempts(self, harness):
        harness.parser.broken["doc2.md"] = "transient"
        harness.sync()
        for _ in range(4):
            harness.reset()
            harness.sync()
        [failed] = harness.row()["remote_data"]["failed_files"]
        assert failed["attempts"] == incremental.MAX_TRANSIENT_ATTEMPTS
        assert harness.loader.single_downloads == []

        # A new version is tried again, from its first attempt.
        harness.loader.files["id2"]["version"] = "v2"
        harness.reset()
        harness.sync()
        assert harness.loader.single_downloads == [["id2"]]
        [failed] = harness.row()["remote_data"]["failed_files"]
        assert failed["attempts"] == 1 and failed["version"] == "v2"

    def test_a_permanent_failure_waits_for_the_file_to_change(self, harness):
        harness.parser.broken["doc2.md"] = "permanent"
        harness.sync()
        harness.reset()
        harness.sync()
        assert harness.loader.single_downloads == []

        harness.parser.broken.clear()
        harness.loader.files["id2"]["version"] = "v2"
        harness.reset()
        harness.sync()
        assert harness.loader.single_downloads == [["id2"]]
        assert "failed_files" not in harness.row()["remote_data"]

    def test_a_changed_file_that_fails_keeps_its_old_chunks(self, harness):
        harness.sync()
        path = os.path.join("Docs", "doc1.md")
        old = harness.store.by_source()[path]
        harness.loader.files["id1"].update(version="v2", text="broken now")
        harness.parser.broken["doc1.md"] = "transient"

        harness.sync()

        assert harness.store.by_source()[path] == old
        assert harness.row()["remote_files"]["files"]["id1"]["version"] == "v1"
        assert [f["id"] for f in harness.row()["remote_data"]["failed_files"]] == ["id1"]


# ---------------------------------------------------------------------------
# What the review found
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIncrementalSafety:

    def test_a_store_that_cannot_edit_chunks_syncs_in_full(self, harness, monkeypatch):
        harness.sync()
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.supports_chunk_edits", lambda type_: False,
        )
        harness.reset()
        # Nothing changed: kept as it is, whatever the store.
        assert harness.sync()["status"] == "unchanged"
        assert harness.loader.full_downloads == 0

        harness.loader.files["id2"]["version"] = "v2"
        harness.sync()
        harness.sync()

        # The change rebuilds the index once; the sync after it finds nothing to do.
        assert harness.loader.full_downloads == 1
        assert harness.loader.single_downloads == []

    def test_a_failed_chunk_listing_changes_nothing_and_the_next_sync_redoes_it(self, harness):
        harness.sync()
        path = os.path.join("Docs", "doc2.md")
        old = harness.store.by_source()[path]
        harness.loader.files["id2"].update(version="v2", text="# Doc 2\n\nrewritten " * 20)
        harness.store.listing_broken = True

        with pytest.raises(RuntimeError):
            harness.sync()
        harness.store.listing_broken = False
        assert harness.store.by_source()[path] == old
        assert harness.row()["remote_files"]["files"]["id2"]["version"] is None

        harness.sync()
        texts = [harness.store.chunks[c]["text"] for c in harness.store.by_source()[path]]
        assert texts and all("rewritten" in t for t in texts)

    def test_files_trading_paths_never_lose_an_unchanged_files_chunks(self, harness):
        loader = harness.loader
        loader.files.clear()
        loader.files["A"] = {"path": "a.md", "version": "v1", "text": "# A\n\nalpha " * 20}
        loader.files["B"] = {"path": "b.md", "version": "v1", "text": "# B\n\nbravo " * 20}
        harness.sync()
        # A is edited and the two swap names; A's download fails.
        loader.files["A"].update(version="v2", path="b.md", text="# A\n\nalpha2 " * 20)
        loader.files["B"].update(path="a.md")
        loader.download_failures["A"] = "transient"

        result = harness.sync()
        by_path = harness.store.by_source()
        # B waits for A's path: both keep their old chunks until A can be read.
        assert all("alpha" in harness.store.chunks[c]["text"] for c in by_path["a.md"])
        assert all("bravo" in harness.store.chunks[c]["text"] for c in by_path["b.md"])
        assert result["files_deferred"] == 1
        assert harness.row()["remote_files"]["files"]["A"]["path"] == "a.md"

        loader.download_failures.clear()
        harness.sync()
        by_path = harness.store.by_source()
        assert all("bravo" in harness.store.chunks[c]["text"] for c in by_path["a.md"])
        assert all("alpha2" in harness.store.chunks[c]["text"] for c in by_path["b.md"])

    def test_another_embedding_model_rebuilds_the_index(self, harness, monkeypatch):
        harness.sync()
        SourcesRepository(harness.pg).update(harness.source_id, "dave", {"model": "old-model"})
        monkeypatch.setattr(worker.settings, "EMBEDDINGS_NAME", "new-model")
        harness.reset()

        harness.sync()

        assert harness.loader.full_downloads == 1

    def test_a_permanent_failure_is_tried_again_once_the_parse_settings_change(self, harness, monkeypatch):
        harness.parser.broken["doc3.md"] = "permanent"
        harness.sync()
        harness.parser.broken.clear()
        harness.reset()
        harness.sync()
        assert harness.loader.single_downloads == []

        monkeypatch.setattr(worker, "_parse_settings_key", lambda: "ocr-now-configured")
        harness.sync()
        assert harness.loader.single_downloads == [["id3"]]
        assert os.path.join("Docs", "doc3.md") in harness.store.by_source()

    def test_a_sync_someone_asked_for_retries_every_failed_file(self, harness):
        harness.parser.broken["doc3.md"] = "permanent"
        harness.sync()
        harness.parser.broken.clear()
        harness.reset()

        harness.sync(retry_failed=True)

        assert harness.loader.single_downloads == [["id3"]]
        assert "failed_files" not in harness.row()["remote_data"]

    def test_a_pending_files_other_path_is_not_handed_to_another_file(self, harness):
        harness.sync()
        repo = SourcesRepository(harness.pg)
        manifest = repo.get_remote_files(harness.source_id)
        q = os.path.join("Docs", "q.md")
        # id0 died part way through a move to q; id1 is moving there now, and id0 fails.
        manifest["files"]["id0"] = {**manifest["files"]["id0"], "version": None,
                                    "pending_paths": [os.path.join("Docs", "doc0.md"), q]}
        repo.update(harness.source_id, "dave", {"remote_files": manifest})
        harness.loader.files["id1"]["path"] = q
        harness.loader.download_failures["id0"] = "transient"
        harness.sync()
        harness.loader.download_failures.clear()
        harness.sync()
        texts = [harness.store.chunks[c]["text"] for c in harness.store.by_source()[q]]
        assert texts and all("body 1" in t for t in texts)

    def test_deletes_go_to_the_store_in_one_call(self, harness):
        harness.sync()
        for fid in ("id0", "id1", "id2"):
            harness.loader.files[fid]["version"] = "v2"
        harness.store.delete_calls = 0

        harness.sync()

        assert harness.store.delete_calls == 1


@pytest.mark.unit
class TestCodeRabbitFixes:

    def test_chunks_written_before_the_final_save_failed_go_once_the_file_does(self, harness, monkeypatch):
        harness.sync()
        harness.loader.files["tmp"] = {"path": "Docs/tmp.md", "version": "v1", "text": "# Tmp\n\ntemporary " * 20}
        real = worker._save_source_sync_state
        calls = []

        def save(source_id, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:  # the final save, after the chunks are in
                raise RuntimeError("database gone")
            return real(source_id, **kwargs)

        monkeypatch.setattr(worker, "_save_source_sync_state", save)
        with pytest.raises(RuntimeError):
            harness.sync()
        monkeypatch.setattr(worker, "_save_source_sync_state", real)
        assert "Docs/tmp.md" in harness.store.by_source()
        del harness.loader.files["tmp"]

        harness.sync()

        assert "Docs/tmp.md" not in harness.store.by_source()

    def test_a_file_added_by_a_sync_that_died_is_removed_once_gone(self, harness):
        harness.sync()
        harness.loader.files["tmp"] = {"path": "Docs/tmp.md", "version": "v1", "text": "# Tmp\n\ntemporary " * 20}
        harness.store.fail_adds = "after_write"
        with pytest.raises(RuntimeError):
            harness.sync()
        harness.store.fail_adds = False
        assert "Docs/tmp.md" in harness.store.by_source()
        del harness.loader.files["tmp"]

        harness.sync()

        assert "Docs/tmp.md" not in harness.store.by_source()
        assert "tmp" not in harness.row()["remote_files"]["files"]

    def test_a_move_cut_short_leaves_nothing_behind_when_the_file_goes(self, harness):
        harness.sync()
        harness.loader.files["id1"]["path"] = "Docs/Moved/one.md"
        harness.loader.files["new"] = {"path": "Docs/new.md", "version": "v1", "text": "# N\n\nnew " * 20}
        harness.store.fail_adds = True  # dies after the move's rewrite, adding the new file
        with pytest.raises(RuntimeError):
            harness.sync()
        harness.store.fail_adds = False
        del harness.loader.files["id1"]

        harness.sync()

        paths = harness.store.by_source()
        assert "Docs/Moved/one.md" not in paths and os.path.join("Docs", "doc1.md") not in paths

    def test_an_incomplete_listing_is_not_reported_as_unchanged(self, harness):
        harness.sync()
        harness.loader.hidden = {"id4"}

        result = harness.sync()

        assert result["status"] == "partial"
        payload = harness.events[-1][1]
        assert "no_changes" not in payload and payload["partial"] is True and payload["folders_failed"] == 1
        # Nothing it couldn't see was removed.
        assert os.path.join("Docs", "doc4.md") in harness.store.by_source()

    def test_a_listing_that_read_nothing_fails_the_sync(self, harness):
        harness.sync()
        harness.loader.hidden = set(harness.loader.files)
        with pytest.raises(worker.ConnectorDownloadError):
            harness.sync()
        assert len(harness.store.by_source()) == 5

    def test_failed_files_past_the_display_cap_keep_their_state(self, harness, monkeypatch):
        monkeypatch.setattr(incremental, "MAX_FAILED_FILES", 1)
        harness.parser.broken.update({"doc1.md": "permanent", "doc2.md": "permanent"})
        harness.sync()
        row = harness.row()
        assert len(row["remote_data"]["failed_files"]) == 1 and row["remote_data"]["files_failed"] == 2
        harness.parser.broken.clear()
        harness.reset()

        harness.sync()

        assert harness.loader.single_downloads == []

    def test_a_full_rebuild_drops_the_fingerprint_until_it_is_stored(self, harness, monkeypatch):
        harness.sync()
        seen = {}

        def _embed(docs, folder, source_id, task, **kwargs):
            seen["remote_data"] = SourcesRepository(harness.pg).get(harness.source_id, "dave")["remote_data"]
            raise RuntimeError("embedding down")

        monkeypatch.setattr(worker, "embed_and_store_documents", _embed)
        _set_config(harness, {"chunking": {"strategy": "classic_chunk", "max_tokens": 600, "min_tokens": 50}})
        with pytest.raises(RuntimeError):
            harness.sync(config={"chunking": {"strategy": "classic_chunk", "max_tokens": 600, "min_tokens": 50}})
        assert "sync_fingerprint" not in seen["remote_data"]

    def test_a_partly_ocrd_file_is_indexed_and_read_again(self, harness):
        harness.parser.partial.add("doc3.md")
        harness.sync()
        path = os.path.join("Docs", "doc3.md")
        assert path in harness.store.by_source()
        [failed] = harness.row()["remote_data"]["failed_files"]
        assert (failed["id"], failed["kind"]) == ("id3", "transient")
        harness.parser.partial.clear()
        harness.reset()

        harness.sync()

        assert harness.loader.single_downloads == [["id3"]]
        assert "failed_files" not in harness.row()["remote_data"]
        assert len(harness.store.by_source()[path]) >= 1

    def test_a_full_ingest_keeps_files_an_incomplete_listing_missed(self, harness):
        harness.loader.hidden = {"id3"}

        result = harness.sync()

        assert os.path.join("Docs", "doc3.md") in harness.store.by_source()
        assert result["partial"] is True and harness.events[-1][1]["partial"] is True
        # No manifest from an incomplete listing: the next sync is a full one.
        assert harness.row()["remote_files"] is None

    def test_a_full_ingest_indexes_only_what_the_listing_names(self, harness, monkeypatch):
        original = harness.loader.download_to_directory

        def download(local_dir, source_config=None):
            result = original(local_dir, source_config)
            Path(local_dir, "stray.md").write_text("# Stray\n\n" + "a second copy " * 20)
            return result

        monkeypatch.setattr(harness.loader, "download_to_directory", download)
        harness.sync()
        assert "stray.md" not in harness.store.by_source()


@pytest.mark.unit
class TestSecondReview:

    def test_a_file_the_reader_passes_over_is_recorded_not_indexed(self, harness):
        harness.loader.files["hid"] = {"path": "Docs/.hidden.md", "version": "v1", "text": "# H\n\nhidden " * 20}
        harness.sync()
        row = harness.row()
        assert "hid" not in row["remote_files"]["files"]
        assert [f["id"] for f in row["remote_data"]["failed_files"]] == ["hid"]

        harness.loader.files["hid2"] = {"path": "Docs/.other.md", "version": "v1", "text": "# O\n\nother " * 20}
        harness.sync()
        assert "hid2" not in harness.row()["remote_files"]["files"]

    def test_a_path_an_unseen_indexed_file_holds_is_left_alone(self, harness):
        harness.sync()
        # id4 can't be seen, and a new file wants its path.
        harness.loader.hidden = {"id4"}
        harness.loader.files["new"] = {"path": os.path.join("Docs", "doc4.md"), "version": "v1",
                                       "text": "# New\n\nnewcomer " * 20}
        before = harness.store.by_source()[os.path.join("Docs", "doc4.md")]

        harness.sync()

        assert harness.store.by_source()[os.path.join("Docs", "doc4.md")] == before
        assert "new" not in harness.row()["remote_files"]["files"]

    def test_the_fingerprint_is_written_with_the_manifest(self, harness, monkeypatch):
        uploads = []
        real = worker.upload_index
        monkeypatch.setattr(worker, "upload_index", lambda path, data: (uploads.append(data), real(path, data))[1])
        harness.sync()
        assert uploads[0]["sync_fingerprint"] == ""
        assert "sync_fingerprint" not in json.loads(uploads[0]["remote_data"])
        row = harness.row()
        assert row["remote_data"]["sync_fingerprint"] and row["remote_files"]["files"]

    def test_a_store_that_adds_fewer_chunks_than_asked_fails_the_sync(self, harness, monkeypatch):
        harness.sync()
        harness.loader.files["id1"]["version"] = "v2"
        monkeypatch.setattr(harness.store, "add_chunks", lambda texts, metadatas=None: [])
        with pytest.raises(RuntimeError, match="added 0 of"):
            harness.sync()
        assert harness.row()["remote_files"]["files"]["id1"]["version"] is None


# ---------------------------------------------------------------------------
# Remote sources (GitHub, crawlers, S3...)
# ---------------------------------------------------------------------------


class FakeRemoteLoader:
    def __init__(self, pages: Dict[str, str]):
        self.pages = pages
        self.report = {}

    def load_data(self, inputs):
        return [
            Document(text=text, extra_info={"file_path": path, "title": path, "source": f"https://x/{path}"})
            for path, text in self.pages.items()
        ]


@pytest.fixture
def remote(pg_conn, patch_worker_db, task_self, published, monkeypatch, tmp_path):
    store = MemoryStore()
    monkeypatch.setattr(incremental, "_sleep", lambda seconds: None)
    loader = FakeRemoteLoader({f"guide/p{i}.md": f"page {i} text " * 30 for i in range(4)})
    monkeypatch.setattr(worker.RemoteCreator, "create_loader", staticmethod(lambda kind: loader))
    monkeypatch.setattr(
        "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
    )
    full_embeds: List[int] = []

    def _embed(docs, folder, source_id, task, **kwargs):
        full_embeds.append(len(docs))
        store.delete_index()
        store.add_texts([d.page_content for d in docs], [dict(d.metadata) for d in docs])

    monkeypatch.setattr(worker, "embed_and_store_documents", _embed)
    monkeypatch.setattr(worker, "assert_index_complete", lambda source_id: None)
    monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: {"status": "ok"})
    src = SourcesRepository(pg_conn).create(
        "crawl", user_id="dave", type="crawler", retriever="classic", sync_frequency="daily",
        remote_data="https://x",
    )
    source_id = str(src["id"])

    def sync(config=None):
        return worker.remote_worker(
            task_self, "https://x", "crawl", "dave", "crawler", directory=str(tmp_path),
            operation_mode="sync", doc_id=source_id, config=config,
        )

    def row():
        repo = SourcesRepository(pg_conn)
        return {**repo.get(source_id, "dave"), "remote_files": repo.get_remote_files(source_id)}

    return MagicMock(
        store=store, loader=loader, sync=sync, full_embeds=full_embeds, events=published, row=row,
    )


@pytest.mark.unit
class TestRemoteIncrementalSync:

    def test_first_sync_rebuilds_and_records_a_manifest(self, remote):
        remote.sync()
        assert remote.full_embeds == [4]
        manifest = remote.row()["remote_files"]
        assert manifest["kind"] == "content" and len(manifest["files"]) == 4

    def test_unchanged_pages_are_not_embedded_again(self, remote):
        remote.sync()
        before = remote.store.by_source()
        remote.store.embedded.clear()

        result = remote.sync()

        assert remote.full_embeds == [4]
        assert remote.store.embedded == []
        assert remote.store.by_source() == before
        assert result["files_changed"] == 0
        assert remote.events[-1][1]["no_changes"] is True

    def test_only_changed_added_and_removed_pages_are_touched(self, remote):
        remote.sync()
        before = remote.store.by_source()
        remote.store.embedded.clear()
        remote.loader.pages["guide/p1.md"] = "rewritten page " * 30
        remote.loader.pages["guide/new.md"] = "brand new page " * 30
        del remote.loader.pages["guide/p3.md"]

        result = remote.sync()

        assert (result["files_changed"], result["files_added"], result["files_removed"]) == (1, 1, 1)
        after = remote.store.by_source()
        assert after["guide/p0.md"] == before["guide/p0.md"]
        assert after["guide/p2.md"] == before["guide/p2.md"]
        assert "guide/p3.md" not in after
        assert all("rewritten" in t or "brand new" in t for t in remote.store.embedded)
        assert remote.full_embeds == [4]

    def test_a_page_written_before_the_final_save_failed_goes_once_gone(self, remote, monkeypatch):
        remote.sync()
        remote.loader.pages["guide/tmp.md"] = "temporary page " * 30
        real = worker._save_source_sync_state
        calls = []

        def save(source_id, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("database gone")
            return real(source_id, **kwargs)

        monkeypatch.setattr(worker, "_save_source_sync_state", save)
        with pytest.raises(RuntimeError):
            remote.sync()
        monkeypatch.setattr(worker, "_save_source_sync_state", real)
        assert "guide/tmp.md" in remote.store.by_source()
        del remote.loader.pages["guide/tmp.md"]

        remote.sync()

        assert "guide/tmp.md" not in remote.store.by_source()

    def test_a_page_added_by_a_sync_that_died_is_removed_once_gone(self, remote):
        remote.sync()
        remote.loader.pages["guide/tmp.md"] = "temporary page " * 30
        remote.store.fail_adds = "after_write"
        with pytest.raises(RuntimeError):
            remote.sync()
        remote.store.fail_adds = False
        assert "guide/tmp.md" in remote.store.by_source()
        del remote.loader.pages["guide/tmp.md"]

        remote.sync()

        assert "guide/tmp.md" not in remote.store.by_source()

    def test_a_settings_change_rebuilds(self, remote):
        remote.sync()
        remote.sync(config={"chunking": {"strategy": "classic_chunk", "max_tokens": 500, "min_tokens": 20}})
        assert len(remote.full_embeds) == 2


# ---------------------------------------------------------------------------
# Upload re-ingest parses only what changed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReingestParsesOnlyChangedFiles:

    def test_unchanged_files_are_neither_parsed_nor_embedded(
        self, pg_conn, patch_worker_db, task_self, published, monkeypatch, tmp_path,
    ):
        from io import BytesIO

        store = MemoryStore()
        parser = FlakyParser()
        files = {"a.md": b"alpha " * 50, "b.md": b"bravo " * 50}
        storage = MagicMock(name="storage")
        storage.is_directory.side_effect = lambda p: p == "inputs/dave/docs"
        storage.list_files.side_effect = lambda p: [f"inputs/dave/docs/{n}" for n in files]
        storage.get_file.side_effect = lambda p: BytesIO(files[os.path.basename(p)])
        monkeypatch.setattr(worker.StorageCreator, "get_storage", lambda: storage)
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
        )
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader",
            functools.partial(worker.SimpleDirectoryReader, file_extractor={".md": parser}),
        )
        import hashlib

        src = SourcesRepository(pg_conn).create(
            "docs", user_id="dave", type="local", retriever="classic", file_path="inputs/dave/docs",
            directory_structure={
                "a.md": {"type": "text/markdown", "size_bytes": 300, "token_count": 51,
                         "sha256": hashlib.sha256(files["a.md"]).hexdigest()},
                "b.md": {"type": "text/markdown", "size_bytes": 300, "token_count": 52, "sha256": "old"},
            },
        )

        result = worker.reingest_source_worker(task_self, str(src["id"]), "dave")

        assert result["modified_files"] == ["b.md"]
        assert parser.parsed == ["b.md"]
        structure = SourcesRepository(pg_conn).get(str(src["id"]), "dave")["directory_structure"]
        assert structure["a.md"]["token_count"] == 51
        assert all("bravo" in text for text in store.embedded)
