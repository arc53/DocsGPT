"""The ``vllm`` protocol: stock vLLM serving a decision model, read one label token at a time.

The published safetensors fold the decision heads into the rows of a few vocabulary tokens, so stock vLLM can
serve the model unchanged with ``--logprobs-mode processed_logprobs --max-logprobs 16``. Each (state, question) is
one ``POST /v1/completions``: the prompt as token ids, built here exactly as the release client builds it (state
cut to ``max_state_tokens``, prefix and suffix encoded apart), ``max_tokens`` 1, sampling restricted to the head's
label tokens, and their log-probabilities returned. After that restriction the labels' log-probabilities share
one normaliser, so they are the head's logits up to a constant; the bias and temperature the folded rows cannot
carry are applied here, with the release client's code and the model's vendored constants
(``models.ModelSpec.serving``). vLLM's prefix cache shares each state's prompt between its questions.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.backends.http import RemoteBackend
from docsgpt.decisions.models import ModelSpec, lookup
from docsgpt.decisions.questions import family
from docsgpt.decisions.types import Lane, Request
from docsgpt.decisions.vendor.arc_decide import Decider as ReleaseDecider
from docsgpt.decisions.vendor.arc_decide import _softmax

logger = logging.getLogger(__name__)

#: ``priority`` per lane when ``DECISION_VLLM_PRIORITY`` is on; vLLM serves lower values first.
PRIORITY = {"hot": 0, "background": 10}


class Calibration(ReleaseDecider):
    """One model's heads and fitted temperatures, applied with the release client's own code, without the model.

    ``_head`` gives a question's label tokens and biases, ``_temperature`` its temperature (by family, as
    ``backends.onnx.Engine``), and ``_answer`` the wire shape.
    """

    def __init__(self, spec: ModelSpec):
        """Read the heads and temperatures from ``spec.serving``."""
        self.meta = spec.serving

    def _temperature(self, kind: str, name: str) -> float:
        return super()._temperature(kind, family(name))

    def labels(self, key: str, question: dict) -> list[int]:
        """The label tokens a question is read at, in the order ``answer`` takes their scores."""
        return self._head(key, question)[1]

    def answer(self, scores: list[float], key: str, question: dict) -> dict:
        """The wire-shaped answer from the label tokens' scores.

        The scores may be logits or log-probabilities normalised over the labels: they differ by one constant,
        which the softmax cancels. The arithmetic is the release client's ``decide``.
        """
        kind, _, bias = self._head(key, question)
        t = self._temperature(kind, key)
        return self._answer(question, kind, _softmax([(s + b) / t for s, b in zip(scores, bias)]))


class VllmBackend(RemoteBackend):
    """Decisions from stock vLLM; the prompt, truncation and calibration are computed on this side."""

    runtime_key = "vllm"
    needs_tokenizer = True
    per_question = True

    def __init__(self, transport: Any = None, **kwargs: Any):
        super().__init__(transport, **kwargs)
        self.runtime = "vllm"
        self._served = self.spec.id  # the name vLLM serves the model under, from the probe
        self._calibration = Calibration(self.spec)

    def _run(self, requests: list[Request], lane: Lane, start: float, deadline: float) -> list[Outcome | str]:
        from docsgpt.core.settings import settings

        budget = max(0.0, deadline - start)
        out: list[Outcome | str] = ["bad_item"] * len(requests)  # kept only by a state that does not render
        encoded: dict[int, tuple[list[int], list[list[int]], bool]] = {}
        jobs = []
        submitted = self._clock()
        for i, request in enumerate(requests):
            try:
                prefix, suffixes, truncated = self.encode(request)
            except (TypeError, ValueError):  # the state does not render
                continue
            encoded[i] = prefix, suffixes, truncated
            for (key, question), suffix in zip(request.questions.items(), suffixes):
                labels = self._calibration.labels(key, question)
                body = {
                    "model": self._served, "prompt": prefix + suffix, "max_tokens": 1, "temperature": 1.0,
                    "logprobs": len(labels), "allowed_token_ids": labels, "return_tokens_as_token_ids": True,
                }
                if settings.DECISION_VLLM_PRIORITY:
                    body["priority"] = PRIORITY[lane]
                jobs.append((lambda body=body, labels=labels: self._complete(body, labels, lane, deadline, budget),
                             (i, key)))
        results: dict[int, dict[str, Any]] = {i: {} for i in encoded}
        for (i, key), result in self._gather(jobs, lane, deadline):
            results[i][key] = result
        for i, by_key in results.items():
            prefix, suffixes, truncated = encoded[i]
            out[i] = self._outcome(requests[i], by_key, truncated, len(prefix) + sum(map(len, suffixes)), submitted)
        return out

    def _complete(self, body: dict, labels: list[int], lane: Lane, deadline: float,
                  budget: float) -> tuple[list[float], float, float] | str:
        """One completion: the labels' log-probabilities, with its start and end, or the reason it has none.

        A refusal (an HTTP 4xx) says nothing of whether the item was at fault, and a reply that leaves label tokens
        out is a server not configured for the model: both are ``backend_error``, as in ``RemoteBackend``.
        """
        began = self._clock()
        reply = self._send("POST", "/v1/completions", body, lane=lane, deadline=deadline, budget=budget,
                           check=lambda data: isinstance(data["choices"][0]["logprobs"]["top_logprobs"][0], dict))
        if reply.data is None:
            return "backend_error" if reply.reason == "rejected" else reply.reason
        top = reply.data["choices"][0]["logprobs"]["top_logprobs"][0]
        by_id = {}
        for token, logprob in top.items():
            name, _, number = str(token).partition("token_id:")
            if not name and number.isdigit() and isinstance(logprob, (int, float)):
                by_id[int(number)] = float(logprob)
        if any(t not in by_id for t in labels):
            self._log_once("labels", logging.WARNING, "vLLM left label tokens out of its reply: serve the decision "
                           "model with --logprobs-mode processed_logprobs and --max-logprobs 16")
            return "backend_error"
        return [by_id[t] for t in labels], began, self._clock()

    def _outcome(self, request: Request, by_key: dict[str, Any], truncated: bool, input_tokens: int,
                 submitted: float) -> Outcome | str:
        """The state's answers once every question has its log-probabilities; else the first reason one failed."""
        for key in request.questions:
            if isinstance(by_key.get(key), str):
                return by_key[key]
        answers = {key: self._calibration.answer(by_key[key][0], key, q) for key, q in request.questions.items()}
        first = min(r[1] for r in by_key.values())
        last = max(r[2] for r in by_key.values())
        return Outcome(answers, (last - first) * 1000, (first - submitted) * 1000, truncated, input_tokens)

    # Identity

    def _models_shape(self, data: Any) -> bool:
        entries = data["data"]
        return isinstance(entries, list) and bool(entries) and all(isinstance(e, dict) for e in entries)

    def _identify(self, data: Any) -> Optional[str]:
        """Find the decision model among the served ones, by its name or the repository it was loaded from.

        A single model served under a name of its own is taken as this one, logged once: vLLM reports no prompt
        or calibration to check. Another registered model is refused.
        """
        entries = data["data"]
        names = [(str(e.get("id", "")), str(e.get("root", ""))) for e in entries]
        match = next((e for e, pair in zip(entries, names) if any(lookup(n) is self.spec for n in pair)), None)
        if match is None and len(entries) == 1 and not any(lookup(n) for n in names[0]):
            match = entries[0]
            self._log_once("identity", logging.INFO, "vLLM serves %s; its answers are taken as %s's",
                           match.get("id"), self.spec.id)
        if match is None:
            self._log_once("wrong_model", logging.WARNING, "vLLM does not serve %s (it serves %s); decisions fail "
                           "open", self.spec.id, ", ".join(str(e.get("id")) for e in entries))
            return "wrong_model"
        self._said.discard("wrong_model")
        self._served = str(match.get("id"))
        return None
