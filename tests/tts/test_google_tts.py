import base64

from application.tts.google_tts import GoogleTTS


def test_google_tts_text_to_speech(monkeypatch):
    captured = {}

    class DummyGTTS:
        def __init__(self, *, text, lang, slow):
            captured["args"] = {"text": text, "lang": lang, "slow": slow}

        def write_to_fp(self, fp):
            fp.write(b"synthetic-audio")

    monkeypatch.setattr("application.tts.google_tts.gTTS", DummyGTTS)

    tts = GoogleTTS()
    audio_base64, lang = tts.text_to_speech("hello world")

    assert captured["args"] == {"text": "hello world", "lang": "en", "slow": False}
    assert lang == "en"
    assert base64.b64decode(audio_base64.encode()) == b"synthetic-audio"

