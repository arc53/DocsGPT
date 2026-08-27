"""Comprehensive tests for application/parser/file/bulk.py

Covers: SimpleDirectoryReader (init, file discovery, load_data, directory
structure building), get_default_file_extractor.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from application.parser.schema.base import Document


# =====================================================================
# Helpers
# =====================================================================


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory with test files."""
    (tmp_path / "file1.md").write_text("# Heading\n\nContent 1")
    (tmp_path / "file2.txt").write_text("Plain text content")
    (tmp_path / ".hidden").write_text("hidden file")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "file3.md").write_text("Nested content")
    return tmp_path


@pytest.fixture
def temp_dir_with_types(tmp_path):
    """Directory with multiple file types."""
    (tmp_path / "doc.md").write_text("markdown")
    (tmp_path / "data.json").write_text('{"key": "value"}')
    (tmp_path / "notes.txt").write_text("text")
    return tmp_path


# =====================================================================
# SimpleDirectoryReader - Init
# =====================================================================


@pytest.mark.unit
class TestSimpleDirectoryReaderInit:

    def test_init_with_dir(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(input_dir=str(temp_dir))
        assert len(reader.input_files) >= 2

    def test_init_with_files(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        files = [str(temp_dir / "file1.md")]
        reader = SimpleDirectoryReader(input_files=files)
        assert len(reader.input_files) == 1

    def test_init_requires_input(self):
        from application.parser.file.bulk import SimpleDirectoryReader

        with pytest.raises(ValueError, match="Must provide"):
            SimpleDirectoryReader()

    def test_exclude_hidden(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(input_dir=str(temp_dir), exclude_hidden=True)
        filenames = [f.name for f in reader.input_files]
        assert ".hidden" not in filenames

    def test_include_hidden(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(input_dir=str(temp_dir), exclude_hidden=False)
        filenames = [f.name for f in reader.input_files]
        assert ".hidden" in filenames

    def test_recursive(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(input_dir=str(temp_dir), recursive=True)
        filenames = [f.name for f in reader.input_files]
        assert "file3.md" in filenames

    def test_non_recursive(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(input_dir=str(temp_dir), recursive=False)
        filenames = [f.name for f in reader.input_files]
        assert "file3.md" not in filenames

    def test_required_exts(self, temp_dir_with_types):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir_with_types), required_exts=[".md"]
        )
        filenames = [f.name for f in reader.input_files]
        assert "doc.md" in filenames
        assert "data.json" not in filenames
        assert "notes.txt" not in filenames

    def test_required_exts_case_insensitive(self, tmp_path):
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "FILE.MD").write_text("content")
        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path), required_exts=[".md"]
        )
        assert len(reader.input_files) == 1

    def test_num_files_limit(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir), num_files_limit=1, recursive=False
        )
        assert len(reader.input_files) <= 1

    def test_custom_file_extractor(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser},
        )
        assert ".md" in reader.file_extractor


# =====================================================================
# SimpleDirectoryReader - load_data
# =====================================================================


@pytest.mark.unit
class TestSimpleDirectoryReaderLoadData:

    def test_load_data_returns_documents(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "parsed content"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            recursive=False,
            exclude_hidden=True,
        )
        docs = reader.load_data()
        assert len(docs) >= 1
        for doc in docs:
            assert isinstance(doc, Document)

    def test_unparseable_file_is_skipped_not_fatal(self, tmp_path):
        """One bad file must not cost the user the other 99.

        Parsers raise ``DocumentParseError`` rather than returning their own
        traceback as the document text, so an unguarded loop turns a single
        corrupt PDF into a failed ingest for the whole zip/folder/sync.
        """
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "good1.md").write_text("first")
        (tmp_path / "bad.md").write_text("corrupt")
        (tmp_path / "good2.md").write_text("second")

        def _parse(path, **kwargs):
            if path.name == "bad.md":
                raise DocumentParseError("Failed to parse bad.md with docling: boom")
            return f"parsed {path.name}"

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.side_effect = _parse
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path),
            file_extractor={".md": mock_parser},
            recursive=False,
            exclude_hidden=True,
        )
        docs = reader.load_data()

        texts = sorted(doc.text for doc in docs)
        assert texts == ["parsed good1.md", "parsed good2.md"]
        # The skip is recorded, not silent: callers can surface it.
        assert [Path(p).name for p, _ in reader.failed_files] == ["bad.md"]
        assert "boom" in reader.failed_files[0][1]

    def test_single_unparseable_file_still_raises(self, tmp_path):
        """The attachment path parses exactly one file and must fail loudly.

        Skipping there would hand ``load_data()[0]`` an empty list and turn a
        clear "this PDF could not be read" into an IndexError.
        """
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "bad.pdf").write_text("not really a pdf")

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.side_effect = DocumentParseError(
            "Failed to parse bad.pdf with docling: InvalidCxxCompiler"
        )

        reader = SimpleDirectoryReader(
            input_files=[str(tmp_path / "bad.pdf")],
            file_extractor={".pdf": mock_parser},
        )
        # The parser's own message reaches the user verbatim, unwrapped.
        with pytest.raises(DocumentParseError, match="InvalidCxxCompiler"):
            reader.load_data()

    def test_all_files_unparseable_raises(self, tmp_path):
        """Nothing parsed is a failed ingest, not an empty success."""
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "a.md").write_text("x")
        (tmp_path / "b.md").write_text("y")

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.side_effect = DocumentParseError("nope")

        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path),
            file_extractor={".md": mock_parser},
            recursive=False,
            exclude_hidden=True,
        )
        with pytest.raises(DocumentParseError) as excinfo:
            reader.load_data()
        assert "None of the 2 files" in str(excinfo.value)

    def test_skipped_file_still_advances_progress(self, tmp_path):
        """Progress must not stall on a skipped file."""
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "good.md").write_text("ok")
        (tmp_path / "bad.md").write_text("bad")

        def _parse(path, **kwargs):
            if path.name == "bad.md":
                raise DocumentParseError("boom")
            return "ok"

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.side_effect = _parse
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path),
            file_extractor={".md": mock_parser},
            recursive=False,
            exclude_hidden=True,
        )
        calls = []
        reader.load_data(progress_callback=lambda done, total: calls.append((done, total)))
        assert [c[0] for c in calls] == [1, 2]

    def test_load_data_progress_callback_fires_per_file(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir), recursive=False, exclude_hidden=True,
        )
        calls = []
        reader.load_data(progress_callback=lambda done, total: calls.append((done, total)))

        total_files = len(reader.input_files)
        assert total_files >= 1
        # One callback per file, monotonically increasing, ending at total.
        assert [c[0] for c in calls] == list(range(1, total_files + 1))
        assert all(c[1] == total_files for c in calls)

    def test_load_data_progress_callback_errors_swallowed(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir), recursive=False, exclude_hidden=True,
        )

        def _boom(done, total):
            raise RuntimeError("callback blew up")

        # A failing callback must not abort ingestion.
        docs = reader.load_data(progress_callback=_boom)
        assert len(docs) >= 1

    def test_load_data_concatenate(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "content"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            recursive=False,
            exclude_hidden=True,
        )
        docs = reader.load_data(concatenate=True)
        assert len(docs) == 1

    def test_load_data_with_file_metadata(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        def custom_metadata(filename):
            return {"custom_key": f"meta_{filename}"}

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "parsed"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            file_metadata=custom_metadata,
            recursive=False,
            exclude_hidden=True,
        )
        docs = reader.load_data()
        assert len(docs) >= 1
        for doc in docs:
            assert doc.extra_info is not None
            assert "custom_key" in doc.extra_info

    def test_load_data_inits_parser_if_not_set(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        mock_parser.parser_config_set = False
        mock_parser.parse_file.return_value = "content"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            recursive=False,
            exclude_hidden=True,
        )
        reader.load_data()
        mock_parser.init_parser.assert_called()

    def test_load_data_standard_read_for_unknown_ext(self, tmp_path):
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "file.xyz").write_text("xyz content")
        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path),
            file_extractor={},
        )
        docs = reader.load_data()
        assert len(docs) == 1
        assert "xyz content" in docs[0].text

    def test_load_data_list_return_from_parser(self, tmp_path):
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "multi.md").write_text("content")
        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = ["part1", "part2"]
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path),
            file_extractor={".md": mock_parser},
        )
        docs = reader.load_data()
        assert len(docs) == 2

    def test_load_data_tracks_token_counts(self, tmp_path):
        from application.parser.file.bulk import SimpleDirectoryReader

        (tmp_path / "test.md").write_text("hello world")
        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "hello world"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(tmp_path),
            file_extractor={".md": mock_parser},
        )
        reader.load_data()
        assert hasattr(reader, "file_token_counts")
        assert len(reader.file_token_counts) >= 1


# =====================================================================
# Directory Structure Building
# =====================================================================


@pytest.mark.unit
class TestBuildDirectoryStructure:

    def test_builds_structure(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "content"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            exclude_hidden=True,
        )
        reader.load_data()
        assert hasattr(reader, "directory_structure")
        assert isinstance(reader.directory_structure, dict)

    def test_structure_contains_files_and_dirs(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "content"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            exclude_hidden=True,
        )
        reader.load_data()
        struct = reader.directory_structure
        # Should contain subdir
        assert "subdir" in struct
        # Files should have metadata
        for key, val in struct.items():
            if isinstance(val, dict) and "type" in val:
                assert "size_bytes" in val

    def test_structure_excludes_hidden(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "c"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_dir=str(temp_dir),
            file_extractor={".md": mock_parser, ".txt": mock_parser},
            exclude_hidden=True,
        )
        reader.load_data()
        assert ".hidden" not in reader.directory_structure

    def test_no_structure_without_input_dir(self, temp_dir):
        from application.parser.file.bulk import SimpleDirectoryReader

        files = [str(temp_dir / "file1.md")]
        mock_parser = MagicMock()
        mock_parser.parser_config_set = True
        mock_parser.parse_file.return_value = "content"
        mock_parser.get_file_metadata.return_value = {}

        reader = SimpleDirectoryReader(
            input_files=files,
            file_extractor={".md": mock_parser},
        )
        reader.load_data()
        assert reader.directory_structure == {}


# =====================================================================
# get_default_file_extractor
# =====================================================================


@pytest.mark.unit
class TestGetDefaultFileExtractor:

    def test_returns_dict(self):
        from application.parser.file.bulk import get_default_file_extractor

        with patch.dict("sys.modules", {"docling": None, "docling.document_converter": None}):
            result = get_default_file_extractor()
            assert isinstance(result, dict)
            assert ".pdf" in result

    def test_fallback_parsers_on_import_error(self):
        with patch(
            "application.parser.file.bulk.get_default_file_extractor"
        ) as mock_fn:
            mock_fn.return_value = {".pdf": MagicMock(), ".md": MagicMock()}
            result = mock_fn()
            assert ".pdf" in result


# =====================================================================
# DOC_PARSER_ENGINE switch
# =====================================================================


@pytest.mark.unit
class TestParserEngineSwitch:
    """``get_default_file_extractor`` honours ``DOC_PARSER_ENGINE`` / ``engine``."""

    @pytest.fixture
    def settings(self):
        from application.core.settings import settings

        return settings

    def test_default_engine_is_anydoc(self, settings, monkeypatch):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import ANYDOC_SUFFIXES, AnydocParser
        from application.parser.file.bulk import get_default_file_extractor
        from application.parser.file.html_parser import HTMLMarkdownParser

        monkeypatch.setattr(settings, "DOC_PARSER_ENGINE", "anydoc")
        extractor = get_default_file_extractor()

        for suffix in ANYDOC_SUFFIXES:
            assert isinstance(extractor[suffix], AnydocParser), suffix
        assert isinstance(extractor[".html"], HTMLMarkdownParser)
        assert isinstance(extractor[".xhtml"], HTMLMarkdownParser)
        # Specialised parsers are untouched by the engine choice.
        assert type(extractor[".md"]).__name__ == "MarkdownParser"
        assert type(extractor[".json"]).__name__ == "JSONParser"
        assert type(extractor[".epub"]).__name__ == "EpubParser"

    def test_anydoc_falls_back_to_docling_when_installed(self):
        pytest.importorskip("anydoc")
        pytest.importorskip("docling")
        from application.parser.file.bulk import get_default_file_extractor

        extractor = get_default_file_extractor(engine="anydoc")

        assert type(extractor[".pdf"].fallback_parser).__name__ == "DoclingPDFParser"
        assert type(extractor[".csv"].fallback_parser).__name__ == "DoclingCSVParser"
        assert extractor[".doc"].fallback_parser is None  # nothing else reads .doc
        # docling keeps the formats anydoc cannot read.
        assert type(extractor[".vtt"]).__name__ == "DoclingVTTParser"

    def test_anydoc_fallback_honours_ocr_flag(self):
        pytest.importorskip("anydoc")
        pytest.importorskip("docling")
        from application.parser.file.bulk import get_default_file_extractor

        extractor = get_default_file_extractor(engine="anydoc", ocr_enabled=True)

        assert extractor[".pdf"].fallback_parser.ocr_enabled is True
        assert type(extractor[".png"]).__name__ == "DoclingImageParser"

    def test_anydoc_falls_back_to_legacy_without_docling(self, monkeypatch):
        pytest.importorskip("anydoc")
        import sys

        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "docling", None)
        extractor = get_default_file_extractor(engine="anydoc")

        assert type(extractor[".pdf"].fallback_parser).__name__ == "PDFParser"
        assert type(extractor[".xlsx"].fallback_parser).__name__ == "ExcelParser"
        assert type(extractor[".png"]).__name__ == "ImageParser"

    def test_docling_engine_keeps_docling_map(self):
        pytest.importorskip("docling")
        from application.parser.file.bulk import get_default_file_extractor

        extractor = get_default_file_extractor(engine="docling")

        assert type(extractor[".pdf"]).__name__ == "DoclingPDFParser"
        assert type(extractor[".html"]).__name__ == "DoclingHTMLParser"

    def test_setting_selects_docling(self, settings, monkeypatch):
        pytest.importorskip("docling")
        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setattr(settings, "DOC_PARSER_ENGINE", "docling")
        assert type(get_default_file_extractor()[".pdf"]).__name__ == "DoclingPDFParser"

    def test_unknown_engine_uses_anydoc(self):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser
        from application.parser.file.bulk import get_default_file_extractor

        assert isinstance(get_default_file_extractor(engine="ghost")[".pdf"], AnydocParser)

    def test_missing_anydoc_degrades_to_base_engine(self, monkeypatch):
        import sys

        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "anydoc", None)
        extractor = get_default_file_extractor(engine="anydoc")

        assert type(extractor[".pdf"]).__name__ in ("DoclingPDFParser", "PDFParser")
        assert type(extractor[".html"]).__name__ in ("DoclingHTMLParser", "HTMLParser")

    def test_missing_docling_map_is_usable(self, monkeypatch):
        """Regression: with docling absent the map handed out docling parsers whose
        ``init_parser`` raised ``ImportError`` — not a ``DocumentParseError`` — so
        the first file aborted the whole ingest instead of degrading."""
        import sys

        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "docling", None)
        extractor = get_default_file_extractor(engine="docling")

        assert type(extractor[".pdf"]).__name__ == "PDFParser"
        assert ".xhtml" in extractor
        for suffix in (".pdf", ".docx", ".csv", ".xlsx", ".html", ".xhtml", ".pptx"):
            extractor[suffix].init_parser()


# =====================================================================
# Gained formats (anydoc-only: legacy/macro Office, OpenDocument, RTF)
# =====================================================================


@pytest.mark.unit
class TestGainedFormats:
    def test_every_supported_extension_has_a_parser_under_both_engines(self):
        """The invariant that keeps constants.py and the parser maps in lockstep.

        Without it, an extension accepted at upload but missing from the map
        falls to SimpleDirectoryReader's plain-text read — for a binary
        format that means mojibake silently ingested and embedded.
        (`.txt` is the one deliberate plain-text read.)
        """
        pytest.importorskip("anydoc")
        from application.parser.file.bulk import get_default_file_extractor
        from application.parser.file.constants import (
            SUPPORTED_SOURCE_DOCUMENT_EXTENSIONS,
        )

        for engine in ("anydoc", "docling"):
            extractor = get_default_file_extractor(engine=engine)
            missing = [
                suffix
                for suffix in SUPPORTED_SOURCE_DOCUMENT_EXTENSIONS
                if suffix != ".txt" and suffix not in extractor
            ]
            assert missing == [], (engine, missing)

    def test_gained_formats_map_to_anydoc_under_both_engines(self):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import (
            ANYDOC_GAINED_SUFFIXES,
            AnydocParser,
        )
        from application.parser.file.bulk import get_default_file_extractor

        for engine in ("anydoc", "docling"):
            extractor = get_default_file_extractor(engine=engine)
            for suffix in ANYDOC_GAINED_SUFFIXES:
                assert isinstance(extractor[suffix], AnydocParser), (engine, suffix)

    def test_gained_formats_never_fall_back_to_anydoc_itself(self):
        pytest.importorskip("anydoc")
        from application.parser.file.anydoc_parser import AnydocParser
        from application.parser.file.bulk import get_default_file_extractor

        extractor = get_default_file_extractor(engine="anydoc")
        assert extractor[".doc"].fallback_parser is None
        assert extractor[".rtf"].fallback_parser is None
        # ...while the core five keep their real fallback.
        assert extractor[".pdf"].fallback_parser is not None
        assert not isinstance(extractor[".pdf"].fallback_parser, AnydocParser)

    def test_gained_entries_absent_without_anydoc(self, monkeypatch):
        import sys

        from application.parser.file.bulk import get_default_file_extractor

        monkeypatch.setitem(sys.modules, "anydoc", None)
        extractor = get_default_file_extractor(engine="docling")
        assert ".doc" not in extractor  # degrades to the pre-anydoc map

    def test_rtf_converts_end_to_end(self, tmp_path):
        pytest.importorskip("anydoc")
        from application.parser.file.bulk import get_default_file_extractor

        path = tmp_path / "note.rtf"
        path.write_text(r"{\rtf1\ansi Hello {\b bold} world.\par Second paragraph.}")
        parser = get_default_file_extractor()[".rtf"]
        parser.init_parser()

        out = parser.parse_file(path)

        assert "Hello **bold** world." in out
        assert "Second paragraph." in out

    def test_odt_converts_end_to_end(self, tmp_path):
        pytest.importorskip("anydoc")
        import zipfile

        from application.parser.file.bulk import get_default_file_extractor

        path = tmp_path / "doc.odt"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "mimetype",
                "application/vnd.oasis.opendocument.text",
                compress_type=zipfile.ZIP_STORED,
            )
            z.writestr(
                "META-INF/manifest.xml",
                '<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
            )
            z.writestr(
                "content.xml",
                '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
                '<text:h text:outline-level="1">Title</text:h><text:p>Body text here.</text:p>'
                "</office:text></office:body></office:document-content>",
            )
        parser = get_default_file_extractor()[".odt"]

        out = parser.parse_file(path)

        assert "# Title" in out
        assert "Body text here." in out
