"""OCR for scanned PDFs and images."""

from __future__ import annotations

from pydantic import AliasChoices, Field

from docsgpt.core.settings._shared import SettingsGroup


class OCRSettings(SettingsGroup):
    """Whether OCR runs, which stack performs it, and which engine it uses.

    OCR_ENABLED covers source ingestion, OCR_ATTACHMENTS_ENABLED chat attachments. Which stack performs
    it is OCR_BACKEND; which engine, OCR_ENGINE. The DOCLING_OCR_* names are the pre-2026-09 spellings
    and stay accepted as aliases.
    """

    OCR_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("OCR_ENABLED", "DOCLING_OCR_ENABLED"),
        description="OCR scanned PDFs and images during source ingestion.",
    )
    OCR_ATTACHMENTS_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("OCR_ATTACHMENTS_ENABLED", "DOCLING_OCR_ATTACHMENTS_ENABLED"),
        description="OCR scanned PDFs and images attached to a chat.",
    )
    OCR_BACKEND: str = Field(
        default="auto",
        description=(
            "Which stack runs OCR when it is on. auto: docling when installed, otherwise native. docling: the "
            "layout-model pipeline (hybrid region OCR, reading order, table structure); needs the optional "
            "docling extra. native: pypdfium2/Pillow page rendering straight into tesseract or a DeepSeek-OCR "
            "endpoint (docsgpt/parser/file/ocr_parser.py); no ML models in the worker, tables come out as text "
            "lines under tesseract."
        ),
    )
    OCR_ENGINE: str = Field(
        default="tesseract",
        description=(
            "OCR engine used when OCR is on. Benched 2026-08 on EN/ZH/table/degraded scans (docs/Guides/ocr has "
            "the menu). tesseract (recommended): best classic-engine accuracy (perfect EN word recall, 0.000 "
            "bilingual CER, 100% table cells), ~35 MB, CPU-only; needs the system binary and language packs, an "
            "optional install like every OCR dependency (build with INSTALL_TESSERACT=true, or apt/brew install "
            "tesseract-ocr for a local run); both backends. deepseek: DeepSeek-OCR against an Ollama/vLLM "
            "endpoint (OCR_DEEPSEEK_*); best table/CJK quality, the worker stays light (no layout models) but "
            "each page costs seconds on the model server; both backends. auto: docling's pick, ocrmac on macOS "
            "(excellent), rapidocr on Linux (silently shreds some long text lines; avoid as a server default). "
            "ocrmac | rapidocr: force one of those. auto/ocrmac/rapidocr exist only inside docling; the native "
            "backend runs tesseract for them. An engine that is not installed degrades (docling: to auto) with "
            "a warning instead of failing the parse."
        ),
    )
    OCR_LANGS: str = Field(
        default="eng",
        description=(
            'Tesseract language packs, "+"-separated (e.g. "eng+chi_sim+deu"). Other engines keep their own '
            "defaults; their language codes differ."
        ),
    )
    OCR_DEEPSEEK_URL: str = Field(
        default="http://localhost:11434/v1/chat/completions",
        description="Chat-completions URL of the DeepSeek-OCR endpoint (Ollama or vLLM).",
    )
    OCR_DEEPSEEK_MODEL: str = Field(default="deepseek-ocr:3b", description="Model name at the DeepSeek-OCR endpoint.")
    OCR_DEEPSEEK_TIMEOUT: float = Field(
        default=300.0,
        description=(
            "Seconds allowed per page request to the DeepSeek endpoint, on both backends (native sends pages one "
            "at a time; docling's VLM pipeline keeps its own concurrency). A 3B model on a laptop needs minutes; "
            "a vLLM GPU deployment, seconds."
        ),
    )
    OCR_RENDER_DPI: int = Field(
        default=200,
        description=(
            "Native backend only: resolution at which pages without a text layer are rendered before OCR. 200 "
            "suits tesseract; clamped to 72-600."
        ),
    )
    OCR_MIN_CHARS_PER_PAGE: int = Field(
        default=20,
        validation_alias=AliasChoices("OCR_MIN_CHARS_PER_PAGE", "DOCLING_OCR_MIN_CHARS_PER_PAGE"),
        description=(
            "Chars-per-page floor below which an OCR'd PDF/image parse is treated as an OCR dropout rather than "
            "as content (long-running docling workers were observed returning zero characters for every "
            "scanned page after a long scanned PDF, with no error). docling retries once on a fresh full-page-OCR "
            "converter; both backends then fail loudly instead of indexing an empty document. 0 disables the "
            "guard."
        ),
    )
