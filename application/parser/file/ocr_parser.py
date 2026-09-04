"""Native OCR parsers: scanned PDFs and images without docling.

OCR in DocsGPT has two backends, selected by ``OCR_BACKEND``:

* ``docling`` — the layout-model pipeline in ``docling_parser.py``. Hybrid
  OCR (only the bitmap regions of a page), reading-order and table
  structure recovery, and five engines (tesseract / auto / ocrmac /
  rapidocr / deepseek). Costs the optional docling install (torch, ONNX
  models, gigabytes of image) and seconds to minutes per file.
* ``native`` (this module) — page rendering with pypdfium2 and Pillow, both
  core dependencies, feeding one of two engines directly: the system
  ``tesseract`` binary, or a DeepSeek-OCR model behind an OpenAI-compatible
  endpoint (Ollama / vLLM). No ML models load in the worker. Pages that
  carry a text layer are read through pypdfium2 and never OCR'd; pages
  without one are rendered and OCR'd. What it lacks against docling is the
  layout model: multi-column scans rely on tesseract's own page
  segmentation, and tesseract yields tables as plain lines (DeepSeek-OCR
  emits Markdown tables itself).

``auto`` picks docling when it is installed and native otherwise, so a
deployment that never installs the docling extra gets working OCR from the
tesseract binary alone, and one that does install it keeps today's
behaviour unchanged.
"""
import base64
import functools
import io
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple, Union

from application.parser.file.base_parser import (
    BaseParser,
    DocumentParseError,
    delegate_parse,
    module_available,
)

logger = logging.getLogger(__name__)

# Every engine ``OCR_ENGINE`` accepts. ``auto``, ``ocrmac`` and ``rapidocr``
# exist only inside docling; the native backend maps them to tesseract.
VALID_OCR_ENGINES: Tuple[str, ...] = ("tesseract", "auto", "ocrmac", "rapidocr", "deepseek")
NATIVE_OCR_ENGINES: Tuple[str, ...] = ("tesseract", "deepseek")
VALID_OCR_BACKENDS: Tuple[str, ...] = ("auto", "docling", "native")

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"})

# Characters in a page's text layer at or above which the page is read from
# that layer instead of being OCR'd. Same separation ``PdfiumTextParser``
# relies on: scanned pages sit at 0-17 chars, text pages in the hundreds+.
DEFAULT_TEXT_LAYER_MIN_CHARS = 32
# Chars-per-page floor for the near-empty guard when the setting is unusable.
_DEFAULT_MIN_CHARS_PER_PAGE = 20
_DEFAULT_RENDER_DPI = 200
_MIN_RENDER_DPI, _MAX_RENDER_DPI = 72, 600
# Pixel budget for one rendered page. pypdfium2 allocates width*height*4
# bytes up front with no cap of its own, so a 14400x14400 pt page (the PDF
# maximum; a 191-byte file) at 200 dpi would ask for 40000x40000 px = 6 GiB.
# 40 MP is ~10x a Letter page at 200 dpi and still OCRs an A0 poster at a
# usable ~125 dpi; anything larger renders at the scale that fits.
_MAX_RENDER_PIXELS = 40_000_000
_TESSERACT_TIMEOUT_SECONDS = 300
# tesseract reports a missing language pack on stderr and, when at least one
# other requested pack loads, exits 0 and silently OCRs with what it has —
# so the exit code alone cannot catch OCR_LANGS=eng+chi_sim without chi_sim.
_TESSERACT_LANG_ERROR_RE = re.compile(r"Error opening data file|Failed loading language")
_TESSERACT_LANG_RE = re.compile(r"^[A-Za-z0-9_/\-]+$")
# docling's DeepSeek-OCR prompt minus its ``<|grounding|>`` prefix: grounding
# makes the model wrap every element in ref/det tags with bounding boxes,
# which docling parses back into a layout tree. Plain Markdown is what the
# ingestion pipeline stores, so ask for that directly.
DEEPSEEK_PROMPT = "Convert the document to markdown."
_DEEPSEEK_MAX_TOKENS = 4096
# Defensive cleanup should a served model still emit grounding markup.
_DEEPSEEK_DET_BLOCK_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)
_DEEPSEEK_TAG_RE = re.compile(r"<\|/?ref\|>|<\|grounding\|>|<\|end▁of▁sentence\|>")
# tesseract's CJK models emit one space between every character ("互相 保密 协议")
# because they segment by glyph. Chinese and Japanese are written without
# word spaces, so collapse whitespace between two CJK characters (or CJK
# punctuation); spaces next to Latin text, digits and line breaks stay.
_CJK_CHAR = r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
_CJK_SPACE_RE = re.compile(rf"(?<={_CJK_CHAR})[ \t]+(?={_CJK_CHAR})")


class OcrUnavailableError(DocumentParseError):
    """The selected OCR engine cannot run on this host (missing binary or endpoint)."""


class OcrEngine(Protocol):
    """Anything that turns one page image into text."""

    name: str

    def ocr_image(self, image) -> str:  # pragma: no cover - protocol
        """Return the text (or Markdown) recognised in ``image`` (a PIL image)."""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def native_ocr_available() -> bool:
    """Whether the native backend's rendering stack (pypdfium2 + Pillow) is importable."""
    return module_available("pypdfium2") and module_available("PIL")


def resolve_ocr_backend(requested: Optional[str] = None) -> str:
    """Resolve ``OCR_BACKEND`` to the backend that will actually run.

    Args:
        requested: ``auto`` | ``docling`` | ``native``, or None to read the setting.

    Returns:
        ``"docling"`` or ``"native"``. ``auto`` prefers docling when it is
        installed; ``docling`` without the install degrades to native with a
        warning rather than leaving OCR off.
    """
    from application.core.settings import settings

    backend = str(requested or getattr(settings, "OCR_BACKEND", None) or "auto").strip().lower()
    if backend not in VALID_OCR_BACKENDS:
        logger.warning(f"Unknown OCR_BACKEND {backend!r}; using auto")
        backend = "auto"
    docling_installed = module_available("docling")
    if backend == "docling" and not docling_installed:
        logger.warning(
            "OCR_BACKEND=docling but docling is not installed (pip install -r "
            "application/requirements-docling.txt); using the native OCR backend"
        )
        return "native"
    if backend == "auto":
        return "docling" if docling_installed else "native"
    return backend


def resolve_native_ocr_engine(requested: Optional[str] = None) -> str:
    """Map ``OCR_ENGINE`` onto an engine the native backend implements.

    Args:
        requested: Engine name, or None to read ``settings.OCR_ENGINE``.

    Returns:
        ``"tesseract"`` or ``"deepseek"``. docling-only engines (``auto``,
        ``ocrmac``, ``rapidocr``) and unknown names become tesseract with a
        warning, so switching a deployment off docling never silently
        disables OCR.
    """
    from application.core.settings import settings

    engine = str(requested or getattr(settings, "OCR_ENGINE", None) or "tesseract").strip().lower()
    if engine in NATIVE_OCR_ENGINES:
        return engine
    if engine in VALID_OCR_ENGINES:
        logger.warning(
            f"OCR_ENGINE={engine!r} is only available through the docling backend; "
            "the native backend is using tesseract"
        )
    else:
        logger.warning(f"Unknown OCR_ENGINE {engine!r}; the native backend is using tesseract")
    return "tesseract"


def ocr_min_chars_per_page() -> int:
    """Chars-per-page floor for the near-empty OCR guard (``OCR_MIN_CHARS_PER_PAGE``); 0 disables it."""
    from application.core.settings import settings

    try:
        return int(getattr(settings, "OCR_MIN_CHARS_PER_PAGE", _DEFAULT_MIN_CHARS_PER_PAGE))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_CHARS_PER_PAGE


def render_dpi() -> int:
    """Rendering resolution for pages that need OCR (``OCR_RENDER_DPI``), clamped to a sane range."""
    from application.core.settings import settings

    try:
        dpi = int(getattr(settings, "OCR_RENDER_DPI", _DEFAULT_RENDER_DPI))
    except (TypeError, ValueError):
        dpi = _DEFAULT_RENDER_DPI
    return max(_MIN_RENDER_DPI, min(_MAX_RENDER_DPI, dpi))


def _has_alpha(image) -> bool:
    return "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)


def _png_bytes(image) -> bytes:
    """Encode a PIL image as PNG, flattening modes the engines cannot take.

    Transparency is composited onto white: a plain ``convert("RGB")`` drops
    the alpha channel and leaves transparent pixels black, which turns dark
    text on a transparent background into an all-black page that OCRs to
    nothing.
    """
    from PIL import Image

    if _has_alpha(image):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        image = canvas
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def fit_to_pixel_budget(image):
    """Downscale a decoded image to ``_MAX_RENDER_PIXELS`` before OCR.

    The same budget the PDF renderer applies: a 28 KB PNG can decode to
    81 MP (Pillow's bomb guard only trips at ~178 MP), and every extra
    pixel is paid again in the PNG re-encode and inside tesseract.
    """
    from PIL import Image

    width, height = image.size
    scale = render_scale(width, height, 72)
    if scale >= 1.0:
        return image
    if image.mode not in ("RGB", "L", "RGBA", "LA"):
        image = image.convert("RGBA" if _has_alpha(image) else "RGB")
    logger.warning(
        "Image is %dx%d px; downscaling to %.0f%% to stay within %d MP before OCR",
        width,
        height,
        scale * 100,
        _MAX_RENDER_PIXELS // 1_000_000,
    )
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.BILINEAR
    )


@functools.lru_cache(maxsize=1)
def tesseract_languages() -> Optional[frozenset]:
    """Language packs the ``tesseract`` binary reports (``--list-langs``), or None when unknown.

    Cached for the process: packs are installed with the image, not at runtime.
    """
    if shutil.which("tesseract") is None:
        return None
    try:
        completed = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.decode("utf-8", "replace") + "\n" + completed.stderr.decode("utf-8", "replace")
    langs = frozenset(
        line.strip() for line in output.splitlines() if _TESSERACT_LANG_RE.match(line.strip())
    )
    return langs or None


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


class TesseractEngine:
    """OCR through the system ``tesseract`` binary (stdin -> stdout, no Python wrapper).

    Attributes:
        languages: Tesseract language codes; None reads ``OCR_LANGS`` per call.
        psm: Page segmentation mode (3 = fully automatic, tesseract's default).
        timeout: Seconds allowed per page.
    """

    name = "tesseract"

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        psm: int = 3,
        timeout: float = _TESSERACT_TIMEOUT_SECONDS,
    ) -> None:
        self.languages = languages
        self.psm = psm
        self.timeout = timeout

    @staticmethod
    def available() -> bool:
        """Whether a ``tesseract`` binary is on PATH."""
        return shutil.which("tesseract") is not None

    def _language_arg(self) -> str:
        if self.languages:
            langs = [lang.strip() for lang in self.languages if lang and lang.strip()]
        else:
            from application.core.settings import settings

            configured = str(getattr(settings, "OCR_LANGS", "") or "eng")
            langs = [lang.strip() for lang in configured.split("+") if lang.strip()]
        return "+".join(langs) or "eng"

    def command(self) -> List[str]:
        """The tesseract command line, for logging and tests."""
        return ["tesseract", "stdin", "stdout", "-l", self._language_arg(), "--psm", str(self.psm)]

    def ocr_image(self, image) -> str:
        """OCR one PIL image.

        Raises:
            OcrUnavailableError: No tesseract binary on PATH.
            DocumentParseError: tesseract failed or timed out.
        """
        if not self.available():
            raise OcrUnavailableError(
                "OCR_ENGINE=tesseract but no tesseract binary is on PATH. Install "
                "tesseract-ocr plus language packs (Docker: build with "
                "INSTALL_TESSERACT=true; local: apt/brew install tesseract-ocr), "
                "or set OCR_ENGINE=deepseek / install the docling extra."
            )
        try:
            completed = subprocess.run(
                self.command(),
                input=_png_bytes(image),
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentParseError(f"tesseract timed out after {self.timeout:.0f}s on a page") from exc
        except OSError as exc:
            raise DocumentParseError(f"tesseract could not be started: {exc}") from exc
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        if _TESSERACT_LANG_ERROR_RE.search(stderr):
            # Exit code 0 here means tesseract dropped the missing pack and
            # OCR'd with the rest: Chinese scans would come out as garbage
            # with no signal. Fail the file and name the fix instead.
            raise OcrUnavailableError(
                f"tesseract could not load a language pack for OCR_LANGS={self._language_arg()!r}: "
                f"{stderr[:300]}. Install the tesseract-ocr-<lang> package for every language listed."
            )
        if completed.returncode != 0:
            raise DocumentParseError(f"tesseract failed (exit {completed.returncode}): {stderr[:300]}")
        return collapse_cjk_spaces(completed.stdout.decode("utf-8", "replace")).strip()


def collapse_cjk_spaces(text: str) -> str:
    """Remove the per-glyph spaces tesseract inserts inside CJK runs."""
    return _CJK_SPACE_RE.sub("", text)


def clean_deepseek_output(text: str) -> str:
    """Strip DeepSeek-OCR grounding markup, keeping the referenced text."""
    text = _DEEPSEEK_DET_BLOCK_RE.sub("", text)
    return _DEEPSEEK_TAG_RE.sub("", text).strip()


class DeepseekOcrEngine:
    """DeepSeek-OCR over an OpenAI-compatible chat-completions endpoint.

    One request per page, sequentially. The image travels as a base64 data
    URL, which both Ollama and vLLM accept. Pages are sent one at a time
    because the model server, not the worker, is the bottleneck; docling's
    default of four concurrent requests and a 90 s timeout is what broke on
    a laptop-hosted Ollama in testing.

    Attributes:
        url: Chat-completions URL (``OCR_DEEPSEEK_URL``).
        model: Model name at that endpoint (``OCR_DEEPSEEK_MODEL``).
        timeout: Seconds per page (``OCR_DEEPSEEK_TIMEOUT``).
        prompt: Instruction sent with every page image.
    """

    name = "deepseek"

    def __init__(
        self,
        url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt: str = DEEPSEEK_PROMPT,
        max_tokens: int = _DEEPSEEK_MAX_TOKENS,
    ) -> None:
        from application.core.settings import settings

        self.url = url or settings.OCR_DEEPSEEK_URL
        self.model = model or settings.OCR_DEEPSEEK_MODEL
        self.timeout = float(timeout if timeout is not None else getattr(settings, "OCR_DEEPSEEK_TIMEOUT", 300))
        self.prompt = prompt
        self.max_tokens = max_tokens

    def payload(self, image) -> Dict:
        """The chat-completions request body for one page image."""
        data_url = "data:image/png;base64," + base64.b64encode(_png_bytes(image)).decode("ascii")
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }

    def ocr_image(self, image) -> str:
        """OCR one PIL image through the endpoint.

        Raises:
            DocumentParseError: The request failed, timed out, or the
                response was not a chat completion.
        """
        import requests

        try:
            response = requests.post(self.url, json=self.payload(image), timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            # Subclasses RequestException too, so it must be caught first or a
            # proxy's HTML error page is reported as a connection failure.
            raise DocumentParseError(f"DeepSeek-OCR endpoint {self.url} returned a non-JSON body") from exc
        except requests.RequestException as exc:
            raise DocumentParseError(
                f"DeepSeek-OCR request to {self.url} failed: {exc}. Check OCR_DEEPSEEK_URL "
                f"and that model {self.model!r} is served (e.g. `ollama pull {self.model}`)."
            ) from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DocumentParseError(
                f"DeepSeek-OCR endpoint {self.url} returned no chat completion: {str(body)[:200]}"
            ) from exc
        if isinstance(content, list):  # some servers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return clean_deepseek_output(str(content or ""))


def build_native_ocr_engine(engine: Optional[str] = None, languages: Optional[List[str]] = None) -> OcrEngine:
    """Instantiate the engine ``OCR_ENGINE`` (or ``engine``) resolves to for the native backend."""
    resolved = resolve_native_ocr_engine(engine)
    if resolved == "deepseek":
        return DeepseekOcrEngine()
    return TesseractEngine(languages=languages)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def render_scale(page_width_pt: float, page_height_pt: float, dpi: int) -> float:
    """Render scale for a page of the given size at ``dpi``, capped by ``_MAX_RENDER_PIXELS``.

    The cap is what stands between an oversized (or hostile) MediaBox and a
    multi-gigabyte bitmap allocation in the ingest worker.
    """
    scale = dpi / 72.0
    area = max(1.0, float(page_width_pt)) * max(1.0, float(page_height_pt))
    max_scale = (_MAX_RENDER_PIXELS / area) ** 0.5
    return min(scale, max_scale)


def _render_page(page, dpi: int):
    """Render a pypdfium2 page to a PIL image at ``dpi``, within the pixel budget."""
    width_pt, height_pt = page.get_size()
    scale = render_scale(width_pt, height_pt, dpi)
    if scale < dpi / 72.0:
        logger.warning(
            "Page is %.0fx%.0f pt; rendering at %.0f dpi instead of %d to stay within %d MP",
            width_pt,
            height_pt,
            scale * 72.0,
            dpi,
            _MAX_RENDER_PIXELS // 1_000_000,
        )
    return page.render(scale=scale).to_pil()


def text_layer_counts(path: Path) -> List[int]:
    """Characters in each page's text layer (pypdfium2), in page order.

    Raises:
        Exception: Propagated from pypdfium2 when the file cannot be opened.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    counts: List[int] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    counts.append(max(0, textpage.count_chars()))
                finally:
                    textpage.close()
            finally:
                page.close()
    finally:
        pdf.close()
    return counts


def _page_has_image(page) -> bool:
    """Whether the page draws at least one image XObject (something OCR could read)."""
    import pypdfium2.raw as pdfium_c

    try:
        # pypdfium2's default max_depth=2 misses images inside nested Form
        # XObjects, which print drivers and InDesign produce routinely.
        objects = page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=16)
        return next(iter(objects), None) is not None
    except Exception:  # noqa: BLE001 - treat an unreadable page as image-bearing
        return True


def scanned_page_indices(path: Path, min_chars: int = DEFAULT_TEXT_LAYER_MIN_CHARS) -> List[int]:
    """0-based indices of the pages that look scanned: no text layer, or a thin one over an image.

    The probe behind mixed-document handling: a text-layer converter (anydoc)
    reads the text pages and silently skips these, so whoever owns OCR has to
    fill them in. A page with no text at all always qualifies. A page with a
    thin text layer (under ``min_chars``: a Bates stamp on a scan, a page
    number under a full-page figure) qualifies only when it also draws an
    image — a cover page reading just "Annual Report 2025" has nothing to OCR,
    and OCR-ing it would duplicate text the converter already read. Returns []
    when the file cannot be probed — the caller then keeps what it has rather
    than failing a successful parse.
    """
    import pypdfium2 as pdfium

    floor = max(1, int(min_chars))
    indices: List[int] = []
    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        count = max(0, textpage.count_chars())
                    finally:
                        textpage.close()
                    if count == 0 or (count < floor and _page_has_image(page)):
                        indices.append(index)
                finally:
                    page.close()
        finally:
            pdf.close()
    except Exception:  # noqa: BLE001 - a probe must never fail the parse
        logger.warning("Could not probe %s for scanned pages", Path(path).name, exc_info=True)
        return []
    return indices


def _check_near_empty(name: str, engine: str, content: str, pages: int, ocr_pages: int) -> None:
    """Loud failure for OCR that produced nothing, a warning for text-sparse documents.

    Mirrors the docling parser's dropout guard: failing only on positive
    evidence — several pages that OCR'd to literally nothing — because a
    photo, logo or chart is genuinely text-poor, and ``DocumentParseError``
    rejects the upload permanently.
    """
    if ocr_pages == 0:
        return
    floor = ocr_min_chars_per_page()
    chars = len(content.strip())
    if floor <= 0 or chars >= floor * pages:
        return
    if chars == 0 and pages > 1:
        raise DocumentParseError(
            f"OCR ({engine}) produced no text over {pages} pages of {name}; "
            "document not indexed. Check the engine's languages (OCR_LANGS) and "
            "that the scan is legible."
        )
    logger.warning(
        "%s OCR'd (%s) to only %d chars over %d page(s); indexing it as text-sparse",
        name,
        engine,
        chars,
        pages,
    )


class NativeOcrPdfParser(BaseParser):
    """PDF parser that OCRs pages without a text layer and reads the rest directly.

    Per page: a text layer of at least ``min_text_chars`` characters is read
    with pypdfium2; anything thinner is rendered and sent to the engine. So
    a scan, a born-digital PDF and a mix of both all come out right without
    any prior classification.

    Attributes:
        engine: The ``OcrEngine``; built from ``OCR_ENGINE`` on first use when None.
        text_parser: Optional parser for documents whose *every* page has a
            text layer — used under ``DOC_PARSER_ENGINE=docling`` to keep
            docling's structured Markdown for text PDFs while scans take the
            native OCR path. None reads text layers with pypdfium2.
        min_text_chars: Text-layer characters per page below which the page is OCR'd.
        ocr_enabled: Always True; lets callers that inspect their fallback
            parser (``AnydocParser``) phrase their errors correctly.
        last_engine: Engine name behind the most recent parse.
    """

    ocr_enabled = True

    def __init__(
        self,
        engine: Optional[OcrEngine] = None,
        text_parser: Optional[BaseParser] = None,
        min_text_chars: int = DEFAULT_TEXT_LAYER_MIN_CHARS,
        parser_config: Optional[Dict] = None,
    ) -> None:
        super().__init__(parser_config)
        self.engine = engine
        self.text_parser = text_parser
        self.min_text_chars = max(1, int(min_text_chars))
        self.last_engine: Optional[str] = None
        self._last_metadata: Dict = {}

    def _init_parser(self) -> Dict:
        try:
            import pypdfium2  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            raise ImportError("pypdfium2 and Pillow are required for NativeOcrPdfParser") from exc
        if self.engine is None:
            self.engine = build_native_ocr_engine()
        return {
            "engine": self.engine.name,
            "text_parser": type(self.text_parser).__name__ if self.text_parser else None,
            "min_text_chars": self.min_text_chars,
        }

    def _ensure_engine(self) -> OcrEngine:
        if self.engine is None:
            self.engine = build_native_ocr_engine()
        return self.engine

    def _text_layer_counts(self, pdf) -> List[int]:
        counts: List[int] = []
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    counts.append(max(0, textpage.count_chars()))
                finally:
                    textpage.close()
            finally:
                page.close()
        return counts

    def ocr_pages(self, file: Path, indices: List[int]) -> Dict[int, str]:
        """OCR only the given 0-based pages of ``file``, ignoring their text layers.

        Used by ``AnydocParser`` for mixed documents: anydoc has already read
        the text pages, so only the scanned ones come here.

        Returns:
            Page index -> recognised text, in the order requested.

        Raises:
            DocumentParseError: The file cannot be opened or the engine failed.
        """
        import pypdfium2 as pdfium

        path = Path(file)
        engine = self._ensure_engine()
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception as exc:
            raise DocumentParseError(f"Failed to open {path.name} with pypdfium2: {exc}") from exc
        texts: Dict[int, str] = {}
        try:
            dpi = render_dpi()
            for index in indices:
                if index < 0 or index >= len(pdf):
                    continue
                page = pdf[index]
                try:
                    texts[index] = (engine.ocr_image(_render_page(page, dpi)) or "").strip()
                finally:
                    page.close()
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"Failed to OCR pages of {path.name} ({engine.name}): {exc}") from exc
        finally:
            pdf.close()
        self.last_engine = engine.name
        return texts

    def text_layer_delegate(self, file: Path) -> Optional[BaseParser]:
        """The ``text_parser`` that ``parse_file`` would hand ``file`` to, or None.

        None when there is no text parser, the file cannot be opened, or any
        page falls below ``min_text_chars`` (those are OCR'd here). Callers
        that want a by-product of the delegate's conversion (docling tables)
        can run it directly instead of converting the document twice.
        """
        if self.text_parser is None:
            return None
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(Path(file)))
        except Exception:  # noqa: BLE001 - a probe; parse_file reports the real error
            return None
        try:
            counts = self._text_layer_counts(pdf)
        except Exception:  # noqa: BLE001
            return None
        finally:
            pdf.close()
        if counts and all(count >= self.min_text_chars for count in counts):
            return self.text_parser
        return None

    def _delegate_text(self, path: Path, errors: str) -> Union[str, List[str]]:
        text_parser = self.text_parser
        assert text_parser is not None
        logger.info(
            "%s has a text layer on every page; parsing with %s instead of OCR",
            path.name,
            type(text_parser).__name__,
        )
        result = delegate_parse(text_parser, path, errors)
        self.last_engine = getattr(text_parser, "last_engine", None) or type(text_parser).__name__
        self._last_metadata = {**text_parser.get_file_metadata(path), "parse_engine": self.last_engine}
        return result

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse a PDF, OCR-ing only the pages that need it.

        Raises:
            DocumentParseError: The file cannot be opened, the engine failed,
                or several pages OCR'd to nothing.
        """
        import pypdfium2 as pdfium

        path = Path(file)
        engine = self._ensure_engine()
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception as exc:
            raise DocumentParseError(f"Failed to open {path.name} with pypdfium2: {exc}") from exc

        pages_text: List[str] = []
        ocr_pages = 0
        try:
            page_count = len(pdf)
            if page_count == 0:
                raise DocumentParseError(f"{path.name} has no pages")
            counts = self._text_layer_counts(pdf)
            if self.text_parser is not None and all(count >= self.min_text_chars for count in counts):
                pdf.close()
                pdf = None
                return self._delegate_text(path, errors)
            dpi = render_dpi()
            for index in range(page_count):
                page = pdf[index]
                try:
                    if counts[index] >= self.min_text_chars:
                        textpage = page.get_textpage()
                        try:
                            text = textpage.get_text_bounded()
                        finally:
                            textpage.close()
                    else:
                        text = engine.ocr_image(_render_page(page, dpi))
                        ocr_pages += 1
                finally:
                    page.close()
                pages_text.append((text or "").strip())
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"Failed to parse {path.name} with native OCR ({engine.name}): {exc}") from exc
        finally:
            if pdf is not None:
                pdf.close()

        content = "\n\n".join(pages_text)
        _check_near_empty(path.name, engine.name, content, page_count, ocr_pages)
        self.last_engine = engine.name
        self._last_metadata = {"parse_engine": engine.name, "pdf_pages": page_count, "ocr_pages": ocr_pages}
        logger.info(
            "Parsed %s with native OCR (%s): %d/%d page(s) OCR'd, %d chars",
            path.name,
            engine.name,
            ocr_pages,
            page_count,
            len(content),
        )
        return content

    def get_file_metadata(self, file: Path) -> Dict:
        """Engine and page counts for the most recently parsed file."""
        _ = file
        return dict(self._last_metadata)


class NativeOcrImageParser(BaseParser):
    """Image parser that OCRs every frame (multi-page TIFFs included) with the native engine."""

    ocr_enabled = True

    def __init__(self, engine: Optional[OcrEngine] = None, parser_config: Optional[Dict] = None) -> None:
        super().__init__(parser_config)
        self.engine = engine
        self.last_engine: Optional[str] = None
        self._last_metadata: Dict = {}

    def _init_parser(self) -> Dict:
        try:
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            raise ImportError("Pillow is required for NativeOcrImageParser") from exc
        if self.engine is None:
            self.engine = build_native_ocr_engine()
        return {"engine": self.engine.name}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """OCR an image file.

        Only TIFF frames are pages (multi-page faxes and scans); every other
        multi-frame format is an animation (GIF, WebP, APNG) whose frames
        repeat one picture, so only the first is OCR'd — a 50-frame WebP
        would otherwise cost 50 tesseract runs and then be rejected as an
        empty multi-page document.

        Raises:
            DocumentParseError: The image cannot be decoded, the engine failed,
                or a multi-frame image OCR'd to nothing.
        """
        from PIL import Image, ImageSequence

        _ = errors
        path = Path(file)
        if self.engine is None:
            self.engine = build_native_ocr_engine()
        engine = self.engine
        texts: List[str] = []
        try:
            with Image.open(path) as image:
                frames = ImageSequence.Iterator(image) if path.suffix.lower() in (".tif", ".tiff") else [image]
                for frame in frames:
                    texts.append((engine.ocr_image(fit_to_pixel_budget(frame)) or "").strip())
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"Failed to OCR {path.name} ({engine.name}): {exc}") from exc

        content = "\n\n".join(texts)
        _check_near_empty(path.name, engine.name, content, max(1, len(texts)), len(texts))
        self.last_engine = engine.name
        self._last_metadata = {"parse_engine": engine.name, "ocr_pages": len(texts)}
        return content

    def get_file_metadata(self, file: Path) -> Dict:
        """Engine and frame count for the most recently parsed file."""
        _ = file
        return dict(self._last_metadata)
