from unittest.mock import MagicMock, patch

from application.parser.file.audio_parser import AudioParser
from application.parser.file.bulk import get_default_file_extractor
from application.stt.upload_limits import AudioFileTooLargeError


def test_audio_init_parser():
    parser = AudioParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


@patch("application.stt.upload_limits.settings")
@patch("application.parser.file.audio_parser.STTCreator.create_stt")
@patch("application.parser.file.audio_parser.settings")
def test_audio_parser_transcribes_file(
    mock_settings, mock_create_stt, mock_limit_settings, tmp_path
):
    mock_settings.STT_PROVIDER = "openai"
    mock_settings.STT_LANGUAGE = "en"
    mock_settings.STT_ENABLE_TIMESTAMPS = False
    mock_settings.STT_ENABLE_DIARIZATION = False
    mock_limit_settings.STT_MAX_FILE_SIZE_MB = 25

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = {"text": "Transcript from audio"}
    mock_create_stt.return_value = mock_stt
    audio_file = tmp_path / "meeting.wav"
    audio_file.write_bytes(b"audio-bytes")

    parser = AudioParser()
    result = parser.parse_file(audio_file)

    assert result == "Transcript from audio"
    mock_create_stt.assert_called_once_with("openai")
    mock_stt.transcribe.assert_called_once_with(
        audio_file,
        language="en",
        timestamps=False,
        diarize=False,
    )


@patch("application.stt.upload_limits.settings")
def test_audio_parser_rejects_oversized_files(mock_limit_settings, tmp_path):
    mock_limit_settings.STT_MAX_FILE_SIZE_MB = 1

    audio_file = tmp_path / "meeting.wav"
    audio_file.write_bytes(b"x" * (2 * 1024 * 1024))

    parser = AudioParser()

    try:
        parser.parse_file(audio_file)
    except AudioFileTooLargeError as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("Expected oversized audio file to be rejected")


def test_default_file_extractor_supports_audio_extensions():
    extractor = get_default_file_extractor()

    assert isinstance(extractor[".wav"], AudioParser)
    assert isinstance(extractor[".mp3"], AudioParser)
    assert isinstance(extractor[".m4a"], AudioParser)
    assert isinstance(extractor[".ogg"], AudioParser)
    assert isinstance(extractor[".webm"], AudioParser)
