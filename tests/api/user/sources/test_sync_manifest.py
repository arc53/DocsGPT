"""Tests for docsgpt/api/user/sources/sync_manifest.py."""

import hashlib
import json

import pytest

from docsgpt.api.user.sources import sync_manifest as sm


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


A, B, C = _sha(b"a"), _sha(b"b"), _sha(b"c")


def _manifest(files: dict[str, str]) -> list[sm.ManifestEntry]:
    return [sm.ManifestEntry(path, digest) for path, digest in files.items()]


def _allocate(client_path, folder_names, taken):
    from docsgpt.api.user.sources.upload import _allocate_stored_path

    return _allocate_stored_path(client_path, folder_names, taken)


def _state(files=None, generation="g1", indexed="g1"):
    return sm.load_state(
        {"version": 1, "generation": generation, "indexed_generation": indexed, "files": files or {}}
    )


class TestStableName:
    def test_keeps_a_name_secure_filename_keeps(self):
        assert sm.stable_name("read me.md") == "read_me.md"

    @pytest.mark.parametrize("name", ["введение.md", "文档", "مرحبا.pdf", "日本語のファイル.txt", "😀.md"])
    def test_a_name_in_another_script_is_named_the_same_every_time(self, name):
        first, second = sm.stable_name(name), sm.stable_name(name)

        assert first == second
        assert first.isascii() and "/" not in first
        assert len(first.split(".")[0]) == 32

    def test_different_names_get_different_stored_names(self):
        assert sm.stable_name("введение.md") != sm.stable_name("заключение.md")

    def test_keeps_a_safe_extension_and_drops_an_unsafe_one(self):
        assert sm.stable_name("отчёт.md").endswith(".md")
        assert "." not in sm.stable_name("файл.доку")


class TestParseManifest:
    def _raw(self, files, version=1):
        return json.dumps({"version": version, "files": files})

    def test_reads_entries_in_order(self):
        entries = sm.parse_manifest(
            self._raw([{"path": "b.md", "sha256": B}, {"path": "docs/введение.md", "sha256": A}]), 10,
        )

        assert entries == [sm.ManifestEntry("b.md", B), sm.ManifestEntry("docs/введение.md", A)]

    def test_reads_bytes(self):
        assert sm.parse_manifest(self._raw([{"path": "a.md", "sha256": A}]).encode(), 10)

    @pytest.mark.parametrize("raw", [
        "not json", b"\xff\xfe", "[]", '{"version": 1}', '{"version": 1, "files": {}}',
        '{"version": 2, "files": [{"path": "a", "sha256": "%s"}]}' % A,
        '{"version": 1, "files": []}',
        '{"version": 1, "files": ["a.md"]}',
        "[" * 100_000,
    ])
    def test_refuses_the_wrong_shape(self, raw):
        with pytest.raises(sm.ManifestError):
            sm.parse_manifest(raw, 10)

    @pytest.mark.parametrize("path", [
        "", "/abs.md", "../up.md", "a/../b.md", "a//b.md", "./a.md", "a\\b.md", "a/", "a\nb.md", "a\x00.md",
        "x" * 1025, "half\udc80.md", "docs/" + "n" * 201 + ".md", "д" * 101, 5, None,
    ])
    def test_refuses_a_path_not_in_normal_form(self, path):
        with pytest.raises(sm.ManifestError):
            sm.parse_manifest({"version": 1, "files": [{"path": path, "sha256": A}]}, 10)

    @pytest.mark.parametrize("digest", ["", "abc", A.upper(), A + "0", A + "\n", None, 7])
    def test_refuses_a_bad_hash(self, digest):
        with pytest.raises(sm.ManifestError):
            sm.parse_manifest({"version": 1, "files": [{"path": "a.md", "sha256": digest}]}, 10)

    def test_refuses_a_repeated_path(self):
        with pytest.raises(sm.ManifestError):
            sm.parse_manifest(self._raw([{"path": "a.md", "sha256": A}, {"path": "a.md", "sha256": B}]), 10)

    def test_refuses_too_many_files(self):
        with pytest.raises(sm.ManifestError):
            sm.parse_manifest(self._raw([{"path": f"{i}.md", "sha256": A} for i in range(3)]), 2)


class TestLoadState:
    def test_nothing_recorded(self):
        assert sm.load_state(None) == {
            "version": 1, "generation": None, "indexed_generation": None, "writing": False, "files": {},
        }

    def test_reads_json_text(self):
        raw = json.dumps({"version": 1, "generation": "g", "files": {"a.md": {"path": "a.md", "sha256": A}}})

        assert sm.load_state(raw)["files"] == {"a.md": {"path": "a.md", "sha256": A}}

    @pytest.mark.parametrize("raw", ["{", [], 3, {"version": 9, "files": {"a": {"path": "a", "sha256": A}}}])
    def test_unreadable_counts_as_nothing_recorded(self, raw):
        assert sm.load_state(raw)["files"] == {}

    def test_drops_malformed_entries_and_hashes(self):
        state = sm.load_state({"version": 1, "files": {
            "ok.md": {"path": "ok.md", "sha256": A},
            "nohash.md": {"path": "nohash.md", "sha256": "zz"},
            "nopath.md": {"sha256": A},
            "notdict.md": "x",
        }})

        assert state["files"] == {
            "ok.md": {"path": "ok.md", "sha256": A},
            "nohash.md": {"path": "nohash.md", "sha256": None},
        }

    def test_an_index_is_not_current_while_files_are_being_written(self):
        state = _state(generation="g", indexed="g")
        assert sm.index_is_current(state)

        assert not sm.index_is_current({**state, "writing": True})
        assert sm.load_state({"version": 1, "generation": "g", "writing": True, "files": {}})["writing"] is True
        # Anything but a real true is not writing.
        assert sm.load_state({"version": 1, "generation": "g", "writing": "yes", "files": {}})["writing"] is False

    def test_index_is_current_only_when_generations_match(self):
        assert sm.index_is_current(_state(generation="g", indexed="g"))
        assert not sm.index_is_current(_state(generation="g2", indexed="g"))
        assert not sm.index_is_current(sm.load_state(None))


class TestPlanSync:
    def test_first_sync_needs_every_file(self):
        plan = sm.plan_sync(sm.load_state(None), set(), _manifest({"a.md": A, "docs/b.md": B}), set(), _allocate)

        assert plan.needed == ["a.md", "docs/b.md"]
        assert not plan.writes and not plan.kept and not plan.complete

    def test_uploaded_files_are_written_at_safe_paths(self):
        plan = sm.plan_sync(
            sm.load_state(None), set(), _manifest({"a.md": A, "my docs/b.md": B}), {"a.md", "my docs/b.md"},
            _allocate,
        )

        assert plan.writes == [("a.md", "a.md"), ("my docs/b.md", "my_docs/b.md")]
        assert plan.complete
        assert plan.files == {
            "a.md": {"path": "a.md", "sha256": A}, "my docs/b.md": {"path": "my_docs/b.md", "sha256": B},
        }

    def test_a_file_with_the_same_hash_still_stored_is_kept(self):
        state = _state({"a.md": {"path": "a.md", "sha256": A}, "b.md": {"path": "b.md", "sha256": B}})

        plan = sm.plan_sync(state, {"a.md", "b.md"}, _manifest({"a.md": A, "b.md": C}), set(), _allocate)

        assert plan.kept == ["a.md"]
        assert plan.needed == ["b.md"]

    def test_an_edited_file_is_written_over_its_stored_path(self):
        state = _state({"введение.md": {"path": "old-name.md", "sha256": A}})

        plan = sm.plan_sync(state, {"old-name.md"}, _manifest({"введение.md": B}), {"введение.md"}, _allocate)

        assert plan.writes == [("введение.md", "old-name.md")]
        assert plan.deletes == []

    def test_a_recorded_file_missing_from_storage_is_needed(self):
        state = _state({"a.md": {"path": "a.md", "sha256": A}})

        plan = sm.plan_sync(state, set(), _manifest({"a.md": A}), set(), _allocate)

        assert plan.needed == ["a.md"]

    def test_a_recorded_file_without_a_hash_is_needed(self):
        state = _state({"a.md": {"path": "a.md", "sha256": None}})

        plan = sm.plan_sync(state, {"a.md"}, _manifest({"a.md": A}), set(), _allocate)

        assert plan.needed == ["a.md"]
        # Its stored copy stays until the new one replaces it.
        assert plan.deletes == []

    def test_files_no_longer_in_the_manifest_are_deleted(self):
        state = _state({"a.md": {"path": "a.md", "sha256": A}, "gone.md": {"path": "gone.md", "sha256": B}})

        plan = sm.plan_sync(state, {"a.md", "gone.md", "unknown.md"}, _manifest({"a.md": A}), set(), _allocate)

        assert plan.complete and plan.kept == ["a.md"]
        assert plan.deletes == ["gone.md", "unknown.md"]

    def test_a_new_file_avoids_the_stored_path_of_a_kept_one(self):
        # "my docs/a.md" already owns my_docs/a.md; "my_docs/a.md" must not land on it.
        state = _state({"my docs/a.md": {"path": "my_docs/a.md", "sha256": A}})

        plan = sm.plan_sync(
            state, {"my_docs/a.md"}, _manifest({"my docs/a.md": A, "my_docs/a.md": B}), {"my_docs/a.md"}, _allocate,
        )

        assert plan.writes == [("my_docs/a.md", "my_docs_2/a.md")]
        assert plan.deletes == []

    def test_a_new_file_reuses_the_stored_path_of_a_file_being_replaced(self):
        # A source uploaded before manifests has files but no record: the
        # first sync writes over them instead of storing "a_2.md".
        plan = sm.plan_sync(sm.load_state(None), {"a.md"}, _manifest({"a.md": A}), {"a.md"}, _allocate)

        assert plan.writes == [("a.md", "a.md")]
        assert plan.deletes == []

    def test_a_new_file_in_a_known_folder_joins_it(self):
        folder = sm.stable_name("文档")
        state = _state({"文档/a.md": {"path": f"{folder}_2/a.md", "sha256": A}})

        plan = sm.plan_sync(
            state, {f"{folder}_2/a.md"}, _manifest({"文档/a.md": A, "文档/b.md": B}), {"文档/b.md"}, _allocate,
        )

        assert plan.writes == [("文档/b.md", f"{folder}_2/b.md")]

    def test_a_stale_file_where_a_folder_is_needed_does_not_block_the_write(self):
        plan = sm.plan_sync(sm.load_state(None), {"docs"}, _manifest({"docs/a.md": A}), {"docs/a.md"}, _allocate)

        assert plan.writes == [("docs/a.md", "docs_2/a.md")]
        assert plan.deletes == ["docs"]

    def test_a_stale_folder_where_a_file_is_needed_does_not_block_the_write(self):
        plan = sm.plan_sync(sm.load_state(None), {"docs/a.md"}, _manifest({"docs": A}), {"docs"}, _allocate)

        assert plan.writes == [("docs", "docs_2")]
        assert plan.deletes == ["docs/a.md"]

    def test_a_recorded_file_whose_place_a_folder_took_gets_a_new_place(self):
        # "docs" was a file; it was removed by hand and docs/a.md added.
        state = _state({"docs": {"path": "docs", "sha256": A}})

        plan = sm.plan_sync(state, {"docs/a.md"}, _manifest({"docs": A}), {"docs"}, _allocate)

        assert plan.writes == [("docs", "docs_2")]
        assert plan.deletes == ["docs/a.md"]

    def test_a_recorded_file_whose_folder_became_a_file_gets_a_new_place(self):
        state = _state({"docs/a.md": {"path": "docs/a.md", "sha256": A}})

        plan = sm.plan_sync(state, {"docs"}, _manifest({"docs/a.md": A}), {"docs/a.md"}, _allocate)

        assert plan.writes == [("docs/a.md", "docs_2/a.md")]

    def test_a_folder_moved_aside_is_kept_for_its_files_and_from_other_folders(self):
        # A leftover file "docs" moves the client folder "docs" to "docs_2";
        # the client folder really named "docs_2" must not share it.
        plan = sm.plan_sync(
            sm.load_state(None), {"docs"},
            _manifest({"docs/a.md": A, "docs/b.md": B, "docs_2/c.md": C}),
            {"docs/a.md", "docs/b.md", "docs_2/c.md"}, _allocate,
        )

        stored = dict(plan.writes)
        assert stored["docs/a.md"] == "docs_2/a.md" and stored["docs/b.md"] == "docs_2/b.md"
        assert stored["docs_2/c.md"].split("/")[0] not in ("docs", "docs_2")
        assert len(set(stored.values())) == 3

    def test_an_upload_of_a_kept_file_is_not_written_again(self):
        state = _state({"a.md": {"path": "a.md", "sha256": A}})

        plan = sm.plan_sync(state, {"a.md"}, _manifest({"a.md": A}), {"a.md"}, _allocate)

        assert plan.kept == ["a.md"] and not plan.writes

    def test_two_manifest_files_recorded_at_one_stored_path_do_not_share_it(self):
        """``My_Docs/a.md`` took over the stored file of ``My Docs/a.md``; now both are listed."""
        state = _state({
            "My Docs/a.md": {"path": "My_Docs/a.md", "sha256": None},
            "My_Docs/a.md": {"path": "My_Docs/a.md", "sha256": B},
        })
        tree = _manifest({"My Docs/a.md": A, "My_Docs/a.md": B})

        plan = sm.plan_sync(state, {"My_Docs/a.md"}, tree, {"My Docs/a.md"}, _allocate)

        assert plan.kept == ["My_Docs/a.md"]
        assert plan.writes == [("My Docs/a.md", "My_Docs_2/a.md")]
        assert not plan.deletes


class TestStates:
    def _plan(self):
        state = _state({"keep.md": {"path": "keep.md", "sha256": A}, "edit.md": {"path": "edit.md", "sha256": A}})
        plan = sm.plan_sync(
            state, {"keep.md", "edit.md"}, _manifest({"keep.md": A, "edit.md": B, "new.md": C}),
            {"edit.md", "new.md"}, _allocate,
        )
        return state, plan

    def test_before_writes_forgets_the_hashes_about_to_change(self):
        state, plan = self._plan()

        before = sm.state_before_writes(state, plan, "g2")

        assert before["generation"] == "g2" and before["indexed_generation"] == "g1"
        assert before["files"] == {
            "keep.md": {"path": "keep.md", "sha256": A},
            "edit.md": {"path": "edit.md", "sha256": None},
            "new.md": {"path": "new.md", "sha256": None},
        }
        # The state it was built from is untouched.
        assert state["files"]["edit.md"]["sha256"] == A

    def test_before_writes_forgets_another_path_recorded_at_a_written_stored_path(self):
        state = _state({"My Docs/a.md": {"path": "My_Docs/a.md", "sha256": A}})
        plan = sm.plan_sync(
            state, {"My_Docs/a.md"}, _manifest({"My_Docs/a.md": B, "other.md": C}), {"My_Docs/a.md"}, _allocate,
        )
        assert plan.writes == [("My_Docs/a.md", "My_Docs/a.md")]

        before = sm.state_before_writes(state, plan, "g2")

        assert before["files"]["My Docs/a.md"] == {"path": "My_Docs/a.md", "sha256": None}

    def test_after_writes_records_the_manifest(self):
        state, plan = self._plan()
        before = sm.state_before_writes(state, plan, "g2")

        after = sm.state_after_writes(before, plan, "g2")

        assert after["generation"] == "g2"
        assert after["files"] == {
            "keep.md": {"path": "keep.md", "sha256": A},
            "edit.md": {"path": "edit.md", "sha256": B},
            "new.md": {"path": "new.md", "sha256": C},
        }
        assert not sm.index_is_current(after)

    def test_after_writes_trusts_nothing_it_wrote_when_another_change_ran(self):
        state, plan = self._plan()
        before = sm.state_before_writes(state, plan, "g2")
        touched = sm.state_touched(before, set(), "g3")

        after = sm.state_after_writes(touched, plan, "g2")

        assert after["generation"] == "g3"
        assert after["files"]["edit.md"]["sha256"] is None
        assert after["files"]["new.md"]["sha256"] is None
        assert after["files"]["keep.md"]["sha256"] == A

    def test_an_incomplete_request_keeps_the_other_records(self):
        state = _state({"old.md": {"path": "old.md", "sha256": A}})
        plan = sm.plan_sync(state, {"old.md"}, _manifest({"a.md": A, "b.md": B}), {"a.md"}, _allocate)
        before = sm.state_before_writes(state, plan, "g2")

        after = sm.state_after_writes(before, plan, "g2")

        assert not plan.complete
        assert after["files"] == {
            "old.md": {"path": "old.md", "sha256": A}, "a.md": {"path": "a.md", "sha256": A},
        }

    def test_a_change_is_writing_until_it_says_it_is_done(self):
        state, plan = self._plan()

        before = sm.state_before_writes(state, plan, "g2")
        after = sm.state_after_writes(before, plan, "g2")
        done = sm.state_touched(after, set(), "g3", writing=False)

        assert before["writing"] is True and after["writing"] is True
        assert done["writing"] is False and done["generation"] == "g3"
        assert done["files"] == after["files"]
        assert sm.state_touched(state, set(), "g2")["writing"] is True

    def test_touched_drops_the_hash_of_written_paths_and_moves_the_generation(self):
        state = _state({"a.md": {"path": "x/a.md", "sha256": A}, "b.md": {"path": "b.md", "sha256": B}})

        touched = sm.state_touched(state, {"x/a.md"}, "g2")

        assert touched["generation"] == "g2" and touched["indexed_generation"] == "g1"
        assert touched["files"] == {
            "a.md": {"path": "x/a.md", "sha256": None}, "b.md": {"path": "b.md", "sha256": B},
        }
