"""A workflow run's documents as ``[D#:L#]`` numbered text (``file_passing: lines``).

Each document is read once per artifact version: the first node, template or
code node that asks for it pays for the parse, and every later one in the
run gets the same entry. ``D#`` is the document's position in the run's
``input_documents`` (documents from elsewhere, such as a code node's output,
are numbered after them in the order they are first read); ``L#`` counts its
lines. Parsed lines are also cached in Redis by content hash, so a run over
the same file does not parse it again.

Nothing is ever cut: a document that cannot be read, or that is too large,
fails the node with a message naming it.
"""

from __future__ import annotations

import json
import logging
import os
import time
import zlib
from typing import Any, Dict, List, Optional, Tuple

from docsgpt.parser.document_lines import FORMAT_VERSION, extract_document_lines, number_lines

logger = logging.getLogger(__name__)

# The state key the entries are published under.
DOCUMENTS_STATE_KEY = "documents"

# Instruction appended to a ``lines`` node's system prompt.
LINES_INSTRUCTION = (
    "## Line references\n"
    "Each line of the input documents starts with a [D#:L#] reference: the document "
    "number and the line number within that document. A table row is one line with its "
    'cells separated by " | "; a marker such as (Sheet1!A5) or (p.3) gives the '
    "spreadsheet cell or PDF page the line comes from. Cite evidence with these references."
)


class WorkflowDocumentError(ValueError):
    """A document could not be given to a node as numbered text.

    The message is written for the person running the workflow.
    """


class DocumentsTooLargeError(WorkflowDocumentError):
    """A node's documents do not fit its model's context window.

    Attributes:
        needed_tokens: Estimated tokens the node's prompt and documents take.
        available_tokens: Tokens the model can take for them.
    """

    def __init__(self, message: str, *, needed_tokens: int, available_tokens: int) -> None:
        super().__init__(message)
        self.needed_tokens = int(needed_tokens)
        self.available_tokens = int(available_tokens)


def is_inline_text_mime(mime_type: str) -> bool:
    """Already-text formats, read in-process instead of on the parsing queue."""
    if mime_type.startswith("text/"):
        return True
    return mime_type in ("application/json", "application/xml")


def snapshot_documents(entries: List[Any]) -> List[Any]:
    """The entries as run snapshots and stream events carry them: no document content.

    The text is dropped, and each table keeps only its line span: a header
    row holds cell values, which can be as sensitive as the text.
    """
    return [_snapshot_entry(entry) if isinstance(entry, dict) else entry for entry in entries]


def _snapshot_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    projected = {key: value for key, value in entry.items() if key != "text"}
    if isinstance(entry.get("tables"), list):
        projected["tables"] = [
            {key: value for key, value in table.items() if key != "header"} if isinstance(table, dict) else table
            for table in entry["tables"]
        ]
    return projected


def attachment_text(entry: Dict[str, Any]) -> str:
    """The text a ``lines`` node gets for one document: a heading line, then its numbered lines."""
    return f"Document {entry['id']}: {entry['filename']} ({entry['line_count']} lines)\n{entry['text']}"


class RunDocuments:
    """The numbered documents of one workflow run, each read once per artifact version."""

    def __init__(self, workflow_run_id: str) -> None:
        self.workflow_run_id = workflow_run_id
        # artifact_id -> (artifact version, D number, entry)
        self._loaded: Dict[str, Tuple[Any, int, Dict[str, Any]]] = {}
        # Documents not among the run's inputs, in the order they were first read.
        self._extra: List[str] = []

    def entries(self) -> List[Dict[str, Any]]:
        """Every document read so far, in ``D#`` order."""
        return [entry for _, _, entry in sorted(self._loaded.values(), key=lambda loaded: loaded[1])]

    def load(self, raw_ids: List[str], input_ids: List[str], user_id: Optional[str]) -> List[Dict[str, Any]]:
        """Read the given documents, parsing only those not read yet.

        Args:
            raw_ids: Artifact ids or short refs (``A1``) of this run.
            input_ids: The run's ``input_documents`` artifact ids, in order.
            user_id: The run's owner, whom the parsing worker reads as.

        Returns:
            The documents' entries, in ``D#`` order.

        Raises:
            WorkflowDocumentError: A document is missing, too large, or
                could not be read.
        """
        resolved = self._resolve(raw_ids)
        pending = [
            (artifact_id, artifact, version)
            for artifact_id, artifact, version in resolved
            if self._loaded.get(artifact_id, (None,))[0] != version.get("_number")
        ]
        if pending:
            parsed = self._read_all(pending, user_id)
            for artifact_id, artifact, version in pending:
                self._remember(artifact_id, artifact, version, parsed[artifact_id], input_ids)
        wanted = {artifact_id for artifact_id, _, _ in resolved}
        return [entry for entry in self.entries() if entry["artifact_id"] in wanted]

    def _resolve(self, raw_ids: List[str]) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
        from docsgpt.agents.tools.artifact_ref import resolve_artifact_id
        from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
        from docsgpt.storage.db.session import db_readonly

        resolved: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
        seen = set()
        with db_readonly() as conn:
            repo = ArtifactsRepository(conn)
            for raw in raw_ids:
                # A short ref resolves within this run only, and the id is
                # re-checked through the run-scoped gate either way.
                artifact_id = resolve_artifact_id(repo, raw, workflow_run_id=self.workflow_run_id)
                artifact = (
                    repo.get_artifact_in_parent(artifact_id, workflow_run_id=self.workflow_run_id)
                    if artifact_id is not None
                    else None
                )
                if artifact is None:
                    raise WorkflowDocumentError(f'Document "{raw}" was not found in this run.')
                artifact_id = str(artifact_id)
                if artifact_id in seen:
                    continue
                seen.add(artifact_id)
                version = repo.get_version(artifact_id, artifact["current_version"])
                if not version or not version.get("storage_path"):
                    raise WorkflowDocumentError(f'Document "{artifact.get("title") or raw}" has no stored content.')
                resolved.append((artifact_id, artifact, {**version, "_number": artifact["current_version"]}))
        return resolved

    def _read_all(
        self, pending: List[Tuple[str, Dict[str, Any], Dict[str, Any]]], user_id: Optional[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Lines for each pending document: from the cache, read in-process, or parsed on the queue.

        Every queue parse is sent before any is awaited, so the documents
        parse side by side on the parsing workers. Inside a Celery worker
        (scheduled and webhook runs) they parse in this process instead, as
        ``read_document`` does: awaiting a queue this worker may itself
        serve could deadlock it.
        """
        from docsgpt.celery_init import in_worker
        from docsgpt.parser.document_reader import _max_input_bytes

        cap = _max_input_bytes()
        inline_parse = in_worker()
        parsed: Dict[str, Dict[str, Any]] = {}
        dispatched: List[Tuple[str, str, Dict[str, Any], Any, float]] = []
        for artifact_id, artifact, version in pending:
            name = _display_name(artifact_id, artifact, version)
            size = version.get("size")
            if isinstance(size, (int, float)) and size > cap:
                raise WorkflowDocumentError(
                    f'Document "{name}" is too large to read ({int(size):,} bytes; the limit is {cap:,}).'
                )
            cached = _cache_get(version, name)
            if cached is not None:
                parsed[artifact_id] = cached
                continue
            mime_type = version.get("mime_type") or "application/octet-stream"
            if is_inline_text_mime(mime_type):
                parsed[artifact_id] = self._read_inline(name, version, mime_type, cap)
                _cache_set(version, name, parsed[artifact_id])
                continue
            if inline_parse:
                parsed[artifact_id] = self._parse_here(artifact_id, name, version, user_id)
                _cache_set(version, name, parsed[artifact_id])
                continue
            dispatched.append(self._dispatch(artifact_id, name, version, user_id))

        for artifact_id, name, version, async_result, deadline in dispatched:
            parsed[artifact_id] = self._await(name, async_result, deadline)
            _cache_set(version, name, parsed[artifact_id])
        return parsed

    @staticmethod
    def _read_inline(name: str, version: Dict[str, Any], mime_type: str, cap: int) -> Dict[str, Any]:
        from docsgpt.storage.storage_creator import StorageCreator

        try:
            file_obj = StorageCreator.get_storage().get_file(version["storage_path"])
            try:
                # Bounded even when the stored size is missing; one byte over
                # the cap is enough for the reader to refuse it.
                data = file_obj.read(cap + 1)
            finally:
                close = getattr(file_obj, "close", None)
                if callable(close):
                    close()
        except Exception:
            logger.exception("Workflow documents: failed to read %s", version["storage_path"])
            raise WorkflowDocumentError(f'Document "{name}" could not be read.') from None
        result = extract_document_lines(data, name, mime_type=mime_type)
        if result.get("error"):
            raise WorkflowDocumentError(f'Document "{name}" could not be read: {result["error"]}')
        return result

    def _parse_here(
        self, artifact_id: str, name: str, version: Dict[str, Any], user_id: Optional[str]
    ) -> Dict[str, Any]:
        """Parse in this worker process, bounded by the same size-scaled window as a queued parse."""
        from docsgpt.agents.tools.read_document import ReadDocumentTool, _InlineParseTimeout
        from docsgpt.api.user.tasks import parse_timeout_for_size
        from docsgpt.worker import run_parse_document

        if not user_id:
            raise WorkflowDocumentError("Reading documents needs a signed-in user.")
        try:
            result = ReadDocumentTool._run_inline_bounded(
                lambda: run_parse_document(artifact_id, self._parent(), user_id, {"output": "lines"}),
                parse_timeout_for_size(version.get("size")),
            )
        except _InlineParseTimeout:
            raise WorkflowDocumentError(f'Document "{name}" could not be read in time.') from None
        except Exception:
            logger.exception("Workflow documents: parse of %s failed", name)
            raise WorkflowDocumentError(f'Document "{name}" could not be read.') from None
        return _parsed_lines(name, result)

    def _parent(self) -> Dict[str, Any]:
        return {"workflow_run_id": self.workflow_run_id}

    def _dispatch(
        self, artifact_id: str, name: str, version: Dict[str, Any], user_id: Optional[str]
    ) -> Tuple[str, str, Dict[str, Any], Any, float]:
        from docsgpt.api.user.tasks import parse_document, parse_task_time_limits, parse_timeout_for_size
        from docsgpt.core.settings import settings

        if not user_id:
            raise WorkflowDocumentError("Reading documents needs a signed-in user.")
        timeout = parse_timeout_for_size(version.get("size"))
        try:
            async_result = parse_document.apply_async(
                args=[artifact_id, self._parent(), user_id, {"output": "lines"}],
                queue=settings.DOCUMENT_PARSE_QUEUE,
                **parse_task_time_limits(timeout),
            )
        except Exception:
            logger.exception("Workflow documents: could not queue the parse of %s", artifact_id)
            raise WorkflowDocumentError(f'Document "{name}" could not be sent to the parsing worker.') from None
        return artifact_id, name, version, async_result, time.monotonic() + timeout

    @staticmethod
    def _await(name: str, async_result: Any, deadline: float) -> Dict[str, Any]:
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        try:
            # A workflow can run inside a Celery worker (scheduled runs,
            # webhooks), where ``get`` refuses to block unless told it may;
            # the parse runs on its own queue, so this cannot self-deadlock.
            result = async_result.get(
                timeout=max(deadline - time.monotonic(), 0.001), disable_sync_subtasks=False
            )
        except (CeleryTimeoutError, TimeoutError):
            raise WorkflowDocumentError(f'Document "{name}" could not be read in time.') from None
        except Exception:
            logger.exception("Workflow documents: parse of %s failed", name)
            raise WorkflowDocumentError(f'Document "{name}" could not be read.') from None
        return _parsed_lines(name, result)

    def _remember(
        self,
        artifact_id: str,
        artifact: Dict[str, Any],
        version: Dict[str, Any],
        parsed: Dict[str, Any],
        input_ids: List[str],
    ) -> None:
        if artifact_id in input_ids:
            number = input_ids.index(artifact_id) + 1
        else:
            if artifact_id not in self._extra:
                self._extra.append(artifact_id)
            number = len(input_ids) + self._extra.index(artifact_id) + 1
        lines = [str(line) for line in parsed["lines"]]
        entry = {
            "id": f"D{number}",
            "artifact_id": artifact_id,
            "filename": _display_name(artifact_id, artifact, version),
            "mime_type": version.get("mime_type") or "application/octet-stream",
            "line_count": len(lines),
            "tables": list(parsed.get("tables") or []),
            "text": number_lines(number, lines),
        }
        self._loaded[artifact_id] = (version.get("_number"), number, entry)


def _parsed_lines(name: str, result: Any) -> Dict[str, Any]:
    """The lines and tables of a ``parse_document`` result, or the error naming the document."""
    if not isinstance(result, dict) or result.get("status") != "ok" or not isinstance(result.get("lines"), list):
        reason = result.get("error") if isinstance(result, dict) else None
        detail = f": {reason}" if reason else "."
        raise WorkflowDocumentError(f'Document "{name}" could not be read{detail}')
    return {"lines": result["lines"], "tables": result.get("tables") or []}


def _display_name(artifact_id: str, artifact: Optional[Dict[str, Any]], version: Dict[str, Any]) -> str:
    return str(version.get("filename") or (artifact or {}).get("title") or artifact_id)


def _cache_key(version: Dict[str, Any], name: str) -> Optional[str]:
    """The cache key for a document version, or None when its content hash is unknown.

    The reader is picked from the extension (and, for a text file without
    one, the mime type), and the configured-parser fallback depends on the
    engine and OCR settings, so identical bytes read differently under
    another name or setup get a key of their own.
    """
    from docsgpt.core.settings import settings

    sha256 = version.get("sha256")
    if not sha256:
        return None
    suffix = os.path.splitext(name)[1].lower()
    reader = suffix or f"mime={version.get('mime_type') or ''}"
    parser = f"{settings.DOC_PARSER_ENGINE}-{settings.OCR_BACKEND}-{int(bool(settings.OCR_ENABLED))}"
    return f"workflow:doclines:v{FORMAT_VERSION}:{parser}:{reader}:{sha256}"


def _cache_ttl() -> int:
    from docsgpt.core.settings import settings

    return max(int(settings.WORKFLOW_DOCUMENT_LINES_CACHE_TTL or 0), 0)


def _cache_get(version: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Cached lines for this document version; None on a miss or any Redis failure."""
    key = _cache_key(version, name)
    if not key or not _cache_ttl():
        return None
    from docsgpt.cache import get_redis_instance

    try:
        client = get_redis_instance()
        raw = client.get(key) if client is not None else None
        if not raw:
            return None
        value = json.loads(zlib.decompress(raw))
    except Exception:
        logger.warning("Workflow documents: line cache read failed", exc_info=True)
        return None
    if not isinstance(value, dict) or not isinstance(value.get("lines"), list):
        return None
    return {"lines": value["lines"], "tables": value.get("tables") or []}


def _cache_set(version: Dict[str, Any], name: str, parsed: Dict[str, Any]) -> None:
    key = _cache_key(version, name)
    ttl = _cache_ttl()
    if not key or not ttl:
        return
    from docsgpt.cache import get_redis_instance

    try:
        client = get_redis_instance()
        if client is None:
            return
        payload = json.dumps({"lines": parsed["lines"], "tables": parsed.get("tables") or []})
        client.set(key, zlib.compress(payload.encode("utf-8")), ex=ttl)
    except Exception:
        logger.warning("Workflow documents: line cache write failed", exc_info=True)
