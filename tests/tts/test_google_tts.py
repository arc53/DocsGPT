import base64
import json
import urllib.parse

import pytest

from docsgpt.tts import google_tts
from docsgpt.tts.google_tts import GoogleTTS, _rpc_body, _split_text


class _Response:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise google_tts.requests.HTTPError(f"status {self.status_code}")

    def iter_lines(self):
        return iter(self._lines)


def _patch_post(monkeypatch, fake_post):
    monkeypatch.setattr(google_tts.requests.Session, "post", lambda self, *a, **k: fake_post(*a, **k))


def _audio_line(audio: bytes) -> bytes:
    payload = json.dumps([base64.b64encode(audio).decode()])
    return json.dumps([["wrb.fr", "jQ1olc", payload, None, None, None, "generic"]]).encode()


def test_text_to_speech_joins_audio_of_every_chunk(monkeypatch):
    sent = []
    parts = iter([b"one-", b"two"])

    def fake_post(url, data, headers, timeout):
        sent.append({"url": url, "data": data, "timeout": timeout})
        return _Response([b")]}'", b"", _audio_line(next(parts))])

    _patch_post(monkeypatch, fake_post)
    text = "First sentence here.\n" + "word " * 18

    audio_base64, lang = GoogleTTS().text_to_speech(text)

    assert lang == "en"
    assert base64.b64decode(audio_base64) == b"one-two"
    assert len(sent) == 2
    assert sent[0]["url"] == "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
    assert sent[0]["timeout"] == google_tts.TIMEOUT_SECONDS


def test_rpc_body_matches_translate_batchexecute_shape():
    body = _rpc_body('say "hi"', "en")

    assert body.startswith("f.req=") and body.endswith("&")
    rpc = json.loads(urllib.parse.unquote(body[len("f.req="):-1]))
    assert rpc[0][0][0] == "jQ1olc"
    assert json.loads(rpc[0][0][1]) == ['say "hi"', "en", None, "null"]


def test_split_text_keeps_chunks_under_limit_and_loses_no_words():
    text = "Alpha beta gamma. " * 20 + "x" * 250

    chunks = _split_text(text, 100)

    assert all(0 < len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_split_text_prefers_sentence_ends():
    chunks = _split_text("A short one. " + "word " * 30, 100)

    assert chunks[0] == "A short one."


def test_split_text_drops_blank_input():
    assert _split_text("   \n ", 100) == []


def test_text_to_speech_raises_without_audio(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **k: _Response([b")]}'", b"[]"]))

    with pytest.raises(RuntimeError, match="no audio"):
        GoogleTTS().text_to_speech("hello")


def test_session_retries_rate_limits_and_server_errors(monkeypatch):
    mounted = {}
    original_mount = google_tts.requests.Session.mount

    def spy_mount(self, prefix, adapter):
        mounted[prefix] = adapter
        return original_mount(self, prefix, adapter)

    monkeypatch.setattr(google_tts.requests.Session, "mount", spy_mount)
    _patch_post(monkeypatch, lambda *a, **k: _Response([_audio_line(b"ok")]))

    GoogleTTS().text_to_speech("hello")

    retry = mounted["https://"].max_retries
    assert retry.total == 3
    assert 429 in retry.status_forcelist and 503 in retry.status_forcelist
    assert "POST" in retry.allowed_methods


def test_text_to_speech_raises_on_empty_text():
    with pytest.raises(ValueError):
        GoogleTTS().text_to_speech("  ")
