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


class DoclingParser(BaseParser):
    """Parser using docling for advanced document processing.

    Docling provides:
    - Advanced PDF layout analysis
    - Table structure recognition
    - Reading order detection
    - OCR for scanned documents (supports RapidOCR)
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
        use_rapidocr: bool = True,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = False,
    ):
        """Initialize DoclingParser.

        Args:
            ocr_enabled: Enable OCR for bitmap/image regions in documents
            table_structure: Enable table structure recognition
            export_format: Output format ('markdown', 'text', 'html')
            use_rapidocr: Use RapidOCR engine (default True, works well in Docker)
            ocr_languages: List of OCR languages (default: ['english'])
            force_full_page_ocr: Force OCR on entire page (False = smart hybrid OCR)
        """
        super().__init__()
        self.ocr_enabled = ocr_enabled
        self.table_structure = table_structure
        self.export_format = export_format
        self.use_rapidocr = use_rapidocr
        self.ocr_languages = ocr_languages or ["english"]
        self.force_full_page_ocr = force_full_page_ocr
        self._converter = None

    def _create_converter(self):
        """Create a docling converter with hybrid OCR configuration.

        Uses smart OCR approach:
        - When ocr_enabled=True and force_full_page_ocr=False (default):
          Layout model detects text vs bitmap regions, OCR only runs on bitmaps
        - When ocr_enabled=True and force_full_page_ocr=True:
          OCR runs on entire page (for scanned documents/images)
        - When ocr_enabled=False:
          No OCR, only native text extraction

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

        pipeline_options = PdfPipelineOptions(
            do_ocr=self.ocr_enabled,
            do_table_structure=self.table_structure,
        )

        if self.ocr_enabled:
            ocr_options = self._get_ocr_options()
            if ocr_options is not None:
                pipeline_options.ocr_options = ocr_options

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

    def _init_parser(self) -> Dict:
        """Initialize the docling converter with hybrid OCR."""
        logger.info("Initializing DoclingParser...")
        logger.info(f"  ocr_enabled={self.ocr_enabled}")
        logger.info(f"  force_full_page_ocr={self.force_full_page_ocr}")
        logger.info(f"  use_rapidocr={self.use_rapidocr}")

        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
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
            "use_rapidocr": self.use_rapidocr,
            "ocr_languages": self.ocr_languages,
            "force_full_page_ocr": self.force_full_page_ocr,
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
                return "\n\n".join(extracted_texts)

        return content

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file using docling with hybrid OCR.

        Uses smart OCR approach where the layout model detects text vs bitmap
        regions. Text is extracted directly, bitmaps are OCR'd only when needed.

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
            logger.info(f"Converting file with hybrid OCR: {file}")
            result = self._converter.convert(str(file))
            content = self._export_content(result.document)
            logger.info(f"Parse complete, content length: {len(content)} chars")

            return content

        except Exception as e:
            logger.error(f"Error parsing file with docling: {e}", exc_info=True)
            if errors == "ignore":
                return f"[Error parsing file with docling: {str(e)}]"
            raise


class DoclingPDFParser(DoclingParser):
    """Docling-based PDF parser with advanced features and RapidOCR support.

    Uses hybrid OCR approach by default:
    - Text regions: Direct PDF text extraction (fast)
    - Bitmap/image regions: OCR only these areas (smart)

    Set force_full_page_ocr=True only for fully scanned documents.
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure: bool = True,
        use_rapidocr: bool = True,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = False,
    ):
        super().__init__(
            ocr_enabled=ocr_enabled,
            table_structure=table_structure,
            export_format="markdown",
            use_rapidocr=use_rapidocr,
            ocr_languages=ocr_languages,
            force_full_page_ocr=force_full_page_ocr,
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

    For images, force_full_page_ocr=True is used since images are entirely
    visual and require full OCR to extract any text.
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        use_rapidocr: bool = True,
        ocr_languages: Optional[List[str]] = None,
        force_full_page_ocr: bool = True,
    ):
        super().__init__(
            ocr_enabled=ocr_enabled,
            export_format="markdown",
            use_rapidocr=use_rapidocr,
            ocr_languages=ocr_languages,
            force_full_page_ocr=force_full_page_ocr,
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
