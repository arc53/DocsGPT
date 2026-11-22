"""The diffs and bookkeeping behind incremental syncs (docsgpt/parser/incremental.py)."""

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


@pytest.mark.unit
class TestLoadManifest:
    def test_one_built_under_other_settings_is_not_used(self):
        manifest = incremental.build_manifest("connector", "k1", {"a": _record("a")})
        assert incremental.load_manifest(manifest, "connector", "k1") == {"a": _record("a")}
        assert incremental.load_manifest(manifest, "connector", "k2") is None
        assert incremental.load_manifest(manifest, "content", "k1") is None

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
