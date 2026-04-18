"""Tests for pure utility functions in application/worker.py.

These cover helpers that don't require a Celery runtime (no task
instantiation). Aimed at maximizing coverage of ``application/worker.py``
without standing up Celery / redis.
"""

import os
import zipfile
from unittest.mock import MagicMock, patch

import pytest


class TestMetadataFromFilename:
    def test_returns_title_dict(self):
        from application.worker import metadata_from_filename
        assert metadata_from_filename("doc.txt") == {"title": "doc.txt"}


class TestNormalizeFileNameMap:
    def test_empty_returns_empty_dict(self):
        from application.worker import _normalize_file_name_map
        assert _normalize_file_name_map(None) == {}
        assert _normalize_file_name_map("") == {}
        assert _normalize_file_name_map({}) == {}

    def test_json_string_parsed(self):
        from application.worker import _normalize_file_name_map
        assert _normalize_file_name_map('{"a": "Alpha"}') == {"a": "Alpha"}

    def test_invalid_json_returns_empty(self):
        from application.worker import _normalize_file_name_map
        assert _normalize_file_name_map("not-json") == {}

    def test_non_dict_returns_empty(self):
        from application.worker import _normalize_file_name_map
        assert _normalize_file_name_map("[1, 2, 3]") == {}

    def test_existing_dict_returned(self):
        from application.worker import _normalize_file_name_map
        assert _normalize_file_name_map({"x": "y"}) == {"x": "y"}


class TestGetDisplayName:
    def test_returns_none_for_empty_inputs(self):
        from application.worker import _get_display_name
        assert _get_display_name({}, "a.txt") is None
        assert _get_display_name({"a": "A"}, "") is None
        assert _get_display_name(None, "a.txt") is None

    def test_exact_rel_path_match(self):
        from application.worker import _get_display_name
        assert _get_display_name({"sub/a.txt": "Alpha"}, "sub/a.txt") == "Alpha"

    def test_basename_fallback(self):
        from application.worker import _get_display_name
        assert _get_display_name({"a.txt": "Alpha"}, "sub/a.txt") == "Alpha"

    def test_no_match_returns_none(self):
        from application.worker import _get_display_name
        assert _get_display_name({"x.txt": "X"}, "sub/a.txt") is None


class TestApplyDisplayNames:
    def test_non_dict_structure_returned_as_is(self):
        from application.worker import _apply_display_names_to_structure
        assert _apply_display_names_to_structure("not a dict", {"a": "A"}) == "not a dict"

    def test_empty_filemap_returned_as_is(self):
        from application.worker import _apply_display_names_to_structure
        s = {"f.txt": {"type": "file", "size_bytes": 10}}
        assert _apply_display_names_to_structure(s, {}) == s

    def test_applies_display_name_to_files(self):
        from application.worker import _apply_display_names_to_structure
        structure = {
            "doc.txt": {"type": "file", "size_bytes": 10},
            "sub": {
                "nested.txt": {"type": "file", "size_bytes": 20},
            },
        }
        filemap = {"doc.txt": "DOC", "sub/nested.txt": "Nested"}
        got = _apply_display_names_to_structure(structure, filemap)
        assert got["doc.txt"]["display_name"] == "DOC"
        assert got["sub"]["nested.txt"]["display_name"] == "Nested"

    def test_missing_display_name_leaves_untouched(self):
        from application.worker import _apply_display_names_to_structure
        structure = {"x.txt": {"type": "file", "size_bytes": 10}}
        got = _apply_display_names_to_structure(structure, {"y.txt": "Y"})
        assert "display_name" not in got["x.txt"]


class TestGenerateRandomString:
    def test_length(self):
        from application.worker import generate_random_string
        assert len(generate_random_string(8)) == 8
        assert len(generate_random_string(0)) == 0

    def test_chars_are_letters(self):
        from application.worker import generate_random_string
        s = generate_random_string(20)
        assert all(c.isalpha() for c in s)


class TestIsPathSafe:
    def test_allows_file_under_base(self, tmp_path):
        from application.worker import _is_path_safe
        base = str(tmp_path)
        target = os.path.join(base, "sub", "file.txt")
        assert _is_path_safe(base, target) is True

    def test_rejects_path_above_base(self, tmp_path):
        from application.worker import _is_path_safe
        base = str(tmp_path)
        target = "/tmp/outside.txt"
        assert _is_path_safe(base, target) is False

    def test_allows_base_itself(self, tmp_path):
        from application.worker import _is_path_safe
        base = str(tmp_path)
        assert _is_path_safe(base, base) is True


class TestValidateZipSafety:
    def test_rejects_nonexistent_zip(self, tmp_path):
        from application.worker import (
            _validate_zip_safety, ZipExtractionError,
        )
        # A path that doesn't exist → BadZipFile wrapped as ZipExtractionError
        with pytest.raises((ZipExtractionError, FileNotFoundError)):
            _validate_zip_safety(
                str(tmp_path / "nope.zip"), str(tmp_path),
            )

    def test_accepts_valid_small_zip(self, tmp_path):
        from application.worker import _validate_zip_safety
        zip_path = tmp_path / "ok.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.txt", "content")
        # Should not raise
        _validate_zip_safety(str(zip_path), str(tmp_path))

    def test_rejects_path_traversal_in_zip(self, tmp_path):
        from application.worker import (
            _validate_zip_safety, ZipExtractionError,
        )
        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Absolute path members trigger path traversal detection
            info = zipfile.ZipInfo("/absolute/file.txt")
            zf.writestr(info, "evil")
        with pytest.raises(ZipExtractionError):
            _validate_zip_safety(str(zip_path), str(tmp_path))

    def test_rejects_too_many_files(self, tmp_path):
        from application.worker import (
            _validate_zip_safety, ZipExtractionError,
        )
        zip_path = tmp_path / "many.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Write just enough files to stay well within the cap, then
            # patch the cap to trigger the "too many files" branch.
            for i in range(20):
                zf.writestr(f"f{i}.txt", "x")
        with patch("application.worker.MAX_FILE_COUNT", 5):
            with pytest.raises(ZipExtractionError):
                _validate_zip_safety(str(zip_path), str(tmp_path))


class TestExtractZipRecursive:
    def test_extracts_flat_zip(self, tmp_path):
        from application.worker import extract_zip_recursive

        zip_path = tmp_path / "in.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.txt", "A content")
            zf.writestr("b.txt", "B content")
        extract_to = tmp_path / "out"
        extract_to.mkdir()
        extract_zip_recursive(str(zip_path), str(extract_to))
        assert (extract_to / "a.txt").exists()
        assert (extract_to / "b.txt").exists()

    def test_extracts_nested_zip_recursively(self, tmp_path):
        from application.worker import extract_zip_recursive

        # Create inner.zip
        inner = tmp_path / "inner.zip"
        with zipfile.ZipFile(inner, "w") as zf:
            zf.writestr("inside.txt", "inside content")

        outer = tmp_path / "outer.zip"
        with zipfile.ZipFile(outer, "w") as zf:
            zf.write(inner, "inner.zip")

        extract_to = tmp_path / "out"
        extract_to.mkdir()
        extract_zip_recursive(str(outer), str(extract_to))
        # After recursive extraction, the inside.txt from the inner zip
        # should be present
        found = list(extract_to.rglob("inside.txt"))
        assert found, "expected nested zip to be extracted"


class TestDownloadFile:
    def test_writes_file_on_success(self, tmp_path):
        from application.worker import download_file

        dest = tmp_path / "downloaded.bin"
        mock_response = MagicMock()
        mock_response.content = b"file-content"
        mock_response.raise_for_status = MagicMock()

        with patch(
            "application.worker.requests.get", return_value=mock_response,
        ):
            download_file("http://ex/foo", {}, str(dest))

        assert dest.read_bytes() == b"file-content"

    def test_raises_on_request_error(self, tmp_path):
        from application.worker import download_file
        import requests

        with patch(
            "application.worker.requests.get",
            side_effect=requests.RequestException("boom"),
        ):
            with pytest.raises(requests.RequestException):
                download_file(
                    "http://ex/foo", {}, str(tmp_path / "x"),
                )


class TestUploadIndex:
    def test_non_faiss_posts_data_only(self, tmp_path):
        from application.worker import upload_index

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch(
            "application.worker.settings.VECTOR_STORE", "milvus"
        ), patch(
            "application.worker.settings.API_URL", "http://api/"
        ), patch(
            "application.worker.settings.INTERNAL_KEY", "k"
        ), patch(
            "application.worker.requests.post", return_value=mock_response,
        ) as mock_post:
            upload_index(str(tmp_path), {"source_id": "1"})

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["headers"]["X-Internal-Key"] == "k"
        assert kwargs["data"] == {"source_id": "1"}

    def test_faiss_missing_file_raises(self, tmp_path):
        from application.worker import upload_index

        with patch(
            "application.worker.settings.VECTOR_STORE", "faiss"
        ):
            with pytest.raises(FileNotFoundError):
                upload_index(str(tmp_path), {"source_id": "1"})

    def test_faiss_uploads_both_files(self, tmp_path):
        from application.worker import upload_index

        (tmp_path / "index.faiss").write_bytes(b"faiss-bytes")
        (tmp_path / "index.pkl").write_bytes(b"pkl-bytes")
        mock_response = MagicMock()

        with patch(
            "application.worker.settings.VECTOR_STORE", "faiss"
        ), patch(
            "application.worker.settings.API_URL", "http://api/"
        ), patch(
            "application.worker.settings.INTERNAL_KEY", ""
        ), patch(
            "application.worker.requests.post", return_value=mock_response,
        ) as mock_post:
            upload_index(str(tmp_path), {"source_id": "1"})

        mock_post.assert_called_once()
        files = mock_post.call_args.kwargs["files"]
        assert "file_faiss" in files and "file_pkl" in files
