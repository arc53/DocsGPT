import datetime
import hashlib
import io
import json
import logging
import mimetypes
import os
import shutil
import string
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

import uuid
from collections import Counter
from urllib.parse import urljoin, urlsplit

import requests

from docsgpt import tracing
from docsgpt.core.settings import settings
from docsgpt.events.publisher import publish_user_event
from docsgpt.parser.chunking_creator import ChunkerCreator
from docsgpt.parser.connectors.connector_creator import ConnectorCreator
from docsgpt.parser.embedding_pipeline import (
    assert_index_complete,
    embed_and_store_documents,
)
from docsgpt.parser.file.base_parser import NoTextLayerError
from docsgpt.parser.file.bulk import SimpleDirectoryReader, get_default_file_extractor
from docsgpt.parser.file.constants import SUPPORTED_SOURCE_EXTENSIONS, is_attachment_archive
from docsgpt.parser.file.image_parser import (
    VISION_CONVERTIBLE_MIME_TYPES,
    convert_image_to_png,
)
from docsgpt.parser.remote.github_loader import GitHubTokenRejected
from docsgpt.parser.remote.remote_creator import (
    RemoteCreator,
    normalize_remote_data,
)
from docsgpt.parser.schema.base import Document
from docsgpt.security.zip_archive import (
    extract_zip_safely,
    safe_zip_error_message,
    validate_zip_archive,
    ZipExtractionBudget,
    ZipExtractionError,
    ZipExtractionLimits,
)

from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.repositories.ingest_chunk_progress import (
    IngestChunkProgressRepository,
)
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.wiki_pages import (
    WikiPagesRepository,
    _content_hash,
    rebuild_wiki_directory_structure,
)
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.storage.db.source_config import SourceConfig
from docsgpt.storage.storage_creator import StorageCreator
from docsgpt.upload_limits import (
    enforce_parseable_attachment,
    UnsupportedUploadTypeError,
)
from docsgpt.utils import (
    count_tokens_docs,
    get_encoding,
    num_tokens_from_string,
    safe_filename,
    truncate_to_line_boundary,
)

# Constants


MIN_TOKENS = 150
MAX_TOKENS = 1250
# Attachment content stored for prompting is capped in tokens — the same
# unit the gate is expressed in — so a stored row can never exceed the cap.
ATTACHMENT_MAX_TOKENS = 100_000
RECURSION_DEPTH = 2
INGEST_HEARTBEAT_INTERVAL_SECONDS = 30


def count_structure_files(node: dict) -> int:
    """Count leaf files in a nested ``directory_structure`` mapping.

    Directories are plain dicts of children; files are dicts carrying a
    ``token_count`` key. ``len()`` on the root only sees top-level entries,
    which undercounts any repo with subdirectories.

    Args:
        node: A ``directory_structure`` mapping (or any subtree of one).

    Returns:
        Number of file leaves beneath ``node``.
    """
    if not isinstance(node, dict):
        return 0
    total = 0
    for value in node.values():
        if isinstance(value, dict):
            if "token_count" in value and "size_bytes" in value:
                total += 1
            else:
                total += count_structure_files(value)
    return total


def add_file_to_structure(
    directory_structure: dict,
    file_path: str,
    file_type: str,
    *,
    size_bytes: int,
    token_count: int,
) -> None:
    """Insert one chunk's stats into a nested ``directory_structure``.

    Callers feed this *chunks*, so a file larger than one chunk arrives
    several times. Stats are accumulated rather than overwritten — the
    previous assignment kept only the final fragment, which made the
    per-file sizes shown in the UI wrong for every multi-chunk file
    (a 2.56M-token repo reported 733k).

    Args:
        directory_structure: Mapping mutated in place.
        file_path: Repo-relative path, e.g. ``"guides/setup.md"``.
        file_type: MIME type recorded on first insert.
        size_bytes: Byte length of this chunk.
        token_count: Token count of this chunk.

    Returns:
        None
    """
    path_parts = [p for p in file_path.split("/") if p]
    if not path_parts:
        return
    current_level = directory_structure
    for part in path_parts[:-1]:
        # Intermediate parts are directories
        child = current_level.get(part)
        if not isinstance(child, dict) or "token_count" in child:
            child = {}
            current_level[part] = child
        current_level = child

    leaf = path_parts[-1]
    existing = current_level.get(leaf)
    if isinstance(existing, dict) and "token_count" in existing:
        existing["size_bytes"] += size_bytes
        existing["token_count"] += token_count
    else:
        current_level[leaf] = {
            "type": file_type,
            "size_bytes": size_bytes,
            "token_count": token_count,
        }


def graph_extraction_key(source_id, updated_at) -> str:
    """Build the extract_graph idempotency key for a source's current state.

    The key embeds ``updated_at`` (the trigger-maintained column) so it
    changes whenever re-extraction is warranted — a re-ingest or re-enable
    bumps ``updated_at`` and yields a fresh key, bypassing the 24h completed
    cache so the worker re-runs. Two enqueues for the same state share a key
    and dedupe. ``updated_at`` is stringified deterministically.
    """
    return f"extract-graph:{source_id}:{updated_at}"


def _source_updated_at(source) -> str:
    """Return the source's ``updated_at`` (falling back to ``date``) as a string."""
    if not source:
        return ""
    stamp = source.get("updated_at") or source.get("date")
    return str(stamp) if stamp is not None else ""


def _reset_graph_for_source(source_id) -> None:
    """Drop a source's existing graph so a re-enable/re-ingest rebuilds from scratch.

    Clears nodes, edges, node→chunk links and the ingest checkpoint. Run at the
    enqueue site (not inside the worker) so a broker redelivery of an interrupted
    build still resumes from its checkpoint rather than restarting from zero.
    """
    from docsgpt.graphrag.store import GraphStore

    GraphStore().delete_by_source(str(source_id))


def _publish_graph_event(user, source_id, event_type, payload) -> None:
    """Publish a graph-extraction SSE event, scoped to the source. Never raises."""
    if not user:
        return
    try:
        publish_user_event(
            user,
            event_type,
            payload,
            scope={"kind": "source", "id": str(source_id)},
        )
    except Exception as e:
        logging.debug(f"Failed to publish graph event {event_type}: {e}")


def _maybe_enqueue_graph_extraction(cfg, source_id, user):
    """Reset and re-enqueue graph extraction after embed for a graphrag source.

    The graph lights up asynchronously once chunks are embedded, so ClassicRAG
    works immediately. A no-op for non-graphrag sources or when GraphRAG is
    unavailable. The prior graph is cleared first so a re-ingest rebuilds rather
    than accumulating stale nodes. The work is isolated so a broker hiccup can
    never fail an otherwise-successful ingest.
    """
    if cfg.kind != "graphrag":
        return
    from docsgpt.graphrag import graphrag_available

    if not graphrag_available():
        return

    source_id = str(source_id)
    try:
        from docsgpt.api.user.tasks import extract_graph

        with db_readonly() as conn:
            source = SourcesRepository(conn).get_any(source_id, user)
        _reset_graph_for_source(source_id)
        key = graph_extraction_key(source_id, _source_updated_at(source))
        extract_graph.delay(source_id, user, idempotency_key=key)
    except Exception as e:
        logging.warning(
            f"Failed to enqueue graph extraction for {source_id}: {e}",
            exc_info=True,
        )

# Re-exported here for backward-compatible imports
# (``from docsgpt.worker import _derive_source_id`` /
# ``DOCSGPT_INGEST_NAMESPACE``) from tests and any other in-tree callers.
# New code should import from ``docsgpt.storage.db.source_ids``
# directly to avoid pulling this Celery worker module into the API
# process at import time.
from docsgpt.storage.db.source_ids import (  # noqa: E402, F401
    DOCSGPT_INGEST_NAMESPACE,
    derive_source_id as _derive_source_id,
)


def _ingest_heartbeat_loop(source_id, stop_event, interval=INGEST_HEARTBEAT_INTERVAL_SECONDS):
    """Bump ``ingest_chunk_progress.last_updated`` until ``stop_event`` is set."""
    while not stop_event.wait(interval):
        try:
            with db_session() as conn:
                IngestChunkProgressRepository(conn).bump_heartbeat(source_id)
        except Exception as e:
            logging.warning(
                f"Heartbeat failed for {source_id}: {e}", exc_info=True
            )


def _start_ingest_heartbeat(source_id):
    """Spawn the heartbeat daemon and return ``(thread, stop_event)``."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_ingest_heartbeat_loop,
        args=(str(source_id), stop_event),
        daemon=True,
        name=f"ingest-heartbeat-{source_id}",
    )
    thread.start()
    return thread, stop_event


def _stop_ingest_heartbeat(thread, stop_event):
    """Signal the heartbeat daemon to exit and wait briefly for it."""
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=5)


def _make_parse_progress_callback(task, user, source_id, start_pct, end_pct):
    """Build a ``load_data`` callback mapping parse progress to
    ``[start_pct, end_pct]`` via ``update_state`` + a throttled
    ``stage='parsing'`` SSE event.
    """
    span = end_pct - start_pct
    source_id_str = str(source_id)
    state = {"last_pct": -1}

    def _callback(files_done, total_files):
        if not total_files:
            return
        pct = start_pct + int((files_done / total_files) * span)
        task.update_state(
            state="PROGRESS",
            meta={"current": pct, "status": "Parsing files"},
        )
        if user and pct > state["last_pct"]:
            publish_user_event(
                user,
                "source.ingest.progress",
                {
                    "current": pct,
                    "total": total_files,
                    "files_done": files_done,
                    "stage": "parsing",
                },
                scope={"kind": "source", "id": source_id_str},
            )
            state["last_pct"] = pct

    return _callback


# Define a function to extract metadata from a given filename.


def metadata_from_filename(title):
    return {"title": title}


def _normalize_file_name_map(file_name_map):
    if not file_name_map:
        return {}
    if isinstance(file_name_map, str):
        try:
            file_name_map = json.loads(file_name_map)
        except Exception:
            return {}
    return file_name_map if isinstance(file_name_map, dict) else {}


def _get_display_name(file_name_map, rel_path):
    if not file_name_map or not rel_path:
        return None
    if rel_path in file_name_map:
        return file_name_map[rel_path]
    base_name = os.path.basename(rel_path)
    return file_name_map.get(base_name)


def _apply_display_names_to_structure(structure, file_name_map, prefix=""):
    if not isinstance(structure, dict) or not file_name_map:
        return structure
    for name, node in structure.items():
        if isinstance(node, dict) and "type" in node and "size_bytes" in node:
            rel_path = f"{prefix}/{name}" if prefix else name
            display_name = _get_display_name(file_name_map, rel_path)
            if display_name:
                node["display_name"] = display_name
        elif isinstance(node, dict):
            next_prefix = f"{prefix}/{name}" if prefix else name
            _apply_display_names_to_structure(node, file_name_map, next_prefix)
    return structure


def _download_source_files_to_dir(storage, source_file_path, temp_dir):
    """Mirror a source's stored files into ``temp_dir``, preserving structure."""
    if not storage.is_directory(source_file_path):
        return
    for storage_file_path in storage.list_files(source_file_path):
        if storage.is_directory(storage_file_path):
            continue
        rel_path = os.path.relpath(storage_file_path, source_file_path)
        local_file_path = os.path.join(temp_dir, rel_path)
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        try:
            file_data = storage.get_file(storage_file_path)
            with open(local_file_path, "wb") as f:
                f.write(file_data.read())
        except Exception as e:
            logging.error(f"Error downloading file {storage_file_path}: {e}")
            continue


# Define a function to generate a random string of a given length.


def generate_random_string(length):
    return "".join([string.ascii_letters[i % 52] for i in range(length)])


# Zip extraction security limits. Kept as module constants for backward
# compatibility with worker callers/tests; values come from operator settings.
MAX_UNCOMPRESSED_SIZE = settings.UPLOAD_MAX_ARCHIVE_BYTES
MAX_FILE_COUNT = settings.UPLOAD_MAX_ARCHIVE_FILES
MAX_COMPRESSION_RATIO = settings.UPLOAD_MAX_ARCHIVE_RATIO


def _is_path_safe(base_path: str, target_path: str) -> bool:
    """
    Check if target_path is safely within base_path (prevents zip slip attacks).

    Args:
        base_path: The base directory where extraction should occur.
        target_path: The full path where a file would be extracted.

    Returns:
        True if the path is safe, False otherwise.
    """
    # Resolve to absolute paths and check containment
    base_resolved = os.path.realpath(base_path)
    target_resolved = os.path.realpath(target_path)
    return target_resolved.startswith(base_resolved + os.sep) or target_resolved == base_resolved


def _validate_zip_safety(zip_path: str, extract_to: str) -> None:
    """
    Validate a zip file for security issues before extraction.

    Checks for:
    - Zip bombs (excessive compression ratio or uncompressed size)
    - Too many files
    - Path traversal attacks (zip slip)

    Args:
        zip_path: Path to the zip file.
        extract_to: Destination directory.

    Raises:
        ZipExtractionError: If the zip file fails security validation.
    """
    del extract_to  # Path checks are platform-independent inside the validator.
    validate_zip_archive(
        zip_path,
        ZipExtractionLimits(
            max_uncompressed_bytes=MAX_UNCOMPRESSED_SIZE,
            max_files=MAX_FILE_COUNT,
            max_compression_ratio=MAX_COMPRESSION_RATIO,
            max_member_bytes=settings.UPLOAD_MAX_FILE_BYTES,
            max_depth=RECURSION_DEPTH,
        ),
    )


def extract_zip_recursive(
    zip_path: str,
    extract_to: str,
    current_depth: int = 0,
    max_depth: int = 5,
    _budget: ZipExtractionBudget | None = None,
) -> None:
    """
    Recursively extract zip files with security protections.

    Security measures:
    - Limits recursion depth to prevent infinite loops
    - Validates uncompressed size to prevent zip bombs
    - Limits number of files to prevent resource exhaustion
    - Checks compression ratio to detect zip bombs
    - Validates paths to prevent zip slip attacks

    Args:
        zip_path (str): Path to the zip file to be extracted.
        extract_to (str): Destination path for extracted files.
        current_depth (int): Current depth of recursion.
        max_depth (int): Maximum allowed depth of recursion to prevent infinite loops.

    Raises:
        ZipExtractionError: If the archive fails safety validation, so ingestion
            fails loudly instead of indexing an empty directory.
    """
    if current_depth > max_depth:
        logging.warning(f"Reached maximum recursion depth of {max_depth}")
        return

    try:
        budget = _budget or ZipExtractionBudget()
        extract_zip_safely(
            zip_path,
            extract_to,
            ZipExtractionLimits(
                max_uncompressed_bytes=MAX_UNCOMPRESSED_SIZE,
                max_files=MAX_FILE_COUNT,
                max_compression_ratio=MAX_COMPRESSION_RATIO,
                max_member_bytes=settings.UPLOAD_MAX_FILE_BYTES,
                max_depth=max_depth - current_depth,
            ),
            budget,
        )
        os.remove(zip_path)  # Remove the zip file after extracting

    except ZipExtractionError as e:
        logging.error(
            "Zip security validation failed for %s: %s",
            safe_zip_error_message(zip_path),
            safe_zip_error_message(e),
        )
        # Remove the potentially malicious zip file
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise
    except Exception as e:
        logging.error(
            "Error extracting zip file %s: %s",
            safe_zip_error_message(zip_path),
            safe_zip_error_message(e),
            exc_info=True,
        )
        raise


def download_file(url, params, dest_path):
    try:
        response = requests.get(url, params=params, timeout=100)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(response.content)
    except requests.RequestException as e:
        logging.error(f"Error downloading file: {e}")
        raise


def _worker_api_url() -> str:
    """Where the worker reaches the API for its own calls: WORKER_API_URL, else API_URL.

    Returns:
        The base URL, without a path.
    """
    return settings.WORKER_API_URL or settings.API_URL


def upload_index(full_path, file_data):
    files = None
    try:
        headers = {}
        if settings.INTERNAL_KEY:
            headers["X-Internal-Key"] = settings.INTERNAL_KEY

        if settings.VECTOR_STORE == "faiss":
            faiss_path = full_path + "/index.faiss"
            pkl_path = full_path + "/index.pkl"

            if not os.path.exists(faiss_path):
                logging.error(f"FAISS index file not found: {faiss_path}")
                raise FileNotFoundError(f"FAISS index file not found: {faiss_path}")

            if not os.path.exists(pkl_path):
                logging.error(f"FAISS pickle file not found: {pkl_path}")
                raise FileNotFoundError(f"FAISS pickle file not found: {pkl_path}")

            files = {
                "file_faiss": open(faiss_path, "rb"),
                "file_pkl": open(pkl_path, "rb"),
            }
            response = requests.post(
                urljoin(_worker_api_url(), "/api/upload_index"),
                files=files,
                data=file_data,
                headers=headers,
                timeout=100,
            )
        else:
            response = requests.post(
                urljoin(_worker_api_url(), "/api/upload_index"),
                data=file_data,
                headers=headers,
                timeout=100,
            )
        response.raise_for_status()
    except (requests.RequestException, FileNotFoundError) as e:
        logging.error(f"Error uploading index: {e}")
        raise
    finally:
        if settings.VECTOR_STORE == "faiss" and files is not None:
            for file in files.values():
                file.close()


# Define the main function for ingesting and processing documents.


def ingest_worker(
    self,
    directory,
    formats,
    job_name,
    file_path,
    filename,
    user,
    retriever="classic",
    file_name_map=None,
    config=None,
    idempotency_key=None,
    source_id=None,
):
    """
    Ingest and process documents.

    Args:
        self: Reference to the instance of the task.
        directory (str): Specifies the directory for ingesting ('inputs' or 'temp').
        formats (list of str): List of file extensions to consider for ingestion (e.g., [".rst", ".md"]).
        job_name (str): Name of the job for this ingestion task (original, unsanitized).
        file_path (str): Complete file path to use consistently throughout the pipeline.
        filename (str): Original unsanitized filename provided by the user.
        user (str): Identifier for the user initiating the ingestion (original, unsanitized).
        retriever (str): Type of retriever to use for processing the documents.
        file_name_map (dict|str|None): Optional mapping of safe relative paths to original filenames.
        config (dict|None): Per-source ``SourceConfig`` dict. ``None``/``{}`` →
            classic defaults (byte-identical to prior behavior).
        idempotency_key (str|None): When provided, the ``source_id`` is derived
            deterministically from the key so a retried task reuses the same
            source row instead of duplicating it.
        source_id (str|None): UUID minted by the HTTP route and returned in
            its response. When supplied, the worker uses it verbatim so SSE
            envelopes carry the same id the frontend already has — required
            for non-idempotent uploads where the route can't predict
            ``_derive_source_id(idempotency_key)``.

    Returns:
        dict: Information about the completed ingestion task, including input parameters and a "limited" flag.
    """
    input_files = None
    recursive = True
    limit = None
    exclude = True
    sample = False

    storage = StorageCreator.get_storage()

    logging.info(f"Ingest path: {file_path}", extra={"user": user, "job": job_name})

    # Source id resolution order:
    #   1. Caller-supplied ``source_id`` (HTTP route minted + returned to
    #      the frontend) — keeps the route response and the SSE event
    #      payloads in lockstep on the non-idempotent path.
    #   2. Deterministic uuid5 from ``idempotency_key`` — retried tasks
    #      reuse the original source row instead of duplicating it.
    #   3. Fresh uuid4 (caller has neither) — opaque, single-shot only.
    if source_id:
        source_uuid = uuid.UUID(source_id)
    else:
        source_uuid = _derive_source_id(idempotency_key)
    source_id_for_events = str(source_uuid)
    # Only emit ``queued`` on the original attempt. Celery retries re-run
    # the body, and re-publishing here would oscillate the toast through
    # ``queued`` again between ``failed`` and ``completed``.
    if self.request.retries == 0:
        publish_user_event(
            user,
            "source.ingest.queued",
            {
                "job_name": job_name,
                "filename": filename,
                "source_id": source_id_for_events,
                "operation": "upload",
            },
            scope={"kind": "source", "id": source_id_for_events},
        )

    # Wrap the entire body in try/except so a failure between the
    # ``queued`` publish above and the inner work (e.g. tempdir
    # creation, OS-level resource exhaustion) still emits a terminal
    # ``failed`` event rather than leaving the toast wedged on
    # 'training' until the polling fallback rescues it 30s later.
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(temp_dir, exist_ok=True)

            if storage.is_directory(file_path):
                # Handle directory case
                logging.info(f"Processing directory: {file_path}")
                files_list = storage.list_files(file_path)

                for storage_file_path in files_list:
                    if storage.is_directory(storage_file_path):
                        continue

                    # Create relative path structure in temp directory
                    rel_path = os.path.relpath(storage_file_path, file_path)
                    local_file_path = os.path.join(temp_dir, rel_path)

                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

                    # Download file
                    try:
                        file_data = storage.get_file(storage_file_path)
                        with open(local_file_path, "wb") as f:
                            f.write(file_data.read())
                    except Exception as e:
                        logging.error(
                            f"Error downloading file {storage_file_path}: {e}"
                        )
                        continue
            else:
                # Handle single file case
                temp_filename = os.path.basename(file_path)
                temp_file_path = os.path.join(temp_dir, temp_filename)

                file_data = storage.get_file(file_path)
                with open(temp_file_path, "wb") as f:
                    f.write(file_data.read())

                # Handle zip files
                if temp_filename.lower().endswith(".zip"):
                    logging.info(f"Extracting zip file: {temp_filename}")
                    extract_zip_recursive(
                        temp_file_path,
                        temp_dir,
                        current_depth=0,
                        max_depth=RECURSION_DEPTH,
                    )

            self.update_state(state="PROGRESS", meta={"current": 1})
            if sample:
                logging.info(f"Sample mode enabled. Using {limit} documents.")
            reader = SimpleDirectoryReader(
                input_dir=temp_dir,
                input_files=input_files,
                recursive=recursive,
                required_exts=formats,
                exclude_hidden=exclude,
                file_metadata=metadata_from_filename,
            )
            # Parsing/OCR owns 1-50% of the bar; embedding takes 50-100%.
            raw_docs = reader.load_data(
                progress_callback=_make_parse_progress_callback(
                    self, user, source_uuid, start_pct=1, end_pct=50,
                )
            )

            directory_structure = getattr(reader, "directory_structure", {})
            logging.info(f"Directory structure from reader: {directory_structure}")
            file_name_map = _normalize_file_name_map(file_name_map)
            if file_name_map:
                for doc in raw_docs:
                    extra_info = getattr(doc, "extra_info", None)
                    if not isinstance(extra_info, dict):
                        continue
                    rel_path = extra_info.get("source") or extra_info.get("file_path")
                    display_name = _get_display_name(file_name_map, rel_path)
                    if display_name:
                        display_name = str(display_name)
                        extra_info["filename"] = display_name
                        extra_info["file_name"] = display_name
                        extra_info["title"] = display_name
                directory_structure = _apply_display_names_to_structure(
                    directory_structure, file_name_map
                )

            cfg = SourceConfig.parse(config)
            chunker = ChunkerCreator.create_chunker(
                cfg.chunking.strategy,
                chunking_strategy=cfg.chunking.strategy,
                max_tokens=cfg.chunking.max_tokens,
                min_tokens=cfg.chunking.min_tokens,
                duplicate_headers=cfg.chunking.duplicate_headers,
            )
            raw_docs = chunker.chunk(documents=raw_docs)

            docs = [Document.to_vector_format(raw_doc) for raw_doc in raw_docs]

            vector_store_path = os.path.join(temp_dir, "vector_store")
            os.makedirs(vector_store_path, exist_ok=True)

            heartbeat_thread, heartbeat_stop = _start_ingest_heartbeat(source_uuid)
            try:
                embed_and_store_documents(
                    docs, vector_store_path, source_uuid, self,
                    attempt_id=getattr(self.request, "id", None),
                    user_id=user,
                    progress_start=50, progress_end=100,
                )
            finally:
                _stop_ingest_heartbeat(heartbeat_thread, heartbeat_stop)
            # Defense-in-depth: chunk-progress is the authoritative
            # record of how many chunks landed; mismatch raises so the
            # task fails loud rather than caching a partial index.
            assert_index_complete(source_uuid)

            tokens = count_tokens_docs(docs)

            self.update_state(state="PROGRESS", meta={"current": 100})

            if sample:
                for i in range(min(5, len(raw_docs))):
                    logging.info(f"Sample document {i}: {raw_docs[i]}")
            file_data = {
                "name": job_name,
                "file": filename,
                "user": user,
                "tokens": tokens,
                "retriever": retriever,
                "id": source_id_for_events,
                "type": "local",
                "file_path": file_path,
                "directory_structure": json.dumps(directory_structure),
            }
            if file_name_map:
                file_data["file_name_map"] = json.dumps(file_name_map)
            if config:
                file_data["config"] = json.dumps(config)

            upload_index(vector_store_path, file_data)
            publish_user_event(
                user,
                "source.ingest.completed",
                {
                    "source_id": source_id_for_events,
                    "filename": filename,
                    "tokens": tokens,
                    "operation": "upload",
                    # Forward-looking contract: ``limited`` is always
                    # ``False`` today but is carried on the wire so a
                    # future token-cap detection path can flip it and
                    # the frontend slice / UploadToast already react.
                    "limited": False,
                },
                scope={"kind": "source", "id": source_id_for_events},
            )
            _maybe_enqueue_graph_extraction(cfg, source_id_for_events, user)
    except Exception as e:
        logging.error(f"Error in ingest_worker: {e}", exc_info=True)
        publish_user_event(
            user,
            "source.ingest.failed",
            {
                "source_id": source_id_for_events,
                "filename": filename,
                "operation": "upload",
                "error": str(e)[:1024],
            },
            scope={"kind": "source", "id": source_id_for_events},
        )
        raise
    return {
        "directory": directory,
        "formats": formats,
        "name_job": job_name,  # Use original job_name
        "filename": filename,
        "user": user,  # Use original user
        "limited": False,
    }


def reingest_source_worker(self, source_id, user):
    """
    Re-ingestion worker that handles incremental updates by:
    1. Adding chunks from newly added files
    2. Removing chunks from deleted files

    Args:
        self: Task instance
        source_id: ID of the source to re-ingest
        user: User identifier

    Returns:
        dict: Information about the re-ingestion task

    Note:
        Reingest does its own ``vector_store.add_chunk`` work rather
        than going through ``embed_and_store_documents`` so it does
        *not* emit per-percent SSE progress events — only ``queued``,
        ``completed`` (carrying ``chunks_added`` / ``chunks_deleted``),
        or ``failed``. v1 limitation; revisit if reingest gains a
        progress-driven UI.
    """
    # Declared at the function scope so the outer except can include
    # ``name`` in the failed event payload when the failure happens
    # after the source lookup. Empty string until the lookup succeeds.
    source_name = ""
    # Tracks inner-block failures so a ``completed`` event reflects
    # partial-success accurately rather than masking it.
    inner_warnings: list[str] = []

    try:
        from docsgpt.vectorstore.vector_creator import VectorCreator

        self.update_state(
            state="PROGRESS",
            meta={"current": 10, "status": "Initializing re-ingestion scan"},
        )

        with db_readonly() as conn:
            source = SourcesRepository(conn).get_any(source_id, user)
        if not source:
            raise ValueError(f"Source {source_id} not found or access denied")
        source_id = str(source["id"])
        source_name = source.get("name") or ""
        # Re-chunk with the source's persisted config (classic defaults
        # when absent/empty), keeping reingest consistent with ingest.
        cfg = SourceConfig.parse(source.get("config"))

        # Publish ``queued`` *after* canonicalising ``source_id`` so the
        # event references the same id as the source row. Trade-off
        # documented: a Celery-backend or PG-lookup hiccup before this
        # publish means the toast may see only a ``failed`` event with
        # no preceding ``queued`` — acceptable for v1 since both
        # conditions also imply broader system trouble. Gate on first
        # attempt only so Celery retries don't re-emit ``queued`` after
        # a prior attempt already published ``failed``.
        if self.request.retries == 0:
            publish_user_event(
                user,
                "source.ingest.queued",
                {
                    "source_id": source_id,
                    "name": source_name,
                    # ``filename`` labels the upload toast on auto-create.
                    "filename": source_name,
                    "operation": "reingest",
                },
                scope={"kind": "source", "id": source_id},
            )

        storage = StorageCreator.get_storage()
        source_file_path = source.get("file_path", "")
        file_name_map = _normalize_file_name_map(source.get("file_name_map"))

        self.update_state(
            state="PROGRESS", meta={"current": 20, "status": "Scanning current files"}
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _download_source_files_to_dir(storage, source_file_path, temp_dir)

            reader = SimpleDirectoryReader(
                input_dir=temp_dir,
                recursive=True,
                required_exts=list(SUPPORTED_SOURCE_EXTENSIONS),
                exclude_hidden=True,
                file_metadata=metadata_from_filename,
            )
            reader.load_data()
            directory_structure = reader.directory_structure
            logging.info(
                f"Directory structure built with token counts: {directory_structure}"
            )

            try:
                old_directory_structure = source.get("directory_structure") or {}
                if isinstance(old_directory_structure, str):
                    try:
                        old_directory_structure = json.loads(old_directory_structure)
                    except Exception:
                        old_directory_structure = {}

                def _flatten_directory_structure(struct, prefix=""):
                    files = set()
                    if isinstance(struct, dict):
                        for name, meta in struct.items():
                            current_path = (
                                os.path.join(prefix, name) if prefix else name
                            )
                            if isinstance(meta, dict) and (
                                "type" in meta and "size_bytes" in meta
                            ):
                                files.add(current_path)
                            elif isinstance(meta, dict):
                                files |= _flatten_directory_structure(
                                    meta, current_path
                                )
                    return files

                old_files = _flatten_directory_structure(old_directory_structure)
                new_files = _flatten_directory_structure(directory_structure)

                added_files = sorted(new_files - old_files)
                removed_files = sorted(old_files - new_files)

                if added_files:
                    logging.info(f"Files added since last ingest: {added_files}")
                else:
                    logging.info("No files added since last ingest.")

                if removed_files:
                    logging.info(f"Files removed since last ingest: {removed_files}")
                else:
                    logging.info("No files removed since last ingest.")

            except Exception as e:
                logging.error(
                    f"Error comparing directory structures: {e}", exc_info=True
                )
                added_files = []
                removed_files = []
            try:
                if not added_files and not removed_files:
                    logging.info("No changes detected.")
                    publish_user_event(
                        user,
                        "source.ingest.completed",
                        {
                            "source_id": source_id,
                            "name": source_name,
                            "filename": source_name,
                            "operation": "reingest",
                            "no_changes": True,
                            "chunks_added": 0,
                            "chunks_deleted": 0,
                        },
                        scope={"kind": "source", "id": source_id},
                    )
                    return {
                        "source_id": source_id,
                        "user": user,
                        "status": "no_changes",
                        "added_files": [],
                        "removed_files": [],
                    }

                vector_store = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE,
                    source_id,
                    settings.EMBEDDINGS_KEY,
                )

                self.update_state(
                    state="PROGRESS",
                    meta={"current": 40, "status": "Processing file changes"},
                )

                # 1) Delete chunks from removed files
                deleted = 0
                if removed_files:
                    try:
                        for ch in vector_store.get_chunks() or []:
                            metadata = (
                                ch.get("metadata", {})
                                if isinstance(ch, dict)
                                else getattr(ch, "metadata", {})
                            )
                            raw_source = metadata.get("source")

                            source_file = str(raw_source) if raw_source else ""

                            if source_file in removed_files:
                                cid = ch.get("doc_id")
                                if cid:
                                    try:
                                        vector_store.delete_chunk(cid)
                                        deleted += 1
                                    except Exception as de:
                                        logging.error(
                                            f"Failed deleting chunk {cid}: {de}"
                                        )
                        logging.info(
                            f"Deleted {deleted} chunks from {len(removed_files)} removed files"
                        )
                    except Exception as e:
                        logging.error(
                            f"Error during deletion of removed file chunks: {e}",
                            exc_info=True,
                        )
                        inner_warnings.append(
                            f"deletion failed: {str(e)[:200]}"
                        )

                # 2) Add chunks from new files
                added = 0
                if added_files:
                    try:
                        # Build list of local files for added files only
                        added_local_files = []
                        for rel_path in added_files:
                            local_path = os.path.join(temp_dir, rel_path)
                            if os.path.isfile(local_path):
                                added_local_files.append(local_path)

                        if added_local_files:
                            reader_new = SimpleDirectoryReader(
                                input_files=added_local_files,
                                exclude_hidden=True,
                                errors="ignore",
                                file_metadata=metadata_from_filename,
                            )
                            raw_docs_new = reader_new.load_data()
                            chunker_new = ChunkerCreator.create_chunker(
                                cfg.chunking.strategy,
                                chunking_strategy=cfg.chunking.strategy,
                                max_tokens=cfg.chunking.max_tokens,
                                min_tokens=cfg.chunking.min_tokens,
                                duplicate_headers=cfg.chunking.duplicate_headers,
                            )
                            chunked_new = chunker_new.chunk(documents=raw_docs_new)

                            for (
                                file_path,
                                token_count,
                            ) in reader_new.file_token_counts.items():
                                try:
                                    rel_path = os.path.relpath(
                                        file_path, start=temp_dir
                                    )
                                    path_parts = rel_path.split(os.sep)
                                    current_dir = directory_structure

                                    for part in path_parts[:-1]:
                                        if part in current_dir and isinstance(
                                            current_dir[part], dict
                                        ):
                                            current_dir = current_dir[part]
                                        else:
                                            break

                                    filename = path_parts[-1]
                                    if filename in current_dir and isinstance(
                                        current_dir[filename], dict
                                    ):
                                        current_dir[filename][
                                            "token_count"
                                        ] = token_count
                                        logging.info(
                                            f"Updated token count for {rel_path}: {token_count}"
                                        )
                                except Exception as e:
                                    logging.warning(
                                        f"Could not update token count for {file_path}: {e}"
                                    )

                            for d in chunked_new:
                                meta = dict(d.extra_info or {})
                                try:
                                    raw_src = meta.get("source")
                                    if isinstance(raw_src, str) and os.path.isabs(
                                        raw_src
                                    ):
                                        meta["source"] = os.path.relpath(
                                            raw_src, start=temp_dir
                                        )
                                except Exception:
                                    pass
                                display_name = _get_display_name(
                                    file_name_map, meta.get("source")
                                )
                                if display_name:
                                    display_name = str(display_name)
                                    meta["filename"] = display_name
                                    meta["file_name"] = display_name
                                    meta["title"] = display_name

                                vector_store.add_chunk(d.text, metadata=meta)
                                added += 1
                            logging.info(
                                f"Added {added} chunks from {len(added_files)} new files"
                            )
                    except Exception as e:
                        logging.error(
                            f"Error during ingestion of new files: {e}", exc_info=True
                        )
                        inner_warnings.append(
                            f"add failed: {str(e)[:200]}"
                        )

                # 3) Update source directory structure timestamp
                try:
                    total_tokens = sum(reader.file_token_counts.values())
                    directory_structure = _apply_display_names_to_structure(
                        directory_structure, file_name_map
                    )

                    now = datetime.datetime.now(datetime.timezone.utc)
                    with db_session() as conn:
                        SourcesRepository(conn).update(
                            source_id, user,
                            {
                                "directory_structure": directory_structure,
                                "date": now,
                                "tokens": total_tokens,
                            },
                        )
                except Exception as e:
                    logging.error(
                        f"Error updating directory_structure in DB: {e}", exc_info=True
                    )

                self.update_state(
                    state="PROGRESS",
                    meta={"current": 100, "status": "Re-ingestion completed"},
                )

                completed_payload: dict = {
                    "source_id": source_id,
                    "name": source_name,
                    "filename": source_name,
                    "operation": "reingest",
                    "chunks_added": added,
                    "chunks_deleted": deleted,
                    "tokens": int(total_tokens) if "total_tokens" in locals() else 0,
                }
                if inner_warnings:
                    # Surface the per-block failures so the toast can warn
                    # rather than claim a clean success.
                    completed_payload["warnings"] = inner_warnings
                publish_user_event(
                    user,
                    "source.ingest.completed",
                    completed_payload,
                    scope={"kind": "source", "id": source_id},
                )
                _maybe_enqueue_graph_extraction(cfg, source_id, user)

                return {
                    "source_id": source_id,
                    "user": user,
                    "status": "completed",
                    "added_files": added_files,
                    "removed_files": removed_files,
                    "chunks_added": added,
                    "chunks_deleted": deleted,
                }
            except Exception as e:
                logging.error(
                    f"Error while processing file changes: {e}", exc_info=True
                )
                raise

    except Exception as e:
        logging.error(f"Error in reingest_source_worker: {e}", exc_info=True)
        publish_user_event(
            user,
            "source.ingest.failed",
            {
                "source_id": str(source_id),
                "name": source_name,
                "filename": source_name,
                "operation": "reingest",
                "error": str(e)[:1024],
            },
            scope={"kind": "source", "id": str(source_id)},
        )
        raise


def remote_worker(
    self,
    source_data,
    name_job,
    user,
    loader,
    directory="temp",
    retriever="classic",
    sync_frequency="never",
    operation_mode="upload",
    doc_id=None,
    config=None,
    idempotency_key=None,
    source_id=None,
    connection_id=None,
):
    safe_user = safe_filename(user)
    full_path = os.path.join(directory, safe_user, uuid.uuid4().hex)
    os.makedirs(full_path, exist_ok=True)

    # Source id resolution order matches ``ingest_worker``:
    #   1. ``operation_mode == "sync"`` reuses the existing source's ``doc_id``.
    #   2. Caller-supplied ``source_id`` (the HTTP route minted it and
    #      already returned it to the frontend) — keeps the route
    #      response and the SSE event payloads in lockstep on the
    #      no-idempotency-key path.
    #   3. Deterministic uuid5 from ``idempotency_key`` — retried tasks
    #      reuse the original source row instead of duplicating it.
    #   4. Fresh uuid4 — opaque, single-shot only.
    if operation_mode == "sync" and doc_id:
        source_uuid = str(doc_id)
    elif source_id:
        source_uuid = uuid.UUID(source_id)
    else:
        source_uuid = _derive_source_id(idempotency_key)
    source_id_for_events = str(source_uuid)

    # Emit the queued event before any work that could fail (including
    # ``update_state``) so the toast UI always sees a queued envelope
    # before any subsequent failed event. Gated on first attempt so
    # Celery retries don't re-emit ``queued`` after a prior ``failed``.
    if self.request.retries == 0:
        publish_user_event(
            user,
            "source.ingest.queued",
            {
                "source_id": source_id_for_events,
                "job_name": name_job,
                "loader": loader,
                "operation": operation_mode,
            },
            scope={"kind": "source", "id": source_id_for_events},
        )

    # Wrap ``update_state`` plus the entire body so any pre-loader
    # failure (Celery backend down, OS resource issue) still emits a
    # terminal ``failed`` event rather than wedging the toast.
    try:
        self.update_state(state="PROGRESS", meta={"current": 1})
        logging.info("Initializing remote loader with type: %s", loader)
        remote_loader = RemoteCreator.create_loader(loader)
        loader_input = source_data
        if connection_id:
            loader_input = _with_connection_credentials(source_data, connection_id)
            if loader_input is None:
                from docsgpt.connectors.service import ConnectionUnavailable

                raise ConnectionUnavailable("Reconnect to continue", connection_id=str(connection_id))
        try:
            raw_docs = remote_loader.load_data(loader_input)
        except GitHubTokenRejected as exc:
            # A revoked token pauses the connection's sources until the
            # owner reconnects, instead of failing on every schedule.
            from docsgpt.connectors import service as connection_service

            if not connection_id:
                raise
            connection_service.mark_reconnect_needed(str(connection_id), str(exc))
            raise connection_service.ConnectionUnavailable(
                str(exc), connection_id=str(connection_id),
            ) from exc

        cfg = SourceConfig.parse(config)
        chunker = ChunkerCreator.create_chunker(
            cfg.chunking.strategy,
            chunking_strategy=cfg.chunking.strategy,
            max_tokens=cfg.chunking.max_tokens,
            min_tokens=cfg.chunking.min_tokens,
            duplicate_headers=cfg.chunking.duplicate_headers,
        )
        raw_docs = chunker.chunk(documents=raw_docs)
        docs = [Document.to_vector_format(raw_doc) for raw_doc in raw_docs]
        tokens = count_tokens_docs(docs)
        logging.info("Total tokens calculated: %d", tokens)

        # Build directory structure from loaded documents
        # Format matches local file uploads: nested structure with type, size_bytes, token_count
        directory_structure = {}
        for doc in raw_docs:
            # Get the file path from extra_info
            # For crawlers: file_path is a virtual path like "guides/setup.md"
            # For other remotes: use key or title as fallback
            file_path = ""
            if doc.extra_info:
                file_path = (
                    doc.extra_info.get("file_path", "")
                    or doc.extra_info.get("key", "")
                    or doc.extra_info.get("title", "")
                )
            if not file_path:
                file_path = doc.doc_id or ""

            if file_path:
                # Calculate token count
                token_count = num_tokens_from_string(doc.text) if doc.text else 0

                # Estimate size in bytes from text content
                size_bytes = len(doc.text.encode("utf-8")) if doc.text else 0

                # Guess mime type from extension
                file_name = (
                    file_path.split("/")[-1] if "/" in file_path else file_path
                )
                ext = os.path.splitext(file_name)[1].lower()
                mime_types = {
                    ".txt": "text/plain",
                    ".md": "text/markdown",
                    ".pdf": "application/pdf",
                    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ".doc": "application/msword",
                    ".html": "text/html",
                    ".json": "application/json",
                    ".csv": "text/csv",
                    ".xml": "application/xml",
                    ".py": "text/x-python",
                    ".js": "text/javascript",
                    ".ts": "text/typescript",
                    ".jsx": "text/jsx",
                    ".tsx": "text/tsx",
                }
                file_type = mime_types.get(ext, "application/octet-stream")

                # Build nested directory structure from path
                # e.g., "guides/setup.md" -> {"guides": {"setup.md": {...}}}
                add_file_to_structure(
                    directory_structure, file_path, file_type,
                    size_bytes=size_bytes, token_count=token_count,
                )

        # ``len(directory_structure)`` counts only top-level entries, so a
        # 1,474-file repo logged "44 files". Count the leaves instead — this
        # line is the operational signal that a remote ingest succeeded.
        logging.info(
            f"Built directory structure with "
            f"{count_structure_files(directory_structure)} files across "
            f"{len(directory_structure)} top-level entries: "
            f"{list(directory_structure.keys())}"
        )

        if operation_mode == "upload":
            embed_and_store_documents(
                docs, full_path, source_uuid, self,
                attempt_id=getattr(self.request, "id", None),
                user_id=user,
            )
            assert_index_complete(source_uuid)
        elif operation_mode == "sync":
            if not doc_id:
                logging.error("Invalid doc_id provided for sync operation: %s", doc_id)
                raise ValueError("doc_id must be provided for sync operation.")
            embed_and_store_documents(
                docs, full_path, source_uuid, self,
                attempt_id=getattr(self.request, "id", None),
                user_id=user,
            )
            assert_index_complete(source_uuid)
        self.update_state(state="PROGRESS", meta={"current": 100})

        # Serialize remote_data as JSON if it's a dict (for S3, Reddit, etc.)
        remote_data_serialized = (
            json.dumps(source_data) if isinstance(source_data, dict) else source_data
        )
        file_data = {
            "name": name_job,
            "user": user,
            "tokens": tokens,
            "retriever": retriever,
            "id": source_id_for_events,
            "type": loader,
            "remote_data": remote_data_serialized,
            "sync_frequency": sync_frequency,
            "directory_structure": json.dumps(directory_structure),
        }
        if config:
            file_data["config"] = json.dumps(config)

        if operation_mode == "sync":
            last_sync_now = datetime.datetime.now(datetime.timezone.utc)
            file_data["last_sync"] = last_sync_now

            try:
                with db_session() as conn:
                    repo = SourcesRepository(conn)
                    src = repo.get_any(source_id_for_events, user)
                    if src is not None:
                        repo.update(str(src["id"]), user, {"date": last_sync_now})
            except Exception as upd_err:
                logging.warning(
                    f"Failed to update last_sync for source {source_id_for_events}: {upd_err}"
                )
        upload_index(full_path, file_data)
        if connection_id:
            _link_source_to_connection(source_id_for_events, str(connection_id))
        publish_user_event(
            user,
            "source.ingest.completed",
            {
                "source_id": source_id_for_events,
                "job_name": name_job,
                "loader": loader,
                "operation": operation_mode,
                "tokens": tokens,
                # Forward-looking contract: see ingest_worker.
                "limited": False,
            },
            scope={"kind": "source", "id": source_id_for_events},
        )
        _maybe_enqueue_graph_extraction(cfg, source_id_for_events, user)
    except Exception as e:
        logging.error("Error in remote_worker task: %s", str(e), exc_info=True)
        publish_user_event(
            user,
            "source.ingest.failed",
            {
                "source_id": source_id_for_events,
                "job_name": name_job,
                "loader": loader,
                "operation": operation_mode,
                "error": str(e)[:1024],
            },
            scope={"kind": "source", "id": source_id_for_events},
        )
        raise
    finally:
        if os.path.exists(full_path):
            shutil.rmtree(full_path)
    logging.info("remote_worker task completed successfully")
    return {
        "id": source_id_for_events,
        "urls": source_data,
        "name_job": name_job,
        "user": user,
        "limited": False,
    }


def sync(
    self,
    source_data,
    name_job,
    user,
    loader,
    sync_frequency,
    retriever,
    doc_id=None,
    directory="temp",
    connection_id=None,
):
    try:
        remote_worker(
            self,
            source_data,
            name_job,
            user,
            loader,
            directory,
            retriever,
            sync_frequency,
            "sync",
            doc_id,
            connection_id=connection_id,
        )
    except Exception as e:
        logging.error(f"Error during sync: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    return {"status": "success"}


# Remote loaders that can only read with a connection (no public fallback).
_CONNECTION_ONLY_LOADERS = frozenset({"linear"})


def sync_worker(self, frequency):
    from sqlalchemy import text as sql_text

    sync_counts = Counter()
    with db_readonly() as conn:
        result = conn.execute(
            sql_text(
                "SELECT id, name, user_id, type, remote_data, retriever, connection_id, metadata "
                "FROM sources WHERE sync_frequency = :freq"
            ),
            {"freq": frequency},
        )
        rows = result.fetchall()

    for row in rows:
        doc = dict(row._mapping)
        name = doc.get("name")
        user = doc.get("user_id")
        source_type = doc.get("type")
        retriever = doc.get("retriever")
        doc_id = str(doc.get("id"))

        sync_counts["total_sync_count"] += 1

        # Connector sources sync from their connection, whose token the
        # worker can refresh. Legacy ones with no connection still need the
        # browser, so they are skipped as before.
        if source_type and source_type.startswith("connector"):
            if doc.get("connection_id"):
                from docsgpt.api.user.tasks import sync_connector_source as sync_task

                sync_task.delay(doc_id)
                sync_counts["sync_dispatched"] += 1
            else:
                sync_counts["sync_skipped"] += 1
            continue

        metadata = doc.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                metadata = {}
        if (
            doc.get("connection_id")
            and isinstance(metadata, dict)
            and metadata.get("sync_state") == "paused_reconnect"
        ):
            # An S3 or GitHub source whose connection needs reconnecting:
            # it resumes when the owner reconnects, rather than failing (and
            # notifying) on every schedule until then.
            sync_counts["sync_skipped"] += 1
            continue
        if source_type in _CONNECTION_ONLY_LOADERS and not doc.get("connection_id"):
            # Linear is read only with a connection's sign-in; its
            # connection was removed and the content kept.
            sync_counts["sync_skipped"] += 1
            continue

        source_data = normalize_remote_data(source_type, doc.get("remote_data"))
        if not source_data:
            # No syncable URL/config — skip instead of dispatching a sync
            # that can only fail (and emit a spurious failed event).
            sync_counts["sync_skipped"] += 1
            continue

        resp = sync(
            self, source_data, name, user, source_type, frequency, retriever, doc_id,
            connection_id=str(doc["connection_id"]) if doc.get("connection_id") else None,
        )
        sync_counts[
            "sync_success" if resp["status"] == "success" else "sync_failure"
        ] += 1
    return {
        key: sync_counts[key]
        for key in [
            "total_sync_count", "sync_success", "sync_failure", "sync_skipped", "sync_dispatched",
        ]
    }


# Line-oriented text formats that stay parseable after a head-truncation.
# Structured/binary formats (pdf, docx, xlsx, json, html, ...) are excluded —
# cutting them mid-stream would break their parsers entirely.
_TRUNCATABLE_ATTACHMENT_SUFFIXES = {
    ".csv",
    ".tsv",
    ".txt",
    ".log",
    ".md",
    ".mdx",
    ".rst",
    ".jsonl",
}


class AttachmentRejectedError(Exception):
    """A deterministic reason an attachment must not be parsed (e.g. zip bomb).

    Raised before parsing and marked non-retryable on the Celery task so a
    poison upload fails once instead of retrying identically.
    """


def _reject_unparseable_attachment(
    local_path: str, filename: str, parser_extensions
) -> None:
    """Reject an attachment with no parser whose contents are binary.

    Defence in depth behind the route's gate, and stricter than it: this runs
    against the parser table actually loaded, so a suffix the route trusted
    (.webp with docling absent, say) is still refused rather than opened as
    plain text by ``SimpleDirectoryReader`` and stored as garbage.

    Args:
        local_path: Filesystem path of the attachment about to be parsed.
        filename: The upload's original filename, which carries the suffix.
        parser_extensions: Suffixes the live ``file_extractor`` can parse.

    Raises:
        AttachmentRejectedError: If the file has no parser and is not text.
    """
    try:
        enforce_parseable_attachment(local_path, filename, parser_extensions)
    except UnsupportedUploadTypeError as exc:
        raise AttachmentRejectedError(str(exc)) from exc


def _reject_attachment_zip_bomb(local_path: str) -> None:
    """Reject a zip-container attachment that decompresses to too much.

    Applies the shared guard (``document_reader.reject_zip_bomb_path``) on the
    attachment path, which previously had no such check.

    Args:
        local_path: Filesystem path of the attachment about to be parsed.

    Raises:
        AttachmentRejectedError: If the archive exceeds the entry-count or
            inner-uncompressed-size caps.
    """
    from docsgpt.parser.document_reader import reject_zip_bomb_path

    reason = reject_zip_bomb_path(local_path)
    if reason is not None:
        raise AttachmentRejectedError(reason)


def _readable_without_text(filename: str) -> bool:
    """Whether a model can read an attachment from its original file alone.

    PDFs and images are sent to models as the file itself (a PDF as page
    images on image-only models); every other format needs extracted text.

    Args:
        filename: The upload's original filename.

    Returns:
        bool: True for PDFs and images.
    """
    mime_type = mimetypes.guess_type(filename)[0] or ""
    return mime_type == "application/pdf" or mime_type.startswith("image/")


def _attachment_fingerprint(local_path: str, filename: str) -> Dict[str, Any]:
    """Fingerprint an upload's original bytes while they are local.

    The chat budget planner dedupes re-sent files by ``content_hash`` and
    sizes native PDF parts by ``page_count``; both are only cheap here, where
    the bytes already sit on disk.

    Args:
        local_path: Path of the original upload.
        filename: The upload's original filename.

    Returns:
        Dict with ``content_hash`` (sha256 hex) and ``size`` (bytes), plus
        ``page_count`` for a PDF pypdfium2 can open. Empty when the file
        cannot be read; a fingerprint never fails the upload.
    """
    digest = hashlib.sha256()
    size = 0
    try:
        with open(local_path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
    except OSError:
        return {}
    fingerprint: Dict[str, Any] = {"content_hash": digest.hexdigest(), "size": size}
    if (mimetypes.guess_type(filename)[0] or "") == "application/pdf":
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(local_path)
            try:
                fingerprint["page_count"] = len(pdf)
            finally:
                pdf.close()
        except Exception:  # noqa: BLE001 - an unreadable PDF just has no page count
            pass
    return fingerprint


def _store_png_copy(storage, relative_path: str, mime_type: str) -> tuple[str, dict]:
    """Store a PNG copy, beside the original, of an image the providers reject.

    Args:
        storage: The storage backend holding the upload.
        relative_path: Storage path of the original image.
        mime_type: The original's mime type, e.g. ``image/tiff``.

    Returns:
        tuple[str, dict]: The PNG's storage path, and the conversion record
        kept in the attachment's metadata.

    Raises:
        DocumentParseError: If the image cannot be decoded.
    """
    with storage.get_file(relative_path) as source:
        png_bytes, frames = convert_image_to_png(source)
    png_path = f"{os.path.splitext(relative_path)[0]}.png"
    storage.save_file(io.BytesIO(png_bytes), png_path)
    return png_path, {"from": mime_type, "to": "image/png", "frames": frames}


def _bounded_attachment_copy(local_path: str) -> tuple[str, bool]:
    """Bound how much of a text attachment reaches the parser.

    Attachment content is capped at ~250k chars after parsing, so bytes past
    ``ATTACHMENT_TEXT_MAX_BYTES`` only cost parse time and memory. Oversized
    line-oriented text files are head-truncated on a line boundary into a
    temp copy; the stored original is never modified (local storage hands the
    canonical file path to ``process_file`` callbacks).

    Args:
        local_path: Filesystem path handed to the parse callback.

    Returns:
        Tuple of (path to parse, whether it is a temp copy the caller must
        delete).
    """
    max_bytes = settings.ATTACHMENT_TEXT_MAX_BYTES
    if max_bytes <= 0:
        return local_path, False
    suffix = os.path.splitext(local_path)[1].lower()
    if suffix not in _TRUNCATABLE_ATTACHMENT_SUFFIXES:
        return local_path, False
    try:
        if os.path.getsize(local_path) <= max_bytes:
            return local_path, False
        with open(local_path, "rb") as src:
            head = src.read(max_bytes)
    except OSError:
        return local_path, False
    head = truncate_to_line_boundary(head)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(head)
    logging.warning(
        f"Attachment {os.path.basename(local_path)} exceeds "
        f"ATTACHMENT_TEXT_MAX_BYTES ({max_bytes}); parsing first {len(head)} bytes"
    )
    return tmp.name, True


def _upsert_attachment_row(
    user,
    filename,
    relative_path,
    *,
    mime_type,
    content,
    token_count,
    metadata,
    attachment_id,
    size=None,
    content_hash=None,
):
    """Create or update the attachment row for one upload handle.

    The upload route mints a UUID-shaped ``attachment_id`` (stored in the
    storage path); the PG ``attachments.id`` is DB-generated, so the handle
    lives in ``legacy_mongo_id``. Task retries share the handle — an earlier
    attempt's failure row is updated in place, never duplicated.
    """
    with db_session() as conn:
        repo = AttachmentsRepository(conn)
        existing = repo.get_by_legacy_id(str(attachment_id), user)
        if existing:
            repo.update(
                existing["id"],
                user,
                {
                    "filename": filename,
                    "upload_path": relative_path,
                    "mime_type": mime_type,
                    "content": content,
                    "token_count": token_count,
                    "metadata": metadata,
                    **({"size": size} if size is not None else {}),
                    **({"content_hash": content_hash} if content_hash else {}),
                },
            )
        else:
            repo.create(
                user,
                filename,
                relative_path,
                mime_type=mime_type,
                size=size,
                content=content,
                token_count=token_count,
                metadata=metadata,
                legacy_mongo_id=str(attachment_id),
                content_hash=content_hash,
            )


def _find_reusable_parse(user: str, content_hash: Optional[str], attachment_id: Any) -> Optional[Dict[str, Any]]:
    """The user's earlier parsed upload of the same bytes, if any.

    A /v1 client re-sends every file on every turn and a user re-attaches the
    same file across conversations; parsing it again only costs time. Never
    fails the upload: a lookup error just means the file is parsed.

    Args:
        user: The uploader; only their own rows are considered.
        content_hash: sha256 hex of the upload's bytes.
        attachment_id: This upload's handle, skipped so a retry never reuses
            its own earlier attempt.

    Returns:
        The earlier row (with its content), or None.
    """
    if not content_hash:
        return None
    try:
        with db_readonly() as conn:
            return AttachmentsRepository(conn).find_by_hash(
                user, content_hash, exclude_legacy_id=str(attachment_id)
            )
    except Exception:
        logging.warning("Attachment content-hash lookup failed; parsing instead", exc_info=True)
        return None


def _reused_parse_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    """The parse-derived metadata of an earlier row, to copy onto a reuse.

    Upload-specific keys (storage details, archive membership) stay with the
    row they describe.

    Args:
        row: The earlier attachment row.

    Returns:
        Its extraction record, page count, transcript/OCR details and parse
        warnings, plus ``reused_from`` naming the row.
    """
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    copied = {
        key: value
        for key, value in metadata.items()
        if key in ("extraction", "page_count", "parse_warnings") or key.startswith(("transcript_", "ocr_"))
    }
    copied["reused_from"] = str(row.get("id"))
    return copied


def _write_attachment_failure_row(
    repo: AttachmentsRepository, user: str, file_info: Dict[str, Any], metadata: Dict[str, Any]
) -> None:
    """Write an upload's failure metadata, never over a parsed row.

    The conditional update carries the no-clobber guard in its own WHERE
    clause: a success row committed by a concurrent duplicate execution
    (broker redelivery, the poison guard racing a live attempt) or earlier in
    the same attempt is never overwritten with a NULL-content failure.

    Args:
        repo: Repository on the caller's transaction.
        user: The uploader.
        file_info: The upload's ``attachment_id``, ``filename``, ``path``.
        metadata: The row's metadata, failed ``extraction`` included.
    """
    attachment_id = str(file_info["attachment_id"])
    filename = file_info.get("filename") or ""
    if repo.update_metadata_if_content_null(attachment_id, user, metadata):
        return
    if repo.get_by_legacy_id(attachment_id, user) is not None:
        return
    repo.create(
        user,
        filename,
        file_info.get("path") or "",
        mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        content=None,
        token_count=None,
        metadata=metadata,
        legacy_mongo_id=attachment_id,
    )


def _failure_metadata(file_info: Dict[str, Any], error: Any, parser: Optional[str] = None) -> Dict[str, Any]:
    """An upload's metadata with a failed ``extraction`` record."""
    return {
        **(file_info.get("metadata") or {}),
        "extraction": {"status": "failed", "parser": parser, "truncated": False, "error": str(error)[:1024]},
    }


def record_attachment_failure(user, file_info, error, parser=None):
    """Persist a failure row so a broken parse is visible to a DB scan.

    Called on the worker's error path and by the poison guard; never raises —
    the original exception must keep propagating, and the parser's error text
    goes into ``metadata.extraction``, never into ``content``.
    """
    attachment_id = file_info.get("attachment_id")
    if not attachment_id:
        return
    try:
        metadata = _failure_metadata(file_info, error, parser)
        with db_session() as conn:
            _write_attachment_failure_row(AttachmentsRepository(conn), user, file_info, metadata)
    except Exception:
        logging.error(
            f"Failed to record failure row for attachment {attachment_id}",
            extra={"user": user},
            exc_info=True,
        )


def attachment_worker(self, file_info, user):
    """Process and store one uploaded attachment without vectorization.

    A zip is unpacked into one attachment per member
    (``_archive_attachment_worker``); anything else is parsed as one file.

    Args:
        self: The Celery task, for progress updates.
        file_info: ``filename``, ``attachment_id`` (the upload handle),
            ``path`` (storage path) and upload ``metadata``.
        user: The uploader.

    Returns:
        The stored attachment's summary.
    """
    if is_attachment_archive(file_info.get("filename")):
        return _archive_attachment_worker(self, file_info, user)
    return _single_attachment_worker(self, file_info, user)


def _no_event(*args: Any, **kwargs: Any) -> None:
    """Stand-in for ``publish_user_event`` where nothing should reach the UI."""


class _SilentTask:
    """Stand-in Celery task for a member parsed inside a zip's own task."""

    def update_state(self, *args: Any, **kwargs: Any) -> None:
        """Progress of a member is reported by the zip, not per member."""


def _single_attachment_worker(self, file_info, user, *, emit_events: bool = True):
    """Process and store a single attachment without vectorization.

    Args:
        self: The Celery task (or a stand-in), for progress updates.
        file_info: ``filename``, ``attachment_id``, ``path``, ``metadata``.
        user: The uploader.
        emit_events: Publish the attachment SSE events; off for a zip's
            members, which the browser never uploaded and does not track.

    Returns:
        The stored attachment's summary.
    """
    publish = publish_user_event if emit_events else _no_event

    filename = file_info["filename"]
    attachment_id = file_info["attachment_id"]
    relative_path = file_info["path"]
    metadata = file_info.get("metadata", {})
    parser_name = None

    publish(
        user,
        "attachment.queued",
        {"attachment_id": str(attachment_id), "filename": filename},
        scope={"kind": "attachment", "id": str(attachment_id)},
    )

    try:
        self.update_state(state="PROGRESS", meta={"current": 10})
        storage = StorageCreator.get_storage()

        self.update_state(
            state="PROGRESS", meta={"current": 30, "status": "Processing content"}
        )
        publish(
            user,
            "attachment.progress",
            {
                "attachment_id": str(attachment_id),
                "filename": filename,
                "current": 30,
                "stage": "processing",
            },
            scope={"kind": "attachment", "id": str(attachment_id)},
        )

        # Attachments only: under the docling engine PDFs are read via their
        # text layer where one exists (``ATTACHMENT_PDF_TEXT_FAST_PATH``; a
        # no-op under anydoc, which is already that fast). Source ingestion
        # calls SimpleDirectoryReader without a ``file_extractor`` and so keeps
        # the ``DOC_PARSER_ENGINE`` default map, which retrieval quality depends on.
        file_extractor = get_default_file_extractor(
            ocr_enabled=settings.OCR_ATTACHMENTS_ENABLED,
            pdf_text_fast_path=settings.ATTACHMENT_PDF_TEXT_FAST_PATH,
        )
        _parser = file_extractor.get(os.path.splitext(filename)[1].lower())
        parser_name = type(_parser).__name__ if _parser is not None else "SimpleDirectoryReader"

        fingerprint: Dict[str, Any] = {}
        reused: Dict[str, Any] = {}

        def _parse_local_file(local_path: str, **kwargs) -> Document:
            fingerprint.update(_attachment_fingerprint(local_path, filename))
            _reject_unparseable_attachment(local_path, filename, set(file_extractor))
            _reject_attachment_zip_bomb(local_path)
            earlier = _find_reusable_parse(user, fingerprint.get("content_hash"), attachment_id)
            if earlier is not None:
                reused.update(earlier)
                return Document(text=earlier.get("content") or "", extra_info={})
            parse_path, is_temp_copy = _bounded_attachment_copy(local_path)
            try:
                return SimpleDirectoryReader(
                    input_files=[parse_path],
                    exclude_hidden=True,
                    errors="ignore",
                    file_extractor=file_extractor,
                    file_metadata=metadata_from_filename,
                ).load_data()[0]
            finally:
                if is_temp_copy:
                    try:
                        os.unlink(parse_path)
                    except OSError:
                        pass

        extraction_status = "ok"
        no_text_reason = None
        try:
            attachment_document = storage.process_file(relative_path, _parse_local_file)
        except NoTextLayerError as exc:
            # A PDF with no text layer is still a usable attachment: models
            # that read PDFs natively, or as page images, are sent the stored
            # file rather than its text. Keep it with nothing to inline; the
            # LLM handler names it to any model that cannot read it.
            if not _readable_without_text(filename):
                raise
            logging.info(
                f"Attachment {filename} has no text layer; keeping it for native reading",
                extra={"user": user},
            )
            attachment_document = Document(text="", extra_info={})
            extraction_status = "no_text"
            no_text_reason = str(exc)[:1024]
        content = attachment_document.text
        # A fast-path parser may have delegated to its fallback for this file,
        # so record the engine that actually ran rather than the one selected.
        parser_name = getattr(_parser, "last_engine", None) or parser_name
        parser_metadata = {
            key: value
            for key, value in (attachment_document.extra_info or {}).items()
            if key.startswith(("transcript_", "ocr_")) or key == "parse_warnings"
        }
        if parser_metadata:
            metadata = {**metadata, **parser_metadata}

        if reused:
            # Same bytes, already parsed for this user: copy the stored text
            # and its extraction record instead of parsing again.
            reused_metadata = _reused_parse_metadata(reused)
            extraction_status = (reused_metadata.get("extraction") or {}).get("status") or "ok"
            token_count = reused.get("token_count") or 0
            metadata = {
                **metadata,
                **{k: v for k, v in fingerprint.items() if k in ("content_hash", "page_count")},
                **reused_metadata,
            }
            logging.info(
                f"Attachment {filename} reuses the parse of attachment {reused.get('id')}",
                extra={"user": user},
            )
        else:
            # Gate and cut in the same unit. The old form gated on tokens but cut
            # at 250k *chars*, which for dense scripts (CJK ~1.4 tokens/char)
            # stored 300k+ tokens while looking like a clean extraction.
            encoding = get_encoding()
            tokens = encoding.encode_ordinary(content)
            original_tokens = len(tokens)
            truncated = original_tokens > ATTACHMENT_MAX_TOKENS
            if truncated:
                content = encoding.decode(tokens[:ATTACHMENT_MAX_TOKENS])
                token_count = ATTACHMENT_MAX_TOKENS
            else:
                token_count = original_tokens

            metadata = {
                **metadata,
                **{k: v for k, v in fingerprint.items() if k in ("content_hash", "page_count")},
                "extraction": {
                    "status": extraction_status,
                    "parser": parser_name,
                    "truncated": truncated,
                    "original_tokens": original_tokens,
                    "stored_tokens": token_count,
                    **({"reason": no_text_reason} if no_text_reason else {}),
                },
            }

        self.update_state(
            state="PROGRESS", meta={"current": 80, "status": "Storing in database"}
        )
        publish(
            user,
            "attachment.progress",
            {
                "attachment_id": str(attachment_id),
                "filename": filename,
                "current": 80,
                "stage": "storing",
            },
            scope={"kind": "attachment", "id": str(attachment_id)},
        )

        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if mime_type in VISION_CONVERTIBLE_MIME_TYPES:
            relative_path, conversion = _store_png_copy(storage, relative_path, mime_type)
            mime_type = conversion["to"]
            metadata = {**metadata, "image_conversion": conversion}

        _upsert_attachment_row(
            user,
            filename,
            relative_path,
            mime_type=mime_type,
            content=content,
            token_count=token_count,
            metadata=metadata,
            attachment_id=attachment_id,
            size=fingerprint.get("size"),
            content_hash=fingerprint.get("content_hash"),
        )

        logging.info(
            f"Stored attachment with ID: {attachment_id}", extra={"user": user}
        )

        self.update_state(state="PROGRESS", meta={"current": 100, "status": "Complete"})

        publish(
            user,
            "attachment.completed",
            {
                "attachment_id": str(attachment_id),
                "filename": filename,
                "token_count": token_count,
                "mime_type": mime_type,
                "extraction_status": extraction_status,
            },
            scope={"kind": "attachment", "id": str(attachment_id)},
        )

        return {
            "filename": filename,
            "path": relative_path,
            "token_count": token_count,
            "attachment_id": attachment_id,
            "mime_type": mime_type,
            "metadata": metadata,
        }
    except Exception as e:
        logging.error(
            f"Error processing file {filename}: {e}",
            extra={"user": user},
            exc_info=True,
        )
        record_attachment_failure(user, file_info, e, parser=parser_name)
        publish(
            user,
            "attachment.failed",
            {
                "attachment_id": str(attachment_id),
                "filename": filename,
                "error": str(e)[:1024],
            },
            scope={"kind": "attachment", "id": str(attachment_id)},
        )
        raise


def _archive_index_text(
    filename: str,
    member_paths: List[str],
    skipped: List[Dict[str, Any]],
    skipped_count: int,
    failed: Dict[str, str],
) -> str:
    """The text stored for a zip itself: what it held and what was left out.

    Args:
        filename: The zip's name.
        member_paths: Archive paths of the members stored as attachments.
        skipped: Recorded skips, ``{"archive_path", "reason"}`` each.
        skipped_count: All members left out, recorded or not.
        failed: Archive path to failure reason, for members whose parse failed.

    Returns:
        A short plain-text index; never the archive's bytes.
    """
    from docsgpt.parser.attachment_archive import SKIP_REASON_TEXT

    lines = [
        f"Archive {filename}: {len(member_paths)} file(s) unpacked, each attached separately; "
        f"{skipped_count} skipped."
    ]
    if member_paths:
        lines.append("Files:")
        for path in member_paths:
            if path not in failed:
                lines.append(f"- {path}")
            elif failed[path]:
                lines.append(f"- {path} (could not be parsed: {failed[path]})")
            else:
                lines.append(f"- {path} (could not be parsed)")
    if skipped:
        lines.append("Skipped:")
        lines.extend(
            f"- {item['archive_path']}: {SKIP_REASON_TEXT.get(item['reason'], item['reason'])}" for item in skipped
        )
        hidden = skipped_count - len(skipped)
        if hidden > 0:
            lines.append(f"- and {hidden} more")
    return "\n".join(lines)


def _archive_member_handle(attachment_id: Any, index: int, archive_path: str) -> str:
    """A member's upload handle, the same on every retry of the zip's task."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"docsgpt-archive:{attachment_id}:{index}:{archive_path}"))


# Progress the zip reports: unpacking fills up to the first mark, its members
# finishing move it to the second, and completing the zip takes it to 100.
_ARCHIVE_UNPACKED_PROGRESS = 30
_ARCHIVE_MEMBERS_DONE_PROGRESS = 90
# Longest member failure reason kept on the zip.
_ARCHIVE_FAILURE_REASON_CHARS = 300


def _archive_state(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The zip's in-progress member bookkeeping, or None once it completed."""
    metadata = (row or {}).get("metadata")
    archive = metadata.get("archive") if isinstance(metadata, dict) else None
    if isinstance(archive, dict) and archive.get("status") == "processing":
        return archive
    return None


def _archive_progress_event(row: Dict[str, Any], current: int, stage: str) -> Dict[str, Any]:
    """A zip's ``attachment.progress`` payload, keyed by its upload handle."""
    return {
        "attachment_id": str(row.get("legacy_mongo_id") or row["id"]),
        "filename": row.get("filename") or "",
        "current": current,
        "stage": stage,
    }


def _finish_archive(repo: AttachmentsRepository, row: Dict[str, Any], archive: Dict[str, Any]) -> Dict[str, Any]:
    """Write the zip's index once every member has an outcome.

    Called under the zip row's lock with ``archive`` holding an outcome for
    every planned member. The bookkeeping (``planned`` / ``outcomes``) is
    replaced by the summary the planner and manifest read.

    Args:
        repo: Repository on the transaction holding the lock.
        row: The zip's row.
        archive: Its bookkeeping, complete.

    Returns:
        The ``attachment.completed`` payload to publish once committed.
    """
    planned = archive.get("planned") or []
    outcomes = archive.get("outcomes") or {}
    skipped = [s for s in archive.get("skipped") or [] if isinstance(s, dict)]
    skipped_count = int(archive.get("skipped_count") or 0)
    member_paths: List[str] = []
    failed_members: List[Dict[str, str]] = []
    member_tokens = 0
    for member in planned:
        path = member["metadata"]["archive_path"]
        member_paths.append(path)
        outcome = outcomes.get(member["attachment_id"]) or {}
        if outcome.get("status") == "ok":
            member_tokens += int(outcome.get("token_count") or 0)
        else:
            failed_members.append({"archive_path": path, "reason": str(outcome.get("reason") or "")})
    filename = row.get("filename") or ""
    index_text = _archive_index_text(
        filename,
        member_paths,
        skipped,
        skipped_count,
        {item["archive_path"]: item["reason"] for item in failed_members},
    )
    index_tokens = len(get_encoding().encode_ordinary(index_text))
    summary = {
        "status": "complete",
        "members": len(planned),
        "failed": len(failed_members),
        "failed_members": failed_members,
        "skipped": skipped,
        "skipped_count": skipped_count,
        "total_bytes": int(archive.get("total_bytes") or 0),
    }
    metadata = {
        **(row.get("metadata") or {}),
        "archive": summary,
        "extraction": {
            "status": "ok",
            "parser": "archive",
            "truncated": False,
            "original_tokens": index_tokens,
            "stored_tokens": index_tokens,
        },
    }
    repo.update(str(row["id"]), row["user_id"], {"content": index_text, "token_count": index_tokens, "metadata": metadata})
    return {
        "attachment_id": str(row.get("legacy_mongo_id") or row["id"]),
        "filename": filename,
        "token_count": member_tokens,
        "mime_type": "application/zip",
        "extraction_status": "ok",
        "archive": {"members": len(planned), "skipped": skipped_count, "failed": len(failed_members)},
    }


def _archive_now() -> datetime.datetime:
    """The current time, as the zip's dispatch stamps record it."""
    return datetime.datetime.now(datetime.timezone.utc)


def _members_to_dispatch(archive: Dict[str, Any], *, resume: bool = False) -> List[Dict[str, Any]]:
    """Members to hand to the workers so at most the window is in flight.

    Members are dispatched in archive order. With ``n`` of them finished,
    the first ``n + window`` may have been dispatched; the ones among them
    not dispatched yet (no ``dispatched_at`` stamp) are due. Every outcome,
    a worker's or the reconciler's, frees a slot this way.

    Args:
        archive: The zip's bookkeeping.
        resume: Dispatch every unfinished member in the window, stamped or
            not (the zip's own task starting or resuming after a retry).

    Returns:
        The members' task payloads.
    """
    planned = archive.get("planned") or []
    outcomes = archive.get("outcomes") or {}
    stamps = archive.get("dispatched_at") or {}
    window = max(1, int(settings.ATTACHMENT_ARCHIVE_PARALLELISM))
    due = [m for m in planned[: len(outcomes) + window] if m["attachment_id"] not in outcomes]
    if resume:
        return due
    return [m for m in due if m["attachment_id"] not in stamps]


def _stamp_dispatched(archive: Dict[str, Any], members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The bookkeeping with ``members`` stamped as dispatched now."""
    now = _archive_now().isoformat()
    stamps = {**(archive.get("dispatched_at") or {}), **{m["attachment_id"]: now for m in members}}
    return {**archive, "dispatched_at": stamps}


def _archive_member_task_key(handle: Any) -> str:
    """A member task's idempotency key, which its lease is held under."""
    return f"archive-member:{handle}"


def _dispatch_archive_member(member_info: Dict[str, Any], user: str) -> None:
    """Queue one zip member's parse as its own Celery task.

    The idempotency key is the member's handle: a duplicate dispatch (a
    retried zip resuming its window) waits for or reuses the first run, and
    a member that keeps killing its worker trips the poison guard, which
    records it as failed so the zip still completes.
    """
    from docsgpt.api.user.tasks import store_archive_member

    store_archive_member.apply_async(
        args=[member_info, user],
        kwargs={"idempotency_key": _archive_member_task_key(member_info["attachment_id"])},
    )


def _is_final_attempt(task: Any, exc: BaseException) -> bool:
    """Whether Celery will not retry ``task`` after ``exc``.

    Args:
        task: The bound task (or a stand-in without retry settings, which
            never retries).
        exc: The exception the attempt raised.

    Returns:
        True when the exception is not retried or the retries are spent.
    """
    no_retry = tuple(getattr(task, "dont_autoretry_for", None) or ())
    if no_retry and isinstance(exc, no_retry):
        return True
    max_retries = getattr(task, "max_retries", None)
    if max_retries is None:
        return True
    retries = getattr(getattr(task, "request", None), "retries", 0) or 0
    return retries >= max_retries


def _apply_archive_outcomes(
    repo: AttachmentsRepository, row: Dict[str, Any], new_outcomes: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, Dict[str, Any]]]]:
    """Count members' final outcomes on their zip, then move the zip on.

    The caller holds the zip row's lock, so concurrent members serialize
    and exactly one sees the last outcome land. A member already counted (a
    redelivered task) is not counted again. The members whose slots this
    freed are stamped as dispatched; the caller dispatches them, and
    publishes the events, once the transaction commits.

    Args:
        repo: Repository on the transaction holding the lock.
        row: The zip's locked row.
        new_outcomes: Member handle to ``{"status": "ok", "token_count": n}``
            or ``{"status": "failed", "reason": text}``.

    Returns:
        The members to dispatch, and the zip's events as ``(type, payload)``
        pairs: progress, or completion when the last member landed.
    """
    archive = _archive_state(row)
    if archive is None:
        return [], []
    planned = archive.get("planned") or []
    known = {m["attachment_id"] for m in planned}
    outcomes = dict(archive.get("outcomes") or {})
    for handle, outcome in new_outcomes.items():
        if handle in known:
            outcomes.setdefault(str(handle), outcome)
    archive = {**archive, "outcomes": outcomes}
    if len(outcomes) >= len(planned):
        completed = _finish_archive(repo, row, archive)
        return [], [
            ("attachment.progress", _archive_progress_event(row, _ARCHIVE_MEMBERS_DONE_PROGRESS, "storing")),
            ("attachment.completed", completed),
        ]
    to_dispatch = _members_to_dispatch(archive)
    archive = _stamp_dispatched(archive, to_dispatch)
    repo.update(str(row["id"]), row["user_id"], {"metadata": {**row["metadata"], "archive": archive}})
    span = _ARCHIVE_MEMBERS_DONE_PROGRESS - _ARCHIVE_UNPACKED_PROGRESS
    current = _ARCHIVE_UNPACKED_PROGRESS + int(span * len(outcomes) / len(planned))
    return to_dispatch, [("attachment.progress", _archive_progress_event(row, current, "processing"))]


def _count_archive_member_outcome(
    user: str, member_info: Dict[str, Any], outcome: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Count one member's final outcome on its zip and report the zip's progress.

    Args:
        user: The uploader.
        member_info: The member's task payload.
        outcome: ``{"status": "ok", "token_count": n}`` or
            ``{"status": "failed", "reason": text}``.

    Returns:
        The members whose slots this freed, stamped as dispatched, for the
        caller to dispatch.
    """
    parent_id = (member_info.get("metadata") or {}).get("parent_attachment_id")
    with db_session() as conn:
        repo = AttachmentsRepository(conn)
        row = repo.get_for_update(str(parent_id), user) if parent_id else None
        if row is None:
            return []
        to_dispatch, events = _apply_archive_outcomes(repo, row, {str(member_info["attachment_id"]): outcome})
    _publish_archive_events(user, row, events)
    return to_dispatch


def _dispatch_archive_members(members: List[Dict[str, Any]], user: str) -> None:
    """Dispatch members already stamped as dispatched, failing any that cannot be queued.

    A member is stamped before its dispatch (the stamp commits with the
    zip's bookkeeping), so a dispatch that raises would otherwise leave it
    stamped with no task behind it until the reconciler's timeout. Each
    dispatch is tried twice; a member that still cannot be queued is
    failed with the reason, which frees its slot for the next member (also
    dispatched here) or completes the zip.

    Args:
        members: The members' task payloads.
        user: The uploader.
    """
    pending = list(members)
    while pending:
        member = pending.pop(0)
        error: Optional[Exception] = None
        for _attempt in range(2):
            try:
                _dispatch_archive_member(member, user)
                error = None
                break
            except Exception as exc:
                error = exc
        if error is None:
            continue
        logging.error(
            f"Could not queue archive member {member.get('metadata', {}).get('archive_path')}",
            extra={"user": user},
            exc_info=error,
        )
        reason = f"Could not be queued for processing: {_member_failure_reason(error)}"
        record_attachment_failure(user, member, reason)
        pending.extend(
            _count_archive_member_outcome(
                user, member, {"status": "failed", "reason": reason[:_ARCHIVE_FAILURE_REASON_CHARS]}
            )
        )


def _record_archive_member_outcome(user: str, member_info: Dict[str, Any], outcome: Dict[str, Any]) -> None:
    """Count one member's final outcome on its zip, then dispatch and report.

    Args:
        user: The uploader.
        member_info: The member's task payload.
        outcome: ``{"status": "ok", "token_count": n}`` or
            ``{"status": "failed", "reason": text}``.
    """
    _dispatch_archive_members(_count_archive_member_outcome(user, member_info, outcome), user)


def _archive_event_scope(row: Dict[str, Any]) -> Dict[str, str]:
    """The SSE scope of a zip's events: its upload handle, which the browser tracks."""
    return {"kind": "attachment", "id": str(row.get("legacy_mongo_id") or row["id"])}


def _publish_archive_events(user: str, row: Dict[str, Any], events: List[Tuple[str, Dict[str, Any]]]) -> None:
    """Report a zip's progress or completion to the browser."""
    scope = _archive_event_scope(row)
    for kind, payload in events:
        publish_user_event(user, kind, payload, scope=scope)


def sweep_stuck_archive_members(
    conn: Any, *, timeout_seconds: int
) -> Tuple[int, List[Tuple[Dict[str, Any], str]], List[Tuple[str, str, Dict[str, Any], Dict[str, str]]]]:
    """Fail zip members queued longer than the timeout without an outcome.

    A member whose task was lost (a broker loss, a crash between the commit
    and the dispatch) would leave its zip processing forever. Each one past
    ``timeout_seconds`` since its dispatch, whose task holds no live lease
    (a running task heartbeats its lease, however long the parse takes),
    gets a failure row and a failed
    outcome with the reason; that frees its slot for the next member, or
    completes the zip with honest counts. Runs in the reconciler's
    transaction; zips a member task holds right now are left to the next
    tick.

    Args:
        conn: The reconciler sweep's connection.
        timeout_seconds: ``ATTACHMENT_ARCHIVE_MEMBER_TIMEOUT``.

    Returns:
        The number of members failed, the members to dispatch as
        ``(member_info, user)`` and the events to publish as
        ``(user, type, payload, scope)``, both for after the commit.
    """
    repo = AttachmentsRepository(conn)
    cutoff = _archive_now() - datetime.timedelta(seconds=timeout_seconds)
    minutes = max(1, round(timeout_seconds / 60))
    reason = f"Not processed within {minutes} minutes."
    failed = 0
    dispatches: List[Tuple[Dict[str, Any], str]] = []
    events: List[Tuple[str, str, Dict[str, Any], Dict[str, str]]] = []
    for row in repo.find_and_lock_processing_archives():
        archive = _archive_state(row) or {}
        outcomes = archive.get("outcomes") or {}
        stamps = archive.get("dispatched_at") or {}
        stuck = []
        for member in archive.get("planned") or []:
            stamp = stamps.get(member["attachment_id"])
            if member["attachment_id"] in outcomes or not stamp:
                continue
            try:
                stale = datetime.datetime.fromisoformat(stamp) < cutoff
            except (TypeError, ValueError):
                stale = True
            if stale:
                stuck.append(member)
        if stuck:
            from docsgpt.storage.db.repositories.idempotency import IdempotencyRepository

            running = IdempotencyRepository(conn).live_lease_keys(
                [_archive_member_task_key(m["attachment_id"]) for m in stuck]
            )
            stuck = [m for m in stuck if _archive_member_task_key(m["attachment_id"]) not in running]
        if not stuck:
            continue
        user = row["user_id"]
        for member in stuck:
            _write_attachment_failure_row(repo, user, member, _failure_metadata(member, reason))
        to_dispatch, zip_events = _apply_archive_outcomes(
            repo, row, {m["attachment_id"]: {"status": "failed", "reason": reason} for m in stuck}
        )
        failed += len(stuck)
        dispatches.extend((member, user) for member in to_dispatch)
        scope = _archive_event_scope(row)
        events.extend((user, kind, payload, scope) for kind, payload in zip_events)
    return failed, dispatches, events


def _member_failure_reason(error: Any) -> str:
    """A member's failure reason as the zip records it: short, one line."""
    text = " ".join(str(error).split()) or type(error).__name__
    return text[:_ARCHIVE_FAILURE_REASON_CHARS]


def archive_member_worker(self, member_info: Dict[str, Any], user: str) -> Dict[str, Any]:
    """Parse one member of a zip attachment, then count it on the zip.

    The member is parsed like any upload but silently: the browser tracks
    only the zip. A failure is counted only once it is final (not retried,
    or out of retries), with its reason, so one bad file never holds the
    zip back and a transient one is not reported as lost.

    Args:
        self: The Celery task, for its retry state.
        member_info: ``filename``, ``attachment_id`` (the member's handle),
            ``path`` and ``metadata`` (``parent_attachment_id``,
            ``archive_path``, ``archive_index``).
        user: The uploader.

    Returns:
        The member's handle and outcome.

    Raises:
        Exception: The parse failed and Celery will retry it.
    """
    try:
        result = _single_attachment_worker(_SilentTask(), member_info, user, emit_events=False)
    except Exception as exc:
        if not _is_final_attempt(self, exc):
            raise
        logging.warning(
            f"Archive member {member_info.get('metadata', {}).get('archive_path')} could not be parsed",
            extra={"user": user},
            exc_info=True,
        )
        outcome = {"status": "failed", "reason": _member_failure_reason(exc)}
    else:
        outcome = {"status": "ok", "token_count": int(result.get("token_count") or 0)}
    _record_archive_member_outcome(user, member_info, outcome)
    return {"attachment_id": str(member_info["attachment_id"]), **outcome}


def record_archive_member_failure(user: str, member_info: Dict[str, Any], error: Any) -> None:
    """Fail a member whose task never got to (the poison guard), so its zip completes.

    Args:
        user: The uploader.
        member_info: The member's task payload.
        error: Why it failed.
    """
    record_attachment_failure(user, member_info, error)
    _record_archive_member_outcome(user, member_info, {"status": "failed", "reason": _member_failure_reason(error)})


def _claim_archive_row(
    user: str,
    file_info: Dict[str, Any],
    metadata: Dict[str, Any],
    size: Optional[int],
    content_hash: Optional[str],
) -> Dict[str, Any]:
    """Create or refresh the zip's own row before its members are stored.

    A retried zip keeps the bookkeeping of the run before it, so members
    already counted stay counted.

    Args:
        user: The uploader.
        file_info: The zip's task payload.
        metadata: The zip's upload metadata (with its content hash).
        size: The zip's size in bytes.
        content_hash: sha256 of the zip's bytes.

    Returns:
        The zip's row as written.
    """
    attachment_id = str(file_info["attachment_id"])
    fields: Dict[str, Any] = {
        "filename": file_info["filename"],
        "upload_path": file_info["path"],
        "mime_type": "application/zip",
        **({"size": size} if size is not None else {}),
        **({"content_hash": content_hash} if content_hash else {}),
    }
    processing = {**metadata, "extraction": {"status": "processing", "parser": "archive"}}
    with db_session() as conn:
        repo = AttachmentsRepository(conn)
        existing = repo.get_by_legacy_id(attachment_id, user)
        if existing is None:
            return repo.create(
                user,
                fields["filename"],
                fields["upload_path"],
                mime_type="application/zip",
                size=size,
                content=None,
                token_count=None,
                metadata=processing,
                legacy_mongo_id=attachment_id,
                content_hash=content_hash,
            )
        row = repo.get_for_update(str(existing["id"]), user) or existing
        previous = (row.get("metadata") or {}).get("archive")
        if isinstance(previous, dict):
            processing["archive"] = previous
        repo.update(str(row["id"]), user, {**fields, "metadata": processing})
        return {**row, **fields, "metadata": processing}


def _start_archive_members(
    user: str,
    parent_id: str,
    planned: List[Dict[str, Any]],
    expansion: Any,
) -> None:
    """Record the zip's members and hand the first window of them to the workers.

    Members a previous run of this zip already counted keep their outcomes
    and are not dispatched again. A zip with nothing to parse (or whose
    members were all counted) completes here.

    Args:
        user: The uploader.
        parent_id: The zip row's PG id.
        planned: The members' task payloads, in archive order.
        expansion: The ``ArchiveExpansion``, for the skipped members.
    """
    handles = {m["attachment_id"] for m in planned}
    completed: Optional[Dict[str, Any]] = None
    to_dispatch: List[Dict[str, Any]] = []
    with db_session() as conn:
        repo = AttachmentsRepository(conn)
        row = repo.get_for_update(parent_id, user)
        if row is None:
            return
        previous = _archive_state(row) or {}
        outcomes = {h: o for h, o in (previous.get("outcomes") or {}).items() if h in handles}
        archive = {
            "status": "processing",
            "members": len(planned),
            "planned": planned,
            "outcomes": outcomes,
            "dispatched_at": {
                h: t for h, t in (previous.get("dispatched_at") or {}).items() if h in handles and h not in outcomes
            },
            "skipped": [{"archive_path": s.archive_path, "reason": s.reason} for s in expansion.skipped],
            "skipped_count": expansion.skipped_count,
            "total_bytes": expansion.total_bytes,
        }
        if len(outcomes) >= len(planned):
            completed = _finish_archive(repo, row, archive)
        else:
            to_dispatch = _members_to_dispatch(archive, resume=True)
            archive = _stamp_dispatched(archive, to_dispatch)
            repo.update(parent_id, user, {"metadata": {**row["metadata"], "archive": archive}})
    _dispatch_archive_members(to_dispatch, user)
    if completed is not None:
        _publish_archive_events(
            user,
            row,
            [
                ("attachment.progress", _archive_progress_event(row, _ARCHIVE_MEMBERS_DONE_PROGRESS, "storing")),
                ("attachment.completed", completed),
            ],
        )


def _record_archive_failure(user: str, file_info: Dict[str, Any], parent_id: Optional[str], error: Any) -> None:
    """Mark the zip failed without losing its members' bookkeeping.

    Before the zip has a row this is the ordinary failure row. After, only
    ``metadata.extraction`` changes, so a retry resumes the members already
    counted.
    """
    if parent_id is None:
        record_attachment_failure(user, file_info, error, parser="archive")
        return
    try:
        with db_session() as conn:
            repo = AttachmentsRepository(conn)
            row = repo.get_for_update(parent_id, user)
            if row is None:
                return
            extraction = {"status": "failed", "parser": "archive", "truncated": False, "error": str(error)[:1024]}
            repo.update(parent_id, user, {"metadata": {**(row.get("metadata") or {}), "extraction": extraction}})
    except Exception:
        logging.error(
            f"Failed to record failure for archive {file_info.get('attachment_id')}",
            extra={"user": user},
            exc_info=True,
        )


def record_archive_task_failure(user: str, file_info: Dict[str, Any], error: Any) -> None:
    """Fail a zip whose own task never got to (the poison guard), keeping its members.

    A zip that already has its row keeps ``metadata.archive``, so members
    still in flight are counted and can complete it; only
    ``metadata.extraction`` is marked failed. Never raises.

    Args:
        user: The uploader.
        file_info: The zip's task payload.
        error: Why it failed.
    """
    parent_id: Optional[str] = None
    try:
        with db_readonly() as conn:
            row = AttachmentsRepository(conn).get_by_legacy_id(str(file_info.get("attachment_id")), user)
        parent_id = str(row["id"]) if row else None
    except Exception:
        logging.error(
            f"Failed to look up archive {file_info.get('attachment_id')}", extra={"user": user}, exc_info=True
        )
    _record_archive_failure(user, file_info, parent_id, error)


def _archive_attachment_worker(self, file_info, user):
    """Unpack a zip attachment and fan its members out to their own tasks.

    The zip keeps its own row as an index (``metadata.archive`` and a short
    text listing, never the compressed bytes). Each member is stored next to
    the other uploads and parsed like one by its own ``store_archive_member``
    task, in its own row linked by ``metadata.parent_attachment_id`` /
    ``archive_path`` / ``archive_index``; members load in archive order after
    the zip wherever the zip is attached
    (``AttachmentsRepository.list_for_planning`` / ``expand_archives``).
    At most ``ATTACHMENT_ARCHIVE_PARALLELISM`` members of one zip are queued
    at a time; each one that finishes queues the next. The zip completes
    (its ``attachment.completed`` event, which the composer waits for) when
    the last member has an outcome. Members with no parser that are not
    text are skipped, like every member the limits leave out, with a reason
    recorded on the zip. Only the zip reports SSE progress: the browser
    shows the zip as one file.

    Args:
        self: The Celery task, for progress updates.
        file_info: The zip's ``filename``, ``attachment_id``, ``path``,
            ``metadata``.
        user: The uploader.

    Returns:
        The zip's summary. Its members are still being parsed unless the
        zip had none.

    Raises:
        AttachmentRejectedError: The file is not a readable zip or is a zip bomb.
    """
    from docsgpt.parser.attachment_archive import ArchiveLimits, ArchiveRejectedError, expand_archive
    from docsgpt.parser.file.constants import attachment_extension
    from docsgpt.upload_limits import UnsupportedUploadTypeError, enforce_parseable_attachment, looks_like_text

    filename = file_info["filename"]
    attachment_id = file_info["attachment_id"]
    relative_path = file_info["path"]
    metadata = file_info.get("metadata", {}) or {}
    scope = {"kind": "attachment", "id": str(attachment_id)}
    parent_id: Optional[str] = None

    with db_readonly() as conn:
        existing = AttachmentsRepository(conn).get_by_legacy_id(str(attachment_id), user)
    existing_archive = ((existing or {}).get("metadata") or {}).get("archive")
    if isinstance(existing_archive, dict) and existing_archive.get("status") == "complete":
        # A redelivery of a zip that already completed: its members are
        # parsed and counted, so there is nothing to redo.
        return {
            "filename": filename,
            "path": relative_path,
            "token_count": existing.get("token_count"),
            "attachment_id": attachment_id,
            "mime_type": "application/zip",
            "metadata": existing.get("metadata"),
        }

    publish_user_event(
        user, "attachment.queued", {"attachment_id": str(attachment_id), "filename": filename}, scope=scope
    )
    work_dir = tempfile.mkdtemp(prefix="docsgpt-archive-")
    try:
        self.update_state(state="PROGRESS", meta={"current": 10})
        storage = StorageCreator.get_storage()
        limits = ArchiveLimits.from_settings()
        fingerprint: Dict[str, Any] = {}
        file_extractor = get_default_file_extractor(
            ocr_enabled=settings.OCR_ATTACHMENTS_ENABLED,
            pdf_text_fast_path=settings.ATTACHMENT_PDF_TEXT_FAST_PATH,
        )
        parser_suffixes = set(file_extractor)

        def _accept(member_name: str, read_head) -> bool:
            # The upload rule (enforce_parseable_attachment) on the member's
            # head, before it is unpacked: unsupported members never count
            # toward the zip's file and byte limits.
            return attachment_extension(member_name) in parser_suffixes or looks_like_text(read_head())

        def _expand(local_path: str, **kwargs):
            fingerprint.update(_attachment_fingerprint(local_path, filename))
            return expand_archive(local_path, work_dir, limits, accept=_accept)

        try:
            expansion = storage.process_file(relative_path, _expand)
        except ArchiveRejectedError as exc:
            raise AttachmentRejectedError(str(exc)) from exc

        content_hash = fingerprint.get("content_hash")
        base_metadata = {**metadata, **({"content_hash": content_hash} if content_hash else {})}
        # The zip's row first, so its members can name it.
        parent = _claim_archive_row(user, file_info, base_metadata, fingerprint.get("size"), content_hash)
        parent_id = str(parent["id"])

        attachments_dir = os.path.dirname(os.path.dirname(relative_path))
        planned: List[Dict[str, Any]] = []
        total = len(expansion.members) or 1
        for index, member in enumerate(expansion.members):
            current = 10 + int((_ARCHIVE_UNPACKED_PROGRESS - 10) * index / total)
            self.update_state(state="PROGRESS", meta={"current": current, "status": "Unpacking"})
            publish_user_event(
                user,
                "attachment.progress",
                {"attachment_id": str(attachment_id), "filename": filename, "current": current, "stage": "processing"},
                scope=scope,
            )
            try:
                enforce_parseable_attachment(member.local_path, member.filename, parser_suffixes)
            except UnsupportedUploadTypeError:
                expansion.skip(member.archive_path, "unsupported_type")
                continue
            handle = _archive_member_handle(attachment_id, index, member.archive_path)
            member_path = f"{attachments_dir}/{handle}/{safe_filename(member.filename)}"
            with open(member.local_path, "rb") as member_bytes:
                storage_metadata = storage.save_file(member_bytes, member_path) or {}
            planned.append(
                {
                    "filename": member.filename,
                    "attachment_id": handle,
                    "path": member_path,
                    "metadata": {
                        **(storage_metadata if isinstance(storage_metadata, dict) else {}),
                        "parent_attachment_id": parent_id,
                        "archive_path": member.archive_path,
                        "archive_index": index,
                    },
                }
            )

        self.update_state(state="PROGRESS", meta={"current": _ARCHIVE_UNPACKED_PROGRESS, "status": "Parsing files"})
        _start_archive_members(user, parent_id, planned, expansion)
        return {
            "filename": filename,
            "path": relative_path,
            "attachment_id": attachment_id,
            "mime_type": "application/zip",
            "members": len(planned),
        }
    except Exception as e:
        logging.error(f"Error unpacking archive {filename}: {e}", extra={"user": user}, exc_info=True)
        _record_archive_failure(user, file_info, parent_id, e)
        publish_user_event(
            user,
            "attachment.failed",
            {"attachment_id": str(attachment_id), "filename": filename, "error": str(e)[:1024]},
            scope=scope,
        )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def parse_document_worker(self, artifact_id, parent, user_id, options):
    """Thin Celery-task wrapper; delegates to the process-agnostic ``run_parse_document``."""
    return run_parse_document(artifact_id, parent, user_id, options)


def run_parse_document(artifact_id, parent, user_id, options):
    """Parse an input artifact's bytes to a shaped result; runnable inline OR on the parsing queue.

    Security: the artifact is re-resolved through the run-scoped gate here (never trusting a
    raw storage path) so authz is enforced independently, in addition to the pre-enqueue check
    in the tool. ``read_document`` calls this directly (in-process) when it already runs inside a
    Celery worker; the web process dispatches ``parse_document`` to the parsing queue, which lands
    here via ``parse_document_worker``.
    """
    from docsgpt.agents.tools.artifact_ref import resolve_artifact_id
    from docsgpt.parser.document_reader import bound_parse_payload, parse_document_bytes

    options = options or {}
    parent = parent or {}
    conversation_id = parent.get("conversation_id")
    workflow_run_id = parent.get("workflow_run_id")
    if conversation_id is None and workflow_run_id is None:
        return {"status": "error", "error": "parse_document requires a conversation_id or workflow_run_id."}

    # Re-resolve through the parent-scoped gate so a forged/cross-run id is rejected
    # here too; resolve a short ref to an id within this parent only.
    try:
        with db_readonly() as conn:
            repo = ArtifactsRepository(conn)
            resolved_id = resolve_artifact_id(
                repo, artifact_id, conversation_id=conversation_id, workflow_run_id=workflow_run_id
            )
            artifact = (
                repo.get_artifact_in_parent(
                    resolved_id, conversation_id=conversation_id, workflow_run_id=workflow_run_id
                )
                if resolved_id is not None
                else None
            )
            if artifact is None:
                return {"status": "error", "error": f"input artifact {artifact_id} not found in this conversation/run."}
            version = repo.get_version(resolved_id, artifact["current_version"])
    except Exception:
        logging.error("run_parse_document: failed to resolve input artifact", exc_info=True)
        return {"status": "error", "error": f"failed to load input artifact {artifact_id}."}

    if not version or not version.get("storage_path"):
        return {"status": "error", "error": f"input artifact {artifact_id} has no stored content."}

    display_name = version.get("filename") or artifact.get("title") or str(resolved_id)
    filename = safe_filename(display_name)
    try:
        data = StorageCreator.get_storage().get_file(version["storage_path"]).read()
    except Exception:
        logging.error("run_parse_document: failed to read input artifact bytes", exc_info=True)
        return {"status": "error", "error": f"failed to read input artifact {artifact_id}."}

    # Parse returns the FULL content (no max_chars/window here) so the persisted artifact is the
    # complete parse; all view-bounding is applied by ``bound_parse_payload`` below.
    result = parse_document_bytes(
        data,
        filename,
        output=options.get("output", "markdown"),
        ocr=options.get("ocr", "auto"),
        pages=options.get("pages"),
        engine=options.get("engine", "auto"),
        include_tables=bool(options.get("include_tables", True)),
    )
    if result.get("error"):
        return {"status": "error", "error": result["error"]}

    payload = {"status": "ok", **result}
    if options.get("persist"):
        # Persist the FULL shaped result by reference (bytes live in the artifact); only the
        # bounded view computed below rides back through the Redis result backend.
        artifact_ref = _persist_parse_result(result, display_name, user_id, parent, options)
        if isinstance(artifact_ref, dict) and artifact_ref.get("error"):
            payload["artifact_error"] = artifact_ref["error"]
        elif artifact_ref is not None:
            payload["artifact"] = artifact_ref
    # Bound the Redis-backed VIEW across all shapes: content is capped by max_chars (else the
    # default head+tail window), chunks are count/length-capped, and structured (needed for
    # json_schema validation) rides back as-is. The FULL result already lives in the artifact.
    payload = bound_parse_payload(payload, max_chars=options.get("max_chars"))
    return payload


def _persist_parse_result(result, title, user_id, parent, options):
    """Persist the full shaped parse result as an owner/parent-scoped ``data`` artifact; return its ref."""
    from docsgpt.sandbox.artifacts_capture import QuotaExceeded, persist_new_artifact

    try:
        data = json.dumps(result).encode("utf-8")
    except (TypeError, ValueError):
        logging.error("parse_document_worker: parse result is not JSON-serializable", exc_info=True)
        return {"error": "parse result is not JSON-serializable."}
    base = safe_filename(title) or "document"
    filename = f"{base}.parsed.json"
    try:
        return persist_new_artifact(
            user_id=user_id,
            kind="data",
            data=data,
            filename=filename,
            mime_type="application/json",
            title=f"{title} (parsed)",
            conversation_id=parent.get("conversation_id"),
            workflow_run_id=parent.get("workflow_run_id"),
            message_id=parent.get("message_id"),
            produced_by={"tool": "read_document", "action": "read_document", "tool_id": options.get("tool_id")},
        )
    except QuotaExceeded as exc:
        return {"error": str(exc)}


def agent_webhook_worker(self, agent_id, payload):
    """Process the webhook payload for an agent.

    Raises on failure: Celery treats a returned dict as success and
    would skip retries, leaving the caller with a stale 200.
    """
    self.update_state(state="PROGRESS", meta={"current": 1})
    try:
        with db_readonly() as conn:
            repo = AgentsRepository(conn)
            agent_config = None
            if looks_like_uuid(str(agent_id)):
                # Access without user scoping — webhooks authenticate via
                # the incoming token, not a user context.
                from sqlalchemy import text as sql_text
                from docsgpt.storage.db.base_repository import row_to_dict
                result = conn.execute(
                    sql_text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"),
                    {"id": str(agent_id)},
                )
                row = result.fetchone()
                if row is not None:
                    agent_config = row_to_dict(row)
            if agent_config is None:
                agent_config = repo.get_by_legacy_id(str(agent_id))
        if not agent_config:
            raise ValueError(f"Agent with ID {agent_id} not found.")
        input_data = json.dumps(payload)
    except Exception as e:
        logging.error(f"Error processing agent webhook: {e}", exc_info=True)
        raise
    self.update_state(state="PROGRESS", meta={"current": 50})
    try:
        # Shared headless path with the scheduler; approval-gated tools auto-deny.
        from docsgpt.agents.headless_runner import run_agent_headless
        from docsgpt.quotas.service import QuotaExceededError

        outcome = run_agent_headless(
            agent_config,
            input_data,
            tool_allowlist=_webhook_tool_allowlist(agent_config),
            endpoint="webhook",
            request_id=getattr(getattr(self, "request", None), "id", None),
        )
        result = {
            "answer": outcome.get("answer", ""),
            "sources": outcome.get("sources", []),
            "tool_calls": outcome.get("tool_calls", []),
            "thought": outcome.get("thought", ""),
        }
    except QuotaExceededError as e:
        # Returned, not raised: retrying cannot succeed before the quota resets.
        logging.warning(
            f"Webhook skipped for agent {agent_id}: {e}", extra={"agent_id": agent_id}
        )
        return {"status": "quota_exceeded", "error": str(e)}
    except Exception as e:
        logging.error(f"Error running agent logic: {e}", exc_info=True)
        raise
    else:
        logging.info(
            f"Webhook processed for agent {agent_id}", extra={"agent_id": agent_id}
        )
        return {"status": "success", "result": result}
    finally:
        self.update_state(state="PROGRESS", meta={"current": 100})


def _webhook_tool_allowlist(agent_config):
    """Deny-all on approval-gated tools for webhooks (per-agent opt-in is TBD)."""
    return []


def _with_connection_credentials(source_data, connection_id: str):
    """Loader input with the connection's stored keys merged in, or None.

    S3, Reddit and GitHub sources made from a connection keep their keys on
    the connection only, never in ``sources.remote_data``. A JSON string
    stays a JSON string and a dict a dict; any other string (a GitHub
    repository URL) becomes ``{"url": ...}`` next to the keys. An MCP
    sign-in (Linear) gets its ``connection_id`` instead: its tokens stay
    with the MCP client, which renews them. Returns None when the
    connection is gone, needs reconnecting, or its connector is turned off.
    """
    from docsgpt.connectors import service
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    with db_readonly() as conn:
        row = ConnectorSessionsRepository(conn).get(str(connection_id))
        enabled = row is not None and service.connector_enabled(conn, row)
    if row is None or not enabled:
        return None
    if (row.get("auth_kind") or "") == "mcp_oauth":
        if service.normalize_status(row) != service.STATUS_CONNECTED:
            return None
        credentials = {"connection_id": str(row["id"])}
    else:
        try:
            credentials = service.access_credentials(row)
        except service.ConnectionUnavailable:
            return None
    if isinstance(source_data, str):
        try:
            parsed = json.loads(source_data)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return json.dumps({**parsed, **credentials})
        return {"url": source_data, **credentials}
    return {**dict(source_data or {}), **credentials}


def _link_source_to_connection(source_id: str, connection_id: str) -> None:
    """Point a source at the connection it syncs from, and lift any reconnect pause."""
    from sqlalchemy import text as sql_text

    try:
        with db_session() as conn:
            conn.execute(
                sql_text(
                    "UPDATE sources SET connection_id = CAST(:cid AS uuid), "
                    "metadata = metadata - 'sync_state' WHERE id = CAST(:sid AS uuid)"
                ),
                {"cid": str(connection_id), "sid": str(source_id)},
            )
    except Exception:
        logging.warning("Could not link source %s to connection %s", source_id, connection_id, exc_info=True)


def sync_connector_source(self, source_id: str) -> Dict[str, Any]:
    """Re-download and re-index a connector source from its connection.

    Runs as the connection owner with no browser: the connection service
    refreshes the token under a row lock. When the grant was revoked the
    service flags the connection and pauses its sources, and this returns
    ``paused`` rather than failing again on every schedule.

    Args:
        self: The bound Celery task.
        source_id: The source to sync.

    Returns:
        ``{"status": "success" | "paused" | "disabled" | "skipped"}`` plus
        the ingest result.
    """
    from docsgpt.connectors.service import ConnectionUnavailable, connector_enabled, normalize_status
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    with db_readonly() as conn:
        from sqlalchemy import text as sql_text

        row = conn.execute(
            sql_text(
                "SELECT id, name, user_id, remote_data, retriever, sync_frequency, config, connection_id "
                "FROM sources WHERE id = CAST(:id AS uuid)"
            ),
            {"id": str(source_id)},
        ).fetchone()
        source = dict(row._mapping) if row else None
        connection = (
            ConnectorSessionsRepository(conn).get(str(source["connection_id"]))
            if source and source.get("connection_id")
            else None
        )
        enabled = connection is not None and connector_enabled(conn, connection)
    if not source or not connection:
        return {"status": "skipped"}
    if not enabled:
        return {"status": "disabled"}
    if normalize_status(connection) != "connected":
        return {"status": "paused"}
    remote_data = source.get("remote_data") or {}
    if isinstance(remote_data, str):
        try:
            remote_data = json.loads(remote_data)
        except json.JSONDecodeError:
            remote_data = {}
    provider = remote_data.get("provider") or connection.get("provider")
    try:
        result = ingest_connector(
            self,
            source.get("name"),
            source.get("user_id"),
            provider,
            connection_id=str(connection["id"]),
            file_ids=remote_data.get("file_ids") or [],
            folder_ids=remote_data.get("folder_ids") or [],
            recursive=remote_data.get("recursive", True),
            retriever=source.get("retriever") or "classic",
            operation_mode="sync",
            doc_id=str(source["id"]),
            sync_frequency=source.get("sync_frequency") or "never",
            config=source.get("config") or None,
        )
    except ConnectionUnavailable:
        return {"status": "paused"}
    return {"status": "success", "result": result}


def ingest_connector(
    self,
    job_name: str,
    user: str,
    source_type: str,
    session_token=None,
    file_ids=None,
    folder_ids=None,
    recursive=True,
    retriever: str = "classic",
    operation_mode: str = "upload",
    doc_id=None,
    sync_frequency: str = "never",
    config=None,
    idempotency_key=None,
    source_id=None,
    connection_id=None,
) -> Dict[str, Any]:
    """
    Ingestion for internal knowledge bases (GoogleDrive, etc.).

    Args:
        job_name: Name of the ingestion job
        user: User identifier
        source_type: Type of remote source ("google_drive", "dropbox", etc.)
        session_token: Legacy browser session token naming the connection
        connection_id: The connection whose account the files are read with
        file_ids: List of file IDs to download
        folder_ids: List of folder IDs to download
        recursive: Whether to recursively download folders
        retriever: Type of retriever to use
        operation_mode: "upload" for initial ingestion, "sync" for incremental sync
        doc_id: Document ID for sync operations (required when operation_mode="sync")
        sync_frequency: How often to sync ("never", "daily", "weekly", "monthly")
        config: Per-source ``SourceConfig`` dict. ``None``/``{}`` → classic
            defaults (byte-identical to prior behavior).
        idempotency_key: When provided, the ``source_id`` is derived
            deterministically so a retried upload reuses the same source row.
        source_id: When supplied, the worker uses it verbatim so SSE envelopes
            carry the same id the HTTP route already returned to the frontend
            — required for non-idempotent uploads where the route can't
            predict ``_derive_source_id(idempotency_key)``.
    """
    logging.info(
        f"Starting remote ingestion from {source_type} for user: {user}, job: {job_name}"
    )

    # Source id resolution mirrors ``ingest_worker`` / ``remote_worker``:
    # sync mode reuses ``doc_id``; otherwise the caller-supplied
    # ``source_id`` (minted by the HTTP route and already echoed to the
    # client) wins; fall back to ``_derive_source_id`` only when neither
    # is supplied. Without rule (2) the no-idempotency-key path would
    # mint a fresh uuid4 here that the frontend has no way to correlate
    # SSE envelopes to.
    if operation_mode == "sync" and doc_id:
        source_uuid = str(doc_id)
    elif source_id:
        source_uuid = uuid.UUID(source_id)
    else:
        source_uuid = _derive_source_id(idempotency_key)
    source_id_for_events = str(source_uuid)

    # First-attempt gate: Celery retries re-run the body, and a
    # repeated ``queued`` here would oscillate the toast through
    # ``queued`` again between ``failed`` and ``completed``.
    if self.request.retries == 0:
        publish_user_event(
            user,
            "source.ingest.queued",
            {
                "source_id": source_id_for_events,
                "job_name": job_name,
                "loader": source_type,
                "operation": operation_mode,
            },
            scope={"kind": "source", "id": source_id_for_events},
        )

    self.update_state(state="PROGRESS", meta={"current": 1})

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 1: Initialize the appropriate loader
            self.update_state(
                state="PROGRESS",
                meta={"current": 10, "status": "Initializing connector"},
            )

            if not session_token and not connection_id:
                raise ValueError(f"{source_type} connector requires a connection")

            if not ConnectorCreator.is_supported(source_type):
                raise ValueError(
                    f"Unsupported connector type: {source_type}. Supported types: {ConnectorCreator.get_supported_connectors()}"
                )

            remote_loader = ConnectorCreator.create_connector(
                source_type, session_token, connection_id=connection_id
            )
            connection_id = remote_loader.connection_id

            # Create a clean config for storage
            api_source_config = {
                "file_ids": file_ids or [],
                "folder_ids": folder_ids or [],
                "recursive": recursive,
            }

            # Step 2: Download files to temp directory
            self.update_state(
                state="PROGRESS", meta={"current": 20, "status": "Downloading files"}
            )
            download_info = remote_loader.download_to_directory(
                temp_dir, api_source_config
            )

            if download_info.get("empty_result", False) or not download_info.get(
                "files_downloaded", 0
            ):
                logging.warning(f"No files were downloaded from {source_type}")
                # Connector returned no files — surface as a benign
                # ``completed`` event with zero tokens so the toast
                # closes out cleanly instead of waiting on polling.
                publish_user_event(
                    user,
                    "source.ingest.completed",
                    {
                        "source_id": source_id_for_events,
                        "job_name": job_name,
                        "loader": source_type,
                        "operation": operation_mode,
                        "tokens": 0,
                        "no_changes": True,
                    },
                    scope={"kind": "source", "id": source_id_for_events},
                )
                # Create empty result directly instead of calling a separate method
                return {
                    "name": job_name,
                    "user": user,
                    "tokens": 0,
                    "type": source_type,
                    "source_config": api_source_config,
                    "directory_structure": "{}",
                }

            # Step 3: Use SimpleDirectoryReader to process downloaded files
            self.update_state(
                state="PROGRESS", meta={"current": 40, "status": "Processing files"}
            )
            reader = SimpleDirectoryReader(
                input_dir=temp_dir,
                recursive=True,
                required_exts=list(SUPPORTED_SOURCE_EXTENSIONS),
                exclude_hidden=True,
                file_metadata=metadata_from_filename,
            )
            # Parsing/OCR fills 40-60% of the bar; embedding takes 60-100%.
            raw_docs = reader.load_data(
                progress_callback=_make_parse_progress_callback(
                    self, user, source_uuid, start_pct=40, end_pct=60,
                )
            )
            directory_structure = getattr(reader, "directory_structure", {})

            # Step 4: Process documents (chunking, embedding, etc.)
            cfg = SourceConfig.parse(config)
            chunker = ChunkerCreator.create_chunker(
                cfg.chunking.strategy,
                chunking_strategy=cfg.chunking.strategy,
                max_tokens=cfg.chunking.max_tokens,
                min_tokens=cfg.chunking.min_tokens,
                duplicate_headers=cfg.chunking.duplicate_headers,
            )
            raw_docs = chunker.chunk(documents=raw_docs)

            # Preserve source information in document metadata
            for doc in raw_docs:
                if hasattr(doc, "extra_info") and doc.extra_info:
                    source = doc.extra_info.get("source")
                    if source and os.path.isabs(source):
                        # Convert absolute path to relative path
                        doc.extra_info["source"] = os.path.relpath(
                            source, start=temp_dir
                        )

            docs = [Document.to_vector_format(raw_doc) for raw_doc in raw_docs]

            # Validate operation_mode here too (the source_uuid path
            # at the top of the function only branches on the
            # sync+doc_id combination; surfacing the wrong-mode error
            # this far in matches the legacy behaviour).
            if operation_mode == "sync" and not doc_id:
                logging.error(
                    "Invalid doc_id provided for sync operation: %s", doc_id
                )
                raise ValueError("doc_id must be provided for sync operation.")
            if operation_mode not in ("upload", "sync"):
                raise ValueError(f"Invalid operation_mode: {operation_mode}")

            vector_store_path = os.path.join(temp_dir, "vector_store")
            os.makedirs(vector_store_path, exist_ok=True)

            self.update_state(
                state="PROGRESS", meta={"current": 60, "status": "Storing documents"}
            )
            embed_and_store_documents(
                docs, vector_store_path, source_uuid, self,
                attempt_id=getattr(self.request, "id", None),
                user_id=user,
                progress_start=60, progress_end=100,
            )
            assert_index_complete(source_uuid)

            tokens = count_tokens_docs(docs)

            # Step 6: Upload index files
            file_data = {
                "user": user,
                "name": job_name,
                "tokens": tokens,
                "retriever": retriever,
                "id": source_id_for_events,
                "type": "connector:file",
                "remote_data": json.dumps(
                    {"provider": source_type, **api_source_config}
                ),
                "directory_structure": json.dumps(directory_structure),
                "sync_frequency": sync_frequency,
            }
            if config:
                file_data["config"] = json.dumps(config)

            file_data["last_sync"] = datetime.datetime.now(datetime.timezone.utc)

            if operation_mode == "sync":
                try:
                    with db_session() as conn:
                        repo = SourcesRepository(conn)
                        src = repo.get_any(source_id_for_events, user)
                        if src is not None:
                            repo.update(
                                str(src["id"]), user,
                                {"date": file_data["last_sync"]},
                            )
                except Exception as upd_err:
                    logging.warning(
                        "Failed to update last_sync for source %s: %s",
                        source_id_for_events,
                        upd_err,
                    )

            upload_index(vector_store_path, file_data)
            if connection_id:
                _link_source_to_connection(source_id_for_events, connection_id)

            # Ensure we mark the task as complete
            self.update_state(
                state="PROGRESS", meta={"current": 100, "status": "Complete"}
            )

            logging.info(f"Remote ingestion completed: {job_name}")

            publish_user_event(
                user,
                "source.ingest.completed",
                {
                    "source_id": source_id_for_events,
                    "job_name": job_name,
                    "loader": source_type,
                    "operation": operation_mode,
                    "tokens": tokens,
                },
                scope={"kind": "source", "id": source_id_for_events},
            )
            _maybe_enqueue_graph_extraction(cfg, source_id_for_events, user)

            return {
                "user": user,
                "name": job_name,
                "tokens": tokens,
                "type": source_type,
                "id": source_id_for_events,
                "status": "complete",
            }
    except Exception as e:
        logging.error(f"Error during remote ingestion: {e}", exc_info=True)
        publish_user_event(
            user,
            "source.ingest.failed",
            {
                "source_id": source_id_for_events,
                "job_name": job_name,
                "loader": source_type,
                "operation": operation_mode,
                "error": str(e)[:1024],
            },
            scope={"kind": "source", "id": source_id_for_events},
        )
        raise


def mcp_oauth(self, config: Dict[str, Any], user_id: str = None) -> Dict[str, Any]:
    """Worker to handle MCP OAuth flow asynchronously.

    Publishes SSE events at each phase boundary so the frontend can
    drive the OAuth popup directly from the push channel. The
    ``mcp.oauth.awaiting_redirect`` envelope carries the
    ``authorization_url`` once the upstream OAuth client surfaces it,
    eliminating the prior polling-only path for that URL.
    """

    # Bind ``task_id`` and the publish helpers OUTSIDE the outer try so
    # the ``except`` handler at the bottom can reach them even when an
    # early statement raises. Without this, ``publish_oauth`` would
    # UnboundLocalError on top of the original failure.
    task_id = self.request.id if getattr(self, "request", None) else None

    def publish_oauth(event_type: str, payload: Dict[str, Any]) -> None:
        # MCP OAuth can be invoked without a route-bound user_id by
        # legacy paths. Skip the SSE publish in that case \u2014 the caller
        # has no per-user channel to subscribe to, and the status is
        # surfaced via the task's return value.
        if not user_id or task_id is None:
            return
        publish_user_event(
            user_id,
            event_type,
            {"task_id": task_id, **payload},
            scope={"kind": "mcp_oauth", "id": task_id},
        )

    def publish_awaiting_redirect(authorization_url: str) -> None:
        """Callback invoked by ``DocsGPTOAuth.redirect_handler`` once
        the OAuth client has minted the authorization URL.

        Carrying the URL on the SSE envelope lets the frontend open the
        popup directly from the event \u2014 the prior polling-only path
        for the URL is gone.
        """
        publish_oauth(
            "mcp.oauth.awaiting_redirect",
            {
                "message": "Awaiting OAuth redirect...",
                "authorization_url": authorization_url,
            },
        )

    try:
        import asyncio

        from docsgpt.agents.tools.mcp_tool import MCPTool

        publish_oauth("mcp.oauth.in_progress", {"message": "Starting OAuth..."})

        tool_config = config.copy()
        tool_config["oauth_task_id"] = task_id
        # Inject the awaiting-redirect publish callback. ``MCPTool`` pops
        # it out of the config and threads it into ``DocsGPTOAuth`` so
        # the publish fires synchronously from inside
        # ``redirect_handler`` \u2014 the only point where the URL is known.
        tool_config["oauth_redirect_publish"] = publish_awaiting_redirect
        mcp_tool = MCPTool(tool_config, user_id)

        async def run_oauth_discovery():
            if not mcp_tool._client:
                mcp_tool._setup_client()
            return await mcp_tool._execute_with_client("list_tools")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(run_oauth_discovery())
            tools = mcp_tool.get_actions_metadata()

            publish_oauth(
                "mcp.oauth.completed",
                {"tools": tools, "tools_count": len(tools)},
            )

            return {"success": True, "tools": tools, "tools_count": len(tools)}
        except Exception as e:
            error_msg = f"OAuth failed: {str(e)}"
            logging.error("MCP OAuth discovery failed: %s", error_msg, exc_info=True)
            publish_oauth("mcp.oauth.failed", {"error": error_msg[:1024]})
            return {"success": False, "error": error_msg}
        finally:
            loop.close()
    except Exception as e:
        error_msg = f"OAuth init failed: {str(e)}"
        logging.error("MCP OAuth init failed: %s", error_msg, exc_info=True)
        publish_oauth("mcp.oauth.failed", {"error": error_msg[:1024]})
        return {"success": False, "error": error_msg}


def reembed_wiki_page_worker(self, source_id, path, content_hash, user):
    """Re-embed one wiki page after an edit, or purge its chunks on delete.

    Targeted delete of the page's existing chunks runs first, so a deleted
    page becomes a pure purge and an edited page is re-embedded cleanly. The
    chunk metadata shape matches the reingest path (``source``/``title``/
    ``filename``) so retrieval and future targeted deletes line up.

    Args:
        self: Celery task instance.
        source_id: Source the page belongs to.
        path: Page path; doubles as the chunk ``source`` metadata key.
        content_hash: The edit's content hash (idempotency anchor).
        user: Owner identifier used to load the source row.

    Returns:
        A status dict: ``{"status", "added", "deleted"}`` on re-embed, or
        ``{"status": "deleted", "deleted": n}`` when the page is gone.
    """
    from docsgpt.vectorstore.vector_creator import VectorCreator

    source_id = str(source_id)

    with db_readonly() as conn:
        source = SourcesRepository(conn).get_any(source_id, user)
    if not source:
        raise ValueError(f"Source {source_id} not found or access denied")
    source_id = str(source["id"])
    cfg = SourceConfig.parse(source.get("config"))

    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
    )
    deleted = store.delete_chunks_by_source_path(path)

    with db_readonly() as conn:
        page = WikiPagesRepository(conn).get_by_path(source_id, path)

    if page is None:
        return {"status": "deleted", "deleted": deleted}

    try:
        title = page.get("title") or path
        chunker = ChunkerCreator.create_chunker(
            cfg.chunking.strategy,
            chunking_strategy=cfg.chunking.strategy,
            max_tokens=cfg.chunking.max_tokens,
            min_tokens=cfg.chunking.min_tokens,
            duplicate_headers=cfg.chunking.duplicate_headers,
        )
        chunks = chunker.chunk(
            documents=[
                Document(
                    text=page["content"],
                    extra_info={
                        "source": path,
                        "title": title,
                        "filename": path,
                    },
                )
            ]
        )

        added = 0
        for chunk in chunks:
            # Start from what the chunker produced -- ``token_count`` above
            # all, which the source viewer reads per chunk -- and let the
            # page's own identity win over anything stale it inherited.
            metadata = dict(chunk.extra_info or {})
            metadata.update({"source": path, "title": title, "filename": path})
            store.add_chunk(chunk.text, metadata=metadata)
            added += 1

        with db_session() as conn:
            WikiPagesRepository(conn).set_embed_status(source_id, path, "embedded")
            # These chunks were just embedded with the configured model, so the
            # source now names it. Wiki sources created before this was recorded
            # carry NULL, which the boot mismatch check reads as the legacy
            # model and reports as stale; stamping here heals them on the next
            # page edit.
            SourcesRepository(conn).update(
                source_id, user, {"model": settings.EMBEDDINGS_NAME}
            )
    except Exception:
        with db_session() as conn:
            WikiPagesRepository(conn).set_embed_status(source_id, path, "failed")
        raise

    return {"status": "embedded", "added": added, "deleted": deleted}


def _wiki_page_path_from_rel(rel_path):
    """Build a validated leading-slash wiki page path, or None if invalid.

    Runs the derived path through ``validate_tool_path`` so a stored filename
    carrying traversal (``..``) never lands as a ``wiki_pages.path``.
    """
    from docsgpt.agents.tools.path_utils import validate_tool_path

    raw = "/" + rel_path.replace(os.sep, "/").lstrip("/")
    return validate_tool_path(raw)


def _chunk_text(chunk) -> str:
    if isinstance(chunk, dict):
        return chunk.get("text") or chunk.get("page_content") or ""
    return getattr(chunk, "text", None) or getattr(chunk, "page_content", "") or ""


def _chunk_metadata(chunk) -> dict:
    if isinstance(chunk, dict):
        meta = chunk.get("metadata")
    else:
        meta = getattr(chunk, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _chunk_doc_id(chunk):
    if isinstance(chunk, dict):
        return chunk.get("doc_id")
    return getattr(chunk, "doc_id", None)


def _url_to_virtual_path(value: str) -> str:
    parts = urlsplit(value)
    path = parts.path.strip("/")
    if path:
        return path
    if parts.netloc:
        return parts.netloc
    return value.replace("://", "/")


def _chunk_page_path(metadata) -> str:
    for key in ("file_path", "file_name", "filename", "title", "source"):
        value = metadata.get(key)
        if value:
            value = str(value)
            if "://" in value:
                value = _url_to_virtual_path(value)
            return value
    return ""


def _chunk_order_hint(metadata):
    for key in ("chunk", "chunk_index", "index", "start", "start_index", "offset"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


MIN_CHUNK_OVERLAP_TRIM = 32


def _join_chunk_texts(texts: list[str]) -> str:
    """Concatenate chunk texts, trimming an exact overlapping boundary.

    Only an exact suffix/prefix overlap of at least ``MIN_CHUNK_OVERLAP_TRIM``
    characters between consecutive chunks is removed (the common
    ``chunk_overlap`` case); shorter, possibly legitimate repeats are kept.
    """
    parts: list[str] = []
    for text in texts:
        if parts:
            prev = parts[-1]
            limit = min(len(prev), len(text))
            overlap = 0
            for size in range(limit, MIN_CHUNK_OVERLAP_TRIM - 1, -1):
                if prev.endswith(text[:size]):
                    overlap = size
                    break
            if overlap:
                text = text[overlap:]
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def convert_source_to_wiki_worker(self, source_id, user):
    """Convert an ingested source into a wiki by reassembling pages from chunks.

    Groups the source's existing vector-store chunks by their page path
    (``metadata.source``), concatenating each group into one wiki page. This
    works uniformly for every source type, including crawler/remote/connector
    sources that hold no stored originals. Chunks with a missing or invalid
    path are skipped and reported. Embedding is enqueued per page (async); the
    source's ``config.kind`` flips to ``wiki`` only after at least one page is
    materialized — a source with no usable chunks keeps its original kind and
    directory structure.

    Args:
        self: Celery task instance.
        source_id: ID of the source to convert.
        user: Owner identifier used to load the source row and author pages.

    Returns:
        A summary dict ``{"status": "converted", "pages_created", "skipped"}``,
        ``{"status": "no_pages", ...}`` when nothing was reassembled, or
        ``{"status": "already_wiki"}`` when the source is already a wiki.
    """
    from docsgpt.api.user.tasks import reembed_wiki_page
    from docsgpt.vectorstore.vector_creator import VectorCreator

    source_id = str(source_id)

    with db_readonly() as conn:
        source = SourcesRepository(conn).get_any(source_id, user)
    if not source:
        raise ValueError(f"Source {source_id} not found or access denied")
    source_id = str(source["id"])

    cfg = SourceConfig.parse(source.get("config"))
    if cfg.kind == "wiki":
        return {"status": "already_wiki", "pages_created": 0, "skipped": []}

    file_name_map = _normalize_file_name_map(source.get("file_name_map"))

    created_pages: list[tuple[str, str]] = []
    skipped: list[dict] = []

    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
    )

    grouped: dict[str, list[tuple[object, str]]] = {}
    original_doc_ids: list[object] = []
    for chunk in store.get_chunks() or []:
        # Track every original chunk so a skipped one (empty/no-path/invalid)
        # is purged on convert too, not left orphaned in the vector store after
        # the source flips to wiki. Only deleted once pages are created below.
        doc_id = _chunk_doc_id(chunk)
        if doc_id is not None:
            original_doc_ids.append(doc_id)
        metadata = _chunk_metadata(chunk)
        rel_path = _chunk_page_path(metadata)
        text = _chunk_text(chunk)
        if not text.strip():
            continue
        if not rel_path:
            skipped.append({"file": "", "reason": "missing path"})
            continue
        if _wiki_page_path_from_rel(rel_path) is None:
            skipped.append({"file": rel_path, "reason": "invalid path"})
            continue
        grouped.setdefault(rel_path, []).append((_chunk_order_hint(metadata), text))

    with db_session() as conn:
        repo = WikiPagesRepository(conn)
        for rel_path in sorted(grouped):
            page_path = _wiki_page_path_from_rel(rel_path)
            entries = grouped[rel_path]
            if any(hint is not None for hint, _ in entries):
                entries = sorted(
                    enumerate(entries),
                    key=lambda item: (
                        item[1][0] if item[1][0] is not None else float("inf"),
                        item[0],
                    ),
                )
                entries = [entry for _, entry in entries]
            content = _join_chunk_texts([text for _, text in entries])
            title = _get_display_name(file_name_map, rel_path) or os.path.basename(
                rel_path
            )
            repo.upsert(
                source_id,
                page_path,
                content,
                title=title,
                updated_by=user,
                updated_via="agent",
            )
            created_pages.append((page_path, _content_hash(content)))

    if not created_pages:
        return {
            "status": "no_pages",
            "pages_created": 0,
            "skipped": skipped,
        }

    with db_session() as conn:
        rebuild_wiki_directory_structure(conn, source_id, user)

    for doc_id in original_doc_ids:
        try:
            store.delete_chunk(doc_id)
        except Exception as exc:
            logging.error(f"Failed deleting original chunk {doc_id}: {exc}")

    for page_path, content_hash in created_pages:
        reembed_wiki_page.delay(
            source_id,
            page_path,
            content_hash,
            user=user,
            idempotency_key=f"reembed-wiki:{source_id}:{page_path}:{content_hash}",
        )

    with db_session() as conn:
        SourcesRepository(conn).update(
            source_id, user, {"config": cfg.wiki_enabled()}
        )

    return {
        "status": "converted",
        "pages_created": len(created_pages),
        "skipped": skipped,
    }


def extract_graph_worker(self, source_id, user):
    """Build a graphrag source's knowledge graph from its embedded chunks.

    Loads the source, fetches its chunks from the vector store, and runs the
    per-chunk LLM extraction pipeline. The chunks carry ``doc_id`` + ``text``,
    matching the retrievable ids the extraction pipeline links against. No-ops
    cleanly when GraphRAG is unavailable or the source has no chunks yet.

    Streams ``graph.extract.progress`` SSE events as chunks are processed and a
    terminal ``graph.extract.completed``/``graph.extract.failed`` on exit.

    Args:
        self: Celery task instance.
        source_id: Source whose graph is being built.
        user: Owner identifier used to load the source and attribute token usage.

    Returns:
        ``{"status": "unavailable"}`` when GraphRAG is off, otherwise the
        extraction summary ``{nodes, edges, chunks_processed, ...}``.
    """
    from docsgpt.graphrag import graphrag_available
    from docsgpt.graphrag.extraction import extract_graph_for_source
    from docsgpt.vectorstore.vector_creator import VectorCreator

    source_id = str(source_id)

    if not graphrag_available():
        return {"status": "unavailable"}

    with db_readonly() as conn:
        source = SourcesRepository(conn).get_any(source_id, user)
    if not source:
        raise ValueError(f"Source {source_id} not found or access denied")
    source_id = str(source["id"])
    cfg = SourceConfig.parse(source.get("config"))

    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
    )
    chunks = store.get_chunks() or []

    total = len(chunks)
    # Throttle: at most ~20 progress events regardless of chunk count.
    step = max(1, total // 20)

    def _progress(info):
        current = int(info.get("current", 0))
        if current and current % step != 0 and current != info.get("total"):
            return
        _publish_graph_event(
            user,
            source_id,
            "graph.extract.progress",
            {
                "source_id": source_id,
                "current": current,
                "total": int(info.get("total", total)),
                "nodes": int(info.get("nodes", 0)),
                "edges": int(info.get("edges", 0)),
            },
        )

    _publish_graph_event(
        user,
        source_id,
        "graph.extract.progress",
        {
            "source_id": source_id,
            "current": 0,
            "total": total,
            "nodes": 0,
            "edges": 0,
        },
    )

    trace = tracing.start_trace(
        source="graph_extraction",
        name=f"graph_extraction {source.get('name') or source_id}",
        request_id=getattr(self.request, "id", None),
        user_id=user,
    )
    try:
        with tracing.activate(trace), tracing.span(
            tracing.KIND_STEP,
            "graph_extraction",
            attributes={"docsgpt.source_id": source_id, "docsgpt.chunk_count": total},
        ) as span:
            summary = extract_graph_for_source(
                source_id,
                user,
                chunks,
                config=cfg,
                request_id=getattr(self.request, "id", None),
                progress_cb=_progress,
            )
            if isinstance(summary, dict):
                span.set(
                    **{
                        "docsgpt.graph.nodes": summary.get("nodes"),
                        "docsgpt.graph.edges": summary.get("edges"),
                        "docsgpt.graph.chunks_processed": summary.get("chunks_processed"),
                    }
                )
    except Exception as e:
        tracing.flush(trace, tracing.STATUS_ERROR)
        _publish_graph_event(
            user,
            source_id,
            "graph.extract.failed",
            {"source_id": source_id, "error": str(e)[:1024]},
        )
        raise

    tracing.flush(trace)
    _publish_graph_event(
        user,
        source_id,
        "graph.extract.completed",
        {"source_id": source_id, **summary},
    )
    return summary
