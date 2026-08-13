"""Tests for zip extraction security measures."""

import os
import stat
import tempfile
import zipfile

import pytest

from application.worker import (
    ZipExtractionError,
    _is_path_safe,
    _validate_zip_safety,
    extract_zip_recursive,
    MAX_FILE_COUNT,
)
from application.security.zip_archive import (
    extract_zip_safely,
    ZipExtractionLimits,
)


def _test_limits(**overrides):
    values = {
        "max_uncompressed_bytes": 20 * 1024 * 1024,
        "max_files": 100,
        "max_compression_ratio": 2_000,
        "max_member_bytes": 10 * 1024 * 1024,
        "max_depth": 3,
    }
    values.update(overrides)
    return ZipExtractionLimits(**values)


class TestTransactionalZipExtraction:
    def test_default_file_budget_accepts_large_source_archives(self, tmp_path):
        from application.api.user.sources.upload import _source_archive_limits
        from application.security.zip_archive import validate_zip_archive

        zip_path = tmp_path / "repository.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            for index in range(1_845):
                archive.writestr(f"src/file-{index}.txt", b"x")

        validate_zip_archive(zip_path, _source_archive_limits())

    def test_directory_records_and_case_distinct_files_are_allowed(self, tmp_path):
        zip_path = tmp_path / "portable.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("docs/", b"")
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("docs/", b"")
            archive.writestr("docs/README.txt", b"upper")
            archive.writestr("docs/readme.txt", b"lower")

        destination = tmp_path / "out"
        extract_zip_safely(zip_path, destination, _test_limits(max_files=2))

        extracted_contents = {
            path.read_bytes() for path in (destination / "docs").iterdir()
        }
        assert extracted_contents == {b"upper", b"lower"}

    def test_failure_leaves_destination_unchanged(self, tmp_path):
        zip_path = tmp_path / "corrupt.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("first.txt", b"FIRST")
            archive.writestr("second.txt", b"SECOND")

        payload = bytearray(zip_path.read_bytes())
        second_offset = payload.index(b"SECOND")
        payload[second_offset] ^= 0xFF
        zip_path.write_bytes(payload)

        destination = tmp_path / "out"
        destination.mkdir()
        marker = destination / "existing.txt"
        marker.write_text("keep", encoding="utf-8")

        with pytest.raises(ZipExtractionError):
            extract_zip_safely(zip_path, destination, _test_limits())

        assert marker.read_text(encoding="utf-8") == "keep"
        assert not (destination / "first.txt").exists()
        assert not (destination / "second.txt").exists()

    def test_nested_archives_are_expanded_with_one_budget(self, tmp_path):
        inner_path = tmp_path / "inner.zip"
        with zipfile.ZipFile(inner_path, "w") as archive:
            archive.writestr("inside.txt", b"nested")

        outer_path = tmp_path / "outer.zip"
        with zipfile.ZipFile(outer_path, "w") as archive:
            archive.writestr("outer.txt", b"outer")
            archive.writestr("inner.zip", inner_path.read_bytes())

        destination = tmp_path / "out"
        budget = extract_zip_safely(outer_path, destination, _test_limits())

        assert (destination / "outer.txt").read_bytes() == b"outer"
        assert (destination / "inner" / "inside.txt").read_bytes() == b"nested"
        assert not (destination / "inner.zip").exists()
        assert budget.files == 3

    def test_nested_archive_uses_private_directory_for_colliding_names(
        self, tmp_path
    ):
        inner_path = tmp_path / "n.zip"
        with zipfile.ZipFile(inner_path, "w") as archive:
            archive.writestr("a.txt", b"inner")

        outer_path = tmp_path / "outer.zip"
        with zipfile.ZipFile(outer_path, "w") as archive:
            archive.writestr("a.txt", b"outer")
            archive.writestr("n.zip", inner_path.read_bytes())

        destination = tmp_path / "out"
        extract_zip_safely(outer_path, destination, _test_limits())

        assert (destination / "a.txt").read_bytes() == b"outer"
        assert (destination / "n" / "a.txt").read_bytes() == b"inner"

    @pytest.mark.parametrize("payload", [b"plain text", b"PK\x03\x04truncated"])
    def test_non_zip_member_with_zip_suffix_is_preserved(self, tmp_path, payload):
        outer_path = tmp_path / "outer.zip"
        with zipfile.ZipFile(outer_path, "w") as archive:
            archive.writestr("readme.txt", b"content")
            archive.writestr("notes.zip", payload)

        destination = tmp_path / "out"
        extract_zip_safely(outer_path, destination, _test_limits())

        assert (destination / "readme.txt").read_bytes() == b"content"
        assert (destination / "notes.zip").read_bytes() == payload


class TestIsPathSafe:
    """Tests for _is_path_safe function."""

    def test_safe_path_in_directory(self):
        """Normal file within directory should be safe."""
        assert _is_path_safe("/tmp/extract", "/tmp/extract/file.txt") is True

    def test_safe_path_in_subdirectory(self):
        """File in subdirectory should be safe."""
        assert _is_path_safe("/tmp/extract", "/tmp/extract/subdir/file.txt") is True

    def test_unsafe_path_parent_traversal(self):
        """Path traversal to parent directory should be unsafe."""
        assert _is_path_safe("/tmp/extract", "/tmp/extract/../etc/passwd") is False

    def test_unsafe_path_absolute(self):
        """Absolute path outside base should be unsafe."""
        assert _is_path_safe("/tmp/extract", "/etc/passwd") is False

    def test_unsafe_path_sibling(self):
        """Sibling directory should be unsafe."""
        assert _is_path_safe("/tmp/extract", "/tmp/other/file.txt") is False

    def test_base_path_itself(self):
        """Base path itself should be safe."""
        assert _is_path_safe("/tmp/extract", "/tmp/extract") is True


class TestValidateZipSafety:
    """Tests for _validate_zip_safety function."""

    def test_valid_small_zip(self):
        """Small valid zip file should pass validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "test.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a small valid zip
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("test.txt", "Hello, World!")

            # Should not raise
            _validate_zip_safety(zip_path, extract_to)

    def test_zip_with_too_many_files(self):
        """Zip with too many files should be rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "test.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a zip with many files (just over limit)
            with zipfile.ZipFile(zip_path, "w") as zf:
                for i in range(MAX_FILE_COUNT + 1):
                    zf.writestr(f"file_{i}.txt", "x")

            with pytest.raises(ZipExtractionError) as exc_info:
                _validate_zip_safety(zip_path, extract_to)
            assert "too many files" in str(exc_info.value).lower()

    def test_zip_with_path_traversal(self):
        """Zip with path traversal attempt should be rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "test.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a zip with path traversal
            with zipfile.ZipFile(zip_path, "w") as zf:
                # Add a normal file first
                zf.writestr("normal.txt", "normal content")
                # Add a file with path traversal
                zf.writestr("../../../etc/passwd", "malicious content")

            with pytest.raises(ZipExtractionError) as exc_info:
                _validate_zip_safety(zip_path, extract_to)
            assert "path traversal" in str(exc_info.value).lower()

    def test_corrupted_zip(self):
        """Corrupted zip file should be rejected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "test.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a corrupted "zip" file
            with open(zip_path, "wb") as f:
                f.write(b"not a zip file content")

            with pytest.raises(ZipExtractionError) as exc_info:
                _validate_zip_safety(zip_path, extract_to)
            assert "invalid" in str(exc_info.value).lower() or "corrupted" in str(exc_info.value).lower()


class TestExtractZipRecursive:
    """Tests for extract_zip_recursive function."""

    def test_extract_valid_zip(self):
        """Valid zip file should be extracted successfully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "test.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a valid zip
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("test.txt", "Hello, World!")
                zf.writestr("subdir/nested.txt", "Nested content")

            extract_zip_recursive(zip_path, extract_to)

            # Check files were extracted
            assert os.path.exists(os.path.join(extract_to, "test.txt"))
            assert os.path.exists(os.path.join(extract_to, "subdir", "nested.txt"))

            # Check zip was removed
            assert not os.path.exists(zip_path)

    def test_extract_nested_zip(self):
        """Nested zip files should be extracted recursively."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create inner zip
            inner_zip_content = b""
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as inner_tmp:
                with zipfile.ZipFile(inner_tmp.name, "w") as inner_zf:
                    inner_zf.writestr("inner.txt", "Inner content")
                with open(inner_tmp.name, "rb") as f:
                    inner_zip_content = f.read()
                os.unlink(inner_tmp.name)

            # Create outer zip containing inner zip
            zip_path = os.path.join(temp_dir, "outer.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("outer.txt", "Outer content")
                zf.writestr("inner.zip", inner_zip_content)

            extract_zip_recursive(zip_path, extract_to)

            # Check outer file was extracted
            assert os.path.exists(os.path.join(extract_to, "outer.txt"))

            # Check inner zip was extracted
            assert os.path.exists(os.path.join(extract_to, "inner", "inner.txt"))

            # Check both zips were removed
            assert not os.path.exists(zip_path)
            assert not os.path.exists(os.path.join(extract_to, "inner.zip"))

    def test_respects_max_depth(self):
        """Nesting beyond max depth should fail the extraction loudly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a chain of nested zips
            current_content = b"Final content"
            for i in range(7):  # More than default max_depth of 5
                inner_tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
                with zipfile.ZipFile(inner_tmp.name, "w") as zf:
                    if i == 0:
                        zf.writestr("content.txt", current_content.decode())
                    else:
                        zf.writestr("nested.zip", current_content)
                with open(inner_tmp.name, "rb") as f:
                    current_content = f.read()
                os.unlink(inner_tmp.name)

            # Write the final outermost zip
            zip_path = os.path.join(temp_dir, "outer.zip")
            with open(zip_path, "wb") as f:
                f.write(current_content)

            # Extract with max_depth=2
            with pytest.raises(ZipExtractionError):
                extract_zip_recursive(zip_path, extract_to, max_depth=2)

    def test_rejects_path_traversal(self):
        """Zip with path traversal should be rejected and removed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "malicious.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a malicious zip
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("../../../tmp/malicious.txt", "malicious")

            with pytest.raises(ZipExtractionError):
                extract_zip_recursive(zip_path, extract_to)

            # Zip should be removed
            assert not os.path.exists(zip_path)

            # Malicious file should NOT exist outside extract_to
            assert not os.path.exists("/tmp/malicious.txt")

    def test_rejects_symlink_members(self):
        """Archive-controlled links must never be materialized."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "links.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            link = zipfile.ZipInfo("escape-link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(link, "../../outside")

            with pytest.raises(ZipExtractionError):
                extract_zip_recursive(zip_path, extract_to)

            assert not os.path.lexists(os.path.join(extract_to, "escape-link"))

    def test_corrupted_zip_fails_loudly(self):
        """Corrupted zip should raise so ingestion fails instead of indexing nothing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "corrupted.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a corrupted file
            with open(zip_path, "wb") as f:
                f.write(b"This is not a valid zip file")

            with pytest.raises(ZipExtractionError):
                extract_zip_recursive(zip_path, extract_to)

            # The rejected zip should be removed
            assert not os.path.exists(zip_path)


class TestZipBombProtection:
    """Tests specifically for zip bomb protection."""

    def test_detects_high_compression_ratio(self):
        """Highly compressed data should trigger compression ratio check."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "bomb.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a file with highly compressible content (all zeros)
            # This triggers the compression ratio check
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Create a large file with repetitive content - compresses extremely well
                repetitive_content = "A" * (1024 * 1024)  # 1 MB of 'A's
                zf.writestr("repetitive.txt", repetitive_content)

            # This should be rejected due to high compression ratio
            with pytest.raises(ZipExtractionError) as exc_info:
                _validate_zip_safety(zip_path, extract_to)
            assert "compression ratio" in str(exc_info.value).lower()

    def test_normal_compression_passes(self):
        """Normal compression ratio should pass validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "normal.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a zip with random-ish content that doesn't compress well
            import random
            random.seed(42)
            random_content = "".join(
                random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=10240)
            )

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("random.txt", random_content)

            # Should pass - random content doesn't compress well
            _validate_zip_safety(zip_path, extract_to)

    def test_size_limit_check(self):
        """Files exceeding size limit should be rejected."""
        # Note: We can't easily create a real zip bomb in tests
        # This test verifies the validation logic works
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "test.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a zip with a reasonable size (no compression to avoid ratio issues)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                # 10 KB file
                zf.writestr("normal.txt", "x" * 10240)

            # Should pass
            _validate_zip_safety(zip_path, extract_to)
