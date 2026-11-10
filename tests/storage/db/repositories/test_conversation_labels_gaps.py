"""ConversationLabelsRepository's agent gap reads: the topic x gap type summary, examples per gap type, and turns
by Logs label, against a real Postgres."""

from __future__ import annotations

import datetime

import pytest

from docsgpt.analytics import schema
from docsgpt.storage.db.repositories.conversation_labels import (
    ConversationLabelsRepository,
    Scope,
    SUMMARY_GAP_TYPES,
)
from tests.drafter import insights_seed as seed


def _window(days=7):
    now = datetime.datetime.now(datetime.timezone.utc)
    return now - datetime.timedelta(days=days), now, now - datetime.timedelta(days=2 * days)


def _groups(conn, scope, *, by_topic, limit=10, min_expected=0.5):
    start, end, previous_start = _window()
    return ConversationLabelsRepository(conn).gap_type_groups(
        scope, schema.SCHEMA_HASH, start, end, previous_start, limit, min_expected, by_topic=by_topic)


@pytest.mark.unit
class TestGapTypeGroups:
    def test_sums_every_gap_type_but_other_per_topic(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        for _ in range(2):
            seed.turn(pg_conn, aid, gap={"docs missing": 0.5, "needs account data": 0.4, "other": 0.9},
                      topics={"Returns": 0.75, "Orders": 0.25})
        seed.turn(pg_conn, aid, gap={"needs account data": 0.8}, topics={"Orders": 1.0})
        rows = _groups(pg_conn, Scope(agent_id=aid, api_key=bot["key"]), by_topic=True)
        got = {(r["topic"], r["gap_type"]): r for r in rows}
        assert "other" not in SUMMARY_GAP_TYPES and all(r["gap_type"] != "other" for r in rows)
        # Orders: 2 x 0.4 x 0.25 + 0.8 = 1.0; Returns docs missing 2 x 0.5 x 0.75 = 0.75; Returns account 0.6
        assert [(r["topic"], r["gap_type"]) for r in rows] == [
            ("Orders", "needs account data"), ("Returns", "docs missing"), ("Returns", "needs account data")]
        assert got[("Orders", "needs account data")]["expected"] == pytest.approx(1.0)
        # turns are the topic's summed weights, the same for each of its gap types
        assert got[("Orders", "needs account data")]["turns"] == pytest.approx(1.5)
        assert got[("Returns", "docs missing")]["turns"] == pytest.approx(1.5)
        assert got[("Returns", "docs missing")]["previous"] == pytest.approx(0)

    def test_without_topics_one_row_per_gap_type_over_every_labelled_turn(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        seed.turn(pg_conn, aid, gap={"confidently ungrounded": 0.9})
        seed.turn(pg_conn, aid, gap={"confidently ungrounded": 0.3, "docs missing": 0.6})
        seed.turn(pg_conn, aid)
        seed.turn(pg_conn, aid, gap={"docs missing": 0.9}, days_ago=10)
        rows = _groups(pg_conn, Scope(agent_id=aid, api_key=bot["key"]), by_topic=False)
        assert [(r["topic"], r["gap_type"]) for r in rows] == [(None, "confidently ungrounded"),
                                                                (None, "docs missing")]
        assert rows[0]["expected"] == pytest.approx(1.2) and rows[0]["turns"] == pytest.approx(3)
        assert rows[1]["previous"] == pytest.approx(0.9)

    def test_min_expected_limit_and_scope(self, pg_conn):
        bot, other = seed.agent(pg_conn), seed.agent(pg_conn, owner="someone-else")
        aid = str(bot["id"])
        seed.turn(pg_conn, aid, gap={"docs missing": 0.9, "out of scope": 0.6, "ambiguous question": 0.4})
        seed.turn(pg_conn, str(other["id"]), gap={"feature not supported": 0.9})
        scope = Scope(agent_id=aid, api_key=bot["key"])
        assert [r["gap_type"] for r in _groups(pg_conn, scope, by_topic=False)] == ["docs missing", "out of scope"]
        assert [r["gap_type"] for r in _groups(pg_conn, scope, by_topic=False, limit=1)] == ["docs missing"]

    def test_gap_conversations_counts_labelled_conversations_in_the_window(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        cid, _ = seed.turn(pg_conn, aid)
        seed.turn(pg_conn, aid, cid=cid, position=1)
        seed.turn(pg_conn, aid)
        seed.turn(pg_conn, aid, days_ago=10)
        start, end, _ = _window()
        repo = ConversationLabelsRepository(pg_conn)
        assert repo.gap_conversations(Scope(agent_id=aid), schema.SCHEMA_HASH, start, end) == 2


@pytest.mark.unit
class TestGapExamplesByType:
    def test_examples_of_one_gap_type_likeliest_first(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        seed.turn(pg_conn, aid, "Where is MRD-1?", gap={"needs account data": 0.7})
        seed.turn(pg_conn, aid, "Where is MRD-2?", gap={"needs account data": 0.95})
        seed.turn(pg_conn, aid, "Docs?", gap={"docs missing": 0.9})
        start, end, _ = _window()
        repo = ConversationLabelsRepository(pg_conn)
        rows = repo.gap_examples("all", Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, [None], 0.5, 5,
                                 gap_type="needs account data")
        assert [r["prompt"] for r in rows] == ["Where is MRD-2?", "Where is MRD-1?"]
        # docs missing stays the default
        rows = repo.gap_examples("all", Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, [None], 0.5, 5)
        assert [r["prompt"] for r in rows] == ["Docs?"]

    def test_by_topic(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        seed.turn(pg_conn, aid, "Refund?", gap={"out of scope": 0.9}, topics={"Returns": 0.9, "Orders": 0.1})
        seed.turn(pg_conn, aid, "Order?", gap={"out of scope": 0.9}, topics={"Orders": 1.0})
        start, end, _ = _window()
        rows = ConversationLabelsRepository(pg_conn).gap_examples(
            "topic", Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, ["Returns"], 0.5, 5,
            gap_type="out of scope")
        assert [r["prompt"] for r in rows] == ["Refund?"]


@pytest.mark.unit
class TestLabelledTurns:
    def test_turns_by_logs_label_with_question_and_answer(self, pg_conn):
        bot, other = seed.agent(pg_conn), seed.agent(pg_conn, owner="someone-else")
        aid = str(bot["id"])
        seed.turn(pg_conn, aid, "Claim deadline?", gap={"docs missing": 0.9}, response="I could not find it.")
        seed.turn(pg_conn, aid, "Maybe a gap?", gap={"docs missing": 0.6})
        seed.turn(pg_conn, aid, "Not a gap", gap={"docs missing": 0.2})
        seed.turn(pg_conn, str(other["id"]), "Someone else's", gap={"docs missing": 0.99})
        start, end, _ = _window()
        repo = ConversationLabelsRepository(pg_conn)
        rows = repo.labelled_turns(Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, "docs_gap", 0.5, 5)
        assert [(r["prompt"], r["response"]) for r in rows] == [("Claim deadline?", "I could not find it."),
                                                                ("Maybe a gap?", "An answer.")]
        assert len(repo.labelled_turns(Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, "docs_gap", 0.5, 1)) \
            == 1

    def test_reply_labels_list_the_reacting_turn_and_a_topic_narrows(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        cid, first = seed.turn(pg_conn, aid, "Where is it?", topics={"Orders": 1.0})
        _, second = seed.turn(pg_conn, aid, "Let me talk to a person", cid=cid, position=1, topics={"Orders": 1.0})
        seed.reaction(pg_conn, aid, cid, first, second, "asks_human", 0.9)
        start, end, _ = _window()
        repo = ConversationLabelsRepository(pg_conn)
        rows = repo.labelled_turns(Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, "asks_human", 0.5, 5)
        assert [r["prompt"] for r in rows] == ["Let me talk to a person"]
        assert repo.labelled_turns(Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, "asks_human", 0.5, 5,
                                   topic="Orders") == rows
        assert repo.labelled_turns(Scope(agent_id=aid), schema.SCHEMA_HASH, start, end, "asks_human", 0.5, 5,
                                   topic="Returns") == []

    def test_conversation_turns_only_of_the_agents_conversation(self, pg_conn):
        bot, other = seed.agent(pg_conn), seed.agent(pg_conn, owner="someone-else")
        aid = str(bot["id"])
        cid, _ = seed.turn(pg_conn, aid, "First?")
        seed.turn(pg_conn, aid, "Second?", cid=cid, position=1)
        keyed, _ = seed.turn(pg_conn, None, "By key", api_key=bot["key"])
        foreign, _ = seed.turn(pg_conn, str(other["id"]), "Not yours")
        repo = ConversationLabelsRepository(pg_conn)
        assert [t["prompt"] for t in repo.agent_conversation_turns(cid, aid, bot["key"], 10)] == ["First?",
                                                                                                  "Second?"]
        assert [t["prompt"] for t in repo.agent_conversation_turns(keyed, aid, bot["key"], 10)] == ["By key"]
        assert repo.agent_conversation_turns(foreign, aid, bot["key"], 10) == []

    def test_conversation_turns_narrowed_to_one_message_of_that_conversation(self, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        cid, _ = seed.turn(pg_conn, aid, "First?")
        _, second = seed.turn(pg_conn, aid, "Second?", cid=cid, position=1)
        _, elsewhere = seed.turn(pg_conn, aid, "Elsewhere")
        repo = ConversationLabelsRepository(pg_conn)
        turns = repo.agent_conversation_turns(cid, aid, bot["key"], 10, message_id=second)
        assert [(t["id"], t["prompt"]) for t in turns] == [(second, "Second?")]
        assert repo.agent_conversation_turns(cid, aid, bot["key"], 10, message_id=elsewhere) == []
