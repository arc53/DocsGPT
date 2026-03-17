from unittest.mock import patch

from application.stt.upload_limits import (
    build_stt_file_size_limit_message,
    enforce_audio_file_size_limit,
    is_audio_filename,
    should_reject_stt_request,
)


@patch("application.stt.upload_limits.settings")
def test_should_reject_stt_request_when_content_length_exceeds_limit(mock_settings):
    mock_settings.STT_MAX_FILE_SIZE_MB = 1

    assert (
        should_reject_stt_request(
            "/api/stt",
            (2 * 1024 * 1024) + 1,
        )
        is True
    )
    assert should_reject_stt_request("/api/upload", (2 * 1024 * 1024) + 1) is False


@patch("application.stt.upload_limits.settings")
def test_enforce_audio_file_size_limit_uses_configured_message(mock_settings):
    mock_settings.STT_MAX_FILE_SIZE_MB = 1

    try:
        enforce_audio_file_size_limit(2 * 1024 * 1024)
    except ValueError as exc:
        assert str(exc) == build_stt_file_size_limit_message()
    else:
        raise AssertionError("Expected oversized audio file to raise")


def test_is_audio_filename_handles_supported_extensions():
    assert is_audio_filename("meeting.wav") is True
    assert is_audio_filename("meeting.txt") is False
