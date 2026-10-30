"""The ONNX backend's lifecycle and pass execution, on a fake engine: no model, no network."""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import features, files, tokens
from docsgpt.decisions.backends import onnx
from docsgpt.decisions.backends.onnx import LoadRefused, OnnxBackend, Outcome
from docsgpt.decisions.models import V02
from docsgpt.decisions.questions import Q
from docsgpt.decisions.types import FeatureSpec, Request, Shape
from docsgpt.decisions.vendor.arc_decide import prefix_text, to_text

from .conftest import load_fixture
from .fakes import CharTokenizer, FakeClock, FakeEngine, byte_tokenizer, expected_p

NOUL = {"type": "noul", "instructions": "Is it?"}
OTHER = {"type": "noul", "instructions": "Is it something else entirely?"}


@pytest.fixture(autouse=True)
def _clean_tokenizer():
    yield
    tokens.reset()


class Opener:
    """Counts loads; returns a fake engine, raises, or waits for ``release`` first."""

    def __init__(self, engine=None, error=None, gated=False):
        self.engine, self.error, self.count = engine, error, 0
        self.release = threading.Event()
        if not gated:
            self.release.set()

    def __call__(self, backend):
        self.count += 1
        self.release.wait(5)
        if self.error:
            raise self.error
        return self.engine


def settle(backend, timeout=5.0):
    end = time.monotonic() + timeout
    while backend.status == "loading" and time.monotonic() < end:
        time.sleep(0.005)
    return backend.status


def loaded(engine, clock=None) -> OnnxBackend:
    backend = OnnxBackend(V02, open_engine=Opener(engine), **({"clock": clock} if clock else {}))
    backend.warm()
    assert settle(backend) == "ready"
    return backend


def far() -> float:
    return time.monotonic() + 30


@pytest.mark.unit
class TestLifecycle:
    def test_nothing_loads_until_asked(self):
        opener = Opener(FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json")))
        backend = OnnxBackend(V02, open_engine=opener)
        assert (backend.status, opener.count) == ("idle", 0)

    def test_a_hot_call_does_not_wait_for_the_load(self):
        opener = Opener(FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json")), gated=True)
        backend = OnnxBackend(V02, open_engine=opener)
        started = time.monotonic()
        assert backend.run([Request("x", {"q": NOUL})] * 2, "hot", far()) == ["loading", "loading"]
        assert time.monotonic() - started < 1
        opener.release.set()
        assert settle(backend) == "ready"
        assert isinstance(backend.run([Request("x", {"q": NOUL})], "hot", far())[0], Outcome)

    def test_a_background_call_waits_for_the_load(self):
        opener = Opener(FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json")), gated=True)
        backend = OnnxBackend(V02, open_engine=opener)
        threading.Timer(0.1, opener.release.set).start()
        (outcome,) = backend.run([Request("x", {"q": NOUL})], "background", far())
        assert isinstance(outcome, Outcome)
        assert opener.count == 1

    def test_the_tokenizer_comes_up_with_the_model(self):
        assert tokens.count_tokens("abc") is None
        loaded(FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json")))
        assert tokens.count_tokens("abc") == 3

    def test_a_failed_load_is_latched_then_retried(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_LOAD_RETRY_SECONDS", 300)
        clock = FakeClock()
        opener = Opener(error=files.FilesUnavailable("offline", "no files"), gated=True)
        backend = OnnxBackend(V02, open_engine=opener, clock=clock)
        assert backend.run([Request("x", {"q": NOUL})], "hot", clock() + 3) == ["loading"]
        opener.release.set()
        assert settle(backend) == "unavailable" and backend.reason == "offline"
        assert backend.run([Request("x", {"q": NOUL})], "background", clock() + 3) == ["offline"]
        assert opener.count == 1
        clock.advance(301)
        backend.warm()
        settle(backend)
        assert opener.count == 2

    @pytest.mark.parametrize("error, reason", [
        (LoadRefused("memory", "too little"), "memory"),
        (LoadRefused("wrong_model", "prompt"), "wrong_model"),
        (files.FilesUnavailable("download", "reset"), "download"),
        (RuntimeError("corrupt graph"), "load_failed"),
    ])
    def test_failure_reasons(self, error, reason):
        backend = OnnxBackend(V02, open_engine=Opener(error=error))
        backend.warm()
        assert settle(backend) == "unavailable"
        assert backend.reason == reason

    def test_the_timing_run_fits_this_machines_cost(self):
        clock = FakeClock()
        c, a, b = 0.02, 0.0004, 3e-7
        engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"), clock=clock,
                            cost=lambda n, k: c + n * (a + b * (k + n / 2)))
        backend = loaded(engine, clock)
        profile = backend.profile
        assert (profile.c, profile.a, profile.b) == pytest.approx((c, a, b), rel=1e-6)
        assert profile.overhead == len(prefix_text(""))
        assert profile.threads == 2

    def test_a_different_calibration_becomes_the_identity(self, caplog):
        meta = load_fixture("arcd_serving-0.4b-v0.2.json")
        meta["temperature"]["noul"] = 1.5
        backend = loaded(FakeEngine(meta))
        assert backend.calibration != V02.calibration
        assert "calibration" in caplog.text


@pytest.fixture
def model_folder(tmp_path, monkeypatch):
    """An ONNX folder with real metadata and no graph, with the session constructor stubbed out."""
    folder = tmp_path / "onnx"
    folder.mkdir()
    (folder / "arcd_serving.json").write_text(json.dumps(load_fixture("arcd_serving-0.4b-v0.2.json")))
    (tmp_path / "questions.json").write_text(json.dumps(load_fixture("questions.json")))
    monkeypatch.setattr(files, "ensure_onnx", lambda spec: folder)
    monkeypatch.setattr(onnx.memory, "headroom_mb", lambda: 4000.0)
    monkeypatch.setattr(settings, "DECISION_MIN_FREE_MB", None)
    monkeypatch.setattr(settings, "DECISION_THREADS", 3)
    built = []
    monkeypatch.setattr(onnx, "Engine", lambda path, threads: built.append((path, threads)) or "engine")
    return folder, built


@pytest.mark.unit
class TestOpen:
    def test_opens_the_folder_with_the_thread_setting(self, model_folder):
        folder, built = model_folder
        assert OnnxBackend(V02)._open() == "engine"
        assert built == [(str(folder), 3)]

    def test_refused_below_the_models_memory_floor(self, model_folder, monkeypatch):
        monkeypatch.setattr(onnx.memory, "headroom_mb", lambda: 1000.0)
        with pytest.raises(LoadRefused) as caught:
            OnnxBackend(V02)._open()
        assert caught.value.reason == "memory"
        assert model_folder[1] == []

    def test_the_memory_floor_is_a_setting(self, model_folder, monkeypatch):
        monkeypatch.setattr(onnx.memory, "headroom_mb", lambda: 1000.0)
        monkeypatch.setattr(settings, "DECISION_MIN_FREE_MB", 800)
        assert OnnxBackend(V02)._open() == "engine"

    def test_unknown_headroom_does_not_block(self, model_folder, monkeypatch):
        monkeypatch.setattr(onnx.memory, "headroom_mb", lambda: None)
        assert OnnxBackend(V02)._open() == "engine"

    def test_another_prompt_is_refused(self, model_folder):
        folder, built = model_folder
        meta = load_fixture("arcd_serving-0.4b-v0.2.json")
        meta["prompt_hash"] = "000000000000"
        (folder / "arcd_serving.json").write_text(json.dumps(meta))
        with pytest.raises(LoadRefused) as caught:
            OnnxBackend(V02)._open()
        assert caught.value.reason == "wrong_model" and built == []

    def test_a_model_without_a_state_limit_is_refused(self, model_folder):
        folder, _ = model_folder
        meta = load_fixture("arcd_serving-0.4b-v0.2.json")
        del meta["max_state_tokens"]
        (folder / "arcd_serving.json").write_text(json.dumps(meta))
        with pytest.raises(LoadRefused) as caught:
            OnnxBackend(V02)._open()
        assert caught.value.reason == "wrong_model"

    def test_changed_question_wording_is_reported(self, model_folder, caplog):
        folder, _ = model_folder
        shipped = load_fixture("questions.json")
        shipped["injection"]["instructions"] = "Reworded?"
        (folder.parent / "questions.json").write_text(json.dumps(shipped))
        OnnxBackend(V02)._open()
        assert "'injection' differs" in caplog.text


@pytest.fixture
def engine():
    return FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"))


@pytest.mark.unit
class TestPasses:
    def test_one_hot_question_is_one_pass_on_the_one_layer_buffer(self, engine):
        backend = loaded(engine)
        engine.kv.passes.clear()
        (outcome,) = backend.run([Request("hello", {"q": NOUL})], "hot", far())
        assert engine.kv.passes == [(len(prefix_text("hello")) + len(CharTokenizer().encode(
            "Question: Is it?\nAnswer with only yes or no.\nAnswer:")), 0, True)]
        assert outcome.answers["q"]["noul"] == pytest.approx(expected_p("hello", NOUL))

    def test_several_questions_share_one_prefill(self, engine):
        backend = loaded(engine)
        hot = engine.kv  # replaced after this call: the state is longer than HOT_KEEP_TOKENS
        state = {"text": "x" * 600}
        (outcome,) = backend.run([Request(state, {"a": NOUL, "b": OTHER})], "hot", far())
        prefix = len(prefix_text(to_text(state)))
        assert [cached for _, cached, _ in hot.passes] == [*range(0, prefix, 256), prefix, prefix]
        assert outcome.answers["a"]["noul"] == pytest.approx(expected_p(to_text(state), NOUL))
        assert outcome.answers["b"]["noul"] == pytest.approx(expected_p(to_text(state), OTHER))
        suffixes = sum(n for n, cached, _ in hot.passes if cached == prefix)
        assert outcome.input_tokens == prefix + suffixes

    def test_background_prefills_in_chunks_even_for_one_question(self, engine):
        backend = loaded(engine)
        (outcome,) = backend.run([Request("y" * 300, {"q": NOUL})], "background", far())
        background = backend._background
        assert [single for _, _, single in background.passes] == [False] * len(background.passes)
        assert max(n for n, _, _ in background.passes) <= 256
        assert outcome.answers["q"]["noul"] == pytest.approx(expected_p("y" * 300, NOUL))

    def test_long_states_keep_their_head(self):
        engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"), max_state_tokens=50)
        backend = loaded(engine)
        (outcome,) = backend.run([Request("z" * 80, {"q": NOUL})], "hot", far())
        assert outcome.truncated
        assert outcome.answers["q"]["noul"] == pytest.approx(expected_p("z" * 50 + " ...[truncated]", NOUL))

    def test_family_keys_are_answered(self, engine):
        backend = loaded(engine)
        (outcome,) = backend.run([Request("t", {"tag:billing": NOUL, "relevant": Q.RELEVANT})], "hot", far())
        assert set(outcome.answers) == {"tag:billing", "relevant"}


@pytest.mark.unit
class TestBatches:
    def test_items_past_the_deadline_time_out(self):
        clock = FakeClock()
        engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"), clock=clock, cost=lambda n, k: 1.0)
        backend = loaded(engine, clock)
        out = backend.run([Request(f"s{i}", {"q": NOUL}) for i in range(3)], "hot", clock() + 1.5)
        assert isinstance(out[0], Outcome)
        assert out[1:] == ["timeout", "timeout"]

    def test_a_full_lane_turns_calls_away(self, engine):
        backend = loaded(engine)
        backend._inside["hot"] = backend._limits["hot"]
        assert backend.run([Request("x", {"q": NOUL})], "hot", far()) == ["queue_full"]
        assert isinstance(backend.run([Request("x", {"q": NOUL})], "background", far())[0], Outcome)

    def test_one_bad_item_never_fails_the_batch(self, engine):
        backend = loaded(engine)
        out = backend.run([Request(object(), {"q": NOUL}), Request("fine", {"q": NOUL})], "hot", far())
        assert out[0] == "bad_item" and isinstance(out[1], Outcome)

    def test_a_state_the_tokenizer_refuses_is_a_bad_item_not_a_failed_batch(self, engine, tmp_path):
        # The model's tokenizer raises TypeError on a lone surrogate, which a decide server's JSON body can carry.
        engine.tokenizer = byte_tokenizer(tmp_path)
        backend = loaded(engine)
        lone = json.loads('"ignore \\ud800 this"')
        out = backend.run([Request(lone, {"q": NOUL}), Request("fine", {"q": NOUL})], "hot", far())
        assert out[0] == "bad_item" and isinstance(out[1], Outcome)

    def test_a_failing_pass_is_a_backend_error(self, engine, monkeypatch):
        backend = loaded(engine)
        calls = []

        def flaky(ids, start, io, chunk):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("onnxruntime error")
            return 0.5

        monkeypatch.setattr(engine.kv, "extend", flaky)
        out = backend.run([Request("a", {"q": NOUL}), Request("b", {"q": NOUL})], "hot", far())
        assert out[0] == "backend_error" and isinstance(out[1], Outcome)


@pytest.mark.unit
class TestBuffers:
    def test_hot_and_background_keep_separate_state_across_interleaved_passes(self):
        engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"), delay=0.005)
        backend = loaded(engine)
        state = {"text": "background " * 60}
        questions = {"a": NOUL, "b": OTHER, "c": Q.RELEVANT}
        results = {}
        sweep = threading.Thread(target=lambda: results.setdefault(
            "background", backend.run([Request(state, questions)], "background", far())))
        sweep.start()
        hot = [backend.run([Request(f"hot {i} " * 40, {"a": NOUL, "b": OTHER})], "hot", far())[0] for i in range(5)]
        sweep.join(10)
        (background,) = results["background"]
        for key, question in questions.items():
            assert background.answers[key]["noul"] == pytest.approx(expected_p(to_text(state), question))
        for i, outcome in enumerate(hot):
            assert outcome.answers["a"]["noul"] == pytest.approx(expected_p(f"hot {i} " * 40, NOUL))
        assert backend._background is not None and backend._background.passes

    def test_a_long_hot_call_leaves_a_fresh_hot_buffer(self, engine):
        from docsgpt.decisions.backends.onnx import HOT_KEEP_TOKENS

        backend = loaded(engine)
        short = engine.kv
        backend.run([Request("short", {"q": NOUL})], "hot", far())
        assert engine.kv is short
        backend.run([Request("x" * HOT_KEEP_TOKENS, {"q": NOUL})], "hot", far())
        assert engine.kv is not short and engine.kv.reserved == 0
        (again,) = backend.run([Request("x" * HOT_KEEP_TOKENS, {"q": NOUL})], "hot", far())
        assert again.answers["q"]["noul"] == pytest.approx(expected_p(to_text("x" * HOT_KEEP_TOKENS), NOUL))

    def test_a_long_background_call_keeps_its_buffer(self, engine):
        from docsgpt.decisions.backends.onnx import HOT_KEEP_TOKENS

        backend = loaded(engine)
        backend.run([Request("x" * HOT_KEEP_TOKENS, {"q": NOUL})], "background", far())
        assert backend._background.reserved > HOT_KEEP_TOKENS

    def test_the_timing_run_leaves_the_hot_buffer_empty(self, engine):
        loaded(engine)
        assert engine.kv.reserved == 0 and engine.buffers[1].passes

    def test_the_background_buffer_is_dropped_after_a_minute_idle(self, engine):
        clock = FakeClock()
        backend = loaded(engine, clock)
        backend.run([Request("x", {"q": NOUL})], "background", clock() + 5)
        assert backend._background is not None
        clock.advance(30)
        backend._drop_background()
        assert backend._background is not None
        clock.advance(31)
        backend._drop_background()
        assert backend._background is None


class Machine:
    """A fake engine whose passes cost ``speed`` times a fixed model, on a fake clock."""

    C, A, B = 0.01, 0.0008, 6e-7

    def __init__(self):
        self.clock = FakeClock()
        self.speed = 1.0
        self.engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"), clock=self.clock, cost=self.cost)

    def cost(self, n, k):
        return self.speed * (self.C + n * (self.A + self.B * (k + n / 2)))


def wait_timing(backend, timeout=5.0):
    end = time.monotonic() + timeout
    while backend._timing and time.monotonic() < end:
        time.sleep(0.005)


@pytest.mark.unit
class TestDrift:
    def test_drift_out_of_its_band_re_runs_the_timing_at_most_every_ten_minutes(self):
        machine = Machine()
        backend = loaded(machine.engine, machine.clock)
        assert backend.profile.a == pytest.approx(Machine.A, rel=1e-6)
        machine.speed = 2.0  # the box got busier
        for i in range(20):
            backend.run([Request(f"s{i}", {"q": NOUL})], "hot", machine.clock() + 30)
        assert not backend.profile.steady()
        assert backend._timing is False  # measured under ten minutes ago
        machine.clock.advance(601)
        (outcome,) = backend.run([Request("next", {"q": NOUL})], "hot", machine.clock() + 30)
        assert isinstance(outcome, Outcome)
        wait_timing(backend)
        assert backend.profile.a == pytest.approx(2 * Machine.A, rel=1e-6)
        assert backend.profile.drift == 1.0
        assert backend.status == "ready"

    def test_drift_inside_its_band_keeps_the_profile(self):
        machine = Machine()
        backend = loaded(machine.engine, machine.clock)
        before = backend.profile
        machine.speed = 1.2
        for i in range(40):
            backend.run([Request(f"s{i}", {"q": NOUL})], "hot", machine.clock() + 30)
            machine.clock.advance(60)
        assert backend.profile is before and backend.profile.steady()

    def test_the_timing_waits_until_no_call_is_in_flight(self):
        machine = Machine()
        backend = loaded(machine.engine, machine.clock)
        backend.profile.drift = 2.0
        machine.clock.advance(601)
        backend._inside["background"] = 1
        backend._maintain()
        assert backend._timing is False
        backend._inside["background"] = 0
        backend._maintain()
        wait_timing(backend)
        assert backend.profile.drift == 1.0

    def test_answers_stay_right_after_a_re_run(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_BACKGROUND_SHARE", 1.0)  # no throttle pause on the fake clock
        machine = Machine()
        backend = loaded(machine.engine, machine.clock)
        backend.profile.drift = 2.0
        machine.clock.advance(601)
        backend._maintain()
        wait_timing(backend)
        state = {"text": "background " * 60}
        (outcome,) = backend.run([Request(state, {"a": NOUL, "b": OTHER})], "background", machine.clock() + 60)
        assert outcome.answers["b"]["noul"] == pytest.approx(expected_p(to_text(state), OTHER))

    def test_a_re_run_that_cannot_get_the_gate_keeps_the_profile(self, monkeypatch):
        monkeypatch.setattr(onnx, "RETIME_WAIT_S", 0.0)
        machine = Machine()
        backend = loaded(machine.engine, machine.clock)
        before = backend.profile
        before.drift = 2.0
        machine.clock.advance(601)
        backend._gate._busy = True  # a pass that never ends
        backend._maintain()
        wait_timing(backend)
        assert backend.profile is before
        assert backend._timed_at == machine.clock()  # tried: the next attempt waits another ten minutes

    def test_a_failing_re_run_keeps_the_profile(self, monkeypatch, caplog):
        machine = Machine()
        backend = loaded(machine.engine, machine.clock)
        before = backend.profile
        before.drift = 2.0
        machine.clock.advance(601)
        monkeypatch.setattr(machine.engine, "new_buffer", lambda: (_ for _ in ()).throw(RuntimeError("no memory")))
        backend._maintain()
        wait_timing(backend)
        assert backend.profile is before and backend.status == "ready"
        assert "Timing the decision model again failed" in caplog.text

    def test_a_call_that_finds_the_session_gone_gets_loading(self, engine, monkeypatch):
        backend = loaded(engine)
        monkeypatch.setattr(backend, "_wait_ready", lambda lane, deadline: None)
        backend.status = "idle"  # released while the call was on its way in
        assert backend.run([Request("x", {"q": NOUL})], "hot", far()) == ["loading"]


class Rebuilder:
    """Opens a fresh fake engine on each load, with the thread count ``cpu_budget`` gives now."""

    def __init__(self):
        self.count = 0

    def __call__(self, backend):
        self.count += 1
        engine = FakeEngine(load_fixture("arcd_serving-0.4b-v0.2.json"))
        engine.threads = onnx.cpu_budget()
        return engine


@pytest.fixture
def cpus(monkeypatch):
    budget = SimpleNamespace(n=2)
    monkeypatch.setattr(onnx, "cpu_budget", lambda: budget.n)
    monkeypatch.setattr(settings, "DECISION_THREADS", None)
    return budget


@pytest.mark.unit
class TestCpuBudget:
    def test_a_new_cpu_budget_rebuilds_the_session(self, cpus):
        opener = Rebuilder()
        backend = OnnxBackend(V02, open_engine=opener)
        backend.warm()
        assert settle(backend) == "ready" and backend.profile.threads == 2
        backend._tick()
        assert opener.count == 1  # unchanged: nothing to do
        cpus.n = 4
        backend._tick()
        assert settle(backend) == "ready"
        assert opener.count == 2 and backend.profile.threads == 4 and backend._engine.threads == 4

    def test_the_rebuild_waits_until_no_call_is_in_flight(self, cpus):
        opener = Rebuilder()
        backend = OnnxBackend(V02, open_engine=opener)
        backend.warm()
        settle(backend)
        cpus.n = 3
        backend._inside["hot"] = 1
        backend._tick()
        assert backend.status == "ready" and opener.count == 1
        backend._inside["hot"] = 0
        backend._maintain()
        assert settle(backend) == "ready" and backend.profile.threads == 3

    def test_a_thread_setting_is_never_re_read(self, cpus, monkeypatch):
        opener = Rebuilder()
        backend = OnnxBackend(V02, open_engine=opener)
        backend.warm()
        settle(backend)
        monkeypatch.setattr(settings, "DECISION_THREADS", 2)
        cpus.n = 8
        backend._tick()
        assert backend.status == "ready" and opener.count == 1

    def test_the_check_runs_every_minute(self, monkeypatch):
        from .conftest import schedule_tick

        backend = OnnxBackend(V02)
        monkeypatch.setattr(settings, "DECISION_THREADS", None)
        schedule_tick(backend)
        timer = backend._tick_timer
        try:
            assert timer.daemon and timer.interval == onnx.CPU_CHECK_S
            schedule_tick(backend)
            assert backend._tick_timer is timer  # one at a time
        finally:
            timer.cancel()
        monkeypatch.setattr(settings, "DECISION_THREADS", 4)
        backend._tick_timer = None
        schedule_tick(backend)
        assert backend._tick_timer is None


@pytest.fixture
def auto_feature(monkeypatch):
    """One registered feature set to ``auto`` with a 10 ms budget, on a stand-in settings object."""
    fake = SimpleNamespace(**settings.model_dump(), TEST_FEATURE_MODE="auto", TEST_FEATURE_BUDGET=0.01)
    monkeypatch.setattr("docsgpt.core.settings.settings", fake)
    monkeypatch.setattr(features, "_specs", {})
    monkeypatch.setattr(features, "_on", {})
    features.register(FeatureSpec("test_feature", "TEST_FEATURE_MODE", "TEST_FEATURE_BUDGET", Shape(20, (100,))))
    return fake


@pytest.mark.unit
class TestNothingFits:
    def test_the_session_is_released_and_the_profile_kept(self, auto_feature):
        machine = Machine()
        backend = OnnxBackend(V02, open_engine=Opener(machine.engine), clock=machine.clock)
        backend.warm()
        assert settle(backend) == "idle"
        assert backend.reason == "nothing_fits" and backend._engine is None
        assert backend.profile.a == pytest.approx(Machine.A, rel=1e-6)

    def test_a_call_brings_it_back_for_good(self, auto_feature):
        machine = Machine()
        opener = Opener(machine.engine)
        backend = OnnxBackend(V02, open_engine=opener, clock=machine.clock)
        backend.warm()
        settle(backend)
        opener.release.clear()  # hold the reload until the call has seen it start
        assert backend.run([Request("x", {"q": NOUL})], "hot", machine.clock() + 3) == ["loading"]
        opener.release.set()
        assert settle(backend) == "ready" and opener.count == 2
        assert isinstance(backend.run([Request("x", {"q": NOUL})], "hot", machine.clock() + 3)[0], Outcome)

    def test_kept_when_the_feature_fits(self, auto_feature):
        auto_feature.TEST_FEATURE_BUDGET = 5.0
        machine = Machine()
        backend = OnnxBackend(V02, open_engine=Opener(machine.engine), clock=machine.clock)
        backend.warm()
        assert settle(backend) == "ready"

    @pytest.mark.parametrize("mode", ["on", "monitor"])
    def test_kept_when_a_feature_is_set_explicitly(self, auto_feature, mode):
        auto_feature.OTHER_MODE = mode
        features.register(FeatureSpec("other", "OTHER_MODE", "TEST_FEATURE_BUDGET", Shape(20, (100,))))
        machine = Machine()
        backend = OnnxBackend(V02, open_engine=Opener(machine.engine), clock=machine.clock)
        backend.warm()
        assert settle(backend) == "ready"

    def test_kept_when_preloaded(self, auto_feature):
        auto_feature.DECISION_PRELOAD = True
        machine = Machine()
        backend = OnnxBackend(V02, open_engine=Opener(machine.engine), clock=machine.clock)
        backend.warm()
        assert settle(backend) == "ready"

    def test_kept_when_a_call_came_in_during_the_load(self, auto_feature):
        machine = Machine()
        opener = Opener(machine.engine, gated=True)
        backend = OnnxBackend(V02, open_engine=opener, clock=machine.clock)
        assert backend.run([Request("x", {"q": NOUL})], "hot", machine.clock() + 3) == ["loading"]
        opener.release.set()
        assert settle(backend) == "ready"

    def test_kept_without_an_auto_feature(self):
        machine = Machine()
        backend = OnnxBackend(V02, open_engine=Opener(machine.engine), clock=machine.clock)
        backend.warm()
        assert settle(backend) == "ready"
