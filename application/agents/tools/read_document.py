"""Read Document tool: parse an input artifact to text/markdown/structured/chunks via the backend parser.

The ``read_document`` action resolves a parent-scoped input artifact, enqueues a
``parse_document`` task on the dedicated ``parsing`` Celery queue, and awaits the
result with a timeout. The run-scoped authz gate is enforced TWICE — here before
enqueue (reject cross-tenant) and again in the worker (re-resolve, never trusting a
raw path). When a ``json_schema`` is supplied the structured payload is validated
through the existing jsonschema path; the full result may also be persisted as a
``data`` artifact by reference (handled in the worker).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from celery import current_task

from application.agents.tools.artifact_ref import resolve_artifact_id
from application.agents.tools.attachment_bridge import (
    AttachmentBridgeError,
    bridge_attachment,
    match_attachment,
)
from application.agents.tools.base import Tool
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.settings import settings
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

try:
    import jsonschema
except Exception:  # pragma: no cover - jsonschema is a declared dependency
    jsonschema = None  # type: ignore[assignment]


class ReadDocumentTool(Tool):
    """Read Document
    Parse a document (PDF, Word, PowerPoint, ...) to text, markdown, or structured data.
    """

    # Hidden from the Add-Tool catalog; surfaced (workflow-only) via the
    # BUILTIN_AGENT_TOOLS synthetic-id path. Does not gate tool_manager loading
    # nor synthetic-id execution.
    internal: bool = True

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Bind the tool to the invoker and its conversation/run scope."""
        self.config: Dict[str, Any] = tool_config or {}
        self.user_id: Optional[str] = user_id
        self.tool_id: Optional[str] = self.config.get("tool_id")
        self.conversation_id: Optional[str] = self.config.get("conversation_id")
        self.workflow_run_id: Optional[str] = self.config.get("workflow_run_id")
        self.message_id: Optional[str] = self.config.get("message_id")
        self._last_artifact_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Tool ABC
    # ------------------------------------------------------------------
    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing the ``read_document`` action for tool schemas."""
        return [
            {
                "name": "read_document",
                "description": (
                    "Read a document artifact (pdf/docx/pptx/...) and return its parsed content as "
                    "markdown, plain text, structured JSON (with tables), or chunks. Optionally "
                    "validate the structured result against a json_schema and persist it as a "
                    "downloadable data artifact."
                ),
                "active": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "Document to read; accepts the short ref like `A1` returned by a "
                            "previous artifact action, a full artifact id, or the name/id of a file the user "
                            "attached to this conversation.",
                        },
                        "output": {
                            "type": "string",
                            "enum": ["markdown", "text", "structured", "chunks"],
                            "description": "Shape of the parsed result (default: markdown). Note: "
                            "`structured` always uses the Docling engine regardless of `engine` "
                            "(the `fast` engine is markdown/text only).",
                        },
                        "ocr": {
                            "type": "string",
                            "enum": ["auto", "on", "off"],
                            "description": "OCR mode for scanned pages/images (default: auto, follows server config).",
                        },
                        "pages": {
                            "type": "string",
                            "description": "Optional page range to read, e.g. `1-3` or `2` (best-effort).",
                        },
                        "engine": {
                            "type": "string",
                            "enum": ["auto", "docling", "fast"],
                            "description": "Parser engine (default: auto). `fast` is a lighter "
                            "markdown/text-only engine; it is ignored when `output='structured'`, "
                            "which always uses Docling.",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Optional cap on returned characters.",
                        },
                        "include_tables": {
                            "type": "boolean",
                            "description": "Include extracted tables in the result (default: true).",
                        },
                        "json_schema": {
                            "type": "object",
                            "description": "Optional JSON schema the structured payload must satisfy.",
                        },
                        "persist": {
                            "type": "boolean",
                            "description": "Persist the parsed result as a downloadable data artifact (default true).",
                        },
                    },
                    "required": ["input"],
                },
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements (none beyond a running parsing worker)."""
        return {}

    def get_artifact_id(self, action_name: str, **kwargs: Any) -> Optional[str]:
        """Return the persisted parse artifact id so the UI artifact rail lights up."""
        return self._last_artifact_id

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Dispatch a tool action; only ``read_document`` is supported."""
        self._last_artifact_id = None
        if action_name != "read_document":
            return {"status": "error", "error": f"unknown action: {action_name}"}
        if not self.user_id:
            return {"status": "error", "error": "read_document requires a valid user_id."}
        if self.conversation_id is None and self.workflow_run_id is None:
            return {"status": "error", "error": "read_document requires a conversation_id or workflow_run_id."}
        return self._read(**kwargs)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def _read(self, **kwargs: Any) -> Dict[str, Any]:
        """Resolve the input run-scoped (reject cross-tenant before enqueue), enqueue+await, validate."""
        input_id = kwargs.get("input")
        json_schema = kwargs.get("json_schema")
        if not isinstance(input_id, str) or not input_id.strip():
            return {"status": "error", "error": "input artifact id is required."}
        if json_schema is not None:
            schema_err = self._check_schema(json_schema)
            if schema_err is not None:
                return schema_err

        artifact_id = self._resolve_input(input_id.strip())
        if isinstance(artifact_id, dict):
            return artifact_id  # error payload

        options = {
            "output": kwargs.get("output", "markdown"),
            "ocr": kwargs.get("ocr", "auto"),
            "pages": kwargs.get("pages"),
            "engine": kwargs.get("engine", "auto"),
            "max_chars": kwargs.get("max_chars"),
            "include_tables": kwargs.get("include_tables", True),
            "persist": kwargs.get("persist", True),
            "tool_id": self.tool_id,
        }
        result = self._dispatch(artifact_id, options)
        if result.get("status") == "error":
            return result
        if json_schema is not None:
            valid = self._validate(json_schema, result.get("structured"))
            if valid is not None:
                return valid
        artifact = result.get("artifact")
        if isinstance(artifact, dict) and artifact.get("artifact_id"):
            self._last_artifact_id = artifact["artifact_id"]
        return result

    def _dispatch(self, artifact_id: str, options: Dict[str, Any]) -> Dict[str, Any]:
        """Parse INLINE inside a Celery worker, else dispatch to the parsing queue and await.

        This tool runs in the WEB process (/stream) OR inside a Celery worker
        (headless/scheduled/workflow agents). When it already runs inside a worker that also
        serves the ``parsing`` queue (the shipped default ``-Q docsgpt,parsing``), dispatching
        and blocking on ``get()`` would self-deadlock: concurrent agent tasks each hold a pool
        slot blocked in ``get()`` so ``parse_document`` never gets a free slot. So parse INLINE
        in-process inside a worker; only dispatch+await (degrading on timeout/failure) from web.
        """
        parent = self._parent()

        # ``current_task`` is a Celery proxy: truthy only while this runs inside a worker task,
        # falsy in the web process (the bare proxy is NOT identity-None, so test truthiness).
        if current_task:
            from application.worker import run_parse_document

            try:
                result = run_parse_document(artifact_id, parent, self.user_id, options)
            except Exception as exc:
                logger.exception("read_document: inline parse failed")
                return {"status": "error", "error": f"document parsing failed: {type(exc).__name__}: {exc}"}
            if not isinstance(result, dict):
                return {"status": "error", "error": "document parsing produced an unexpected result."}
            return result

        from celery.exceptions import TimeoutError as CeleryTimeoutError

        from application.api.user.tasks import parse_document

        timeout = float(getattr(settings, "DOCUMENT_PARSE_TIMEOUT", 120))
        queue = getattr(settings, "DOCUMENT_PARSE_QUEUE", "parsing")
        try:
            async_result = parse_document.apply_async(args=[artifact_id, parent, self.user_id, options], queue=queue)
            # The web process (not a worker) awaits here; ``disable_sync_subtasks=False`` keeps
            # the call correct if invoked from a non-prefork (eventlet/gevent) worker where the
            # inline branch above still ran but the blanket guard would otherwise raise.
            result = async_result.get(timeout=timeout, disable_sync_subtasks=False)
        except (CeleryTimeoutError, TimeoutError):
            return {"status": "error", "error": f"document parsing timed out after {int(timeout)}s."}
        except Exception as exc:
            logger.exception("read_document: parse task failed")
            return {"status": "error", "error": f"document parsing failed: {type(exc).__name__}: {exc}"}
        if not isinstance(result, dict):
            return {"status": "error", "error": "document parsing produced an unexpected result."}
        return result

    # ------------------------------------------------------------------
    # Input resolution (run-scoped gate, before enqueue)
    # ------------------------------------------------------------------
    def _resolve_input(self, raw_id: str) -> Any:
        """Resolve a short ref/uuid to a parent-scoped artifact id; an error dict on miss/cross-tenant."""
        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                artifact_id = resolve_artifact_id(
                    repo,
                    raw_id,
                    conversation_id=self.conversation_id,
                    workflow_run_id=self.workflow_run_id,
                )
                artifact = (
                    repo.get_artifact_in_parent(
                        artifact_id,
                        conversation_id=self.conversation_id,
                        workflow_run_id=self.workflow_run_id,
                    )
                    if artifact_id is not None
                    else None
                )
        except Exception:
            logger.exception("read_document: failed to resolve input artifact")
            return {"status": "error", "error": f"failed to resolve input artifact {raw_id}."}
        if artifact is None:
            # Conversation scope only: a raw ref that is not an artifact may name a
            # chat attachment; bridge it on demand. Workflows bridge up front.
            bridged_id = self._bridge_chat_attachment(raw_id)
            if isinstance(bridged_id, dict):
                return bridged_id
            if bridged_id is not None:
                return bridged_id
            return {"status": "error", "error": f"input artifact {raw_id} not found in this conversation/run."}
        return str(artifact_id)

    def _bridge_chat_attachment(self, raw_id: str) -> Any:
        """Bridge a referenced chat attachment to a conversation artifact id; None on miss, error dict on failure."""
        if not self.conversation_id or not self.user_id:
            return None
        attachment = match_attachment(self.config.get("attachments"), raw_id, self.user_id)
        if attachment is None:
            return None
        try:
            return bridge_attachment(attachment, user_id=self.user_id, conversation_id=self.conversation_id)
        except AttachmentBridgeError as exc:
            return {"status": "error", "error": f"failed to attach {raw_id}: {exc}"}

    def _parent(self) -> Dict[str, Any]:
        """Build the run-scoped parent dict passed to the worker for its independent re-resolve."""
        if self.conversation_id is not None:
            parent: Dict[str, Any] = {"conversation_id": self.conversation_id}
            if self.message_id:
                parent["message_id"] = self.message_id
            return parent
        return {"workflow_run_id": self.workflow_run_id}

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------
    @staticmethod
    def _check_schema(json_schema: Any) -> Optional[Dict[str, Any]]:
        """Return an error payload when ``json_schema`` itself is malformed, else None."""
        try:
            normalize_json_schema_payload(json_schema)
        except JsonSchemaValidationError as exc:
            return {"status": "error", "error": f"invalid json_schema: {exc}"}
        return None

    @staticmethod
    def _validate(json_schema: Any, instance: Any) -> Optional[Dict[str, Any]]:
        """Validate ``instance`` against the (already-normalized) json_schema; error payload on mismatch."""
        if jsonschema is None:
            return {"status": "error", "error": "jsonschema is required for json_schema validation."}
        if instance is None:
            return {"status": "error", "error": "json_schema validation requires output='structured'."}
        schema = normalize_json_schema_payload(json_schema)
        try:
            jsonschema.validate(instance=instance, schema=schema)
        except jsonschema.exceptions.ValidationError as exc:
            return {"status": "error", "error": f"parsed structure did not match json_schema: {exc.message}"}
        return None
