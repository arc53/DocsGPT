"""Docling parser.

Uses docling library for advanced document parsing with layout detection,
table structure recognition, and unified document representation.

Supports: PDF, DOCX, PPTX, XLSX, HTML, XHTML, CSV, Markdown, AsciiDoc,
images (PNG, JPEG, TIFF, BMP, WEBP), WebVTT, and specialized XML formats.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from application.parser.file.base_parser import BaseParser

logger = logging.getLogger(__name__)

# Minimum content length to consider a PDF as having extractable text
MIN_CONTENT_LENGTH = 100


class DoclingParser(BaseParser):
    """Parser using docling for advanced document processing.

    Docling provides:
    - Advanced PDF layout analysis
    - Table structure recognition
    - Reading order detection
    - OCR for scanned documents (supports RapidOCR)
    - Unified DoclingDocument format
    - Export to Markdown
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure: bool = True,
        export_format: str = "markdown",
        use_rapidocr: bool = True,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = False,
        ocr_on_empty_only: bool = True,
    ):
        """Initialize DoclingParser.

        Args:
            ocr_enabled: Enable OCR for scanned documents/images
            table_structure: Enable table structure recognition
            export_format: Output format ('markdown', 'text', 'html')
            use_rapidocr: Use RapidOCR engine (default True, works well in Docker)
            ocr_languages: List of OCR languages (default: ['english'])
            force_full_page_ocr: Force OCR on entire page regardless of content
            ocr_on_empty_only: Only use OCR if initial parsing returns empty/minimal content
        """
        super().__init__()
        self.ocr_enabled = ocr_enabled
        self.table_structure = table_structure
        self.export_format = export_format
        self.use_rapidocr = use_rapidocr
        self.ocr_languages = ocr_languages or ["english"]
        self.force_full_page_ocr = force_full_page_ocr
        self.ocr_on_empty_only = ocr_on_empty_only
        self._converter = None
        self._converter_with_ocr = None

    def _create_converter(self, with_ocr: bool = False):
        """Create a docling converter with specified OCR setting.

        Args:
            with_ocr: Whether to enable OCR in the converter

        Returns:
            DocumentConverter instance
        """
        from docling.document_converter import (
            DocumentConverter,
            InputFormat,
            PdfFormatOption,
        )
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        pipeline_options = PdfPipelineOptions(
            do_ocr=with_ocr,
            do_table_structure=self.table_structure,
        )

        if with_ocr:
            ocr_options = self._get_ocr_options()
            if ocr_options is not None:
                pipeline_options.ocr_options = ocr_options

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                ),
            }
        )

    def _init_parser(self) -> Dict:
        """Initialize the docling converters."""
        logger.info("Initializing DoclingParser...")
        logger.info(f"  ocr_enabled={self.ocr_enabled}")
        logger.info(f"  ocr_on_empty_only={self.ocr_on_empty_only}")
        logger.info(f"  use_rapidocr={self.use_rapidocr}")

        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            raise ImportError(
                "docling is required for DoclingParser. "
                "Install it with: pip install docling"
            )

        # Create converter without OCR (for initial fast parsing)
        if self.ocr_on_empty_only:
            logger.info("Creating converter without OCR for initial parsing")
            self._converter = self._create_converter(with_ocr=False)
            # Create OCR converter lazily when needed
            self._converter_with_ocr = None
        else:
            # OCR always on or always off
            logger.info(f"Creating converter with ocr_enabled={self.ocr_enabled}")
            self._converter = self._create_converter(with_ocr=self.ocr_enabled)

        logger.info("DoclingParser initialized successfully")
        return {
            "ocr_enabled": self.ocr_enabled,
            "table_structure": self.table_structure,
            "export_format": self.export_format,
            "use_rapidocr": self.use_rapidocr,
            "ocr_languages": self.ocr_languages,
            "ocr_on_empty_only": self.ocr_on_empty_only,
        }

    def _get_ocr_options(self):
        """Get OCR options based on configuration.

        Returns RapidOcrOptions if use_rapidocr is True and available,
        otherwise returns None to use docling defaults.
        """
        if not self.use_rapidocr:
            return None

        try:
            from docling.datamodel.pipeline_options import RapidOcrOptions

            return RapidOcrOptions(
                lang=self.ocr_languages,
                force_full_page_ocr=self.force_full_page_ocr,
            )
        except ImportError as e:
            logger.warning(f"Failed to import RapidOcrOptions: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating RapidOcrOptions: {e}")
            return None

    def _export_content(self, document) -> str:
        """Export document content in the configured format."""
        if self.export_format == "markdown":
            return document.export_to_markdown()
        elif self.export_format == "html":
            return document.export_to_html()
        else:
            return document.export_to_text()

    def _is_content_empty(self, content: str) -> bool:
        """Check if extracted content is empty or too short.

        Args:
            content: The extracted text content

        Returns:
            True if content is considered empty/insufficient
        """
        if not content:
            return True
        # Strip whitespace and check length
        stripped = content.strip()
        return len(stripped) < MIN_CONTENT_LENGTH

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file using docling.

        First attempts parsing without OCR for speed. If content is empty/minimal
        and ocr_on_empty_only is True, retries with OCR enabled.

        Args:
            file: Path to the file to parse
            errors: Error handling mode (ignored, docling handles internally)

        Returns:
            Parsed document content as markdown string
        """
        logger.info(f"parse_file called for: {file}")

        if self._converter is None:
            self._init_parser()

        try:
            # First pass: try without OCR (fast)
            logger.info(f"Converting file (without OCR): {file}")
            result = self._converter.convert(str(file))
            content = self._export_content(result.document)
            logger.info(f"Initial parse complete, content length: {len(content)} chars")

            # Check if we need OCR
            if self.ocr_on_empty_only and self.ocr_enabled and self._is_content_empty(content):
                logger.info(f"Content is empty/minimal ({len(content.strip())} chars), retrying with OCR...")

                # Create OCR converter lazily
                if self._converter_with_ocr is None:
                    logger.info("Creating converter with OCR enabled")
                    self._converter_with_ocr = self._create_converter(with_ocr=True)

                # Retry with OCR
                result = self._converter_with_ocr.convert(str(file))
                content = self._export_content(result.document)
                logger.info(f"OCR parse complete, content length: {len(content)} chars")

            return content

        except Exception as e:
            logger.error(f"Error parsing file with docling: {e}", exc_info=True)
            if errors == "ignore":
                return f"[Error parsing file with docling: {str(e)}]"
            raise


class DoclingPDFParser(DoclingParser):
    """Docling-based PDF parser with advanced features and RapidOCR support.

    By default, parses PDFs without OCR first for speed. If the content is
    empty or minimal, automatically retries with OCR enabled.
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure: bool = True,
        use_rapidocr: bool = True,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = False,
        ocr_on_empty_only: bool = True,
    ):
        super().__init__(
            ocr_enabled=ocr_enabled,
            table_structure=table_structure,
            export_format="markdown",
            use_rapidocr=use_rapidocr,
            ocr_languages=ocr_languages,
            force_full_page_ocr=force_full_page_ocr,
            ocr_on_empty_only=ocr_on_empty_only,
        )


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


class DoclingHTMLParser(DoclingParser):
    """Docling-based HTML parser."""

    def __init__(self):
        super().__init__(export_format="markdown")


class DoclingImageParser(DoclingParser):
    """Docling-based image parser with OCR and RapidOCR support.

    For images, OCR is always enabled immediately (not lazy) since images
    typically require OCR to extract any text.
    """

    def __init__(
        self,
        use_rapidocr: bool = True,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = True,
    ):
        super().__init__(
            ocr_enabled=True,
            export_format="markdown",
            use_rapidocr=use_rapidocr,
            ocr_languages=ocr_languages,
            force_full_page_ocr=force_full_page_ocr,
            ocr_on_empty_only=False,  # Always use OCR for images
        )


class DoclingCSVParser(DoclingParser):
    """Docling-based CSV parser."""

    def __init__(self):
        super().__init__(table_structure=True, export_format="markdown")


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


class DoclingXMLParser(DoclingParser):
    """Docling-based XML parser (USPTO, JATS)."""

    def __init__(self):
        super().__init__(export_format="markdown")
