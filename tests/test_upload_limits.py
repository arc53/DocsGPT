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


# --- attachment type gate -------------------------------------------------
#
# ``SimpleDirectoryReader`` falls through to a plain-text ``open()`` for any
# suffix without a parser. That is what a .py or a .log attachment relies on,
# and it is also how a phone-uploaded video used to be "parsed" into
# megabytes of binary garbage, truncated, and stored with
# ``extraction.status == "ok"``. So a suffix with no parser is admitted on
# content: text in, binary out.

MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("clip.mp4", MP4_HEADER),
        ("movie.MOV", MP4_HEADER),
        ("archive.zip", b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + bytes(range(32))),
        ("binary", bytes(range(32)) * 8),
        ("trailing.", b"\x00\x01\x02\x03"),
        ("x.tar.gz", b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"),
    ],
)
def test_enforce_parseable_attachment_rejects_binary_without_a_parser(
    filename, content, tmp_path
):
    from application.upload_limits import (
        enforce_parseable_attachment,
        UnsupportedUploadTypeError,
        unsupported_upload_message,
    )

    path = tmp_path / "staged.bin"
    path.write_bytes(content)

    with pytest.raises(UnsupportedUploadTypeError) as excinfo:
        enforce_parseable_attachment(path, filename)
    assert str(excinfo.value) == unsupported_upload_message(filename)
    assert str(excinfo.value).startswith("Unsupported file type")


@pytest.mark.parametrize(
    "filename",
    [
        "notes.txt",
        "Report.PDF",
        "photo.JPG",
        "slides.pptx",
        "voice.ogg",
        "page.xhtml",
        "doc.adoc",
        "scan.webp",
        "fax.tiff",
        "subs.vtt",
        "feed.xml",
    ],
)
def test_enforce_parseable_attachment_accepts_parser_backed_types(filename, tmp_path):
    """A parser-backed suffix is admitted on its name — a PDF is binary and parses fine."""
    from application.upload_limits import enforce_parseable_attachment

    path = tmp_path / "staged.bin"
    path.write_bytes(MP4_HEADER)

    enforce_parseable_attachment(path, filename)


@pytest.mark.parametrize(
    "filename",
    ["main.py", "server.log", "config.yaml", "query.sql", "Dockerfile", "notes.unknown"],
)
def test_enforce_parseable_attachment_accepts_text_without_a_parser(filename, tmp_path):
    """The plain-text fallthrough reads these correctly, so they must stay allowed."""
    from application.upload_limits import enforce_parseable_attachment

    path = tmp_path / "staged.txt"
    path.write_text("def main():\n\treturn 'café — ok'\n", encoding="utf-8")

    enforce_parseable_attachment(path, filename)


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (b"", True),
        (b"plain text\n", True),
        ("café — em dash\n".encode(), True),
        (b"\x1b[31mred log line\x1b[0m\n", True),
        (b"text\x00with nul", False),
        (bytes(range(32)) * 4, False),
        (b"\x7f\x7f\x7f\x7f" + b"a" * 16, False),
    ],
)
def test_looks_like_text(sample, expected):
    from application.upload_limits import looks_like_text

    assert looks_like_text(sample) is expected


def test_file_looks_like_text_only_samples_the_head(tmp_path):
    """Binary past the sampled head is the parser's problem, not the gate's."""
    from application.upload_limits import file_looks_like_text

    path = tmp_path / "staged.log"
    path.write_bytes(b"a" * 9000 + b"\x00" * 100)

    assert file_looks_like_text(path) is True


def test_file_looks_like_text_allows_an_unreadable_file(tmp_path):
    from application.upload_limits import file_looks_like_text

    assert file_looks_like_text(tmp_path / "missing.txt") is True


def test_unsupported_upload_message_names_the_extension():
    from application.upload_limits import unsupported_upload_message

    assert unsupported_upload_message("clip.mp4") == "Unsupported file type: .mp4"
    assert unsupported_upload_message("Clip.MP4") == "Unsupported file type: .mp4"
    assert unsupported_upload_message("binary") == "Unsupported file type: (no extension)"
