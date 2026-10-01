"""Server-side tool that lists and reads the files attached to a conversation.

A synthetic tool (no ``user_tools`` row, no configuration), added to a chat
turn when the conversation has attachments and the model takes tools. It
reaches every file of the conversation, not only this turn's, under the same
``F1..Fn`` refs the turn's manifest shows: the refs come from the attachment
planner itself. Rows are loaded per call and owner-checked, and every piece
of file text returned is fenced as untrusted data.

The tool is never client-side and never approval-gated, so on ``/v1`` it can
neither pause the client nor appear in standard ``tool_calls``; it shows up
only in ``docsgpt`` extension frames.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from docsgpt.agents.attachment_budget import (
    SPREADSHEET_EXTENSIONS,
    SPREADSHEET_MIME_TYPES,
    PlannedFile,
    _attachment_id,
    plan_attachments,
)
from docsgpt.agents.attachment_context import UNTRUSTED_NOTE, fence_file, sanitize_filename
from docsgpt.agents.tools.base import Tool
from docsgpt.agents.turn_capabilities import ATTACHMENTS_TOOL_NAME, TurnCapabilities
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

# Sentinel tools-dict key and ``id``: the executor resolves a tool row by id,
# and this tool has none.
ATTACHMENTS_TOOL_ID = "attachments"

LIST = "attachments_list"
READ = "attachments_read"
ACTIONS: Tuple[str, ...] = (LIST, READ)
# Prefix our action names take when a client tool already uses one of them:
# the client's tool keeps its name, ours moves aside.
COLLISION_PREFIX = "docsgpt_"

DEFAULT_READ_TOKENS = 8000
MAX_READ_TOKENS = 16000
MIN_READ_TOKENS = 200
# Room the label, notes and footer take next to the text, inside the
# per-result cap the handler applies (``TOOL_RESULT_MAX_TOKENS``).
RESULT_OVERHEAD_TOKENS = 600

_REF_RE = re.compile(r"^[Ff]?(\d+)$")
_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:[-–:]\s*(\d*)\s*)?$")

_REASONS = {
    "extraction_failed": "could not be parsed",
    "needs_vision": "needs a model that reads images or scanned PDFs",
    "no_text": "no readable text",
    "conversion_failed": "could not be converted for this model",
}


def build_attachments_tool_config(
    *,
    user: str,
    current_ids: Sequence[str],
    earlier_ids: Sequence[str],
    actions: Optional[Dict[str, str]] = None,
    plan: Optional[Dict[str, Dict[str, Any]]] = None,
    vision: bool = False,
    max_native_parts: int = 0,
) -> Dict[str, Any]:
    """Build the config the executor hands the tool.

    Everything in it is plain data: a paused turn saves its tools and a
    resumed one rebuilds the tool from them.

    Args:
        user: Whose attachments these are; every row is re-checked against it.
        current_ids: This turn's attachment ids, in upload order.
        earlier_ids: Earlier turns' attachment ids, in upload order.
        actions: Our action names as the model sees them, by base name.
        plan: This turn's plan per ref (``status``, ``shown_tokens``, ``reason``).
        vision: The model reads images.
        max_native_parts: Images the tool may still add this turn.

    Returns:
        The config dict.
    """
    return {
        "user": user,
        "current_ids": [str(i) for i in current_ids],
        "earlier_ids": [str(i) for i in earlier_ids],
        "actions": dict(actions or {name: name for name in ACTIONS}),
        "plan": dict(plan or {}),
        "vision": bool(vision),
        "max_native_parts": max(int(max_native_parts or 0), 0),
    }


def _client_action_names(tools_dict: Dict[str, Any]) -> set:
    names = set()
    for tool in tools_dict.values():
        if isinstance(tool, dict) and tool.get("client_side"):
            for action in tool.get("actions") or []:
                if isinstance(action, dict) and action.get("name"):
                    names.add(action["name"])
    return names


def build_attachments_tool_entry(action_names: Dict[str, str]) -> Dict[str, Any]:
    """The synthetic tools-dict entry, with the given LLM-visible action names.

    Args:
        action_names: Base action name to the name the model sees.

    Returns:
        The entry, without ``id`` or ``config``.
    """
    actions = []
    for meta in AttachmentsTool().get_actions_metadata():
        actions.append({**meta, "name": action_names.get(meta["name"], meta["name"]), "active": True})
    return {"name": ATTACHMENTS_TOOL_NAME, "actions": actions}


def add_attachments_tool(
    tools_dict: Dict[str, Any],
    *,
    user: str,
    current_ids: Sequence[str],
    earlier_ids: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """Add the attachments tool to ``tools_dict`` when there are files.

    Mirrors ``add_internal_search_tool``: a sentinel ``id`` so the executor
    can load the row-less tool, and a ``config`` it copies into the tool.
    Call it after client tools are merged: an action name a client tool
    already uses gets a ``docsgpt_`` prefix here, so the client's tool keeps
    its own name.

    Args:
        tools_dict: The turn's tools; mutated in place.
        user: The attachments' owner.
        current_ids: This turn's attachment ids, in upload order.
        earlier_ids: Earlier turns' attachment ids, in upload order.

    Returns:
        The entry's config (the agent fills in the plan later), or None when
        there is nothing to add.
    """
    if not user or not (current_ids or earlier_ids):
        return None
    taken = _client_action_names(tools_dict)
    names = {name: (f"{COLLISION_PREFIX}{name}" if name in taken else name) for name in ACTIONS}
    entry = build_attachments_tool_entry(names)
    entry["id"] = ATTACHMENTS_TOOL_ID
    entry["config"] = build_attachments_tool_config(
        user=user, current_ids=current_ids, earlier_ids=earlier_ids, actions=names
    )
    tools_dict[ATTACHMENTS_TOOL_ID] = entry
    return entry["config"]


def sync_attachments_tool(
    config: Dict[str, Any],
    *,
    capabilities: Optional[TurnCapabilities] = None,
    plan: Any = None,
    max_native_parts: Optional[int] = None,
) -> None:
    """Copy what the turn decided into the tool's config.

    Args:
        config: The config ``add_attachments_tool`` returned.
        capabilities: The turn's capabilities (vision).
        plan: The turn's ``AttachmentPlan``; its statuses show in the listing.
        max_native_parts: Images the tool may still add this turn.
    """
    if capabilities is not None:
        config["vision"] = bool(capabilities.vision)
    if plan is not None:
        config["plan"] = {
            planned.ref: {
                "status": planned.status.value,
                "shown_tokens": int(planned.shown_tokens or 0),
                "native": bool(planned.native),
                "reason": planned.reason,
            }
            for planned in plan.files
        }
    if max_native_parts is not None:
        config["max_native_parts"] = max(int(max_native_parts), 0)


def _ref_caps() -> TurnCapabilities:
    """Capabilities for assigning refs only: planning outcomes are ignored."""
    return TurnCapabilities(
        tool_calling=True,
        vision=False,
        native_pdf=False,
        sandbox=False,
        window=0,
        is_v1=False,
        attachments_tool=True,
        attachments_actions=(READ,),
    )


def assign_refs(current: Sequence[Dict[str, Any]], earlier: Sequence[Dict[str, Any]]) -> List[PlannedFile]:
    """The conversation's files under the refs the planner gives them.

    Runs the planner itself so the refs can never drift from the manifest.

    Args:
        current: This turn's rows, in upload order.
        earlier: Earlier turns' rows, in upload order.

    Returns:
        One entry per ref, in ref order.
    """
    plan = plan_attachments(
        list(current), _ref_caps(), budget=0, earlier=list(earlier), max_native_parts=0,
        sandbox_max_input_bytes=0,
    )
    return plan.files


def _load_rows(ids: List[str], user: str) -> List[Dict[str, Any]]:
    """The owner's rows for ``ids`` (metadata only), in the order of ``ids``."""
    if not ids:
        return []
    with db_readonly() as conn:
        return AttachmentsRepository(conn).list_for_planning(ids, user)


def _load_row(attachment_id: str, user: str) -> Optional[Dict[str, Any]]:
    """The owner's full row, text included."""
    with db_readonly() as conn:
        return AttachmentsRepository(conn).get_any(str(attachment_id), user)


def _metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _extraction(row: Dict[str, Any]) -> Dict[str, Any]:
    value = _metadata(row).get("extraction")
    return value if isinstance(value, dict) else {}


def _is_spreadsheet(planned: PlannedFile) -> bool:
    extension = os.path.splitext(planned.filename)[1].lower()
    return extension in SPREADSHEET_EXTENSIONS or planned.mime_type.lower() in SPREADSHEET_MIME_TYPES


def _parse_range(spec: Any) -> Optional[Tuple[int, Optional[int]]]:
    """``"5"``, ``"5-9"`` or ``"5-"`` as 1-based ``(first, last)``."""
    if isinstance(spec, int):
        return (spec, spec) if spec >= 1 else None
    match = _RANGE_RE.match(str(spec or ""))
    if not match:
        return None
    first = int(match.group(1))
    last_text = match.group(2)
    if match.group(0).strip().isdigit():
        last: Optional[int] = first
    else:
        last = int(last_text) if last_text else None
    if first < 1 or (last is not None and last < first):
        return None
    return first, last


def _encoding():
    from docsgpt.utils import get_encoding

    return get_encoding()


class AttachmentsTool(Tool):
    """Attachments

    Lists and reads the files attached anywhere in the conversation, by the
    ``F#`` refs of the turn's manifest.
    """

    internal = True

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.user: Optional[str] = self.config.get("user")
        self._files: Optional[List[PlannedFile]] = None

    # ---- Tool interface ----

    def execute_action(self, action_name: str, **kwargs: Any) -> str:
        """Run one action.

        Args:
            action_name: ``attachments_list`` or ``attachments_read`` (with
                the collision prefix, if any).
            **kwargs: The action's arguments.

        Returns:
            Text for the model.
        """
        action = action_name.removeprefix(COLLISION_PREFIX)
        if not self.user:
            return "Error: attachments are unavailable in this context."
        try:
            if action == LIST:
                return self._list()
            if action == READ:
                return self._read(
                    kwargs.get("ref"),
                    offset=kwargs.get("offset"),
                    max_tokens=kwargs.get("max_tokens"),
                    rows=kwargs.get("rows"),
                )
        except Exception:
            logger.exception("attachments tool: %s failed", action)
            return "Error: the attachments could not be read right now."
        return f"Unknown action: {action_name}"

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": LIST,
                "description": (
                    "List the files attached in this conversation, with their F# refs, size and "
                    "whether each is already in your context."
                ),
                "parameters": {"properties": {}},
            },
            {
                "name": READ,
                "description": (
                    "Read an attached file by ref, a slice at a time; the result says where to "
                    "continue. Use rows for spreadsheets and CSV."
                ),
                "parameters": {
                    "properties": {
                        "ref": {
                            "type": "string",
                            "description": "File ref from the attachments list, e.g. F3.",
                            "filled_by_llm": True,
                            "required": True,
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Token offset to start at (default 0).",
                            "filled_by_llm": True,
                            "required": False,
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": f"Tokens to return (default {DEFAULT_READ_TOKENS}, max {MAX_READ_TOKENS}).",
                            "filled_by_llm": True,
                            "required": False,
                        },
                        "rows": {
                            "type": "string",
                            "description": "Line range such as 100-200 (1-based, the header is row 1).",
                            "filled_by_llm": True,
                            "required": False,
                        },
                    }
                },
            },
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        return {}

    # ---- Scope ----

    def _action(self, base: str) -> str:
        return (self.config.get("actions") or {}).get(base, base)

    def files(self) -> List[PlannedFile]:
        """The conversation's files under their refs, loaded once per tool."""
        if self._files is None:
            current_ids = [str(i) for i in self.config.get("current_ids") or []]
            earlier_ids = [str(i) for i in self.config.get("earlier_ids") or [] if str(i) not in current_ids]
            rows = {_attachment_id(r): r for r in _load_rows(list(dict.fromkeys(earlier_ids + current_ids)), self.user)}
            self._files = assign_refs(
                [rows[i] for i in current_ids if i in rows],
                [rows[i] for i in earlier_ids if i in rows],
            )
        return self._files

    def _find(self, ref: Any) -> Tuple[Optional[PlannedFile], str]:
        files = self.files()
        match = _REF_RE.match(str(ref or "").strip())
        wanted = f"F{int(match.group(1))}" if match else str(ref or "").strip()
        for planned in files:
            if planned.ref == wanted:
                return planned, wanted
        return None, wanted

    def _unknown(self, wanted: str) -> str:
        files = self.files()
        if not files:
            return "No files are attached in this conversation."
        known = f"{files[0].ref}–{files[-1].ref}" if len(files) > 1 else files[0].ref
        return f"Unknown ref {wanted or '(none)'}. The files are {known}; call {self._action(LIST)} to see them."

    def _plan_info(self, planned: PlannedFile) -> Dict[str, Any]:
        info = (self.config.get("plan") or {}).get(planned.ref)
        return info if isinstance(info, dict) else {}

    # ---- attachments_list ----

    def _status(self, planned: PlannedFile) -> str:
        info = self._plan_info(planned)
        status = info.get("status") or ("available" if planned.current else "earlier")
        if status == "partial":
            return f"partial (tokens 1–{int(info.get('shown_tokens') or 0):,} are in your context)"
        if status == "inline":
            return "inline (in your context)"
        if self._has_text(planned):
            return status
        reason = (info.get("reason") if status == "unreadable" else None) or self._unreadable_reason(planned)
        return f"{status} ({_REASONS.get(reason or 'no_text', 'no readable text')})"

    @staticmethod
    def _has_text(planned: PlannedFile) -> bool:
        status = _extraction(planned.attachment).get("status")
        return (status in (None, "ok")) and planned.text_tokens > 0

    @staticmethod
    def _unreadable_reason(planned: PlannedFile) -> Optional[str]:
        status = _extraction(planned.attachment).get("status")
        if status == "failed":
            return "extraction_failed"
        if status == "no_text":
            return "no_text"
        return None

    @staticmethod
    def _size(planned: PlannedFile) -> str:
        parts = []
        extraction = _extraction(planned.attachment)
        if extraction.get("truncated") and planned.original_tokens > planned.text_tokens:
            parts.append(
                f"{planned.text_tokens:,} of ~{planned.original_tokens:,} tokens stored (cut at upload)"
            )
        elif planned.text_tokens:
            parts.append(f"{planned.text_tokens:,} tokens")
        if planned.page_count:
            parts.append(f"{planned.page_count:,} pages")
        return ", ".join(parts)

    def _list(self) -> str:
        files = self.files()
        if not files:
            return "No files are attached in this conversation."
        lines = []
        for planned in files:
            fields = [f"{planned.ref} {sanitize_filename(planned.filename)}", planned.mime_type]
            size = self._size(planned)
            if size:
                fields.append(size)
            fields.append(self._status(planned))
            lines.append("- " + " | ".join(fields))
        return (
            f"{len(files)} file(s) in this conversation:\n" + "\n".join(lines)
            + f"\nRead one with {self._action(READ)}(ref=\"F#\")."
        )

    # ---- attachments_read ----

    def _read_budget(self, max_tokens: Any) -> int:
        from docsgpt.core.settings import settings

        try:
            wanted = int(max_tokens) if max_tokens not in (None, "") else DEFAULT_READ_TOKENS
        except (TypeError, ValueError):
            wanted = DEFAULT_READ_TOKENS
        cap = MAX_READ_TOKENS
        result_cap = int(getattr(settings, "TOOL_RESULT_MAX_TOKENS", 0) or 0)
        if result_cap > 0:
            cap = min(cap, max(result_cap - RESULT_OVERHEAD_TOKENS, MIN_READ_TOKENS))
        return max(min(wanted, cap), MIN_READ_TOKENS)

    def _content(self, planned: PlannedFile) -> Optional[Dict[str, Any]]:
        return _load_row(planned.attachment_ids[0], self.user)

    def _read(self, ref: Any, *, offset: Any = None, max_tokens: Any = None, rows: Any = None) -> str:
        planned, wanted = self._find(ref)
        if planned is None:
            return self._unknown(wanted)
        row = self._content(planned)
        if row is None:
            return f"{planned.ref} is no longer available."
        name = sanitize_filename(planned.filename)
        text = str(row.get("content") or "")
        budget = self._read_budget(max_tokens)
        if not text.strip():
            reason = self._unreadable_reason(planned)
            why = _REASONS.get(reason or "no_text", "no readable text")
            return f"{planned.ref} {name} has no readable text ({why}); its content cannot be read here."
        if rows not in (None, ""):
            return self._read_rows(planned, row, text, rows, budget)
        return self._read_tokens(planned, row, text, offset, budget)

    def _cut_note(self, planned: PlannedFile, row: Dict[str, Any], stored: int) -> str:
        extraction = _extraction(row)
        original = int(extraction.get("original_tokens") or 0)
        if not extraction.get("truncated") or original <= stored:
            return ""
        return (
            f"The file was cut at upload: only tokens 1–{stored:,} of ~{original:,} were stored; "
            f"tokens {stored + 1:,}–{original:,} are not available."
        )

    def _read_tokens(
        self, planned: PlannedFile, row: Dict[str, Any], text: str, offset: Any, budget: int
    ) -> str:
        name = sanitize_filename(planned.filename)
        encoding = _encoding()
        ids = encoding.encode_ordinary(text)
        total = len(ids)
        try:
            start = max(int(offset or 0), 0)
        except (TypeError, ValueError):
            start = 0
        cut = self._cut_note(planned, row, total)
        if start >= total:
            message = f"{planned.ref} {name}: offset {start:,} is past the end of the stored text ({total:,} tokens)."
            return f"{message} {cut}" if cut else message
        end = min(start + budget, total)
        body = encoding.decode(ids[start:end])
        shown = f"tokens {start + 1:,}–{end:,} of {total:,}"
        footer = f"[{planned.ref} {name}: showing {shown}."
        if end < total:
            footer += f' Continue with {self._action(READ)}(ref="{planned.ref}", offset={end}).]'
        elif cut:
            footer += f" End of the stored text. {cut}]"
        else:
            footer += " End of file.]"
        return "\n".join([UNTRUSTED_NOTE, fence_file(planned.ref, planned.filename, body, range=shown), footer])

    def _read_rows(
        self, planned: PlannedFile, row: Dict[str, Any], text: str, rows: Any, budget: int
    ) -> str:
        name = sanitize_filename(planned.filename)
        bounds = _parse_range(rows)
        if bounds is None:
            return f'Invalid rows "{rows}": use a 1-based range such as "100-200".'
        lines = text.split("\n")
        total = len(lines)
        first, last = bounds
        if first > total:
            return f"{planned.ref} {name} has {total:,} rows; row {first:,} is past the end."
        last = min(last or total, total)
        encoding = _encoding()
        picked: List[str] = []
        used = 0
        if first > 1:
            header = lines[0]
            picked.append(header)
            used += len(encoding.encode_ordinary(header)) + 1
        end = first - 1
        for index in range(first - 1, last):
            cost = len(encoding.encode_ordinary(lines[index])) + 1
            if used + cost > budget and end >= first:
                break
            picked.append(lines[index])
            used += cost
            end = index + 1
        shown = f"rows {first:,}–{end:,} of {total:,}"
        footer = f"[{planned.ref} {name}: showing {shown}" + (" (row 1, the header, repeated first)" if first > 1 else "")
        if end < total:
            footer += f'. Continue with {self._action(READ)}(ref="{planned.ref}", rows="{end + 1}-{min(end + (end - first + 1), total)}").]'
        else:
            cut = self._cut_note(planned, row, len(encoding.encode_ordinary(text)))
            footer += f". End of the stored text. {cut}]" if cut else ". End of file.]"
        body = "\n".join(picked)
        return "\n".join([UNTRUSTED_NOTE, fence_file(planned.ref, planned.filename, body, range=shown), footer])

