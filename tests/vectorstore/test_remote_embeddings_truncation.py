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


class TestInputLimitResolution:
    """The cap falls back to the model's own context window."""

    def _remote(self, model_name):
        from application.vectorstore.base import RemoteEmbeddings

        return RemoteEmbeddings(
            api_url="http://embeddings", model_name=model_name, api_key=None
        )

    def test_explicit_setting_wins(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 123)
        assert self._remote("granite-311m")._resolve_input_limit() == 123

    def test_registered_model_supplies_its_own_ceiling(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
        assert self._remote("granite-311m")._resolve_input_limit() == 32768
        # mpnet genuinely stops at 384; sending more is paid for and discarded.
        assert self._remote("all-mpnet-base-v2")._resolve_input_limit() == 384

    def test_unknown_model_stays_unlimited(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
        assert self._remote("some-org/mystery")._resolve_input_limit() is None

    def test_non_positive_setting_falls_through_to_the_registry(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 0)
        assert self._remote("granite-97m")._resolve_input_limit() == 32768

    def test_dimension_is_taken_from_the_registry(self):
        assert self._remote("granite-97m").dimension == 384
        assert self._remote("granite-311m").dimension == 768

    def test_unknown_model_dimension_is_probed_not_assumed(self):
        """The old hardcoded 768 made the probe below unreachable."""
        assert self._remote("some-org/mystery").dimension is None
