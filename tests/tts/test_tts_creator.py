import pytest
from unittest.mock import patch, MagicMock
from application.tts.tts_creator import TTSCreator


@pytest.fixture
def tts_creator():
    return TTSCreator()


def test_create_google_tts(tts_creator):
    # Patch the provider registry so the factory calls our mock class
    with patch.dict(TTSCreator.tts_providers, {"google_tts": MagicMock()}):
        mock_google_tts = TTSCreator.tts_providers["google_tts"]
        instance = MagicMock()
        mock_google_tts.return_value = instance

        result = tts_creator.create_tts("google_tts", "arg1", key="value")

        mock_google_tts.assert_called_once_with("arg1", key="value")
        assert result == instance


def test_create_elevenlabs_tts(tts_creator):
    # Patch the provider registry so the factory calls our mock class
    with patch.dict(TTSCreator.tts_providers, {"elevenlabs": MagicMock()}):
        mock_elevenlabs_tts = TTSCreator.tts_providers["elevenlabs"]
        instance = MagicMock()
        mock_elevenlabs_tts.return_value = instance

        result = tts_creator.create_tts("elevenlabs", "voice", lang="en")

        mock_elevenlabs_tts.assert_called_once_with("voice", lang="en")
        assert result == instance


def test_invalid_tts_type(tts_creator):
    with pytest.raises(ValueError) as excinfo:
        tts_creator.create_tts("unknown_tts")
    assert "No tts class found" in str(excinfo.value)


def test_tts_type_case_insensitivity(tts_creator):
    # Patch the provider registry to ensure case-insensitive lookup hits our mock
    with patch.dict(TTSCreator.tts_providers, {"google_tts": MagicMock()}):
        mock_google_tts = TTSCreator.tts_providers["google_tts"]
        instance = MagicMock()
        mock_google_tts.return_value = instance

        result = tts_creator.create_tts("GoOgLe_TtS")

        mock_google_tts.assert_called_once_with()
        assert result == instance


def test_tts_providers_integrity(tts_creator):
    providers = tts_creator.tts_providers
    assert "google_tts" in providers
    assert "elevenlabs" in providers
    assert callable(providers["google_tts"])
    assert callable(providers["elevenlabs"])