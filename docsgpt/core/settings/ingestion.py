"""Uploads, document parsing and the size caps that keep one file from taking a worker down."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


class IngestionSettings(SettingsGroup):
    """Upload limits, the parser engine, and per-format byte caps for ingestion and attachments."""

    UPLOAD_FOLDER: str = Field(default="inputs", description="Directory under the data home for uploaded sources.")
    UPLOAD_MAX_REQUEST_BYTES: int = Field(
        default=256 * 1024 * 1024,
        gt=0,
        description="Cap on an upload request body; applied by Flask before multipart parsing.",
    )
    UPLOAD_MAX_FILE_BYTES: int = Field(
        default=100 * 1024 * 1024, gt=0, description="Cap on a single uploaded file; also enforced while copying."
    )
    PARSE_SPEC_MAX_BYTES: int = Field(
        default=10 * 1024 * 1024, gt=0, description="Cap on an OpenAPI/tool spec file accepted for parsing."
    )
    # ZIP limits apply cumulatively across nested archives in one extraction.
    UPLOAD_MAX_ARCHIVE_BYTES: int = Field(
        default=250 * 1024 * 1024, gt=0, description="Cap on total bytes extracted from one uploaded archive."
    )
    UPLOAD_MAX_ARCHIVE_FILES: int = Field(
        default=10_000, gt=0, description="Cap on files extracted from one uploaded archive."
    )
    UPLOAD_MAX_ARCHIVE_RATIO: int = Field(
        default=1000, gt=0, description="Maximum decompressed-to-compressed ratio before an archive is rejected."
    )
    UPLOAD_MAX_ARCHIVE_DEPTH: int = Field(
        default=3, ge=0, description="Maximum nesting depth of archives inside archives."
    )
    PARSE_PDF_AS_IMAGE: bool = Field(default=False, description="Render PDF pages to images before parsing.")
    PARSE_IMAGE_REMOTE: bool = Field(default=False, description="Send images to a remote parser.")
    DOC_PARSER_ENGINE: Literal["anydoc", "docling"] = Field(
        default="anydoc",
        description=(
            'Document parser for source ingestion, chat attachments and the read_document tool. "anydoc" '
            "(default): firecrawl-anydoc, a Rust converter with no ML models; milliseconds per file, ~100 MB "
            'peak RSS. "docling": the layout/table-model pipeline (optional install; needed for '
            "read_document's structured output and the docling OCR backend). Files anydoc cannot convert "
            "(scanned PDFs, malformed input) fall back to docling when it is installed, otherwise to the native "
            "OCR parsers (OCR on) or the legacy parsers. Rollback to the previous behaviour is this one variable."
        ),
    )
    DOCLING_PIPELINE_QUEUE_MAX_SIZE: int = Field(
        default=2,
        description=(
            "Pages docling's threaded pipeline buffers in flight; the library default (100) drives worker RSS "
            "to ~3 GB on a mid-size PDF."
        ),
    )
    DOCLING_COMPILE_TORCH_MODELS: bool = Field(
        default=False, description="Let docling torch.compile its models (slower start, faster pages)."
    )
    DOCLING_TABULAR_MAX_BYTES: int = Field(
        default=2_000_000, description="Largest CSV/XLSX docling will parse, in bytes."
    )
    DOCLING_MARKUP_MAX_BYTES: int = Field(
        default=8_000_000, description="Largest HTML/XML docling will parse, in bytes."
    )
    MARKUP_MAX_BYTES: int = Field(
        default=8_000_000,
        ge=0,
        description=(
            "HTML/XHTML larger than this (bytes) are head-truncated before the markdownify parser runs (the "
            "anydoc engine's HTML path). The tree that path builds costs ~50x the input (30 MB of HTML measured "
            "at 1.6 GB RSS) and the upload cap is 100 MB, so the gate is what keeps one upload from taking the "
            "ingest worker down. 0 disables it."
        ),
    )
    PDF_TRUST_CHECK: bool = Field(
        default=True,
        description=(
            "Trust-check anydoc's PDF output (docsgpt/parser/file/pdf_trust.py): flag composite (Type0) fonts "
            "without a ToUnicode map, and CJK-declaring PDFs whose extracted text has almost no CJK, the two "
            "classes where anydoc drops text silently. A flagged file re-parses on the docling fallback when "
            "docling is installed; otherwise the anydoc output is kept and the document gets "
            'extra_info["parse_warnings"]. ~30 ms per scanned MB.'
        ),
    )
    ANYDOC_TABLEIZE: bool = Field(
        default=False,
        description=(
            "Rewrite dot-leader / whitespace-aligned table runs in anydoc's PDF markdown into GFM tables "
            "(docsgpt/parser/file/tableize.py). Off by default: it rewrites content on a heuristic (>=3 uniform "
            "label+numbers lines) validated only on a small corpus so far."
        ),
    )
    ATTACHMENT_PDF_TEXT_FAST_PATH: bool = Field(
        default=True,
        description=(
            "Read PDF attachments via their embedded text layer (pypdfium2) instead of docling, falling back to "
            "docling when there is no text layer. Attachments go into a prompt, so docling's structural "
            "markdown earns far less than the tens of seconds per file it costs; source ingestion is "
            "unaffected because chunking and retrieval do depend on that structure."
        ),
    )
    ATTACHMENT_PDF_TEXT_MIN_MEDIAN_CHARS: int = Field(
        default=32,
        description=(
            "Median chars per sampled page below which a PDF attachment is treated as a scan and handed to "
            "docling. Measured on real uploads: scans at 0-17 chars/page, text-layer documents at 433-6834."
        ),
    )
    ATTACHMENT_TEXT_MAX_BYTES: int = Field(default=5_000_000, description="Cap on extracted attachment text.")
    AGENT_IMAGE_MAX_BYTES: int = Field(default=5_000_000, description="Cap on an image passed to an agent.")
    AGENT_IMAGE_MAX_PIXELS: int = Field(
        default=16_777_216, description="Cap on the pixel count of an image passed to an agent."
    )
    GITHUB_INGEST_MAX_FILE_BYTES: int = Field(
        default=1048576, ge=0, description="Skip GitHub repo blobs larger than this (0 = no cap)."
    )
    GITHUB_INGEST_MAX_WORKERS: int = Field(default=8, ge=1, description="Parallel file fetches per GitHub repo ingest.")

    # read_document parsing on a dedicated Celery queue (backend parser).
    DOCUMENT_PARSE_QUEUE: str = Field(default="parsing", description="Celery queue the parse_document task is routed to.")
    DOCUMENT_PARSE_TIMEOUT: int = Field(
        default=120, description="Seconds the read_document tool awaits the enqueued parse before degrading."
    )
    DOCUMENT_PARSE_TIMEOUT_PER_MB: int = Field(
        default=60,
        description=(
            "Extra seconds of parse window per MiB of input. The base timeout is a FLOOR: the window grows with "
            "document size because OCR cost scales with pages. Without this a large scan is silently dropped at "
            "the base window."
        ),
    )
    DOCUMENT_PARSE_TIMEOUT_MAX: int = Field(
        default=900, description="Absolute ceiling on the size-scaled parse window, in seconds."
    )
    DOCUMENT_PARSE_MAX_BYTES: int = Field(
        default=0, ge=0, description="Cap on a parsed document's bytes (0 = reuse SANDBOX_MAX_INPUT_BYTES)."
    )
    DOCUMENT_MAX_DECOMPRESSED_BYTES: int = Field(
        default=300 * 1024 * 1024, description="Cap on bytes decompressed from an archive handed to read_document."
    )
    DOCUMENT_MAX_ARCHIVE_ENTRIES: int = Field(
        default=10000, description="Cap on entries in an archive handed to read_document."
    )

    @field_validator("DOC_PARSER_ENGINE", mode="before")
    @classmethod
    def _normalize_parser_engine(cls, v):
        return normalize_choice(v)
