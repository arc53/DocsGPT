"""Docling parser.

Uses docling library for advanced document parsing with layout detection,
table structure recognition, and unified document representation.

Supports: PDF, DOCX, PPTX, XLSX, HTML, XHTML, CSV, Markdown, AsciiDoc,
images (PNG, JPEG, TIFF, BMP, WEBP), WebVTT, and specialized XML formats.
"""
import importlib.util
import logging
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from application.parser.file.base_parser import (
    BaseParser,
    DocumentParseError,
    delegate_parse as _delegate,
)
from application.parser.file.ocr_parser import VALID_OCR_ENGINES as _VALID_OCR_ENGINES
from application.parser.file.ocr_parser import collapse_cjk_spaces
from application.utils import truncate_to_line_boundary

logger = logging.getLogger(__name__)


# Per-stage batch size for docling's threaded pipeline; 1 holds the
# concurrent working set to a single page (see _apply_pipeline_caps).
_PIPELINE_BATCH_SIZE = 1


def _apply_pipeline_caps(pipeline_options) -> None:
    """Cap docling's threaded-pipeline queue depth and batch sizes in place.

    hasattr-guarded so docling builds without these knobs are unaffected.
    """
    from application.core.settings import settings

    caps = {
        "queue_max_size": max(1, settings.DOCLING_PIPELINE_QUEUE_MAX_SIZE),
        "layout_batch_size": _PIPELINE_BATCH_SIZE,
        "table_batch_size": _PIPELINE_BATCH_SIZE,
        "ocr_batch_size": _PIPELINE_BATCH_SIZE,
    }
    for name, value in caps.items():
        if hasattr(pipeline_options, name):
            setattr(pipeline_options, name, value)


def _apply_inference_settings() -> None:
    """Set docling's global torch.compile toggle from ``DOCLING_COMPILE_TORCH_MODELS``.

    docling compiles its layout/table/OCR models with ``torch.compile`` by
    default. For DocsGPT's one-shot, per-file parses that warmup is never
    amortized, and it hard-fails wherever TorchInductor cannot build: it emits
    invalid Metal on Apple Silicon, and its C++ path does not quote the ``-L``
    library path, so any install directory containing a space fails to build.

    Guarded so docling builds without the inference settings are unaffected.
    """
    from application.core.settings import settings

    try:
        from docling.datamodel.settings import settings as docling_settings
    except ImportError:  # pragma: no cover - docling always present here
        return

    inference = getattr(docling_settings, "inference", None)
    if inference is not None and hasattr(inference, "compile_torch_models"):
        inference.compile_torch_models = settings.DOCLING_COMPILE_TORCH_MODELS




def _resolve_ocr_engine(requested: Optional[str]) -> str:
    """Resolve the OCR engine to build, degrading to ``auto`` when unavailable.

    ``auto`` is docling's own selection (ocrmac on macOS, rapidocr on a
    typical Linux server). The degradation is deliberate: OCR is switched on
    by deployments that expect scans to work, so a missing engine must warn
    and OCR with what exists rather than fail every parse.

    Args:
        requested: Engine name, or None to read ``settings.OCR_ENGINE``.

    Returns:
        One of ``_VALID_OCR_ENGINES``, guaranteed buildable here.
    """
    from application.core.settings import settings
    from application.parser.file.base_parser import module_available

    engine = str(requested or settings.OCR_ENGINE or "auto").strip().lower()
    if engine not in _VALID_OCR_ENGINES:
        logger.warning(
            f"Unknown OCR_ENGINE {engine!r}; using docling auto-selection"
        )
        return "auto"
    if engine == "tesseract" and shutil.which("tesseract") is None:
        logger.warning(
            "OCR_ENGINE=tesseract but no tesseract binary is on PATH (install "
            "tesseract-ocr plus language packs; the Docker image ships them unless "
            "built with INSTALL_TESSERACT=false); using docling auto-selection"
        )
        return "auto"
    if engine == "ocrmac" and (
        sys.platform != "darwin" or not module_available("ocrmac")
    ):
        logger.warning(
            "OCR_ENGINE=ocrmac needs macOS with the ocrmac package; "
            "using docling auto-selection"
        )
        return "auto"
    if engine == "rapidocr" and not module_available("rapidocr"):
        logger.warning(
            "OCR_ENGINE=rapidocr but rapidocr is not installed; "
            "using docling auto-selection"
        )
        return "auto"
    return engine


def _build_ocr_options(
    engine: str, languages: Optional[List[str]], force_full_page_ocr: bool
):
    """docling OCR options for a resolved classic engine.

    Returns None for ``auto`` (docling's default pipeline options already run
    auto-selection) and on any build failure — the parse then proceeds on the
    default engine rather than failing; the caller re-applies
    ``force_full_page_ocr`` onto whatever options end up active.

    Args:
        engine: A ``_resolve_ocr_engine`` result other than ``deepseek``.
        languages: Engine-specific language list; None uses the engine's
            default (tesseract reads ``settings.OCR_LANGS``).
        force_full_page_ocr: OCR whole pages instead of only bitmap regions.
    """
    if engine == "auto":
        return None
    from application.core.settings import settings

    try:
        if engine == "tesseract":
            from docling.datamodel.pipeline_options import TesseractCliOcrOptions

            langs = (
                languages
                or [lang.strip() for lang in settings.OCR_LANGS.split("+") if lang.strip()]
                or ["eng"]
            )
            return TesseractCliOcrOptions(
                lang=langs, force_full_page_ocr=force_full_page_ocr
            )
        if engine == "rapidocr":
            from docling.datamodel.pipeline_options import RapidOcrOptions

            return RapidOcrOptions(
                lang=languages or ["english"],
                force_full_page_ocr=force_full_page_ocr,
            )
        if engine == "ocrmac":
            from docling.datamodel.pipeline_options import OcrMacOptions

            if languages:
                return OcrMacOptions(
                    lang=languages, force_full_page_ocr=force_full_page_ocr
                )
            return OcrMacOptions(force_full_page_ocr=force_full_page_ocr)
    except ImportError as e:
        logger.warning(f"Failed to build {engine} OCR options: {e}")
        return None
    except Exception as e:
        logger.error(f"Error building {engine} OCR options: {e}")
        return None
    return None


def _tabular_content_size(file: Path) -> int:
    """Effective content size of a tabular file, in bytes.

    Docling's memory scales with cell count, and for XLSX the cell count is
    hidden by zip compression — a 2 MB xlsx can hold ~850k cells. So for the
    zip-based ``.xlsx`` the measure is the inner-uncompressed size (read from
    the central directory without decompressing); for plain-text CSV the
    on-disk size already reflects the content.

    Args:
        file: Path to the tabular file.

    Returns:
        Content size in bytes, or -1 when it can't be determined.
    """
    path = Path(file)
    try:
        if path.suffix.lower() == ".xlsx":
            with zipfile.ZipFile(path) as zf:
                return sum(info.file_size for info in zf.infolist())
        return path.stat().st_size
    except (OSError, zipfile.BadZipFile):
        try:
            return path.stat().st_size
        except OSError:
            return -1


def _exceeds_tabular_gate(file: Path) -> bool:
    """Whether a tabular file is too large (by content) to hand to docling.

    Docling materializes a ``TableCell`` model per cell, so tabular memory
    scales with cell count, not on-disk bytes (~11 KB of RSS per 4-cell CSV
    row — an 88 MB CSV needs ~26 GB). Oversized CSV/XLSX files are routed to
    the lightweight parsers in ``tabular_parser`` instead.

    Args:
        file: Path to the tabular file about to be parsed.

    Returns:
        True when the file's content exceeds ``DOCLING_TABULAR_MAX_BYTES``
        (and the gate is enabled), False otherwise or when size is unknown.
    """
    from application.core.settings import settings

    max_bytes = settings.DOCLING_TABULAR_MAX_BYTES
    if max_bytes <= 0:
        return False
    return _tabular_content_size(file) > max_bytes


def _capped_markup_copy(file: Path) -> Optional[str]:
    """Head-truncate an oversized markup file to a temp copy for docling.

    HTML/VTT have no lightweight full-content parser to fall back to (unlike
    CSV/XLSX), so element-dense markup is bounded by parsing only the first
    ``DOCLING_MARKUP_MAX_BYTES`` — enough context for retrieval, and docling's
    lenient HTML/VTT backends handle a truncated tail. Cuts on a line boundary
    when one is reasonably close to the limit.

    Args:
        file: Path to the markup file about to be parsed.

    Returns:
        Path to a temp copy the caller must delete, or None when the file is
        within the limit / the gate is disabled / the size can't be read.
    """
    from application.core.settings import settings

    max_bytes = settings.DOCLING_MARKUP_MAX_BYTES
    if max_bytes <= 0:
        return None
    try:
        if Path(file).stat().st_size <= max_bytes:
            return None
        with open(file, "rb") as src:
            head = src.read(max_bytes)
    except OSError:
        return None
    head = truncate_to_line_boundary(head)
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=Path(file).suffix
    ) as tmp:
        tmp.write(head)
    return tmp.name


def _parse_markup_bounded(
    parser: "DoclingParser", file: Path, errors: str
) -> Union[str, List[str]]:
    """Run ``parser`` on ``file``, first truncating it if it is oversized markup."""
    capped = _capped_markup_copy(file)
    if capped is None:
        return DoclingParser.parse_file(parser, file, errors)
    logger.warning(
        f"Markup {Path(file).name} exceeds DOCLING_MARKUP_MAX_BYTES; "
        "parsing a head-truncated copy to bound memory"
    )
    try:
        return DoclingParser.parse_file(parser, Path(capped), errors)
    finally:
        try:
            os.unlink(capped)
        except OSError:
            pass


# Suffixes whose text comes (wholly or partly) from OCR, and are therefore
# covered by the near-empty-output dropout guard. Everything else docling
# handles (docx/xlsx/html/vtt/...) has a native text layer and legitimately
# short files, so the guard would only produce false alarms there.
_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
)
_OCR_GUARDED_SUFFIXES = _IMAGE_SUFFIXES | {".pdf"}

# Chars-per-page floor below which an OCR parse is treated as a pipeline
# dropout rather than as the document's real content. Scanned pages that
# carry any text at all clear this comfortably; the observed failure mode
# returns literally zero characters per page.
_DEFAULT_OCR_MIN_CHARS_PER_PAGE = 20

# Docling emits this placeholder for a picture it did not read; it is markup,
# not document text, so it must not count towards the chars-per-page ratio.
_IMAGE_PLACEHOLDER_RE = re.compile(r"<!--\s*image\s*-->")


def _ocr_min_chars_per_page() -> int:
    """Chars-per-page floor for the OCR dropout guard; 0 disables it."""
    from application.core.settings import settings

    try:
        return int(
            getattr(
                settings,
                "OCR_MIN_CHARS_PER_PAGE",
                _DEFAULT_OCR_MIN_CHARS_PER_PAGE,
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_OCR_MIN_CHARS_PER_PAGE


def _text_char_count(content: Optional[str]) -> int:
    """Count real text characters in exported content, ignoring placeholders."""
    if not content:
        return 0
    return len(_IMAGE_PLACEHOLDER_RE.sub("", content).strip())


def _positive_len(value: object) -> int:
    """``len(value)`` when it is a positive int, 0 when it is neither."""
    try:
        length = len(value)
    except TypeError:
        return 0
    return length if isinstance(length, int) and length > 0 else 0


def _result_page_count(result: object, file: Path) -> int:
    """Page count of a conversion result, never below 1.

    Args:
        result: Docling ``ConversionResult``.
        file: Path of the file that was converted.

    Returns:
        Number of pages; 1 for images and whenever docling reports none.
    """
    if Path(file).suffix.lower() in _IMAGE_SUFFIXES:
        return 1
    document = getattr(result, "document", None)
    pages = _positive_len(getattr(document, "pages", None))
    if pages:
        return pages
    num_pages = getattr(document, "num_pages", None)
    if callable(num_pages):
        try:
            reported = num_pages()
        except Exception:  # pragma: no cover - defensive, docling-version drift
            reported = None
        if isinstance(reported, int) and reported > 0:
            return reported
    return _positive_len(getattr(result, "pages", None)) or 1


def _pdf_text_layer_probe(file: Path) -> Tuple[int, int]:
    """Measure a PDF's embedded text layer with pypdfium2.

    Used only to explain a suspected OCR dropout: a near-empty parse of a PDF
    that *does* carry a text layer means docling failed to read text it never
    needed OCR for, while an absent text layer points at the OCR stage itself.

    Args:
        file: Path to the PDF.

    Returns:
        Tuple of (page count, characters in the text layer); (0, 0) when the
        file cannot be probed.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return 0, 0
    try:
        pdf = pdfium.PdfDocument(str(file))
    except Exception:
        return 0, 0
    try:
        total = 0
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            try:
                total += max(0, textpage.count_chars())
            finally:
                textpage.close()
                page.close()
        return len(pdf), total
    except Exception:
        return 0, 0
    finally:
        pdf.close()


class DoclingParser(BaseParser):
    """Parser using docling for advanced document processing.

    Docling provides:
    - Advanced PDF layout analysis
    - Table structure recognition
    - Reading order detection
    - OCR for scanned documents (engine chosen by ``OCR_ENGINE``)
    - Unified DoclingDocument format
    - Export to Markdown

    Uses hybrid OCR approach by default:
    - Text regions: Direct PDF text extraction (fast)
    - Bitmap/image regions: OCR only these areas (smart)
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure: bool = True,
        export_format: str = "markdown",
        ocr_engine: Optional[str] = None,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = False,
    ):
        """Initialize DoclingParser.

        Args:
            ocr_enabled: Enable OCR for bitmap/image regions in documents
            table_structure: Enable table structure recognition
            export_format: Output format ('markdown', 'text', 'html')
            ocr_engine: OCR engine when OCR is enabled — one of
                ``tesseract | auto | ocrmac | rapidocr | deepseek``. None
                reads ``settings.OCR_ENGINE`` at converter build time; an
                unavailable engine degrades to docling's auto-selection with
                a warning.
            ocr_languages: Engine-specific language list; None keeps the
                engine's own default (tesseract reads ``settings.OCR_LANGS``).
            force_full_page_ocr: Force OCR on entire page (False = smart hybrid OCR)
        """
        super().__init__()
        self.ocr_enabled = ocr_enabled
        self.table_structure = table_structure
        self.export_format = export_format
        self.ocr_engine = ocr_engine
        self.ocr_languages = ocr_languages
        self.force_full_page_ocr = force_full_page_ocr
        # Engine the current converter was built for (None with OCR off);
        # drives tesseract-specific post-processing of the export.
        self._active_ocr_engine: Optional[str] = None
        self._converter = None

    def _create_converter(self):
        """Create a docling converter for the configured OCR engine.

        - ``ocr_enabled=False``: no OCR, native text extraction only.
        - Classic engines (tesseract / auto / ocrmac / rapidocr): the standard
          PDF pipeline (layout + TableFormer) with that engine's OCR options.
          ``force_full_page_ocr=False`` (default) OCRs only the bitmap regions
          the layout model finds; True routes whole pages through OCR.
        - ``deepseek``: the VLM pipeline instead (``_create_vlm_converter``).

        Returns:
            DocumentConverter instance
        """
        from docling.document_converter import (
            DocumentConverter,
            ImageFormatOption,
            InputFormat,
            PdfFormatOption,
        )
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        _apply_inference_settings()

        engine = _resolve_ocr_engine(self.ocr_engine) if self.ocr_enabled else None
        self._active_ocr_engine = engine
        if engine == "deepseek":
            return self._create_vlm_converter()

        pipeline_options = PdfPipelineOptions(
            do_ocr=self.ocr_enabled,
            do_table_structure=self.table_structure,
        )
        _apply_pipeline_caps(pipeline_options)

        if self.ocr_enabled:
            ocr_options = _build_ocr_options(
                engine, self.ocr_languages, self.force_full_page_ocr
            )
            if ocr_options is not None:
                pipeline_options.ocr_options = ocr_options
            # Docling's *default* OCR options carry their own flag, so without
            # this the setting was silently dropped whenever no explicit
            # options were built (engine=auto, or a build failure) — including
            # the dropout retry, whose whole point is forcing full-page OCR.
            active_ocr_options = getattr(pipeline_options, "ocr_options", None)
            if hasattr(active_ocr_options, "force_full_page_ocr"):
                active_ocr_options.force_full_page_ocr = self.force_full_page_ocr

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                ),
                InputFormat.IMAGE: ImageFormatOption(
                    pipeline_options=pipeline_options,
                ),
            }
        )

    def _create_vlm_converter(self):
        """DeepSeek-OCR converter via docling's VLM pipeline.

        Each page goes to an OpenAI-compatible endpoint (Ollama or vLLM;
        ``OCR_DEEPSEEK_URL`` / ``OCR_DEEPSEEK_MODEL``) and the grounded output
        is parsed back into a DoclingDocument. This replaces the *entire*
        classic pipeline — no layout/TableFormer/OCR models load in the worker
        (~370 MB RSS vs 1.0-1.6 GB measured), the compute lives in the model
        server. Bench trade-offs (2026-08): best table/CJK/degraded-scan
        quality of every engine tried, ~10-20 s/page on modest hardware, and
        occasional silent drops of page-level elements (titles).
        """
        from docling.datamodel import vlm_model_specs
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.document_converter import (
            DocumentConverter,
            ImageFormatOption,
            InputFormat,
            PdfFormatOption,
        )
        from docling.pipeline.vlm_pipeline import VlmPipeline

        from application.core.settings import settings

        vlm_options = vlm_model_specs.DEEPSEEKOCR_OLLAMA.model_copy(deep=True)
        vlm_options.url = settings.OCR_DEEPSEEK_URL
        vlm_options.params["model"] = settings.OCR_DEEPSEEK_MODEL
        pipeline_options = VlmPipelineOptions(
            vlm_options=vlm_options, enable_remote_services=True
        )
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
                ),
                InputFormat.IMAGE: ImageFormatOption(
                    pipeline_cls=VlmPipeline, pipeline_options=pipeline_options
                ),
            }
        )

    def _init_parser(self) -> Dict:
        """Initialize the docling converter with hybrid OCR."""
        from application.core.settings import settings

        logger.info("Initializing DoclingParser...")
        logger.info(f"  ocr_enabled={self.ocr_enabled}")
        logger.info(f"  force_full_page_ocr={self.force_full_page_ocr}")
        logger.info(f"  ocr_engine={self.ocr_engine or settings.OCR_ENGINE}")

        if importlib.util.find_spec("docling.document_converter") is None:
            raise ImportError(
                "docling is required for DoclingParser. "
                "Install it with: pip install docling"
            )

        # Create converter with hybrid OCR (smart: text direct, bitmaps OCR'd)
        self._converter = self._create_converter()

        logger.info("DoclingParser initialized successfully")
        return {
            "ocr_enabled": self.ocr_enabled,
            "table_structure": self.table_structure,
            "export_format": self.export_format,
            "ocr_engine": self.ocr_engine,
            "ocr_languages": self.ocr_languages,
            "force_full_page_ocr": self.force_full_page_ocr,
        }

    def _export_content(self, document) -> str:
        """Export document content in the configured format.

        Handles edge case where text is nested under picture elements (e.g., OCR'd
        images). If the standard export returns minimal content but document.texts
        contains extracted text, falls back to direct text extraction.
        """
        if self.export_format == "markdown":
            content = document.export_to_markdown()
        elif self.export_format == "html":
            content = document.export_to_html()
        else:
            content = document.export_to_text()

        # Handle case where text is nested under pictures (common with OCR'd images)
        # Standard exports may return just "<!-- image -->" while actual text exists
        stripped_content = content.strip()
        is_minimal = len(stripped_content) < 50 or stripped_content == "<!-- image -->"

        if is_minimal and hasattr(document, "texts") and document.texts:
            # Extract text directly from document.texts
            extracted_texts = [t.text for t in document.texts if t.text]
            if extracted_texts:
                logger.info(
                    f"Standard export minimal ({len(stripped_content)} chars), "
                    f"extracting {len(extracted_texts)} texts directly"
                )
                content = "\n\n".join(extracted_texts)

        return self._postprocess_ocr_text(content)

    def _postprocess_ocr_text(self, content: str) -> str:
        """Engine-specific cleanup of OCR'd text.

        tesseract's CJK models space every glyph ("互相 保密 协议"); the native
        backend collapses that in ``TesseractEngine`` and the docling path
        needs the same treatment or Chinese scans index worse here than there.
        Other engines (and OCR off) return the export untouched.
        """
        if self.ocr_enabled and self._active_ocr_engine == "tesseract":
            return collapse_cjk_spaces(content)
        return content

    def _ocr_guard_applies(self, file: Path) -> bool:
        """Whether the near-empty-output dropout guard covers this parse."""
        return (
            bool(self.ocr_enabled)
            and _ocr_min_chars_per_page() > 0
            and Path(file).suffix.lower() in _OCR_GUARDED_SUFFIXES
        )

    def _recover_from_ocr_dropout(
        self, file: Path, first_pass_chars: int, pages: int
    ) -> str:
        """Retry a near-empty OCR parse once on a fresh full-page-OCR converter.

        Docling caches its pipeline (and the threaded page queue behind it) on
        the ``DocumentConverter`` instance, so a converter that has degraded
        mid-worker keeps returning empty pages while a fresh one starts clean —
        hence a brand new converter rather than a second `convert` call.

        ``self._converter`` is dropped either way instead of being replaced by
        the retry converter: the degraded instance must not survive, but the
        retry one is configured for full-page OCR, and keeping it would impose
        that cost (and its worse results on text PDFs) on every later file in
        the worker. The next parse lazily rebuilds one with normal options.

        Args:
            file: Path to the file being parsed.
            first_pass_chars: Text characters the first pass produced.
            pages: Page count reported for the first pass.

        Returns:
            The retry's content: either because it cleared the chars-per-page
            floor, or because the document is genuinely text-sparse.

        Raises:
            DocumentParseError: Only with positive evidence of a dropout — a
                PDF text layer docling should have read without OCR, or a
                multi-page document that OCR'd to literally zero characters.
        """
        name = Path(file).name
        logger.warning(
            "OCR output for %s is near-empty (%d chars over %d page(s)); "
            "retrying once on a fresh converter with full-page OCR",
            name,
            first_pass_chars,
            pages,
        )
        original_force_full_page_ocr = self.force_full_page_ocr
        try:
            self.force_full_page_ocr = True
            result = self._create_converter().convert(str(file))
            content = self._export_content(result.document)
        finally:
            self.force_full_page_ocr = original_force_full_page_ocr
            self._converter = None

        retry_chars = _text_char_count(content)
        retry_pages = max(pages, _result_page_count(result, file))
        if retry_chars >= _ocr_min_chars_per_page() * retry_pages:
            logger.warning(
                "Recovered %s on retry: %d chars over %d page(s) after a "
                "near-empty first pass (%d chars); the degraded converter has "
                "been discarded",
                name,
                retry_chars,
                retry_pages,
                first_pass_chars,
            )
            return content

        detail = ""
        layer_pages = layer_chars = 0
        if Path(file).suffix.lower() == ".pdf":
            layer_pages, layer_chars = _pdf_text_layer_probe(file)
            if layer_chars > 0:
                detail = (
                    f" The PDF carries a {layer_chars}-char text layer over "
                    f"{layer_pages} page(s) that docling should have read "
                    "without OCR at all."
                )
            elif layer_pages > 0:
                detail = (
                    f" The PDF has no text layer over {layer_pages} page(s), "
                    "so OCR was the only possible source."
                )

        # Sparse is not the same as dropped. Fail only on positive evidence
        # that there was text to find: a text layer docling should have read
        # without OCR, or a multi-page document that OCR'd to literally
        # nothing (the observed incident). A photo, logo, chart or picture-led
        # catalogue is genuinely text-poor — failing it would reject the
        # upload permanently, since DocumentParseError skips autoretry.
        if layer_chars > 0 or (retry_chars == 0 and retry_pages > 1):
            raise DocumentParseError(
                f"OCR produced {retry_chars} chars over {retry_pages} pages for "
                f"{name}; likely OCR pipeline dropout — document not indexed."
                + detail
            )

        logger.warning(
            "%s yielded only %d chars over %d page(s) after a full-page-OCR "
            "retry; indexing it as genuinely text-sparse rather than treating "
            "it as an OCR dropout.%s",
            name,
            retry_chars,
            retry_pages,
            detail,
        )
        return content

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file using docling with hybrid OCR.

        Uses smart OCR approach where the layout model detects text vs bitmap
        regions. Text is extracted directly, bitmaps are OCR'd only when needed.

        When OCR is enabled for a PDF or image, a near-empty result is retried
        once on a fresh converter. It is only rejected as a pipeline dropout if
        the retry is near-empty *and* there is evidence text was there to find;
        a genuinely text-sparse document (a photo, a picture-led catalogue) is
        indexed with a warning.

        Args:
            file: Path to the file to parse
            errors: Error handling mode (ignored, docling handles internally)

        Returns:
            Parsed document content as markdown string

        Raises:
            DocumentParseError: If docling fails, or if an OCR parse stays
                near-empty across both passes on a document that demonstrably
                carried text.
        """
        logger.info(f"parse_file called for: {file}")

        if self._converter is None:
            self._init_parser()

        try:
            logger.info(f"Converting file with hybrid OCR: {file}")
            result = self._converter.convert(str(file))
            content = self._export_content(result.document)
            pages = _result_page_count(result, file)
            chars = _text_char_count(content)
            logger.info(
                "Parse complete for %s: %d chars (%d text) over %d page(s), "
                "%.1f chars/page",
                Path(file).name,
                len(content),
                chars,
                pages,
                chars / pages,
            )

            if self._ocr_guard_applies(file) and chars < (
                _ocr_min_chars_per_page() * pages
            ):
                return self._recover_from_ocr_dropout(file, chars, pages)

            return content

        except DocumentParseError:
            # Already the loud, actionable failure — do not re-wrap it into a
            # generic "Failed to parse ..." and lose the dropout diagnosis.
            raise
        except Exception as e:
            logger.error(f"Error parsing file with docling: {e}", exc_info=True)
            # ``errors`` governs *decoding* leniency, not whether a total
            # conversion failure may be substituted for the document. Returning
            # the message here (the old ``errors == "ignore"`` branch) made the
            # caller store the traceback as the file's text and report the
            # upload successful — the model then read the error as the document.
            raise DocumentParseError(
                f"Failed to parse {Path(file).name} with docling: {e}"
            ) from e


class DoclingPDFParser(DoclingParser):
    """Docling-based PDF parser with advanced features and configurable OCR.

    Uses hybrid OCR approach by default:
    - Text regions: Direct PDF text extraction (fast)
    - Bitmap/image regions: OCR only these areas (smart)

    Set force_full_page_ocr=True only for fully scanned documents.
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure: bool = True,
        ocr_engine: Optional[str] = None,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = False,
    ):
        super().__init__(
            ocr_enabled=ocr_enabled,
            table_structure=table_structure,
            export_format="markdown",
            ocr_engine=ocr_engine,
            ocr_languages=ocr_languages,
            force_full_page_ocr=force_full_page_ocr,
        )


    def ocr_pages(self, file: Path, indices: List[int]) -> Dict[int, str]:
        """Convert only the given 0-based pages of ``file`` and return their text.

        The counterpart of ``NativeOcrPdfParser.ocr_pages`` for the docling
        backend: ``AnydocParser`` calls it for the scanned pages of a mixed
        document. Each page is a separate ``convert`` with ``page_range`` so
        the layout model sees one page at a time; a fully scanned page is one
        bitmap region, which hybrid OCR reads in full.

        Raises:
            DocumentParseError: docling failed on a page.
        """
        if self._converter is None:
            self._init_parser()
        path = Path(file)
        texts: Dict[int, str] = {}
        for index in indices:
            if index < 0:
                continue
            try:
                result = self._converter.convert(str(path), page_range=(index + 1, index + 1))
                texts[index] = self._export_content(result.document).strip()
            except Exception as exc:
                raise DocumentParseError(
                    f"Failed to OCR page {index + 1} of {path.name} with docling: {exc}"
                ) from exc
        return texts


class DoclingDocxParser(DoclingParser):
    """Docling-based DOCX parser."""

    def __init__(self):
        super().__init__(export_format="markdown")


class DoclingPPTXParser(DoclingParser):
    """Docling-based PPTX parser."""

    def __init__(self):
        super().__init__(export_format="markdown")


class DoclingXLSXParser(DoclingParser):
    """Docling-based XLSX parser with table structure."""

    def __init__(self):
        super().__init__(table_structure=True, export_format="markdown")

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse an XLSX file, delegating oversized files to ``ExcelParser``."""
        if _exceeds_tabular_gate(file):
            logger.warning(
                f"XLSX {file.name} exceeds DOCLING_TABULAR_MAX_BYTES; "
                "using lightweight Excel parser instead of docling"
            )
            from application.parser.file.tabular_parser import ExcelParser

            return _delegate(ExcelParser(), file, errors)
        return super().parse_file(file, errors)


class DoclingHTMLParser(DoclingParser):
    """Docling-based HTML parser."""

    def __init__(self):
        super().__init__(export_format="markdown")

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse HTML, truncating oversized element-dense markup first."""
        return _parse_markup_bounded(self, file, errors)


class DoclingImageParser(DoclingParser):
    """Docling-based image parser with configurable OCR.

    For images, force_full_page_ocr=True is used since images are entirely
    visual and require full OCR to extract any text.
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        ocr_engine: Optional[str] = None,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = True,
    ):
        super().__init__(
            ocr_enabled=ocr_enabled,
            export_format="markdown",
            ocr_engine=ocr_engine,
            ocr_languages=ocr_languages,
            force_full_page_ocr=force_full_page_ocr,
        )


class DoclingCSVParser(DoclingParser):
    """Docling-based CSV parser."""

    def __init__(self):
        super().__init__(table_structure=True, export_format="markdown")

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse a CSV file, delegating oversized files to the plain ``CSVParser``."""
        if _exceeds_tabular_gate(file):
            logger.warning(
                f"CSV {file.name} exceeds DOCLING_TABULAR_MAX_BYTES; "
                "using plain CSV parser instead of docling"
            )
            from application.parser.file.tabular_parser import CSVParser

            return _delegate(CSVParser(), file, errors)
        return super().parse_file(file, errors)


class DoclingMarkdownParser(DoclingParser):
    """Docling-based Markdown parser."""

    def __init__(self):
        super().__init__(export_format="markdown")


class DoclingAsciiDocParser(DoclingParser):
    """Docling-based AsciiDoc parser."""

    def __init__(self):
        super().__init__(export_format="markdown")


class DoclingVTTParser(DoclingParser):
    """Docling-based WebVTT (video text tracks) parser."""

    def __init__(self):
        super().__init__(export_format="markdown")

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse WebVTT, truncating oversized cue-dense tracks first."""
        return _parse_markup_bounded(self, file, errors)


class DoclingXMLParser(DoclingParser):
    """Docling-based XML parser (USPTO, JATS)."""

    def __init__(self):
        super().__init__(export_format="markdown")
