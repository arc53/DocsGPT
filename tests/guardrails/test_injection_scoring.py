"""The prompt-injection scorer: the content-score cache, windows sent to the model, budgets and lazy scoring.

The decision model is ``FakeDecider`` and the cache a dict: no model, no database, no broker.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, usage
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.decisions.types import BatchResult
from docsgpt.guardrails import injection_scoring as scoring
from docsgpt.retriever.labels import chunk_key
from tests.decisions.fakes import byte_tokenizer

#: The cache read as it ships, before the suite-wide fixture replaces it with an empty one.
REAL_LOAD = scoring._load


class CharTokenizer:
    def encode(self, text):
        return [ord(c) for c in text]

    def decode(self, ids):
        return "".join(chr(i) for i in ids)


class Cache:
    """``content_scores`` as a dict keyed by ``(hash, scorer)``."""

    def __init__(self, monkeypatch):
        self.rows: dict = {}
        self.reads = 0
        monkeypatch.setattr(scoring, "_load", self.load)
        monkeypatch.setattr(scoring, "_store", self.store)

    def load(self, hashes, scorer):
        self.reads += 1
        return {h: self.rows[(h, scorer)] for h in hashes if (h, scorer) in self.rows}

    def store(self, rows):
        for row in rows:
            self.rows[(row["content_hash"], row["scorer"])] = {
                k: row[k] for k in ("p", "windows_scored", "windows_total")
            }

    def put(self, text, p, scored=1, total=1, stale=False):
        self.rows[(scoring.content_hash(text), scoring.scorer_id())] = {
            "p": p, "windows_scored": scored, "windows_total": total, "stale": stale
        }


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", True)


@pytest.fixture
def cache(monkeypatch):
    return Cache(monkeypatch)


def score(fake, texts, **kwargs):
    kwargs.setdefault("feature", "injection_retrieval")
    kwargs.setdefault("budget", Budget.hot(1.5))
    with installed(fake):
        return scoring.score(texts, **kwargs)


@pytest.mark.unit
class TestCache:
    def test_a_hit_makes_no_call_and_is_counted_as_cached(self, cache):
        fake = FakeDecider({"injection": 0.99})
        with installed(fake):
            cache.put("known chunk", 0.12)
        result = score(fake, ["known chunk"])
        assert fake.calls == [] and result.cache_hits == 1 and result.live == 0
        assert result[0] == scoring.InjectionScore(0.12, 1, 1, cached=True)
        ((_, feature, mode, _, status), counters), = usage._counts.items()
        assert (feature, mode, status) == ("injection_retrieval", "local", "cached") and counters[1:3] == [1, 1]

    def test_a_miss_is_scored_and_stored(self, cache):
        fake = FakeDecider({"injection": 0.97})
        result = score(fake, ["new chunk"])
        assert len(fake.calls) == 1 and result.live == 1 and result[0].p == pytest.approx(0.97)
        assert not result[0].cached
        assert score(fake, ["new chunk"]).cache_hits == 1 and len(fake.calls) == 1

    def test_a_hit_on_a_row_not_seen_today_is_marked_seen_off_the_request_path(self, cache, monkeypatch):
        touched, queued = [], []
        monkeypatch.setattr(scoring, "_touch", lambda hashes, scorer: touched.append(sorted(hashes)))
        monkeypatch.setattr(scoring, "_touch_later", lambda hashes, scorer: queued.append(sorted(hashes)))
        fake = FakeDecider({"injection": 0.5})
        with installed(fake):
            cache.put("old chunk", 0.1, stale=True)
            cache.put("fresh chunk", 0.1)
        score(fake, ["old chunk", "fresh chunk"])
        # A chat turn only queues it, and only for rows not seen today.
        assert queued == [[scoring.content_hash("old chunk")]] and touched == []
        score(fake, ["old chunk", "fresh chunk"], budget=Budget.BACKGROUND)
        assert touched == [[scoring.content_hash("old chunk")]]
        score(fake, ["fresh chunk"])
        assert len(queued) == 1 and fake.calls == []

    def test_keyed_by_sha256_never_by_the_chunk_key(self, cache):
        score(FakeDecider({"injection": 0.2}), ["some chunk"])
        ((digest, _),) = cache.rows
        assert digest == hashlib.sha256(b"some chunk").hexdigest() and digest != chunk_key("some chunk")

    def test_without_the_cache_nothing_is_read_or_stored(self, cache):
        fake = FakeDecider({"injection": 0.2})
        score(fake, ["a user message"], cache=False)
        assert cache.reads == 0 and cache.rows == {}

    def test_a_row_scored_with_fewer_windows_than_this_call_reads_is_rescored(self, cache, monkeypatch):
        monkeypatch.setattr(scoring, "WINDOW_TOKENS", 10)
        monkeypatch.setattr(scoring, "WINDOW_OVERLAP", 2)
        fake = FakeDecider({"injection": 0.1}, tokenizer=CharTokenizer())
        text = "a" * 42  # five windows
        with installed(fake):
            cache.put(text, 0.1, scored=3, total=5)
        result = score(fake, [text], max_windows=8)
        assert len(fake.calls[0].requests) == 5 and result[0].complete

    def test_an_unreadable_cache_is_a_miss(self, monkeypatch):
        def broken():
            raise RuntimeError("no database")

        monkeypatch.setattr(scoring, "_load", REAL_LOAD)
        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", broken)
        with installed(FakeDecider()):
            assert scoring.lookup(["text"]) == [None]


@pytest.mark.unit
class TestScorerId:
    def test_built_from_the_model_version_question_and_windows(self):
        with installed(FakeDecider(model_version="arc53/m/pabc/cdef")):
            ident = scoring.scorer_id()
        assert ident.startswith("injection:arc53/m/pabc/cdef:q") and ident.endswith(":w512o50")

    def test_changes_with_the_model_the_question_and_the_window(self, monkeypatch):
        with installed(FakeDecider(model_version="a")):
            base = scoring.scorer_id()
        with installed(FakeDecider(model_version="b")):
            assert scoring.scorer_id() != base
        with installed(FakeDecider(model_version="a")):
            monkeypatch.setattr(scoring, "WINDOW_TOKENS", 400)
            assert scoring.scorer_id() != base
            monkeypatch.setattr(scoring, "WINDOW_TOKENS", 512)
            assert scoring.scorer_id() == base
            monkeypatch.setattr(scoring, "QUESTIONS", {"injection": {**scoring.Q.INJECTION, "question": "other?"}})
            assert scoring.scorer_id() != base

    def test_none_without_a_model(self):
        assert scoring.scorer_id() is None

    def test_a_new_model_misses_every_row(self, cache):
        with installed(FakeDecider(model_version="old")):
            cache.put("chunk", 0.2)
        fake = FakeDecider({"injection": 0.2}, model_version="new")
        assert score(fake, ["chunk"]).cache_hits == 0 and len(fake.calls) == 1


@pytest.mark.unit
class TestCalls:
    def test_the_hot_lane_sends_one_call_within_the_budget(self, cache):
        fake = FakeDecider({"injection": 0.1})
        score(fake, ["a", "b", "c"], feature="injection_attachment")
        (call,) = fake.calls
        assert call.feature == "injection_attachment" and call.budget.lane == "hot"
        assert 0 < call.budget.seconds <= 1.5 and len(call.requests) == 3
        assert call.requests[0].state == {"text": "a"} and call.requests[0].questions == scoring.QUESTIONS

    def test_background_calls_are_split_into_batch_states(self, cache, monkeypatch):
        monkeypatch.setattr(settings, "GUARDRAILS_INJECTION_BATCH_STATES", 2)
        fake = FakeDecider({"injection": 0.1})
        score(fake, ["a", "b", "c", "d", "e"], feature="injection_lazy", budget=Budget.BACKGROUND)
        assert [len(c.requests) for c in fake.calls] == [2, 2, 1]
        assert all(c.budget is Budget.BACKGROUND and c.feature == "injection_lazy" for c in fake.calls)

    def test_live_limits_the_misses_sent_and_defers_the_rest(self, cache):
        fake = FakeDecider({"injection": 0.1})
        with installed(fake):
            cache.put("cached", 0.3)
        result = score(fake, ["cached", "one", "two", "three"], live=1)
        assert [r.state["text"] for r in fake.calls[0].requests] == ["one"]
        assert result.reasons == [None, None, scoring.DEFERRED, scoring.DEFERRED]
        assert result[2] is None and result.live == 1 and result.cache_hits == 1

    def test_unavailable_stops_further_calls(self, cache, monkeypatch):
        monkeypatch.setattr(settings, "GUARDRAILS_INJECTION_BATCH_STATES", 1)
        fake = FakeDecider(reasons={"*": "loading"})
        result = score(fake, ["a", "b", "c"], budget=Budget.BACKGROUND)
        assert len(fake.calls) == 1 and list(result) == [None, None, None]
        assert result.reasons == ["loading"] * 3 and cache.rows == {}

    @pytest.mark.parametrize("budget, size", [
        (Budget.BACKGROUND, "GUARDRAILS_INJECTION_BATCH_STATES"), (Budget.hot(1.5), "DECISION_MAX_BATCH_STATES"),
    ])
    def test_a_part_the_backend_failed_on_does_not_stop_the_rest(self, cache, monkeypatch, budget, size):
        monkeypatch.setattr(settings, size, 2)
        fake = FakeDecider({"injection": lambda state, q: 0.99 if "PAYLOAD" in state["text"] else 0.01})
        real = fake.decide_batch

        def poison_fails(requests, **kwargs):
            done = real(requests, **kwargs)
            failed = ["POISON" in r.state["text"] for r in requests]
            return BatchResult([None if f else d for d, f in zip(done, failed)],
                               ["backend_error" if f else None for f in failed])

        monkeypatch.setattr(fake, "decide_batch", poison_fails)
        result = score(fake, ["POISON 1", "POISON 2", "PAYLOAD"], budget=budget)
        assert len(fake.calls) == 2 and result.reasons == ["backend_error", "backend_error", None]
        assert result[:2] == [None, None] and result[2].p == 0.99

    def test_a_backend_reason_beside_backend_error_still_stops_further_calls(self, cache, monkeypatch):
        monkeypatch.setattr(settings, "GUARDRAILS_INJECTION_BATCH_STATES", 2)
        fake = FakeDecider({"injection": 0.2})
        monkeypatch.setattr(fake, "decide_batch", lambda requests, **kwargs: fake.calls.append(requests) or BatchResult(
            [None] * len(requests), ["backend_error"] + ["transport"] * (len(requests) - 1)))
        result = score(fake, ["a", "b", "c"], budget=Budget.BACKGROUND)
        assert len(fake.calls) == 1 and list(result) == [None, None, None]
        assert result.reasons == ["backend_error", "transport", "transport"]

    @pytest.mark.parametrize("reason", ["timeout", "bad_item", "backend_error"])
    def test_items_not_answered_are_not_cached(self, cache, monkeypatch, reason):
        fake = FakeDecider({"injection": 0.2})
        real = fake.decide_batch

        def second_fails(requests, **kwargs):
            done = real(requests, **kwargs)
            return BatchResult([done[0], None], [None, reason])

        monkeypatch.setattr(fake, "decide_batch", second_fails)
        result = score(fake, ["answered", "not answered"])
        assert result.reasons == [None, reason] and result[1] is None
        assert list(cache.rows) == [(scoring.content_hash("answered"), result_scorer(fake))]

    def test_a_text_is_cached_only_when_every_window_sent_was_answered(self, cache, monkeypatch):
        monkeypatch.setattr(scoring, "WINDOW_TOKENS", 10)
        monkeypatch.setattr(scoring, "WINDOW_OVERLAP", 2)
        fake = FakeDecider({"injection": 0.2}, tokenizer=CharTokenizer())
        real = fake.decide_batch

        def first_only(requests, **kwargs):
            done = real(requests, **kwargs)
            return BatchResult([done[0]] + [None] * (len(requests) - 1), [None] + ["timeout"] * (len(requests) - 1))

        monkeypatch.setattr(fake, "decide_batch", first_only)
        result = score(fake, ["z" * 25])
        assert result[0] == scoring.InjectionScore(0.2, 1, 3) and result.reasons == ["timeout"]
        assert cache.rows == {}

    def test_blank_text_is_clean_without_a_call(self, cache):
        fake = FakeDecider()
        result = score(fake, ["  \n"])
        assert fake.calls == [] and result[0] == scoring.InjectionScore(0.0, 0, 0)

    def test_nothing_is_asked_with_the_switch_off(self, cache, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", False)
        fake = FakeDecider()
        result = score(fake, ["text"])
        assert fake.calls == [] and result.reasons == ["off"] and cache.reads == 0


def result_scorer(fake):
    with installed(fake):
        return scoring.scorer_id()


@pytest.mark.unit
class TestStored:
    def test_a_score_stored_with_the_item_counts_for_the_current_scorer_only(self):
        with installed(FakeDecider()):
            stored = scoring.as_metadata(scoring.InjectionScore(0.97, 2, 2))
            assert stored["scorer"] == scoring.scorer_id()
            assert scoring.from_metadata(stored) == scoring.InjectionScore(0.97, 2, 2, cached=True)
            assert scoring.from_metadata({**stored, "scorer": "injection:old"}) is None
            assert scoring.from_metadata({"p": 0.5}) is None and scoring.from_metadata(None) is None


@pytest.mark.unit
class TestLazy:
    @pytest.fixture
    def queued(self, monkeypatch):
        calls = []
        monkeypatch.setattr(scoring, "_queue", calls.append)
        return calls

    def test_queues_at_most_sixteen_distinct_texts(self, queued):
        with installed(FakeDecider()):
            assert scoring.enqueue_lazy([f"t{i % 20}" for i in range(40)] + [" "]) == 16
        assert queued == [[f"t{i}" for i in range(16)]]

    @pytest.mark.parametrize("setting", ["DECISION_INJECTION_ENABLED", "GUARDRAILS_INJECTION_LAZY"])
    def test_off_queues_nothing(self, queued, monkeypatch, setting):
        monkeypatch.setattr(settings, setting, False)
        with installed(FakeDecider()):
            assert scoring.enqueue_lazy(["text"]) == 0
        assert queued == []

    def test_a_broker_failure_never_raises(self, monkeypatch):
        def broken(texts):
            raise ConnectionError("no broker")

        monkeypatch.setattr(scoring, "_queue", broken)
        with installed(FakeDecider()):
            assert scoring.enqueue_lazy(["text"]) == 0

    def test_the_task_looks_the_texts_up_again_and_scores_in_the_background(self, cache):
        fake = FakeDecider({"injection": 0.4})
        with installed(fake):
            cache.put("already scored", 0.1)
            done = scoring.score_lazy(["already scored", "new"])
        assert done == {"texts": 2, "cached": 1, "scored": 1}
        (call,) = fake.calls
        assert call.feature == "injection_lazy" and call.budget is Budget.BACKGROUND
        assert [r.state["text"] for r in call.requests] == ["new"]

    def test_the_task_body_is_the_scorer(self, monkeypatch):
        from docsgpt.api.user.tasks import score_injection_texts

        seen = []
        monkeypatch.setattr(scoring, "score_lazy", lambda texts: seen.append(texts) or {"texts": len(texts)})
        assert score_injection_texts.run(["a", "b"]) == {"texts": 2}
        assert seen == [["a", "b"]]


@pytest.mark.unit
def test_scores_report_what_the_windows_read(cache, monkeypatch):
    fake = FakeDecider({"injection": 0.3})
    real = fake.decide_batch

    def marked(requests, **kwargs):
        done = real(requests, **kwargs)
        return BatchResult([replace(d, truncated=True) for d in done], done.reasons)

    monkeypatch.setattr(fake, "decide_batch", marked)
    result = score(fake, ["text"])
    assert result[0].truncated and result.model is not None and result.totals == [1]


#: A lone surrogate, as ``json.loads`` makes one from a ``\ud800`` escape: a tool's JSON, or a client's request body.
LONE = json.loads('"look here \\ud800 and carry on"')


@pytest.mark.unit
class TestTextsTheTokenizerRefuses:
    """The model's tokenizer raises on a lone surrogate. One such text must not leave the others unscored."""

    def test_a_lone_surrogate_is_scored_as_its_repaired_text(self, cache, tmp_path):
        fake = FakeDecider({"injection": lambda state, q: 0.99 if "PAYLOAD" in state["text"] else 0.02},
                           tokenizer=byte_tokenizer(tmp_path))
        result = score(fake, [LONE, "a chunk with the PAYLOAD"])
        assert result.reasons == [None, None]
        assert result[0].p == pytest.approx(0.02) and result[1].p == pytest.approx(0.99)
        assert fake.calls[0].requests[0].state == {"text": "look here � and carry on"}

    def test_the_cache_keys_the_text_as_it_came(self, cache, tmp_path):
        score(FakeDecider({"injection": 0.1}, tokenizer=byte_tokenizer(tmp_path)), [LONE, "plain chunk"])
        assert {digest for digest, _ in cache.rows} == {
            hashlib.sha256(LONE.encode("utf-8", "surrogatepass")).hexdigest(),
            hashlib.sha256(b"plain chunk").hexdigest(),
        }

    def test_windows_before_the_tokenizer_loads_are_repaired(self):
        assert scoring.windows(LONE) == (["look here � and carry on"], 1)

    def test_a_text_the_tokenizer_fails_on_is_a_bad_item_and_the_rest_are_scored(self, cache):
        class Fails(CharTokenizer):
            def encode(self, text):
                if "BOOM" in text:
                    raise RuntimeError("the tokenizer failed")
                return super().encode(text)

        fake = FakeDecider({"injection": 0.97}, tokenizer=Fails())
        result = score(fake, ["BOOM", "a chunk with the PAYLOAD"])
        assert result.reasons == ["bad_item", None] and result[0] is None and result[1].p == pytest.approx(0.97)
        assert [r.state for r in fake.calls[0].requests] == [{"text": "a chunk with the PAYLOAD"}]
