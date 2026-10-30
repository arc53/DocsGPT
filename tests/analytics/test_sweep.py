"""The analytics sweep against a real schema (``pg_conn``) and a scripted decision client (``FakeDecider``)."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import re
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from docsgpt.analytics import schema, states, tasks
from docsgpt.analytics.states import TERMINATED_RESPONSE_PLACEHOLDER
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget
from docsgpt.decisions.models import V01, V02, version
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.decisions.types import BatchResult
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversation_labels import (
    _AGENT,
    ConversationLabelsRepository,
    Scope,
    _has_text,
    _is_turn,
    _message_hash,
)
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
             sources=None, tool_calls=None) -> str:
    return conn.execute(
        text(
            """
            INSERT INTO conversation_messages
                (conversation_id, user_id, position, prompt, response, status, sources, tool_calls, timestamp,
                 updated_at)
            VALUES (CAST(:cid AS uuid), 'owner', :position, :prompt, :response, :status, CAST(:sources AS jsonb),
                    CAST(:tool_calls AS jsonb), now() - make_interval(mins => :ago),
                    now() - make_interval(mins => :ago))
            RETURNING CAST(id AS text)
            """
        ),
        {"cid": cid, "position": position, "prompt": prompt, "response": response, "status": status,
         "sources": json.dumps(sources or [{"title": "Install", "text": "pip install docsgpt"}]),
         "tool_calls": json.dumps(tool_calls or []), "ago": ago_minutes - position},
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

    def test_an_overlapping_topic_added_during_a_sweep_is_asked(self, db, fake, monkeypatch):
        # The message pass reads the agent; an edit before the conversation pass must not leave conversations
        # stamped with the new topics' hash while asked the old ones.
        agent = _agent(db, enabled=True)
        cid, _, _ = _two_turns(db, agent_id=str(agent["id"]))
        original = tasks.Sweep.conversation_pass

        def edited_first(sweep):
            AgentsRepository(db).update(str(agent["id"]), "owner", {"config": {"analytics": {"topics": [PRICING]}}})
            monkeypatch.setattr(tasks.Sweep, "conversation_pass", original)
            return original(sweep)

        monkeypatch.setattr(tasks.Sweep, "conversation_pass", edited_first)
        tasks.sweep()
        tasks.sweep()
        assert (None, "tag:pricing01") in _labels(db, cid)

    def test_derived_rows_keep_a_deleted_agents_ownership(self, db, fake):
        # topic_effective names the agent's topics: rewritten after the agent is gone (here for a new turn), it
        # must stay the agent's row, hidden from the chatting user's own views, not become a row of no agent.
        agent = _agent(db, topics=TOPICS)
        agent_id = str(agent["id"])
        cid, first, second = _two_turns(db, agent_id=agent_id)
        tasks.sweep()
        AgentsRepository(db).delete(agent_id, "owner")
        third = _message(db, cid, 2, "and then?", ago_minutes=60)
        tasks.sweep()
        labels = _labels(db, cid)
        assert (third, "answer_status") in labels
        effective = {key: row for key, row in labels.items() if key[1] == "topic_effective"}
        assert {key[0] for key in effective} >= {first, second}
        assert {row.agent_id for row in effective.values()} == {agent_id}
        assert labels[(None, "resolution")].agent_id == agent_id

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


class _Failing(FakeDecider):
    """Fails the requests ``fail(request)`` picks with ``reason`` on every call (of ``features``, when given)."""

    def __init__(self, fail, reason, features=None):
        super().__init__(ANSWERS)
        self.fail, self.reason, self.features = fail, reason, features

    def decide_batch(self, requests, *, feature, budget=Budget.HOT):
        result = super().decide_batch(requests, feature=feature, budget=budget)
        if self.features is not None and feature not in self.features:
            return result
        hit = [self.fail(r) for r in requests]
        return BatchResult([None if h else d for d, h in zip(result, hit)],
                           [self.reason if h else None for h in hit])


class _Redis:
    """The Redis calls the sweep lock makes: ``set``, ``get``, ``delete`` and its compare-and-expire and
    compare-and-delete scripts, which ``eval`` re-implements. TTLs are recorded in ``ttls``, never run down;
    ``refreshes`` counts the compare-and-expire scripts run."""

    def __init__(self, store=None):
        self.store = dict(store or {})
        self.ttls: dict = {}
        self.refreshes = 0

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key], self.ttls[key] = value.encode() if isinstance(value, str) else value, ex
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def eval(self, script, numkeys, key, token, ttl=None):
        assert numkeys == 1 and ("expire" in script or "del" in script)
        held = self.store.get(key) == (token.encode() if isinstance(token, str) else token)
        if "del" in script:
            if held:
                self.store.pop(key)
            return int(held)
        self.refreshes += 1
        if not held:
            return 0
        self.ttls[key] = int(ttl)
        return 1


def _age(conn, cid, days=2):
    """Move a conversation and its labels ``days`` back, past the resolution window."""
    for table in ("conversation_messages", "conversation_labels"):
        column = "timestamp" if table == "conversation_messages" else "occurred_at"
        conn.execute(text(f"UPDATE {table} SET {column} = {column} - make_interval(days => :days) "
                          "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid, "days": days})


def _parked(conn, cid) -> dict:
    """The sources of ``cid`` set aside uncounted (a ``_retry`` row with ``parked_since``), to their attempts."""
    return {key[0]: row.probabilities["attempts"] for key, row in _labels(conn, cid).items()
            if key[1] == "_retry" and row.probabilities.get("parked_since")}


def _park_back(conn, hours):
    """Move every ``parked_since`` ``hours`` back."""
    conn.execute(text(
        "UPDATE conversation_labels SET probabilities = jsonb_set(probabilities, '{parked_since}',"
        " to_jsonb(CAST(probabilities->>'parked_since' AS timestamptz) - make_interval(hours => :hours)))"
        " WHERE label = '_retry' AND probabilities->>'parked_since' IS NOT NULL"), {"hours": hours})


def _about(prompt):
    """Picks the requests about the user message ``prompt``: its turn and its request type."""
    return lambda r: prompt in (r.state.get("question"), r.state.get("message"))


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
        # the reply's reaction fails while the call answers the rest, so the fault is the item's own
        bad = _Partial(lambda r: "reaction" in r.questions, "bad_item")
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

    @pytest.mark.parametrize("reason", ["bad_item", "backend_error"])
    def test_a_call_that_fails_whole_stops_and_writes_nothing(self, db, reason):
        cid, first, second = _two_turns(db)
        with installed(_Partial(lambda r: True, reason)) as failing:
            report = tasks.sweep()
            stopped = {"bad_item": "failed", "backend_error": "unavailable"}[reason]
            assert report["stopped"] == stopped and len(failing.calls) == 1
            assert not _labels(db, cid) and report["errors"] == 0
            report = tasks.sweep()  # healthy again
        labels = _labels(db, cid)
        assert (first, "request_type") in labels and (second, "request_type") in labels
        assert not [key for key in labels if key[1].startswith("_")]
        assert report["messages"] == 2

    def test_a_backend_error_among_answers_is_retried_then_marked(self, db):
        cid, first, second = _two_turns(db)
        failing = _Failing(lambda r: r.state.get("message") == "and on Windows?", "backend_error")
        with installed(failing):
            for attempt in range(1, tasks.ATTEMPTS):
                report = tasks.sweep()
                labels = _labels(db, cid)
                assert (first, "request_type") in labels and (second, "_error") not in labels
                assert labels[(second, "_retry")].probabilities == {"attempts": attempt}
                assert report["stopped"] is None and report["retries"] == 1 and report["errors"] == 0
            report = tasks.sweep()
            labels = _labels(db, cid)
            assert labels[(second, "_error")].top == "backend_error" and report["errors"] == 1
            calls = len(failing.calls)
            tasks.sweep()
            assert all(c.feature != "analytics_turn" for c in failing.calls[calls:])
        assert (None, "goal_met") in _labels(db, cid)

    @pytest.mark.parametrize("others", [60, 900], ids=["asked_before", "asked_after"])
    def test_a_message_that_fails_alone_counts_attempts_only_while_the_backend_answers_others(self, db, others,
                                                                                             monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 2)  # a message a call
        cid = _conversation(db)
        only = _message(db, cid, 0, "How do I install it?", ago_minutes=300)
        failing = _Failing(_about("How do I install it?"), "backend_error", features={"analytics_turn"})
        with installed(failing):
            for _ in range(tasks.ATTEMPTS + 1):  # nothing else answered: no telling it from a failing backend
                assert tasks.sweep()["stopped"] == "unavailable"
            assert _parked(db, cid) == {only: 0}
            for attempt in range(1, tasks.ATTEMPTS):
                _message(db, _conversation(db), 0, "and on Windows?", ago_minutes=others)  # traffic it answers
                report = tasks.sweep()
                assert report["stopped"] is None and report["retries"] == 1
                assert _labels(db, cid)[(only, "_retry")].probabilities == {"attempts": attempt}
            _message(db, _conversation(db), 0, "and on Windows?", ago_minutes=others)
            report = tasks.sweep()
        labels = _labels(db, cid)
        assert labels[(only, "_error")].top == "backend_error" and report["errors"] == 1
        assert (None, "goal_met") in labels

    @pytest.mark.parametrize("batch", [1, 3, 16])
    def test_a_backend_that_fails_every_item_marks_none_and_labels_them_once_healthy(self, db, monkeypatch, batch):
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", batch)  # 1: split messages; 3: a message a call
        cids = [_two_turns(db)[0] for _ in range(3)]
        lone = _conversation(db)
        _message(db, lone, 0, "Hello?")
        cids.append(lone)
        with installed(_Failing(lambda r: True, "backend_error")):
            for _ in range(tasks.ATTEMPTS + 1):
                assert tasks.sweep()["stopped"] == "unavailable"
        rows = [row for cid in cids for row in _labels(db, cid).values()]  # what failed alone, set aside
        assert all(row.label == "_retry" and row.probabilities["attempts"] == 0 for row in rows)
        assert all(_parked(db, cid) for cid in cids if any(row for row in _labels(db, cid)))
        with installed(FakeDecider(ANSWERS)):
            report = tasks.sweep()
        assert report["messages"] == 7 and report["conversations"] == 4 and report["stopped"] is None
        assert not [key for cid in cids for key in _labels(db, cid) if key[1] == "_error"]

    def test_messages_the_backend_always_fails_on_never_hold_up_older_ones(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 2)  # a message a call
        refused = []
        for i in range(tasks.LONE_FAILURES):  # the newest, so asked first while nothing has failed
            cid = _conversation(db)
            refused.append((cid, _message(db, cid, 0, f"Refused {i}?", ago_minutes=60 + i)))
        older = {}
        for i in range(3):
            cid = _conversation(db)
            older[cid] = _message(db, cid, 0, "How do I install it?", ago_minutes=600 + i)
        failing = _Failing(lambda r: "Refused" in (r.state.get("question") or r.state.get("message") or ""),
                           "backend_error", features={"analytics_turn"})

        def attempts():
            return [_labels(db, cid)[(mid, "_retry")].probabilities for cid, mid in refused]

        with installed(failing):
            report = tasks.sweep()  # the three alone end the pass; the next asks the older ones, which answer
            assert all((mid, "request_type") in _labels(db, cid) for cid, mid in older.items())
            assert attempts() == [{"attempts": 1}] * 3 and report["retries"] == 3 and report["stopped"] is None
            tasks.sweep()  # asked first, alone again; the older conversations' own calls answer, so they count
            assert all((None, "goal_met") in _labels(db, cid) for cid in older)
            assert attempts() == [{"attempts": 2}] * 3
            for attempt in range(3, tasks.ATTEMPTS + 1):  # nothing else answers: each counts once set aside a day
                assert tasks.sweep()["stopped"] == "unavailable"
                assert all(a["attempts"] == attempt - 1 and a["parked_since"] for a in attempts())
                tasks.sweep()
                assert all(a["attempts"] == attempt - 1 for a in attempts())  # not a day yet
                _park_back(db, tasks.PARKED_HOURS + 1)
                tasks.sweep()
                if attempt < tasks.ATTEMPTS:
                    assert attempts() == [{"attempts": attempt}] * 3
            assert all(_labels(db, cid)[(mid, "_error")].top == "backend_error" for cid, mid in refused)
            calls = len(failing.calls)
            tasks.sweep()
            assert all(c.feature != "analytics_turn" for c in failing.calls[calls:])

    @pytest.mark.parametrize("feature", ["analytics_turn", "analytics_conversation"])
    def test_what_fails_alone_for_longer_than_the_bound_counts_all_the_same(self, db, feature):
        cid = _conversation(db)
        only = _message(db, cid, 0, "How do I install it?", ago_minutes=300)
        source = only
        if feature == "analytics_conversation":
            with installed(FakeDecider(ANSWERS)):
                tasks.Sweep(VERSION).message_pass()  # its message labelled, its own labels not yet asked
            source = None
        with installed(_Failing(lambda r: True, "backend_error", features={feature})):
            for _ in range(2):  # within the bound: set aside, nothing counted
                assert tasks.sweep()["stopped"] == "unavailable"
            assert _parked(db, cid) == {source: 0}
            for attempt in range(1, tasks.ATTEMPTS + 1):
                _park_back(db, tasks.PARKED_HOURS - 1)
                tasks.sweep()
                assert _parked(db, cid) == {source: attempt - 1}  # not a day yet
                _park_back(db, 2)
                report = tasks.sweep()
                labels = _labels(db, cid)
                if attempt < tasks.ATTEMPTS:
                    assert labels[(source, "_retry")].probabilities == {"attempts": attempt}
                    assert report["retries"] == 1 and not _parked(db, cid)
                    assert tasks.sweep()["stopped"] == "unavailable"  # set aside again, the day from now
                    assert _parked(db, cid) == {source: attempt}
            assert labels[(source, "_error")].top == "backend_error" and report["errors"] == 1

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
        redis = _Redis({tasks.LOCK_KEY: b"another worker"})
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
        _two_turns(db)
        assert tasks.sweep() == {"skipped": "locked"} and not fake.calls
        redis.store.clear()
        assert tasks.sweep()["messages"] == 2
        assert tasks.LOCK_KEY not in redis.store  # released

    def test_a_refresh_never_extends_another_workers_lock(self, monkeypatch):
        redis = _Redis()
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
        monkeypatch.setattr(tasks, "LOCK_REFRESH_SECONDS", 0)
        lock = tasks._Lock(600)
        assert lock.acquire() and lock.refresh() is True and redis.ttls[tasks.LOCK_KEY] == 600
        redis.store[tasks.LOCK_KEY], redis.ttls[tasks.LOCK_KEY] = b"another worker", 10  # ours expired, then taken
        assert lock.refresh() is False and redis.ttls[tasks.LOCK_KEY] == 10
        # released in one compare-and-delete: nothing between reading the token and deleting the key
        redis.get = redis.delete = None
        lock.release()
        assert redis.store[tasks.LOCK_KEY] == b"another worker"

    def test_a_lost_lock_stops_the_sweep(self, db, monkeypatch):
        redis = _Redis()
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
        monkeypatch.setattr(tasks, "LOCK_REFRESH_SECONDS", 0)
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 5)
        for _ in range(3):
            _two_turns(db)

        def taken():
            redis.store[tasks.LOCK_KEY], redis.ttls[tasks.LOCK_KEY] = b"another worker", 10

        with installed(_Editing("analytics_turn", taken)) as editing:
            report = tasks.sweep()
        assert report["stopped"] == "lock_lost" and len(editing.calls) == 1
        assert redis.store[tasks.LOCK_KEY] == b"another worker" and redis.ttls[tasks.LOCK_KEY] == 10

    def test_a_pass_without_model_calls_keeps_the_lock(self, db, fake, monkeypatch):
        redis = _Redis()
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: redis)
        monkeypatch.setattr(tasks, "LOCK_REFRESH_SECONDS", 0)
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        _age(db, cid)
        calls, redis.refreshes = len(fake.calls), 0
        assert tasks.sweep()["resolutions"] == 1 and len(fake.calls) == calls
        assert redis.refreshes >= 1


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

    def test_the_pending_pass_keeps_to_the_agent_asked_for_and_to_agents_with_analytics_on(self, db, fake):
        mine, other, off = (_agent(db, enabled=True) for _ in range(3))
        cids = {name: _two_turns(db, agent_id=str(agent["id"]))[0]
                for name, agent in (("mine", mine), ("other", other), ("off", off))}
        tasks.sweep()
        for cid in cids.values():
            _age(db, cid)
        AgentsRepository(db).update(str(off["id"]), "owner", {"config": {"analytics": {"enabled": False}}})

        def pending(name):
            return _labels(db, cids[name])[(None, "resolution")].probabilities["pending"] > 0

        assert tasks.sweep(agent_id=str(mine["id"]))["resolutions"] == 1
        assert (pending("mine"), pending("other"), pending("off")) == (False, True, True)
        assert tasks.sweep()["resolutions"] == 1
        assert (pending("other"), pending("off")) == (False, True)

    def test_a_pending_resolution_left_without_messages_is_dropped_not_reloaded(self, db, fake):
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        _age(db, cid)
        ConversationsRepository(db).truncate_after(cid, -1)  # a regenerate from the first message
        report = tasks.sweep()
        labels = _labels(db, cid)
        assert report["resolutions"] == 0 and report["rows"] == 0
        assert (None, "resolution") not in labels and (None, "experience") not in labels
        assert not ConversationLabelsRepository(db).pending_resolutions(schema.SCHEMA_HASH, VERSION, 24, 50)

    def test_a_pending_resolution_without_goal_met_is_rewritten_with_it(self, db, fake, monkeypatch):
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        _age(db, cid)
        db.execute(text("DELETE FROM conversation_labels WHERE label = 'goal_met'"))
        monkeypatch.setattr(settings, "ANALYTICS_TURN_SETTLE_SECONDS", 0)  # moving the messages back edited them
        report = tasks.sweep()
        assert report["resolutions"] == 0 and report["conversations"] == 1
        labels = _labels(db, cid)
        assert (None, "goal_met") in labels and labels[(None, "resolution")].probabilities["pending"] == 0

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

    def test_backfill_estimate_skips_what_the_servers_model_labelled(self, db, fake):
        _two_turns(db)
        tasks.sweep()
        server = _Server(answered=True)
        with installed(server):
            estimate = tasks.backfill_estimate(7)
        assert (estimate["messages"], estimate["conversations"], estimate["turns"]) == (0, 0, 0)
        assert server.probes == 1
        assert estimate["model_version"] == VERSION and "warning" not in estimate

    def test_backfill_estimate_says_when_the_server_did_not_answer(self, db, fake, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_BASE_URL", "http://decider:7095")
        _two_turns(db)
        tasks.sweep()
        with installed(_Server(answered=False)):
            estimate = tasks.backfill_estimate(7)
        assert estimate["model_version"] == version(V01)
        assert "did not answer" in estimate["warning"]

    def test_backfill_estimate_says_when_no_server_is_set(self, db, fake, monkeypatch):
        _two_turns(db)
        tasks.sweep()
        monkeypatch.setattr(settings, "DECISION_MODE", "api")  # and no DECISION_BASE_URL: the probe answers None
        monkeypatch.setattr("docsgpt.decisions._client", None)  # the real client, not the fake
        estimate = tasks.backfill_estimate(7)
        assert (estimate["messages"], estimate["model_version"]) == (2, version(V01))
        assert "DECISION_BASE_URL" in estimate["warning"] and "did not answer" not in estimate["warning"]

    def test_backfill_estimate_asks_no_server_in_local_mode(self, db, fake):
        _two_turns(db)
        tasks.sweep()
        estimate = tasks.backfill_estimate(7)
        assert (estimate["messages"], estimate["model_version"]) == (0, VERSION) and "warning" not in estimate


class _Server(FakeDecider):
    """A client in API mode: until it probes the server it assumes a server's default model (V01), as the real
    client does, and a probe that is answered learns the model the server runs (V02)."""

    def __init__(self, answered: bool):
        super().__init__(ANSWERS, model_version=version(V01))
        self.mode, self.answered, self.probes = "api", answered, 0

    def probe(self, timeout: float = 5.0) -> bool:
        self.probes += 1
        if self.answered:
            self.info = dataclasses.replace(self.info, version=VERSION)
        return self.answered


def _candidates(conn, **kwargs) -> list[dict]:
    return ConversationLabelsRepository(conn).message_candidates(schema.SCHEMA_HASH, VERSION, 30, 0, 50, **kwargs)


def _conversation_candidates(conn) -> list[dict]:
    return ConversationLabelsRepository(conn).conversation_candidates(schema.SCHEMA_HASH, VERSION, 30, 30, 50)


def _coverage(conn, user="owner") -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return ConversationLabelsRepository(conn).coverage(Scope(user_id=user), schema.SCHEMA_HASH,
                                                       now - datetime.timedelta(days=7), now,
                                                       now - datetime.timedelta(days=30))


@pytest.mark.unit
class TestAgentByKey:
    def test_a_key_only_conversation_resolves_its_agent_in_any_case(self, db, fake):
        agent = _agent(db, enabled=True)
        cid = _conversation(db, api_key=agent["key"].upper())
        _message(db, cid, 0, "How do I install it?")
        assert [c["agent_id"] for c in _candidates(db)] == [str(agent["id"])]
        tasks.sweep()
        assert {row.agent_id for row in _labels(db, cid).values()} == {str(agent["id"])}

    def test_another_owners_agent_by_key_is_out_of_a_users_coverage_in_any_case(self, db, fake):
        agent = _agent(db, enabled=True)
        cid = _conversation(db, api_key=agent["key"].upper(), user="someone")
        _message(db, cid, 0, "How do I install it?")
        assert _coverage(db, "someone")["turns"] == 0

    def test_the_agent_lookup_can_use_the_key_index(self, db):
        index = db.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'agents' AND indexdef LIKE '%(key)%'"
        )).scalar()
        db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(row[0] for row in db.execute(text(f"EXPLAIN SELECT ag.id FROM conversations c {_AGENT}")))
        assert index and index in plan


@pytest.mark.unit
class TestBlankText:
    def test_a_blank_prompt_never_holds_up_the_conversation(self, db, fake):
        cid = _conversation(db)
        _message(db, cid, 0, "How do I install it?")
        _message(db, cid, 1, " \n\t ", "ok")
        tasks.sweep()
        assert (None, "goal_met") in _labels(db, cid)
        assert not _candidates(db)

    def test_a_blank_answer_is_not_a_turn(self, db, fake):
        cid = _conversation(db)
        _message(db, cid, 0, "How do I install it?", "\n")
        _message(db, cid, 1, "and now?", f"{TERMINATED_RESPONSE_PLACEHOLDER}\n")
        assert tasks.backfill_estimate(7)["turns"] == 0
        tasks.sweep()
        coverage = _coverage(db)
        assert (coverage["turns"], coverage["unlabelled_recent_turns"]) == (0, 0)

    def test_sql_and_python_agree_on_whitespace(self, db):
        python = "".join(c for c in map(chr, range(0x110000)) if c.isspace())
        assert set(states.WHITESPACE) == set(python)
        query = text(f"""SELECT {_has_text("CAST(:t AS text)")} AS has_text, {_is_turn("m")} AS is_turn
                         FROM (SELECT 'complete'::text AS status, CAST(:t AS text) AS response) m""")
        for c in [*python, "\u200b", "\u00ad", "a"]:  # a zero-width space and a soft hyphen are not whitespace
            for value in (c * 2, f"{c}{TERMINATED_RESPONSE_PLACEHOLDER}{c}", f"{c}a"):
                row = db.execute(query, {"t": value, "placeholder": TERMINATED_RESPONSE_PLACEHOLDER}).one()
                message = states.Message(id="m", prompt=value, response=value)
                assert (row.has_text, row.is_turn) == (bool(value.strip()), message.is_turn), (hex(ord(c)), value)

    def test_a_prompt_of_whitespace_python_strips_is_never_a_candidate(self, db, fake):
        cid = _conversation(db)
        _message(db, cid, 0, "\u00a0\x1f\u3000")
        tasks.sweep()
        assert not _labels(db, cid) and not _candidates(db) and not _conversation_candidates(db)

    def test_a_conversation_the_states_drop_whole_gets_an_error_marker(self, db, fake, monkeypatch):
        cid = _conversation(db)
        dropped = _message(db, cid, 0, "drop me")
        monkeypatch.setattr(tasks.states, "messages", lambda rows: [])
        report = tasks.sweep()
        labels = _labels(db, cid)
        assert labels[(dropped, "_error")].top == labels[(None, "_error")].top == "build_failed"
        assert report["conversations"] == 1 and not fake.calls
        assert not _candidates(db) and not _conversation_candidates(db)

    def test_a_message_the_states_drop_still_gets_a_marker(self, db, fake, monkeypatch):
        cid = _conversation(db)
        _message(db, cid, 0, "How do I install it?")
        dropped = _message(db, cid, 1, "drop me")
        real = tasks.states.messages
        monkeypatch.setattr(tasks.states, "messages",
                            lambda rows: [m for m in real(rows) if m.prompt != "drop me"])
        tasks.sweep()
        labels = _labels(db, cid)
        assert labels[(dropped, "_error")].top == "build_failed"
        assert (None, "goal_met") in labels and not _candidates(db)


@pytest.mark.unit
class TestFailedTurns:
    def test_turns_whose_states_failed_are_counted_failed_not_pending(self, db):
        _two_turns(db)
        with installed(_Partial(lambda r: "answer_status" in r.questions, "bad_item")):
            tasks.sweep()
        coverage = _coverage(db)
        assert (coverage["turns"], coverage["labelled_turns"]) == (2, 0)
        assert (coverage["unlabelled_recent_turns"], coverage["failed_turns"]) == (0, 2)

    def test_an_edit_after_the_failure_makes_the_turn_pending_again(self, db, monkeypatch):
        cid, first, _ = _two_turns(db)
        with installed(_Partial(lambda r: "answer_status" in r.questions, "bad_item")):
            tasks.sweep()
        db.execute(text("UPDATE conversation_messages SET response = 'Regenerated.' WHERE id = CAST(:id AS uuid)"),
                   {"id": first})
        coverage = _coverage(db)
        assert (coverage["unlabelled_recent_turns"], coverage["failed_turns"]) == (1, 1)


class _Editing(FakeDecider):
    """Answers as ``FakeDecider``, and runs ``edit`` once, during the first call of ``feature``."""

    def __init__(self, feature, edit):
        super().__init__(ANSWERS)
        self.feature, self.edit = feature, edit

    def decide_batch(self, requests, *, feature, budget=Budget.HOT):
        if feature == self.feature and self.edit is not None:
            self.edit, edit = None, self.edit
            edit()
        return super().decide_batch(requests, feature=feature, budget=budget)


def _respond(conn, message_id, response):
    conn.execute(text("UPDATE conversation_messages SET response = :r WHERE id = CAST(:id AS uuid)"),
                 {"r": response, "id": message_id})


@pytest.mark.unit
class TestFreshness:
    def test_an_edit_during_the_call_leaves_the_message_to_the_next_sweep(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_TURN_SETTLE_SECONDS", 0)
        cid, _, second = _two_turns(db)
        editing = _Editing("analytics_turn", lambda: _respond(db, second, "Regenerated."))
        with installed(editing):
            tasks.sweep()
            assert [c["conversation_id"] for c in _candidates(db)] == [cid]
            calls = len(editing.calls)
            tasks.sweep()
        asked = editing.calls[calls]
        assert asked.feature == "analytics_turn" and asked.requests[0].state["answer"] == "Regenerated."
        assert not _candidates(db)

    def test_an_edit_during_the_conversation_call_asks_the_conversation_again(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ANALYTICS_TURN_SETTLE_SECONDS", 0)
        cid, first, _ = _two_turns(db)
        editing = _Editing("analytics_conversation", lambda: _respond(db, first, "Regenerated."))
        with installed(editing):
            tasks.sweep()
            assert (None, "goal_met") in _labels(db, cid)
            calls = len(editing.calls)
            tasks.sweep()
        assert [c.feature for c in editing.calls[calls:]] == ["analytics_turn", "analytics_conversation"]

    def test_feedback_and_a_finished_background_job_relabel_nothing(self, db, fake, monkeypatch):
        cid = _conversation(db)
        first = _message(db, cid, 0, "How do I install it?",
                         tool_calls=[{"call_id": "c1", "job_id": "job-1", "status": "running"}])
        _message(db, cid, 1, "and on Windows?")
        tasks.sweep()
        db.execute(text("UPDATE conversation_labels SET created_at = now() - interval '10 minutes'"))
        repo = ConversationsRepository(db)
        assert repo.set_feedback(cid, 1, {"text": "dislike"})
        assert repo.patch_tool_call(first, "job-1", {"status": "completed"})
        monkeypatch.setattr(settings, "ANALYTICS_TURN_SETTLE_SECONDS", 0)
        calls = len(fake.calls)
        report = tasks.sweep()
        assert len(fake.calls) == calls and report["messages"] == 0 and not _candidates(db)


class _Clock:
    """``tasks.time`` with a clock that moves only when told."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class _Slow(FakeDecider):
    """Answers as ``FakeDecider``; every call takes ``seconds`` of the fake clock."""

    def __init__(self, clock, seconds):
        super().__init__(ANSWERS)
        self.clock, self.seconds = clock, seconds

    def decide_batch(self, requests, *, feature, budget=Budget.HOT):
        self.clock.now += self.seconds
        return super().decide_batch(requests, feature=feature, budget=budget)


@pytest.fixture
def slow(monkeypatch):
    """A decider whose calls take 10 s of a fake clock, at one two-turn conversation (5 states) per call."""
    clock = _Clock()
    monkeypatch.setattr(tasks, "time", clock)
    monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 5)
    with installed(_Slow(clock, 10.0)) as decider:
        yield decider


def _count(conn, label) -> int:
    return conn.execute(text("SELECT COUNT(*) FROM conversation_labels WHERE label = :label"),
                        {"label": label}).scalar()


@pytest.mark.unit
class TestBacklog:
    def test_a_sustained_backlog_leaves_time_for_conversations(self, db, slow):
        for _ in range(20):
            _two_turns(db)
        report = tasks.sweep(budget_seconds=100)
        assert report["stopped"] == "budget"
        assert "analytics_conversation" in [c.feature for c in slow.calls]
        assert _count(db, "goal_met") > 0 and _count(db, "experience") == _count(db, "goal_met")

    def test_a_quiet_agents_older_message_is_not_starved(self, db, slow):
        busy, quiet = _agent(db, enabled=True), _agent(db, enabled=True)
        for _ in range(6):
            _two_turns(db, agent_id=str(busy["id"]))
        cid = _conversation(db, agent_id=str(quiet["id"]))
        old = _message(db, cid, 0, "How do I install it?", ago_minutes=600)
        assert [c["conversation_id"] for c in _candidates(db)][1] == cid
        tasks.sweep(budget_seconds=30)
        assert (old, "request_type") in _labels(db, cid)

    def test_no_agent_conversations_take_turns_by_user(self, db):
        ann = [_conversation(db, user="ann") for _ in range(3)]
        bob = _conversation(db, user="bob")
        for i, cid in enumerate(ann):
            _message(db, cid, 0, "How do I install it?", ago_minutes=100 + i)
        _message(db, bob, 0, "How do I install it?", ago_minutes=500)
        assert [c["conversation_id"] for c in _candidates(db)] == [ann[0], bob, ann[1], ann[2]]

    def test_what_failed_comes_after_the_rest_the_least_recently_tried_first(self, db, fake):
        cids = [_conversation(db) for _ in range(4)]
        messages = [_message(db, cid, 0, "How do I install it?", ago_minutes=100 + i) for i, cid in enumerate(cids)]
        now = datetime.datetime.now(datetime.timezone.utc)

        def failed(level):  # the newest two failed, the newest one last
            for i in (0, 1):
                ConversationLabelsRepository(db).upsert_many([{
                    "conversation_id": cids[i], "message_id": messages[i] if level == "message" else None,
                    "user_id": "owner", "level": level, "label": "_retry", "probabilities": {"attempts": 1},
                    "schema_hash": schema.SCHEMA_HASH, "model_version": VERSION, "occurred_at": now,
                    "source_updated_at": now}])
                db.execute(text("UPDATE conversation_labels SET created_at = now() - make_interval(hours => :h)"
                                " WHERE conversation_id = CAST(:cid AS uuid) AND label = '_retry'"),
                           {"h": 1 + i, "cid": cids[i]})

        failed("message")
        assert [c["conversation_id"] for c in _candidates(db)] == [cids[2], cids[3], cids[1], cids[0]]
        tasks.Sweep(VERSION).message_pass()  # labelled: their conversations are candidates
        failed("conversation")
        assert [c["conversation_id"] for c in _conversation_candidates(db)] == [cids[2], cids[3], cids[1], cids[0]]

    def test_a_success_clears_the_attempts_before_it(self, db, fake):
        # Attempts count one episode: kept past a success, a later re-ask (a topic change) would start near the
        # limit and one failure would mark the conversation for good.
        cid = _conversation(db)
        mid = _message(db, cid, 0, "How do I install it?", ago_minutes=300)
        now = datetime.datetime.now(datetime.timezone.utc)

        def retry(message_id, level):
            ConversationLabelsRepository(db).upsert_many([{
                "conversation_id": cid, "message_id": message_id, "user_id": "owner", "level": level,
                "label": "_retry", "probabilities": {"attempts": 2}, "schema_hash": schema.SCHEMA_HASH,
                "model_version": VERSION, "occurred_at": now, "source_updated_at": now}])

        retry(mid, "message")
        tasks.Sweep(VERSION).message_pass()
        assert (mid, "request_type") in _labels(db, cid) and (mid, "_retry") not in _labels(db, cid)
        retry(None, "conversation")
        tasks.Sweep(VERSION).conversation_pass()
        assert (None, "goal_met") in _labels(db, cid) and (None, "_retry") not in _labels(db, cid)

    def test_a_pending_resolution_settles_under_a_backlog(self, db, fake, monkeypatch):
        cid, _, _ = _two_turns(db)
        tasks.sweep()
        db.execute(text("UPDATE conversation_messages SET timestamp = timestamp - interval '2 days' "
                        "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid})
        db.execute(text("UPDATE conversation_labels SET occurred_at = occurred_at - interval '2 days' "
                        "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid})
        for _ in range(20):
            _two_turns(db)
        clock = _Clock()
        monkeypatch.setattr(tasks, "time", clock)
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 5)
        with installed(_Slow(clock, 10.0)):
            report = tasks.sweep(budget_seconds=30)
        assert report["resolutions"] == 1
        assert _labels(db, cid)[(None, "resolution")].probabilities["pending"] == 0

    def test_a_conversation_deleted_while_its_resolution_settles_is_skipped(self, db, fake, monkeypatch):
        from sqlalchemy.exc import IntegrityError

        gone, _, _ = _two_turns(db)
        kept, _, _ = _two_turns(db)
        tasks.sweep()
        for cid in (gone, kept):
            db.execute(text("UPDATE conversation_messages SET timestamp = timestamp - interval '2 days' "
                            "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid})
            db.execute(text("UPDATE conversation_labels SET occurred_at = occurred_at - interval '2 days' "
                            "WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid})
        real = ConversationLabelsRepository.upsert_many

        def deleted_meanwhile(repo, rows):
            if rows and rows[0]["conversation_id"] == gone:
                raise IntegrityError("INSERT", {}, Exception("conversation_labels_conversation_id_fkey"))
            return real(repo, rows)

        monkeypatch.setattr(ConversationLabelsRepository, "upsert_many", deleted_meanwhile)
        sweep = tasks.Sweep(VERSION)
        sweep.pending_pass()
        assert sweep.stats["resolutions"] == 1
        assert _labels(db, kept)[(None, "resolution")].probabilities["pending"] == 0

    @pytest.mark.parametrize("budget", [100, 200])
    def test_one_long_conversation_keeps_to_the_message_share_and_resumes_after(self, db, monkeypatch, budget):
        clock = _Clock()
        monkeypatch.setattr(tasks, "time", clock)
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 5)
        idle = _conversation(db)
        _message(db, idle, 0, "How do I install it?", ago_minutes=600)
        with installed(FakeDecider(ANSWERS)):
            tasks.Sweep(VERSION).message_pass()  # its messages labelled, its own labels not yet asked
        assert (None, "goal_met") not in _labels(db, idle)
        long = _conversation(db)
        for position in range(60):
            _message(db, long, position, f"Question {position}?")
        with installed(_Slow(clock, 20.0)) as slow:
            tasks.sweep(budget_seconds=budget)
        assert (None, "goal_met") in _labels(db, idle)
        features = [c.feature for c in slow.calls]
        turns = [r.state["question"] for c in slow.calls for r in c.requests if "answer_status" in r.questions]
        assert len(turns) == len(set(turns))  # nothing asked twice
        if budget == 200:  # the message pass picks the long conversation up again after the conversation pass
            assert features[features.index("analytics_conversation") + 1:] == ["analytics_turn"] * 2
            assert _count(db, "request_type") == len(turns) + 1

    def test_messages_count_only_those_labelled(self, db, slow):
        for _ in range(3):
            cid = _conversation(db)
            _message(db, cid, 0, "How do I install it?")
        report = tasks.sweep(budget_seconds=5)  # one call of two messages; the third is queued, never asked
        assert report["messages"] == _count(db, "request_type") == 2


@pytest.mark.unit
class TestBatchCap:
    def test_the_decision_limit_caps_the_batch(self, db, fake, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MAX_BATCH_STATES", 8)
        cids = [_two_turns(db)[0] for _ in range(3)]
        report = tasks.sweep()
        assert max(len(c.requests) for c in fake.calls) <= 8
        assert report["messages"] == 6 and all((None, "goal_met") in _labels(db, cid) for cid in cids)

    def test_a_message_larger_than_the_limit_is_split_across_calls(self, db, fake, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MAX_BATCH_STATES", 2)
        agent = _agent(db, topics=TOPICS)
        cid, first, second = _two_turns(db, agent_id=str(agent["id"]))
        tasks.sweep()
        assert max(len(c.requests) for c in fake.calls) <= 2
        labels = _labels(db, cid)
        assert {(second, "answer_status"), (first, "reaction"), (second, "topic"), (second, "request_type"),
                (None, "goal_met")} <= set(labels)

    def test_a_split_message_keeps_no_marker_when_a_part_was_not_answered(self, db, monkeypatch):
        monkeypatch.setattr(settings, "DECISION_MAX_BATCH_STATES", 2)
        cid, first, second = _two_turns(db)
        with installed(_Failing(lambda r: "reaction" in r.questions, "timeout")):
            report = tasks.sweep()
        labels = _labels(db, cid)
        assert (first, "request_type") in labels
        assert not [key for key in labels if key[0] == second] and (first, "reaction") not in labels
        assert report["timeouts"] >= 1


_CANDIDATE_QUERIES = ("message_candidates", "conversation_candidates", "pending_resolutions")


@pytest.fixture
def excludes(monkeypatch):
    """The ``exclude`` every candidate query is asked with, per query, in order."""
    asked: dict[str, list[set]] = {name: [] for name in _CANDIDATE_QUERIES}
    for name in _CANDIDATE_QUERIES:
        real = getattr(ConversationLabelsRepository, name)

        def spy(self, *args, _real=real, _name=name, **kwargs):
            asked[_name].append(set(kwargs.get("exclude", ())))
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(ConversationLabelsRepository, name, spy)
    return asked


class _Reasons(FakeDecider):
    """Fails, on every call of a feature, the requests whose state mentions a text, each with its reason."""

    def __init__(self, reasons: dict[tuple[str, str], str]):
        super().__init__(ANSWERS)
        self.reasons = reasons

    def decide_batch(self, requests, *, feature, budget=Budget.HOT):
        result = super().decide_batch(requests, feature=feature, budget=budget)
        why = [next((reason for (f, needle), reason in self.reasons.items()
                     if f == feature and needle in json.dumps(r.state)), None) for r in requests]
        return BatchResult([None if w else d for d, w in zip(result, why)], why)


def _asked_about(calls, feature, needle) -> int:
    return sum(needle in json.dumps(r.state) for c in calls if c.feature == feature for r in c.requests)


class _NoRows:
    def fetchall(self):
        return []


class _Recorder:
    """A connection that records the statements run on it and returns no rows."""

    def __init__(self):
        self.statements: list[tuple[Any, dict]] = []

    def execute(self, statement, params=None):
        self.statements.append((statement, params or {}))
        return _NoRows()


def _generic_plan(conn, statement, params: dict) -> str:
    """``EXPLAIN`` of ``statement`` as a prepared statement's generic plan: the plan psycopg's prepared statements
    get from Postgres after a few runs on one connection (``plan_cache_mode`` forces it on the first)."""
    names: list[str] = []

    def number(match):
        if match.group(1) not in names:
            names.append(match.group(1))
        return f"${names.index(match.group(1)) + 1}"

    def literal(value):
        if isinstance(value, (list, tuple, set)):
            value = "{" + ",".join(value) + "}"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return repr(value)

    sql = re.sub(r"%\((\w+)\)s", number, str(statement.compile(dialect=conn.dialect))).replace("%%", "%")
    conn.exec_driver_sql("SET LOCAL plan_cache_mode = force_generic_plan")
    conn.exec_driver_sql(f"PREPARE candidates AS {sql}")
    try:
        args = ", ".join(literal(params[name]) for name in names)
        return "\n".join(row[0] for row in conn.exec_driver_sql(f"EXPLAIN EXECUTE candidates({args})"))
    finally:
        conn.exec_driver_sql("DEALLOCATE candidates")


@pytest.mark.unit
class TestScale:
    def test_a_long_conversation_writes_each_derived_row_about_once(self, db, fake, monkeypatch):
        # Each call recomputes the conversation's derived rows; only those whose value changed are written, so a
        # conversation of N messages costs about N derived writes, not N squared.
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 4)
        agent = _agent(db, topics=TOPICS)
        cid = _conversation(db, agent_id=str(agent["id"]))
        for i in range(20):
            _message(db, cid, i, "How do I install it?" if i % 5 == 0 else "and then?", ago_minutes=300)
        written = []
        real = ConversationLabelsRepository.upsert_many

        def counting(repo, rows):
            written.extend(row for row in rows if row.get("derived"))
            return real(repo, rows)

        monkeypatch.setattr(ConversationLabelsRepository, "upsert_many", counting)
        tasks.sweep()
        final = [row for row in _labels(db, cid).values() if row.derived]
        assert len(final) == 42  # gap_type and topic_effective per message, resolution and experience
        assert len(written) <= 2 * len(final)

    def test_a_backfill_excludes_only_what_may_come_back(self, db, fake, excludes, monkeypatch):
        monkeypatch.setattr(tasks, "PAGE", 4)
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 4)  # two one-message conversations a call
        cids = []
        for i in range(30):
            cids.append(_conversation(db))
            _message(db, cids[-1], 0, "How do I install it?", ago_minutes=100 + i)
        report = tasks.sweep()
        assert report["messages"] == 30 and report["conversations"] == 30 and report["stopped"] is None
        assert all((None, "goal_met") in _labels(db, cid) for cid in cids)
        assert _asked_about(fake.calls, "analytics_turn", "install") == 60  # each message's two states, once
        assert max(len(exclude) for asked in excludes.values() for exclude in asked) <= tasks.PAGE

    def test_what_stays_a_candidate_stays_excluded_and_the_backfill_ends(self, db, excludes, monkeypatch):
        monkeypatch.setattr(tasks, "PAGE", 3)
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 4)
        prompts = {3: "retry me", 7: "late one", 9: "How do I pay?"}
        cids = {}
        for i in range(12):
            cid = _conversation(db)
            _message(db, cid, 0, prompts.get(i, "How do I install it?"), ago_minutes=100 + i)
            cids[prompts.get(i, cid)] = cid
        failing = _Reasons({("analytics_turn", "retry me"): "backend_error", ("analytics_turn", "late one"): "timeout",
                            ("analytics_conversation", "pay?"): "backend_error"})
        with installed(failing):
            report = tasks.sweep()
        assert report["stopped"] is None and report["retries"] == 2 and report["timeouts"] == 2
        for needle, feature in (("retry me", "analytics_turn"), ("late one", "analytics_turn"),
                                ("pay?", "analytics_conversation")):
            per_message = 2 if feature == "analytics_turn" else 1
            assert _asked_about(failing.calls, feature, needle) == per_message, needle
        retried, late, paid = cids["retry me"], cids["late one"], cids["How do I pay?"]
        assert [key[1] for key in _labels(db, retried)] == ["_retry"] and not _labels(db, late)
        assert (None, "_retry") in _labels(db, paid) and (None, "goal_met") not in _labels(db, paid)
        assert sum((None, "goal_met") in _labels(db, cid) for cid in cids.values()) == 9
        later = [exclude for exclude in excludes["message_candidates"] if retried in exclude]
        assert later and all(late in exclude for exclude in later[1:])
        assert max(len(exclude) for exclude in excludes["message_candidates"]) <= 3  # the two, a call queued
        assert any(paid in exclude for exclude in excludes["conversation_candidates"])
        assert max(len(exclude) for exclude in excludes["conversation_candidates"]) <= tasks.PAGE + 1

    @pytest.mark.parametrize("query", _CANDIDATE_QUERIES)
    def test_the_exclusion_is_hashed_in_a_generic_plan(self, db, query):
        recorder = _Recorder()
        args = {"message_candidates": (30, 60, 50), "conversation_candidates": (30, 30, 50),
                "pending_resolutions": (24, 50)}[query]
        exclude = [str(uuid.uuid4()) for _ in range(3)]
        getattr(ConversationLabelsRepository(recorder), query)(schema.SCHEMA_HASH, VERSION, *args, exclude=exclude)
        (statement, params), = recorder.statements
        plan = _generic_plan(db, statement, params)
        assert "NOT (hashed SubPlan" in plan and "<> ALL" not in plan, plan

    def test_a_backfill_holds_the_rows_of_about_a_call(self, db, fake, monkeypatch):
        monkeypatch.setattr(tasks, "PAGE", 4)
        monkeypatch.setattr(settings, "ANALYTICS_BATCH_STATES", 4)
        for _ in range(12):
            _two_turns(db)
        held: list[int] = []
        real = tasks.Sweep._load

        def load(self, conn, conversation_id):
            msgs = real(self, conn, conversation_id)
            held.append(max(len(self._messages), len(self._conversations)))
            return msgs

        monkeypatch.setattr(tasks.Sweep, "_load", load)
        sweep = tasks.Sweep(VERSION)
        report = sweep.run()
        assert report["messages"] == 24 and report["conversations"] == 12
        # at most the conversations of one call: the conversation pass asks one state of each
        assert max(held) <= settings.ANALYTICS_BATCH_STATES and not sweep._messages and not sweep._conversations


@pytest.mark.unit
class TestSourceMessages:
    def test_only_what_the_states_read_is_loaded_and_the_hash_is_unchanged(self, db):
        cid = _conversation(db)
        first = _message(db, cid, 0, "How do I install it?",
                         tool_calls=[{"call_id": "c1", "job_id": "job-1", "status": "running"}])
        second = _message(db, cid, 1, "and on Windows?")
        db.execute(text("UPDATE conversation_messages SET thought = 'thinking...',"
                        " attachments = ARRAY[gen_random_uuid()], message_metadata = '{\"request_id\": \"r\"}'"
                        " WHERE id = CAST(:id AS uuid)"), {"id": first})
        # the hash as it was always computed: what the states read, nothing else (stored labels compare with it)
        pinned = dict(db.execute(text(
            "SELECT CAST(id AS text), md5(jsonb_build_array(prompt, response, sources, status,"
            " extract(epoch FROM timestamp))::text) FROM conversation_messages"
            " WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid}).fetchall())
        loaded = ConversationLabelsRepository(db).source_messages(cid)
        rows = {row["id"]: row for row in loaded["messages"]}
        assert {m: rows[m]["source_hash"] for m in rows} == pinned
        assert {m: row["has_tool_calls"] for m, row in rows.items()} == {first: True, second: False}
        assert not {"thought", "attachments", "tool_calls", "feedback"} & set(rows[first])
        assert rows[first]["message_metadata"] == {"request_id": "r"}
        conversation_hash = db.execute(text(
            f"SELECT md5(string_agg({_message_hash('m')}, ',' ORDER BY m.position)) FROM conversation_messages m"
            " WHERE m.conversation_id = CAST(:cid AS uuid)"), {"cid": cid}).scalar()
        assert loaded["hash"] == conversation_hash
        msgs = states.messages(loaded["messages"])
        assert [m.id for m in msgs] == [first, second] and msgs[0].source_hash == pinned[first]
