"""Native OCR parsers: scanned PDFs and images without docling.

OCR in DocsGPT has two backends, selected by ``OCR_BACKEND``:

* ``docling`` — the layout-model pipeline in ``docling_parser.py``. Hybrid
  OCR (only the bitmap regions of a page), reading-order and table
  structure recovery, and four engines (tesseract / auto / ocrmac /
  rapidocr). Costs the optional docling install (torch, ONNX models,
  gigabytes of image) and seconds to minutes per file.
* ``native`` (this module) — page rendering with pypdfium2 and Pillow, both
  core dependencies, feeding one of two engines directly: the system
  ``tesseract`` binary, or a DeepSeek-OCR model behind an OpenAI-compatible
  endpoint (a local Ollama / vLLM, or a hosted API such as Novita or
  DeepInfra). DeepSeek-OCR always runs here, never through docling. No ML
  models load in the worker. Pages that carry a text layer are read through
  pypdfium2 and never OCR'd; pages without one are rendered and OCR'd. What
  it lacks against docling is the layout model: multi-column scans rely on
  tesseract's own page segmentation, and tesseract yields tables as plain
  lines (DeepSeek-OCR emits Markdown tables itself).

``auto`` picks docling when it is installed and native otherwise (always
native under ``OCR_ENGINE=deepseek``), so a deployment that never installs
the docling extra gets working OCR from the tesseract binary alone, and one
that does install it keeps today's behaviour unchanged.
"""
import base64
import hashlib
import functools
import io
import logging
import random
import re
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Hashable, Iterable, List, Optional, Protocol, Tuple, TypeVar, Union

from docsgpt.parser.file.base_parser import (
    BaseParser,
    DocumentParseError,
    TransientParseError,
    delegate_parse,
    module_available,
)

from docsgpt.core.optional_deps import install_hint

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
# Default instruction (``OCR_DEEPSEEK_PROMPT``). Measured 2026-09 on real
# pages against their text layers, Ollama deepseek-ocr:3b: "Free OCR." kept
# 94-100% of the words and wrote tables as Markdown; "Convert the document to
# markdown." kept 17% of a table page, because it emits HTML tables whose
# cell tags the server strips as special tokens, gluing every cell together.
DEEPSEEK_PROMPT = "Free OCR."
_DEEPSEEK_MAX_TOKENS = 4096
# Where DeepSeek-OCR runs: provider -> (chat-completions URL, model, hosted).
# Hosted presets need an API key and default to concurrent page requests; a
# laptop-hosted Ollama only slows down under parallel requests.
DEEPSEEK_PROVIDERS: Dict[str, Tuple[Optional[str], Optional[str], bool]] = {
    "ollama": ("http://localhost:11434/v1/chat/completions", "deepseek-ocr:3b", False),
    "vllm": ("http://localhost:8000/v1/chat/completions", "deepseek-ai/DeepSeek-OCR", False),
    "novita": ("https://api.novita.ai/openai/chat/completions", "deepseek/deepseek-ocr-2", True),
    "deepinfra": ("https://api.deepinfra.com/v1/openai/chat/completions", "deepseek-ai/DeepSeek-OCR", True),
    "custom": (None, None, False),
}
# Providers whose default is several pages in flight: hosted APIs and vLLM,
# which batches concurrent requests on the GPU.
_CONCURRENT_PROVIDERS = frozenset({"vllm", "novita", "deepinfra"})
_DEFAULT_HOSTED_CONCURRENCY = 4
# Statuses worth another attempt: rate limits and transient server failures.
_RETRY_STATUSES = (408, 409, 425, 429, 500, 502, 503, 504)
_MAX_RETRY_WAIT_SECONDS = 60.0
_BASE_RETRY_WAIT_SECONDS = 1.0
# Output cleanup. Grounding markup (<|ref|>/<|det|>, or the bare
# ``label[[x1, y1, x2, y2]]`` lines a server that strips special tokens
# leaves), chat-template tokens the model sometimes leaks, and the <p>/<br>
# tags it uses for plain paragraphs. HTML tables are kept: their structure
# is content.
_DEEPSEEK_DET_BLOCK_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)
_DEEPSEEK_TAG_RE = re.compile(
    r"<\|/?ref\|>|<\|grounding\|>|<\|end▁of▁sentence\|>|<\|im_(?:start|end|begin)\|>"
)
_DEEPSEEK_BOX_LINE_RE = re.compile(r"^[a-z_]+\[\[\d+(?:,\s*\d+){3}\]\]\s*$\n?", re.MULTILINE)
_HTML_BREAK_RE = re.compile(r"<br\s*/?>")
_HTML_PARAGRAPH_END_RE = re.compile(r"</p>[ \t]*")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
# tesseract's CJK models emit one space between every character ("互相 保密 协议")
# because they segment by glyph. Chinese and Japanese are written without
# word spaces, so collapse whitespace between two CJK characters (or CJK
# punctuation); spaces next to Latin text, digits and line breaks stay.
_CJK_CHAR = r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
_CJK_SPACE_RE = re.compile(rf"(?<={_CJK_CHAR})[ \t]+(?={_CJK_CHAR})")


class OcrRateLimitedError(TransientParseError):
    """The OCR endpoint kept answering 429 for longer than ``OCR_RATE_LIMIT_MAX_WAIT``.

    The file is fine; the quota is spent for now. ``SimpleDirectoryReader``
    defers such a file and parses it again after the other files, and the
    pages already recognised are kept, so only the missing ones are sent again.
    """


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
        ``"docling"`` or ``"native"``. ``OCR_ENGINE=deepseek`` is always
        native. Otherwise ``auto`` prefers docling when it is installed;
        ``docling`` without the install degrades to native with a warning
        rather than leaving OCR off.
    """
    from docsgpt.core.settings import settings

    backend = str(requested or settings.OCR_BACKEND or "auto").strip().lower()
    if backend not in VALID_OCR_BACKENDS:
        logger.warning(f"Unknown OCR_BACKEND {backend!r}; using auto")
        backend = "auto"
    if str(settings.OCR_ENGINE or "").strip().lower() == "deepseek":
        # DeepSeek-OCR is an HTTP call per page; the native parsers make it
        # directly, so it never needs (or loads) docling.
        if backend == "docling":
            logger.info("OCR_ENGINE=deepseek runs on the native OCR backend; ignoring OCR_BACKEND=docling")
        return "native"
    docling_installed = module_available("docling")
    if backend == "docling" and not docling_installed:
        logger.warning(
            "OCR_BACKEND=docling but docling is not installed (%s); using the native OCR backend",
            install_hint("docling"),
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
    from docsgpt.core.settings import settings

    engine = str(requested or settings.OCR_ENGINE or "tesseract").strip().lower()
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
    from docsgpt.core.settings import settings

    try:
        return int(settings.OCR_MIN_CHARS_PER_PAGE)
    except (TypeError, ValueError):
        return _DEFAULT_MIN_CHARS_PER_PAGE


def render_dpi() -> int:
    """Rendering resolution for pages that need OCR (``OCR_RENDER_DPI``), clamped to a sane range."""
    from docsgpt.core.settings import settings

    try:
        dpi = int(settings.OCR_RENDER_DPI)
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
            from docsgpt.core.settings import settings

            configured = str(settings.OCR_LANGS or "eng")
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
    """Strip DeepSeek-OCR grounding markup and leaked tokens; turn <p>/<br> into line breaks."""
    text = _DEEPSEEK_DET_BLOCK_RE.sub("", text)
    text = _DEEPSEEK_TAG_RE.sub("", text)
    text = _DEEPSEEK_BOX_LINE_RE.sub("", text)
    text = _HTML_BREAK_RE.sub("\n", text)
    text = _HTML_PARAGRAPH_END_RE.sub("\n\n", text).replace("<p>", "")
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def _sleep(seconds: float) -> None:
    """Backoff wait; a module attribute so tests can skip it."""
    time.sleep(seconds)


def _monotonic() -> float:
    """The clock a request's rate-limit budget is measured on; a module attribute so tests can move it."""
    return time.monotonic()


def _wall_now() -> float:
    """Wall-clock seconds, for an HTTP-date ``Retry-After``; a module attribute so tests can fix it."""
    return time.time()


@dataclass(frozen=True)
class DeepseekEndpoint:
    """The DeepSeek-OCR endpoint the settings resolve to.

    Attributes:
        provider: ``OCR_DEEPSEEK_PROVIDER``.
        url: Chat-completions URL.
        model: Model name at that URL.
        api_key: Bearer token, or None for a keyless local server.
        timeout: Seconds per page request.
        concurrency: Page requests in flight per file.
        max_retries: Retries per page after a 429, a 5xx or a refused connection.
        hosted: Whether the preset is a third-party API.
        prompt: Instruction sent with every page (``OCR_DEEPSEEK_PROMPT``).
        problem: Why the endpoint cannot be used as configured, or None.
    """

    provider: str
    url: str
    model: str
    api_key: Optional[str]
    timeout: float
    concurrency: int
    max_retries: int
    hosted: bool
    prompt: str = DEEPSEEK_PROMPT
    problem: Optional[str] = None

    def headers(self) -> Dict[str, str]:
        """Request headers: the bearer token when one is configured."""
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def describe(self) -> str:
        """One line for logs and ``docsgpt ocr-check``; never includes the key."""
        key = "set" if self.api_key else "none"
        return (
            f"provider={self.provider} url={self.url or '(unset)'} model={self.model or '(unset)'} "
            f"api_key={key} concurrency={self.concurrency} timeout={self.timeout:.0f}s retries={self.max_retries}"
        )


def resolve_deepseek_endpoint() -> DeepseekEndpoint:
    """Resolve ``OCR_DEEPSEEK_*`` into an endpoint: the provider preset, overridden by explicit values.

    Never raises: a configuration that cannot work (a hosted preset without a
    key, ``custom`` without a URL or model) comes back with ``problem`` set,
    and the engine raises it only when a page actually needs OCR — so
    text-layer documents keep parsing, as with a missing tesseract binary.
    """
    from docsgpt.core.settings import settings

    provider = str(settings.OCR_DEEPSEEK_PROVIDER or "ollama").strip().lower()
    if provider not in DEEPSEEK_PROVIDERS:
        logger.warning(f"Unknown OCR_DEEPSEEK_PROVIDER {provider!r}; using ollama")
        provider = "ollama"
    preset_url, preset_model, hosted = DEEPSEEK_PROVIDERS[provider]
    url = settings.OCR_DEEPSEEK_URL or preset_url or ""
    model = settings.OCR_DEEPSEEK_MODEL or preset_model or ""
    api_key = settings.OCR_DEEPSEEK_API_KEY
    if not api_key and provider == "novita":
        api_key = settings.NOVITA_API_KEY
    concurrency = settings.OCR_DEEPSEEK_CONCURRENCY or (
        _DEFAULT_HOSTED_CONCURRENCY if provider in _CONCURRENT_PROVIDERS else 1
    )
    problem = None
    if not url:
        problem = f"OCR_DEEPSEEK_PROVIDER={provider} needs OCR_DEEPSEEK_URL (the chat-completions URL)"
    elif not model:
        problem = f"OCR_DEEPSEEK_PROVIDER={provider} needs OCR_DEEPSEEK_MODEL (the model name at {url})"
    elif hosted and not api_key:
        extra = " (or NOVITA_API_KEY)" if provider == "novita" else ""
        problem = f"OCR_DEEPSEEK_PROVIDER={provider} needs an API key: set OCR_DEEPSEEK_API_KEY{extra}"
    return DeepseekEndpoint(
        provider=provider,
        url=url,
        model=model,
        api_key=api_key,
        timeout=float(settings.OCR_DEEPSEEK_TIMEOUT),
        concurrency=max(1, int(concurrency)),
        max_retries=max(0, int(settings.OCR_DEEPSEEK_MAX_RETRIES)),
        hosted=hosted,
        prompt=str(settings.OCR_DEEPSEEK_PROMPT or "").strip() or DEEPSEEK_PROMPT,
        problem=problem,
    )


def _header(response, name: str) -> Optional[str]:
    """A response header by name, whatever its case (tests pass plain dicts)."""
    headers = getattr(response, "headers", None) or {}
    value = headers.get(name)
    if value is not None:
        return value
    wanted = name.lower()
    for key, candidate in headers.items():
        if str(key).lower() == wanted:
            return candidate
    return None


def _retry_after_seconds(response) -> Optional[float]:
    """How long the server asked to wait: ``retry-after-ms`` (Azure), else ``Retry-After`` in seconds or as an HTTP date.

    Returns:
        Seconds, or None when the server sent neither (or something unreadable).
    """
    millis = _header(response, "retry-after-ms")
    if millis is not None:
        try:
            return max(0.0, float(millis) / 1000.0)
        except (TypeError, ValueError):
            pass
    value = _header(response, "Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - _wall_now())


def _backoff_seconds(attempt: int) -> float:
    return min(_MAX_RETRY_WAIT_SECONDS, _BASE_RETRY_WAIT_SECONDS * 2**attempt + random.uniform(0, 0.5))


def _rate_limit_wait(response, attempt: int) -> float:
    """The wait before retrying a 429: the server's ask or the backoff, whichever is longer, capped."""
    asked = _retry_after_seconds(response)
    return min(_MAX_RETRY_WAIT_SECONDS, max(asked or 0.0, _backoff_seconds(attempt)))


def _token_count(value) -> int:
    """A usage count from a response; a server that omits or garbles it counts as 0."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):  # OverflowError: 1e309 decodes to inf
        return 0


def _error_body(response) -> str:
    try:
        return str(response.text or "").strip()[:300]
    except Exception:  # noqa: BLE001 - only for the error message
        return ""


class DeepseekOcrEngine:
    """DeepSeek-OCR over an OpenAI-compatible chat-completions endpoint.

    One request per page. The image travels as a base64 data URL, which
    Ollama, vLLM and the hosted APIs all accept. Local presets send pages one
    at a time because the model server, not the worker, is the bottleneck
    (docling's four concurrent requests with a 90 s timeout broke a
    laptop-hosted Ollama in testing); hosted presets default to several in
    flight, which ``ocr_images`` schedules. Rate limits and 5xx responses are
    retried with backoff; token usage is summed for the file's metadata.

    Attributes:
        url: Chat-completions URL.
        model: Model name at that endpoint.
        timeout: Seconds per page.
        concurrency: Page requests in flight per file.
        max_retries: Retries per page after a transient failure.
        prompt: Instruction sent with every page image.
    """

    name = "deepseek"

    def __init__(
        self,
        url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt: Optional[str] = None,
        max_tokens: int = _DEEPSEEK_MAX_TOKENS,
        endpoint: Optional[DeepseekEndpoint] = None,
    ) -> None:
        resolved = endpoint or resolve_deepseek_endpoint()
        self.endpoint = resolved
        self.url = url or resolved.url
        self.model = model or resolved.model
        self.timeout = float(timeout if timeout is not None else resolved.timeout)
        self.concurrency = resolved.concurrency
        self.max_retries = resolved.max_retries
        self.prompt = prompt or resolved.prompt
        self.max_tokens = max_tokens
        # An explicit URL and model mean the caller configured the endpoint itself.
        self._problem = None if (url and model) else resolved.problem
        self._usage_lock = threading.Lock()
        self._usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self._rate_stats = _empty_rate_stats()
        # Slots shared by every engine and worker process sending to this URL.
        from docsgpt.parser.file.ocr_limiter import limiter_for

        self.limiter = limiter_for(self.name, self.url, lease_seconds=self.timeout + 60)

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

    def usage(self) -> Dict[str, int]:
        """Requests and tokens since the last ``reset_usage``."""
        with self._usage_lock:
            return dict(self._usage)

    def reset_usage(self) -> None:
        """Start counting usage for a new file."""
        with self._usage_lock:
            self._usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}
            self._rate_stats = _empty_rate_stats()

    def rate_limit_stats(self) -> Dict[str, Any]:
        """Requests sent (``attempts``, retries included), 429s and seconds waited since the last ``reset_usage``."""
        with self._usage_lock:
            return dict(self._rate_stats)

    def _count(self, key: str, amount: float = 1) -> None:
        with self._usage_lock:
            self._rate_stats[key] += amount

    def _record_usage(self, body: Dict) -> None:
        usage = body.get("usage") if isinstance(body, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        with self._usage_lock:
            self._usage["requests"] += 1
            for key in ("prompt_tokens", "completion_tokens"):
                self._usage[key] += _token_count(usage.get(key))

    def _send(self, body: Dict, headers: Dict[str, str], deadline: Optional[float] = None):
        """One request, holding a slot of the endpoint's shared in-flight limit.

        Args:
            body: The request body.
            headers: The request headers.
            deadline: For a retry after a 429: the ``_monotonic()`` time the
                rate-limit budget runs out; past it once a slot is free, nothing is sent.

        Raises:
            OcrRateLimitedError: The budget ran out while this waited for a slot.
        """
        import requests

        with self.limiter.slot():
            if deadline is not None and _monotonic() >= deadline:
                raise OcrRateLimitedError(
                    f"DeepSeek-OCR endpoint {self.url} rate-limit budget ran out while waiting for a request slot; "
                    "the page will be tried again later."
                )
            self._count("attempts")
            return requests.post(self.url, json=body, headers=headers, timeout=self.timeout)

    def _post(self, body: Dict):
        """POST one page, retrying rate limits, 5xx responses and refused connections.

        A 429 is retried until ``OCR_RATE_LIMIT_MAX_WAIT`` has passed since the
        first try, each wait the longer of what the server asked for and the
        backoff. Other transient failures are retried ``max_retries`` times.

        Raises:
            OcrUnavailableError: The endpoint rejected the key or does not serve the model.
            OcrRateLimitedError: Still rate limited when the budget ran out.
            TransientParseError: A 5xx, a refused connection or a timeout, after the retries.
            DocumentParseError: Any other failure.
        """
        import requests

        from docsgpt.core.settings import settings

        headers = self.endpoint.headers()
        budget = max(0.0, float(settings.OCR_RATE_LIMIT_MAX_WAIT))
        started = _monotonic()
        attempt = 0
        rate_limited = 0
        while True:
            try:
                # Only a retry after a 429 is bound by the budget; the first try always goes.
                response = self._send(body, headers, deadline=started + budget if rate_limited else None)
            except requests.exceptions.ConnectionError as exc:
                # ConnectTimeout lands here too; a read timeout does not.
                if attempt < self.max_retries:
                    wait_s = _backoff_seconds(attempt)
                    logger.debug(f"DeepSeek-OCR endpoint {self.url} unreachable ({exc}); retrying in {wait_s:.1f}s")
                    self._wait(wait_s)
                    attempt += 1
                    continue
                raise TransientParseError(
                    f"DeepSeek-OCR request to {self.url} failed: {exc}. Check OCR_DEEPSEEK_URL "
                    f"and that model {self.model!r} is served (e.g. `ollama pull {self.model}`)."
                ) from exc
            except requests.exceptions.Timeout as exc:
                raise TransientParseError(
                    f"DeepSeek-OCR request to {self.url} timed out after {self.timeout:.0f}s on a page; "
                    "raise OCR_DEEPSEEK_TIMEOUT for a slow model server."
                ) from exc
            except requests.RequestException as exc:
                raise TransientParseError(f"DeepSeek-OCR request to {self.url} failed: {exc}") from exc

            status = response.status_code
            if status == 429:
                self._count("rate_limited")
                self.limiter.record_rate_limited()
                left = budget - (_monotonic() - started)
                wait_s = _rate_limit_wait(response, rate_limited)
                if left <= 0 or wait_s >= left:
                    # The wait would end past the budget: give the page up now
                    # rather than sleep and send a request that can't count.
                    raise OcrRateLimitedError(
                        f"DeepSeek-OCR endpoint {self.url} was still rate limiting after "
                        f"{budget - max(0.0, left):.0f}s of a {budget:.0f}s budget "
                        f"({rate_limited + 1} rate-limited answers); the page will be tried again later. "
                        "Lower OCR_MAX_IN_FLIGHT or raise the provider's quota."
                    )
                logger.debug(f"DeepSeek-OCR endpoint {self.url} returned 429; retrying in {wait_s:.1f}s")
                self._wait(wait_s)
                rate_limited += 1
                continue
            if status in _RETRY_STATUSES and attempt < self.max_retries:
                wait_s = _backoff_seconds(attempt)
                logger.debug(f"DeepSeek-OCR endpoint {self.url} returned {status}; retrying in {wait_s:.1f}s")
                self._wait(wait_s)
                attempt += 1
                continue
            if status in (401, 403):
                raise OcrUnavailableError(
                    f"DeepSeek-OCR endpoint {self.url} rejected the request ({status}): {_error_body(response)}. "
                    "Check OCR_DEEPSEEK_API_KEY."
                )
            if status == 404:
                raise OcrUnavailableError(
                    f"DeepSeek-OCR endpoint {self.url} returned 404 for model {self.model!r}: "
                    f"{_error_body(response)}. Check OCR_DEEPSEEK_URL and OCR_DEEPSEEK_MODEL "
                    f"(for Ollama: `ollama pull {self.model}`)."
                )
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                error = TransientParseError if status in _RETRY_STATUSES else DocumentParseError
                raise error(
                    f"DeepSeek-OCR endpoint {self.url} returned {status}: {_error_body(response)}"
                ) from exc
            self.limiter.record_success()
            return response

    def _wait(self, seconds: float) -> None:
        self._count("waited_seconds", seconds)
        _sleep(seconds)

    def ocr_image(self, image) -> str:
        """OCR one PIL image through the endpoint.

        Raises:
            OcrUnavailableError: The endpoint is misconfigured, rejected the
                key or does not serve the model.
            DocumentParseError: The request failed, timed out, or the
                response was not a chat completion.
        """
        if self._problem:
            raise OcrUnavailableError(self._problem)
        response = self._post(self.payload(image))
        try:
            body = response.json()
        except ValueError as exc:  # requests' JSONDecodeError included: a proxy's HTML error page
            raise DocumentParseError(f"DeepSeek-OCR endpoint {self.url} returned a non-JSON body") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DocumentParseError(
                f"DeepSeek-OCR endpoint {self.url} returned no chat completion: {str(body)[:200]}"
            ) from exc
        self._record_usage(body)
        if isinstance(content, list):  # some servers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return clean_deepseek_output(str(content or ""))


def _empty_rate_stats() -> Dict[str, Any]:
    return {"attempts": 0, "rate_limited": 0, "waited_seconds": 0.0}


def build_native_ocr_engine(engine: Optional[str] = None, languages: Optional[List[str]] = None) -> OcrEngine:
    """Instantiate the engine ``OCR_ENGINE`` (or ``engine``) resolves to for the native backend."""
    resolved = resolve_native_ocr_engine(engine)
    if resolved == "deepseek":
        return DeepseekOcrEngine()
    return TesseractEngine(languages=languages)


K = TypeVar("K", bound=Hashable)


def ocr_images(
    engine: OcrEngine,
    items: Iterable[Tuple[K, object]],
    skip_failed: bool = False,
    failures: Optional[Dict[K, BaseException]] = None,
) -> Dict[K, str]:
    """OCR ``(key, image)`` pairs, up to ``engine.concurrency`` requests at a time.

    ``items`` is consumed on the calling thread — PDF pages are rendered
    there, since pypdfium2 is not thread-safe — and no more than twice the
    concurrency of rendered pages wait for a free slot, so a 500-page scan
    never sits in memory at once. Engines without a ``concurrency``
    attribute (tesseract) run sequentially.

    Args:
        engine: The OCR engine.
        items: Page keys and PIL images, in page order.
        skip_failed: Log and leave out a page whose OCR failed instead of
            raising (mixed documents, where the text pages are already safe).
        failures: When given, a failed page's error is stored here under its
            key instead of being raised, so the caller keeps every page that
            did come back. Once a page fails with ``OcrRateLimitedError`` or
            ``OcrUnavailableError`` no further pages are sent: each would
            fail the same way. The pages not sent are simply absent.

    Returns:
        Key -> stripped text, in the order ``items`` produced them.

    Raises:
        Exception: The first page failure, unless ``skip_failed`` or ``failures``.
    """
    workers = max(1, int(getattr(engine, "concurrency", 1) or 1))
    order: List[K] = []
    results: Dict[K, str] = {}
    stop = {"now": False}

    def _failed(key: K, exc: Exception) -> None:
        if failures is not None:
            failures[key] = exc
            if isinstance(exc, (OcrRateLimitedError, OcrUnavailableError)):
                stop["now"] = True
            return
        if not skip_failed:
            raise exc
        label = key + 1 if isinstance(key, int) else key
        logger.warning(f"OCR of page {label} failed ({exc}); skipping that page")

    def _close_items() -> None:
        close = getattr(items, "close", None)
        if callable(close):
            close()

    if workers == 1:
        for key, image in items:
            order.append(key)
            try:
                results[key] = (engine.ocr_image(image) or "").strip()
            except Exception as exc:  # noqa: BLE001 - re-raised unless skip_failed
                _failed(key, exc)
            if stop["now"]:
                _close_items()
                break
        return {key: results[key] for key in order if key in results}

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr")
    pending: Dict[Future, K] = {}

    def _collect(done) -> None:
        for future in done:
            key = pending.pop(future)
            try:
                results[key] = (future.result() or "").strip()
            except Exception as exc:  # noqa: BLE001 - re-raised unless skip_failed
                _failed(key, exc)

    try:
        for key, image in items:
            order.append(key)
            pending[pool.submit(engine.ocr_image, image)] = key
            while len(pending) >= workers * 2:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                _collect(done)
            if stop["now"]:
                _close_items()
                break
        while pending:
            if stop["now"]:
                # A terminal failure (a spent rate-limit budget, a refused key):
                # pages not yet sent stay missing for the retry instead of
                # spending another budget now.
                for future in [f for f in pending if f.cancel()]:
                    pending.pop(future)
                if not pending:
                    break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            _collect(done)
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return {key: results[key] for key in order if key in results}


def _reset_usage(engine: OcrEngine) -> None:
    reset = getattr(engine, "reset_usage", None)
    if callable(reset):
        reset()


def usage_metadata(engine: OcrEngine) -> Dict[str, int]:
    """Flat ``ocr_*`` usage fields for an engine that reports usage and made requests, else {}.

    Flat integers rather than a nested dict because parser metadata is
    copied onto every chunk, and not every vector store takes nested values.
    """
    usage_fn = getattr(engine, "usage", None)
    if not callable(usage_fn):
        return {}
    usage = usage_fn() or {}
    if not usage.get("requests"):
        return {}
    return {
        "ocr_requests": int(usage.get("requests", 0)),
        "ocr_prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "ocr_completion_tokens": int(usage.get("completion_tokens", 0)),
    }


def _log_usage(name: str, engine: OcrEngine, usage: Dict[str, int]) -> None:
    """One line per file: requests sent, 429s, time spent waiting, pages billed and tokens.

    Replaces a warning per retry, which drowned a rate-limited ingest's log.
    """
    stats_fn = getattr(engine, "rate_limit_stats", None)
    stats = stats_fn() if callable(stats_fn) else {}
    if not usage and not stats.get("attempts"):
        return
    logger.info(
        "OCR of %s (%s): %d request(s), %d rate limited (429), %.1fs waited, %d page(s) billed, "
        "%d prompt token(s), %d completion token(s)",
        name,
        engine.name,
        int(stats.get("attempts") or usage.get("ocr_requests", 0)),
        int(stats.get("rate_limited") or 0),
        float(stats.get("waited_seconds") or 0.0),
        int(usage.get("ocr_requests", 0)),
        int(usage.get("ocr_prompt_tokens", 0)),
        int(usage.get("ocr_completion_tokens", 0)),
    )


#: Files whose recognised pages a parser keeps after a failed parse, for the retry.
_KEPT_FILES = 256


def _missing_pages_error(
    path: Path,
    engine_name: str,
    failures: Dict[int, BaseException],
    missing: int,
    total: int,
    rate_limit_first: bool = False,
) -> DocumentParseError:
    """The error for a parse that could not OCR every page it needed.

    A page that failed for good (a misconfigured endpoint, a page the model
    refuses) makes the file fail for good; otherwise a rate limit makes it a
    file to try again later (``OcrRateLimitedError``), as does any other
    transient failure.

    Args:
        rate_limit_first: A rate-limited page wins over one that failed for
            good: a caller that skips failed pages (``ocr_pages(skip_failed=True)``)
            still wants the file set aside and tried again after the cool-down.
    """
    errors = list(failures.values())
    if rate_limit_first and any(isinstance(error, OcrRateLimitedError) for error in errors):
        return OcrRateLimitedError(
            f"{path.name}: {missing} of {total} scanned page(s) could not be OCR'd yet: the OCR endpoint is "
            f"rate limiting. The {total - missing} page(s) recognised are kept for the retry."
        )
    for error in errors:
        if isinstance(error, OcrUnavailableError):
            return error
    for error in errors:
        if not isinstance(error, TransientParseError):
            if isinstance(error, DocumentParseError):
                return error
            return DocumentParseError(f"Failed to parse {path.name} with native OCR ({engine_name}): {error}")
    if any(isinstance(error, OcrRateLimitedError) for error in errors):
        return OcrRateLimitedError(
            f"{path.name}: {missing} of {total} scanned page(s) could not be OCR'd yet: the OCR endpoint is "
            f"rate limiting. The {total - missing} page(s) recognised are kept for the retry."
        )
    if errors:
        return errors[0]  # a TransientParseError
    return TransientParseError(f"{path.name}: {missing} of {total} scanned page(s) were not OCR'd")


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
        batch_ocr_pages: ``ocr_pages`` takes several pages and ``skip_failed``,
            so ``AnydocParser`` hands it every scanned page at once.
        last_engine: Engine name behind the most recent parse.
        last_ocr_usage: ``ocr_*`` usage fields of the most recent ``ocr_pages`` call.
    """

    ocr_enabled = True
    batch_ocr_pages = True

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
        self.last_ocr_usage: Dict[str, int] = {}
        #: Pages ``ocr_pages(skip_failed=True)`` left out of its most recent result.
        self.last_ocr_failed_pages = 0
        self._last_metadata: Dict = {}
        # Pages recognised before a parse failed, so a retry of the same file
        # (same bytes, engine and resolution) sends only the missing ones.
        self._kept_pages: "OrderedDict[Tuple, Dict[int, str]]" = OrderedDict()
        self._kept_lock = threading.Lock()

    def _kept_key(self, path: Path, engine: OcrEngine, dpi: int) -> Optional[Tuple]:
        """The key of a file's recognised pages: its path and its content, the engine and the DPI."""
        try:
            stat = path.stat()
            digest = hashlib.sha256()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(block)
            return (str(path.resolve()), stat.st_size, digest.hexdigest(), engine.name, dpi)
        except OSError:
            return None

    def _kept(self, key: Optional[Tuple]) -> Dict[int, str]:
        if key is None:
            return {}
        with self._kept_lock:
            return dict(self._kept_pages.get(key) or {})

    def _keep(self, key: Optional[Tuple], pages: Dict[int, str]) -> None:
        if key is None:
            return
        with self._kept_lock:
            if pages:
                self._kept_pages[key] = dict(pages)
                self._kept_pages.move_to_end(key)
                while len(self._kept_pages) > _KEPT_FILES:
                    self._kept_pages.popitem(last=False)
            else:
                self._kept_pages.pop(key, None)

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

    def ocr_pages(self, file: Path, indices: List[int], skip_failed: bool = False) -> Dict[int, str]:
        """OCR only the given 0-based pages of ``file``, ignoring their text layers.

        Used by ``AnydocParser`` for mixed documents: anydoc has already read
        the text pages, so only the scanned ones come here.

        Args:
            file: The PDF.
            indices: 0-based pages to OCR; out-of-range ones are ignored.
            skip_failed: Leave out a page whose OCR failed instead of raising;
                ``last_ocr_failed_pages`` then says how many were left out. A
                rate limit still raises, so the file can be tried again.

        Returns:
            Page index -> recognised text, in the order requested.

        Raises:
            OcrRateLimitedError: A page was still rate limited when its budget
                ran out. The pages recognised are kept, and a retry of the same
                file sends only the missing ones.
            DocumentParseError: The file cannot be opened or the engine failed.
        """
        import pypdfium2 as pdfium

        path = Path(file)
        engine = self._ensure_engine()
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception as exc:
            raise DocumentParseError(f"Failed to open {path.name} with pypdfium2: {exc}") from exc
        _reset_usage(engine)
        self.last_ocr_failed_pages = 0
        failures: Dict[int, BaseException] = {}
        try:
            dpi = render_dpi()
            key = self._kept_key(path, engine, dpi)
            kept = self._kept(key)
            requested = [index for index in dict.fromkeys(indices) if 0 <= index < len(pdf)]

            def _pages():
                for index in requested:
                    if index in kept:
                        continue
                    page = pdf[index]
                    try:
                        image = _render_page(page, dpi)
                    finally:
                        page.close()
                    yield index, image

            kept.update(ocr_images(engine, _pages(), failures=failures))
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"Failed to OCR pages of {path.name} ({engine.name}): {exc}") from exc
        finally:
            pdf.close()
        self.last_engine = engine.name
        self.last_ocr_usage = usage_metadata(engine)
        _log_usage(path.name, engine, self.last_ocr_usage)
        missing = [index for index in requested if index not in kept]
        rate_limited = any(isinstance(error, OcrRateLimitedError) for error in failures.values())
        if missing and (rate_limited or not skip_failed):
            # Kept for the retry: only the missing pages are sent again.
            self._keep(key, kept)
            raise _missing_pages_error(
                path, engine.name, failures, len(missing), len(requested), rate_limit_first=skip_failed,
            )
        self._keep(key, {})
        for index, error in failures.items():
            logger.warning(f"OCR of page {index + 1} of {path.name} failed ({error}); skipping that page")
        self.last_ocr_failed_pages = len(missing)
        return {index: kept[index] for index in requested if index in kept}

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

        A page whose request fails fails only itself: the other pages are
        still recognised, and are kept on this parser, so parsing the same
        file again (unchanged, same engine and resolution) sends only the
        pages still missing. The text comes back only once every page has.

        Raises:
            OcrRateLimitedError: Pages were still rate limited when their
                budget ran out; the file can be parsed again later.
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
            pages_text = [""] * page_count
            key = self._kept_key(path, engine, dpi)
            kept = self._kept(key)
            scanned = [index for index in range(page_count) if counts[index] < self.min_text_chars]

            def _scanned_pages():
                # Reads text pages in place and yields renders of the rest, all
                # on this thread; only the OCR requests run concurrently. Pages
                # recognised by an earlier, failed parse of this file are kept.
                for index in range(page_count):
                    if index in kept:
                        continue
                    page = pdf[index]
                    try:
                        if counts[index] >= self.min_text_chars:
                            textpage = page.get_textpage()
                            try:
                                pages_text[index] = (textpage.get_text_bounded() or "").strip()
                            finally:
                                textpage.close()
                            continue
                        image = _render_page(page, dpi)
                    finally:
                        page.close()
                    yield index, image

            _reset_usage(engine)
            failures: Dict[int, BaseException] = {}
            kept.update(ocr_images(engine, _scanned_pages(), failures=failures))
            missing = [index for index in scanned if index not in kept]
            if missing:
                # A page that failed fails only itself: the rest are kept, and
                # a retry of this file sends only what is missing. Never a
                # partial text: the file is either whole or an error.
                self._keep(key, kept)
                self.last_ocr_usage = usage_metadata(engine)
                _log_usage(path.name, engine, self.last_ocr_usage)
                raise _missing_pages_error(path, engine.name, failures, len(missing), len(scanned))
            self._keep(key, {})
            for index in scanned:
                pages_text[index] = kept[index]
            ocr_pages = len(scanned)
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
        self.last_ocr_usage = usage_metadata(engine)
        self._last_metadata = {
            "parse_engine": engine.name,
            "pdf_pages": page_count,
            "ocr_pages": ocr_pages,
            **self.last_ocr_usage,
        }
        _log_usage(path.name, engine, self.last_ocr_usage)
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
        _reset_usage(engine)
        try:
            with Image.open(path) as image:
                frames = ImageSequence.Iterator(image) if path.suffix.lower() in (".tif", ".tiff") else [image]
                # A TIFF frame is the same object seeked to the next page, so a
                # frame handed to a concurrent request must be a copy.
                texts = ocr_images(
                    engine, ((index, fit_to_pixel_budget(frame).copy()) for index, frame in enumerate(frames))
                )
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"Failed to OCR {path.name} ({engine.name}): {exc}") from exc

        content = "\n\n".join(texts.values())
        _check_near_empty(path.name, engine.name, content, max(1, len(texts)), len(texts))
        self.last_engine = engine.name
        usage = usage_metadata(engine)
        self._last_metadata = {"parse_engine": engine.name, "ocr_pages": len(texts), **usage}
        _log_usage(path.name, engine, usage)
        return content

    def get_file_metadata(self, file: Path) -> Dict:
        """Engine and frame count for the most recently parsed file."""
        _ = file
        return dict(self._last_metadata)
