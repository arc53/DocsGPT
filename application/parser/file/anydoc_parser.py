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

from application.parser.file.base_parser import (
    BaseParser,
    DocumentParseError,
    delegate_parse,
    module_available,
)

logger = logging.getLogger(__name__)

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


def anydoc_available() -> bool:
    """Whether the ``anydoc`` extension can be imported."""
    return module_available("anydoc")


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
            return self._delegate(path, errors, f"{type(exc).__name__}: {exc}")
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
        return content

    def _delegate(self, path: Path, errors: str, reason: str) -> Union[str, List[str]]:
        """Hand ``path`` to the fallback parser, or fail loudly without one."""
        fallback = self.fallback_parser
        if fallback is None:
            self.last_engine = None
            raise DocumentParseError(f"Failed to parse {path.name}: {reason}")
        logger.warning(
            f"anydoc could not convert {path.name} ({reason}); "
            f"falling back to {type(fallback).__name__}"
        )
        result = delegate_parse(fallback, path, errors)
        self.last_engine = getattr(fallback, "last_engine", None) or type(fallback).__name__
        return result
