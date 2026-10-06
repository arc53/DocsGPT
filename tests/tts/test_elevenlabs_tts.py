import base64
import sys
from types import ModuleType

import pytest

from docsgpt.core.settings import Settings
from docsgpt.tts.elevenlabs import ElevenlabsTTS

DEFAULT_VOICE_ID = "nPczCjzI2devNBz1zQrb"


@pytest.fixture
def elevenlabs_client(monkeypatch):
    """Replace the ``elevenlabs`` SDK with a stub that records calls."""
    created = {}

    class DummyClient:
        def __init__(self, api_key):
            created["api_key"] = api_key
            self.convert_calls = []

            class TextToSpeech:
                def __init__(self, outer):
                    self._outer = outer

                def convert(self, *, voice_id, model_id, text, output_format):
                    self._outer.convert_calls.append(
                        {
                            "voice_id": voice_id,
                            "model_id": model_id,
                            "text": text,
                            "output_format": output_format,
                        }
                    )
                    yield b"chunk-one"
                    yield b"chunk-two"

            self.text_to_speech = TextToSpeech(self)

    client_module = ModuleType("elevenlabs.client")
    client_module.ElevenLabs = DummyClient
    package_module = ModuleType("elevenlabs")
    package_module.client = client_module

    monkeypatch.setitem(sys.modules, "elevenlabs", package_module)
    monkeypatch.setitem(sys.modules, "elevenlabs.client", client_module)
    return created


def _use_settings(monkeypatch):
    monkeypatch.setattr(
        "docsgpt.tts.elevenlabs.settings",
        Settings(_env_file=None, ELEVENLABS_API_KEY="api-key"),
    )


def test_elevenlabs_text_to_speech_monkeypatched_client(monkeypatch, elevenlabs_client):
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    _use_settings(monkeypatch)

    tts = ElevenlabsTTS()
    audio_base64, lang = tts.text_to_speech("Speak")

    assert elevenlabs_client["api_key"] == "api-key"
    assert tts.client.convert_calls == [
        {
            "voice_id": DEFAULT_VOICE_ID,
            "model_id": "eleven_multilingual_v2",
            "text": "Speak",
            "output_format": "mp3_44100_128",
        }
    ]
    assert lang == "en"
    assert base64.b64decode(audio_base64.encode()) == b"chunk-onechunk-two"


def test_elevenlabs_text_to_speech_uses_configured_voice(monkeypatch, elevenlabs_client):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "custom-voice-id")
    _use_settings(monkeypatch)

    tts = ElevenlabsTTS()
    tts.text_to_speech("Bonjour")

    assert tts.client.convert_calls[0]["voice_id"] == "custom-voice-id"
