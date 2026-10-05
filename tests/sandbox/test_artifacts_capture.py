"""Unit tests for artifacts_capture scratch/outputs filtering."""

from __future__ import annotations

import hashlib
import logging

import pytest

from docsgpt.sandbox import artifacts_capture as ac
from docsgpt.sandbox.artifacts_capture import _is_scratch, _matches_outputs


@pytest.mark.unit
class TestIsScratch:
    @pytest.mark.parametrize(
        "path",
        ["tmp/x.csv", "tmp/sub/y.json", "scratch/preview.png", "scratch/sub/check.pdf",
         "__pycache__/m.pyc", "pkg/__pycache__/m.pyc",
         ".cache/blob", ".ipynb_checkpoints/nb", "a.tmp", "b.lock", "c.pyc"],
    )
    def test_scratch_paths_excluded(self, path):
        assert _is_scratch(path) is True

    @pytest.mark.parametrize(
        "path", ["report.pdf", "out/data.csv", "deck.pptx", "notes.txt", "tmpfile.txt", "scratchpad.txt",
                 "out/scratch/x.csv"],
    )
    def test_real_outputs_kept(self, path):
        assert _is_scratch(path) is False


@pytest.mark.unit
class TestMatchesOutputs:
    def test_basename_and_path(self):
        assert _matches_outputs("report.pdf", ["report.pdf"])
        assert _matches_outputs("out/report.pdf", ["report.pdf"])  # basename also matches

    def test_globs(self):
        assert _matches_outputs("a/b.csv", ["*.csv"])
        assert _matches_outputs("out/x.json", ["out/*.json"])

    def test_no_match(self):
        assert not _matches_outputs("report.pdf", ["*.csv"])


class _FakeMgr:
    """Serves a fixed {rel_path: bytes} workspace listing."""

    def __init__(self, files):
        self._files = files

    def list_files(self, _sid):
        return list(self._files)

    def get_file(self, _sid, path):
        return self._files[path]


@pytest.mark.unit
class TestCaptureFiltering:
    @staticmethod
    def _captured(monkeypatch, files, pre=None, outputs=None):
        seen = []

        def fake_persist(rel_path, data, **_kw):
            seen.append(rel_path)
            return {"artifact_id": rel_path, "version": 1,
                    "filename": rel_path.rsplit("/", 1)[-1], "mime_type": "x", "size": len(data)}

        monkeypatch.setattr(ac, "persist_artifact", fake_persist)
        ac.capture_artifacts(_FakeMgr(files), "sid", pre or {}, user_id="u", outputs=outputs)
        return seen

    def test_auto_skips_scratch(self, monkeypatch):
        files = {"report.pdf": b"x", "tmp/scratch.csv": b"y", "scratch/preview.png": b"p",
                 "__pycache__/m.pyc": b"z"}
        assert self._captured(monkeypatch, files) == ["report.pdf"]

    def test_inputs_never_captured(self, monkeypatch):
        files = {"report.pdf": b"x", "inputs/source.csv": b"y"}
        assert self._captured(monkeypatch, files) == ["report.pdf"]

    def test_outputs_allow_list_only(self, monkeypatch):
        files = {"report.pdf": b"x", "data.csv": b"y", "notes.txt": b"z"}
        assert self._captured(monkeypatch, files, outputs=["report.pdf"]) == ["report.pdf"]

    def test_outputs_bypass_scratch(self, monkeypatch):
        # An explicit pattern wins over the scratch skip.
        files = {"tmp/keep.csv": b"x", "skip.txt": b"y"}
        assert self._captured(monkeypatch, files, outputs=["*.csv"]) == ["tmp/keep.csv"]

    def test_unchanged_file_skipped(self, monkeypatch):
        pre = {"report.pdf": (1, hashlib.sha256(b"x").hexdigest())}
        assert self._captured(monkeypatch, {"report.pdf": b"x"}, pre=pre) == []
        # Content change is captured.
        assert self._captured(monkeypatch, {"report.pdf": b"xy"}, pre=pre) == ["report.pdf"]


class _CountingMgr:
    """Serves a fixed {rel_path: bytes} workspace and counts every get_file read."""

    def __init__(self, files):
        self._files = files
        self.reads = 0

    def list_files(self, _sid):
        return list(self._files)

    def get_file(self, _sid, path):
        self.reads += 1
        return self._files[path]


@pytest.mark.unit
class TestReadSweepCap:
    def test_snapshot_signature_scan_capped(self):
        # An unchanged-file-heavy workspace can no longer be read in full each pass.
        files = {f"f{i:04d}.txt": b"x" for i in range(ac.MAX_SCANNED_FILES + 50)}
        mgr = _CountingMgr(files)
        sigs = ac.snapshot_signatures(mgr, "sid")
        assert mgr.reads == ac.MAX_SCANNED_FILES
        assert len(sigs) == ac.MAX_SCANNED_FILES

    def test_capture_read_sweep_capped(self, monkeypatch):
        # Every get_file (even for unchanged, never-persisted files) counts toward the cap.
        files = {f"f{i:04d}.txt": b"x" for i in range(ac.MAX_SCANNED_FILES + 50)}
        pre = {name: (1, hashlib.sha256(b"x").hexdigest()) for name in files}  # all unchanged
        mgr = _CountingMgr(files)
        monkeypatch.setattr(ac, "persist_artifact", lambda *a, **k: None)
        captured = ac.capture_artifacts(mgr, "sid", pre, user_id="u")
        assert captured == []  # nothing changed -> nothing persisted
        assert mgr.reads == ac.MAX_SCANNED_FILES  # but the sweep is still bounded


class _ListingRaisesMgr:
    """A manager whose workspace listing fails (sandbox auto-stopped/deleted)."""

    def list_files(self, _sid):
        # Mirrors the generic IOError the Daytona/Jupyter backends raise when the
        # workspace can't be listed because the runtime is gone.
        raise IOError("list_files failed: RuntimeError")


@pytest.mark.unit
class TestListingFailureLogLevel:
    """Regression: a swallowed, recoverable workspace-listing failure must log at
    WARNING, not ERROR.

    ``snapshot_signatures`` / ``capture_artifacts`` catch a failed listing, log it,
    and return empty (best-effort — the exec result is still delivered). Logging it
    via ``logger.exception`` stamps it ERROR, which inflated the production error
    stream: on 2026-07-20 these two lines were 7 of the day's ~43 real-app ERRORs
    and false-alarmed the error review (ledger #28, Bug B). A no-op capture is not
    an error.
    """

    def test_pre_exec_listing_failure_logs_warning_not_error(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="docsgpt.sandbox.artifacts_capture"):
            sigs = ac.snapshot_signatures(_ListingRaisesMgr(), "sid")
        assert sigs == {}  # swallowed, best-effort
        recs = [r for r in caplog.records if "pre-exec listing failed" in r.getMessage()]
        assert recs, "expected a pre-exec listing-failed log record"
        assert all(r.levelno == logging.WARNING for r in recs), (
            "a swallowed, recoverable listing failure must not log at ERROR"
        )

    def test_post_exec_listing_failure_logs_warning_not_error(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="docsgpt.sandbox.artifacts_capture"):
            captured = ac.capture_artifacts(_ListingRaisesMgr(), "sid", {}, user_id="u")
        assert captured == []  # swallowed, best-effort
        recs = [r for r in caplog.records if "post-exec listing failed" in r.getMessage()]
        assert recs, "expected a post-exec listing-failed log record"
        assert all(r.levelno == logging.WARNING for r in recs), (
            "a swallowed, recoverable listing failure must not log at ERROR"
        )


@pytest.mark.unit
class TestPersistArtifactVersionsSameName:
    """A re-saved file becomes the next version of its artifact, not a second artifact."""

    _EXISTING = {"id": "art-1", "user_id": "u", "current_version": 2, "metadata": {"ref_seq": 1}}

    @staticmethod
    def _wire(monkeypatch, existing=None, current_sha=None, ref="A1"):
        calls = {"new": [], "append": [], "lookup": []}

        def fake_find(filename, **kw):
            calls["lookup"].append((filename, kw))
            if existing is None:
                return None
            current = {"version": 2, "sha256": current_sha, "size": 3,
                       "filename": filename, "mime_type": "application/x-test"}
            return existing, current, ref

        monkeypatch.setattr(ac, "_find_same_name_artifact", fake_find)
        monkeypatch.setattr(
            ac, "persist_new_artifact",
            lambda **kw: calls["new"].append(kw) or {"artifact_id": "new", "version": 1},
        )
        monkeypatch.setattr(
            ac, "append_artifact_version",
            lambda **kw: calls["append"].append(kw) or {"artifact_id": kw["artifact_id"], "version": 3},
        )
        return calls

    def test_same_name_from_the_same_tool_appends_a_version(self, monkeypatch):
        calls = self._wire(monkeypatch, existing=self._EXISTING, current_sha="other")
        produced_by = {"tool": "code_executor", "action": "run_code"}
        ref = ac.persist_artifact("out/review.docx", b"new", user_id="u", conversation_id="c",
                                  message_id="m2", produced_by=produced_by)
        assert calls["new"] == []
        (append,) = calls["append"]
        assert append["artifact_id"] == "art-1"
        assert append["user_id"] == "u" and append["data"] == b"new"
        assert append["filename"] == "review.docx" and append["produced_by"] == produced_by
        assert append["conversation_id"] == "c" and append["workflow_run_id"] is None
        assert ref == {"artifact_id": "art-1", "version": 3}
        (lookup,) = calls["lookup"]
        assert lookup == ("review.docx", {"user_id": "u", "tool": "code_executor",
                                          "conversation_id": "c", "workflow_run_id": None})

    def test_identical_bytes_reuse_the_current_version(self, monkeypatch):
        data = b"same"
        calls = self._wire(monkeypatch, existing=self._EXISTING, current_sha=hashlib.sha256(data).hexdigest())
        ref = ac.persist_artifact("review.docx", data, user_id="u", conversation_id="c",
                                  produced_by={"tool": "code_executor"})
        assert calls["new"] == [] and calls["append"] == []
        assert ref == {"artifact_id": "art-1", "version": 2, "filename": "review.docx",
                       "mime_type": "application/x-test", "size": 3, "ref": "A1"}

    def test_identical_bytes_without_a_ref_omit_it(self, monkeypatch):
        data = b"same"
        self._wire(monkeypatch, existing=self._EXISTING, current_sha=hashlib.sha256(data).hexdigest(), ref=None)
        ref = ac.persist_artifact("review.docx", data, user_id="u", workflow_run_id="r",
                                  produced_by={"tool": "code_executor"})
        assert "ref" not in ref and ref["artifact_id"] == "art-1"

    def test_no_match_creates_a_new_artifact(self, monkeypatch):
        calls = self._wire(monkeypatch)
        ac.persist_artifact("review.docx", b"x", user_id="u", conversation_id="c",
                            message_id="m1", produced_by={"tool": "code_executor"})
        assert calls["append"] == []
        (new,) = calls["new"]
        assert new["filename"] == "review.docx" and new["message_id"] == "m1"

    def test_without_a_tool_a_user_or_a_parent_it_never_looks_up(self, monkeypatch):
        # Workflow code nodes record {"node_id", "node_type"}: they keep making new artifacts.
        calls = self._wire(monkeypatch, existing=self._EXISTING, current_sha="other")
        ac.persist_artifact("a.csv", b"x", user_id="u", workflow_run_id="r",
                            produced_by={"node_id": "n1", "node_type": "code"})
        ac.persist_artifact("a.csv", b"x", user_id="u", produced_by={"tool": "code_executor"})
        ac.persist_artifact("a.csv", b"x", user_id="u", conversation_id="c", produced_by=None)
        ac.persist_artifact("a.csv", b"x", user_id="", conversation_id="c",
                            produced_by={"tool": "code_executor"})
        assert calls["lookup"] == [] and calls["append"] == []
        assert len(calls["new"]) == 4


@pytest.mark.unit
class TestFindSameNameArtifact:
    """The lookup wrapper: parent-scoped repo read, current version, ref; failures fall back."""

    def test_returns_the_artifact_its_current_version_and_ref(self, monkeypatch):
        seen = {}

        class _Repo:
            def __init__(self, conn):
                pass

            def find_by_current_filename(self, filename, **kw):
                seen["find"] = (filename, kw)
                return {"id": "art-1", "current_version": 2, "metadata": {"ref_seq": 4}}

            def get_version(self, artifact_id, version):
                seen["version"] = (artifact_id, version)
                return {"version": 2, "sha256": "abc"}

        class _Conn:
            def __enter__(self):
                return object()

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(ac, "db_readonly", lambda: _Conn())
        monkeypatch.setattr(ac, "ArtifactsRepository", _Repo)
        artifact, current, ref = ac._find_same_name_artifact(
            "r.docx", user_id="u", tool="code_executor", conversation_id="c", workflow_run_id=None
        )
        assert artifact["id"] == "art-1" and current["sha256"] == "abc" and ref == "A4"
        assert seen["find"] == ("r.docx", {"user_id": "u", "produced_by_tool": "code_executor",
                                           "conversation_id": "c", "workflow_run_id": None})
        assert seen["version"] == ("art-1", 2)

    def test_a_miss_returns_none(self, monkeypatch):
        class _Repo:
            def __init__(self, conn):
                pass

            def find_by_current_filename(self, filename, **kw):
                return None

        class _Conn:
            def __enter__(self):
                return object()

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(ac, "db_readonly", lambda: _Conn())
        monkeypatch.setattr(ac, "ArtifactsRepository", _Repo)
        assert ac._find_same_name_artifact(
            "r.docx", user_id="u", tool="code_executor", conversation_id="c", workflow_run_id=None
        ) is None

    def test_a_lookup_failure_warns_and_creates_a_new_artifact(self, monkeypatch, caplog):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(ac, "db_readonly", boom)
        created = []
        monkeypatch.setattr(ac, "persist_new_artifact", lambda **kw: created.append(kw) or {"artifact_id": "n"})
        with caplog.at_level(logging.DEBUG, logger="docsgpt.sandbox.artifacts_capture"):
            ref = ac.persist_artifact("r.docx", b"x", user_id="u", conversation_id="c",
                                      produced_by={"tool": "code_executor"})
        assert ref == {"artifact_id": "n"} and len(created) == 1
        recs = [r for r in caplog.records if "same-name artifact lookup failed" in r.getMessage()]
        assert recs and all(r.levelno == logging.WARNING for r in recs)


def test_resaving_one_file_versions_one_artifact_end_to_end(pg_engine, tmp_path, monkeypatch):
    """Three saves of one name, the middle one byte-identical, leave one artifact at v2.

    A file of the same name from another tool, or from another user, stays separate.
    """
    import uuid

    from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
    from docsgpt.storage.local import LocalStorage
    from docsgpt.storage.storage_creator import StorageCreator

    monkeypatch.setattr(StorageCreator, "_instance", LocalStorage(base_dir=str(tmp_path)), raising=False)
    monkeypatch.setattr("docsgpt.storage.db.session.get_engine", lambda: pg_engine)
    conv = str(uuid.uuid4())
    kw = {"user_id": "user-1", "conversation_id": conv,
          "produced_by": {"tool": "code_executor", "action": "run_code"}}

    first = ac.persist_artifact("review.docx", b"draft", message_id=str(uuid.uuid4()), **kw)
    same = ac.persist_artifact("review.docx", b"draft", **kw)
    final = ac.persist_artifact("out/review.docx", b"final", **kw)
    other_tool = ac.persist_artifact(
        "review.docx", b"render", **{**kw, "produced_by": {"tool": "artifact_generator"}}
    )

    assert first["artifact_id"] == same["artifact_id"] == final["artifact_id"]
    assert (first["version"], same["version"], final["version"]) == (1, 1, 2)
    assert first["ref"] == same["ref"] == final["ref"] == "A1"
    assert same == first
    assert other_tool["artifact_id"] != first["artifact_id"] and other_tool["ref"] == "A2"

    with pg_engine.connect() as conn:
        repo = ArtifactsRepository(conn)
        rows = repo.list_artifacts(conversation_id=conv)
        versions = repo.list_versions(first["artifact_id"])
    assert len(rows) == 2
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["sha256"] for v in versions] == [hashlib.sha256(b"draft").hexdigest(),
                                                hashlib.sha256(b"final").hexdigest()]
    stored = LocalStorage(base_dir=str(tmp_path)).get_file(versions[-1]["storage_path"]).read()
    assert stored == b"final"
