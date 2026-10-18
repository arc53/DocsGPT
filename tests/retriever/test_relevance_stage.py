"""Tests for the decision-model relevance stage, its fallbacks, its gate and its use without a Dispatcher."""

from __future__ import annotations

import dataclasses

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Q, record
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.decisions.types import BatchResult
from docsgpt.retriever.stages.relevance import (
    QUERY_CHARS,
    RelevancePolicy,
    RelevanceStage,
    apply_relevance,
    base_selection,
    relevance_enabled,
    rollout_on,
    score_relevance,
    source_mode,
)
from docsgpt.storage.db.source_config import DEFAULT_CANDIDATE_K, RerankerConfig


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

    def test_a_narrowed_pool_still_fills_the_usual_selection(self):
        # A stage before this one (the search tool's path filter) dropped both usual chunks.
        fake = FakeDecider(by_passage({"c": 0.2, "d": 0.8, "e": 0.5}))
        with installed(fake):
            out = rerank()(docs("c", "d", "e", base=[False, False, False]), {"query": "q", "selection_size": 2})
        assert [d["text"] for d in out] == ["d", "e"]

    def test_a_narrowed_pool_falls_back_to_what_is_left_of_the_selection(self):
        fake = FakeDecider(reasons={"*": "unavailable"})
        with installed(fake):
            out = rerank()(docs("b", "c", "d", base=[True, False, False]), {"query": "q", "selection_size": 2})
        assert [d["text"] for d in out] == ["b"]

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

    def test_a_capped_policy_falls_back_to_its_cap(self):
        with installed(FakeDecider(reasons={"*": "off"})):
            out = rerank(keep=2)(docs("a", "b", "c"), {"query": "q"})
        assert [d["text"] for d in out] == ["a", "b"]

    def test_an_untagged_list_is_all_selection(self):
        assert base_selection(docs("a", "b")) == docs("a", "b")
        assert [d["text"] for d in base_selection(docs("a", "b", base=[False, True]))] == ["b"]


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
            rerank(arm="on")(docs("a", "b"), {"query": "q"})
        rerank_span = next(s for s in trace.spans if s.kind == tracing.KIND_RERANK)
        leaf = next(s for s in trace.spans if s.kind == tracing.KIND_DECISION)
        assert rerank_span.name == "rerank relevance" and leaf.parent_id == rerank_span.id
        assert rerank_span.attributes == {
            "gen_ai.operation.name": "rerank", "docsgpt.rerank.backend": "decision",
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

    def test_the_operator_switch(self, monkeypatch):
        with installed(FakeDecider()):
            assert relevance_enabled() is False
            monkeypatch.setattr(settings, "DECISION_RELEVANCE_ENABLED", True)
            assert relevance_enabled() is True
        assert relevance_enabled() is False  # the tests run with DECISION_MODE=none

    def test_the_prediction_is_of_best_windows_on_a_cpu(self):
        from docsgpt.decisions import features
        from docsgpt.decisions.features import RAG_RERANK

        fake = FakeDecider()
        with installed(fake):
            whole = features.shape_of(RAG_RERANK)
            fake.info = dataclasses.replace(fake.info, runtime="onnx-int8")
            windows = features.shape_of(RAG_RERANK)
        assert whole.states == windows.states == DEFAULT_CANDIDATE_K
        assert windows.state_tokens == settings.DECISION_RELEVANCE_CPU_PASSAGE_TOKENS + 64 < whole.state_tokens

    def test_source_modes(self):
        # A source without a reranker is off; one with it is on only while the operator lets the model score.
        assert source_mode(None, True, True) == ("off", None)
        assert source_mode(RerankerConfig(), True, True) == ("on", "on")
        assert source_mode(RerankerConfig(min_relevance=0.3), False, True) == ("off", None)
        # Outside the rollout it is the control arm and keeps the retriever's output.
        assert source_mode(RerankerConfig(), True, False) == ("off", "control")
        assert source_mode(None, True, False) == ("off", None)


@pytest.mark.unit
class TestSettings:
    def test_defaults(self):
        from docsgpt.core.settings import Settings

        fresh = Settings(_env_file=None)
        assert fresh.DECISION_RELEVANCE_ENABLED is False
        assert (fresh.DECISION_RELEVANCE_ROLLOUT_PERCENT, fresh.DECISION_RELEVANCE_CANDIDATE_TOKENS) == (100, 60000)
        assert fresh.DECISION_RELEVANCE_MIN_KEEP == 1
        assert (fresh.DECISION_RELEVANCE_MAX_PASSAGES, fresh.DECISION_RELEVANCE_TIMEOUT) == (100, 2.0)
        assert fresh.DECISION_RELEVANCE_CPU_PASSAGE_TOKENS == 256

    def test_rag_rerank_is_the_switch(self, monkeypatch):
        from docsgpt.decisions import features

        monkeypatch.setattr(settings, "DECISION_RELEVANCE_ENABLED", False)
        spec = next(s for s in features.specs() if s.name == "rag_rerank")
        assert (spec.mode_setting, spec.budget_setting) == ("DECISION_RELEVANCE_ENABLED", "DECISION_RELEVANCE_TIMEOUT")
        assert features.configured(spec) == "off" and not features.wanted_at_start()
        monkeypatch.setattr(settings, "DECISION_RELEVANCE_ENABLED", True)
        assert features.configured(spec) == "on" and features.wanted_at_start()
        assert features.effective(spec, True, None)[0] == "on"
        assert features.effective(spec, False, None)[0] == "off"


@pytest.mark.unit
class TestApplyRelevance:
    """Relevance for a caller with no Dispatcher (workflow agent nodes): each source by its own reranker."""

    @pytest.fixture
    def on(self, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_RELEVANCE_ENABLED", True)
        return monkeypatch

    @staticmethod
    def mixed():
        return [
            {"text": "a", "source_id": "s1"}, {"text": "x", "source_id": "s2"},
            {"text": "b", "source_id": "s1"}, {"text": "c", "source_id": "s1"},
        ]

    def test_reorders_a_source_in_its_own_places(self, on, entries):
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.9, "c": 0.4}))
        with installed(fake):
            out = apply_relevance(self.mixed(), "q", {"s1": RerankerConfig()})
        # s2 sets no reranker: its chunk keeps its place and is never sent.
        assert [d["text"] for d in out] == ["b", "x", "c", "a"]
        assert [r.state["passage"] for r in fake.calls[0].requests] == ["a", "b", "c"]
        (entry,) = entries
        assert entry["feature"] == "rag_rerank" and entry["applied"] is True and entry["outcome"]["kept"] == 3

    def test_a_threshold_filters_that_source_only(self, on):
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.9, "c": 0.4}))
        with installed(fake):
            out = apply_relevance(self.mixed(), "q", {"s1": RerankerConfig(min_relevance=0.3)})
        assert [d["text"] for d in out] == ["b", "x", "c"]

    @pytest.mark.parametrize("reason", ["unavailable", "timeout"])
    def test_fails_open_to_the_retriever_order(self, on, reason):
        fake = FakeDecider(reasons={"*": reason})
        with installed(fake):
            out = apply_relevance(docs("a", "b"), "q", {"s1": RerankerConfig()})
        assert fake.calls and [d["text"] for d in out] == ["a", "b"]
        assert not any("relevance" in d for d in out)

    def test_an_unexpected_error_fails_open(self, on, monkeypatch):
        monkeypatch.setattr(RelevanceStage, "__call__", lambda self, d, c: 1 / 0)
        original = docs("a", "b")
        with installed(FakeDecider()):
            assert apply_relevance(original, "q", {"s1": RerankerConfig()}) is original

    def test_the_switch_off_never_calls_the_model(self, monkeypatch, entries):
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.9}))
        original = docs("a", "b")
        with installed(fake):
            assert apply_relevance(original, "q", {"s1": RerankerConfig()}) is original
        assert fake.calls == [] and fake.warmed == 0 and entries == []

    def test_decisions_off_asks_nothing(self, on):
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.9}))
        fake.enabled = False
        with installed(fake):
            assert [d["text"] for d in apply_relevance(docs("a", "b"), "q", {"s1": RerankerConfig()})] == ["a", "b"]
        assert fake.calls == []

    def test_sources_without_a_reranker_ask_nothing(self, on):
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.9}))
        with installed(fake):
            assert [d["text"] for d in apply_relevance(docs("a", "b"), "q", {})] == ["a", "b"]
            assert [d["text"] for d in apply_relevance(docs("a", "b"), "q", {"s9": RerankerConfig()})] == ["a", "b"]
        assert fake.calls == []

    def test_the_control_arm_is_recorded_and_left_alone(self, on, entries):
        on.setattr(settings, "DECISION_RELEVANCE_ROLLOUT_PERCENT", 50)
        key = next(k for k in (f"c{i}" for i in range(100)) if not rollout_on(k, 50))
        fake = FakeDecider(by_passage({"a": 0.1, "b": 0.9}))
        with installed(fake):
            out = apply_relevance(docs("a", "b"), "q", {"s1": RerankerConfig()}, rollout_key=key)
        assert fake.calls == [] and [d["text"] for d in out] == ["a", "b"]
        (entry,) = entries
        assert entry["outcome"] == {"arm": "control"} and entry["status"] == "skipped"

    def test_nothing_to_order_asks_nothing(self, on):
        fake = FakeDecider()
        with installed(fake):
            assert apply_relevance([], "q", {"s1": RerankerConfig()}) == []
            assert [d["text"] for d in apply_relevance(docs("a"), "", {"s1": RerankerConfig()})] == ["a"]
        assert fake.calls == []
