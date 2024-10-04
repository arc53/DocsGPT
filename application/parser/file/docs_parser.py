"""
Docs parser.

Contains parsers for docx, pdf files with optional OCR support for PDFs.

"""
from pathlib import Path
from typing import Dict

from application.parser.file.base_parser import BaseParser


class PDFParser(BaseParser):
    """PDF parser with optional OCR support."""

    def __init__(self, use_ocr: bool = False, ocr_threshold: int = 10):
        """
        Initializes the PDF parser.

        :param use_ocr: Flag to enable OCR for pages that don't have enough extractable text.
        :param ocr_threshold: The minimum length of text to attempt OCR.
        """
        self.use_ocr = use_ocr
        self.ocr_threshold = ocr_threshold

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> str:
        """Parse file."""
        try:
            import PyPDF2
            import pytesseract
            from pdf2image import convert_from_path
            from PIL import Image
        except ImportError as e:
            raise ValueError("Required libraries for PDF parsing and OCR are missing: {}".format(e))

        text_list = []
        with open(file, "rb") as fp:
            # Create a PDF object
            pdf = PyPDF2.PdfReader(fp)
            num_pages = len(pdf.pages)

            for page_num in range(num_pages):
                page = pdf.pages[page_num]
                page_text = page.extract_text()

                # Check if OCR is needed
                if self.use_ocr and (page_text is None or len(page_text.strip()) < self.ocr_threshold):
                    page_text = self._extract_text_with_ocr(file, page_num)

                text_list.append(page_text or "")

        return "\n".join(text_list)

    def _extract_text_with_ocr(self, file: Path, page_num: int) -> str:
        """
        Extracts text from a PDF page using OCR.

        :param file: The PDF file path.
        :param page_num: Page number in the PDF to process.
        :return: Extracted text using OCR.
        """
        # Convert specific page to an image
        pages = convert_from_path(file, first_page=page_num + 1, last_page=page_num + 1)
        if pages:
            img = pages[0]
            # Perform OCR on the image
            ocr_text = pytesseract.image_to_string(img)
            return ocr_text.strip()
        return ""
        

class DocxParser(BaseParser):
    """Docx parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> str:
        """Parse file."""
        try:
            import docx2txt
        except ImportError:
            raise ValueError("docx2txt is required to read Microsoft Word files.")

        text = docx2txt.process(file)
        return text
