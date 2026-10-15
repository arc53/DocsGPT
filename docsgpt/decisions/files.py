"""Decision model files: pinned, downloaded only when first needed, and kept as real files.

Nothing here runs at import. The files are fetched at a pinned commit into
``DECISION_CACHE_DIR/<repo>/<revision>/`` the first time the model is loaded (or by ``docsgpt decisions
prefetch``), never while every decision feature is off. They are real files, not the Hub cache's symlinks:
onnxruntime refuses external weights reached through a symlink that leaves the model's folder. A download goes
into ``<revision>.partial`` and is renamed when complete, under a lock file, so an interrupted or concurrent
download never looks finished.
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


def _onnx_in(folder: Path) -> Optional[Path]:
    """The folder holding ``model.onnx``: ``folder/onnx`` or ``folder`` itself."""
    for candidate in (folder / "onnx", folder):
        if (candidate / "model.onnx").is_file():
            return candidate
    return None


def local_onnx_dir(spec: ModelSpec) -> Optional[Path]:
    """The ONNX folder already on disk (``DECISION_MODEL_PATH`` or a finished download), or ``None``."""
    from docsgpt.core.settings import settings

    if settings.DECISION_MODEL_PATH:
        return _onnx_in(Path(settings.DECISION_MODEL_PATH).expanduser())
    folder = snapshot_dir(spec)
    return _onnx_in(folder) if folder.is_dir() else None


def ensure_onnx(spec: ModelSpec) -> Path:
    """The ONNX folder, downloading the pinned files first if they are not on disk.

    Raises:
        FilesUnavailable: When the files are missing and cannot be fetched; the message names the fix.
    """
    from docsgpt.core.settings import settings

    found = local_onnx_dir(spec)
    if found:
        return found
    if settings.DECISION_MODEL_PATH:
        raise FilesUnavailable(
            "offline", f"DECISION_MODEL_PATH ({settings.DECISION_MODEL_PATH}) holds no model.onnx"
        )
    if offline():
        raise FilesUnavailable(
            "offline",
            f"{spec.id} is not in {snapshot_dir(spec).parent} and HF_HUB_OFFLINE is set: run "
            "`docsgpt decisions prefetch` on a connected machine and copy DECISION_CACHE_DIR, or set "
            "DECISION_MODEL_PATH",
        )
    return _download(spec, revision(spec))


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


def _download(spec: ModelSpec, rev: str) -> Path:
    from huggingface_hub import snapshot_download

    target = snapshot_dir(spec)
    partial = target.with_name(target.name + ".partial")
    with _locked(target.parent / ".lock"):
        found = _onnx_in(target) if target.is_dir() else None
        if found:  # another process finished while this one waited
            return found
        logger.info("Downloading the decision model %s at %s into %s", spec.id, rev, target)
        try:
            snapshot_download(repo_id=spec.id, revision=rev, allow_patterns=list(ONNX_PATTERNS), local_dir=partial)
        except Exception as exc:  # noqa: BLE001 -- any failure leaves the partial folder to resume from
            raise FilesUnavailable("download", f"could not download {spec.id} at {rev}: {exc}") from exc
        if _onnx_in(partial) is None:
            raise FilesUnavailable("download", f"{spec.id} at {rev} has no onnx/model.onnx")
        if target.exists():
            shutil.rmtree(target)
        os.replace(partial, target)
    return _onnx_in(target)

