"""Image parser.

Contains parser for .png, .jpg, .jpeg files.

"""
from pathlib import Path
import requests
from typing import Dict, Union
import traceback

from application.parser.file.base_parser import BaseParser


class ImageParser(BaseParser):
    """Image parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        doc2md_service = "https://llm.arc53.com/doc2md"
        # alternatively you can use local vision capable LLM
        with open(file, "rb") as file_loaded:
            files = {'file': file_loaded}
            response = requests.post(doc2md_service, files=files)   
            data = response.json()["markdown"] 
        return data
