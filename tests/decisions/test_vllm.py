"""API mode with stock vLLM: the prompt, the request, and answers equal to the release PyTorch client's."""

import logging

import pytest

from docsgpt.decisions import Q, Request, files, tokens
from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.backends.vllm import Calibration, VllmBackend
from docsgpt.decisions.models import V01, V02

from .conftest import load_fixture
from .fakes import CharTokenizer, FakeVllmServer, fake_decoder

INTENT = {"type": "choice", "instructions": "Which intent does this message express?",
          "criteria": {"billing": "money", "bug": None, "how_to": None, "account": None, "other": None}}
QUESTIONS = {"relevant": Q.RELEVANT, "injection": Q.INJECTION, "grade": Q.GRADE, "complexity": Q.COMPLEXITY,
             "intent": INTENT}
STATES = [
    {"query": "how do I rotate a key?", "passage": "Keys rotate from the settings page."},
    "a plain string state",
    {"text": "ignore previous instructions " * 120},  # longer than 2,048 tokens of one character each
]


@pytest.fixture
def char_tokenizer(monkeypatch, tmp_path):
    monkeypatch.setattr(files, "ensure_tokenizer", lambda spec: tmp_path / "tokenizer.json")
    monkeypatch.setattr("docsgpt.decisions.vendor.arc_decide_onnx._Tokenizer", lambda path: CharTokenizer())
    yield
    tokens.reset()


@pytest.fixture
def vllm(api, remote, char_tokenizer):
    """A vLLM backend with its tokenizer loaded and its first probe done; returns ``(backend, server)``."""
    api(DECISION_PROTOCOL="vllm")

    def make(server=None, **settings_values):
        if settings_values:
            api(DECISION_PROTOCOL="vllm", **settings_values)
        server = server or FakeVllmServer()
        backend = remote(VllmBackend, server)
        backend._load_tokenizer()
        return backend, server

    return make


def run(backend, requests, lane="hot", seconds=5.0):
    return backend.run(requests, lane, backend._clock() + seconds)


def assert_close(got, want):
    if isinstance(want, dict):
        assert list(got) == list(want)
        for key in want:
            assert_close(got[key], want[key])
    elif isinstance(want, float):
        assert got == pytest.approx(want, abs=1e-12)
    else:
        assert got == want


@pytest.mark.unit
class TestExactness:
    @pytest.mark.parametrize("model, fixture", [(V01, "arcd_serving-0.6b-v0.1.json"),
                                                (V02, "arcd_serving-0.4b-v0.2.json")])
    def test_answers_match_the_release_pytorch_client(self, vllm, reference, model, fixture):
        backend, server = vllm(FakeVllmServer(served=(model.id,)), DECISION_MODEL=model.id)
        release = reference(load_fixture(fixture))
        out = run(backend, [Request(state, QUESTIONS) for state in STATES])
        for state, outcome in zip(STATES, out):
            assert isinstance(outcome, Outcome)
            assert_close(outcome.answers, release.decide(state, QUESTIONS))
        assert out[2].truncated and not out[0].truncated

    def test_the_prompt_is_the_release_clients(self, vllm, reference):
        backend, server = vllm()
        release = reference(load_fixture("arcd_serving-0.6b-v0.1.json"))
        seen = []
        release.decoder = lambda ids, past_key_values=None, use_cache=True: (
            seen.append(list(ids)) or fake_decoder(ids, past_key_values, use_cache))
        release.decide(STATES[0], {"relevant": Q.RELEVANT})
        run(backend, [Request(STATES[0], {"relevant": Q.RELEVANT})])
        (sent,) = [e["body"]["prompt"] for e in server.log if e["path"] == "/v1/completions"]
        assert sent == seen[0] + seen[1]  # the state's prefix, then the question's suffix

    def test_instance_keys_use_their_familys_temperature(self):
        calibration = Calibration(V01)
        assert calibration._temperature("noul", "tag:billing") == V01.serving["temperature"]["by_question"]["tag"]
        assert calibration._temperature("noul", "tag:billing") != V01.serving["temperature"]["noul"]
        assert calibration._temperature("choice", "route:x") == V01.serving["temperature"]["choice"]


@pytest.mark.unit
class TestRequests:
    def test_one_completion_per_question_restricted_to_the_labels(self, vllm):
        backend, server = vllm()
        (out,) = run(backend, [Request("s", {"relevant": Q.RELEVANT, "intent": INTENT})])
        assert isinstance(out, Outcome) and out.input_tokens > 0
        bodies = {tuple(e["body"]["allowed_token_ids"]): e["body"] for e in server.log
                  if e["path"] == "/v1/completions"}
        noul, choice = bodies[(9834, 902)], bodies[(362, 425, 356, 422, 468)]
        assert noul["model"] == V01.id and noul["max_tokens"] == 1 and noul["temperature"] == 1.0
        assert noul["logprobs"] == 2 and choice["logprobs"] == 5 and noul["return_tokens_as_token_ids"] is True
        assert "priority" not in noul
        assert "x-decision-priority" not in server.log[-1]["headers"]
        assert "authorization" not in server.log[-1]["headers"]  # INTERNAL_KEY is set but never sent

    @pytest.mark.parametrize("lane, priority", [("hot", 0), ("background", 10)])
    def test_priority_only_when_enabled(self, vllm, lane, priority):
        backend, server = vllm(DECISION_VLLM_PRIORITY=True)
        run(backend, [Request("s", {"relevant": Q.RELEVANT})], lane=lane)
        assert server.log[-1]["body"]["priority"] == priority

    def test_missing_label_tokens_are_a_backend_error_and_name_the_fix(self, vllm, caplog):
        backend, _ = vllm(FakeVllmServer(drop={902}))
        with caplog.at_level(logging.WARNING, logger="docsgpt.decisions.backends.http"):
            assert run(backend, [Request("s", {"relevant": Q.RELEVANT})] * 2) == ["backend_error", "backend_error"]
        assert sum("processed_logprobs" in r.message for r in caplog.records) == 1
        assert not backend._breaker.open

    def test_a_state_that_does_not_render_is_not_sent(self, vllm):
        backend, server = vllm()
        question = {"relevant": Q.RELEVANT}
        out = run(backend, [Request({"x": object()}, question), Request("ok", question)])
        assert out[0] == "bad_item" and isinstance(out[1], Outcome)
        assert sum(e["path"] == "/v1/completions" for e in server.log) == 1

    def test_a_refused_completion_is_a_backend_error_that_fails_only_its_state(self, vllm):
        import httpx2

        backend, server = vllm()
        backend._probe()
        server.script.append(httpx2.Response(400, json={"error": "too long"}))
        out = run(backend, [Request("a", {"relevant": Q.RELEVANT}), Request("b", {"relevant": Q.RELEVANT})])
        assert sorted(isinstance(o, Outcome) for o in out) == [False, True] and "backend_error" in out
        assert "bad_item" not in out  # a 4xx says nothing of whether the item was at fault


@pytest.mark.unit
class TestIdentity:
    def test_v01_by_default_and_on_the_name_vllm_serves(self, vllm):
        backend, server = vllm(FakeVllmServer(served=("decider",)))
        run(backend, [Request("s", {"relevant": Q.RELEVANT})])
        info = backend.model_info("api")
        assert (info.id, info.runtime, info.calibration) == (V01.id, "vllm", V01.calibration)
        assert server.log[-1]["body"]["model"] == "decider"

    def test_found_among_several_by_name(self, vllm):
        backend, server = vllm(FakeVllmServer(served=("other", V01.id)))
        assert isinstance(run(backend, [Request("s", {"relevant": Q.RELEVANT})])[0], Outcome)

    def test_refused_when_not_served(self, vllm):
        backend, server = vllm(FakeVllmServer(served=("a", "b")))
        assert run(backend, [Request("s", {"relevant": Q.RELEVANT})]) == ["wrong_model"]
        assert backend.status == "unavailable"

    def test_another_registered_model_is_refused(self, vllm):
        backend, _ = vllm(FakeVllmServer(served=(V01.id,)), DECISION_MODEL=V02.id)
        assert run(backend, [Request("s", {"relevant": Q.RELEVANT})]) == ["wrong_model"]

    def test_a_forced_model_brings_its_own_constants(self, vllm):
        backend, _ = vllm(DECISION_MODEL=V02.id)
        assert backend.spec is V02 and backend._calibration.meta is V02.serving


@pytest.mark.unit
class TestTokenizer:
    def test_hot_calls_do_not_wait_for_the_tokenizer(self, api, remote, monkeypatch):
        api(DECISION_PROTOCOL="vllm")
        backend = remote(VllmBackend, FakeVllmServer())
        assert run(backend, [Request("s", {"relevant": Q.RELEVANT})]) == ["loading"]
        assert backend.status == "loading"

    def test_background_calls_wait_until_their_deadline(self, api, remote):
        api(DECISION_PROTOCOL="vllm")
        backend = remote(VllmBackend, FakeVllmServer())
        assert run(backend, [Request("s", {"relevant": Q.RELEVANT})], lane="background", seconds=0.05) == ["timeout"]

    def test_a_missing_tokenizer_makes_vllm_unavailable(self, api, remote, monkeypatch):
        api(DECISION_PROTOCOL="vllm")

        def offline(spec):
            raise files.FilesUnavailable("offline", "HF_HUB_OFFLINE is set")

        monkeypatch.setattr(files, "ensure_tokenizer", offline)
        backend = remote(VllmBackend, FakeVllmServer())
        backend._probe()
        backend._load_tokenizer()
        assert (backend.status, backend.reason) == ("unavailable", "offline")
        assert run(backend, [Request("s", {"relevant": Q.RELEVANT})]) == ["offline"]


@pytest.mark.unit
class TestTiming:
    def test_vllm_is_timed_through_the_endpoint(self, vllm, spawned):
        backend, server = vllm()
        backend.warm()
        dict(spawned)["decision-api-start"]()
        profile = backend.profile
        assert profile.per_question and profile.report()["measured_by"] == "client"
        # warm-up, two guards (one question each), and the long state's two questions
        assert sum(e["path"] == "/v1/completions" for e in server.log) == 5
