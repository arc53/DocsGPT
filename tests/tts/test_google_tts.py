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


def test_retries_throttling_and_dropped_connections(monkeypatch):
    sleeps = []
    monkeypatch.setattr(google_tts.time, "sleep", sleeps.append)
    replies = iter(
        [
            _Response([], status=429),
            google_tts.requests.ConnectionError("reset"),
            _Response([_audio_line(b"ok")]),
        ]
    )

    def fake_post(*a, **k):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    _patch_post(monkeypatch, fake_post)

    audio_base64, _ = GoogleTTS().text_to_speech("hello")

    assert base64.b64decode(audio_base64) == b"ok"
    assert sleeps == [0.5, 1.0]


def test_gives_up_after_the_last_retry(monkeypatch):
    monkeypatch.setattr(google_tts.time, "sleep", lambda s: None)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _Response([], status=503)

    _patch_post(monkeypatch, fake_post)

    with pytest.raises(google_tts.requests.HTTPError):
        GoogleTTS().text_to_speech("hello")
    assert len(calls) == len(google_tts.RETRY_BACKOFF_SECONDS) + 1


def test_retries_share_the_deadline(monkeypatch):
    now = [0.0]
    timeouts = []
    monkeypatch.setattr(google_tts.time, "monotonic", lambda: now[0])

    def fake_sleep(seconds):
        now[0] += seconds

    def fake_post(*a, timeout, **k):
        timeouts.append(timeout)
        now[0] += timeout
        raise google_tts.requests.Timeout("slow")

    monkeypatch.setattr(google_tts.time, "sleep", fake_sleep)
    _patch_post(monkeypatch, fake_post)

    with pytest.raises((TimeoutError, google_tts.requests.Timeout)):
        GoogleTTS().text_to_speech("hello")
    assert now[0] <= google_tts.DEADLINE_SECONDS
    assert timeouts[-1] < google_tts.TIMEOUT_SECONDS


def test_text_to_speech_raises_on_empty_text():
    with pytest.raises(ValueError):
        GoogleTTS().text_to_speech("  ")
