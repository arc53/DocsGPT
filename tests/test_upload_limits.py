"""Tests for bounded user-upload stream helpers."""

import io

import pytest

from application.upload_limits import (
    copy_upload_to_path,
    read_upload_limited,
    read_text_upload_limited,
    UploadTooLargeError,
)


class _ShortReadStream(io.BytesIO):
    """Return small chunks even when the caller asks for more."""

    def read(self, size=-1):
        return super().read(min(size, 2) if size >= 0 else 2)


def test_limited_read_accumulates_short_reads_before_rejecting():
    with pytest.raises(UploadTooLargeError):
        read_upload_limited(_ShortReadStream(b"12345"), max_bytes=4)


def test_limited_copy_rejects_before_writing_overflow_byte(tmp_path):
    target = tmp_path / "upload.bin"
    with pytest.raises(UploadTooLargeError):
        copy_upload_to_path(io.BytesIO(b"12345"), target, max_bytes=4)

    assert target.stat().st_size <= 4


def test_limited_text_read_decodes_incrementally_and_rejects_overflow():
    assert read_text_upload_limited(io.BytesIO("café".encode()), max_bytes=5) == "café"

    with pytest.raises(UploadTooLargeError):
        read_text_upload_limited(_ShortReadStream(b"12345"), max_bytes=4)
