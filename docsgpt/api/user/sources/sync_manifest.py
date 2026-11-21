"""What a file source's storage holds, as the last ``sync`` left it.

``sources.sync_manifest`` records, for each file a ``sync`` stored, the path
the client sent it under, the path it is stored at and the SHA-256 of what
was written:

.. code-block:: json

    {
      "version": 1,
      "generation": "5c1f…",
      "indexed_generation": "5c1f…",
      "writing": false,
      "files": {"guide/введение.md": {"path": "guide/6a0f….md", "sha256": "9b2e…"}}
    }

A client that sends the list of its files (a *manifest*) can then be told
which ones the source does not hold yet, and upload only those.

Two rules keep the record honest:

* A ``sha256`` is only ever recorded for bytes that were written while the
  source's files lock was held, and is cleared *before* a stored file is
  overwritten. A request that dies part way leaves entries without a hash,
  which the next sync uploads again.
* ``generation`` changes every time the stored files are about to change,
  and again once they have changed; ``writing`` is true in between, and
  stays true if the request died there. A reingest that read the files at
  generation ``g``, with ``writing`` false, sets ``indexed_generation`` to
  ``g`` when it finishes cleanly, and only if the record still says ``g``
  and not ``writing``. The index is current exactly when the two
  generations are equal and nothing is being written.

The functions here are pure (no storage, no database): ``upload.py`` runs the
plan they return.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from werkzeug.utils import secure_filename

MANIFEST_VERSION = 1
#: Longest path a manifest entry may name, in characters.
MAX_PATH_CHARS = 1024

#: Longest folder or file name in a manifest path, in UTF-8 bytes: one that
#: file systems, and a temporary name built from it, can still hold.
MAX_PART_BYTES = 200

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ManifestError(ValueError):
    """A client's manifest cannot be used.

    Attributes:
        public_message: What is wrong, in words that are safe to return to
            the client: it never quotes the input.
    """

    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message


@dataclass(frozen=True)
class ManifestEntry:
    """One file of a client's manifest."""

    path: str
    sha256: str


@dataclass
class SyncPlan:
    """What one sync request does to a source's stored files.

    Attributes:
        writes: ``(client path, stored path)`` of each uploaded file to store.
        needed: Client paths the source lacks and this request did not bring.
        kept: Client paths whose stored file already has the wanted content.
        files: The manifest's files once ``writes`` are stored, by client
            path: ``{"path": stored path, "sha256": wanted hash}``. Entries of
            ``needed`` paths are absent.
        deletes: Stored paths to remove once nothing is ``needed``.
    """

    writes: list[tuple[str, str]] = field(default_factory=list)
    needed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    files: dict[str, dict[str, Optional[str]]] = field(default_factory=dict)
    deletes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Whether the source will hold every file of the manifest after ``writes``."""
        return not self.needed


def new_generation() -> str:
    """A fresh generation token."""
    return uuid.uuid4().hex


def split_path(path: str) -> list[str]:
    """The parts of a client path: ``\\`` counts as ``/``; empty, ``.`` and ``..`` parts are dropped."""
    return [part for part in path.replace("\\", "/").split("/") if part not in ("", ".", "..")]


def normalize_path(path: str) -> str:
    """A client path as the ``/``-joined parts ``split_path`` keeps."""
    return "/".join(split_path(path))


def stable_name(part: str) -> str:
    """One path part made safe for storage, the same way every time.

    ``safe_filename`` makes up a random name for a part it cannot keep, such
    as one written only in non-Latin letters. A sync has to store a file at
    the same place each time, or every such file would be removed and
    embedded again, so those parts are named after a hash of the part instead.

    Args:
        part: One folder or file name, as the client sent it.

    Returns:
        ``secure_filename(part)`` when that keeps a name; else 32 hex
        characters of the part's SHA-256, with the part's extension when the
        extension is itself safe.
    """
    _, extension = posixpath.splitext(part)
    cleaned = secure_filename(part)
    if cleaned and cleaned != extension.lstrip("."):
        return cleaned
    if secure_filename(f"x{extension}") != f"x{extension}":
        extension = ""
    digest = hashlib.sha256(part.encode("utf-8", "surrogatepass")).hexdigest()[:32]
    return f"{digest}{extension}"


def parse_manifest(raw: Any, max_files: int) -> list[ManifestEntry]:
    """Read a client's manifest.

    Args:
        raw: The JSON text (``str`` or ``bytes``) or the decoded value:
            ``{"version": 1, "files": [{"path": ..., "sha256": ...}, ...]}``.
        max_files: The most files a manifest may list.

    Returns:
        The entries, in the order given.

    Raises:
        ManifestError: Not JSON, the wrong shape, an unknown version, no
            files, too many, a path that is not already in normal form
            (see ``normalize_path``) or not valid Unicode, a repeated path
            or a bad hash.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as err:
            raise ManifestError("The manifest is not UTF-8 text") from err
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError) as err:
            # RecursionError: JSON nested too deep to be a manifest.
            raise ManifestError("The manifest is not valid JSON") from err
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), list):
        raise ManifestError('The manifest must be an object with a "files" list')
    if raw.get("version") != MANIFEST_VERSION:
        raise ManifestError(f"Unsupported manifest version; this server reads version {MANIFEST_VERSION}")
    files = raw["files"]
    if not files:
        raise ManifestError("The manifest lists no files")
    if len(files) > max_files:
        raise ManifestError(f"The manifest lists more than {max_files} files")
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ManifestError("Each manifest file must be an object")
        path, digest = item.get("path"), item.get("sha256")
        if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
            raise ManifestError(f"A manifest path must be 1 to {MAX_PATH_CHARS} characters")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
            raise ManifestError("A manifest path cannot contain control characters")
        if any(0xD800 <= ord(char) <= 0xDFFF for char in path):
            # A lone surrogate (half a character): JSONB cannot store one.
            raise ManifestError("A manifest path must be valid Unicode text")
        if any(len(part.encode("utf-8")) > MAX_PART_BYTES for part in path.split("/")):
            raise ManifestError(f"A folder or file name in a manifest path cannot be over {MAX_PART_BYTES} bytes")
        if normalize_path(path) != path:
            raise ManifestError(
                'A manifest path must be relative, use "/" and have no empty, "." or ".." parts'
            )
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ManifestError("A manifest sha256 must be 64 lowercase hex characters")
        if path in seen:
            raise ManifestError("A manifest path is listed twice")
        seen.add(path)
        entries.append(ManifestEntry(path, digest))
    return entries


def load_state(raw: Any) -> dict:
    """A source's ``sync_manifest`` column as a well-formed state.

    Anything unreadable counts as no record, which only costs an upload.

    Args:
        raw: The column: a dict, its JSON text, or ``None``.

    Returns:
        ``{"version", "generation", "indexed_generation", "files"}``, with
        only well-formed file entries.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
        raw = {}
    files: dict[str, dict[str, Optional[str]]] = {}
    stored = raw.get("files")
    if isinstance(stored, dict):
        for path, entry in stored.items():
            if not isinstance(path, str) or not isinstance(entry, dict):
                continue
            stored_path, digest = entry.get("path"), entry.get("sha256")
            if not isinstance(stored_path, str) or not stored_path:
                continue
            if not (isinstance(digest, str) and _SHA256.fullmatch(digest)):
                digest = None
            files[path] = {"path": stored_path, "sha256": digest}
    generation = raw.get("generation")
    indexed = raw.get("indexed_generation")
    return {
        "version": MANIFEST_VERSION,
        "generation": generation if isinstance(generation, str) and generation else None,
        "indexed_generation": indexed if isinstance(indexed, str) and indexed else None,
        "writing": raw.get("writing") is True,
        "files": files,
    }


def index_is_current(state: dict) -> bool:
    """Whether the last clean reingest read the files as they are now."""
    return (
        not state.get("writing")
        and bool(state.get("generation"))
        and state.get("generation") == state.get("indexed_generation")
    )


def _folder_names(files: dict[str, dict[str, Optional[str]]], paths: Iterable[str]) -> dict[str, str]:
    """The stored folder already chosen for each client folder of ``paths``.

    Args:
        files: The recorded files, by client path.
        paths: The client paths whose records still stand.

    Returns:
        Client folder path to stored folder path, for use as
        ``_safe_relative_upload_path``'s ``folder_names``.
    """
    names: dict[str, str] = {}
    for path in paths:
        client_parts = path.split("/")
        stored_parts = files[path]["path"].split("/")
        if len(client_parts) != len(stored_parts):
            continue
        for depth in range(1, len(client_parts)):
            names.setdefault("/".join(client_parts[:depth]), "/".join(stored_parts[:depth]))
    return names


def _reserve_folders(folder_names: dict[str, str], client_path: str, stored_path: str) -> None:
    """Make the folders a file was stored in the ones its client folders map to.

    An allocation can move a file out of the folder first chosen for it (a
    leftover file had that name); the next file of the same client folder
    must follow it there, and another client folder must not be given it.
    """
    client_parts, stored_parts = client_path.split("/"), stored_path.split("/")
    if len(client_parts) != len(stored_parts):
        return
    for depth in range(1, len(client_parts)):
        folder_names["/".join(client_parts[:depth])] = "/".join(stored_parts[:depth])


def _blocked(stored_path: str, stale: set[str]) -> bool:
    """Whether a stale stored file is a folder of ``stored_path``, or ``stored_path`` a folder of one."""
    parts = stored_path.split("/")
    if any("/".join(parts[:depth]) in stale for depth in range(1, len(parts))):
        return True
    prefix = f"{stored_path}/"
    return any(path.startswith(prefix) for path in stale)


def plan_sync(
    state: dict,
    present: Iterable[str],
    manifest: list[ManifestEntry],
    uploaded: Iterable[str],
    allocate: Callable[[str, dict[str, str], set[str]], str],
) -> SyncPlan:
    """Work out what one manifest sync request stores, keeps, still needs and removes.

    A manifest file is *kept* when the record has it with the same hash and
    its stored file is still there, whether or not the request uploaded it
    (one upload serves every file with its content). Otherwise it is
    *written* if this request uploaded it, and *needed* if not. A file the record knows keeps its stored
    path; a new one gets a path from ``allocate``, clear of every path a
    manifest file holds. When the record has two manifest files at one
    stored path (a new path took over the stored file of an old one, and
    both are listed now), only one keeps it, the one whose content it holds
    first; the other counts as new.

    Args:
        state: The source's record (``load_state``).
        present: The stored paths the source's folder holds now.
        manifest: The client's files.
        uploaded: The client paths this request uploaded; each must be in
            ``manifest``.
        allocate: ``(client path, folder names, taken stored paths) -> stored
            path`` for a file the record does not know. It may add to the
            folder names.

    Returns:
        The plan. ``deletes`` lists every present path no manifest file is
        stored at; the caller removes them only when the plan is complete.
    """
    recorded = state.get("files") or {}
    present = set(present)
    uploaded = set(uploaded)
    wanted = {entry.path: entry.sha256 for entry in manifest}
    holders: dict[str, str] = {}
    for path in sorted(
        (path for path in recorded if path in wanted),
        key=lambda path: recorded[path]["sha256"] != wanted[path],
    ):
        holders.setdefault(recorded[path]["path"], path)
    standing = [path for path in recorded if path in wanted and holders[recorded[path]["path"]] == path]
    recorded = {path: entry for path, entry in recorded.items() if path not in wanted or path in standing}
    folder_names = _folder_names(recorded, standing)
    taken = {recorded[path]["path"] for path in standing}
    stale = present - taken

    plan = SyncPlan()
    for entry in manifest:
        known = recorded.get(entry.path)
        if (
            known is not None
            and known["sha256"] == entry.sha256
            and known["path"] in present
        ):
            plan.kept.append(entry.path)
            plan.files[entry.path] = {"path": known["path"], "sha256": entry.sha256}
            continue
        if entry.path not in uploaded:
            plan.needed.append(entry.path)
            continue
        if known is not None and not _blocked(known["path"], present):
            stored_path = known["path"]
        else:
            # New to the record, or its recorded place can no longer take a
            # file: a folder now sits there, or a file where its folder was.
            stored_path = allocate(entry.path, folder_names, taken)
            if _blocked(stored_path, stale):
                # A leftover file sits where this path needs a folder (or the
                # other way round) and is only removed after the writes.
                stored_path = allocate(entry.path, folder_names, taken | stale)
            taken.add(stored_path)
            _reserve_folders(folder_names, entry.path, stored_path)
        plan.writes.append((entry.path, stored_path))
        plan.files[entry.path] = {"path": stored_path, "sha256": entry.sha256}

    claimed = {entry["path"] for entry in plan.files.values()}
    # A needed file keeps the stored path its record names, so a later
    # request overwrites it in place rather than leaving the old copy behind.
    claimed.update(recorded[path]["path"] for path in plan.needed if path in recorded)
    plan.deletes = sorted(present - claimed)
    return plan


def state_before_writes(state: dict, plan: SyncPlan, generation: str) -> dict:
    """The record to save before any stored file changes.

    Every path about to be written loses its hash and the generation moves,
    so a request that stops here leaves nothing the record vouches for
    wrongly. That includes any other client path recorded at a stored path
    about to be written (a renamed file can take over the stored path of the
    name it had).

    Args:
        state: The record as read under the files lock.
        plan: The request's plan.
        generation: The request's new generation.

    Returns:
        The new record; ``state`` is not changed.
    """
    written = {stored_path for _, stored_path in plan.writes}
    files = {
        path: {"path": entry["path"], "sha256": None if entry["path"] in written else entry["sha256"]}
        for path, entry in (state.get("files") or {}).items()
    }
    for client_path, stored_path in plan.writes:
        files[client_path] = {"path": stored_path, "sha256": None}
    return {
        "version": MANIFEST_VERSION,
        "generation": generation,
        "indexed_generation": state.get("indexed_generation"),
        "writing": True,
        "files": files,
    }


def state_after_writes(state: dict, plan: SyncPlan, generation: str) -> dict:
    """The record to save once the plan's writes are stored.

    Args:
        state: The record as read again, after the writes.
        plan: The request's plan.
        generation: The generation ``state_before_writes`` saved.

    Returns:
        The record with the written files' hashes, and with exactly the
        manifest's files when the plan is complete. If the generation is no
        longer this request's, another change ran meanwhile: the written
        paths stay without a hash, so the next sync uploads them again.
    """
    files = {path: dict(entry) for path, entry in (state.get("files") or {}).items()}
    ours = state.get("generation") == generation
    for client_path, stored_path in plan.writes:
        files[client_path] = {
            "path": stored_path,
            "sha256": plan.files[client_path]["sha256"] if ours else None,
        }
    if plan.complete and ours:
        files = {path: dict(entry) for path, entry in plan.files.items()}
    return {
        "version": MANIFEST_VERSION,
        "generation": state.get("generation") or generation,
        "indexed_generation": state.get("indexed_generation"),
        # Still true: the request has files to remove, and says when it is done.
        "writing": bool(state.get("writing")),
        "files": files,
    }


def state_touched(state: dict, written: Iterable[str], generation: str, writing: bool = True) -> dict:
    """The record around a change to the stored files: before it starts, and once it is done.

    Args:
        state: The source's record.
        written: Stored paths about to be written.
        generation: A new generation.
        writing: ``True`` before the change, ``False`` once it is done.

    Returns:
        The record with the new generation, ``writing`` as given, and no
        hash for the written paths.
    """
    written = set(written)
    files = {}
    for path, entry in (state.get("files") or {}).items():
        files[path] = {
            "path": entry["path"],
            "sha256": None if entry["path"] in written else entry["sha256"],
        }
    return {
        "version": MANIFEST_VERSION,
        "generation": generation,
        "indexed_generation": state.get("indexed_generation"),
        "writing": writing,
        "files": files,
    }
