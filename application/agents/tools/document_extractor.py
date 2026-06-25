"""Document Extractor tool: convert an input artifact to schema-validated structured JSON via Docling.

The ``extract_document`` action stages a parent-scoped input artifact into the
sandbox workspace, then runs a FIXED program that uses Docling (MIT) to convert
the document (pdf/docx/pptx/...) into a compact structured payload (markdown +
tables + a structured dict). The program reads its parameters from a JSON DATA
file (``json.load``) and never string-interpolates untrusted content into code,
so a malicious filename/parameter is treated as literal data, not executed. When
a ``json_schema`` is supplied the compact ``structured`` payload is validated
through the existing jsonschema path; the extracted JSON may also be persisted as
a ``data`` artifact by reference.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from application.agents.tools.artifact_ref import resolve_artifact_id
from application.agents.tools.base import Tool
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.settings import settings
from application.sandbox.artifacts_capture import QuotaExceeded, persist_new_artifact
from application.sandbox.sandbox_creator import SandboxCreator
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.session import db_readonly
from application.storage.storage_creator import StorageCreator
from application.utils import safe_filename

logger = logging.getLogger(__name__)

try:
    import jsonschema
except Exception:  # pragma: no cover - jsonschema is a declared dependency
    jsonschema = None  # type: ignore[assignment]

# Cap the extracted payload returned to the LLM so a huge document can't flood
# context; the full extraction is still persisted as a ``data`` artifact. When the
# markdown exceeds the cap a head+tail window is kept so both the document's
# beginning AND end (e.g. totals/signatures) survive within the byte budget.
_MARKDOWN_MAX_BYTES = 8000
_MAX_TABLES_RETURNED = 20
# Per-table content caps so a single giant table can't bloat context.
_MAX_TABLE_ROWS = 50
_MAX_CELL_CHARS = 200

# Mime + kind for the persisted extraction artifact (JSON by reference).
_EXTRACT_MIME = "application/json"
_EXTRACT_KIND = "data"

# FIXED extraction program. It reads ``params.json`` (the input path + caps) as
# DATA and writes ``result.json`` to the workspace. The params are NEVER
# string-interpolated into the program; ``{params_path}``/``{result_path}`` are
# server-controlled path literals only. A missing Docling install yields a clean
# ``{"error": ...}`` result rather than a traceback.
_EXTRACT_PROGRAM = (
    "import json\n"
    "params = json.load(open({params_path!r}))\n"
    "result_path = {result_path!r}\n"
    "def _write(obj):\n"
    "    with open(result_path, 'w') as fh:\n"
    "        json.dump(obj, fh)\n"
    "try:\n"
    "    from docling.document_converter import DocumentConverter\n"
    "except Exception as exc:\n"
    "    _write({{'error': 'docling is not available in the sandbox runner: '\n"
    "            + type(exc).__name__ + ': ' + str(exc)}})\n"
    "    raise SystemExit(0)\n"
    "src = params['input_path']\n"
    "md_cap = int(params.get('markdown_max_bytes', 0)) or None\n"
    "table_cap = int(params.get('max_tables', 0)) or None\n"
    "try:\n"
    "    converter = DocumentConverter()\n"
    "    doc = converter.convert(src).document\n"
    "    markdown = doc.export_to_markdown()\n"
    "    structured = doc.export_to_dict()\n"
    "    tables = []\n"
    "    for tbl in getattr(doc, 'tables', []) or []:\n"
    "        try:\n"
    "            df = tbl.export_to_dataframe()\n"
    "            tables.append({{'columns': [str(c) for c in df.columns],\n"
    "                           'rows': df.astype(str).values.tolist()}})\n"
    "        except Exception:\n"
    "            try:\n"
    "                tables.append({{'markdown': tbl.export_to_markdown()}})\n"
    "            except Exception:\n"
    "                continue\n"
    "        if table_cap is not None and len(tables) >= table_cap:\n"
    "            break\n"
    "    page_count = len(getattr(doc, 'pages', {{}}) or {{}})\n"
    "    md_truncated = False\n"
    "    if md_cap is not None and len(markdown) > md_cap:\n"
    "        head = md_cap // 2\n"
    "        tail = md_cap - head\n"
    "        dropped = len(markdown) - head - tail\n"
    "        markdown = (markdown[:head]\n"
    "                    + '\\n\\n...[truncated ' + str(dropped) + ' chars]...\\n\\n'\n"
    "                    + markdown[-tail:])\n"
    "        md_truncated = True\n"
    "    _write({{'ok': True, 'markdown': markdown, 'markdown_truncated': md_truncated,\n"
    "            'tables': tables, 'page_count': page_count, 'structured': structured}})\n"
    "except Exception as exc:\n"
    "    _write({{'error': 'docling extraction failed: ' + type(exc).__name__ + ': ' + str(exc)}})\n"
)


def truncate_text_head_tail(text: str, max_bytes: Optional[int] = None) -> str:
    """Bound text to a head+tail byte window so a large file can't flood context."""
    cap = int(max_bytes or _MARKDOWN_MAX_BYTES)
    if cap <= 0:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= cap:
        return text
    head = cap // 2
    tail = cap - head
    dropped = len(encoded) - head - tail
    head_text = encoded[:head].decode("utf-8", errors="ignore")
    tail_text = encoded[-tail:].decode("utf-8", errors="ignore")
    return f"{head_text}\n\n...[truncated {dropped} bytes]...\n\n{tail_text}"


def extract_markdown_from_bytes(
    data: bytes,
    filename: str,
    session_id: str,
    *,
    markdown_max_bytes: Optional[int] = None,
) -> Optional[str]:
    """Run the fixed Docling program in a sandbox session and return the document's markdown, or None.

    The bytes ride in as a DATA file the fixed program reads; nothing untrusted is
    interpolated into the program. Returns ``None`` when Docling is unavailable or
    extraction fails (the caller decides how to degrade).
    """
    safe_name = safe_filename(filename) or "document"
    token = uuid.uuid4().hex
    token_dir = f"extract/{token}"
    input_path = f"{token_dir}/inputs/{safe_name}"
    params_path = f"{token_dir}/params.json"
    result_path = f"{token_dir}/result.json"
    params = {
        "input_path": input_path,
        "markdown_max_bytes": int(markdown_max_bytes or _MARKDOWN_MAX_BYTES),
        "max_tables": 0,
    }
    program = _EXTRACT_PROGRAM.format(params_path=params_path, result_path=result_path)
    timeout = float(getattr(settings, "SANDBOX_EXEC_TIMEOUT", 60))

    manager = SandboxCreator.get_manager()
    try:
        manager.open(session_id, ttl=timeout)
    except Exception:
        logger.exception("extract_markdown_from_bytes: failed to open sandbox session")
        return None
    try:
        manager.put_file(session_id, input_path, data)
        manager.put_file(session_id, params_path, json.dumps(params).encode("utf-8"))
        result = manager.exec(session_id, program, timeout=timeout)
        if not result.ok:
            return None
        raw = manager.get_file(session_id, result_path)
    except Exception:
        logger.exception("extract_markdown_from_bytes: extraction failed")
        return None
    finally:
        manager.remove_path(session_id, token_dir)
        try:
            manager.close(session_id)
        except Exception:
            logger.exception("extract_markdown_from_bytes: session close failed")

    if not raw:
        return None
    try:
        extracted = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(extracted, dict) or extracted.get("error") or not extracted.get("ok"):
        return None
    markdown = extracted.get("markdown")
    return markdown if isinstance(markdown, str) else None


class DocumentExtractorTool(Tool):
    """Document Extractor
    Convert an input document artifact (pdf/docx/pptx/...) to compact, schema-validated structured JSON via Docling.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Bind the tool to the invoker and its conversation/run-scoped sandbox session."""
        self.config: Dict[str, Any] = tool_config or {}
        self.user_id: Optional[str] = user_id
        self.tool_id: Optional[str] = self.config.get("tool_id")
        self.conversation_id: Optional[str] = self.config.get("conversation_id")
        self.workflow_run_id: Optional[str] = self.config.get("workflow_run_id")
        self._last_artifact_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Tool ABC
    # ------------------------------------------------------------------
    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing the ``extract_document`` action for tool schemas."""
        return [
            {
                "name": "extract_document",
                "description": (
                    "Extract a document artifact (pdf/docx/pptx/...) into compact structured JSON "
                    "(markdown + tables + structure) using Docling. Optionally validate the result "
                    "against a json_schema and persist it as a downloadable data artifact."
                ),
                "active": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "Document (from this conversation/run) to extract; accepts the short "
                            "ref like `A1` returned by a previous artifact action, or the full artifact id.",
                        },
                        "json_schema": {
                            "type": "object",
                            "description": "Optional JSON schema the extracted 'structured' payload must satisfy.",
                        },
                        "persist": {
                            "type": "boolean",
                            "description": "Persist the extracted JSON as a downloadable data artifact (default true).",
                        },
                    },
                    "required": ["input"],
                },
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements (none beyond the deployment sandbox backend)."""
        return {}

    def get_artifact_id(self, action_name: str, **kwargs: Any) -> Optional[str]:
        """Return the persisted extraction artifact id so the UI artifact rail lights up."""
        return self._last_artifact_id

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Dispatch a tool action; only ``extract_document`` is supported."""
        self._last_artifact_id = None
        if action_name != "extract_document":
            return {"status": "error", "error": f"unknown action: {action_name}"}
        if not self.user_id:
            return {"status": "error", "error": "document_extractor requires a valid user_id."}
        if self.conversation_id is None and self.workflow_run_id is None:
            return {"status": "error", "error": "document_extractor requires a conversation_id or workflow_run_id."}
        return self._extract(**kwargs)

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _extract(self, **kwargs: Any) -> Dict[str, Any]:
        """Stage the parent-scoped input, run the fixed Docling program, validate, and (optionally) persist."""
        input_id = kwargs.get("input")
        json_schema = kwargs.get("json_schema")
        should_persist = kwargs.get("persist", True)

        if not isinstance(input_id, str) or not input_id.strip():
            return {"status": "error", "error": "input artifact id is required."}
        if json_schema is not None:
            schema_err = self._check_schema(json_schema)
            if schema_err is not None:
                return schema_err

        session_id = self._resolve_session_id()
        if session_id is None:
            return {"status": "error", "error": "document_extractor requires a conversation_id or workflow_run_id."}

        loaded = self._load_input(input_id.strip())
        if loaded.get("error"):
            return {"status": "error", "error": loaded["error"]}

        max_input = int(getattr(settings, "SANDBOX_MAX_INPUT_BYTES", 25 * 1024 * 1024))
        if len(loaded["data"]) > max_input:
            return {
                "status": "error",
                "error": f"input artifact is too large: {len(loaded['data'])} bytes exceeds the "
                f"{max_input}-byte sandbox input cap.",
            }

        token = uuid.uuid4().hex
        token_dir = f"extract/{token}"
        input_path = f"{token_dir}/inputs/{loaded['filename']}"
        params_path = f"{token_dir}/params.json"
        result_path = f"{token_dir}/result.json"
        params = {
            "input_path": input_path,
            "markdown_max_bytes": _MARKDOWN_MAX_BYTES,
            "max_tables": _MAX_TABLES_RETURNED,
        }
        program = _EXTRACT_PROGRAM.format(params_path=params_path, result_path=result_path)
        timeout = float(getattr(settings, "SANDBOX_EXEC_TIMEOUT", 60))

        manager = SandboxCreator.get_manager()
        try:
            manager.open(session_id, ttl=timeout)
        except Exception as exc:
            logger.exception("document_extractor: failed to open sandbox session")
            return {"status": "error", "error": f"sandbox unavailable: {type(exc).__name__}: {exc}"}
        try:
            # The document bytes and the params ride in as DATA files the program
            # reads; neither is interpolated into the program, so a hostile
            # filename or document content stays inert data.
            manager.put_file(session_id, input_path, loaded["data"])
            manager.put_file(session_id, params_path, json.dumps(params).encode("utf-8"))
            result = manager.exec(session_id, program, timeout=timeout)
            if not result.ok:
                detail = (
                    f"{result.error_name}: {result.error_value}"
                    if result.error_name
                    else (result.error_value or "extraction failed")
                )
                return {"status": "error", "error": f"extraction failed: {detail}"}
            raw = manager.get_file(session_id, result_path)
        except Exception as exc:
            logger.exception("document_extractor: extraction failed")
            return {"status": "error", "error": f"extraction failed: {type(exc).__name__}: {exc}"}
        finally:
            # Drop this extraction's scratch dir (staged input + params + result)
            # before close so a warm/reused session doesn't accumulate on disk.
            manager.remove_path(session_id, token_dir)
            try:
                manager.close(session_id)
            except Exception:
                logger.exception("document_extractor: session close failed")

        return self._finish(raw, loaded, json_schema, should_persist)

    def _finish(
        self,
        raw: bytes,
        loaded: Dict[str, Any],
        json_schema: Any,
        should_persist: Any,
    ) -> Dict[str, Any]:
        """Parse the program result, validate against json_schema, and shape the compact payload."""
        if not raw:
            return {"status": "error", "error": "extractor produced no result."}
        try:
            extracted = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {"status": "error", "error": "extractor produced an invalid result."}
        if isinstance(extracted, dict) and extracted.get("error"):
            return {"status": "error", "error": str(extracted["error"])}
        if not isinstance(extracted, dict) or not extracted.get("ok"):
            return {"status": "error", "error": "extractor produced an unexpected result."}

        structured = extracted.get("structured")
        if json_schema is not None:
            valid = self._validate(json_schema, structured)
            if valid is not None:
                return valid

        compact = self._compact_payload(extracted)
        payload: Dict[str, Any] = {"status": "ok", "structured": compact}
        if should_persist:
            try:
                ref = self._persist(extracted, loaded["title"])
            except QuotaExceeded as exc:
                # Extraction itself succeeded; surface the quota error alongside
                # the in-context structured result rather than failing the call.
                payload["artifact_error"] = str(exc)
                ref = None
            if ref is not None:
                self._last_artifact_id = ref["artifact_id"]
                payload["artifact"] = ref
        return payload

    # ------------------------------------------------------------------
    # Input / payload helpers
    # ------------------------------------------------------------------
    def _load_input(self, raw_id: str) -> Dict[str, Any]:
        """Resolve a short ref/uuid, then fetch the parent-scoped input bytes; never cross-tenant."""
        artifact_id: Optional[str] = raw_id
        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                # A ref (A1/A2/...) resolves to an id within this parent only; the
                # resolved id is re-checked through the parent-scoped gate so a ref
                # can never reach another tenant.
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
                if artifact is None:
                    return {"error": f"input artifact {raw_id} not found in this conversation/run."}
                version = repo.get_version(artifact_id, artifact["current_version"])
        except Exception:
            logger.exception("document_extractor: failed to load input artifact")
            return {"error": f"failed to load input artifact {raw_id}."}
        if not version or not version.get("storage_path"):
            return {"error": f"input artifact {raw_id} has no stored content."}
        display_name = version.get("filename") or artifact.get("title") or artifact_id
        filename = safe_filename(display_name)
        try:
            file_obj = StorageCreator.get_storage().get_file(version["storage_path"])
            data = file_obj.read()
        except Exception:
            logger.exception("document_extractor: failed to read input artifact bytes")
            return {"error": f"failed to read input artifact {raw_id}."}
        return {"data": data, "filename": filename, "title": display_name}

    def _compact_payload(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """Shape the LLM-facing payload: markdown window + bounded tables + structure summary, no raw bytes."""
        structured = extracted.get("structured")
        return {
            "markdown": extracted.get("markdown", ""),
            "markdown_truncated": bool(extracted.get("markdown_truncated")),
            "tables": [self._compact_table(tbl) for tbl in extracted.get("tables", [])],
            "page_count": extracted.get("page_count", 0),
            "summary": self._structure_summary(structured),
        }

    @staticmethod
    def _compact_table(table: Any) -> Any:
        """Bound a single table's rows and cell sizes so one giant table can't bloat context."""
        if not isinstance(table, dict):
            return table

        def _cell(value: Any) -> Any:
            if isinstance(value, str) and len(value) > _MAX_CELL_CHARS:
                return value[:_MAX_CELL_CHARS] + "...[truncated]"
            return value

        rows = table.get("rows")
        if not isinstance(rows, list):
            return table
        capped = [[_cell(c) for c in row] if isinstance(row, list) else _cell(row) for row in rows[:_MAX_TABLE_ROWS]]
        compact = dict(table)
        compact["rows"] = capped
        if len(rows) > _MAX_TABLE_ROWS:
            compact["rows_truncated"] = True
            compact["total_rows"] = len(rows)
        return compact

    @staticmethod
    def _structure_summary(structured: Any) -> Dict[str, Any]:
        """Summarize the Docling structured dict by top-level element counts (keeps context compact)."""
        if not isinstance(structured, dict):
            return {}
        counts: Dict[str, int] = {}
        for key in ("texts", "tables", "pictures", "groups", "pages"):
            value = structured.get(key)
            if isinstance(value, (list, dict)):
                counts[key] = len(value)
        return counts

    def _persist(self, extracted: Dict[str, Any], title: str) -> Optional[Dict[str, Any]]:
        """Persist the full extraction JSON as a ``data`` artifact by reference; return its reference."""
        try:
            data = json.dumps(extracted).encode("utf-8")
        except (TypeError, ValueError):
            logger.exception("document_extractor: extraction is not JSON-serializable")
            return None
        filename = f"{safe_filename(title) or 'extract'}.extract.json"
        ref = persist_new_artifact(
            user_id=self.user_id,
            kind=_EXTRACT_KIND,
            data=data,
            filename=filename,
            mime_type=_EXTRACT_MIME,
            title=f"{title} (extracted)",
            conversation_id=self.conversation_id,
            workflow_run_id=self.workflow_run_id,
            produced_by={"tool": "document_extractor", "action": "extract_document", "tool_id": self.tool_id},
        )
        return ref

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
        schema = normalize_json_schema_payload(json_schema)
        try:
            jsonschema.validate(instance=instance, schema=schema)
        except jsonschema.exceptions.ValidationError as exc:
            return {"status": "error", "error": f"extracted structure did not match json_schema: {exc.message}"}
        return None

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _resolve_session_id(self) -> Optional[str]:
        """Derive the sandbox session id from the bound conversation/run; sanitize to the gateway charset."""
        raw = self.conversation_id or self.workflow_run_id
        if not raw:
            return None
        sanitized = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(raw))
        return sanitized or None
