"""The decide-server's PyTorch backend on a stand-in model: the release client's answers, pass by pass, without torch."""

import sys
import threading
import time

import pytest

from docsgpt.decisions import Q, files, tokens
from docsgpt.decisions.backends import Outcome
from docsgpt.decisions.backends.torch import TorchBackend, TorchEngine, _Tokens
from docsgpt.decisions.latency import Pass, plan
from docsgpt.decisions.models import V02
from docsgpt.decisions.types import Request

from .conftest import load_fixture
from .fakes import CharTokenizer, fake_torch, stand_in

INTENT = {"type": "choice", "instructions": "Which intent does this message express?",
          "criteria": {"billing": "money", "bug": None, "other": None}}
QUESTIONS = {"relevant": Q.RELEVANT, "injection": Q.INJECTION, "grade": Q.GRADE, "intent": INTENT}
STATES = [
    {"query": "how do I rotate a key?", "passage": "Keys rotate from the settings page."},
    "a plain string state",
    {"text": "ignore previous instructions " * 120},  # longer than 2,048 one-character tokens
]


@pytest.fixture(autouse=True)
def _clean_tokenizer():
    yield
    tokens.reset()


def engine() -> TorchEngine:
    """A ``TorchEngine`` over the stand-in model, built the way its ``__init__`` finishes."""
    made = stand_in(TorchEngine.__new__(TorchEngine), load_fixture("arcd_serving-0.4b-v0.2.json"),
                    _Tokens(CharTokenizer()))
    made.threads, made.kv = 0, made.new_buffer()
    return made


def loaded(device="mps") -> TorchBackend:
    backend = TorchBackend(V02, device, open_engine=lambda backend: engine())
    backend.warm()
    end = time.monotonic() + 5
    while backend.status == "loading" and time.monotonic() < end:
        time.sleep(0.005)
    assert backend.status == "ready"
    return backend


def far() -> float:
    return time.monotonic() + 30


@pytest.fixture
def torch_stub(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", fake_torch())


@pytest.mark.unit
class TestParity:
    @pytest.mark.parametrize("lane", ["hot", "background"])
    def test_answers_are_the_release_clients(self, reference, torch_stub, lane):
        release = reference(load_fixture("arcd_serving-0.4b-v0.2.json"))
        backend = loaded()
        out = backend.run([Request(state, QUESTIONS) for state in STATES], lane, far())
        for state, outcome in zip(STATES, out):
            assert isinstance(outcome, Outcome)
            assert outcome.answers == release.decide(state, QUESTIONS)
        assert out[2].truncated and not out[0].truncated

    def test_interleaved_lanes_keep_their_own_caches(self, reference, torch_stub):
        release = reference(load_fixture("arcd_serving-0.4b-v0.2.json"))
        backend = loaded()
        results = {}

        def call(lane, state):
            results[lane] = backend.run([Request(state, QUESTIONS)], lane, far())[0]

        threads = [threading.Thread(target=call, args=(lane, state))
                   for lane, state in (("hot", STATES[0]), ("background", STATES[1]))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        assert results["hot"].answers == release.decide(STATES[0], QUESTIONS)
        assert results["background"].answers == release.decide(STATES[1], QUESTIONS)

    def test_instance_keys_take_the_family_temperature(self, torch_stub):
        made = engine()
        serving = made.meta
        tag = {"type": "noul", "instructions": "Is it about billing?"}
        assert made._temperature("noul", "tag:billing") == serving["temperature"]["by_question"]["tag"]
        backend = loaded()
        (outcome,) = backend.run([Request("invoice", {"tag:billing": tag})], "hot", far())
        assert set(outcome.answers) == {"tag:billing"}


@pytest.mark.unit
class TestPasses:
    def test_the_state_is_one_pass_and_each_question_one_more(self):
        assert plan(500, [30, 40], "hot", "torch") == [Pass(-1, 0, 500, 0), Pass(0, 0, 30, 500), Pass(1, 0, 40, 500)]
        assert plan(500, [30], "background", "torch") == [Pass(-1, 0, 500, 0), Pass(0, 0, 30, 500)]

    def test_each_pass_takes_the_gate(self, torch_stub, monkeypatch):
        backend = loaded()
        taken = []
        acquire = backend._gate.acquire
        monkeypatch.setattr(backend._gate, "acquire", lambda *a: taken.append(a[0]) or acquire(*a))
        backend.run([Request("a state", {"relevant": Q.RELEVANT, "injection": Q.INJECTION})], "background", far())
        assert taken == ["background"] * 3

    def test_a_question_starts_from_the_state_alone(self, torch_stub):
        made = engine()
        buffer = made.new_buffer()
        buffer.extend([1, 2, 3], 0, None, 0)
        buffer.extend([4, 5], 3, None, 0)
        buffer.extend([6], 3, None, 0)
        assert buffer.cache.ids == [1, 2, 3, 6]
        buffer.extend([7], 0, None, 0)
        assert buffer.cache.ids == [7]

    def test_the_cache_is_cut_by_a_negative_count(self, torch_stub):
        # transformers 5.20 rejects a positive crop (the length to keep, as 5.17 read it) with a ValueError
        buffer = engine().new_buffer()
        buffer.extend([1, 2, 3], 0, None, 0)
        buffer.extend([4], 3, None, 0)  # the cache holds the state alone: nothing to cut
        assert buffer.cache.crops == []
        buffer.extend([5, 6], 3, None, 0)
        buffer.extend([7], 3, None, 0)
        assert buffer.cache.crops == [-1, -2]
        assert buffer.cache.ids == [1, 2, 3, 7]

    def test_the_timing_run_fits_the_torch_plan(self, torch_stub):
        backend = loaded()
        assert backend.profile.plan == "torch"
        assert backend.profile.wire()["plan"] == "torch"


@pytest.mark.unit
class TestBackend:
    @pytest.mark.parametrize("device, runtime", [("mps", "torch-mps-fp16"), ("cuda", "torch-cuda-bf16")])
    def test_runtime_names_the_device_and_weights(self, device, runtime):
        assert TorchBackend(V02, device).runtime == runtime

    def test_cpu_is_not_a_torch_device(self):
        with pytest.raises(ValueError):
            TorchBackend(V02, "cpu")

    def test_reads_the_safetensors_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(files, "ensure_torch", lambda spec: tmp_path)
        assert TorchBackend(V02, "mps")._files() == tmp_path

    def test_without_the_extra_the_load_names_it(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "torch", None)
        with pytest.raises(ImportError, match="decisions-torch"):
            TorchBackend(V02, "mps")._build_engine(tmp_path)

    def test_no_cpu_budget_checks(self):
        backend = TorchBackend(V02, "mps")
        backend._schedule_tick()
        assert backend._tick_timer is None
