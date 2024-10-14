"""Docs parser.

Contains parsers for docx and pdf files with OCR support.
"""
from pathlib import Path
from typing import Dict, Optional
import logging
import pytesseract
from pdf2image import convert_from_path

from application.parser.file.base_parser import BaseParser

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PDFParser(BaseParser):
    """PDF parser with OCR support."""

    def _init_parser(self) -> Dict:
        """Initialize parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Optional[str]:
        """Parse a PDF file and extract text, using OCR if necessary.

        Args:
            file (Path): The path to the PDF file.
            errors (str): Error handling strategy (default is "ignore").

        Returns:
            Optional[str]: The extracted text from the PDF file, or None if the file is empty.
        """
        try:
            import PyPDF2
        except ImportError:
            logger.error("PyPDF2 is required to read PDF files.")
            raise ValueError("PyPDF2 is required to read PDF files.")

        text_list = []
        with open(file, "rb") as fp:
            # Create a PDF object
            pdf = PyPDF2.PdfReader(fp)

            # Get the number of pages in the PDF document
            num_pages = len(pdf.pages)

            if num_pages == 0:
                logger.warning("The PDF file is empty.")
                return None
            
            # Iterate over every page
            for page in range(num_pages):
                # Extract the text from the page
                page_text = pdf.pages[page].extract_text()
                if page_text:
                    text_list.append(page_text)
                else:
                    logger.warning(f"No text found on page {page + 1}, attempting OCR.")
                    # If no text found, convert the page to an image and apply OCR
                    images = convert_from_path(file, first_page=page + 1, last_page=page + 1)
                    for image in images:
                        ocr_text = pytesseract.image_to_string(image)
                        if ocr_text:
                            text_list.append(ocr_text)
                            logger.info(f"OCR text extracted from page {page + 1}.")
                        else:
                            logger.warning(f"No text found using OCR on page {page + 1}.")
        
        text = "\n".join(text_list)

        return text if text else None


class DocxParser(BaseParser):
    """Docx parser with OCR support (if necessary)."""

    def _init_parser(self) -> Dict:
        """Initialize parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Optional[str]:
        """Parse a DOCX file and extract text.

        Args:
            file (Path): The path to the DOCX file.
            errors (str): Error handling strategy (default is "ignore").

        Returns:
            Optional[str]: The extracted text from the DOCX file, or None if the file is empty.
        """
        try:
            import docx2txt
        except ImportError:
            logger.error("docx2txt is required to read Microsoft Word files.")
            raise ValueError("docx2txt is required to read Microsoft Word files.")

        text = docx2txt.process(file)

        if not text:
            logger.warning("The DOCX file is empty or could not be parsed.")
            return None
        
        return text
