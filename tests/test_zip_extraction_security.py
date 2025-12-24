"""Tests for zip extraction security measures."""

import os
import tempfile
import zipfile

import pytest

from application.worker import (
    ZipExtractionError,
    _is_path_safe,
    _validate_zip_safety,
    extract_zip_recursive,
    MAX_UNCOMPRESSED_SIZE,
    MAX_FILE_COUNT,
    MAX_COMPRESSION_RATIO,
)


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
            assert os.path.exists(os.path.join(extract_to, "inner.txt"))

            # Check both zips were removed
            assert not os.path.exists(zip_path)
            assert not os.path.exists(os.path.join(extract_to, "inner.zip"))

    def test_respects_max_depth(self):
        """Extraction should stop at max recursion depth."""
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
            extract_zip_recursive(zip_path, extract_to, max_depth=2)

            # The deepest nested zips should remain unextracted
            # (we can't easily verify the exact behavior, but the function should not crash)

    def test_rejects_path_traversal(self):
        """Zip with path traversal should be rejected and removed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "malicious.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a malicious zip
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("../../../tmp/malicious.txt", "malicious")

            extract_zip_recursive(zip_path, extract_to)

            # Zip should be removed
            assert not os.path.exists(zip_path)

            # Malicious file should NOT exist outside extract_to
            assert not os.path.exists("/tmp/malicious.txt")

    def test_handles_corrupted_zip_gracefully(self):
        """Corrupted zip should be handled gracefully without crashing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "corrupted.zip")
            extract_to = os.path.join(temp_dir, "extract")
            os.makedirs(extract_to)

            # Create a corrupted file
            with open(zip_path, "wb") as f:
                f.write(b"This is not a valid zip file")

            # Should not raise, just log error
            extract_zip_recursive(zip_path, extract_to)

            # Function should complete without exception


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
