"""Unit tests for artifacts_capture scratch/outputs filtering."""

from __future__ import annotations

import hashlib

import pytest

from application.sandbox import artifacts_capture as ac
from application.sandbox.artifacts_capture import _is_scratch, _matches_outputs


@pytest.mark.unit
class TestIsScratch:
    @pytest.mark.parametrize(
        "path",
        ["tmp/x.csv", "tmp/sub/y.json", "__pycache__/m.pyc", "pkg/__pycache__/m.pyc",
         ".cache/blob", ".ipynb_checkpoints/nb", "a.tmp", "b.lock", "c.pyc"],
    )
    def test_scratch_paths_excluded(self, path):
        assert _is_scratch(path) is True

    @pytest.mark.parametrize(
        "path", ["report.pdf", "out/data.csv", "deck.pptx", "notes.txt", "tmpfile.txt"],
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
        files = {"report.pdf": b"x", "tmp/scratch.csv": b"y", "__pycache__/m.pyc": b"z"}
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
