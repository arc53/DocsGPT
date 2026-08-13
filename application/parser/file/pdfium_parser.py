"""Direct PDF text-layer extraction with pypdfium2, for the attachment path.

Attachments are read straight into a chat prompt; sources are chunked and
embedded for retrieval. That difference is what justifies two parsers. Docling
produces structured markdown — headings, table markup, image placeholders —
which is worth its cost when the output feeds chunking, and mostly wasted when
the output is concatenated into a prompt.

The cost is not marginal. Measured on eight real uploads drawn from the p90 of
production attachment-ingest latency (docling 2.119.0, OCR off, warm process):

    docling total   155.6 s      pypdfium2 total   0.33 s      (~470x)
    token yield within +/-15% per file, three files yielding *more* text

What is lost is structure: docling emitted 20-187 headings and 44-88 table rows
per file where this parser emits none, and text arrives in content-stream order
rather than reading order. Acceptable for prompt context; not acceptable for
retrieval, which is why `get_default_file_extractor` keeps docling by default
and only swaps in this parser when a caller opts in.

A scanned PDF has no text layer, so this parser would return an empty document
for exactly the files that need docling most. It therefore probes first and
delegates to `fallback_parser` when the text layer is too thin to be real,
leaving scanned-PDF behaviour unchanged.
"""

import logging
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from application.parser.file.base_parser import BaseParser, DocumentParseError

logger = logging.getLogger(__name__)

# Pages sampled by the text-layer probe. Sampling a spread rather than the
# first N matters: scanned documents routinely carry a text cover page, and
# born-digital ones sometimes open with a full-page image.
DEFAULT_SAMPLE_PAGES = 16

# Median characters per sampled page below which the file is treated as having
# no usable text layer. Measured separation on the production corpus was stark:
# scanned files sat at 0 and 17 characters per page, text-layer files at
# 433-6834, so anything in the low hundreds separates them. 32 is deliberately
# conservative — it keeps sparse-but-real documents on docling.
DEFAULT_MIN_MEDIAN_CHARS = 32


class PdfiumTextParser(BaseParser):
    """Extract a PDF's embedded text layer with pypdfium2.

    Falls back to ``fallback_parser`` when the file has no usable text layer
    (a scan), cannot be opened, or when pypdfium2 raises. The fallback is the
    parser this one displaces, so delegating restores the previous behaviour
    exactly rather than degrading it.

    Attributes:
        fallback_parser: Parser used when the text layer is unusable.
        min_median_chars: Median chars/page required to use the fast path.
        sample_pages: Maximum number of pages inspected by the probe.
        last_engine: Name of the engine that produced the most recent parse,
            ``"pypdfium2"`` or the fallback parser's class name.
    """

    def __init__(
        self,
        fallback_parser: Optional[BaseParser] = None,
        min_median_chars: int = DEFAULT_MIN_MEDIAN_CHARS,
        sample_pages: int = DEFAULT_SAMPLE_PAGES,
        parser_config: Optional[Dict] = None,
    ) -> None:
        """Initialize the parser.

        Args:
            fallback_parser: Parser to delegate to when the text layer is
                unusable. When ``None`` such files raise ``DocumentParseError``.
            min_median_chars: Median characters per sampled page required to
                take the fast path.
            sample_pages: Maximum pages the probe inspects.
            parser_config: Optional pre-built parser config.
        """
        super().__init__(parser_config)
        self.fallback_parser = fallback_parser
        self.min_median_chars = min_median_chars
        self.sample_pages = max(1, sample_pages)
        self.last_engine: Optional[str] = None
        self._last_metadata: Dict[str, Any] = {}

    def _init_parser(self) -> Dict:
        """Initialize the parser config.

        Returns:
            Dict: Static config describing the probe thresholds.
        """
        return {
            "engine": "pypdfium2",
            "min_median_chars": self.min_median_chars,
            "sample_pages": self.sample_pages,
        }

    def _sample_indices(self, page_count: int) -> List[int]:
        """Return a spread of page indices to probe."""
        if page_count <= self.sample_pages:
            return list(range(page_count))
        step = (page_count - 1) / (self.sample_pages - 1)
        return sorted({round(i * step) for i in range(self.sample_pages)})

    def _probe_text_layer(self, file: Path) -> Dict[str, Any]:
        """Measure how much extractable text the PDF carries.

        Args:
            file: Path to the PDF.

        Returns:
            Dict: ``page_count`` and ``median_chars`` across sampled pages.

        Raises:
            Exception: Propagated from pypdfium2 when the file cannot be read.
        """
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(file))
        try:
            page_count = len(pdf)
            counts = []
            for index in self._sample_indices(page_count):
                page = pdf[index]
                textpage = page.get_textpage()
                try:
                    counts.append(textpage.count_chars())
                finally:
                    textpage.close()
                    page.close()
        finally:
            pdf.close()
        return {
            "page_count": page_count,
            "median_chars": int(statistics.median(counts)) if counts else 0,
        }

    def _extract_text(self, file: Path) -> str:
        """Extract every page's text layer.

        Args:
            file: Path to the PDF.

        Returns:
            str: Page texts joined by blank lines.
        """
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(file))
        pages: List[str] = []
        try:
            for index in range(len(pdf)):
                page = pdf[index]
                textpage = page.get_textpage()
                try:
                    pages.append(textpage.get_text_range())
                finally:
                    textpage.close()
                    page.close()
        finally:
            pdf.close()
        return "\n\n".join(pages)

    def _delegate(self, file: Path, errors: str, reason: str) -> Union[str, List[str]]:
        """Hand the file to the fallback parser.

        Args:
            file: Path to the PDF.
            errors: Decoding leniency passed through to the fallback.
            reason: Why the fast path was skipped, for the log line.

        Returns:
            The fallback parser's output.

        Raises:
            DocumentParseError: When no fallback parser is configured.
        """
        if self.fallback_parser is None:
            raise DocumentParseError(
                f"{file.name} has no usable PDF text layer ({reason}) and no "
                "fallback parser is configured."
            )
        logger.info(
            "PDF text-layer fast path skipped for %s (%s); using %s",
            file.name,
            reason,
            type(self.fallback_parser).__name__,
        )
        if not self.fallback_parser.parser_config_set:
            self.fallback_parser.init_parser()
        self.last_engine = type(self.fallback_parser).__name__
        result = self.fallback_parser.parse_file(file, errors=errors)
        self._last_metadata = {
            **self.fallback_parser.get_file_metadata(file),
            "parse_engine": self.last_engine,
        }
        return result

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse a PDF, preferring its embedded text layer.

        Args:
            file: Path to the PDF.
            errors: Decoding leniency, passed through to the fallback parser.

        Returns:
            The extracted text, or the fallback parser's output.

        Raises:
            DocumentParseError: When the text layer is unusable and no fallback
                parser is configured.
        """
        file = Path(file)
        try:
            probe = self._probe_text_layer(file)
        except Exception as exc:  # noqa: BLE001 - any read failure defers to docling
            return self._delegate(file, errors, f"unreadable by pypdfium2: {exc}")

        if probe["page_count"] == 0:
            return self._delegate(file, errors, "no pages")
        if probe["median_chars"] < self.min_median_chars:
            return self._delegate(
                file,
                errors,
                f"median {probe['median_chars']} chars/page below "
                f"{self.min_median_chars}",
            )

        try:
            text = self._extract_text(file)
        except Exception as exc:  # noqa: BLE001 - as above
            return self._delegate(file, errors, f"extraction failed: {exc}")

        self.last_engine = "pypdfium2"
        self._last_metadata = {
            "parse_engine": "pypdfium2",
            "pdf_pages": probe["page_count"],
        }
        logger.info(
            "Parsed %s via pypdfium2 text layer: %d pages, %d chars",
            file.name,
            probe["page_count"],
            len(text),
        )
        return text

    def get_file_metadata(self, file: Path) -> Dict:
        """Return metadata for the most recently parsed file.

        Args:
            file: Path to the PDF (unused; state is per-parse).

        Returns:
            Dict: Includes ``parse_engine`` so a stored attachment records
            which parser actually produced its content.
        """
        _ = file
        return dict(self._last_metadata)
