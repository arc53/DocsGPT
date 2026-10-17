"""OCR for scanned PDFs and images."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import AliasChoices, Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


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
    OCR_BACKEND: Literal["auto", "docling", "native"] = Field(
        default="auto",
        description=(
            "Which stack runs OCR when it is on (OCR_ENGINE=deepseek always uses native). auto: docling when "
            "installed, otherwise native. docling: the "
            "layout-model pipeline (hybrid region OCR, reading order, table structure); needs the optional "
            "docling extra. native: pypdfium2/Pillow page rendering straight into tesseract or a DeepSeek-OCR "
            "endpoint (docsgpt/parser/file/ocr_parser.py); no ML models in the worker, tables come out as text "
            "lines under tesseract."
        ),
    )
    OCR_ENGINE: Literal["tesseract", "deepseek", "auto", "ocrmac", "rapidocr"] = Field(
        default="tesseract",
        description=(
            "OCR engine used when OCR is on. Benched 2026-08 on EN/ZH/table/degraded scans (docs page Sources/ocr has "
            "the menu). tesseract (recommended): best classic-engine accuracy (perfect EN word recall, 0.000 "
            "bilingual CER, 100% table cells), ~35 MB, CPU-only; needs the system binary and language packs, an "
            "optional install like every OCR dependency (build with INSTALL_TESSERACT=true, or apt/brew install "
            "tesseract-ocr for a local run); both backends. deepseek: DeepSeek-OCR on a local Ollama/vLLM server "
            "or a hosted API (OCR_DEEPSEEK_*); best table/CJK quality, the worker stays light (no layout models) "
            "but each page costs seconds on the model server; always runs on the native backend, whatever "
            "OCR_BACKEND says; docling never OCRs with it. auto: docling's pick, ocrmac on macOS "
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
    OCR_DEEPSEEK_PROVIDER: Literal["ollama", "vllm", "novita", "deepinfra", "custom"] = Field(
        default="ollama",
        description=(
            "Where DeepSeek-OCR runs; each preset supplies the endpoint URL, model and concurrency. ollama: a local "
            "Ollama (deepseek-ocr:3b). vllm: a vLLM server on localhost:8000 (deepseek-ai/DeepSeek-OCR). novita: "
            "Novita's hosted API (deepseek/deepseek-ocr-2). deepinfra: DeepInfra's hosted API "
            "(deepseek-ai/DeepSeek-OCR). custom: no defaults; set OCR_DEEPSEEK_URL and OCR_DEEPSEEK_MODEL. The "
            "hosted presets need OCR_DEEPSEEK_API_KEY and send every scanned page to that provider."
        ),
    )
    OCR_DEEPSEEK_URL: Optional[str] = Field(
        default=None,
        description=(
            "Chat-completions URL of the DeepSeek-OCR endpoint. Unset uses the OCR_DEEPSEEK_PROVIDER preset's URL "
            "(Ollama's http://localhost:11434/v1/chat/completions by default); a value here always wins."
        ),
    )
    OCR_DEEPSEEK_MODEL: Optional[str] = Field(
        default=None,
        description="Model name at the DeepSeek-OCR endpoint. Unset uses the OCR_DEEPSEEK_PROVIDER preset's model.",
    )
    OCR_DEEPSEEK_API_KEY: Optional[str] = Field(
        default=None,
        description=(
            "Bearer token sent to the DeepSeek-OCR endpoint. Required by the novita and deepinfra presets (novita "
            "falls back to NOVITA_API_KEY); local servers need none."
        ),
    )
    OCR_DEEPSEEK_CONCURRENCY: Optional[int] = Field(
        default=None,
        ge=1,
        le=32,
        description=(
            "Page requests in flight per file. Unset: 4 for the novita, deepinfra and vllm presets, 1 for ollama "
            "and custom, since a laptop-hosted model only slows down under parallel requests."
        ),
    )
    OCR_DEEPSEEK_MAX_RETRIES: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "Retries per page after a rate limit (429), a 5xx or a refused connection, with "
            "exponential backoff that honours Retry-After. Read timeouts are not retried."
        ),
    )
    OCR_DEEPSEEK_TIMEOUT: float = Field(
        default=300.0,
        description=(
            "Seconds allowed per page request to the DeepSeek endpoint. A 3B model on a laptop "
            "needs minutes; a vLLM GPU deployment or a hosted API, seconds."
        ),
    )
    OCR_DEEPSEEK_PROMPT: str = Field(
        default="Free OCR.",
        description=(
            "Instruction sent with every page image. 'Free OCR.' kept 94-100% of the words on real pages in "
            "testing and returns tables as Markdown; 'Convert the document to markdown.' lost most of a table "
            "page on Ollama, whose server strips the HTML cell tags that prompt produces. '<|grounding|>...' "
            "prompts add bounding boxes, which the output cleanup removes."
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
        ge=0,
        validation_alias=AliasChoices("OCR_MIN_CHARS_PER_PAGE", "DOCLING_OCR_MIN_CHARS_PER_PAGE"),
        description=(
            "Chars-per-page floor below which an OCR'd PDF/image parse is treated as an OCR dropout rather than "
            "as content (long-running docling workers were observed returning zero characters for every "
            "scanned page after a long scanned PDF, with no error). docling retries once on a fresh full-page-OCR "
            "converter; both backends then fail loudly instead of indexing an empty document. 0 disables the "
            "guard."
        ),
    )

    @field_validator("OCR_BACKEND", "OCR_ENGINE", "OCR_DEEPSEEK_PROVIDER", mode="before")
    @classmethod
    def _normalize_ocr_choices(cls, v):
        return normalize_choice(v)

    @field_validator("OCR_DEEPSEEK_CONCURRENCY", mode="before")
    @classmethod
    def _unset_concurrency(cls, v):
        if isinstance(v, str) and v.strip().lower() in ("", "none"):
            return None
        return v
