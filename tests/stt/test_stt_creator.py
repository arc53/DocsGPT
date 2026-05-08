import pytest
from unittest.mock import MagicMock, patch

from application.stt.stt_creator import STTCreator


@pytest.fixture
def stt_creator():
    return STTCreator()


def test_create_openai_stt(stt_creator):
    with patch.dict(STTCreator.stt_providers, {"openai": MagicMock()}):
        mock_openai_stt = STTCreator.stt_providers["openai"]
        instance = MagicMock()
        mock_openai_stt.return_value = instance

        result = stt_creator.create_stt("openai", "arg1", language="en")

        mock_openai_stt.assert_called_once_with("arg1", language="en")
        assert result == instance


def test_create_faster_whisper_stt(stt_creator):
    with patch.dict(STTCreator.stt_providers, {"faster_whisper": MagicMock()}):
        mock_faster_whisper_stt = STTCreator.stt_providers["faster_whisper"]
        instance = MagicMock()
        mock_faster_whisper_stt.return_value = instance

        result = stt_creator.create_stt("faster_whisper", model_size="base")

        mock_faster_whisper_stt.assert_called_once_with(model_size="base")
        assert result == instance


def test_invalid_stt_type(stt_creator):
    with pytest.raises(ValueError) as excinfo:
        stt_creator.create_stt("unknown_stt")
    assert "No stt class found" in str(excinfo.value)


def test_stt_type_case_insensitivity(stt_creator):
    with patch.dict(STTCreator.stt_providers, {"openai": MagicMock()}):
        mock_openai_stt = STTCreator.stt_providers["openai"]
        instance = MagicMock()
        mock_openai_stt.return_value = instance

        result = stt_creator.create_stt("OpEnAi")

        mock_openai_stt.assert_called_once_with()
        assert result == instance


def test_stt_providers_integrity(stt_creator):
    providers = stt_creator.stt_providers
    assert "openai" in providers
    assert "faster_whisper" in providers
    assert callable(providers["openai"])
    assert callable(providers["faster_whisper"])
