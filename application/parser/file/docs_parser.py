"""Docs parser.

Contains parsers for docx, pdf files.

"""

from pathlib import Path
from typing import Dict, List, Any, Union
from base64 import b64encode
from application.parser.file.base_parser import BaseParser
from application.core.settings import settings
from docx import Document
from docx.enum.shape import WD_INLINE_SHAPE_TYPE
import requests
import logging
import sys

logger = logging.getLogger(__name__)


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
                files = {"file": file_loaded}
                response = requests.post(doc2md_service, files=files)
                data = response.json()["markdown"]
            return data

        try:
            import PyPDF2
        except ImportError:
            raise ValueError("PyPDF2 is required to read PDF files.")
        text_list = []
        with open(file, "rb") as fp:
            # Create a PDF object
            pdf = PyPDF2.PdfReader(fp)

            # Get the number of pages in the PDF document
            num_pages = len(pdf.pages)

            # Iterate over every page
            for page in range(num_pages):
                # Extract the text from the page
                page_text = pdf.pages[page].extract_text()
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
        document = Document(file)
        docx_content = []
        text = docx2txt.process(file)
        for block in self.iter_blocks(document):
            if isinstance(block, str):  # It's plain text
                docx_content.append(block)
            elif isinstance(block, list):  # It's a table
                table_text = "\n".join([" | ".join(row) for row in block])
                print(f"Appending table: {block}", file=sys.stderr)
                docx_content.append(table_text)
            elif isinstance(block, dict):  # It's an image
                #print(f"Appending image: {block}", file=sys.stderr)
                docx_content.extend([block["content"]["filename"], block["content"]["image_base64"]])

        final_content = "\n\n".join(docx_content)
        print("Completed parsing file. Final consolidated content:", file=sys.stderr)
        print(final_content, file=sys.stderr)
        return final_content

    def iter_blocks(self, document: Document):
        print("Iterating over document blocks...", file=sys.stderr)
        if hasattr(document, "paragraphs"):
            print(
                f"Document has paragraphs: {len(document.paragraphs)}", file=sys.stderr
            )
            for para in document.paragraphs:
                if para.text.strip():
                    print(f"Found paragraph: {para.text.strip()}", file=sys.stderr)
                    yield para.text.strip()

        # check images
        if hasattr(document, "inline_shapes"):
            print(
                f"Document has inline shapes: {len(document.inline_shapes)}",
                file=sys.stderr,
            )
            for shape in document.inline_shapes:
                """
                Found inline shape: <docx.shape.InlineShape object at 0x319554a10>
                Shape type: WD_INLINE_SHAPE_TYPE.PICTURE
                """
                for attr in dir(shape):
                    print(f"Shape attribute: {attr}", file=sys.stderr)
                    print(
                        f"Shape attribute value: {getattr(shape, attr)}",
                        file=sys.stderr,
                    )
                if shape.type == WD_INLINE_SHAPE_TYPE.PICTURE:
                    print("Extracting image from inline shape...", file=sys.stderr)
                    image_data = self.extract_image_from_shape(shape, document=document)
                    if image_data:
                        print(f"Extracted image filename: {image_data['content']['filename']}", file=sys.stderr)
                        print(f"Base64 snippet: {image_data['content']['image_base64'][:20]}...", file=sys.stderr)
                        yield image_data
                    else:
                        print("No image data extracted.", file=sys.stderr)

        if hasattr(document, "tables"):
            print(f"Document has tables: {len(document.tables)}", file=sys.stderr)
            for table in document.tables:
                table_data = self.extract_table(table)
                print(f"Found table: {table_data}", file=sys.stderr)
                yield table_data

        if hasattr(document, "sections"):
            print(f"Document has sections: {len(document.sections)}", file=sys.stderr)
            for section in document.sections:
                if section.header:
                    print("Found header.", file=sys.stderr)
                    for paragraph in section.header.paragraphs:
                        if paragraph.text.strip():
                            print(
                                f"Header paragraph: {paragraph.text.strip()}",
                                file=sys.stderr,
                            )
                            yield paragraph.text.strip()
                if section.footer:
                    print("Found footer.", file=sys.stderr)
                    for paragraph in section.footer.paragraphs:
                        if paragraph.text.strip():
                            print(
                                f"Footer paragraph: {paragraph.text.strip()}",
                                file=sys.stderr,
                            )
                            yield paragraph.text.strip()

    def extract_table(self, table) -> str:
        """
        This function will return the table data in HTML format.
        for easy to read format. to LLM
        """
        print("Extracting table data with HTML semantics...", file=sys.stderr)
        table_html = ["<table>"]

        # Add table rows
        for row in table.rows:
            row_html = ["<tr>"]
            for cell in row.cells:
                tag = "th" if self.is_header_row(row) else "td"
                cell_text = cell.text.strip()
                print(f"Extracted cell: {cell_text}", file=sys.stderr)
                row_html.append(f"<{tag}>{cell_text}</{tag}>")
            row_html.append("</tr>")
            table_html.extend(row_html)

        table_html.append("</table>")
        return "\n".join(table_html)

    def is_header_row(self, row) -> bool:
        """Determine if the row is a header row (you can customize this logic)."""
        return all(cell.text.isupper() for cell in row.cells)
    
    def extract_image_from_shape(self, shape, document: Document) -> Dict:
        """Extract image from an inline shape."""
        try:
            if shape.type == WD_INLINE_SHAPE_TYPE.PICTURE:
                print(f"Processing shape: {shape}", file=sys.stderr)

                # Get the relationship ID for the image
                rId = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
                print(f"Found relationship ID: {rId}", file=sys.stderr)

                # Fetch the image data from the part relationships
                image_part = document.part.related_parts[rId]
                image_data = image_part.blob
                image_filename = image_part.filename or f"image_{rId}.png"

                # Convert the image to Base64
                import base64
                image_base64 = base64.b64encode(image_data).decode("utf-8")
                print(f"Successfully extracted image: {image_filename}", file=sys.stderr)

                return {
                    "type": "image",
                    "content": {
                        "filename": image_filename,
                        "image_base64": image_base64,
                    },
                }
        except Exception as e:
            print(f"Error extracting image: {e}", file=sys.stderr)

        return None