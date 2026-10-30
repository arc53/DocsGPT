"""Decision model files: pinned, downloaded only when first needed, and kept as real files.

Nothing here runs at import. The files are fetched at a pinned commit into
``DECISION_CACHE_DIR/<repo>/<revision>/`` the first time the model is loaded (or by ``docsgpt decisions
prefetch``), never while every decision feature is off. They are real files, not the Hub cache's symlinks:
onnxruntime refuses external weights reached through a symlink that leaves the model's folder. A download goes
into ``<revision>.partial`` and is renamed when complete, under a lock file, so an interrupted or concurrent
download never looks finished.

The torch runtime of ``docsgpt decide-server --device mps|cuda`` reads the safetensors weights from the same folder
(``ensure_torch``); a download for one runtime keeps the other's files. A process that only calls a decision server
(API mode) needs the tokenizer alone, 11 MB, to count tokens and, for vLLM, to build the prompt;
``ensure_tokenizer`` fetches just that file at the same pinned commit.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from pathlib import Path
from typing import Iterator, Optional

from docsgpt.decisions.models import ModelSpec

logger = logging.getLogger(__name__)

#: What the ONNX runtime needs from a model repository: the graph, its weights, tokenizer and serving metadata,
#: plus the question wording (checked against the registry) and the licences. Not the safetensors weights.
ONNX_PATTERNS = ("onnx/*", "questions.json", "LICENSE", "LICENSE-Qwen3")


class FilesUnavailable(Exception):
    """The model files are not on disk and cannot be fetched.

    Attributes:
        reason: ``offline`` (``HF_HUB_OFFLINE`` or ``DECISION_MODEL_PATH`` without the files) or ``download``.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def offline() -> bool:
    """Whether ``HF_HUB_OFFLINE`` forbids downloads."""
    return os.environ.get("HF_HUB_OFFLINE", "").strip().upper() in {"1", "TRUE", "YES", "ON"}


def revision(spec: ModelSpec) -> str:
    """The commit to fetch: ``DECISION_MODEL_REVISION``, else the pin."""
    from docsgpt.core.settings import settings

    return settings.DECISION_MODEL_REVISION or spec.revision


def snapshot_dir(spec: ModelSpec) -> Path:
    """Where the model's files live once downloaded."""
    from docsgpt.core.settings import settings

    return Path(settings.DECISION_CACHE_DIR) / spec.id / revision(spec)


#: Every file the ONNX client opens; a folder missing any of them would fail at load, so it does not count as present.
ONNX_FILES = ("model.onnx", "model.onnx.data", "arcd_serving.json", "config.json", "tokenizer.json")

#: What the torch runtime needs: the safetensors weights with their config and tokenizer, the serving metadata,
#: the question wording and the licences. Not the ONNX export.
TORCH_PATTERNS = (
    "model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json", "arcd_serving.json",
    "questions.json", "LICENSE", "LICENSE-Qwen3",
)

#: Every file the torch runtime opens.
TORCH_FILES = ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json", "arcd_serving.json")


def onnx_folder(folder: Path) -> Optional[Path]:
    """The complete ONNX folder: ``folder/onnx`` or ``folder`` itself."""
    for candidate in (folder / "onnx", folder):
        if all((candidate / name).is_file() for name in ONNX_FILES):
            return candidate
    return None


def torch_folder(folder: Path) -> Optional[Path]:
    """``folder`` when it holds every file the torch runtime opens."""
    return folder if all((folder / name).is_file() for name in TORCH_FILES) else None


#: Per runtime: what to fetch, how to find the complete folder, and the files it needs (for messages).
_LAYOUTS = {
    "onnx": (ONNX_PATTERNS, onnx_folder, f"onnx/{{{','.join(ONNX_FILES)}}}"),
    "torch": (TORCH_PATTERNS, torch_folder, ", ".join(TORCH_FILES)),
}


def _local(spec: ModelSpec, runtime: str) -> Optional[Path]:
    from docsgpt.core.settings import settings

    find = _LAYOUTS[runtime][1]
    if settings.DECISION_MODEL_PATH:
        return find(Path(settings.DECISION_MODEL_PATH).expanduser())
    folder = snapshot_dir(spec)
    return find(folder) if folder.is_dir() else None


def local_onnx_dir(spec: ModelSpec) -> Optional[Path]:
    """The ONNX folder already on disk (``DECISION_MODEL_PATH`` or a finished download), or ``None``."""
    return _local(spec, "onnx")


def local_torch_dir(spec: ModelSpec) -> Optional[Path]:
    """The folder holding the torch runtime's files (``DECISION_MODEL_PATH`` or a finished download), or ``None``."""
    return _local(spec, "torch")


def ensure_onnx(spec: ModelSpec) -> Path:
    """The ONNX folder, downloading the pinned files first if they are not on disk.

    Raises:
        FilesUnavailable: When the files are missing and cannot be fetched; the message names the fix.
    """
    return _ensure(spec, "onnx")


def ensure_torch(spec: ModelSpec) -> Path:
    """The torch runtime's folder, downloading the pinned safetensors files first if they are not on disk.

    Raises:
        FilesUnavailable: When the files are missing and cannot be fetched; the message names the fix.
    """
    return _ensure(spec, "torch")


def _ensure(spec: ModelSpec, runtime: str) -> Path:
    from docsgpt.core.settings import settings

    found = _local(spec, runtime)
    if found:
        return found
    if settings.DECISION_MODEL_PATH:
        names = ONNX_FILES if runtime == "onnx" else TORCH_FILES
        raise FilesUnavailable(
            "offline", f"DECISION_MODEL_PATH ({settings.DECISION_MODEL_PATH}) lacks one of {', '.join(names)}"
        )
    if offline():
        flag = "" if runtime == "onnx" else f" --runtime {runtime}"
        raise FilesUnavailable(
            "offline",
            f"{spec.id} is not in {snapshot_dir(spec).parent} and HF_HUB_OFFLINE is set: run "
            f"`docsgpt decisions prefetch{flag}` on a connected machine and copy DECISION_CACHE_DIR, or set "
            "DECISION_MODEL_PATH",
        )
    return _download(spec, revision(spec), runtime)


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` across processes (where ``fcntl`` exists; one process elsewhere)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        try:
            import fcntl
        except ImportError:  # Windows runs the API in one process
            yield
            return
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _download(spec: ModelSpec, rev: str, runtime: str) -> Path:
    from huggingface_hub import snapshot_download

    patterns, find, needed = _LAYOUTS[runtime]
    target = snapshot_dir(spec)
    partial = target.with_name(target.name + ".partial")
    with _locked(target.parent / ".lock"):
        found = find(target) if target.is_dir() else None
        if found:  # another process finished while this one waited
            return found
        logger.info("Downloading the decision model %s (%s) at %s into %s", spec.id, runtime, rev, target)
        try:
            snapshot_download(repo_id=spec.id, revision=rev, allow_patterns=list(patterns), local_dir=partial)
        except Exception as exc:  # noqa: BLE001 -- any failure leaves the partial folder to resume from
            raise FilesUnavailable("download", f"could not download {spec.id} at {rev}: {exc}") from exc
        if find(partial) is None:
            raise FilesUnavailable("download", f"{spec.id} at {rev} lacks one of {needed}")
        _move_into(partial, target)
    return find(target)


def _move_into(partial: Path, target: Path) -> None:
    """Put a finished download in place; files of the other runtime already in ``target`` stay."""
    if not target.exists():
        os.replace(partial, target)
        return
    for entry in partial.iterdir():
        destination = target / entry.name
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        os.replace(entry, destination)
    partial.rmdir()


#: The tokenizer inside a model repository; the same file in both published models.
TOKENIZER = "onnx/tokenizer.json"


def _tokenizer_dir(spec: ModelSpec) -> Path:
    """Where a tokenizer fetched alone lives, beside (never inside) the model's own folder."""
    folder = snapshot_dir(spec)
    return folder.with_name(folder.name + ".tokenizer")


def local_tokenizer(spec: ModelSpec) -> Optional[Path]:
    """The tokenizer already on disk, or ``None``.

    Any registered model's copy will do, at its configured revision: both models ship the same file, so an API
    process sharing the decider's model cache reads the decider's download instead of fetching its own.
    """
    from docsgpt.core.settings import settings
    from docsgpt.decisions.models import REGISTRY

    if settings.DECISION_MODEL_PATH:
        folder = Path(settings.DECISION_MODEL_PATH).expanduser()
        candidates = [folder / TOKENIZER, folder / "tokenizer.json"]
    else:
        candidates = []
        for each in [spec, *(s for s in REGISTRY.values() if s is not spec)]:
            candidates += [snapshot_dir(each) / TOKENIZER, _tokenizer_dir(each) / TOKENIZER]
    return next((path for path in candidates if path.is_file()), None)


def ensure_tokenizer(spec: ModelSpec) -> Path:
    """The model's ``tokenizer.json``, downloading that file alone at the pinned commit if it is not on disk.

    Raises:
        FilesUnavailable: When the file is missing and cannot be fetched.
    """
    from docsgpt.core.settings import settings

    found = local_tokenizer(spec)
    if found:
        return found
    if settings.DECISION_MODEL_PATH:
        raise FilesUnavailable("offline", f"DECISION_MODEL_PATH ({settings.DECISION_MODEL_PATH}) has no tokenizer.json")
    if offline():
        raise FilesUnavailable(
            "offline",
            f"the decision model's tokenizer is not in {snapshot_dir(spec).parent} and HF_HUB_OFFLINE is set: run "
            "`docsgpt decisions prefetch` on a connected machine and copy DECISION_CACHE_DIR",
        )
    from huggingface_hub import snapshot_download

    rev = revision(spec)
    target = _tokenizer_dir(spec)
    partial = target.with_name(target.name + ".partial")
    with _locked(target.parent / ".tokenizer.lock"):
        if (target / TOKENIZER).is_file():
            return target / TOKENIZER
        logger.info("Downloading the decision model's tokenizer from %s at %s into %s", spec.id, rev, target)
        try:
            snapshot_download(repo_id=spec.id, revision=rev, allow_patterns=[TOKENIZER], local_dir=partial)
        except Exception as exc:  # noqa: BLE001 -- the caller retries after DECISION_LOAD_RETRY_SECONDS
            raise FilesUnavailable("download", f"could not download {spec.id}'s tokenizer at {rev}: {exc}") from exc
        if not (partial / TOKENIZER).is_file():
            raise FilesUnavailable("download", f"{spec.id} at {rev} has no {TOKENIZER}")
        if target.exists():
            shutil.rmtree(target)
        os.replace(partial, target)
    return target / TOKENIZER
