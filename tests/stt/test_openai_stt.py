"""Tests for application/stt/openai_stt.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


@pytest.mark.unit
class TestOpenAISTTInit:

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_init_defaults_from_settings(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-from-settings"
        mock_settings.API_KEY = "sk-fallback"
        mock_settings.OPENAI_BASE_URL = "https://custom.api.com/v1"
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        assert stt.api_key == "sk-from-settings"
        assert stt.base_url == "https://custom.api.com/v1"
        assert stt.model == "whisper-1"
        mock_openai_cls.assert_called_once_with(
            api_key="sk-from-settings",
            base_url="https://custom.api.com/v1",
        )

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_init_explicit_params_override_settings(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-settings"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT(
            api_key="sk-explicit",
            base_url="https://explicit.api.com",
            model="whisper-2",
        )

        assert stt.api_key == "sk-explicit"
        assert stt.base_url == "https://explicit.api.com"
        assert stt.model == "whisper-2"

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_init_falls_back_to_api_key(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = None
        mock_settings.API_KEY = "sk-fallback-key"
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        assert stt.api_key == "sk-fallback-key"

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_init_default_base_url(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        assert stt.base_url == "https://api.openai.com/v1"


@pytest.mark.unit
class TestOpenAISTTTranscribe:

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_transcribe_basic(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "text": "Hello world",
            "language": "en",
            "duration": 2.5,
            "segments": [],
        }
        mock_client.audio.transcriptions.create.return_value = mock_response

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        file_path = Path("/tmp/test_audio.wav")
        with patch("builtins.open", mock_open(read_data=b"audio_data")):
            result = stt.transcribe(file_path)

        assert result["text"] == "Hello world"
        assert result["language"] == "en"
        assert result["duration_s"] == 2.5
        assert result["segments"] == []
        assert result["provider"] == "openai"

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_transcribe_with_language(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "text": "Bonjour",
            "language": "fr",
            "duration": 1.0,
            "segments": [],
        }
        mock_client.audio.transcriptions.create.return_value = mock_response

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        file_path = Path("/tmp/test_audio.wav")
        with patch("builtins.open", mock_open(read_data=b"audio_data")):
            result = stt.transcribe(file_path, language="fr")

        assert result["language"] == "fr"
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["language"] == "fr"

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_transcribe_with_timestamps(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        segment_obj = MagicMock()
        segment_obj.model_dump.return_value = {
            "start": 0.0,
            "end": 1.5,
            "text": "Hello",
        }

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "text": "Hello",
            "language": "en",
            "duration": 1.5,
            "segments": [segment_obj],
        }
        mock_client.audio.transcriptions.create.return_value = mock_response

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        file_path = Path("/tmp/test_audio.wav")
        with patch("builtins.open", mock_open(read_data=b"audio_data")):
            result = stt.transcribe(file_path, timestamps=True)

        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["timestamp_granularities"] == ["segment"]
        assert len(result["segments"]) == 1

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_transcribe_no_segments_key(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "text": "Hello",
        }
        mock_client.audio.transcriptions.create.return_value = mock_response

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        file_path = Path("/tmp/test_audio.wav")
        with patch("builtins.open", mock_open(read_data=b"audio_data")):
            result = stt.transcribe(file_path)

        assert result["text"] == "Hello"
        assert result["segments"] == []

    @patch("application.stt.openai_stt.OpenAI")
    @patch("application.stt.openai_stt.settings")
    def test_transcribe_language_fallback_to_param(self, mock_settings, mock_openai_cls):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.API_KEY = None
        mock_settings.OPENAI_BASE_URL = None
        mock_settings.OPENAI_STT_MODEL = "whisper-1"

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "text": "Test",
            "language": None,
            "duration": 1.0,
        }
        mock_client.audio.transcriptions.create.return_value = mock_response

        from application.stt.openai_stt import OpenAISTT

        stt = OpenAISTT()

        file_path = Path("/tmp/test_audio.wav")
        with patch("builtins.open", mock_open(read_data=b"audio_data")):
            result = stt.transcribe(file_path, language="de")

        assert result["language"] == "de"


@pytest.mark.unit
class TestOpenAISTTToDict:

    def test_to_dict_with_model_dump(self):
        from application.stt.openai_stt import OpenAISTT

        obj = MagicMock()
        obj.model_dump.return_value = {"key": "value"}

        result = OpenAISTT._to_dict(obj)
        assert result == {"key": "value"}

    def test_to_dict_with_dict(self):
        from application.stt.openai_stt import OpenAISTT

        result = OpenAISTT._to_dict({"key": "value"})
        assert result == {"key": "value"}

    def test_to_dict_with_other_type(self):
        from application.stt.openai_stt import OpenAISTT

        result = OpenAISTT._to_dict("string_value")
        assert result == {}

    def test_to_dict_with_none(self):
        from application.stt.openai_stt import OpenAISTT

        result = OpenAISTT._to_dict(None)
        assert result == {}
