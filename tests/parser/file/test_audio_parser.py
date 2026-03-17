from pathlib import Path
from unittest.mock import MagicMock, patch

from application.parser.file.audio_parser import AudioParser
from application.parser.file.bulk import get_default_file_extractor


def test_audio_init_parser():
    parser = AudioParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


@patch("application.parser.file.audio_parser.STTCreator.create_stt")
@patch("application.parser.file.audio_parser.settings")
def test_audio_parser_transcribes_file(mock_settings, mock_create_stt):
    mock_settings.STT_PROVIDER = "openai"
    mock_settings.STT_LANGUAGE = "en"
    mock_settings.STT_ENABLE_TIMESTAMPS = False
    mock_settings.STT_ENABLE_DIARIZATION = False

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = {"text": "Transcript from audio"}
    mock_create_stt.return_value = mock_stt

    parser = AudioParser()
    result = parser.parse_file(Path("meeting.wav"))

    assert result == "Transcript from audio"
    mock_create_stt.assert_called_once_with("openai")
    mock_stt.transcribe.assert_called_once_with(
        Path("meeting.wav"),
        language="en",
        timestamps=False,
        diarize=False,
    )


def test_default_file_extractor_supports_audio_extensions():
    extractor = get_default_file_extractor()

    assert isinstance(extractor[".wav"], AudioParser)
    assert isinstance(extractor[".mp3"], AudioParser)
    assert isinstance(extractor[".m4a"], AudioParser)
    assert isinstance(extractor[".ogg"], AudioParser)
    assert isinstance(extractor[".webm"], AudioParser)
