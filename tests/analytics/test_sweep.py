"""The analytics sweep against a real schema (``pg_conn``) and a scripted decision client (``FakeDecider``)."""

from __future__ import annotations

import contextlib
import json
import uuid

import pytest
from sqlalchemy import text

from docsgpt.analytics import schema, tasks
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget
from docsgpt.decisions.models import V02, version
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.decisions.types import BatchResult
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository

VERSION = version(V02)
ANSWERS = {
    "answer_status": {"fully answered": 0.2, "partially answered": 0.1, "declined, no information": 0.6,
                      "not a request": 0.1},
    "unanswered_reason": {"docs missing": 0.8, "other": 0.2},
    "reaction": {"follow-up": 0.7, "new question": 0.3},
    "frustrated": 0.1,
    "asks_human": 0.05,
    "sentiment": [0.1, 0.7, 0.2],
    "request_type": "how-to",
    "topic": {"install": 0.7, "auth": 0.2, "none of these": 0.1},
    "goal_met": 0.8,
    "tag": 0.9,
}
TOPICS = [{"id": "install01", "name": "install", "description": "Setting it up"}, {"id": "auth0001", "name": "auth"}]
PRICING = {"id": "pricing01", "name": "Pricing", "description": "Asks about plans or prices.", "overlap": True}


@pytest.fixture
def db(pg_conn, monkeypatch):
    """The sweep's sessions on the test's connection; writes in a savepoint, as a real session is a transaction."""

    @contextlib.contextmanager
    def readonly():
        yield pg_conn

    @contextlib.contextmanager
    def session():
        with pg_conn.begin_nested():
            yield pg_conn

    monkeypatch.setattr(tasks, "db_readonly", readonly)
    monkeypatch.setattr(tasks, "db_session", session)
    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    monkeypatch.setattr(settings, "POSTGRES_URI", settings.POSTGRES_URI or "postgresql://test")
    return pg_conn


@pytest.fixture
def fake():
    with installed(FakeDecider(ANSWERS)) as f:
        yield f


def _conversation(conn, *, agent_id=None, api_key=None, user="owner", visibility="hidden") -> str:
    return str(ConversationsRepository(conn).create(user, "c", agent_id=agent_id, api_key=api_key,
                                                    visibility=visibility)["id"])


def _message(conn, cid, position, prompt, response="Here is how.", *, status="complete", ago_minutes=120,
             sources=None) -> str:
    return conn.execute(
        text(
            """
            INSERT INTO conversation_messages
                (conversation_id, user_id, position, prompt, response, status, sources, timestamp, updated_at)
            VALUES (CAST(:cid AS uuid), 'owner', :position, :prompt, :response, :status, CAST(:sources AS jsonb),
                    now() - make_interval(mins => :ago), now() - make_interval(mins => :ago))
            RETURNING CAST(id AS text)
            """
        ),
        {"cid": cid, "position": position, "prompt": prompt, "response": response, "status": status,
         "sources": json.dumps(sources or [{"title": "Install", "text": "pip install docsgpt"}]),
         "ago": ago_minutes - position},
    ).scalar()


def _agent(conn, **analytics) -> dict:
    return AgentsRepository(conn).create("owner", "Docs bot", "published", key=f"key-{uuid.uuid4().hex[:12]}",
                                         config={"analytics": analytics} if analytics else {})


def _labels(conn, cid) -> dict:
    rows = conn.execute(
        text(
            """
            SELECT CAST(message_id AS text) AS message_id, CAST(reply_message_id AS text) AS reply, label, level,
                   top, p_top, probabilities, derived, lang, options_hash, schema_hash, model_version,
                   CAST(agent_id AS text) AS agent_id
            FROM conversation_labels WHERE conversation_id = CAST(:cid AS uuid)
            """
        ),
        {"cid": cid},
    ).fetchall()
    return {(row.message_id, row.label): row for row in rows}


def _two_turns(conn, **kwargs) -> tuple[str, str, str]:
    cid = _conversation(conn, **kwargs)
    first = _message(conn, cid, 0, "How do I install it?")
    second = _message(conn, cid, 1, "and on Windows?")
    return cid, first, second


@pytest.mark.unit
class TestLabelling:
    def test_every_label_is_written_with_the_schema_and_model(self, db, fake):
        cid, first, second = _two_turns(db)
        report = tasks.sweep()
        labels = _labels(db, cid)
        assert {key for key in labels} == {
            (first, "answer_status"), (first, "unanswered_reason"), (first, "request_type"), (first, "gap_type"),
            (first, "reaction"), (first, "frustrated"), (first, "asks_human"), (first, "sentiment"),
            (second, "answer_status"), (second, "unanswered_reason"), (second, "request_type"),
            (second, "gap_type"), (None, "goal_met"), (None, "resolution"), (None, "experience"),
        }
        assert {(row.schema_hash, row.model_version) for row in labels.values()} == {(schema.SCHEMA_HASH, VERSION)}
        assert report["messages"] == 2 and report["conversations"] == 1 and report["stopped"] is None
        reaction = labels[(first, "reaction")]
        assert (reaction.level, reaction.reply, reaction.top) == ("reaction", second, "follow-up")
        assert labels[(first, "frustrated")].probabilities == pytest.approx({"yes": 0.1, "no": 0.9})
        assert labels[(first, "sentiment")].top == "1"
        assert labels[(second, "request_type")].lang == "en"
        assert not labels[(first, "answer_status")].derived and labels[(first, "gap_type")].derived

    def test_the_gap_is_weighted_by_the_unanswered_mass(self, db, fake):
        cid, first, _ = _two_turns(db)
        tasks.sweep()
        gap = _labels(db, cid)[(first, "gap_type")].probabilities
        assert gap["docs missing"] == pytest.approx(0.7 * 0.8)
        assert gap["other"] == pytest.approx(0.7 * 0.2)
        assert gap["not retrieved"] == gap["answer missed"] == 0.0

    def test_the_resolution_is_pending_within_the_window(self, db, fake):
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        labels = _labels(db, cid)
        assert labels[(None, "resolution")].probabilities["pending"] > 0
        experience = labels[(None, "experience")]
        assert experience.top == "score" and 1.0 <= experience.p_top <= 5.0

    def test_calls_are_background_with_the_analytics_feature_labels(self, db, fake):
        _two_turns(db)
        tasks.sweep()
        assert [(c.feature, c.budget) for c in fake.calls] == [
            ("analytics_turn", Budget.BACKGROUND), ("analytics_conversation", Budget.BACKGROUND),
        ]
        turn_call = fake.calls[0]
        assert [list(r.questions) for r in turn_call.requests] == [
            ["answer_status", "unanswered_reason"], ["request_type"],
            ["answer_status", "unanswered_reason"], ["reaction", "frustrated", "asks_human", "sentiment"],
            ["request_type"],
        ]
        assert list(fake.calls[1].requests[0].questions) == ["goal_met"]

    def test_a_second_sweep_writes_nothing(self, db, fake):
        _two_turns(db)
        tasks.sweep()
        calls = len(fake.calls)
        report = tasks.sweep()
        assert len(fake.calls) == calls
        assert report["rows"] == 0 and report["messages"] == 0

    def test_a_batch_never_splits_a_message(self, db, fake, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 4)
        _two_turns(db)
        tasks.sweep()
        assert [len(c.requests) for c in fake.calls if c.feature == "analytics_turn"] == [2, 3]

    def test_an_edited_message_is_labelled_again(self, db, fake, monkeypatch):
        cid, _, second = _two_turns(db)
        tasks.sweep()
        db.execute(text("UPDATE conversation_labels SET created_at = now() - interval '10 minutes'"))
        db.execute(text("UPDATE conversation_messages SET response = 'Regenerated.' WHERE id = CAST(:id AS uuid)"),
                   {"id": second})
        monkeypatch.setattr(settings, "ANALYTICS_TURN_SETTLE_SECONDS", 0)
        calls = len(fake.calls)
        report = tasks.sweep()
        assert report["messages"] == 1
        asked = fake.calls[calls]
        assert asked.feature == "analytics_turn"
        assert asked.requests[0].state["answer"] == "Regenerated."

    def test_an_unsettled_edit_waits(self, db, fake):
        cid, _, second = _two_turns(db)
        tasks.sweep()
        db.execute(text("UPDATE conversation_labels SET created_at = now() - interval '10 minutes'"))
        db.execute(text("UPDATE conversation_messages SET response = 'Regenerated.' WHERE id = CAST(:id AS uuid)"),
                   {"id": second})
        assert tasks.sweep()["messages"] == 0

    def test_truncating_a_conversation_takes_its_labels(self, db, fake):
        cid, first, second = _two_turns(db)
        tasks.sweep()
        ConversationsRepository(db).truncate_after(cid, 0)
        labels = _labels(db, cid)
        assert not [key for key in labels if key[0] == second]
        assert (first, "reaction") not in labels and (first, "answer_status") in labels

    def test_hidden_api_and_shared_traffic_is_labelled(self, db, fake):
        agent = _agent(db, enabled=True)
        by_key = _conversation(db, api_key=agent["key"], user="owner", visibility="hidden")
        _message(db, by_key, 0, "How do I install it?")
        listed = _conversation(db, user="someone", visibility="listed")
        _message(db, listed, 0, "Hello?")
        tasks.sweep()
        assert _labels(db, by_key) and _labels(db, listed)
        assert {row.agent_id for row in _labels(db, by_key).values()} == {str(agent["id"])}

    def test_an_agent_with_analytics_off_is_skipped(self, db, fake):
        agent = _agent(db, enabled=False)
        cid = _conversation(db, agent_id=str(agent["id"]))
        _message(db, cid, 0, "How do I install it?")
        assert tasks.sweep()["messages"] == 0 and not _labels(db, cid) and not fake.calls

    def test_compression_rows_and_unfinished_messages_are_never_candidates(self, db, fake):
        cid = _conversation(db)
        db.execute(
            text(
                "INSERT INTO conversation_messages (conversation_id, user_id, position, prompt, response, "
                "message_metadata, timestamp, updated_at) VALUES (CAST(:cid AS uuid), 'owner', 0, "
                "'[Context Compression Summary]', 's', '{\"compression_summary\": true}', now() - interval '2 hours', "
                "now() - interval '2 hours')"
            ),
            {"cid": cid},
        )
        _message(db, cid, 1, "Still streaming?", "", status="streaming")
        assert tasks.sweep()["messages"] == 0 and not fake.calls

    def test_a_failed_message_is_a_user_message_without_a_turn(self, db, fake):
        cid = _conversation(db)
        first = _message(db, cid, 0, "How do I install it?")
        failed = _message(db, cid, 1, "and on Windows?", "", status="failed")
        tasks.sweep()
        labels = _labels(db, cid)
        assert (failed, "request_type") in labels and (failed, "answer_status") not in labels
        assert labels[(first, "reaction")].reply == failed


@pytest.mark.unit
class TestTopicsAndTags:
    def test_topics_and_the_effective_topic(self, db, fake):
        agent = _agent(db, topics=TOPICS)
        cid, first, second = _two_turns(db, agent_id=str(agent["id"]))
        tasks.sweep()
        labels = _labels(db, cid)
        topic = labels[(second, "topic")]
        assert list(topic.probabilities) == ["auth", "install", "none of these"]
        assert topic.options_hash and labels[(second, "topic_effective")].options_hash == topic.options_hash
        # the second message follows up (p_cont 0.7) on an opener with the same answer, so the mix is unchanged
        assert labels[(second, "topic_effective")].probabilities == pytest.approx(topic.probabilities)
        assert labels[(first, "topic_effective")].top == "install"
        question = fake.calls[0].requests[1].questions["topic"]
        assert question == schema.topic_question({"auth": None, "install": "Setting it up"})

    def test_a_new_overlapping_topic_relabels_the_conversation_and_a_removed_one_goes(self, db, fake):
        agent = _agent(db, enabled=True)
        cid, _, _ = _two_turns(db, agent_id=str(agent["id"]))
        tasks.sweep()
        assert (None, "tag:pricing01") not in _labels(db, cid)
        AgentsRepository(db).update(str(agent["id"]), "owner", {"config": {"analytics": {"topics": [PRICING]}}})
        calls = len(fake.calls)
        tasks.sweep()
        asked = fake.calls[calls]
        assert asked.feature == "analytics_conversation"
        assert asked.requests[0].questions["tag:pricing01"] == schema.tag_question("Pricing",
                                                                                     "Asks about plans or prices.")
        row = _labels(db, cid)[(None, "tag:pricing01")]
        assert row.top == "yes" and row.p_top == pytest.approx(0.9) and row.options_hash
        AgentsRepository(db).update(str(agent["id"]), "owner", {"config": {"analytics": {"topics": []}}})
        tasks.sweep()
        assert (None, "tag:pricing01") not in _labels(db, cid)

    def test_an_overlapping_topic_without_a_description_is_asked_by_its_name(self, db, fake):
        bare = {**PRICING, "description": ""}
        agent = _agent(db, topics=[bare])
        _two_turns(db, agent_id=str(agent["id"]))
        tasks.sweep()
        (asked,) = [c for c in fake.calls if c.feature == "analytics_conversation"]
        assert asked.requests[0].questions["tag:pricing01"] == schema.tag_question("Pricing", "Pricing")

    def test_a_topic_that_does_not_overlap_never_reasks_the_conversation(self, db, fake):
        agent = _agent(db, topics=[PRICING])
        _two_turns(db, agent_id=str(agent["id"]))
        tasks.sweep()
        AgentsRepository(db).update(str(agent["id"]), "owner", {"config": {"analytics": {
            "topics": [PRICING, *TOPICS], "hidden_folders": ["guides"]}}})
        calls = len(fake.calls)
        tasks.sweep()
        assert not [c for c in fake.calls[calls:] if c.feature == "analytics_conversation"]

    def test_flipping_a_topic_to_overlap_reasks_the_conversation(self, db, fake):
        agent = _agent(db, topics=TOPICS)
        cid, _, _ = _two_turns(db, agent_id=str(agent["id"]))
        tasks.sweep()
        flipped = [{**TOPICS[0], "overlap": True}, TOPICS[1]]
        AgentsRepository(db).update(str(agent["id"]), "owner", {"config": {"analytics": {"topics": flipped}}})
        calls = len(fake.calls)
        tasks.sweep()
        assert [c.feature for c in fake.calls[calls:]] == ["analytics_conversation"]
        assert (None, "tag:install01") in _labels(db, cid)

    def test_conversations_wait_until_idle(self, db, fake):
        cid = _conversation(db)
        _message(db, cid, 0, "How do I install it?", ago_minutes=5)
        tasks.sweep()
        assert [c.feature for c in fake.calls] == ["analytics_turn"]
        assert (None, "goal_met") not in _labels(db, cid)


class _Partial(FakeDecider):
    """Fails the requests ``fail(request)`` picks with ``reason``, once."""

    def __init__(self, fail, reason):
        super().__init__(ANSWERS)
        self.fail, self.reason, self.armed = fail, reason, True

    def decide_batch(self, requests, *, feature, budget=Budget.HOT):
        result = super().decide_batch(requests, feature=feature, budget=budget)
        if not self.armed:
            return result
        self.armed = False
        hit = [self.fail(r) for r in requests]
        return BatchResult([None if h else d for d, h in zip(result, hit)],
                           [self.reason if h else None for h in hit])


@pytest.mark.unit
class TestStopConditions:
    def test_unavailable_writes_nothing_and_stops(self, db):
        cid, _, _ = _two_turns(db)
        with installed(FakeDecider(ANSWERS, reasons={"*": "loading"})) as fake:
            report = tasks.sweep()
        assert report["stopped"] == "unavailable" and len(fake.calls) == 1
        assert not _labels(db, cid)

    def test_timed_out_messages_are_labelled_by_the_next_sweep(self, db):
        cid, first, second = _two_turns(db)
        late = _Partial(lambda r: r.state.get("message") == "and on Windows?", "timeout")
        with installed(late):
            report = tasks.sweep()
            labels = _labels(db, cid)
            assert report["timeouts"] == 1 and report["stopped"] is None
            assert (first, "request_type") in labels and (second, "answer_status") not in labels
            assert (first, "reaction") not in labels  # it was asked for the late message
            tasks.sweep()
        labels = _labels(db, cid)
        assert (second, "request_type") in labels and (first, "reaction") in labels

    def test_a_call_that_timed_out_whole_stops_the_sweep(self, db):
        _two_turns(db)
        with installed(_Partial(lambda r: True, "timeout")) as fake:
            report = tasks.sweep()
        assert report["stopped"] == "timeout" and len(fake.calls) == 1

    def test_bad_items_and_unbuildable_states_become_error_rows(self, db, monkeypatch):
        cid, first, second = _two_turns(db)
        bad = _Partial(lambda r: r.state.get("message") == "and on Windows?", "bad_item")
        real_turn = tasks.states.turn
        monkeypatch.setattr(tasks.states, "turn", lambda msgs, i: 1 / 0 if i == 0 else real_turn(msgs, i))
        with installed(bad):
            report = tasks.sweep()
            labels = _labels(db, cid)
            assert report["errors"] == 2
            assert labels[(first, "_error")].top == "build_failed"
            assert labels[(second, "_error")].top == "bad_item"
            assert (first, "request_type") in labels and (second, "answer_status") in labels
            calls = len(bad.calls)
            tasks.sweep()
            assert all(c.feature != "analytics_turn" for c in bad.calls[calls:])

    def test_the_time_budget_is_honoured(self, db, fake):
        _two_turns(db)
        report = tasks.sweep(budget_seconds=0)
        assert report["stopped"] == "budget" and not fake.calls

    def test_the_switch_off_returns_at_once(self, db, fake, monkeypatch):
        _two_turns(db)
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        assert tasks.sweep() == {"skipped": "disabled"} and not fake.calls

    def test_decisions_off_returns_at_once(self, db):
        _two_turns(db)  # no fake: the root conftest runs with DECISION_MODE=none
        assert tasks.sweep() == {"skipped": "disabled"}

    def test_the_lock_blocks_a_concurrent_sweep(self, db, fake, monkeypatch):
        class Redis:
            def __init__(self):
                self.store = {tasks.LOCK_KEY: b"another worker"}

            def set(self, key, value, nx=False, ex=None):
                if nx and key in self.store:
                    return None
                self.store[key] = value
                return True

            def get(self, key):
                return self.store.get(key)

            def delete(self, key):
                self.store.pop(key, None)

            def expire(self, key, ttl):
                return True

        redis = Redis()
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
        _two_turns(db)
        assert tasks.sweep() == {"skipped": "locked"} and not fake.calls
        redis.store.clear()
        assert tasks.sweep()["messages"] == 2
        assert tasks.LOCK_KEY not in redis.store  # released


@pytest.mark.unit
class TestPendingAndRetention:
    def test_pending_settles_after_the_window_without_a_model_call(self, db, fake):
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        assert _labels(db, cid)[(None, "resolution")].probabilities["pending"] > 0
        db.execute(text("UPDATE conversation_messages SET timestamp = timestamp - interval '2 days' "
                        "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid})
        db.execute(text("UPDATE conversation_labels SET occurred_at = occurred_at - interval '2 days' "
                        "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid})
        calls = len(fake.calls)
        report = tasks.sweep()
        assert len(fake.calls) == calls and report["resolutions"] == 1
        resolution = _labels(db, cid)[(None, "resolution")].probabilities
        assert resolution["pending"] == 0
        assert resolution["assumed"] > 0 and sum(resolution.values()) == pytest.approx(1.0)

    def test_cleanup_purges_past_retention(self, db, fake):
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        db.execute(text("UPDATE conversation_labels SET occurred_at = now() - interval '100 days' "
                        "WHERE label = 'goal_met'"))
        assert tasks.cleanup_conversation_labels.run() == {"deleted": 1, "ttl_days": 90}
        assert (None, "goal_met") not in _labels(db, cid)


@pytest.mark.unit
class TestDigestAndBackfill:
    def test_the_digest_names_the_top_gap_topics(self, db, fake, monkeypatch):
        agent = _agent(db, topics=TOPICS, digest=True)
        quiet = _agent(db, enabled=True, digest=False)
        for _ in range(2):
            _two_turns(db, agent_id=str(agent["id"]))
        _two_turns(db, agent_id=str(quiet["id"]))
        tasks.sweep()
        sent = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kwargs: sent.append(kwargs))
        assert tasks.gap_digest() == {"sent": 1}
        (note,) = sent
        assert note["user_id"] == "owner" and note["kind"] == "docs_gaps" and note["title"] == "Docs bot"
        assert note["url"] == f"/agents/manage/insights/{agent['id']}#docs-gaps"
        # four turns, each 0.56 docs missing, 70% of it about install
        assert note["body"].startswith("install 1.6")

    def test_backfill_estimate_counts_without_labelling(self, db, fake):
        _two_turns(db)
        estimate = tasks.backfill_estimate(7)
        assert (estimate["messages"], estimate["conversations"], estimate["turns"]) == (2, 1, 2)
        assert estimate["estimated_compute_s"] is None and not fake.calls
