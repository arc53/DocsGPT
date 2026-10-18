"""State builders: rendering as trained, and caps that keep the short field inside the token limit."""

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import states, tokens


class WordTokenizer:
    """One token per space-separated word, reversibly."""

    def __init__(self):
        self.vocab, self.words = {}, []

    def encode(self, text):
        ids = []
        for word in text.split(" ") if text else []:
            if word not in self.vocab:
                self.vocab[word] = len(self.words)
                self.words.append(word)
            ids.append(self.vocab[word])
        return ids

    def decode(self, ids):
        return " ".join(self.words[i] for i in ids)


@pytest.fixture
def word_tokens():
    tok = WordTokenizer()
    tokens.use(tok)
    yield tok
    tokens.reset()


@pytest.mark.unit
class TestRender:
    def test_structures_render_as_sorted_json(self):
        assert states.render({"query": "q", "passage": "p"}) == '{\n  "passage": "p",\n  "query": "q"\n}'

    def test_strings_render_as_they_are(self):
        assert states.render(states.plain("just text")) == "just text"

    def test_builders(self):
        assert states.text("hi") == {"text": "hi"}
        assert states.relevance("q", "p") == {"query": "q", "passage": "p"}
        assert states.grounding("src", "claim") == {"source": "src", "claim": "claim"}


@pytest.mark.unit
class TestCaps:
    def test_character_cap_before_the_tokenizer_loads(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MAX_TEXT_CHARS", 300)
        state = states.relevance("q", "x" * 1000)
        assert state["passage"] == "x" * 300 and state["query"] == "q"

    def test_token_cap_leaves_room_for_the_query(self, word_tokens, monkeypatch):
        monkeypatch.setattr(states, "max_state_tokens", lambda: 200)
        passage = " ".join(f"w{i}" for i in range(500))
        state = states.relevance("how do i rotate a key", passage)
        assert state["query"] == "how do i rotate a key"
        assert tokens.state_tokens(state) <= 200 - states.MARGIN
        assert passage.startswith(state["passage"]) and len(state["passage"]) < len(passage)

    def test_short_states_are_untouched(self, word_tokens):
        assert states.grounding("a short source", "a claim") == {"source": "a short source", "claim": "a claim"}

    def test_counts_are_none_before_the_tokenizer_loads(self):
        assert tokens.count_tokens("anything") is None
        assert tokens.state_tokens({"text": "anything"}) is None

    def test_max_state_tokens(self):
        assert states.max_state_tokens() == 2048


def _words(prefix, n, start=0):
    return " ".join(f"{prefix}{i}" for i in range(start, start + n))


@pytest.mark.unit
class TestBestWindow:
    """The CPU relevance profile: arc-decide's ``cap_passage(select="best")``, ported exactly.

    Each expected value was produced by arc-decide's own function on the same word tokenizer.
    """

    def test_the_window_holding_the_query_words_follows_the_head(self, word_tokens):
        passage = f"{_words('h', 64)} {_words('x', 200)} rotate the signing key here {_words('y', 200)}"
        got = states.best_window(passage, "rotate the signing key", 128)
        # Of the windows holding all four words (starts 160 and 192, every 32), the earlier one wins.
        assert got == f"{_words('h', 64)} ...\n{_words('x', 40, 160)} rotate the signing key here {_words('y', 19)}"

    def test_without_a_match_the_first_window_follows_the_head_directly(self, word_tokens):
        passage = f"{_words('h', 64)} {_words('x', 300)}"
        assert states.best_window(passage, "kubernetes ingress", 128) == f"{_words('h', 64)}{_words('x', 64)}"

    def test_the_last_tokens_past_the_final_window_start_are_never_reached(self, word_tokens):
        # Window starts step by half a window and stop where a full window still fits, as measured.
        passage = f"{_words('h', 64)} {_words('x', 300)} export billing csv"
        assert states.best_window(passage, "export billing csv", 128) == f"{_words('h', 64)}{_words('x', 64)}"

    def test_cjk_characters_count_as_query_terms(self, word_tokens):
        passage = f"{_words('h', 64)} {_words('x', 150)} 密钥 轮换 {_words('y', 150)}"
        got = states.best_window(passage, "密钥轮换", 100)
        assert got == f"{_words('h', 64)} ...\n{_words('x', 24, 126)} 密钥 轮换 {_words('y', 10)}"

    def test_a_passage_that_fits_is_unchanged(self, word_tokens):
        assert states.best_window(_words("w", 50), "anything", 128) == _words("w", 50)

    def test_without_a_query_the_head_is_kept(self, word_tokens):
        passage = f"{_words('h', 64)} {_words('x', 300)}"
        assert states.best_window(passage, "", 128) == f"{_words('h', 64)} {_words('x', 64)}"

    def test_none_before_the_tokenizer_loads(self):
        assert states.best_window("some passage", "query", 256) is None

    @pytest.mark.parametrize(
        "runtime, cpu",
        [("onnx-int8", True), ("onnx-fp32", True), ("api-process", True), ("api-process:onnx-int8", True),
         ("api-process:torch-cuda-bf16", False), ("torch-mps-fp16", False), ("vllm", False), ("remote", False),
         (None, False)],
    )
    def test_cpu_runtimes(self, runtime, cpu):
        assert states.cpu_runtime(runtime) is cpu
