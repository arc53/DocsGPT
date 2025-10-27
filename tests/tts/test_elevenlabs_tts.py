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

    tts = ElevenlabsTTS()
    audio_base64, lang = tts.text_to_speech("Speak")

    assert created["api_key"] == "api-key"
    assert tts.client.convert_calls == [
        {
            "voice_id": "nPczCjzI2devNBz1zQrb",
            "model_id": "eleven_multilingual_v2",
            "text": "Speak",
            "output_format": "mp3_44100_128",
        }
    ]
    assert lang == "en"
    assert base64.b64decode(audio_base64.encode()) == b"chunk-onechunk-two"

