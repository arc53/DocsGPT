"""Tests for the ``EMBEDDINGS_MAX_INPUT_TOKENS`` truncation net.

The remote embeddings server (e.g. llama.cpp) hard-rejects any single input
larger than its physical batch size with a 500. When the setting is
configured, ``RemoteEmbeddings`` clips each input to that many tokens before
the request; the overflow is dropped (lossy by design).
"""

from unittest.mock import MagicMock

from application.core.settings import settings
from application.utils import get_encoding
from application.vectorstore import base
from application.vectorstore.base import RemoteEmbeddings


def _capture_post(monkeypatch):
    """Patch ``requests.post`` and return a dict recording the sent payload."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        n_inputs = len(json["input"]) if isinstance(json["input"], list) else 1
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "data": [{"index": i, "embedding": [0.0]} for i in range(n_inputs)]
        }
        return resp

    monkeypatch.setattr(base.requests, "post", fake_post)
    return captured


def test_truncates_oversized_input_to_limit(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 10)
    captured = _capture_post(monkeypatch)
    enc = get_encoding()

    long_text = " ".join(["word"] * 100)  # ~100 tokens, far over the limit of 10
    emb = RemoteEmbeddings(api_url="https://example.test", model_name="m")
    emb.embed_documents([long_text])

    sent = captured["payload"]["input"][0]
    assert sent == enc.decode(enc.encode(long_text)[:10])
    assert len(enc.encode(sent)) <= 10


def test_short_input_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 10)
    captured = _capture_post(monkeypatch)

    short_text = "hello world"
    emb = RemoteEmbeddings(api_url="https://example.test", model_name="m")
    emb.embed_documents([short_text])

    assert captured["payload"]["input"][0] == short_text


def test_no_truncation_when_setting_unset(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
    captured = _capture_post(monkeypatch)
    enc = get_encoding()

    long_text = " ".join(["word"] * 100)
    emb = RemoteEmbeddings(api_url="https://example.test", model_name="m")
    emb.embed_documents([long_text])

    sent = captured["payload"]["input"][0]
    assert sent == long_text
    assert len(enc.encode(sent)) > 10


def test_query_path_is_truncated(monkeypatch):
    """``embed_query`` passes a bare string through the same net."""
    monkeypatch.setattr(settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 10)
    captured = _capture_post(monkeypatch)
    enc = get_encoding()

    long_text = " ".join(["word"] * 100)
    emb = RemoteEmbeddings(api_url="https://example.test", model_name="m")
    emb.embed_query(long_text)

    sent = captured["payload"]["input"]
    assert sent == enc.decode(enc.encode(long_text)[:10])
