"""Model files: the pinned download, its layout, and what happens offline or on failure."""

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import files
from docsgpt.decisions.models import V02


def write_onnx(folder, skip=()):
    folder.mkdir(parents=True, exist_ok=True)
    for name in files.ONNX_FILES:
        if name not in skip:
            (folder / name).write_bytes(b"x")


class FakeHub:
    """Stands in for ``huggingface_hub.snapshot_download``: writes the ONNX files as real files."""

    def __init__(self, fail=False, with_onnx=True):
        self.calls, self.fail, self.with_onnx = [], fail, with_onnx

    def __call__(self, repo_id, revision, allow_patterns, local_dir):
        self.calls.append({"repo_id": repo_id, "revision": revision, "allow_patterns": allow_patterns,
                           "local_dir": local_dir})
        if self.fail:
            raise OSError("connection reset")
        if self.with_onnx:
            write_onnx(local_dir / "onnx")
        (local_dir / "questions.json").write_text("{}")
        return str(local_dir)


@pytest.fixture
def hub(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DECISION_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "DECISION_MODEL_PATH", None)
    monkeypatch.setattr(settings, "DECISION_MODEL_REVISION", None)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    fake = FakeHub()
    monkeypatch.setattr("huggingface_hub.snapshot_download", fake)
    return fake


@pytest.mark.unit
class TestDownload:
    def test_fetches_the_pinned_onnx_files_as_real_files(self, hub, tmp_path):
        folder = files.ensure_onnx(V02)
        target = tmp_path / "cache" / V02.id / V02.revision
        assert folder == target / "onnx"
        assert (folder / "model.onnx").is_file() and not (folder / "model.onnx").is_symlink()
        (call,) = hub.calls
        assert call["repo_id"] == "arc53/arc-decide-0.4b-v0.2"
        assert call["revision"] == "cb32fe9190a78aed4291fd8e8f087628dc5053df"
        assert call["allow_patterns"] == ["onnx/*", "questions.json", "LICENSE", "LICENSE-Qwen3"]
        assert call["local_dir"].name == f"{V02.revision}.partial"
        assert not call["local_dir"].exists()  # renamed once complete

    def test_present_files_are_not_fetched_again(self, hub):
        files.ensure_onnx(V02)
        files.ensure_onnx(V02)
        assert len(hub.calls) == 1

    def test_revision_override(self, hub, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MODEL_REVISION", "0123abc")
        assert files.ensure_onnx(V02).parent.name == "0123abc"
        assert hub.calls[0]["revision"] == "0123abc"

    def test_a_failed_download_leaves_no_finished_folder(self, hub):
        hub.fail = True
        with pytest.raises(files.FilesUnavailable) as caught:
            files.ensure_onnx(V02)
        assert caught.value.reason == "download"
        assert files.local_onnx_dir(V02) is None

    def test_a_revision_without_onnx_files_is_a_failed_download(self, hub):
        hub.with_onnx = False
        with pytest.raises(files.FilesUnavailable) as caught:
            files.ensure_onnx(V02)
        assert caught.value.reason == "download"
        assert files.local_onnx_dir(V02) is None

    def test_an_interrupted_download_resumes_into_the_same_partial_folder(self, hub):
        hub.fail = True
        with pytest.raises(files.FilesUnavailable):
            files.ensure_onnx(V02)
        hub.fail = False
        files.ensure_onnx(V02)
        assert hub.calls[0]["local_dir"] == hub.calls[1]["local_dir"]


@pytest.mark.unit
class TestOffline:
    def test_hf_hub_offline_without_files(self, hub, monkeypatch):
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        with pytest.raises(files.FilesUnavailable) as caught:
            files.ensure_onnx(V02)
        assert caught.value.reason == "offline"
        assert "docsgpt decisions prefetch" in str(caught.value)
        assert hub.calls == []

    def test_hf_hub_offline_with_prefetched_files(self, hub, monkeypatch):
        files.ensure_onnx(V02)
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        assert files.ensure_onnx(V02).name == "onnx"
        assert len(hub.calls) == 1

    @pytest.mark.parametrize("layout", ["snapshot", "onnx folder"])
    def test_model_path_is_used_as_it_is(self, hub, monkeypatch, tmp_path, layout):
        snapshot = tmp_path / "copied"
        write_onnx(snapshot / "onnx")
        given = snapshot if layout == "snapshot" else snapshot / "onnx"
        monkeypatch.setattr(settings, "DECISION_MODEL_PATH", str(given))
        assert files.ensure_onnx(V02) == snapshot / "onnx"
        assert hub.calls == []

    def test_model_path_without_a_model_never_downloads(self, hub, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "DECISION_MODEL_PATH", str(tmp_path / "empty"))
        with pytest.raises(files.FilesUnavailable) as caught:
            files.ensure_onnx(V02)
        assert caught.value.reason == "offline"
        assert hub.calls == []

    @pytest.mark.parametrize("missing", files.ONNX_FILES)
    def test_an_incomplete_folder_is_not_present(self, hub, monkeypatch, tmp_path, missing):
        write_onnx(tmp_path / "copied" / "onnx", skip=(missing,))
        monkeypatch.setattr(settings, "DECISION_MODEL_PATH", str(tmp_path / "copied"))
        assert files.local_onnx_dir(V02) is None
        with pytest.raises(files.FilesUnavailable) as caught:
            files.ensure_onnx(V02)
        assert missing in str(caught.value)


def write_torch(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in files.TORCH_FILES:
        (folder / name).write_bytes(b"x")


@pytest.mark.unit
class TestTorchFiles:
    @pytest.fixture
    def torch_hub(self, hub, monkeypatch):
        """The fake Hub writing whichever runtime's files were asked for."""

        def snapshot(repo_id, revision, allow_patterns, local_dir):
            hub.calls.append({"repo_id": repo_id, "revision": revision, "allow_patterns": allow_patterns,
                              "local_dir": local_dir})
            if "onnx/*" in allow_patterns:
                write_onnx(local_dir / "onnx")
            else:
                write_torch(local_dir)
            return str(local_dir)

        monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot)
        return hub

    def test_fetches_the_safetensors_files_at_the_pin(self, torch_hub, tmp_path):
        folder = files.ensure_torch(V02)
        assert folder == tmp_path / "cache" / V02.id / V02.revision
        (call,) = torch_hub.calls
        assert call["revision"] == V02.revision
        assert "model.safetensors" in call["allow_patterns"] and "onnx/*" not in call["allow_patterns"]

    @pytest.mark.parametrize("first, second", [("onnx", "torch"), ("torch", "onnx")])
    def test_one_runtimes_download_keeps_the_others_files(self, torch_hub, first, second):
        ensure = {"onnx": files.ensure_onnx, "torch": files.ensure_torch}
        ensure[first](V02)
        ensure[second](V02)
        assert files.local_onnx_dir(V02) is not None and files.local_torch_dir(V02) is not None
        assert len(torch_hub.calls) == 2
        files.ensure_onnx(V02)
        files.ensure_torch(V02)
        assert len(torch_hub.calls) == 2

    def test_offline_names_the_torch_prefetch(self, torch_hub, monkeypatch):
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        with pytest.raises(files.FilesUnavailable) as caught:
            files.ensure_torch(V02)
        assert "prefetch --runtime torch" in str(caught.value)
        assert torch_hub.calls == []
