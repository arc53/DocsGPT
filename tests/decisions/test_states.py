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
