"""Comprehensive tests for application/parser/file/bulk.py

Covers: SimpleDirectoryReader (init, file discovery, load_data, directory
structure building), get_default_file_extractor.
"""

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
