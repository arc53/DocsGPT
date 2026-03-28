import base64
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from application.tts.minimax_tts import MiniMaxTTS


@pytest.fixture
def minimax_tts(monkeypatch):
    monkeypatch.setattr(
        "application.tts.minimax_tts.settings",
        SimpleNamespace(MINIMAX_API_KEY="test-minimax-key"),
    )
    return MiniMaxTTS()


@pytest.mark.unit
def test_minimax_tts_text_to_speech(minimax_tts, monkeypatch):
    # Prepare fake hex-encoded audio data (MP3 ID3 header)
    fake_audio_bytes = b"ID3\x04\x00\x00\x00\x00\x00"
    fake_hex = fake_audio_bytes.hex()

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "data": {"audio": fake_hex, "status": 2},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }

    monkeypatch.setattr(
        "application.tts.minimax_tts.requests.post",
        lambda *args, **kwargs: fake_response,
    )

    audio_base64, lang = minimax_tts.text_to_speech("Hello world")

    assert lang == "en"
    decoded = base64.b64decode(audio_base64)
    assert decoded == fake_audio_bytes


@pytest.mark.unit
def test_minimax_tts_api_error(minimax_tts, monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "data": {},
        "base_resp": {"status_code": 1004, "status_msg": "authentication failed"},
    }

    monkeypatch.setattr(
        "application.tts.minimax_tts.requests.post",
        lambda *args, **kwargs: fake_response,
    )

    with pytest.raises(RuntimeError, match="MiniMax TTS error"):
        minimax_tts.text_to_speech("Hello")


@pytest.mark.unit
def test_minimax_tts_empty_audio(minimax_tts, monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "data": {"audio": "", "status": 2},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }

    monkeypatch.setattr(
        "application.tts.minimax_tts.requests.post",
        lambda *args, **kwargs: fake_response,
    )

    with pytest.raises(RuntimeError, match="empty audio"):
        minimax_tts.text_to_speech("Hello")


@pytest.mark.unit
def test_minimax_tts_correct_request_params(minimax_tts, monkeypatch):
    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0] if args else kwargs.get("url")
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "data": {"audio": "4944330400", "status": 2},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }
        return resp

    monkeypatch.setattr("application.tts.minimax_tts.requests.post", fake_post)

    minimax_tts.text_to_speech("Test text")

    assert captured["url"] == "https://api.minimax.io/v1/t2a_v2"
    assert captured["headers"]["Authorization"] == "Bearer test-minimax-key"
    assert captured["json"]["model"] == "speech-2.8-hd"
    assert captured["json"]["text"] == "Test text"
    assert captured["json"]["voice_setting"]["voice_id"] == "English_Graceful_Lady"
