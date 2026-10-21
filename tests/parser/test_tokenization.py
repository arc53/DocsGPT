"""Chunk sizes must be counted in the embedding model's units, and splitting
must never rewrite the text it splits."""

import sys
import types
import unicodedata

import pytest

from docsgpt.parser import tokenization
from docsgpt.parser.tokenization import (
    HuggingFaceCounter,
    TiktokenCounter,
    get_token_counter,
    split_to_token_limit,
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


class _RecordingEncoding:
    """Wraps a tiktoken-like encoding and records how much each call is handed.

    #3130: one ``encode_ordinary`` over a whole document materialises per-token
    data for all of it at once, so the size of every single call is what bounds
    the worker's peak memory.
    """

    def __init__(self, inner):
        self._inner = inner
        self.encode_lengths = []
        self.decode_lengths = []

    def encode_ordinary(self, text):
        self.encode_lengths.append(len(text))
        return self._inner.encode_ordinary(text)

    def decode(self, ids):
        return self._inner.decode(ids)

    def decode_with_offsets(self, ids):
        self.decode_lengths.append(len(ids))
        return self._inner.decode_with_offsets(ids)


class _CharEncoded:
    def __init__(self, offsets):
        self.offsets = offsets
        self.ids = list(range(len(offsets)))


class _CharTokenizer:
    """Fake HF tokenizer: one token per character, with true offsets.

    With ``skip_whitespace`` whitespace yields no token at all, the way
    WordPiece's pre-tokenizer drops it, so a long blank run weighs nothing.
    """

    def __init__(self, skip_whitespace=False):
        self.skip_whitespace = skip_whitespace
        self.encode_lengths = []

    def encode(self, text, add_special_tokens=False):
        self.encode_lengths.append(len(text))
        return _CharEncoded(
            [(i, i + 1) for i, c in enumerate(text) if not (self.skip_whitespace and c.isspace())]
        )


class _RecordingTokenizer:
    """Wraps a real HF tokenizer and records the length of every encode."""

    def __init__(self, inner):
        self._inner = inner
        self.encode_lengths = []

    def encode(self, text, add_special_tokens=False):
        self.encode_lengths.append(len(text))
        return self._inner.encode(text, add_special_tokens=add_special_tokens)


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

    def test_verified_split_empty_text(self, monkeypatch):
        monkeypatch.setattr(tokenization, "get_encoding", _StubEncoding)
        assert split_to_token_limit(TiktokenCounter(), "", 10) == []

    def test_verified_split_rejects_unsplittable_character(self):
        class ImpossibleCounter:
            count = staticmethod(lambda text: 2)
            split = staticmethod(lambda text, limit: [text])

        with pytest.raises(ValueError, match="cannot split"):
            split_to_token_limit(ImpossibleCounter(), "x", 1)

    def test_verified_first_window_recovers_if_splitter_drops_text(self):
        class DroppingFirstCounter:
            count = staticmethod(len)

            @staticmethod
            def split(text, limit, first_max_tokens=None):
                if first_max_tokens is not None:
                    return []
                return [text[i : i + limit] for i in range(0, len(text), limit)]

        pieces = split_to_token_limit(
            DroppingFirstCounter(), "abcdef", 4, first_max_tokens=2
        )
        assert "".join(pieces) == "abcdef"
        assert all(len(piece) <= 2 for piece in pieces)


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


class TestTokenizerFile:
    """The chunker's tokenizer must come from the hub cache without a network round trip."""

    def test_cache_hit_makes_no_online_call(self, monkeypatch):
        calls = []

        def fake_download(repo, filename, local_files_only=False, cache_dir=None):
            calls.append(local_files_only)
            return "/cache/tokenizer.json"

        fake_hub = types.ModuleType("huggingface_hub")
        fake_hub.hf_hub_download = fake_download
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
        assert tokenization._tokenizer_file("org/model") == "/cache/tokenizer.json"
        assert calls == [True]

    def test_cache_miss_falls_back_to_online(self, monkeypatch):
        calls = []

        def fake_download(repo, filename, local_files_only=False, cache_dir=None):
            calls.append(local_files_only)
            if local_files_only:
                raise FileNotFoundError("not cached")
            return "/downloaded/tokenizer.json"

        fake_hub = types.ModuleType("huggingface_hub")
        fake_hub.hf_hub_download = fake_download
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
        assert tokenization._tokenizer_file("org/model") == "/downloaded/tokenizer.json"
        assert calls == [True, False]

    def test_reads_the_embedding_model_cache(self, monkeypatch):
        """FastEmbed's snapshot already holds tokenizer.json; a second cache downloads it again."""
        cache_dirs = []

        def fake_download(repo, filename, local_files_only=False, cache_dir=None):
            cache_dirs.append(cache_dir)
            if local_files_only:
                raise FileNotFoundError("not cached")
            return "/models/tokenizer.json"

        fake_hub = types.ModuleType("huggingface_hub")
        fake_hub.hf_hub_download = fake_download
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
        monkeypatch.setattr(tokenization.settings, "EMBEDDINGS_CACHE_DIR", "/models")
        tokenization._tokenizer_file("org/model")
        assert cache_dirs == ["/models", "/models"]


# ---------------------------------------------------------------------------
# #3130: bounded per-call tokenization.
#
# Ingesting one 80 MiB Chinese .txt peaked the worker at 10.3 GiB, roughly
# 180-430 bytes of RAM per character, because every count and split handed the
# whole document to a single encode. The counters now walk the text in windows
# of ``tokenization._WINDOW_CHARS`` characters, so no tokenizer call sees more
# than ``2 * _WINDOW_CHARS`` of it. The window is read at call time, which lets
# these tests shrink it and exercise many seams on small inputs.
# ---------------------------------------------------------------------------

_SMALL_WINDOW = 256

# Mixed lines of English and unbroken CJK: the shape of the #3130 document.
_MIXED = ("The quick brown fox jumps over the lazy dog.\n" "検索は自然言語でできます。絵文字も🎉あります。\n") * 120

_GLUE_CATEGORIES = {"Mn", "Mc", "Me", "Cf"}


def _is_glue(char):
    """Characters a cut must not land in front of: they attach to the previous one."""
    code = ord(char)
    return (
        unicodedata.category(char) in _GLUE_CATEGORIES
        or 0xD800 <= code <= 0xDFFF
        or 0x1F3FB <= code <= 0x1F3FF
    )


def _shrink_window(monkeypatch, size):
    # ``raising=False`` so code without the constant fails on the behaviour
    # under test rather than on the setattr itself.
    monkeypatch.setattr(tokenization, "_WINDOW_CHARS", size, raising=False)


def _real_cl100k():
    try:
        encoding = tokenization.get_encoding()
        encoding.encode_ordinary("probe")
    except Exception as exc:  # offline CI, same policy as the HF fixture
        pytest.skip(f"cl100k encoding unavailable: {exc}")
    return encoding


class TestEncodeCallsAreBounded:
    """The #3130 regression: no single tokenizer call sees the whole document."""

    def _tiktoken(self, monkeypatch):
        encoding = _RecordingEncoding(_StubEncoding())
        monkeypatch.setattr(tokenization, "get_encoding", lambda: encoding)
        return TiktokenCounter(), encoding

    def test_text_is_many_windows_long(self):
        assert len(_MIXED) >= 20 * _SMALL_WINDOW

    def test_tiktoken_count_is_windowed(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        counter, encoding = self._tiktoken(monkeypatch)
        assert counter.count(_MIXED) == len(_MIXED)
        assert max(encoding.encode_lengths) <= 2 * _SMALL_WINDOW

    def test_tiktoken_split_is_windowed_and_lossless(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        counter, encoding = self._tiktoken(monkeypatch)
        pieces = counter.split(_MIXED, 40)
        assert "".join(pieces) == _MIXED
        assert all(len(piece) <= 40 for piece in pieces)
        assert max(encoding.encode_lengths) <= 2 * _SMALL_WINDOW
        assert max(encoding.decode_lengths) <= 2 * _SMALL_WINDOW

    def test_hf_count_is_windowed(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        tokenizer = _CharTokenizer()
        counter = HuggingFaceCounter(tokenizer, "spy")
        assert counter.count(_MIXED) == len(_MIXED)
        assert max(tokenizer.encode_lengths) <= 2 * _SMALL_WINDOW

    def test_hf_split_is_windowed_and_lossless(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        tokenizer = _CharTokenizer()
        counter = HuggingFaceCounter(tokenizer, "spy")
        pieces = counter.split(_MIXED, 40)
        assert "".join(pieces) == _MIXED
        assert all(len(piece) <= 40 for piece in pieces)
        assert max(tokenizer.encode_lengths) <= 2 * _SMALL_WINDOW


class TestHuggingFaceSplitEncodesOnce:
    """Splitting used to encode for offsets and then again inside ``count``,
    holding two full encodings of the same text alive at once."""

    def test_over_budget_text_is_encoded_once(self):
        tokenizer = _CharTokenizer()
        counter = HuggingFaceCounter(tokenizer, "spy")
        text = "abcdefghij" * 10
        pieces = counter.split(text, 10)
        assert "".join(pieces) == text
        assert len(tokenizer.encode_lengths) == 1

    def test_within_budget_text_is_encoded_once(self):
        tokenizer = _CharTokenizer()
        counter = HuggingFaceCounter(tokenizer, "spy")
        assert counter.split("short", 100) == ["short"]
        assert len(tokenizer.encode_lengths) == 1


class TestZeroTokenRunsAreCarried:
    """A long blank run weighs nothing, so a segment holding only it never
    splits. The carried remainder must still be capped, or the next encode
    grows with the run and the bound is lost (and the work goes quadratic)."""

    def test_whitespace_run_keeps_the_bound_and_stays_linear(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        tokenizer = _CharTokenizer(skip_whitespace=True)
        counter = HuggingFaceCounter(tokenizer, "spy")
        text = ("  \n\t " * 260 + "alpha beta gamma") * 10
        assert len(text) >= 50 * _SMALL_WINDOW
        pieces = counter.split(text, 3)
        assert "".join(pieces) == text
        assert max(tokenizer.encode_lengths) <= 2 * _SMALL_WINDOW
        assert len(tokenizer.encode_lengths) <= 4 * len(text) // _SMALL_WINDOW + 4

    def test_whitespace_run_counts_only_the_words(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        tokenizer = _CharTokenizer(skip_whitespace=True)
        counter = HuggingFaceCounter(tokenizer, "spy")
        text = " " * (20 * _SMALL_WINDOW) + "word"
        assert counter.count(text) == 4
        assert max(tokenizer.encode_lengths) <= 2 * _SMALL_WINDOW

    def test_blank_run_within_budget_comes_back_whole(self):
        """Within one window a text that fits is returned as is; the character
        cap is only for pieces a split actually produced."""
        counter = HuggingFaceCounter(_CharTokenizer(skip_whitespace=True), "spy")
        text = "a" + " " * 200 + "b"
        assert counter.split(text, 5) == [text]


class TestTextWindows:
    """Where the windows fall decides whether a seam changes tokenization.

    Cuts prefer places every supported pre-tokenizer already breaks at, so a
    windowed count equals the one-shot count on ordinary prose.
    """

    @staticmethod
    def _windows(text, size):
        return list(tokenization._text_windows(text, size))

    @staticmethod
    def _assert_tiles(text, windows, size):
        assert windows[0][0] == 0
        assert windows[-1][1] == len(text)
        for (_, end), (start, _) in zip(windows, windows[1:]):
            assert end == start
        for start, end in windows:
            assert 0 < end - start <= size

    def test_short_text_is_one_window(self):
        assert self._windows("abc", 10) == [(0, 3)]
        assert self._windows("a" * 10, 10) == [(0, 10)]

    @pytest.mark.parametrize(
        "text",
        [_MIXED, "a" * 1000, " " * 1000, "x\n" * 500, "é" * 500, "́" * 1000],
        ids=["mixed", "no-break", "blank", "newlines", "combining", "all-glue"],
    )
    def test_windows_tile_the_text(self, text):
        windows = self._windows(text, 64)
        self._assert_tiles(text, windows, 64)
        for start, end in windows[:-1]:
            assert end - start > 32, "a non-final window covers more than half the size"

    def test_cuts_after_a_newline_before_text(self):
        """cl100k and whitespace pre-tokenizers end a pretoken at ``\\n`` + non-space."""
        text = "a" * 12 + "\n" + "b" * 30
        assert self._windows(text, 20)[0] == (0, 13)

    def test_skips_a_newline_followed_by_whitespace(self):
        """``\\n `` belongs to one cl100k ``\\s+`` run, so cutting there changes a token."""
        text = "a" * 12 + "\nb" + "aaa" + "\n " + "c" * 30
        assert self._windows(text, 20)[0] == (0, 13)

    def test_newline_beats_a_later_space(self):
        text = "a" * 11 + "\n" + "bb cc" + "d" * 30
        assert self._windows(text, 20)[0] == (0, 12)

    def test_cuts_before_a_space(self):
        """`` word`` is one token in cl100k and SentencePiece; cutting after the
        space would split it."""
        text = "a" * 14 + " " + "b" * 30
        windows = self._windows(text, 20)
        assert windows[0] == (0, 14)
        assert text[windows[0][1]] == " "

    def test_space_must_follow_text(self):
        text = "a" * 13 + "  " + "b" * 30
        assert self._windows(text, 20)[0] == (0, 13)

    def test_space_exactly_at_half_is_not_a_cut(self):
        """A cut at ``size // 2`` would leave a window no longer than half."""
        text = "a" * 32 + " " + "a" * 100
        (_, end), *_ = self._windows(text, 64)
        assert end > 32

    # Combining acute, ZWJ, VS16, a lone surrogate, a Devanagari vowel sign
    # (a spacing mark, Mc) and an emoji skin-tone modifier.
    @pytest.mark.parametrize("glue", ["́", "‍", "️", "\ud800", "ि", "\U0001F3FD"])
    def test_hard_cut_never_lands_before_glue(self, glue):
        text = "x" * 20 + glue + "y" * 40
        windows = self._windows(text, 20)
        assert windows[0] == (0, 19)
        self._assert_tiles(text, windows, 20)

    def test_hard_cut_steps_back_over_a_glue_run(self):
        text = "x" * 17 + "́" * 4 + "y" * 40
        assert self._windows(text, 20)[0] == (0, 16)

    def test_all_glue_back_half_takes_the_hard_cut(self):
        text = "x" * 5 + "́" * 100
        windows = self._windows(text, 20)
        assert windows[0] == (0, 20)
        self._assert_tiles(text, windows, 20)

    @pytest.mark.parametrize(
        "text",
        ["é́" * 400, "👨‍👩‍👧‍👦🏳️‍🌈" * 200, "a⃝" * 500, "किताबें" * 200, "👍🏽👋🏿" * 300],
        ids=["combining", "zwj", "enclosing", "devanagari", "skin-tone"],
    )
    def test_no_cut_lands_before_glue(self, text):
        windows = self._windows(text, 16)
        self._assert_tiles(text, windows, 16)
        for _, end in windows[:-1]:
            assert not _is_glue(text[end])


_SEAM_CORPORA = {
    "prose": (
        "DocsGPT answers questions about your documents, citing its sources. "
        "Upload a file and ask away.\n"
        "Retrieval runs before generation; the model sees only the top chunks.\n\n"
    )
    * 40,
    "cjk": "検索は自然言語でできます。絵文字も含まれています。日本語のテキストです。" * 120,
    "zwj": "👨‍👩‍👧‍👦👩🏽‍💻🏳️‍🌈" * 300,
    "combining": "café résumé naïve ééé\n" * 150,
    "crlf": "line one\r\nline two\n\n\n  indented line\r\n\r\n\n" * 100,
    # No whitespace at all, so every seam is a hard cut. Punctuated rather than
    # one unbroken word: a run WordPiece collapses to ``[UNK]`` already
    # overshoots small budgets on main (see TestUnknownTokenCollapse).
    "one-line": "https://docs.example.com/guides/setup_v2.html?lang=en&page=3#install;" * 80,
}

_SEAM_WINDOW = 512


class TestSeamFidelity:
    """Real tokenizers at a small window: many seams, nothing lost or rewritten."""

    @pytest.fixture
    def cl100k_counter(self, monkeypatch):
        encoding = _RecordingEncoding(_real_cl100k())
        monkeypatch.setattr(tokenization, "get_encoding", lambda: encoding)
        return TiktokenCounter(), encoding

    @pytest.fixture
    def mpnet_counter(self, hf_counter):
        tokenizer = _RecordingTokenizer(hf_counter._tokenizer)
        return HuggingFaceCounter(tokenizer, hf_counter.name), tokenizer

    @staticmethod
    def _check(counter, encode_lengths, text, budget, monkeypatch):
        assert len(text) > 4 * _SEAM_WINDOW
        _shrink_window(monkeypatch, _SEAM_WINDOW)
        pieces = counter.split(text, budget)
        assert max(encode_lengths) <= 2 * _SEAM_WINDOW
        assert "".join(pieces) == text
        assert "" not in pieces
        assert all("�" not in piece for piece in pieces)
        # Weigh each piece one-shot, the way the embedding server will.
        _shrink_window(monkeypatch, 10**9)
        for piece in pieces:
            assert counter.count(piece) <= budget + 2

    @pytest.mark.parametrize("budget", [7, 64])
    @pytest.mark.parametrize("name", list(_SEAM_CORPORA))
    def test_cl100k(self, cl100k_counter, name, budget, monkeypatch):
        counter, encoding = cl100k_counter
        self._check(counter, encoding.encode_lengths, _SEAM_CORPORA[name], budget, monkeypatch)

    @pytest.mark.parametrize("budget", [7, 64])
    @pytest.mark.parametrize("name", list(_SEAM_CORPORA))
    def test_mpnet(self, mpnet_counter, name, budget, monkeypatch):
        counter, tokenizer = mpnet_counter
        self._check(counter, tokenizer.encode_lengths, _SEAM_CORPORA[name], budget, monkeypatch)


class TestWindowedCountIsExactOnProse:
    """Newline cuts fall where every pre-tokenizer already breaks, so a
    windowed count of newline-separated prose equals the one-shot count."""

    TEXT = "\n".join(
        f"Sentence {i} explains how chunk {i % 7} is retrieved, ranked and cited." for i in range(200)
    )

    def test_cl100k(self, monkeypatch):
        encoding = _real_cl100k()
        one_shot = len(encoding.encode_ordinary(self.TEXT))
        _shrink_window(monkeypatch, _SEAM_WINDOW)
        assert len(self.TEXT) > 10 * _SEAM_WINDOW
        assert TiktokenCounter().count(self.TEXT) == one_shot

    def test_mpnet(self, hf_counter, monkeypatch):
        one_shot = hf_counter.count(self.TEXT)
        _shrink_window(monkeypatch, _SEAM_WINDOW)
        assert hf_counter.count(self.TEXT) == one_shot


class TestFirstBudgetAcrossWindows:
    """The header budget applies to the first piece even when the first
    window fits whole and is carried into the next one."""

    FIRST, REST = 300, 1000

    def _text(self):
        return "word " * (2 * _SMALL_WINDOW)

    def test_tiktoken(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        encoding = _RecordingEncoding(_StubEncoding())
        monkeypatch.setattr(tokenization, "get_encoding", lambda: encoding)
        text = self._text()
        pieces = TiktokenCounter().split(text, self.REST, first_max_tokens=self.FIRST)
        assert "".join(pieces) == text
        assert len(pieces[0]) <= self.FIRST
        assert all(len(piece) <= self.REST for piece in pieces)

    def test_hf(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        counter = HuggingFaceCounter(_CharTokenizer(), "spy")
        text = self._text()
        pieces = counter.split(text, self.REST, first_max_tokens=self.FIRST)
        assert "".join(pieces) == text
        assert len(pieces[0]) <= self.FIRST
        assert all(len(piece) <= self.REST for piece in pieces)


class TestWindowedPiecesStayFull:
    """Bounded is not enough: streaming must not leave a short piece at every
    seam, or a document splits into more chunks than a one-shot split gives."""

    PROSE = "The quick brown fox jumps over the lazy dog.\n" * 400

    # Budgets that don't divide the ~50 tokens a 256-char window holds, so a
    # piece that should run across a seam is visibly cut short if it isn't.
    @pytest.mark.parametrize("budget", [37, 60])
    def test_piece_count_matches_one_shot(self, budget, monkeypatch):
        _real_cl100k()
        counter = TiktokenCounter()
        one_shot = counter.split(self.PROSE, budget, first_max_tokens=10)
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        windowed = counter.split(self.PROSE, budget, first_max_tokens=10)
        assert "".join(windowed) == self.PROSE
        assert len(windowed) <= len(one_shot) + 2

    def test_tiktoken_pieces_are_not_character_capped(self, monkeypatch):
        """The 16-chars-per-token cap is a WordPiece ``[UNK]`` guard; a cl100k
        token can legitimately span a long whitespace run."""
        _real_cl100k()
        counter = TiktokenCounter()
        text = ("x" + " " * 60 + "\n") * 40
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        pieces = counter.split(text, 1)
        assert "".join(pieces) == text
        assert all(counter.count(piece) == 1 for piece in pieces)
        assert any(len(piece) > 16 for piece in pieces)


class TestHugeBudgetIsStillBounded:
    """A budget no window can fill means every segment comes back whole; the
    carry cap is what keeps the next encode from growing to the full text."""

    def test_tiktoken(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        encoding = _RecordingEncoding(_StubEncoding())
        monkeypatch.setattr(tokenization, "get_encoding", lambda: encoding)
        text = _MIXED[: 10 * _SMALL_WINDOW]
        assert "".join(TiktokenCounter().split(text, 10**9)) == text
        assert max(encoding.encode_lengths) <= 2 * _SMALL_WINDOW

    def test_hf(self, monkeypatch):
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        tokenizer = _CharTokenizer()
        text = _MIXED[: 10 * _SMALL_WINDOW]
        assert "".join(HuggingFaceCounter(tokenizer, "spy").split(text, 10**9)) == text
        assert max(tokenizer.encode_lengths) <= 2 * _SMALL_WINDOW


# Recorded on main before windowing: per sample, ``count`` and the lengths of
# the ``split`` pieces (with exact reassembly, lengths pin the pieces). Texts
# within the window must come out identical.
_GOLDEN = {
    ("cl100k", "count"): [10, 401, 14, 16, 23, 480],
    ("cl100k", 7, None): [
        [25, 14],
        [34, 30, 29, 36, 31, 29, 34, 32, 30, 29, 35, 30, 29, 36, 31, 29, 34, 32, 30, 29, 35,
         30, 29, 36, 31, 29, 34, 32, 30, 29, 35, 30, 29, 36, 31, 29, 34, 32, 30, 29, 35, 30,
         29, 36, 31, 29, 34, 32, 30, 29, 35, 30, 29, 36, 31, 29, 34, 2],
        [28, 28], [23, 37, 7], [7, 21, 16, 6],
        [9, 7, 9, 7, 9, 7, 7, 9, 7, 9, 7, 9, 7, 8, 8, 7, 9, 7, 9, 7, 9, 7, 7, 9, 7, 9, 7, 9,
         7, 8, 8, 7, 9, 7, 9, 7, 9, 7, 7, 9, 7, 9, 7, 9, 7, 8, 8, 7, 9, 7, 9, 7, 9, 7, 7, 9,
         7, 9, 7, 9, 7, 8, 8, 7, 9, 7, 9, 7, 4],
    ],
    ("cl100k", 50, None): [
        [39], [224, 225, 225, 225, 225, 225, 225, 225, 1], [56], [67], [50],
        [57, 57, 56, 56, 56, 56, 56, 56, 57, 33],
    ],
    ("cl100k", 20, 5): [
        [18, 21],
        [25, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 65],
        [21, 35], [19, 48], [5, 45],
        [7, 22, 22, 22, 24, 22, 22, 22, 24, 22, 22, 22, 24, 22, 22, 22, 24, 22, 22, 22, 24, 22,
         22, 22, 17],
    ],
    ("mpnet", "count"): [9, 400, 18, 24, 18, 450],
    ("mpnet", 7, None): [
        [28, 11],
        [34, 30, 29, 36, 31, 29, 34, 32, 30, 29, 35, 30, 29, 36, 31, 29, 34, 32, 30, 29, 35,
         30, 29, 36, 31, 29, 34, 32, 30, 29, 35, 30, 29, 36, 31, 29, 34, 32, 30, 29, 35, 30,
         29, 36, 31, 29, 34, 32, 30, 29, 35, 30, 29, 36, 31, 29, 34, 2],
        [21, 25, 10], [18, 16, 26, 7], [20, 22, 8],
        [8, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9,
         8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9, 8, 9, 8, 8, 9,
         8, 9, 8, 8, 9, 8, 9, 8, 3],
    ],
    ("mpnet", 50, None): [
        [39], [224, 225, 225, 225, 225, 225, 225, 226], [56], [67], [50],
        [59, 60, 60, 60, 60, 60, 60, 60, 61],
    ],
    ("mpnet", 20, 5): [
        [18, 21],
        [25, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 90, 65],
        [18, 38], [14, 53], [17, 33],
        [5, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24,
         24, 7],
    ],
}

_GOLDEN_BUDGETS = [(7, None), (50, None), (20, 5)]


class TestSmallTextsAreUnchanged:
    """Within the default window, windowing must be invisible: the same counts
    and the same chunk boundaries as before, so existing indexes stay valid."""

    @pytest.fixture
    def cl100k(self):
        _real_cl100k()
        return TiktokenCounter()

    def _check(self, counter, name):
        assert [counter.count(text) for text in SAMPLES] == _GOLDEN[(name, "count")]
        for max_tokens, first in _GOLDEN_BUDGETS:
            splits = [counter.split(text, max_tokens, first_max_tokens=first) for text in SAMPLES]
            for text, pieces in zip(SAMPLES, splits):
                assert "".join(pieces) == text
            assert [[len(p) for p in pieces] for pieces in splits] == _GOLDEN[(name, max_tokens, first)]

    def test_cl100k(self, cl100k):
        self._check(cl100k, "cl100k")

    def test_mpnet(self, hf_counter):
        self._check(hf_counter, "mpnet")


class TestCountTokensWindowed:
    """#3130 W2: ingest's whole-file counts (bulk ``token_count``, markdown's
    chunk check) go through a windowed cl100k count, not one encode of the file."""

    def test_prose_count_matches_one_shot_and_is_bounded(self, monkeypatch):
        from docsgpt.parser.tokenization import count_tokens_windowed

        text = TestWindowedCountIsExactOnProse.TEXT
        inner = _real_cl100k()
        expected = len(inner.encode_ordinary(text))
        encoding = _RecordingEncoding(inner)
        monkeypatch.setattr(tokenization, "get_encoding", lambda: encoding)
        _shrink_window(monkeypatch, _SMALL_WINDOW)
        assert len(text) > 4 * _SMALL_WINDOW

        assert count_tokens_windowed(text) == expected
        assert max(encoding.encode_lengths) <= 2 * _SMALL_WINDOW

    def test_empty_text_is_zero(self):
        from docsgpt.parser.tokenization import count_tokens_windowed

        assert count_tokens_windowed("") == 0
