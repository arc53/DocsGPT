"""Offline verification: every check must pass, docling only when installed."""

import sys
import types
from unittest.mock import patch

from docsgpt.scripts import verify_offline


def _fake_tiktoken(monkeypatch):
    module = types.ModuleType("tiktoken")
    module.get_encoding = lambda name: types.SimpleNamespace(encode=lambda text: [1, 2])
    monkeypatch.setitem(sys.modules, "tiktoken", module)


class TestVerify:
    def test_passes_when_every_check_passes(self, monkeypatch, capsys):
        _fake_tiktoken(monkeypatch)
        counter = types.SimpleNamespace(name="org/model", count=lambda text: 4)
        with patch("docsgpt.parser.tokenization.get_token_counter", return_value=counter), \
                patch("docsgpt.vectorstore.embeddings_local.EmbeddingsWrapper") as wrapper, \
                patch.object(verify_offline, "is_available", return_value=False):
            wrapper.return_value.embed_query.return_value = [0.0] * 768
            assert verify_offline.verify(["ibm-granite/granite-embedding-311m-multilingual-r2"]) is True
        out = capsys.readouterr().out
        assert "ok    tiktoken cl100k_base" in out
        assert "skip  docling" in out

    def test_fails_when_the_tokenizer_fell_back_to_cl100k(self, monkeypatch, capsys):
        """A cache miss makes chunking silently use cl100k; that is a failed check."""
        _fake_tiktoken(monkeypatch)
        counter = types.SimpleNamespace(name="cl100k_base", count=lambda text: 4)
        with patch("docsgpt.parser.tokenization.get_token_counter", return_value=counter), \
                patch("docsgpt.vectorstore.embeddings_local.EmbeddingsWrapper") as wrapper, \
                patch.object(verify_offline, "is_available", return_value=False):
            wrapper.return_value.embed_query.return_value = [0.0] * 768
            assert verify_offline.verify(["ibm-granite/granite-embedding-311m-multilingual-r2"]) is False
        assert "FAIL  tokenizer" in capsys.readouterr().out

    def test_runs_the_docling_check_when_installed(self, monkeypatch):
        _fake_tiktoken(monkeypatch)
        with patch.object(verify_offline, "is_available", return_value=True), \
                patch.object(verify_offline, "_docling_check", return_value="models from /app/models/docling") as check:
            assert verify_offline.verify([]) is True
        check.assert_called_once()

    def test_remote_models_are_skipped(self, monkeypatch, capsys):
        _fake_tiktoken(monkeypatch)
        with patch.object(verify_offline, "is_available", return_value=False):
            assert verify_offline.verify(["openai_text-embedding-ada-002"]) is True
        assert "skip  openai_text-embedding-ada-002" in capsys.readouterr().out
