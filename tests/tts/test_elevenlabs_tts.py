import base64
import sys
from types import ModuleType, SimpleNamespace

from application.tts.elevenlabs import ElevenlabsTTS


def test_elevenlabs_text_to_speech_monkeypatched_client(monkeypatch):
    monkeypatch.setattr(
        "application.tts.elevenlabs.settings",
        SimpleNamespace(ELEVENLABS_API_KEY="api-key"),
    )

    created = {}

    class DummyClient:
        def __init__(self, api_key):
            created["api_key"] = api_key
            self.generate_calls = []

        def generate(self, *, text, model, voice):
            self.generate_calls.append({"text": text, "model": model, "voice": voice})
            yield b"chunk-one"
            yield b"chunk-two"

    client_module = ModuleType("elevenlabs.client")
    client_module.ElevenLabs = DummyClient
    package_module = ModuleType("elevenlabs")
    package_module.client = client_module

    monkeypatch.setitem(sys.modules, "elevenlabs", package_module)
    monkeypatch.setitem(sys.modules, "elevenlabs.client", client_module)

    tts = ElevenlabsTTS()
    audio_base64, lang = tts.text_to_speech("Speak")

    assert created["api_key"] == "api-key"
    assert tts.client.generate_calls == [
        {"text": "Speak", "model": "eleven_multilingual_v2", "voice": "Brian"}
    ]
    assert lang == "en"
    assert base64.b64decode(audio_base64.encode()) == b"chunk-onechunk-two"

