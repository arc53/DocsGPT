"""Fakes for the decision backends: an ONNX engine whose KV buffer checks every pass reads rows it holds, a fake
clock, a stand-in PyTorch model, a backend for ``DecideService`` to serve, and decision servers (the ``decide`` protocol and stock vLLM) behind an
``httpx2.MockTransport``."""

import contextlib
import json
import math
import threading
import time
import types
from collections import deque

import httpx2

from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.models import V02
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

    def encode(self, text, add_special_tokens=False):
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


def logit(ids, token) -> float:
    """A stand-in label logit at the last position of ``ids``: deterministic, and sensitive to every id."""
    return 4.0 * math.sin(sum((i + 1) * v for i, v in enumerate(ids)) * 1e-3 + token * 0.37)


def server_answer(question: dict, p: float) -> dict:
    """An answer as ``arcd serve`` shapes it: ``p`` on the first option (or yes), the rest spread evenly."""
    kind = question.get("type", "noul")
    if kind == "noul":
        return {"type": "noul", "noul": p}
    names = list(question["criteria"]) if kind == "choice" else [str(i) for i in range(len(question["criteria"]))]
    probs = {name: (p if i == 0 else (1 - p) / (len(names) - 1)) for i, name in enumerate(names)}
    if kind == "choice":
        return {"type": "choice", "choice": names[0], "confidence": p, "probabilities": probs}
    return {"type": "score", "score": 1.0, "confidence": p, "legend": {}, "probabilities": probs}


class FakeServer:
    """A decision server behind ``httpx2.MockTransport``, recording every request.

    ``script`` holds responses (or exceptions) for the next requests to the decision routes, before the normal
    behaviour resumes; ``gate`` blocks requests of one lane until it is set.
    """

    def __init__(self):
        self.log: list[dict] = []
        self.script: deque = deque()
        self.lock = threading.Lock()
        self.gate: dict[str, threading.Event] = {}

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        entry = {"method": request.method, "path": request.url.path, "body": body, "headers": request.headers}
        with self.lock:
            self.log.append(entry)
            scripted = self.script.popleft() if self.script and request.url.path != "/v1/models" else None
        event = self.gate.get(request.headers.get("x-decision-priority", ""))
        if event is not None:
            event.wait(5)
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is not None:
            return scripted(body) if callable(scripted) else scripted
        return self.route(request.url.path, body)

    def paths(self, *, models: bool = False) -> list[str]:
        return [e["path"] for e in self.log if models or e["path"] != "/v1/models"]

    def route(self, path, body):
        raise NotImplementedError


class FakeDecideServer(FakeServer):
    """``arcd serve`` (no identity on ``/v1/models``) or, with ``entry``, DocsGPT's decide-server.

    ``score(state, key)`` gives each answer's p.
    """

    def __init__(self, entry=None, score=lambda state, key: 0.7, load_route=True):
        super().__init__()
        self.entry = entry or {"name": "head:checkpoints/p5-v01", "description": "", "release_date": ""}
        self.score = score
        self.load_route = load_route

    def decide(self, body):
        answers = {key: server_answer(q, self.score(body["state"], key)) for key, q in body["questions"].items()}
        return {"model": self.entry["name"], "answers": answers, "usage": {"input_tokens": 7, "output_tokens": 0}}

    def route(self, path, body):
        if path == "/v1/models":
            return httpx2.Response(200, json={"models": [self.entry]})
        if path == "/v1/load":
            return httpx2.Response(202) if self.load_route else httpx2.Response(404)
        if path == "/v1/decide":
            return httpx2.Response(200, json=self.decide(body))
        if path == "/v1/decide/batch":
            return httpx2.Response(200, json={"responses": [self.decide(r) for r in body["requests"]]})
        return httpx2.Response(404)


class FakeVllmServer(FakeServer):
    """Stock vLLM with ``--logprobs-mode processed_logprobs``: log-probabilities over the allowed tokens only,
    from ``logit`` over the prompt ids, keyed ``token_id:<id>`` and in no particular order."""

    def __init__(self, served=("arc53/arc-decide-0.6b-v0.1",), drop=()):
        super().__init__()
        self.served = served
        self.drop = set(drop)

    def route(self, path, body):
        if path == "/v1/models":
            return httpx2.Response(200, json={"object": "list", "data": [
                {"id": name, "object": "model", "root": name, "max_model_len": 4096} for name in self.served]})
        if path == "/v1/completions":
            allowed = body["allowed_token_ids"]
            z = [logit(body["prompt"], t) for t in allowed]
            norm = max(z) + math.log(sum(math.exp(x - max(z)) for x in z))
            top = {f"token_id:{t}": x - norm for t, x in reversed(list(zip(allowed, z))) if t not in self.drop}
            return httpx2.Response(200, json={"choices": [{"index": 0, "text": "", "logprobs": {
                "tokens": [f"token_id:{allowed[0]}"], "token_logprobs": [0.0], "top_logprobs": [top]}}]})
        return httpx2.Response(404)


class FakeLogits:
    """What ``(head @ h).float()`` gives the release client: label logits indexed by head row."""

    def __init__(self, ids, rows):
        self.ids, self.rows = ids, rows

    def float(self):
        return self

    def cpu(self):
        return self

    def __getitem__(self, column):
        return types.SimpleNamespace(item=lambda: logit(self.ids, self.rows[column]))


class FakeHead:
    def __init__(self, rows):
        self.rows = rows

    def __matmul__(self, hidden):
        return FakeLogits(hidden, self.rows)


class FakeCache:
    def __init__(self):
        self.ids = []

    def crop(self, length):
        self.ids = self.ids[:length]


def fake_decoder(ids, past_key_values=None, use_cache=True):
    """The decoder stand-in: the "hidden state" at the last position is every id read so far."""
    cache = past_key_values or FakeCache()
    cache.ids = cache.ids + list(ids)
    return types.SimpleNamespace(past_key_values=cache, last_hidden_state={(0, -1): list(cache.ids)})


def fake_torch() -> types.ModuleType:
    """The few ``torch`` calls the PyTorch clients make around the model."""
    torch = types.ModuleType("torch")
    torch.inference_mode = contextlib.nullcontext
    torch.tensor = lambda rows, device=None: rows[0]
    return torch


def stand_in(decider, serving, tokenizer=None):
    """Give a PyTorch client built with ``__new__`` (its ``__init__`` downloads and loads the model) the stand-in
    model, the tokenizer and the published ``arcd_serving.json``."""
    decider.meta, decider.tokenizer, decider.device = serving, tokenizer or CharTokenizer(), "cpu"
    rows = sorted({t for h in serving["heads"].values() for t in h["tokens"]})
    decider.column = {t: i for i, t in enumerate(rows)}
    decider.head, decider.decoder = FakeHead(rows), fake_decoder
    decider.max_state_tokens = serving["max_state_tokens"]
    return decider


class FakeBackend:
    """What ``DecideService`` needs from a backend; ``outcomes`` scripts what ``run`` returns."""

    def __init__(self, outcomes=None):
        self.spec, self.calibration, self.runtime = V02, V02.calibration, "onnx-int8"
        self.status, self.reason, self.profile = "idle", None, None
        self.outcomes = outcomes
        self.calls, self.warmed = [], 0

    def run(self, requests, lane, deadline):
        self.calls.append((requests, lane, deadline))
        if self.outcomes is not None:
            return list(self.outcomes)
        return [Outcome({key: {"type": "noul", "noul": 0.7} for key in r.questions}, 1.0, 0.0, False, 12)
                for r in requests]

    def warm(self):
        self.warmed += 1
