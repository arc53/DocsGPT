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
        monkeypatch.setattr(base, "_embeddings_name_is_explicit", lambda: True)
        assert self._remote("granite-311m")._resolve_input_limit() == 32768
        # mpnet genuinely stops at 384; sending more is paid for and discarded.
        assert self._remote("all-mpnet-base-v2")._resolve_input_limit() == 384

    def test_default_model_name_lends_the_server_no_ceiling(self, monkeypatch):
        """An unset EMBEDDINGS_NAME describes nothing about the remote server.

        The name is only forwarded as the ``model`` field. Letting the
        settings default contribute mpnet's 384-token window would clip every
        chunk on a server that may well serve a 32k-context model.
        """
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
        monkeypatch.setattr(base, "_embeddings_name_is_explicit", lambda: False)
        assert self._remote("all-mpnet-base-v2")._resolve_input_limit() is None

    def test_explicit_setting_still_wins_over_an_unset_name(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 512)
        monkeypatch.setattr(base, "_embeddings_name_is_explicit", lambda: False)
        assert self._remote("all-mpnet-base-v2")._resolve_input_limit() == 512

    def test_unknown_model_stays_unlimited(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
        assert self._remote("some-org/mystery")._resolve_input_limit() is None

    def test_non_positive_setting_falls_through_to_the_registry(self, monkeypatch):
        from application.vectorstore import base

        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", 0)
        monkeypatch.setattr(base, "_embeddings_name_is_explicit", lambda: True)
        assert self._remote("granite-97m")._resolve_input_limit() == 32768

    def test_dimension_is_taken_from_the_registry(self):
        assert self._remote("granite-97m").dimension == 384
        assert self._remote("granite-311m").dimension == 768

    def test_unknown_model_dimension_is_probed_not_assumed(self):
        """The old hardcoded 768 made the probe below unreachable."""
        assert self._remote("some-org/mystery").dimension is None


class TestEmbeddingsNameIsExplicit:
    """Which names count as chosen decides whether a remote server inherits a
    context window it may not have.

    The tests above monkeypatch the predicate, so they cannot see it being
    wrong. These drive the real one.
    """

    def _default(self):
        from application.core.settings import Settings

        return Settings.model_fields["EMBEDDINGS_NAME"].default

    def test_the_default_name_is_not_a_choice(self, monkeypatch):
        """Every setup script has always written this value unconditionally.

        Reading it as deliberate lends the server mpnet's 384-token window and
        clips ~80% off every chunk, silently, on upgrade. ``model_fields_set``
        could not tell the difference: pydantic marks a field set for anything
        that reached it, ``.env`` included.
        """
        monkeypatch.setattr(base.settings, "EMBEDDINGS_NAME", self._default())
        assert base._embeddings_name_is_explicit() is False

    def test_a_different_name_is_a_choice(self, monkeypatch):
        monkeypatch.setattr(
            base.settings,
            "EMBEDDINGS_NAME",
            "ibm-granite/granite-embedding-311m-multilingual-r2",
        )
        assert base._embeddings_name_is_explicit() is True

    def test_dotenv_written_default_does_not_clip(self, monkeypatch):
        """End to end: the common upgrade path must send the full chunk."""
        monkeypatch.setattr(base.settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
        monkeypatch.setattr(base.settings, "EMBEDDINGS_NAME", self._default())
        captured = _capture_post(monkeypatch)

        long_text = " ".join(["word"] * 1000)
        emb = RemoteEmbeddings(api_url="http://embeddings", model_name=self._default())
        emb.embed_documents([long_text])

        assert captured["payload"]["input"][0] == long_text
