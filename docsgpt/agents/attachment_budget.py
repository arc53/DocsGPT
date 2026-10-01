"""Decide which of a conversation's attached files go into this turn's context.

Pure planning: no I/O, no model calls. The agent computes one
:class:`AttachmentPlan` per turn from the attachment rows, the turn's
:class:`~docsgpt.agents.turn_capabilities.TurnCapabilities` and a token
budget, then message building, the context gate and the LLM handler all read
the same plan:

* every file gets a stable conversation-scoped ref ``F1..Fn`` in upload order
  (earlier turns first), with re-sent copies collapsed onto the first ref by
  ``content_hash`` (falling back to filename and byte size);
* files from earlier turns are never inlined again (status ``earlier``);
* this turn's files are walked in upload order: a file that fits whole is
  inlined (as a native part when the model reads its type, else as text); a
  file that does not fit is skipped while later files that do fit are still
  inlined (back-fill); the first skipped text file then gets the remaining
  budget as a partial head with a marker, when enough is left for that to be
  useful; native parts are never cut;
* the rest are left for a tool (``tool``), a spreadsheet goes to the code
  sandbox with a short preview (``sandbox``), and with no tool to reach them
  they are ``not_included``;
* a zip is listed (``archive``) but never inlined: the worker unpacked it,
  and its members follow it in the rows as files of their own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from docsgpt.agents.turn_capabilities import TurnCapabilities

# Context the provider charges for one image part. Matches the compression
# token counter's per-image estimate; real cost varies by provider and size.
IMAGE_PART_TOKENS = 1500
# Extra context a native PDF part costs per page on top of its text: providers
# send each page as an image too. A conservative average across providers.
NATIVE_PDF_PAGE_TOKENS = 500
# Page images a PDF becomes on a vision model without native PDF support
# (``LLMHandler._convert_pdf_to_images``).
SYNTHETIC_PDF_MAX_PAGES = 20
# Label and untrusted-data fence around one inlined file.
PER_FILE_OVERHEAD_TOKENS = 40
# The "showing tokens 1-N of M" marker after a partial file.
PARTIAL_MARKER_TOKENS = 60
# The manifest: a fixed header plus one line per file.
MANIFEST_BASE_TOKENS = 150
MANIFEST_LINE_TOKENS = 30
# A partial head shorter than this is not worth sending.
MIN_PARTIAL_TOKENS = 4000
# Head of a spreadsheet inlined next to its sandbox reference.
SPREADSHEET_PREVIEW_TOKENS = 1000
# Share of the window that retrieved documents may hold back from the budget;
# beyond it they are shed lowest-ranked first.
DOCS_RESERVE_SHARE = 0.15
# Share of the window kept free for the answer.
OUTPUT_RESERVE_SHARE = 0.1

SPREADSHEET_EXTENSIONS = frozenset({".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".ods"})
SPREADSHEET_MIME_TYPES = frozenset(
    {
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.ms-excel",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.spreadsheet",
    }
)


class FileStatus(str, Enum):
    """Where a planned file ends up this turn."""

    INLINE = "inline"
    PARTIAL = "partial"
    TOOL = "tool"
    SANDBOX = "sandbox"
    EARLIER = "earlier"
    NOT_INCLUDED = "not_included"
    UNREADABLE = "unreadable"
    ARCHIVE = "archive"


@dataclass(eq=False)
class PlannedFile:
    """One conversation file and what this turn does with it.

    Attributes:
        ref: Stable conversation-scoped reference, ``F1``, ``F2``, ...
        attachment: The representative attachment row.
        attachment_ids: Every attachment id collapsed onto this ref.
        filename: The file's name.
        mime_type: The file's MIME type.
        current: Attached on this turn (else on an earlier one).
        status: Where the file ends up this turn.
        native: Sent as a native part (image, PDF, page images).
        text_tokens: Tokens of the stored text (the ``M`` of a partial).
        original_tokens: Tokens the parser extracted before the stored cut.
        page_count: Pages, for a PDF the worker could open.
        inline_tokens: Context this plan spends on the file.
        shown_tokens: Text tokens shown inline (the ``N`` of a partial,
            the preview of a sandbox file).
        native_parts: Native parts the file is sent as.
        reason: Why the file was left out, when it was.
        sandbox_eligible: The code sandbox is in the turn and can take the
            file (its size is within ``SANDBOX_MAX_INPUT_BYTES`` or unknown).
    """

    ref: str
    attachment: Dict[str, Any]
    attachment_ids: Tuple[str, ...]
    filename: str
    mime_type: str
    current: bool
    status: FileStatus = FileStatus.NOT_INCLUDED
    native: bool = False
    text_tokens: int = 0
    original_tokens: int = 0
    page_count: Optional[int] = None
    inline_tokens: int = 0
    shown_tokens: int = 0
    native_parts: int = 0
    reason: Optional[str] = None
    sandbox_eligible: bool = False

    @property
    def in_context(self) -> bool:
        """Some of the file's content is in this turn's context."""
        return self.inline_tokens > 0


@dataclass(eq=False)
class AttachmentPlan:
    """The per-turn attachment plan.

    Attributes:
        files: One entry per ref, in upload order.
        capabilities: The capabilities the plan was made for.
        budget: Tokens the plan was allowed to spend.
    """

    files: List[PlannedFile]
    capabilities: TurnCapabilities
    budget: int
    _by_id: Dict[str, PlannedFile] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for planned in self.files:
            for attachment_id in planned.attachment_ids:
                self._by_id[attachment_id] = planned

    @property
    def inline_tokens(self) -> int:
        """Tokens of file content placed in the context."""
        return sum(f.inline_tokens for f in self.files)

    @property
    def native_tokens(self) -> int:
        """Tokens of the native parts (images, PDFs, page images)."""
        return sum(f.inline_tokens for f in self.files if f.native)

    @property
    def native_parts(self) -> int:
        """Native parts sent this turn."""
        return sum(f.native_parts for f in self.files)

    @property
    def manifest_tokens(self) -> int:
        """Estimated size of the manifest; zero when there is nothing to list."""
        return manifest_estimate(len(self.files))

    @property
    def reserved_tokens(self) -> int:
        """Everything the plan adds to the turn: content plus manifest."""
        return self.inline_tokens + self.manifest_tokens if self.files else 0

    @property
    def current_files(self) -> List[PlannedFile]:
        """Files attached on this turn."""
        return [f for f in self.files if f.current]

    def for_attachment(self, attachment_id: Any) -> Optional[PlannedFile]:
        """The planned file an attachment id belongs to.

        Args:
            attachment_id: Any id collapsed onto a ref.

        Returns:
            The planned file, or None for an id the plan does not know.
        """
        return self._by_id.get(str(attachment_id)) if attachment_id is not None else None

    def with_status(self, *statuses: FileStatus) -> List[PlannedFile]:
        """Files whose status is one of ``statuses``."""
        return [f for f in self.files if f.status in statuses]


def manifest_estimate(file_count: int) -> int:
    """Token estimate of a manifest listing ``file_count`` files."""
    if file_count <= 0:
        return 0
    return MANIFEST_BASE_TOKENS + MANIFEST_LINE_TOKENS * file_count


def compute_attachment_budget(
    *,
    window: int,
    share: float,
    system_tokens: int = 0,
    history_tokens: int = 0,
    query_tokens: int = 0,
    docs_tokens: int = 0,
) -> int:
    """Tokens this turn's attachments may take.

    The smaller of ``share`` of the window and the free space left after the
    system prompt (compressed summary included), the post-compression
    history, a bounded reserve for retrieved documents, the answer's reserve
    and the query.

    Args:
        window: The model's context window.
        share: Fraction of the window attachments may take.
        system_tokens: The system prompt, compressed summary included.
        history_tokens: The history replayed this turn, after compression.
        query_tokens: The user's message.
        docs_tokens: Retrieved documents for this turn.

    Returns:
        The budget in tokens, never negative.
    """
    window = max(int(window or 0), 0)
    output_reserve = int(window * OUTPUT_RESERVE_SHARE)
    docs_reserve = min(max(int(docs_tokens), 0), int(window * DOCS_RESERVE_SHARE))
    free = (
        window
        - output_reserve
        - max(int(system_tokens), 0)
        - max(int(history_tokens), 0)
        - max(int(query_tokens), 0)
        - docs_reserve
    )
    return max(min(int(window * share), free), 0)


class _RefRegistry:
    """Hands out conversation refs in upload order, collapsing re-sent copies."""

    def __init__(self) -> None:
        self.files: List[PlannedFile] = []
        self._by_key: Dict[Tuple[Any, ...], PlannedFile] = {}

    def register(self, row: Dict[str, Any], is_current: bool) -> Tuple[PlannedFile, bool]:
        """Give ``row`` its ref.

        Args:
            row: An attachment row.
            is_current: The row was attached on this turn.

        Returns:
            The planned file the row belongs to, and whether it is new (a
            copy of an earlier row is added to that row's ids instead).
        """
        key = _dedupe_key(row)
        attachment_id = _attachment_id(row)
        existing = self._by_key.get(key)
        if existing is not None:
            if attachment_id not in existing.attachment_ids:
                existing.attachment_ids = existing.attachment_ids + (attachment_id,)
            return existing, False
        planned = _new_planned(row, f"F{len(self.files) + 1}", attachment_id, is_current)
        self._by_key[key] = planned
        self.files.append(planned)
        return planned, True


def assign_refs(
    current: Sequence[Dict[str, Any]],
    earlier: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[PlannedFile]:
    """The conversation's files under the refs the planner gives them.

    The single source of ``F#`` refs outside a plan (tools resolving a ref
    the model passes): the same assignment ``plan_attachments`` makes, with
    no budgeting. Earlier rows come first, so a flat list in upload order
    gets the same refs as the split one.

    Args:
        current: This turn's rows, in upload order.
        earlier: Earlier turns' rows, in upload order.

    Returns:
        One entry per ref, in ref order; ``status`` is not planned.
    """
    registry = _RefRegistry()
    for row in earlier or ():
        if isinstance(row, dict):
            registry.register(row, False)
    for row in current or ():
        if isinstance(row, dict):
            registry.register(row, True)
    return registry.files


def plan_attachments(
    current: Sequence[Dict[str, Any]],
    capabilities: TurnCapabilities,
    *,
    budget: int,
    earlier: Optional[Sequence[Dict[str, Any]]] = None,
    max_native_parts: int = 40,
    sandbox_max_input_bytes: Optional[int] = None,
) -> AttachmentPlan:
    """Plan this turn's attachments against a token budget.

    Args:
        current: This turn's attachment rows, in upload order.
        capabilities: The turn's capabilities.
        budget: Tokens the attachments may take (manifest included).
        earlier: Attachment rows from earlier turns of the conversation, in
            upload order. Listed, never inlined.
        max_native_parts: Cap on native parts (images, PDFs, page images).
        sandbox_max_input_bytes: Largest file the sandbox stages; larger
            spreadsheets are planned like any other file. None reads
            ``SANDBOX_MAX_INPUT_BYTES``.

    Returns:
        The plan.
    """
    if sandbox_max_input_bytes is None:
        from docsgpt.core.settings import settings

        sandbox_max_input_bytes = int(settings.SANDBOX_MAX_INPUT_BYTES)

    registry = _RefRegistry()
    files = registry.files

    def register(row: Dict[str, Any], is_current: bool) -> Optional[PlannedFile]:
        planned, _ = registry.register(row, is_current)
        return planned if is_current else None

    for row in earlier or ():
        if isinstance(row, dict):
            planned, is_new = registry.register(row, False)
            if is_new:
                planned.status = FileStatus.EARLIER

    reachable = capabilities.attachments_tool
    walk: List[PlannedFile] = []
    for row in current or ():
        if not isinstance(row, dict):
            continue
        planned = register(row, True)
        if planned is None or any(p is planned for p in walk):
            continue
        if not planned.current:
            # A file the user sent again. A tool can still read the first
            # copy, so it is not inlined a second time; with nothing able to
            # reach it, the re-send is how the user gets it in front of the model.
            if reachable:
                continue
            # Earlier rows are loaded without their text; plan this copy.
            refreshed = _new_planned(row, planned.ref, planned.attachment_ids[0], True)
            refreshed.attachment_ids = planned.attachment_ids
            planned.__dict__.update(refreshed.__dict__)
        walk.append(planned)

    remaining = max(int(budget), 0) - manifest_estimate(len(files))
    native_used = 0
    deferred: List[PlannedFile] = []
    overflow = FileStatus.TOOL if reachable else FileStatus.NOT_INCLUDED

    for planned in walk:
        row = planned.attachment
        has_text = _has_text(row)
        native_ok = capabilities.reads_natively(planned.mime_type) and _native_readable(row)

        if is_archive(row):
            # A zip's members follow it as files of their own; its stored
            # text is only an index of them.
            planned.status = FileStatus.ARCHIVE
            continue

        if not has_text and not native_ok:
            planned.status = FileStatus.UNREADABLE
            planned.reason = _unreadable_reason(row, capabilities)
            continue

        if capabilities.sandbox and _is_spreadsheet(planned) and _fits_sandbox(row, sandbox_max_input_bytes):
            planned.status = FileStatus.SANDBOX
            preview = min(planned.text_tokens, SPREADSHEET_PREVIEW_TOKENS) if has_text else 0
            cost = preview + PER_FILE_OVERHEAD_TOKENS
            if preview and cost <= remaining:
                planned.shown_tokens = preview
                planned.inline_tokens = cost
                remaining -= cost
            continue

        if native_ok:
            parts = _native_parts(planned, capabilities)
            cost = _native_cost(planned, capabilities) + PER_FILE_OVERHEAD_TOKENS
            if native_used + parts > max_native_parts:
                planned.reason = "native_cap"
            elif cost <= remaining:
                planned.status = FileStatus.INLINE
                planned.native = True
                planned.native_parts = parts
                planned.inline_tokens = cost
                native_used += parts
                remaining -= cost
                continue
            else:
                planned.reason = "too_large"

        if has_text:
            cost = planned.text_tokens + PER_FILE_OVERHEAD_TOKENS
            if cost <= remaining:
                planned.status = FileStatus.INLINE
                planned.shown_tokens = planned.text_tokens
                planned.inline_tokens = cost
                planned.reason = None
                remaining -= cost
                continue
            planned.reason = "too_large"
            deferred.append(planned)

        planned.status = overflow

    # The first file that did not fit gets what the whole files left over.
    for planned in deferred:
        head = remaining - PER_FILE_OVERHEAD_TOKENS - PARTIAL_MARKER_TOKENS
        if head >= MIN_PARTIAL_TOKENS:
            planned.status = FileStatus.PARTIAL
            planned.shown_tokens = min(head, planned.text_tokens)
            planned.inline_tokens = (
                planned.shown_tokens + PER_FILE_OVERHEAD_TOKENS + PARTIAL_MARKER_TOKENS
            )
            planned.reason = None
            remaining -= planned.inline_tokens
        break

    if capabilities.sandbox:
        for planned in files:
            planned.sandbox_eligible = _fits_sandbox(planned.attachment, sandbox_max_input_bytes)

    return AttachmentPlan(files=files, capabilities=capabilities, budget=max(int(budget), 0))


def is_archive(row: Dict[str, Any]) -> bool:
    """A zip attachment unpacked into member attachments (``metadata.archive``)."""
    return isinstance(_metadata(row).get("archive"), dict)


def _attachment_id(row: Dict[str, Any]) -> str:
    """The id a row is known by (PG id, else the legacy upload handle)."""
    for key in ("id", "_id", "legacy_mongo_id"):
        value = row.get(key)
        if value:
            return str(value)
    return f"anon-{id(row)}"


def _metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _extraction(row: Dict[str, Any]) -> Dict[str, Any]:
    extraction = _metadata(row).get("extraction")
    return extraction if isinstance(extraction, dict) else {}


def _dedupe_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """Content hash, else filename plus a known size, else the row itself."""
    content_hash = row.get("content_hash") or _metadata(row).get("content_hash")
    if content_hash:
        return ("hash", str(content_hash))
    size = row.get("size")
    if isinstance(size, int) and size > 0 and row.get("filename"):
        return ("name_size", str(row["filename"]), size)
    return ("id", _attachment_id(row))


def _int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _new_planned(row: Dict[str, Any], ref: str, attachment_id: str, is_current: bool) -> PlannedFile:
    extraction = _extraction(row)
    text_tokens = _int(row.get("token_count"))
    if not text_tokens:
        text_tokens = _int(extraction.get("stored_tokens"))
    original = _int(extraction.get("original_tokens")) or text_tokens
    page_count = _metadata(row).get("page_count")
    return PlannedFile(
        ref=ref,
        attachment=row,
        attachment_ids=(attachment_id,),
        filename=str(row.get("filename") or "attachment"),
        mime_type=str(row.get("mime_type") or "application/octet-stream"),
        current=is_current,
        text_tokens=text_tokens,
        original_tokens=original,
        page_count=page_count if isinstance(page_count, int) and page_count > 0 else None,
    )


def _has_text(row: Dict[str, Any]) -> bool:
    """Extraction succeeded and left usable text."""
    status = _extraction(row).get("status")
    if status is not None and status != "ok":
        return False
    content = row.get("content")
    return content is not None and bool(str(content).strip())


def _native_readable(row: Dict[str, Any]) -> bool:
    """The original file exists to send (a failed parse may have no file)."""
    return _extraction(row).get("status") != "failed"


def _unreadable_reason(row: Dict[str, Any], capabilities: TurnCapabilities) -> str:
    status = _extraction(row).get("status")
    if status == "failed":
        return "extraction_failed"
    mime_type = str(row.get("mime_type") or "")
    if mime_type.startswith("image/") and not capabilities.vision:
        return "needs_vision"
    if mime_type == "application/pdf" and status == "no_text":
        return "needs_vision"
    return "no_text"


def _native_parts(planned: PlannedFile, capabilities: TurnCapabilities) -> int:
    if planned.mime_type == "application/pdf" and capabilities.synthetic_pdf:
        return min(planned.page_count or SYNTHETIC_PDF_MAX_PAGES, SYNTHETIC_PDF_MAX_PAGES)
    return 1


def _native_cost(planned: PlannedFile, capabilities: TurnCapabilities) -> int:
    """Context a native part is expected to take."""
    if planned.mime_type.startswith("image/"):
        return IMAGE_PART_TOKENS
    if planned.mime_type == "application/pdf":
        if capabilities.synthetic_pdf:
            return _native_parts(planned, capabilities) * IMAGE_PART_TOKENS
        pages = planned.page_count or 1
        return planned.original_tokens + pages * NATIVE_PDF_PAGE_TOKENS
    return max(planned.original_tokens, IMAGE_PART_TOKENS)


def _is_spreadsheet(planned: PlannedFile) -> bool:
    extension = os.path.splitext(planned.filename)[1].lower()
    return extension in SPREADSHEET_EXTENSIONS or planned.mime_type.lower() in SPREADSHEET_MIME_TYPES


def _fits_sandbox(row: Dict[str, Any], max_bytes: int) -> bool:
    size = row.get("size")
    if not isinstance(size, int) or size <= 0 or max_bytes <= 0:
        return True
    return size <= max_bytes

