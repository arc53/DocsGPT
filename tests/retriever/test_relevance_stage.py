"""Tests for the decision-model relevance stage: the rerank, the decision prescreen and their fallbacks."""

from __future__ import annotations

import dataclasses

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Q, record
from docsgpt.decisions.latency import SpeedProfile
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.decisions.types import BatchResult
from docsgpt.retriever.stages.relevance import (
    QUERY_CHARS,
    RelevancePolicy,
    RelevanceStage,
    base_selection,
    instance_mode,
    rollout_on,
    score_relevance,
    source_mode,
)
from docsgpt.storage.db.source_config import RerankerConfig


def by_passage(scores):
    """A scripted ``relevant`` answer read off the passage text."""
    return {"relevant": lambda state, question: scores[state["passage"]]}


def docs(*texts, base=None, source="s1"):
    out = [{"text": t, "source_id": source} for t in texts]
    if base is not None:
        for doc, flag in zip(out, base):
            doc["_base"] = flag
    return out


def rerank(**overrides):
    return RelevanceStage(RelevancePolicy(**{"keep": None, "threshold": 0.0, "min_keep": 1, **overrides}))


class Partial(FakeDecider):
    """Answers every state but the last."""

    def decide_batch(self, requests, *, feature, budget):
        full = super().decide_batch(requests, feature=feature, budget=budget)
        return BatchResult(list(full[:-1]) + [None], [None] * (len(full) - 1) + ["timeout"])


class WordTokenizer:
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
def entries():
    rec = record.DecisionRecord()
    with record.activate(rec):
        yield rec._doc["entries"]


@pytest.mark.unit
class TestRerank:
    def test_orders_by_relevance_with_stable_ties(self):
        fake = FakeDecider(by_passage({"a": 0.2, "b": 0.9, "c": 0.2, "d": 0.5}))
        with installed(fake):
            out = rerank()(docs("a", "b", "c", "d"), {"query": "q"})
        assert [d["text"] for d in out] == ["b", "d", "a", "c"]
        assert [d["relevance"] for d in out] == [0.9, 0.5, 0.2, 0.2]

    def test_keeps_as_many_as_the_usual_selection(self):
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.2, "c": 0.9, "d": 0.8}))
        with installed(fake):
            out = rerank()(docs("a", "b", "c", "d", base=[True, True, False, False]), {"query": "q"})
        assert [d["text"] for d in out] == ["c", "d"]

    def test_threshold_keeps_min_keep(self):
        fake = FakeDecider(by_passage({"a": 0.05, "b": 0.1, "c": 0.4}))
        with installed(fake):
            assert [d["text"] for d in rerank(threshold=0.3)(docs("a", "b", "c"), {"query": "q"})] == ["c"]
            assert [d["text"] for d in rerank(threshold=0.5)(docs("a", "b", "c"), {"query": "q"})] == ["c"]
            assert rerank(threshold=0.5, min_keep=0)(docs("a", "b", "c"), {"query": "q"}) == []
            two = rerank(threshold=0.5, min_keep=2)(docs("a", "b", "c"), {"query": "q"})
            assert [d["text"] for d in two] == ["c", "b"]

    def test_keep_caps(self):
        fake = FakeDecider(by_passage({"a": 0.3, "b": 0.9, "c": 0.6}))
        with installed(fake):
            out = rerank(keep=2)(docs("a", "b", "c"), {"query": "q"})
        assert [d["text"] for d in out] == ["b", "c"]

    def test_per_source_thresholds(self):
        fake = FakeDecider(by_passage({"a": 0.4, "b": 0.4}))
        both = docs("a", source="strict") + docs("b", source="lenient")
        with installed(fake):
            out = rerank(threshold=0.1, min_keep=0, thresholds_by_source={"strict": 0.5})(both, {"query": "q"})
        assert [d["text"] for d in out] == ["b"]

    def test_judges_the_search_query(self):
        fake = FakeDecider(by_passage({"a": 0.5}))
        with installed(fake):
            rerank()(docs("a"), {"query": "and on Windows?", "search_query": "install on Windows"})
        (request,) = fake.calls[0].requests
        assert request.state == {"query": "install on Windows", "passage": "a"}

    def test_states_and_question(self):
        fake = FakeDecider(by_passage({"a": 0.5, "b": 0.5}))
        long_query = "x" * (QUERY_CHARS + 50)
        with installed(fake):
            rerank()(docs("a", "b"), {"query": long_query})
        (call,) = fake.calls
        assert call.feature == "rag_rerank" and call.budget.lane == "hot"
        assert call.budget.seconds == settings.DECISION_RELEVANCE_TIMEOUT
        assert [r.state for r in call.requests] == [{"query": "x" * QUERY_CHARS, "passage": t} for t in "ab"]
        assert all(r.questions == {"relevant": Q.RELEVANT} for r in call.requests)

    def test_caps_the_states_per_call(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_RELEVANCE_MAX_PASSAGES", 2)
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.2, "c": 0.9}))
        with installed(fake):
            out = rerank(keep=3)(docs("a", "b", "c"), {"query": "q"})
        assert len(fake.calls[0].requests) == 2
        assert [d["text"] for d in out] == ["b", "a"]

    def test_top_relevance_in_the_context(self):
        fake = FakeDecider(by_passage({"a": 0.3, "b": 0.71234}))
        context = {"query": "q"}
        with installed(fake):
            rerank()(docs("a", "b"), context)
        assert context["top_relevance"] == 0.7123

    def test_empty_input_calls_nothing(self):
        fake = FakeDecider()
        with installed(fake):
            assert rerank()([], {"query": "q"}) == []
        assert fake.calls == []


@pytest.mark.unit
class TestFallback:
    """Any answer short of every candidate scored returns the usual selection, untouched."""

    POOL = ("p0", "p1", "p2", "p3")

    def candidates(self):
        return docs(*self.POOL, base=[False, True, False, True])

    @pytest.mark.parametrize("reason", ["off", "loading", "circuit_open", "timeout"])
    def test_failed_calls_return_the_usual_selection(self, reason, entries):
        context = {"query": "q"}
        with installed(FakeDecider(reasons={"*": reason})):
            out = rerank()(self.candidates(), context)
        assert [d["text"] for d in out] == ["p1", "p3"]
        assert all("relevance" not in d for d in out)
        assert context["top_relevance"] is None
        (entry,) = entries
        assert entry["status"] == ("timeout" if reason == "timeout" else "unavailable")
        assert entry["applied"] is False and entry["outcome"]["top"] is None

    def test_a_partial_answer_is_no_answer(self, entries):
        with installed(Partial({"relevant": 0.9})):
            out = rerank()(self.candidates(), {"query": "q"})
        assert [d["text"] for d in out] == ["p1", "p3"]
        assert entries[0]["status"] == "timeout"

    def test_no_query_calls_nothing(self, entries):
        fake = FakeDecider()
        with installed(fake):
            out = rerank()(self.candidates(), {"query": ""})
        assert [d["text"] for d in out] == ["p1", "p3"] and fake.calls == []
        assert entries[0]["status"] == "skipped"

    def test_an_error_never_escapes(self, entries, monkeypatch):
        fake = FakeDecider()
        monkeypatch.setattr(fake, "decide_batch", lambda *a, **k: 1 / 0)
        with installed(fake):
            out = rerank()(self.candidates(), {"query": "q"})
        assert [d["text"] for d in out] == ["p1", "p3"]
        assert entries[0]["status"] == "error"

    def test_the_prescreen_falls_back_to_its_cap(self):
        with installed(FakeDecider(reasons={"*": "off"})):
            out = rerank(keep=2, feature="rag_prescreen")(docs("a", "b", "c"), {"query": "q"})
        assert [d["text"] for d in out] == ["a", "b"]

    def test_an_untagged_list_is_all_selection(self):
        assert base_selection(docs("a", "b")) == docs("a", "b")
        assert [d["text"] for d in base_selection(docs("a", "b", base=[False, True]))] == ["b"]


@pytest.mark.unit
class TestMonitor:
    def test_scores_records_and_returns_the_usual_selection(self, entries):
        fake = FakeDecider(by_passage({"p0": 0.9, "p1": 0.1, "p2": 0.8}))
        context = {"query": "q"}
        with installed(fake):
            out = rerank(mode="monitor", arm="on")(docs("p0", "p1", "p2", base=[False, True, True]), context)
        assert [d["text"] for d in out] == ["p1", "p2"]
        assert all("relevance" not in d for d in out)
        assert context["top_relevance"] == 0.9
        (entry,) = entries
        assert entry["applied"] is False and entry["status"] == "ok"
        # Would have kept p0 and p2: one doc the usual selection lacks.
        assert entry["outcome"]["kept"] == 2 and entry["outcome"]["replaced"] == 1


@pytest.mark.unit
class TestRecord:
    def test_one_entry_of_scalars_per_call(self, entries):
        fake = FakeDecider(by_passage({"p0": 0.9, "p1": 0.2, "p2": 0.6}))
        context = {"query": "and on Windows?", "search_query": "install on Windows"}
        with installed(fake):
            rerank(arm="on")(docs("p0", "p1", "p2", base=[False, True, True]), context)
        (entry,) = entries
        assert entry["feature"] == "rag_rerank" and entry["status"] == "ok" and entry["applied"] is True
        assert entry["outcome"] == {
            "candidates": 3, "kept": 2, "replaced": 1, "top": 0.9, "threshold": 0.0, "query_source": "rephrased",
            "arm": "on", "passage_select": "full", "passage_tokens": None,
        }
        assert "ms" in entry


@pytest.mark.unit
class TestCpuProfile:
    @pytest.fixture
    def cpu(self, monkeypatch):
        fake = FakeDecider({"relevant": 0.5}, tokenizer=WordTokenizer())
        fake.info = dataclasses.replace(fake.info, runtime="onnx-int8")
        monkeypatch.setattr(settings, "DECISION_RELEVANCE_CPU_PASSAGE_TOKENS", 128)
        return fake

    def test_passages_are_cut_to_their_best_window_and_recorded(self, cpu, entries):
        filler = " ".join(f"x{i}" for i in range(300))
        head = " ".join(f"h{i}" for i in range(64))
        with installed(cpu):
            rerank()(docs(f"{head} {filler} rotate the key now", "short"), {"query": "rotate key"})
        long, short = (r.state["passage"] for r in cpu.calls[0].requests)
        assert len(long.split(" ")) <= 128 and long.startswith("h0 h1") and short == "short"
        assert entries[0]["outcome"]["passage_select"] == "best"
        assert entries[0]["outcome"]["passage_tokens"] == 128

    def test_before_the_tokenizer_loads_nothing_is_sent(self, cpu, entries):
        cpu.tokenizer = None
        with installed(cpu):
            out = rerank()(docs("a", "b"), {"query": "q"})
        assert cpu.calls == [] and cpu.warmed == 1
        assert [d["text"] for d in out] == ["a", "b"]
        assert entries[0]["status"] == "unavailable"

    def test_gpu_and_api_runtimes_score_whole_chunks(self):
        fake = FakeDecider({"relevant": 0.5}, tokenizer=WordTokenizer())
        fake.info = dataclasses.replace(fake.info, runtime="vllm")
        text = " ".join(f"w{i}" for i in range(1000))
        with installed(fake):
            score_relevance(docs(text), "q", feature="rag_rerank", budget=Budget.hot(1.0))
        assert fake.calls[0].requests[0].state["passage"] == text


@pytest.mark.unit
class TestTracing:
    @pytest.fixture
    def trace(self, monkeypatch):
        monkeypatch.setattr(settings, "TRACES_ENABLED", True)
        t = tracing.start_trace(source="stream", capture_otel_context=False)
        with tracing.activate(t):
            yield t

    def test_rerank_span_wraps_the_decision_call(self, trace):
        fake = FakeDecider(by_passage({"a": 0.2, "b": 0.8}))
        real = fake.decide_batch

        def traced(requests, *, feature, budget):
            # The real client opens its own leaf span; it must land under the stage's.
            with tracing.span(tracing.KIND_DECISION, f"decision {feature}"):
                return real(requests, feature=feature, budget=budget)

        fake.decide_batch = traced
        with installed(fake):
            rerank(mode="on", arm="on")(docs("a", "b"), {"query": "q"})
        rerank_span = next(s for s in trace.spans if s.kind == tracing.KIND_RERANK)
        leaf = next(s for s in trace.spans if s.kind == tracing.KIND_DECISION)
        assert rerank_span.name == "rerank relevance" and leaf.parent_id == rerank_span.id
        assert rerank_span.attributes == {
            "gen_ai.operation.name": "rerank", "docsgpt.rerank.backend": "decision", "docsgpt.rerank.mode": "on",
            "docsgpt.rerank.feature": "rag_rerank", "docsgpt.rerank.arm": "on", "docsgpt.candidate_count": 2,
            "docsgpt.relevance_threshold": 0.0, "docsgpt.query_source": "raw", "docsgpt.kept_count": 2,
            "docsgpt.top_relevance": 0.8, "docsgpt.relevance.passage_select": "full",
        }

    def test_a_fallback_is_on_the_span(self, trace):
        with installed(FakeDecider(reasons={"*": "circuit_open"})):
            rerank()(docs("a"), {"query": "q"})
        rerank_span = next(s for s in trace.spans if s.kind == tracing.KIND_RERANK)
        assert rerank_span.attributes["docsgpt.decision.fallback"] == "circuit_open"


@pytest.mark.unit
class TestModes:
    def test_rollout_is_deterministic_by_key(self):
        assert rollout_on(None, 100) and rollout_on("c", 100)
        assert not rollout_on("c", 0) and not rollout_on(None, 50)
        arms = [rollout_on(f"conversation-{i}", 50) for i in range(400)]
        assert arms == [rollout_on(f"conversation-{i}", 50) for i in range(400)]
        assert 150 < sum(arms) < 250
        assert all(rollout_on(f"conversation-{i}", 80) for i, on in enumerate(arms) if on)

    @pytest.mark.parametrize("mode", ["off", "monitor", "on"])
    def test_explicit_modes(self, monkeypatch, mode):
        monkeypatch.setattr(settings, "DECISION_RERANK_MODE", mode)
        with installed(FakeDecider()):
            assert instance_mode() == mode

    def test_mode_none_is_off(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_RERANK_MODE", "on")
        assert instance_mode() == "off"  # the tests run with DECISION_MODE=none

    def test_auto_follows_the_measured_verdict(self, monkeypatch):
        from docsgpt.decisions import features

        monkeypatch.setattr(settings, "DECISION_RERANK_MODE", "auto")
        fast = SpeedProfile(c=0.001, a=0.00001, b=0.0, overhead=50, threads=4, measured_at=0.0)
        slow = SpeedProfile(c=0.05, a=0.005, b=0.0, overhead=50, threads=4, measured_at=0.0)
        features.reset()
        with installed(FakeDecider(profile=fast)):
            assert instance_mode() == "on"
        features.reset()
        with installed(FakeDecider(profile=slow)):
            assert instance_mode() == "off"
        features.reset()
        unmeasured = FakeDecider()
        with installed(unmeasured):
            assert instance_mode() == "off" and unmeasured.warmed == 1
        features.reset()

    def test_auto_predicts_best_windows_on_a_cpu(self, monkeypatch):
        from docsgpt.decisions import features
        from docsgpt.decisions.features import RAG_RERANK

        fake = FakeDecider()
        with installed(fake):
            whole = features.shape_of(RAG_RERANK)
            fake.info = dataclasses.replace(fake.info, runtime="onnx-int8")
            windows = features.shape_of(RAG_RERANK)
        assert whole.states == windows.states == settings.DECISION_RERANK_CANDIDATE_K
        assert windows.state_tokens == settings.DECISION_RELEVANCE_CPU_PASSAGE_TOKENS + 64 < whole.state_tokens

    def test_source_modes(self):
        assert source_mode("classic", None, "on", True) == ("on", "on")
        assert source_mode("hybrid", None, "monitor", True) == ("monitor", "on")
        assert source_mode("classic", None, "on", False) == ("off", "control")
        assert source_mode("classic", None, "off", True) == ("off", None)
        assert source_mode("graphrag", None, "on", True) == ("off", None)
        assert source_mode("classic", RerankerConfig(type="off"), "on", True) == ("off", None)

    def test_a_source_opts_in_only_while_the_operator_has_the_rerank_on(self):
        # On: beyond the instance's retrievers and outside the rollout.
        assert source_mode("graphrag", RerankerConfig(), "on", True) == ("on", "source")
        assert source_mode("classic", RerankerConfig(), "monitor", False) == ("on", "source")
        # Off: a stored opt-in is the same as opting out.
        assert source_mode("graphrag", RerankerConfig(), "off", True) == ("off", None)
        assert source_mode("classic", RerankerConfig(min_relevance=0.3), "off", True) == ("off", None)

    def test_the_prescreen_gate(self, monkeypatch):
        from docsgpt.retriever.stages.relevance import decision_prescreen_enabled

        with installed(FakeDecider()):
            assert decision_prescreen_enabled() is False
            monkeypatch.setattr(settings, "DECISION_PRESCREEN_ENABLED", True)
            assert decision_prescreen_enabled() is True
        assert decision_prescreen_enabled() is False  # the tests run with DECISION_MODE=none


@pytest.mark.unit
class TestSettings:
    def test_defaults(self):
        from docsgpt.core.settings import Settings

        fresh = Settings(_env_file=None)
        assert (fresh.DECISION_RERANK_MODE, fresh.DECISION_RERANK_BUDGET, fresh.DECISION_RERANK_ROLLOUT_PERCENT) == (
            "off", 3.0, 100
        )
        assert fresh.DECISION_RERANK_RETRIEVERS == ["classic", "hybrid"]
        assert (fresh.DECISION_RERANK_CANDIDATE_K, fresh.DECISION_RERANK_THRESHOLD) == (20, 0.0)
        assert fresh.DECISION_RERANK_CANDIDATE_TOKENS == 60000
        assert (fresh.DECISION_PRESCREEN_THRESHOLD, fresh.DECISION_RELEVANCE_MIN_KEEP) == (0.2, 1)
        assert (fresh.DECISION_RELEVANCE_MAX_PASSAGES, fresh.DECISION_RELEVANCE_TIMEOUT) == (100, 2.0)
        assert fresh.DECISION_RELEVANCE_CPU_PASSAGE_TOKENS == 256
        assert fresh.DECISION_PRESCREEN_ENABLED is False

    def test_retrievers_read_a_comma_list(self, monkeypatch):
        from docsgpt.core.settings import Settings

        monkeypatch.setenv("DECISION_RERANK_RETRIEVERS", "classic, graphrag")
        monkeypatch.setenv("DECISION_RERANK_MODE", "AUTO")
        fresh = Settings(_env_file=None)
        assert fresh.DECISION_RERANK_RETRIEVERS == ["classic", "graphrag"] and fresh.DECISION_RERANK_MODE == "auto"

    def test_rag_rerank_is_a_registered_feature(self):
        from docsgpt.decisions import features

        spec = next(s for s in features.specs() if s.name == "rag_rerank")
        assert (spec.mode_setting, spec.budget_setting) == ("DECISION_RERANK_MODE", "DECISION_RERANK_BUDGET")
