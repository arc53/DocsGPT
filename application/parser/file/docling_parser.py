"""Docling parser.

Uses docling library for advanced document parsing with layout detection,
table structure recognition, and unified document representation.

Supports: PDF, DOCX, PPTX, XLSX, HTML, XHTML, CSV, Markdown, AsciiDoc,
images (PNG, JPEG, TIFF, BMP, WEBP), WebVTT, and specialized XML formats.
"""
from pathlib import Path
from typing import Dict, List, Union

from application.parser.file.base_parser import BaseParser


class DoclingParser(BaseParser):
    """Parser using docling for advanced document processing.

    Docling provides:
    - Advanced PDF layout analysis
    - Table structure recognition
    - Reading order detection
    - OCR for scanned documents
    - Unified DoclingDocument format
    - Export to Markdown
    """

    def __init__(
        self,
        ocr_enabled: bool = True,
        table_structure: bool = True,
        export_format: str = "markdown",
    ):
        """Initialize DoclingParser.

        Args:
            ocr_enabled: Enable OCR for scanned documents/images
            table_structure: Enable table structure recognition
            export_format: Output format ('markdown', 'text', 'html')
        """
        super().__init__()
        self.ocr_enabled = ocr_enabled
        self.table_structure = table_structure
        self.export_format = export_format
        self._converter = None

    def _init_parser(self) -> Dict:
        """Initialize the docling converter."""
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            raise ImportError(
                "docling is required for DoclingParser. "
                "Install it with: pip install docling"
            )

        self._converter = DocumentConverter()

        return {
            "ocr_enabled": self.ocr_enabled,
            "table_structure": self.table_structure,
            "export_format": self.export_format,
        }

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file using docling.

        Args:
            file: Path to the file to parse
            errors: Error handling mode (ignored, docling handles internally)

        Returns:
            Parsed document content as markdown string
        """
        if self._converter is None:
            self._init_parser()

        try:
            result = self._converter.convert(str(file))
            document = result.document

            if self.export_format == "markdown":
                return document.export_to_markdown()
            elif self.export_format == "html":
                return document.export_to_html()
            else:
                return document.export_to_text()

        except Exception as e:
            if errors == "ignore":
                return f"[Error parsing file with docling: {str(e)}]"
            raise


class DoclingPDFParser(DoclingParser):
    """Docling-based PDF parser with advanced features."""

    def __init__(self, ocr_enabled: bool = True, table_structure: bool = True):
        super().__init__(
            ocr_enabled=ocr_enabled,
            table_structure=table_structure,
            export_format="markdown"
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
    """Docling-based image parser with OCR."""

    def __init__(self):
        super().__init__(ocr_enabled=True, export_format="markdown")


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
