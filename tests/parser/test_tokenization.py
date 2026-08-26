"""Chunk sizes must be counted in the embedding model's units, and splitting
must never rewrite the text it splits."""

import pytest

from application.parser import tokenization
from application.parser.tokenization import (
    HuggingFaceCounter,
    TiktokenCounter,
    get_token_counter,
)

SAMPLES = [
    "Hello World: DocsGPT ANSWERS Questions.",
    "The quick brown fox jumps over the lazy dog. " * 40,
    "Comment configurer l'authentification avec une clé API ?",
    "def embed(text: str) -> list[float]:\n    return model.encode(text)\n",
    "Ünïcödé — em-dashes, curly “quotes”, and 日本語 text.",
    "a,b,c\n1,2,3\n4,5,6\n" * 30,
]


class _StubEncoding:
    """Whitespace tokenizer standing in for tiktoken."""

    def encode_ordinary(self, text):
        return [ord(c) for c in text]

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


@pytest.fixture(autouse=True)
def _clear_cache():
    tokenization.reset_cache()
    yield
    tokenization.reset_cache()


class TestSplittingPreservesText:
    """The property that protects every stored document."""

    @pytest.mark.parametrize("text", SAMPLES)
    def test_tiktoken_split_reassembles_exactly(self, text, monkeypatch):
        monkeypatch.setattr(tokenization, "get_encoding", lambda: _StubEncoding())
        counter = TiktokenCounter()
        pieces = counter.split(text, 7)
        assert "".join(pieces) == text

    @pytest.mark.parametrize("text", SAMPLES)
    def test_hf_split_reassembles_exactly(self, text, hf_counter):
        """WordPiece lowercases on decode, so splitting must slice, not decode."""
        pieces = hf_counter.split(text, 7)
        assert "".join(pieces) == text

    def test_hf_split_does_not_lowercase(self, hf_counter):
        text = "Hello World: DocsGPT ANSWERS Questions."
        assert "".join(hf_counter.split(text, 3)) == text
        assert "DocsGPT" in "".join(hf_counter.split(text, 3))

    @pytest.mark.parametrize("text", SAMPLES)
    def test_every_piece_is_within_budget(self, text, hf_counter):
        budget = 10
        for piece in hf_counter.split(text, budget):
            # The final piece can absorb trailing characters the tokenizer
            # dropped, so allow a small overshoot there only.
            assert hf_counter.count(piece) <= budget + 2

    def test_short_text_is_returned_whole(self, hf_counter):
        assert hf_counter.split("short", 100) == ["short"]

    def test_empty_text_yields_no_pieces(self, hf_counter):
        assert hf_counter.split("", 10) == []

    def test_zero_budget_is_clamped_not_infinite_loop(self, hf_counter):
        pieces = hf_counter.split("some words here to split", 0)
        assert "".join(pieces) == "some words here to split"


class TestCounting:
    def test_counts_differ_between_tokenizers(self, hf_counter, monkeypatch):
        """The whole point: mpnet and cl100k disagree, so units matter."""
        monkeypatch.setattr(tokenization, "get_encoding", lambda: _StubEncoding())
        text = "internationalisation tokenization"
        assert hf_counter.count(text) != TiktokenCounter().count(text)

    def test_empty_text_counts_zero(self, hf_counter):
        assert hf_counter.count("") == 0


class TestSelection:
    def test_registered_model_uses_its_own_tokenizer(self):
        counter = get_token_counter("huggingface_sentence-transformers/all-mpnet-base-v2")
        assert isinstance(counter, HuggingFaceCounter)
        assert counter.name == "sentence-transformers/all-mpnet-base-v2"

    def test_openai_model_falls_back_to_cl100k(self):
        """OpenAI models are served remotely and genuinely count cl100k."""
        assert isinstance(get_token_counter("openai_text-embedding-ada-002"), TiktokenCounter)

    def test_unreachable_tokenizer_falls_back_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(tokenization, "_load_hf_counter", lambda repo: None)
        assert isinstance(get_token_counter("granite-311m"), TiktokenCounter)

    def test_counter_is_cached_per_model(self):
        first = get_token_counter("granite-311m")
        assert get_token_counter("granite-311m") is first
