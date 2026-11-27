"""The diffs and bookkeeping behind incremental syncs (docsgpt/parser/incremental.py)."""

import json
import os
from unittest.mock import MagicMock

import pytest

from docsgpt.parser import incremental
from docsgpt.parser.connectors.base import FileEntry, SelectionListing


def _entry(fid, path, version="v1"):
    return FileEntry(id=fid, path=path, version=version, url=f"u/{fid}")


def _record(path, version="v1", tokens=5):
    return {"path": path, "version": version, "url": None, "tokens": tokens}


@pytest.mark.unit
class TestSettingsKey:
    def test_show_links_does_not_change_it(self):
        base = {"chunking": {"max_tokens": 1000}, "retrieval": {"chunks": 2, "show_links": True}}
        other = {"chunking": {"max_tokens": 1000}, "retrieval": {"chunks": 2, "show_links": False}}
        assert incremental.settings_key(base, 1) == incremental.settings_key(other, 1)

    def test_chunking_and_version_change_it(self):
        key = incremental.settings_key({"chunking": {"max_tokens": 1000}}, 1)
        assert key != incremental.settings_key({"chunking": {"max_tokens": 900}}, 1)
        assert key != incremental.settings_key({"chunking": {"max_tokens": 1000}}, 2)

    def test_json_text_is_read(self):
        assert incremental.settings_key('{"a": 1}', 1) == incremental.settings_key({"a": 1}, 1)

    @pytest.mark.parametrize(
        "retrieval",
        [
            {"chunks": 12},
            {"exposure": "agentic_tool"},
            {"retriever": "hybrid"},
            {"rephrase_query": False},
            {"score_threshold": 0.4},
            {"reranker": {"type": "decision", "min_relevance": 0.5}},
            {"prescreen": {"candidate_k": 40}},
            {"graph": {"seed_strategy": "relationships", "blend_vector": False}},
        ],
    )
    def test_a_retrieval_edit_does_not_change_it(self, retrieval):
        # Retrieval settings take effect live: they don't change what a sync ingests.
        base = {"chunking": {"max_tokens": 1000}}
        assert incremental.settings_key(base, 1) == incremental.settings_key({**base, "retrieval": retrieval}, 1)

    def test_graph_extraction_settings_do_not_change_it(self):
        # A graph is carried over by chunk content after any sync, full or not.
        base = {"kind": "graphrag", "chunking": {"max_tokens": 1000}}
        edited = {**base, "graph": {"extraction_model": "other", "gleanings": 2, "max_chunks": 10}}
        assert incremental.settings_key(base, 1) == incremental.settings_key(edited, 1)

    def test_kind_and_embeddings_change_it(self):
        key = incremental.settings_key({"kind": "classic"}, 1, "model-a")
        assert key != incremental.settings_key({"kind": "graphrag"}, 1, "model-a")
        assert key != incremental.settings_key({"kind": "classic"}, 1, "model-b")

    def test_defaults_written_out_match_an_empty_config(self):
        # Ingest reads both as the defaults, so both index the same.
        from docsgpt.storage.db.source_config import SourceConfig

        written = SourceConfig().model_dump()
        assert incremental.settings_key(written, 1) == incremental.settings_key({}, 1)
        assert incremental.settings_key(None, 1) == incremental.settings_key({}, 1)


@pytest.mark.unit
class TestLegacySettingsKey:
    """The key stored before retrieval was left out, still accepted for the same config."""

    def test_it_is_the_old_whole_config_hash(self):
        import hashlib

        config = {"chunking": {"max_tokens": 1000}, "retrieval": {"chunks": 2, "show_links": False}}
        payload = json.dumps(
            {"config": {"chunking": {"max_tokens": 1000}, "retrieval": {"chunks": 2}}, "version": 1, "embeddings": "m"},
            sort_keys=True, default=str,
        )
        assert incremental.legacy_settings_key(config, 1, "m") == hashlib.sha256(payload.encode()).hexdigest()
        assert incremental.legacy_settings_key(json.dumps(config), 1, "m") == incremental.legacy_settings_key(
            config, 1, "m",
        )

    def test_settings_keys_gives_the_current_then_the_legacy_key(self):
        config = {"retrieval": {"chunks": 3}}
        assert incremental.settings_keys(config, 1, "m") == (
            incremental.settings_key(config, 1, "m"), incremental.legacy_settings_key(config, 1, "m"),
        )

    def test_a_manifest_under_the_legacy_key_is_accepted(self):
        config = {"retrieval": {"chunks": 3}}
        current, legacy = incremental.settings_keys(config, 1, "m")
        manifest = incremental.build_manifest("connector", legacy, {"a": _record("a")})
        assert incremental.load_manifest(manifest, "connector", (current, legacy)) == {"a": _record("a")}
        assert incremental.manifest_settings(manifest) == legacy
        assert incremental.manifest_settings(json.dumps(manifest)) == legacy
        assert incremental.manifest_settings("not json") is None
        assert incremental.manifest_settings(None) is None


@pytest.mark.unit
class TestLoadManifest:
    def test_one_built_under_other_settings_is_not_used(self):
        manifest = incremental.build_manifest("connector", "k1", {"a": _record("a")})
        assert incremental.load_manifest(manifest, "connector", "k1") == {"a": _record("a")}
        assert incremental.load_manifest(manifest, "connector", "k2") is None
        assert incremental.load_manifest(manifest, "content", "k1") is None

    @pytest.mark.parametrize("settings", [[], {}, 7, None])
    def test_settings_that_are_not_a_key_are_not_used(self, settings):
        manifest = {**incremental.build_manifest("connector", "k1", {}), "settings": settings}
        assert incremental.load_manifest(manifest, "connector", ("k1", "k2")) is None
        assert incremental.manifest_settings(manifest) is None

    @pytest.mark.parametrize("raw", [None, "", "not json", [], {"format": 99}])
    def test_anything_unreadable_is_not_used(self, raw):
        assert incremental.load_manifest(raw, "connector", "k") is None


@pytest.mark.unit
class TestPlanConnectorSync:
    def test_classifies_every_kind_of_change(self):
        manifest = {
            "same": _record("a.md"),
            "edit": _record("b.md"),
            "move": _record("c.md"),
            "gone": _record("d.md"),
        }
        listing = SelectionListing([
            _entry("same", "a.md"),
            _entry("edit", "b.md", "v2"),
            _entry("move", os.path.join("sub", "c.md")),
            _entry("new", "e.md"),
        ])
        plan = incremental.plan_connector_sync(manifest, listing, {})
        assert [e.id for e in plan.added] == ["new"]
        assert [e.id for _, e in plan.changed] == ["edit"]
        assert [(r["path"], e.path) for r, e in plan.moved] == [("c.md", os.path.join("sub", "c.md"))]
        assert [fid for fid, _ in plan.removed] == ["gone"]
        assert plan.unchanged == 1
        assert [e.id for e in plan.to_download()] == ["new", "edit"]

    def test_an_incomplete_listing_removes_nothing(self):
        plan = incremental.plan_connector_sync(
            {"gone": _record("d.md")}, SelectionListing([], complete=False), {},
        )
        assert plan.removed == [] and plan.empty

    def test_a_pending_file_counts_as_changed(self):
        plan = incremental.plan_connector_sync(
            {"a": _record("a.md", version=None)}, SelectionListing([_entry("a", "a.md")]), {},
        )
        assert [e.id for _, e in plan.changed] == ["a"]

    def test_a_failed_file_due_a_retry_is_added_again(self):
        failed = {"a": incremental.FailedFile(id="a", path="a.md", version="v1", attempts=1)}
        plan = incremental.plan_connector_sync({}, SelectionListing([_entry("a", "a.md")]), failed)
        assert [e.id for e in plan.added] == ["a"] and plan.retrying == {"a"}

    @pytest.mark.parametrize("failure", [
        incremental.FailedFile(id="a", path="a.md", version="v1", kind="permanent"),
        incremental.FailedFile(id="a", path="a.md", version="v1", attempts=incremental.MAX_TRANSIENT_ATTEMPTS),
    ], ids=["permanent", "out-of-attempts"])
    def test_a_failed_file_not_due_a_retry_waits_for_a_new_version(self, failure):
        listing = SelectionListing([_entry("a", "a.md")])
        assert incremental.plan_connector_sync({}, listing, {"a": failure}).empty
        changed = SelectionListing([_entry("a", "a.md", "v2")])
        assert [e.id for e in incremental.plan_connector_sync({}, changed, {"a": failure}).added] == ["a"]


@pytest.mark.unit
class TestRecordFailures:
    def test_attempts_count_up_for_the_same_transient_version(self):
        entry = _entry("a", "a.md")
        first = incremental.record_failures({}, [entry], {"a": ("transient", "429")})
        second = incremental.record_failures(first, [entry], {"a": ("transient", "429")})
        assert second["a"].attempts == 2

    def test_a_new_version_or_kind_starts_again(self):
        prior = {"a": incremental.FailedFile(id="a", path="a.md", version="v1", attempts=2)}
        assert incremental.record_failures(prior, [_entry("a", "a.md", "v2")], {"a": ("transient", "x")})["a"].attempts == 1
        assert incremental.record_failures(prior, [_entry("a", "a.md")], {"a": ("permanent", "x")})["a"].attempts == 1

    def test_a_read_file_is_dropped_and_untried_ones_kept_while_listed(self):
        prior = {
            "read": incremental.FailedFile(id="read", path="r.md", version="v1"),
            "kept": incremental.FailedFile(id="kept", path="k.md", version="v1"),
            "gone": incremental.FailedFile(id="gone", path="g.md", version="v1"),
        }
        listing = SelectionListing([_entry("read", "r.md"), _entry("kept", "moved/k.md")])
        out = incremental.record_failures(prior, [_entry("read", "r.md")], {}, listing)
        assert set(out) == {"kept"} and out["kept"].path == "moved/k.md"

    def test_round_trip_and_cap(self, monkeypatch):
        monkeypatch.setattr(incremental, "MAX_FAILED_FILES", 2)
        failed = {f"f{i}": incremental.FailedFile(id=f"f{i}", path=f"{i}.md", version=None) for i in range(3)}
        dumped = incremental.dump_failed_files(failed)
        assert len(dumped) == 2
        assert incremental.load_failed_files(dumped)["f0"].path == "0.md"
        assert incremental.load_failed_files([{"no": "id"}, "junk"]) == {}


@pytest.mark.unit
class TestPlanContentSync:
    def test_classifies_by_hash(self):
        plan = incremental.plan_content_sync(
            {"a": {"sha256": "1"}, "b": {"sha256": "2"}, "c": {"sha256": "3"}, "p": {"sha256": None}},
            {"a": "1", "b": "changed", "d": "4", "p": "5"},
        )
        assert (plan.added, sorted(plan.changed), plan.removed, plan.unchanged) == (["d"], ["b", "p"], ["c"], 1)

    def test_content_hash_follows_text_and_metadata(self):
        base = incremental.content_hash(["x"], [{"a": 1}])
        assert base == incremental.content_hash(["x"], [{"a": 1}])
        assert base != incremental.content_hash(["y"], [{"a": 1}])
        assert base != incremental.content_hash(["x"], [{"a": 2}])


@pytest.mark.unit
class TestStructures:
    def test_round_trip(self):
        structure = {
            "a.md": {"type": "text/markdown", "size_bytes": 1},
            "dir": {"sub": {"b.md": {"type": "text/markdown", "size_bytes": 2}}},
        }
        assert incremental.structure_from_files(incremental.structure_files(structure)) == structure

    def test_a_path_through_a_file_is_left_out(self):
        files = {"a": {"type": "t", "size_bytes": 1}, os.path.join("a", "b"): {"type": "t", "size_bytes": 2}}
        assert incremental.structure_from_files(files) == {"a": {"type": "t", "size_bytes": 1}}


@pytest.mark.unit
class TestChunkEdits:
    def _store(self, chunks):
        store = MagicMock(spec=["get_chunks", "delete_chunk", "add_chunk", "update_chunk"])
        store.get_chunks.return_value = chunks
        return store

    def test_ids_by_path_come_from_one_listing(self):
        store = self._store([
            {"doc_id": "1", "metadata": {"source": "a"}},
            {"doc_id": "2", "metadata": {"source": "b"}},
            {"doc_id": "3", "metadata": {"source": "a"}},
        ])
        assert incremental.chunk_ids_by_path(store, ["a", "x"]) == {"a": ["1", "3"]}
        store.get_chunks.assert_called_once()

    def test_a_store_that_cannot_list_raises(self):
        with pytest.raises(NotImplementedError):
            incremental.chunk_ids_by_path(self._store(None), ["a"])

    def test_undeleted_chunks_are_reported_by_path(self):
        store = self._store([])
        store.delete_chunk.side_effect = [True, RuntimeError("down")]
        deleted, undeleted = incremental.delete_chunk_ids(store, {"a": ["1"], "b": ["2"]})
        assert (deleted, undeleted) == (1, {"b"})

    def test_a_store_without_metadata_rewrites_goes_through_update_chunk(self):
        store = self._store([{"doc_id": "1", "text": "t", "metadata": {"source": "a", "x": 1}}])
        count = incremental.rewrite_chunk_paths(store, {"a": (["1"], {"source": "b", "url": None})})
        assert count == 1
        store.update_chunk.assert_called_once_with("1", "t", {"source": "b", "x": 1})


class _Store:
    """A real ``BaseVectorStore`` subclass held in a dict, built lazily so the import stays local."""

    @staticmethod
    def make(add_failures=0, overrides_add_chunks=False):
        from docsgpt.vectorstore.base import BaseVectorStore

        class Store(BaseVectorStore):
            def __init__(self):
                super().__init__()
                self.chunks = {}
                self.writes = []
                self.failures_left = add_failures

            def search(self, *a, **k):
                return []

            def add_texts(self, texts, metadatas=None, *a, **k):
                if self.failures_left:
                    self.failures_left -= 1
                    raise RuntimeError("429")
                self.writes.append(len(texts))
                ids = []
                for text, meta in zip(texts, metadatas):
                    cid = str(len(self.chunks) + 1)
                    self.chunks[cid] = {"doc_id": cid, "text": text, "metadata": dict(meta)}
                    ids.append(cid)
                return ids

            def get_chunks(self, *a, **k):
                return list(self.chunks.values())

            def delete_chunk(self, cid, *a, **k):
                return self.chunks.pop(cid, None) is not None

            def update_chunks_metadata(self, updates):
                return 0

        if overrides_add_chunks:
            Store.add_chunks = lambda self, texts, metadatas=None: self.add_texts(texts, metadatas)
        return Store()


@pytest.mark.unit
class TestBatchedWrites:
    def test_adds_go_in_embedding_batches_with_the_source_stamped(self, monkeypatch):
        store = _Store.make()
        count = incremental.add_chunks(store, [(f"t{i}", {"source": "a"}) for i in range(5)], source_id="s1", batch=2)
        assert count == 5 and store.writes == [2, 2, 1]
        assert all(c["metadata"]["source_id"] == "s1" for c in store.chunks.values())

    def test_a_store_with_its_own_add_chunks_is_written_once(self):
        store = _Store.make(overrides_add_chunks=True)
        incremental.add_chunks(store, [(f"t{i}", {}) for i in range(5)], batch=2)
        assert store.writes == [5]

    def test_a_failed_batch_is_retried_with_backoff(self, monkeypatch):
        waits = []
        monkeypatch.setattr(incremental, "_sleep", waits.append)
        store = _Store.make(add_failures=2)
        assert incremental.add_chunks(store, [("t", {})]) == 1
        assert waits == [incremental.ADD_RETRY_SECONDS, incremental.ADD_RETRY_SECONDS * 2]

    def test_a_batch_that_keeps_failing_raises(self, monkeypatch):
        monkeypatch.setattr(incremental, "_sleep", lambda s: None)
        with pytest.raises(RuntimeError):
            incremental.add_chunks(_Store.make(add_failures=incremental.ADD_TRIES), [("t", {})])

    def test_a_short_delete_names_the_paths_left(self, monkeypatch):
        store = _Store.make()
        store.add_texts(["a", "b"], [{"source": "a"}, {"source": "b"}])
        monkeypatch.setattr(store, "delete_chunks", lambda ids: (store.chunks.pop("1"), 1)[1])
        deleted, left = incremental.delete_chunk_ids(store, {"a": ["1"], "b": ["2"]})
        assert (deleted, left) == (1, {"b"})

    def test_a_short_rewrite_raises(self):
        store = _Store.make()
        store.add_texts(["a"], [{"source": "a"}])
        with pytest.raises(RuntimeError):
            incremental.rewrite_chunk_paths(store, {"a": (["1"], {"source": "b"})})


@pytest.mark.unit
class TestRetryRules:
    def test_a_failure_under_other_parse_settings_is_due_a_retry(self):
        failed = incremental.FailedFile(id="a", path="a", version="v1", kind="permanent", parse_key="old")
        assert not failed.retryable("old")
        assert failed.retryable("new")

    def test_files_trading_paths_are_both_downloaded_again(self):
        manifest = {"A": _record("a.md"), "B": _record("b.md")}
        listing = SelectionListing([_entry("A", "b.md"), _entry("B", "a.md")])
        plan = incremental.plan_connector_sync(manifest, listing, {})
        assert sorted(e.id for _, e in plan.changed) == ["A", "B"] and plan.moved == []

    def test_a_file_moving_onto_a_removed_ones_path_is_downloaded_again(self):
        manifest = {"A": _record("a.md"), "B": _record("b.md")}
        plan = incremental.plan_connector_sync(manifest, SelectionListing([_entry("A", "b.md")]), {})
        assert [e.id for _, e in plan.changed] == ["A"] and [fid for fid, _ in plan.removed] == ["B"]

    def test_retry_failed_tries_every_failed_file(self):
        failed = {"a": incremental.FailedFile(id="a", path="a.md", version="v1", kind="permanent")}
        listing = SelectionListing([_entry("a", "a.md")])
        assert incremental.plan_connector_sync({}, listing, failed).empty
        assert [e.id for e in incremental.plan_connector_sync({}, listing, failed, retry_failed=True).added] == ["a"]


@pytest.mark.unit
class TestEdges:
    def test_settings_key_hashes_text_that_is_not_json(self):
        assert incremental.settings_key("not json", 1) != incremental.settings_key("other", 1)

    def test_a_garbled_attempt_count_reads_as_one(self):
        assert incremental.FailedFile.from_dict({"id": "a", "attempts": "many"}).attempts == 1

    def test_stored_failed_files_read_the_manifest_then_remote_data(self):
        listed = [{"id": "a", "path": "a.md"}]
        assert set(incremental.stored_failed_files({}, {"failed": listed})) == {"a"}
        assert set(incremental.stored_failed_files({}, json.dumps({"failed": listed}))) == {"a"}
        assert set(incremental.stored_failed_files({"failed_files": listed}, "not json")) == {"a"}
        assert incremental.stored_failed_files(None, None) == {}

    def test_a_manifest_whose_files_are_not_a_mapping_is_not_used(self):
        raw = {"format": incremental.MANIFEST_FORMAT, "kind": "connector", "settings": "k", "files": []}
        assert incremental.load_manifest(raw, "connector", "k") is None

    def test_a_stuck_file_at_a_new_path_keeps_its_chunks_moving(self):
        failure = incremental.FailedFile(id="a", path="a.md", version="v2", kind="permanent")
        listing = SelectionListing([_entry("a", "moved/a.md", "v2")])
        plan = incremental.plan_connector_sync({"a": _record("a.md", "v1")}, listing, {"a": failure})
        assert [e.path for _, e in plan.moved] == ["moved/a.md"] and not plan.changed

    def test_a_stuck_file_in_place_is_left_alone(self):
        failure = incremental.FailedFile(id="a", path="a.md", version="v2", kind="permanent")
        listing = SelectionListing([_entry("a", "a.md", "v2")])
        plan = incremental.plan_connector_sync({"a": _record("a.md", "v1")}, listing, {"a": failure})
        assert plan.empty and plan.unchanged == 1

    def test_structure_files_of_something_else_is_empty(self):
        assert incremental.structure_files(["not", "a", "dict"]) == {}

    def test_structure_from_files_skips_an_empty_path(self):
        assert incremental.structure_from_files({"": {"type": "t", "size_bytes": 1}}) == {}

    def test_a_delete_that_raises_lists_what_is_left(self, monkeypatch):
        store = _Store.make()
        store.add_texts(["a"], [{"source": "a"}])
        monkeypatch.setattr(store, "delete_chunks", lambda ids: (_ for _ in ()).throw(RuntimeError("down")))
        assert incremental.delete_chunk_ids(store, {"a": ["1"]}) == (0, {"a"})

    def test_a_delete_whose_relisting_fails_counts_every_path(self, monkeypatch):
        store = _Store.make()
        monkeypatch.setattr(store, "delete_chunks", lambda ids: 0)
        monkeypatch.setattr(store, "get_chunks", lambda: (_ for _ in ()).throw(RuntimeError("down")))
        assert incremental.delete_chunk_ids(store, {"a": ["1"], "b": ["2"]}) == (0, {"a", "b"})

    def test_the_retry_sleep_waits(self, monkeypatch):
        import time

        slept = []
        monkeypatch.setattr(time, "sleep", slept.append)
        incremental._sleep(1.5)
        assert slept == [1.5]


@pytest.mark.unit
class TestAmbiguousCommit:
    def test_a_batch_that_landed_with_its_reply_lost_is_not_added_twice(self, monkeypatch):
        monkeypatch.setattr(incremental, "_sleep", lambda s: None)
        store = _Store.make()
        real = store.add_texts
        state = {"lost": True}

        def add_texts(texts, metadatas=None, *a, **k):
            ids = real(texts, metadatas)
            if state["lost"] and any(m.get("source") == "b" for m in metadatas):
                state["lost"] = False
                raise RuntimeError("commit reply lost")
            return ids

        monkeypatch.setattr(store, "add_texts", add_texts)
        incremental.add_chunks(store, [("one", {"source": "a"}), ("two", {"source": "b"}), ("three", {"source": "b"})],
                               batch=1)
        texts = sorted(c["text"] for c in store.chunks.values())
        assert texts == ["one", "three", "two"]


    def test_a_cleanup_that_leaves_strays_stops_the_retry(self, monkeypatch):
        monkeypatch.setattr(incremental, "_sleep", lambda s: None)
        store = _Store.make()
        real = store.add_texts
        calls = {"n": 0}

        def add_texts(texts, metadatas=None, *a, **k):
            calls["n"] += 1
            real(texts, metadatas)
            raise RuntimeError("commit reply lost")

        monkeypatch.setattr(store, "add_texts", add_texts)
        monkeypatch.setattr(store, "delete_chunks", lambda ids: 0)  # reports nothing deleted, deletes nothing
        with pytest.raises(RuntimeError, match="not retrying"):
            incremental.add_chunks(store, [("one", {"source": "a"})])
        assert calls["n"] == 1 and len(store.chunks) == 1
