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

    def decode_with_offsets(self, ids):
        # One token per character, so each token starts where the last ended.
        return self.decode(ids), list(range(len(ids)))


@pytest.fixture(autouse=True)
def _clear_cache():
    tokenization.reset_cache()
    yield
    tokenization.reset_cache()


class TestSplittingPreservesText:
    """The property that protects every stored document."""

    @pytest.mark.parametrize("text", SAMPLES)
    def test_tiktoken_split_reassembles_exactly(self, text, monkeypatch):
        monkeypatch.setattr(tokenization, "get_encoding", _StubEncoding)
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
        monkeypatch.setattr(tokenization, "get_encoding", _StubEncoding)
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


class TestTiktokenSplitAgainstRealCl100k:
    """The stub above is one token per character, so it can never place a cut
    inside a character. Real cl100k can, and that is the case that corrupted
    text: decoding each window on its own turns a straddled multi-byte
    character into U+FFFD on both sides of the cut."""

    @pytest.fixture
    def real_counter(self):
        try:
            counter = TiktokenCounter()
            counter.count("probe")
        except Exception as exc:  # offline CI, same policy as the HF fixture
            pytest.skip(f"cl100k encoding unavailable: {exc}")
        return counter

    # 2000 is the shipped default max_tokens, 384 mpnet's window; the small
    # values place many more cuts per unit of text.
    @pytest.mark.parametrize("window", [1, 2, 3, 7, 128, 384, 2000])
    @pytest.mark.parametrize(
        "text",
        [
            "日本語のテキストです。絵文字も🎉あります。",
            "検索は自然言語でできます。" * 200,
            "Здравствуйте, как настроить аутентификацию?",
            "🎉🎊✨🚀🔥💡📚🧠" * 50,
            "Ünïcödé — em-dashes, curly “quotes”, and 日本語 text.",
        ],
        ids=["ja-short", "ja-long", "ru", "emoji", "mixed"],
    )
    def test_split_reassembles_exactly(self, real_counter, text, window):
        pieces = real_counter.split(text, window)
        assert "".join(pieces) == text

    @pytest.mark.parametrize("window", [1, 3, 128, 2000])
    def test_split_never_emits_a_replacement_character(self, real_counter, window):
        text = "検索は自然言語でできます。絵文字も🎉あります。" * 100
        assert "�" not in "".join(real_counter.split(text, window))

    def test_first_window_budget_is_honoured_and_lossless(self, real_counter):
        text = "日本語のテキストです。" * 50
        pieces = real_counter.split(text, 20, first_max_tokens=5)
        assert "".join(pieces) == text
        assert real_counter.count(pieces[0]) <= 5


class TestTiktokenCounterEdges:
    """The cl100k path is the fallback, so its edges matter as much."""

    @pytest.fixture
    def counter(self, monkeypatch):
        monkeypatch.setattr(tokenization, "get_encoding", _StubEncoding)
        return TiktokenCounter()

    def test_empty_text_counts_zero_and_splits_to_nothing(self, counter):
        assert counter.count("") == 0
        assert counter.split("", 10) == []

    def test_text_within_budget_is_returned_whole(self, counter):
        assert counter.split("abc", 10) == ["abc"]

    def test_first_window_can_be_smaller_than_the_rest(self, counter):
        """A header eats into the first chunk's budget only."""
        pieces = counter.split("abcdefghij", 4, first_max_tokens=2)
        assert pieces[0] == "ab"
        assert "".join(pieces) == "abcdefghij"


class TestCounterContract:
    def test_base_class_requires_an_implementation(self):
        base = tokenization.TokenCounter()
        with pytest.raises(NotImplementedError):
            base.count("x")
        with pytest.raises(NotImplementedError):
            base.split("x", 1)


class TestFallbackWhenTokenizerUnavailable:
    def test_load_failure_returns_none_rather_than_raising(self, monkeypatch, caplog):
        """Chunking must survive an offline host or a bad repo name."""
        import builtins

        real_import = builtins.__import__

        def boom(name, *args, **kwargs):
            if name == "tokenizers":
                raise ImportError("no tokenizers here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", boom)
        assert tokenization._load_hf_counter("some/repo") is None

    def test_selection_falls_back_to_cl100k_on_failure(self, monkeypatch):
        monkeypatch.setattr(tokenization, "_load_hf_counter", lambda repo: None)
        assert isinstance(get_token_counter("granite-97m"), TiktokenCounter)

    def test_reset_cache_forces_reselection(self, monkeypatch):
        first = get_token_counter("granite-311m")
        tokenization.reset_cache()
        monkeypatch.setattr(tokenization, "_load_hf_counter", lambda repo: None)
        assert get_token_counter("granite-311m") is not first


class TestOffsetsWithoutSpans:
    """Some tokenizers emit ``(0, 0)`` for specials or normalised-away chars.

    Those tokens consume budget but point at no text, so the splitter has to
    skip the window rather than emit an empty piece or lose the tail.
    """

    class _Encoded:
        def __init__(self, offsets):
            self.offsets = offsets
            self.ids = list(range(len(offsets)))

    class _Tokenizer:
        def __init__(self, offsets):
            self._offsets = offsets

        def encode(self, text, add_special_tokens=False):
            return TestOffsetsWithoutSpans._Encoded(self._offsets)

    def _counter(self, offsets):
        return HuggingFaceCounter(self._Tokenizer(offsets), "stub")

    def test_span_less_windows_are_skipped_not_emitted_empty(self):
        # Two real tokens, then a window of pure (0, 0) padding-like entries.
        counter = self._counter([(0, 2), (2, 4), (0, 0), (0, 0)])
        pieces = counter.split("abcd", 2)
        assert "" not in pieces
        assert "".join(pieces) == "abcd"

    def test_trailing_text_is_never_dropped(self):
        """Offsets that stop short of the string must not lose the remainder."""
        counter = self._counter([(0, 1), (1, 2), (2, 3)])
        pieces = counter.split("abcdef", 2)
        assert "".join(pieces) == "abcdef"

    def test_all_span_less_offsets_still_return_the_text(self):
        counter = self._counter([(0, 0), (0, 0), (0, 0)])
        assert "".join(counter.split("abc", 1)) == "abc"


class TestUnknownTokenCollapse:
    """A tokenizer that folds a long unbroken run into one ``[UNK]``.

    WordPiece gives up on any word longer than ``max_input_chars_per_word``
    and emits a single unknown token for it. Counting that as one token makes
    a base64 blob or a minified bundle look tiny, so the chunker never splits
    it and an oversized chunk reaches the embedding server.
    """

    class _CollapsingEncoding:
        """One token per whitespace-separated word, however long the word."""

        def __init__(self, text):
            self.ids = []
            self.offsets = []
            cursor = 0
            for word in text.split(" "):
                if word:
                    self.ids.append(0)
                    self.offsets.append((cursor, cursor + len(word)))
                cursor += len(word) + 1

    class _CollapsingTokenizer:
        def encode(self, text, add_special_tokens=False):
            return TestUnknownTokenCollapse._CollapsingEncoding(text)

    def _counter(self):
        return tokenization.HuggingFaceCounter(self._CollapsingTokenizer(), "stub")

    def test_long_unbroken_run_is_charged_by_its_span(self):
        counter = self._counter()
        assert counter.count("a" * 9000) > 100

    def test_ordinary_prose_is_unaffected(self):
        counter = self._counter()
        text = "the quick brown fox jumps over the lazy dog"
        assert counter.count(text) == 9

    def test_split_bounds_a_collapsed_run(self):
        counter = self._counter()
        text = "a" * 9000
        pieces = counter.split(text, 20)
        assert "".join(pieces) == text, "split must not lose or alter text"
        assert len(pieces) > 1, "a collapsed run must still be cut into pieces"
        assert all(counter.count(p) <= 20 for p in pieces)
