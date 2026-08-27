"""anydoc parser.

Converts documents to GitHub-Flavored Markdown with `firecrawl-anydoc
<https://github.com/firecrawl/anydoc>`_: a single Rust extension with no ML
models and no Python dependencies. Measured against docling on a 20-document
corpus it was 20-160x faster per file (1.2 s vs 193 s on a 150-page annual
report), imported in 6 ms instead of 3.9 s, and peaked at 107 MB RSS instead
of 2.3 GB, with equivalent output on clean office files, CSV and text-layer
PDFs.

anydoc never OCRs. It *detects* a scanned or image-only PDF and raises
``UnsupportedError`` ("OCR is required"), which is the routing point: a
parser given a ``fallback_parser`` (docling when installed, otherwise the
legacy parser for the suffix) delegates there; without one the file fails
loudly as ``DocumentParseError`` rather than being stored empty.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from application.core.settings import settings
from application.parser.file.base_parser import (
    BaseParser,
    DocumentParseError,
    delegate_parse,
    module_available,
)

logger = logging.getLogger(__name__)

# A fallback parse (scanned-PDF delegation or trust-check re-parse) yielding
# fewer stripped characters than this is an empty document in the making,
# not content.
_MIN_SCAN_FALLBACK_CHARS = 50

# Suffixes anydoc 0.2.3 converts, verified with ``anydoc.format_from_extension``.
# ``.epub`` is deliberately absent: it stays on ``EpubParser``.
ANYDOC_SUFFIXES: Tuple[str, ...] = (
    # Word processing
    ".pdf",
    ".docx",
    ".docm",
    ".doc",
    ".odt",
    ".rtf",
    # Presentations
    ".pptx",
    ".pptm",
    ".ppsx",
    ".ppsm",
    ".ppt",
    ".pps",
    ".pot",
    ".odp",
    # Spreadsheets / tabular
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".xls",
    ".ods",
    ".csv",
)


# The five formats every engine has its own parser for (docling / legacy);
# under the anydoc engine they get that parser as the fallback. Everything
# else in ``ANYDOC_SUFFIXES`` is anydoc-only ("gained") and is mapped to a
# fallback-less ``AnydocParser`` in every parser map.
_CORE_SUFFIXES = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".csv"})
ANYDOC_GAINED_SUFFIXES: Tuple[str, ...] = tuple(
    suffix for suffix in ANYDOC_SUFFIXES if suffix not in _CORE_SUFFIXES
)


def anydoc_available() -> bool:
    """Whether the ``anydoc`` extension can be imported."""
    return module_available("anydoc")


def _result_chars(result: Union[str, List[str]]) -> int:
    """Stripped character count of a parser result (str or list of rows)."""
    if isinstance(result, list):
        return sum(len(str(part).strip()) for part in result)
    return len(str(result).strip())


def _is_docling_backed(parser: Optional[BaseParser]) -> bool:
    """True when ``parser`` is a docling parser (worth a trust-check re-parse)."""
    if parser is None:
        return False
    try:
        from application.parser.file.docling_parser import DoclingParser
    except ImportError:
        return False
    return isinstance(parser, DoclingParser)


class AnydocParser(BaseParser):
    """Markdown conversion via ``anydoc.to_markdown`` with a typed fallback.

    Attributes:
        fallback_parser: Parser used when anydoc cannot convert the file
            (scanned PDF, unsupported or malformed input). ``None`` means
            such files raise ``DocumentParseError``.
        last_engine: Name of the engine that produced the most recent parse:
            ``"anydoc"``, or the fallback parser's ``last_engine`` / class
            name when it was delegated to. Mirrors ``PdfiumTextParser`` so
            the attachment worker records what actually ran.
    """

    def __init__(
        self,
        fallback_parser: Optional[BaseParser] = None,
        parser_config: Optional[Dict] = None,
    ) -> None:
        super().__init__(parser_config)
        self.fallback_parser = fallback_parser
        self.last_engine: Optional[str] = None
        # (path, problems) from the most recent parse whose output the trust
        # check flagged but kept — surfaced via ``get_file_metadata`` as
        # ``parse_warnings`` so the document carries its own caveat.
        self._last_warnings: Optional[Tuple[Path, List[str]]] = None

    def _init_parser(self) -> Dict:
        # Import for real rather than trusting ``find_spec``: a wheel whose
        # native extension fails to load (glibc/arch mismatch) has a spec but
        # no importable module, and that must fail here — where the ingest
        # task treats it as a setup error — not as a bare ImportError from
        # ``parse_file`` mid-batch, which ``load_data`` does not catch.
        try:
            import anydoc  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "firecrawl-anydoc is required for AnydocParser. "
                "Install it with: pip install firecrawl-anydoc"
            ) from exc
        fallback = self.fallback_parser
        return {"fallback_parser": type(fallback).__name__ if fallback else None}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Convert ``file`` to Markdown.

        Args:
            file: Path to the document.
            errors: Decoding error policy; anydoc decodes internally, so this
                is only forwarded to the fallback parser.

        Returns:
            The document as Markdown.

        Raises:
            DocumentParseError: When neither anydoc nor the fallback could
                produce text for the file, or anydoc hit a resource limit.
        """
        import anydoc

        path = Path(file)
        self._last_warnings = None
        try:
            content = anydoc.to_markdown(str(path))
        except anydoc.ResourceLimitError as exc:
            # anydoc refused because the file is too expensive (declared
            # decompression size, nesting depth, node count). A heavier
            # engine would spend exactly what was just refused, so this is
            # terminal rather than a reason to delegate.
            self.last_engine = None
            raise DocumentParseError(
                f"Failed to parse {path.name}: {type(exc).__name__}: {exc}"
            ) from exc
        except anydoc.ConvertError as exc:
            # Typed, per-document failures another engine may still handle:
            # UnsupportedError (scanned PDF / unknown format), MalformedError,
            # EncryptedError, MissingPartError.
            ocr_needed = isinstance(exc, anydoc.UnsupportedError) and "OCR" in str(exc)
            return self._delegate(
                path, errors, f"{type(exc).__name__}: {exc}", ocr_needed=ocr_needed
            )
        except OSError as exc:
            raise DocumentParseError(
                f"Failed to parse {path.name}: the file could not be read."
            ) from exc
        except Exception as exc:
            logger.error(f"anydoc failed on {path.name}: {exc}", exc_info=True)
            raise DocumentParseError(
                f"Failed to parse {path.name} with anydoc: {exc}"
            ) from exc

        if not content or not content.strip():
            return self._delegate(path, errors, "anydoc produced no text")

        self.last_engine = "anydoc"
        if path.suffix.lower() == ".pdf":
            content = self._finish_pdf(path, content, errors)
        return content

    def _finish_pdf(self, path: Path, content: str, errors: str) -> Union[str, List[str]]:
        """Post-process a successful anydoc PDF conversion.

        Two PDF-only steps:

        1. Trust check (``PDF_TRUST_CHECK``): the two classes where anydoc
           drops text *silently* — Type0 fonts without ToUnicode, and
           CJK-declaring PDFs with CJK-less output. A flagged file re-parses
           on the docling fallback when one is wired; otherwise the anydoc
           output is kept and the problems ride along as ``parse_warnings``
           metadata.
        2. ``ANYDOC_TABLEIZE`` (off by default): rewrite dot-leader /
           whitespace table runs as GFM tables. Never applied to a docling
           re-parse — docling emits real tables already.
        """
        problems = self._trust_problems(path, content)
        if problems:
            rerouted = self._reroute_flagged(path, errors, problems)
            if rerouted is not None:
                return rerouted
            self._last_warnings = (path, problems)
            logger.warning(
                f"anydoc output for {path.name} failed the PDF trust check "
                f"({'; '.join(problems)}); keeping it with parse_warnings"
            )
        if settings.ANYDOC_TABLEIZE:
            from application.parser.file.tableize import tableize

            content = tableize(content)
        return content

    def _trust_problems(self, path: Path, content: str) -> List[str]:
        """Trust-check findings for ``content``; [] when disabled, clean, or the check errors."""
        if not settings.PDF_TRUST_CHECK:
            return []
        try:
            from application.parser.file.pdf_trust import verify_pdf_file

            return verify_pdf_file(path, content)
        except Exception:
            # The check exists to catch silent loss; it must never turn a
            # successful parse into a failure.
            logger.warning(
                f"PDF trust check errored on {path.name}; trusting the output",
                exc_info=True,
            )
            return []

    def _reroute_flagged(
        self, path: Path, errors: str, problems: List[str]
    ) -> Optional[Union[str, List[str]]]:
        """Re-parse a trust-flagged PDF with a docling-backed fallback.

        Returns the fallback's output, or None when there is no docling
        fallback, it fails, or it comes back near-empty — the caller then
        keeps the anydoc output.
        Only docling is worth the re-parse: it ships Adobe's predefined
        CMaps, which is exactly what the flagged font class needs; the
        legacy pypdf parser does not.
        """
        fallback = self.fallback_parser
        if not _is_docling_backed(fallback):
            return None
        logger.warning(
            f"anydoc output for {path.name} failed the PDF trust check "
            f"({'; '.join(problems)}); re-parsing with {type(fallback).__name__}"
        )
        try:
            result = delegate_parse(fallback, path, errors)
        except DocumentParseError:
            logger.warning(
                f"docling re-parse of trust-flagged {path.name} failed; "
                "keeping the anydoc output",
                exc_info=True,
            )
            return None
        if _result_chars(result) < _MIN_SCAN_FALLBACK_CHARS:
            # A docling pipeline dropout ('' / '<!-- image -->') returns
            # without raising; adopting it would swap anydoc's real text for
            # an empty document.
            logger.warning(
                f"docling re-parse of trust-flagged {path.name} returned almost "
                "no text; keeping the anydoc output"
            )
            return None
        self.last_engine = getattr(fallback, "last_engine", None) or type(fallback).__name__
        return result

    def get_file_metadata(self, file: Path) -> Dict:
        """Surface trust-check findings for the file just parsed, if any."""
        last = self._last_warnings
        if last is not None and last[0] == Path(file):
            return {"parse_warnings": list(last[1])}
        return {}

    def _delegate(
        self, path: Path, errors: str, reason: str, ocr_needed: bool = False
    ) -> Union[str, List[str]]:
        """Hand ``path`` to the fallback parser, or fail loudly without one.

        ``ocr_needed`` marks anydoc's scanned-PDF refusal ("OCR is required").
        The fallback still runs first — docling extracts text layers anydoc
        refuses (seen on degenerate CJK text layers) even with OCR off — but
        when it comes back near-empty the parse fails loudly, telling the
        user how to get OCR, instead of silently storing an empty document
        for a scan.
        """
        fallback = self.fallback_parser
        if fallback is None:
            self.last_engine = None
            raise DocumentParseError(f"Failed to parse {path.name}: {reason}")
        logger.warning(
            f"anydoc could not convert {path.name} ({reason}); "
            f"falling back to {type(fallback).__name__}"
        )
        result = delegate_parse(fallback, path, errors)
        if ocr_needed and _result_chars(result) < _MIN_SCAN_FALLBACK_CHARS:
            self.last_engine = None
            if getattr(fallback, "ocr_enabled", False):
                hint = " even with OCR enabled."
            else:
                hint = (
                    ". Enable OCR to ingest scans: set DOCLING_OCR_ENABLED=true "
                    "(and DOCLING_OCR_ATTACHMENTS_ENABLED for attachments) with "
                    "the docling extra installed."
                )
            raise DocumentParseError(
                f"{path.name} appears to be a scanned PDF (no text layer), and "
                f"{type(fallback).__name__} extracted almost nothing{hint}"
            )
        self.last_engine = getattr(fallback, "last_engine", None) or type(fallback).__name__
        return result
