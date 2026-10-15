"""A fake engine for the ONNX backend: a KV buffer that checks every pass reads rows it holds, and a fake clock."""

import time

from docsgpt.decisions.vendor.arc_decide import Decider as Release
from docsgpt.decisions.vendor.arc_decide import prefix_text, suffix_text


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CharTokenizer:
    """One token per character."""

    def encode(self, text):
        return [ord(c) for c in text]

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


def digest(ids) -> float:
    """An order-sensitive function of every row, standing in for the label logits at the last position."""
    return (sum((i + 1) * v for i, v in enumerate(ids)) % 9973) / 9973


class FakeBuffer:
    """Mimics ``SharedKV``: rows persist between passes, and a pass may only extend rows it holds."""

    def __init__(self, clock=None, cost=None, delay=0.0):
        self.rows: list[int] = []
        self.passes: list[tuple[int, int, bool]] = []  # (tokens, cached, one-layer)
        self.io, self.io_single = "all layers", "one layer"
        self.reserved = 0
        self.clock, self.cost, self.delay = clock, cost, delay

    def reserve(self, needed):
        self.reserved = max(self.reserved, needed)

    def extend(self, ids, start, io, chunk):
        assert chunk == 0, "the backend runs one pass per extend"
        assert start <= len(self.rows), "a pass read rows the buffer does not hold"
        self.rows = self.rows[:start] + list(ids)
        self.passes.append((len(ids), start, io == self.io_single))
        if self.delay:
            time.sleep(self.delay)
        if self.clock is not None:
            self.clock.advance(self.cost(len(ids), start))
        return digest(self.rows)


class FakeEngine:
    """What ``OnnxBackend`` needs from ``Engine``, without a session."""

    def __init__(self, meta, clock=None, cost=None, delay=0.0, max_state_tokens=2048):
        self.meta = meta
        self.tokenizer = CharTokenizer()
        self.max_state_tokens = max_state_tokens
        self.threads = 2
        self._buffer_args = (clock, cost, delay)
        self.kv = FakeBuffer(*self._buffer_args)
        self.buffers = [self.kv]

    def new_buffer(self):
        buffer = FakeBuffer(*self._buffer_args)
        self.buffers.append(buffer)
        return buffer

    def answer(self, logits, key, question):
        kind = question.get("type", "noul")
        if kind == "noul":
            return Release._answer(question, "noul", [logits, 1 - logits])
        n = len(question["criteria"])
        return Release._answer(question, kind, [(i + 1) / (n * (n + 1) / 2) for i in range(n)])


def expected_p(state_text: str, question: dict) -> float:
    """The P(yes) a fresh, uninterrupted run over the prompt and the question would give."""
    tok = CharTokenizer()
    return digest(tok.encode(prefix_text(state_text)) + tok.encode(suffix_text(question)))
