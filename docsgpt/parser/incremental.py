"""Incremental source syncs: what changed since the last ingest, and the index edits that follow.

A sync that can list its files without downloading them (a connector's
``list_selection``) or that already holds every file's content (a remote
loader) compares them with the record of what the index was built from, and
changes the chunks of the files that differ instead of rebuilding the index:

* **added** files are embedded,
* **changed** files have their chunks replaced,
* **moved or renamed** files (same id, same version, new path) keep their
  chunks with the new path written into their metadata,
* **removed** files lose their chunks,
* unchanged files are left alone.

The record is a manifest kept in ``sources.remote_files``. A connector
manifest is keyed by the provider's file id (``kind: "connector"``); a remote
loader's by the file's path, with a hash of its content (``kind: "content"``).
Both carry the settings key they were built under, so a change of chunking
settings, or of the ingest version, makes the next sync a full one.

The chunk edits here are shared by the upload re-ingest
(``reingest_source_worker``) and the connector and remote syncs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from docsgpt.parser.connectors.base import FileEntry, SelectionListing

#: Format of the manifests below; a manifest of another format is ignored, so the sync is a full one.
MANIFEST_FORMAT = 1
#: Syncs that retry a file failed for a passing reason (rate limit, outage) before it waits for its next change.
MAX_TRANSIENT_ATTEMPTS = 3
#: Failed files kept on a source; a selection with more keeps the first ones and counts the rest.
MAX_FAILED_FILES = 1000
#: Chunks sent to the vector store per write.
ADD_BATCH_CHUNKS = 256

TRANSIENT = "transient"
PERMANENT = "permanent"


def settings_key(config: Any, ingest_version: int) -> str:
    """A key that changes whenever a source's processing settings or the ingest version do.

    ``retrieval.show_links`` is left out: it only decides what a search
    returns, not what is ingested.

    Args:
        config: The source's ``SourceConfig`` dict (or its JSON), or ``None``.
        ingest_version: The loader family's ingest version.

    Returns:
        A hex digest.
    """
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            pass
    if isinstance(config, dict) and isinstance(config.get("retrieval"), dict):
        retrieval = {k: v for k, v in config["retrieval"].items() if k != "show_links"}
        config = {**config, "retrieval": retrieval}
    payload = json.dumps({"config": config or {}, "version": ingest_version}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Failed files
# ---------------------------------------------------------------------------


@dataclass
class FailedFile:
    """A file left out of the index because it could not be downloaded or parsed.

    Attributes:
        id: The connector's file id.
        path: Its path in the source.
        version: The version that failed (Drive ``modifiedTime``...).
        kind: ``transient`` (may pass on a later try) or ``permanent`` (only
            changes with the file).
        attempts: Syncs that tried this version and failed.
        error: What went wrong, shortened.
    """

    id: str
    path: str
    version: Optional[str]
    kind: str = TRANSIENT
    attempts: int = 1
    error: str = ""

    @property
    def retryable(self) -> bool:
        """Whether a sync that finds the file unchanged tries it again."""
        return self.kind == TRANSIENT and self.attempts < MAX_TRANSIENT_ATTEMPTS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "version": self.version,
            "kind": self.kind,
            "attempts": self.attempts,
            "error": self.error[:300],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["FailedFile"]:
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        kind = raw.get("kind") if raw.get("kind") in (TRANSIENT, PERMANENT) else TRANSIENT
        try:
            attempts = max(1, int(raw.get("attempts") or 1))
        except (TypeError, ValueError):
            attempts = 1
        version = raw.get("version")
        return cls(
            id=str(raw["id"]),
            path=str(raw.get("path") or ""),
            version=str(version) if version is not None else None,
            kind=kind,
            attempts=attempts,
            error=str(raw.get("error") or ""),
        )


def load_failed_files(raw: Any) -> Dict[str, FailedFile]:
    """``remote_data.failed_files`` as ``{id: FailedFile}``; anything unreadable is dropped."""
    out: Dict[str, FailedFile] = {}
    if isinstance(raw, list):
        for item in raw:
            failed = FailedFile.from_dict(item)
            if failed is not None:
                out[failed.id] = failed
    return out


def dump_failed_files(failed: Dict[str, FailedFile]) -> List[Dict[str, Any]]:
    """The failed files as stored in ``remote_data``, by path, capped at ``MAX_FAILED_FILES``."""
    return [f.to_dict() for f in sorted(failed.values(), key=lambda f: (f.path, f.id))][:MAX_FAILED_FILES]


def record_failures(
    previous: Dict[str, FailedFile],
    attempted: Iterable[FileEntry],
    failures: Dict[str, Tuple[str, str]],
    listing: Optional[SelectionListing] = None,
) -> Dict[str, FailedFile]:
    """The failed files after a sync: this run's outcomes over what was recorded before.

    A file this run tried and read is dropped; one it tried and failed is
    recorded with one more attempt when the same version failed for a passing
    reason before, else with its first. A file it didn't try keeps its record
    while it is still listed (or the listing was incomplete).

    Args:
        previous: The failed files recorded before this run.
        attempted: The files this run downloaded or tried to.
        failures: ``{id: (kind, error)}`` for the attempted files that failed.
        listing: The selection as listed now; ``None`` keeps every untried record.

    Returns:
        ``{id: FailedFile}``.
    """
    attempted = list(attempted)
    attempted_ids = {entry.id for entry in attempted}
    listed = listing.by_id() if listing is not None else None
    out: Dict[str, FailedFile] = {}
    for file_id, failed in previous.items():
        if file_id in attempted_ids:
            continue
        if listed is None or not listing.complete or file_id in listed:
            current = listed.get(file_id) if listed else None
            if current is not None:
                failed = FailedFile(
                    id=failed.id, path=current.path, version=failed.version, kind=failed.kind,
                    attempts=failed.attempts, error=failed.error,
                )
            out[file_id] = failed
    for entry in attempted:
        if entry.id not in failures:
            continue
        kind, error = failures[entry.id]
        before = previous.get(entry.id)
        attempts = 1
        if before is not None and before.version == entry.version and before.kind == kind == TRANSIENT:
            attempts = before.attempts + 1
        out[entry.id] = FailedFile(
            id=entry.id, path=entry.path, version=entry.version, kind=kind, attempts=attempts, error=error,
        )
    return out


# ---------------------------------------------------------------------------
# Connector manifests and plans
# ---------------------------------------------------------------------------


def load_manifest(raw: Any, kind: str, key: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """The files of a stored manifest, or ``None`` when it can't be used.

    Args:
        raw: ``sources.remote_files`` (a dict, its JSON, or ``None``).
        kind: ``connector`` or ``content``.
        key: The source's current :func:`settings_key`; a manifest built under
            another one is not used, so the sync rebuilds the index.

    Returns:
        ``{file key: record}``, or ``None``.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    if raw.get("format") != MANIFEST_FORMAT or raw.get("kind") != kind or raw.get("settings") != key:
        return None
    files = raw.get("files")
    if not isinstance(files, dict):
        return None
    return {str(k): v for k, v in files.items() if isinstance(v, dict)}


def build_manifest(kind: str, key: str, files: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """A manifest to store in ``sources.remote_files``."""
    return {"format": MANIFEST_FORMAT, "kind": kind, "settings": key, "files": files}


def connector_record(entry: FileEntry, tokens: int = 0) -> Dict[str, Any]:
    """A connector manifest's record of one indexed file."""
    return {"path": entry.path, "version": entry.version, "url": entry.url, "tokens": int(tokens or 0)}


def manifest_from_listing(
    listing: SelectionListing, tokens_by_path: Dict[str, int], left_out: Iterable[str] = (),
) -> Dict[str, Dict[str, Any]]:
    """A connector manifest's files for a listing the index was just built from.

    Args:
        listing: The selection as listed before the download.
        tokens_by_path: Tokens each read file added.
        left_out: Ids not in the index (they failed); they are recorded only
            in the failed files, so the next sync sees them as new.

    Returns:
        ``{id: record}``.
    """
    skip = set(left_out)
    return {
        entry.id: connector_record(entry, tokens_by_path.get(entry.path, 0))
        for entry in listing.entries
        if entry.id not in skip
    }


@dataclass
class ConnectorPlan:
    """What a connector sync must do to bring the index to the listed selection.

    Attributes:
        added: Files the index doesn't hold (new ones, and failed ones being retried).
        changed: ``(old record, entry)`` for files whose version moved on.
        moved: ``(old record, entry)`` for files at a new path with the same version.
        removed: ``(id, old record)`` for files no longer in the selection.
        unchanged: How many files need nothing.
        retrying: Ids in ``added`` that failed before.
    """

    added: List[FileEntry] = field(default_factory=list)
    changed: List[Tuple[Dict[str, Any], FileEntry]] = field(default_factory=list)
    moved: List[Tuple[Dict[str, Any], FileEntry]] = field(default_factory=list)
    removed: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    unchanged: int = 0
    retrying: Set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.moved or self.removed)

    def to_download(self) -> List[FileEntry]:
        """The files to download: added, retried and changed ones."""
        return [*self.added, *(entry for _, entry in self.changed)]


def plan_connector_sync(
    manifest: Dict[str, Dict[str, Any]], listing: SelectionListing, failed: Dict[str, FailedFile],
) -> ConnectorPlan:
    """Diff the manifest of the indexed files against the selection as listed now.

    A file whose current version already failed, and isn't due a retry
    (a ``permanent`` failure, or a ``transient`` one tried
    ``MAX_TRANSIENT_ATTEMPTS`` times), is left as the index holds it until
    its version changes. A file the manifest marks pending (no version, as a
    sync that died part way leaves it) counts as changed.

    Args:
        manifest: ``{id: record}`` of the indexed files.
        listing: The selection now.
        failed: The failed files recorded so far.

    Returns:
        The plan.
    """
    plan = ConnectorPlan()
    for entry in listing.entries:
        record = manifest.get(entry.id)
        failure = failed.get(entry.id)
        stuck = failure is not None and failure.version == entry.version and not failure.retryable
        if record is None:
            if stuck:
                plan.unchanged += 1
                continue
            plan.added.append(entry)
            if failure is not None:
                plan.retrying.add(entry.id)
            continue
        version = record.get("version")
        if version is None or version != entry.version or entry.version is None:
            if stuck:
                # The new version failed for good; the index keeps the old one.
                if record.get("path") != entry.path and version is not None:
                    plan.moved.append((record, entry))
                else:
                    plan.unchanged += 1
                continue
            plan.changed.append((record, entry))
            if failure is not None:
                plan.retrying.add(entry.id)
            continue
        if record.get("path") != entry.path:
            plan.moved.append((record, entry))
        else:
            plan.unchanged += 1
    if listing.complete:
        listed = listing.by_id()
        plan.removed = [(file_id, record) for file_id, record in manifest.items() if file_id not in listed]
    return plan


# ---------------------------------------------------------------------------
# Content manifests (remote loaders)
# ---------------------------------------------------------------------------


def content_hash(texts: Sequence[str], metadata: Sequence[Dict[str, Any]]) -> str:
    """A hash of what a file contributes to the index: its documents' text and metadata.

    Args:
        texts: The file's document texts, in order.
        metadata: Their metadata.

    Returns:
        A hex digest.
    """
    digest = hashlib.sha256()
    for text, meta in zip(texts, metadata):
        digest.update(json.dumps([text, meta], sort_keys=True, default=str).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


@dataclass
class ContentPlan:
    """What a remote sync must change, by file path."""

    added: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.removed)


def plan_content_sync(manifest: Dict[str, Dict[str, Any]], hashes: Dict[str, str]) -> ContentPlan:
    """Diff a content manifest against the files as loaded now.

    Args:
        manifest: ``{path: {"sha256": ...}}`` of the indexed files.
        hashes: ``{path: sha256}`` of the files now.

    Returns:
        The plan; a file recorded without a hash counts as changed.
    """
    plan = ContentPlan()
    for path, digest in hashes.items():
        record = manifest.get(path)
        if record is None:
            plan.added.append(path)
        elif not record.get("sha256") or record.get("sha256") != digest:
            plan.changed.append(path)
        else:
            plan.unchanged += 1
    plan.removed = [path for path in manifest if path not in hashes]
    return plan


# ---------------------------------------------------------------------------
# Directory structures
# ---------------------------------------------------------------------------


def _is_file_entry(node: Any) -> bool:
    return isinstance(node, dict) and "type" in node and "size_bytes" in node


def structure_files(structure: Any, prefix: str = "") -> Dict[str, dict]:
    """Every file entry of a ``directory_structure``, keyed by its path relative to the source.

    Args:
        structure: A ``directory_structure`` mapping, or a subtree of one.
        prefix: The path of ``structure`` itself.

    Returns:
        ``{"guide/a.md": {"type": ..., "size_bytes": ..., "sha256": ...}}``.
    """
    files: Dict[str, dict] = {}
    if not isinstance(structure, dict):
        return files
    for name, node in structure.items():
        path = os.path.join(prefix, name) if prefix else name
        if _is_file_entry(node):
            files[path] = node
        elif isinstance(node, dict):
            files.update(structure_files(node, path))
    return files


def structure_from_files(files: Dict[str, dict]) -> dict:
    """A nested ``directory_structure`` from ``{path: entry}``; the inverse of :func:`structure_files`.

    A path that runs through a file (``a`` a file, ``a/b`` wanted too) is left out.
    """
    root: dict = {}
    for path in sorted(files):
        parts = [part for part in path.split(os.sep) if part]
        if not parts:
            continue
        node: Optional[dict] = root
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict) or _is_file_entry(child):
                node = None
                break
            node = child
        if node is not None and parts[-1] not in node:
            node[parts[-1]] = dict(files[path])
    return root


# ---------------------------------------------------------------------------
# Chunk edits
# ---------------------------------------------------------------------------


def _metadata_of(chunk: Any) -> dict:
    meta = chunk.get("metadata") if isinstance(chunk, dict) else getattr(chunk, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _chunk_id(chunk: Any) -> Optional[str]:
    cid = chunk.get("doc_id") if isinstance(chunk, dict) else getattr(chunk, "doc_id", None)
    return str(cid) if cid is not None else None


def source_path_key(metadata: dict) -> str:
    """The path a chunk belongs to: its ``source`` (uploads and connectors)."""
    raw = metadata.get("source")
    return str(raw) if raw else ""


def chunk_ids_by_path(
    store: Any, paths: Iterable[str], key: Callable[[dict], str] = source_path_key,
) -> Dict[str, List[str]]:
    """The ids of the chunks at each of ``paths``, from one listing of the store.

    Args:
        store: The source's vector store.
        paths: The paths to look up.
        key: Reads a chunk's path from its metadata.

    Returns:
        ``{path: [chunk id, ...]}`` for the paths that have chunks.

    Raises:
        NotImplementedError: The store cannot list its chunks.
        Exception: Whatever listing the store raised.
    """
    wanted = {p for p in paths if p}
    if not wanted:
        return {}
    chunks = store.get_chunks()
    if chunks is None:
        raise NotImplementedError(f"{type(store).__name__} cannot list its chunks")
    found: Dict[str, List[str]] = {}
    for chunk in chunks:
        path = key(_metadata_of(chunk))
        cid = _chunk_id(chunk)
        if path in wanted and cid:
            found.setdefault(path, []).append(cid)
    return found


def _is_store(store: Any) -> bool:
    """Whether ``store`` is a real vector store (with batched writes), not a stand-in."""
    from docsgpt.vectorstore.base import BaseVectorStore

    return isinstance(store, BaseVectorStore)


def delete_chunk_ids(store: Any, ids_by_path: Dict[str, List[str]]) -> Tuple[int, Set[str]]:
    """Delete the given chunks; a store's batched delete when it has one.

    Args:
        store: The source's vector store.
        ids_by_path: ``{path: [chunk id, ...]}``.

    Returns:
        ``(deleted, paths with a chunk that could not be deleted)``.
    """
    deleted = 0
    undeleted: Set[str] = set()
    for path, ids in ids_by_path.items():
        if not ids:
            continue
        if _is_store(store):
            try:
                count = store.delete_chunks(ids)
            except Exception as err:  # noqa: BLE001 - reported per path
                logging.error(f"Failed deleting the chunks of {path}: {err}")
                undeleted.add(path)
                continue
            deleted += int(count or 0)
            if int(count or 0) < len(ids):
                undeleted.add(path)
            continue
        for cid in ids:
            try:
                store.delete_chunk(cid)
                deleted += 1
            except Exception as err:  # noqa: BLE001 - reported per path
                logging.error(f"Failed deleting chunk {cid}: {err}")
                undeleted.add(path)
    return deleted, undeleted


def add_chunks(store: Any, chunks: Sequence[Tuple[str, dict]], batch: int = ADD_BATCH_CHUNKS) -> int:
    """Add ``(text, metadata)`` chunks, in batches when the store writes batches.

    A store that saves its whole index on every write (FAISS) is written once
    per batch rather than once per chunk.

    Args:
        store: The source's vector store.
        chunks: The chunks.
        batch: Chunks per write.

    Returns:
        How many were added.

    Raises:
        Exception: Whatever adding raised; a batch either lands whole or not at all.
    """
    from docsgpt.parser.embedding_pipeline import sanitize_content
    from docsgpt.utils import strip_null_bytes

    added = 0
    if _is_store(store):
        for start in range(0, len(chunks), max(1, batch)):
            part = chunks[start:start + batch]
            store.add_chunks(
                [sanitize_content(text) for text, _ in part], [strip_null_bytes(dict(meta)) for _, meta in part],
            )
            added += len(part)
        return added
    for text, meta in chunks:
        store.add_chunk(text, metadata=meta)
        added += 1
    return added


def rewrite_chunk_paths(store: Any, moves: Dict[str, Tuple[List[str], Dict[str, Any]]]) -> int:
    """Point moved files' chunks at their new paths, without embedding them again where the store allows.

    Args:
        store: The source's vector store.
        moves: ``{old path: ([chunk id, ...], metadata changes)}``; ``None`` in the
            changes removes that key.

    Returns:
        How many chunks were rewritten.
    """
    wanted = {cid: changes for ids, changes in moves.values() for cid in ids}
    if not wanted:
        return 0
    chunks = store.get_chunks() or []
    updates: Dict[str, Tuple[str, dict]] = {}
    for chunk in chunks:
        cid = _chunk_id(chunk)
        if cid not in wanted:
            continue
        meta = dict(_metadata_of(chunk))
        for k, v in wanted[cid].items():
            if v is None:
                meta.pop(k, None)
            else:
                meta[k] = v
        text = chunk.get("text") if isinstance(chunk, dict) else getattr(chunk, "text", "")
        updates[cid] = (text or "", meta)
    rewrite = getattr(store, "update_chunks_metadata", None)
    if _is_store(store) and callable(rewrite):
        return int(rewrite({cid: meta for cid, (_, meta) in updates.items()}) or 0)
    count = 0
    for cid, (text, meta) in updates.items():
        store.update_chunk(cid, text, meta)
        count += 1
    return count
