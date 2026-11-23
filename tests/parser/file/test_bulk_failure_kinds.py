"""Which unreadable files a reader reports as worth trying again (``transient_failures``)."""

from pathlib import Path

import pytest

from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError, TransientParseError
from docsgpt.parser.file.bulk import SimpleDirectoryReader
from docsgpt.parser.file.ocr_parser import OcrUnavailableError


class _Raising(BaseParser):
    def __init__(self, errors):
        super().__init__()
        self.errors = errors

    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        error = self.errors.get(Path(file).name)
        if error:
            raise error
        return "text"


@pytest.mark.unit
def test_transient_and_unavailable_ocr_failures_are_worth_retrying(tmp_path):
    for name in ("ok.pdf", "busy.pdf", "nokey.pdf", "corrupt.pdf"):
        (tmp_path / name).write_bytes(b"%PDF")
    parser = _Raising({
        "busy.pdf": TransientParseError("503"),
        "nokey.pdf": OcrUnavailableError("401: check OCR_DEEPSEEK_API_KEY"),
        "corrupt.pdf": DocumentParseError("not a PDF"),
    })
    reader = SimpleDirectoryReader(input_dir=str(tmp_path), file_extractor={".pdf": parser})
    reader.load_data()
    assert sorted(p.name for p, _ in reader.failed_files) == ["busy.pdf", "corrupt.pdf", "nokey.pdf"]
    assert sorted(p.name for p in reader.transient_failures) == ["busy.pdf", "nokey.pdf"]
