"""The ``attachment.failed`` payload: a stable code and a short, user-safe message."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

_BASE64 = "QUJD" * 400


def _classify(error, filename="report.pdf"):
    from docsgpt.worker import attachment_failure

    return attachment_failure(error, filename)


class TestAttachmentFailure:
    def test_unsupported_type_keeps_the_stable_upload_message(self):
        from docsgpt.upload_limits import UnsupportedUploadTypeError, unsupported_upload_message
        from docsgpt.worker import AttachmentRejectedError

        rejected = AttachmentRejectedError(unsupported_upload_message("clip.mp4"), code="unsupported_type")
        assert _classify(rejected, "clip.mp4") == {
            "code": "unsupported_type",
            "error": "Unsupported file type: .mp4",
        }
        assert _classify(UnsupportedUploadTypeError("x"), "clip.mp4")["code"] == "unsupported_type"

    @pytest.mark.parametrize(
        ("code", "expected"),
        [("too_large", "too_large"), ("archive_unreadable", "archive_unreadable"), (None, "rejected")],
    )
    def test_a_rejection_reports_its_own_code(self, code, expected):
        from docsgpt.worker import AttachmentRejectedError

        failure = _classify(AttachmentRejectedError(f"raw detail {_BASE64}", code=code))
        assert failure["code"] == expected
        assert _BASE64 not in failure["error"] and "raw detail" not in failure["error"]

    def test_a_scan_without_text(self):
        from docsgpt.parser.file.base_parser import NoTextLayerError

        assert _classify(NoTextLayerError("no text layer on 12 pages"))["code"] == "no_text"

    @pytest.mark.parametrize("error_type", ["soft", "timeout"])
    def test_a_parse_that_took_too_long(self, error_type):
        from celery.exceptions import SoftTimeLimitExceeded

        error = SoftTimeLimitExceeded() if error_type == "soft" else TimeoutError("read timed out")
        assert _classify(error)["code"] == "timeout"

    def test_a_parser_error(self):
        from docsgpt.parser.file.base_parser import DocumentParseError

        failure = _classify(DocumentParseError(f"docling exploded: {_BASE64}"))
        assert failure["code"] == "parse_failed"
        assert _BASE64 not in failure["error"]

    def test_a_storage_error(self):
        class ClientError(Exception):
            pass

        ClientError.__module__ = "botocore.exceptions"
        assert _classify(FileNotFoundError("uploads/x"))["code"] == "storage"
        assert _classify(ClientError("NoSuchKey"))["code"] == "storage"

    def test_anything_else_is_generic(self):
        failure = _classify(RuntimeError(f"Traceback secret {_BASE64}"))
        assert failure == {"code": "processing_failed", "error": "This file could not be processed."}

    def test_every_message_is_short_and_plain(self):
        from docsgpt.worker import ATTACHMENT_FAILURE_MESSAGES

        for code, message in ATTACHMENT_FAILURE_MESSAGES.items():
            assert code and message.endswith(".") and len(message) <= 120


def test_the_log_line_is_bounded_and_drops_base64_but_keeps_the_frames():
    from docsgpt.worker import _failure_log_text

    try:
        raise RuntimeError("parser said " + _BASE64 + " x" * 2000)
    except RuntimeError as exc:
        text = _failure_log_text(exc)
    first_line, _, frames = text.partition("\n")
    assert first_line.startswith("RuntimeError: parser said [long token omitted]")
    assert len(first_line) <= 600
    assert _BASE64 not in text
    assert "test_the_log_line_is_bounded" in frames
