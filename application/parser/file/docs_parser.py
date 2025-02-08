"""Docs parser.

Contains parsers for docx, pdf files.

"""
from pathlib import Path
from typing import Dict

from application.parser.file.base_parser import BaseParser
from application.core.settings import settings
import requests

class PDFParser(BaseParser):
    """PDF parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> str:
        """Parse file."""
        if settings.PARSE_PDF_AS_IMAGE:
            doc2md_service = "https://llm.arc53.com/doc2md"
            # alternatively you can use local vision capable LLM
            with open(file, "rb") as file_loaded:
                files = {'file': file_loaded}
                response = requests.post(doc2md_service, files=files)
                data = response.json()["markdown"]
            return data

        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("pypdf is required to read PDF files.")
        text_list = []
        with open(file, "rb") as fp:
            # Create a PDF object
            pdf = PdfReader(fp)

            # Get the number of pages in the PDF document
            num_pages = len(pdf.pages)

            # Iterate over every page
            for page_index in range(num_pages):
                # Extract the text from the page
                page = pdf.pages[page_index]
                page_text = page.extract_text()
                text_list.append(page_text)
        text = "\n".join(text_list)

        return text


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