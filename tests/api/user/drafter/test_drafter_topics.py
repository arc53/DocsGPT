"""Topic suggestions end to end: the status route, which questions are read, and the stream with a fake model."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.analytics import schema
from docsgpt.drafter.fencing import DATA_GUARD
from docsgpt.drafter.topics_recipe import DAYS, load_workspace, MIN_CONVERSATIONS
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversation_labels import ConversationLabelsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from tests.drafter.fakes import calls, FakeLLM, tool_call

MODEL = {"id": "task-model", "display_name": "Task Model", "supports_tools": True}


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@contextmanager
def _session(user="owner"):
    with patch("docsgpt.app.handle_auth", return_value={"sub": user}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.storage.db.session.db_readonly", _yield):
        yield


def _agent(conn, owner="owner", key=None, **analytics):
    return AgentsRepository(conn).create(
        owner, "Support bot", "published", key=key or f"key-{uuid.uuid4().hex[:8]}",
        config={"analytics": analytics} if analytics else {},
    )


def _message(conn, cid, position, prompt, *, days_ago=1.0):
    return conn.execute(
        text(
            """
            INSERT INTO conversation_messages (conversation_id, position, prompt, response, status, timestamp,
                                               updated_at)
            VALUES (CAST(:cid AS uuid), :position, :prompt, 'An answer.', 'complete',
                    now() - make_interval(secs => :ago), now() - make_interval(secs => :ago))
            RETURNING CAST(id AS text)
            """
        ),
        {"cid": cid, "position": position, "prompt": prompt, "ago": days_ago * 86400},
    ).scalar()


def _conversation(conn, user, *prompts, agent_id=None, api_key=None, days_ago=1.0):
    cid = str(ConversationsRepository(conn).create(user, "c", agent_id=agent_id, api_key=api_key)["id"])
    ids = [_message(conn, cid, i, prompt, days_ago=days_ago) for i, prompt in enumerate(prompts)]
    return cid, ids


def _busy_agent(conn, n=MIN_CONVERSATIONS, **analytics):
    agent = _agent(conn, **analytics)
    for i in range(n):
        _conversation(conn, f"user-{i}", f"Where is my parcel {i}?", agent_id=str(agent["id"]))
    return agent


def _share(conn, agent_id, owner, member, level):
    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    team = str(TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)["id"])
    TeamMembersRepository(conn).add_member(team, member)
    TeamResourceGrantsRepository(conn).grant(team, "agent", agent_id, owner, owner, access_level=level)


@pytest.fixture(autouse=True)
def _insights_on(monkeypatch):
    """Insights labels conversations here; shares stay the drafting model's estimates."""
    from docsgpt.core.settings import settings
    from docsgpt.drafter import topics_recipe

    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    monkeypatch.setattr("docsgpt.decisions.available", lambda: True)
    monkeypatch.setattr(topics_recipe, "measuring_available", lambda: False)


def _status(client, conn, user, agent_id):
    query = f"?agent_id={agent_id}" if agent_id else ""
    with _db(conn), _session(user):
        return client.get(f"/api/drafter/topics/status{query}")


@pytest.mark.unit
class TestStatus:
    def test_holds_until_enough_conversations(self, client, pg_conn):
        agent = _busy_agent(pg_conn, n=MIN_CONVERSATIONS - 1)
        response = _status(client, pg_conn, "owner", agent["id"])
        assert response.status_code == 200
        assert response.get_json() == {"available": False, "conversations": MIN_CONVERSATIONS - 1,
                                       "needed": MIN_CONVERSATIONS, "reason": None}
        _conversation(pg_conn, "late", "Customs fee?", agent_id=str(agent["id"]))
        assert _status(client, pg_conn, "owner", agent["id"]).get_json()["available"] is True

    def test_counts_conversations_not_messages_and_only_recent_ones(self, client, pg_conn):
        agent = _agent(pg_conn)
        _conversation(pg_conn, "u", "a", "b", "c", agent_id=str(agent["id"]))
        _conversation(pg_conn, "u", "old", agent_id=str(agent["id"]), days_ago=DAYS + 1)
        assert _status(client, pg_conn, "owner", agent["id"]).get_json()["conversations"] == 1

    def test_is_unavailable_while_insights_is_off(self, client, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        agent = _busy_agent(pg_conn, enabled=False)
        assert _status(client, pg_conn, "owner", agent["id"]).get_json() == {
            "available": False, "conversations": 0, "needed": MIN_CONVERSATIONS,
            "reason": "turned_off_for_this_agent",
        }
        on = _busy_agent(pg_conn)
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        status = _status(client, pg_conn, "owner", on["id"]).get_json()
        assert status["available"] is False and status["reason"] == "off_on_this_instance"
        # Access is checked first.
        assert _status(client, pg_conn, "stranger", on["id"]).status_code == 404

    def test_is_unavailable_while_the_drafter_is_off(self, client, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        agent = _busy_agent(pg_conn)
        monkeypatch.setattr(settings, "DRAFTER_ENABLED", False)
        with patch.object(ConversationLabelsRepository, "agent_question_counts") as count:
            status = _status(client, pg_conn, "owner", agent["id"]).get_json()
            count.assert_not_called()
        assert status["available"] is False and status["reason"] == "disabled"

    def test_an_unexpected_failure_is_a_server_error(self, client, pg_conn):
        agent = _busy_agent(pg_conn)
        with patch.object(ConversationLabelsRepository, "agent_question_counts", side_effect=RuntimeError("db")):
            assert _status(client, pg_conn, "owner", agent["id"]).status_code == 500

    def test_needs_edit_access(self, client, pg_conn):
        agent = _busy_agent(pg_conn)
        assert _status(client, pg_conn, "stranger", agent["id"]).status_code == 404
        _share(pg_conn, str(agent["id"]), "owner", "viewer", "viewer")
        assert _status(client, pg_conn, "viewer", agent["id"]).status_code == 403
        _share(pg_conn, str(agent["id"]), "owner", "editor", "editor")
        assert _status(client, pg_conn, "editor", agent["id"]).get_json()["available"] is True
        assert _status(client, pg_conn, "owner", None).status_code == 400

    def test_an_access_token_is_refused(self, client):
        from docsgpt.api.pat.tokens import expand_scopes, SCOPES

        claims = {"sub": "owner", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
                  "scopes": sorted(expand_scopes(list(SCOPES))), "resource_filter": {}}
        with patch("docsgpt.app.handle_auth", return_value=claims):
            assert client.get("/api/drafter/topics/status?agent_id=x").status_code == 403


@pytest.mark.unit
class TestSampling:
    def test_only_the_agents_own_traffic_including_its_api_key(self, pg_conn):
        agent = _busy_agent(pg_conn, n=MIN_CONVERSATIONS)
        other = _agent(pg_conn)
        _conversation(pg_conn, "widget-user", "Asked through the widget", api_key=agent["key"])
        _conversation(pg_conn, "owner", "Another agent of the owner", agent_id=str(other["id"]))
        _conversation(pg_conn, "owner", "The owner's plain chat")
        _conversation(pg_conn, "x", "Through another key", api_key=other["key"])
        _conversation(pg_conn, "u", "Too old", agent_id=str(agent["id"]), days_ago=DAYS + 1)
        with _db(pg_conn):
            ws = load_workspace("owner", {"agent_id": str(agent["id"])})
        read = ws.unmatched + ws.other
        assert "Asked through the widget" in read and "Where is my parcel 0?" in read
        for missing in ("Another agent of the owner", "The owner's plain chat", "Through another key", "Too old"):
            assert missing not in read
        assert ws.conversations == MIN_CONVERSATIONS + 1 and ws.counts()["questions"] == len(read)

    def test_repeats_are_read_once_and_unmatched_ones_first(self, pg_conn):
        from docsgpt.decisions.models import V02, version

        agent = _busy_agent(pg_conn)
        _conversation(pg_conn, "a", "How do I return a sofa?", agent_id=str(agent["id"]))
        cid, (unmatched,) = _conversation(pg_conn, "b", "  how do I return a sofa? ", agent_id=str(agent["id"]),
                                          days_ago=2)
        _, (matched,) = _conversation(pg_conn, "c", "Do you ship to Oslo?", agent_id=str(agent["id"]), days_ago=3)
        base = {"conversation_id": cid, "user_id": "b", "agent_id": str(agent["id"]), "level": "message",
                "label": "topic", "lang": "en", "schema_hash": schema.SCHEMA_HASH, "model_version": version(V02)}
        ConversationLabelsRepository(pg_conn).upsert_many([
            {**base, "message_id": matched, "probabilities": {"shipping": 0.9, schema.NONE_OPTION: 0.1},
             "occurred_at": "2026-10-30T00:00:00Z"},
        ])
        _, (old_sofa,) = _conversation(pg_conn, "d", "Sofa assembly help", agent_id=str(agent["id"]), days_ago=4)
        ConversationLabelsRepository(pg_conn).upsert_many([
            {**base, "message_id": old_sofa, "probabilities": {"shipping": 0.2, schema.NONE_OPTION: 0.8},
             "occurred_at": "2026-10-30T00:00:00Z"},
        ])
        with _db(pg_conn):
            ws = load_workspace("owner", {"agent_id": str(agent["id"])})
        assert ws.unmatched == ["Sofa assembly help"]
        assert [q.lower().strip() for q in ws.other].count("how do i return a sofa?") == 1
        assert "Do you ship to Oslo?" in ws.other

    def test_repeats_differing_only_in_spacing_are_read_once(self, pg_conn):
        agent = _busy_agent(pg_conn)
        _conversation(pg_conn, "a", "Where do I\n\nsend  a return?", agent_id=str(agent["id"]))
        _conversation(pg_conn, "b", "where do i send a return?", agent_id=str(agent["id"]), days_ago=2)
        with _db(pg_conn):
            ws = load_workspace("owner", {"agent_id": str(agent["id"])})
        assert [q for q in ws.other if "return" in q] == ["Where do I send a return?"]

    def test_the_status_counts_up_to_what_it_needs(self, pg_conn):
        agent = _busy_agent(pg_conn, n=MIN_CONVERSATIONS + 3)
        repo = ConversationLabelsRepository(pg_conn)
        assert repo.agent_question_counts(str(agent["id"]), agent["key"], DAYS, cap=MIN_CONVERSATIONS) == {
            "conversations": MIN_CONVERSATIONS}
        assert repo.agent_question_counts(str(agent["id"]), agent["key"], DAYS)["conversations"] == \
            MIN_CONVERSATIONS + 3

    def test_nothing_is_read_while_insights_is_off(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.drafter.recipe import BadDraftRequest

        off = _busy_agent(pg_conn, enabled=False)
        on = _busy_agent(pg_conn)
        with _db(pg_conn), patch.object(ConversationLabelsRepository, "agent_questions") as read:
            with pytest.raises(BadDraftRequest, match="Insights are off for this agent"):
                load_workspace("owner", {"agent_id": str(off["id"])})
            monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
            with pytest.raises(BadDraftRequest, match="Insights are off on this server"):
                load_workspace("owner", {"agent_id": str(on["id"])})
            read.assert_not_called()

    def test_too_few_conversations_or_no_edit_access_is_refused(self, pg_conn):
        from docsgpt.drafter.recipe import BadDraftRequest

        quiet = _busy_agent(pg_conn, n=MIN_CONVERSATIONS - 1)
        busy = _busy_agent(pg_conn)
        with _db(pg_conn):
            with pytest.raises(BadDraftRequest, match="Suggestions need"):
                load_workspace("owner", {"agent_id": str(quiet["id"])})
            with pytest.raises(BadDraftRequest, match="not found"):
                load_workspace("stranger", {"agent_id": str(busy["id"])})

    def test_reads_topics_folders_and_room(self, pg_conn):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        structure = {"shipping": {"rates.md": {"token_count": 9}}, "returns": {"labels.md": {"token_count": 3}}}
        source = SourcesRepository(pg_conn).create("Docs", user_id="owner", directory_structure=structure)
        agent = _busy_agent(pg_conn, topics=[{"id": "abcdefgh1", "name": "Billing", "description": "Invoices.",
                                             "overlap": False}], hidden_folders=["returns"])
        AgentsRepository(pg_conn).update(str(agent["id"]), "owner", {"source_id": str(source["id"])})
        with _db(pg_conn):
            ws = load_workspace("owner", {"agent_id": str(agent["id"])})
        assert ws.own == [{"name": "Billing", "description": "Invoices.", "overlap": False}]
        assert [f["name"] for f in ws.folders] == ["shipping", "returns"] and ws.hidden_folders == ["returns"]
        assert [f["name"] for f in ws.offered_folders()] == ["shipping"]
        assert ws.capacity() == {"one_per_question_free": 13, "one_per_question_max": 14, "overlapping_free": 20}


def _body(agent_id):
    return {"recipe": "topics", "messages": [{"role": "user", "content": "Suggest topics."}],
            "context": {"agent_id": agent_id}}


def _events(response) -> list[dict]:
    body = response.get_data(as_text=True)
    return [json.loads(chunk[len("data: "):]) for chunk in body.split("\n\n") if chunk.startswith("data: ")]


def _stream(client, conn, body, fake=None, user="owner"):
    with _db(conn), _session(user), patch("docsgpt.drafter.service.drafter_model", return_value=MODEL), patch(
        "docsgpt.drafter.runner.build_llm", fake.factory if fake else None
    ):
        return _events(client.post("/api/drafter/stream", json=body))


@pytest.mark.unit
class TestStream:
    def test_one_turn_ends_in_suggestions(self, client, pg_conn):
        agent = _busy_agent(pg_conn)
        fake = FakeLLM(calls(tool_call("submit_proposal", {
            "message": "Most questions are about parcels.",
            "topics": [{"name": "Delivery delays", "description": "Late or stuck parcels.", "overlap": False,
                        "share": 0.6}],
            "left_out": [],
        })))
        events = _stream(client, pg_conn, _body(str(agent["id"])), fake)
        assert [e["type"] for e in events] == ["status", "status", "status", "proposal", "end"]
        assert events[0] == {"type": "status", "step": "reading"}
        assert events[1]["counts"] == {"questions": MIN_CONVERSATIONS, "conversations": MIN_CONVERSATIONS}
        proposal = events[3]["proposal"]
        assert proposal["topics"][0]["id"] == "t1" and proposal["topics"][0]["share_kind"] == "estimate"
        assert proposal["sample"] == {"questions": MIN_CONVERSATIONS, "conversations": MIN_CONVERSATIONS,
                                      "days": DAYS}
        sent = fake.calls[0]["messages"][-1]["content"]
        assert "Where is my parcel 3?" in sent and DATA_GUARD in sent

    def test_too_few_conversations_is_a_bad_request(self, client, pg_conn):
        agent = _busy_agent(pg_conn, n=2)
        events = _stream(client, pg_conn, _body(str(agent["id"])))
        # The read runs on the stream: the refusal follows the reading status.
        assert [e["type"] for e in events] == ["status", "error", "end"]
        assert events[1]["code"] == "bad_request" and "Suggestions need" in events[1]["message"]

    def test_insights_off_for_the_agent_is_a_bad_request(self, client, pg_conn):
        agent = _busy_agent(pg_conn, enabled=False)
        events = _stream(client, pg_conn, _body(str(agent["id"])))
        assert events[1]["code"] == "bad_request" and "Insights are off" in events[1]["message"]
        assert "parcel" not in json.dumps(events)

    def test_someone_who_cant_edit_the_agent_reads_nothing(self, client, pg_conn):
        agent = _busy_agent(pg_conn)
        events = _stream(client, pg_conn, _body(str(agent["id"])), user="stranger")
        assert events[1]["code"] == "bad_request" and events[-1] == {"type": "end"}
        assert "parcel" not in json.dumps(events)
