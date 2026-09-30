"""Webhook and scheduled runs get the Wiki tool of an agent's wiki source.

A headless run acts as the agent's owner. A webhook, a schedule set through
the API and one a public-link user set are outside callers: they read the
wiki and edit it only when its owner allows outside edits. A schedule the
owner set in the app edits it like the owner. Nobody can approve a headless
write, so no action is ever put behind an approval.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository

OWNER = "alice"
ALL_ACTIONS = {"wiki_view", "wiki_create", "wiki_str_replace", "wiki_insert", "wiki_delete", "wiki_rename"}


def _wiki(conn, owner: str = OWNER) -> str:
    return str(SourcesRepository(conn).create("W", user_id=owner, config={"kind": "wiki"})["id"])


def _share(conn, sid: str, member: str, level: str) -> None:
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", OWNER)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(str(team["id"]), "source", sid, OWNER, OWNER, access_level=level)


def _run(monkeypatch, conn, source_id: str, *, agent_owner: str = OWNER, agent_type: str = "agentic", **run_kwargs):
    """Run a headless agent on ``source_id``; return its ``agent_kwargs``."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.return_value = iter([{"answer": "ok"}])
    agent.llm.token_usage = {}
    seen: dict = {}

    @contextmanager
    def _conn():
        yield conn

    def _create_agent(cls, _agent_type, **kwargs):
        seen.update(kwargs)
        return agent

    monkeypatch.setattr(hr, "db_readonly", _conn)
    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr, "build_dispatcher", lambda *_a, **_kw: MagicMock(search=MagicMock(return_value=[])))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[]))
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create_agent))
    monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)
    config = {
        "user_id": agent_owner, "id": str(uuid.uuid4()), "default_model_id": "m",
        "agent_type": agent_type, "source_id": source_id,
    }
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        hr.run_agent_headless(config, "read the wiki", **run_kwargs)
    return seen


def _actions(agent_kwargs: dict):
    """The Wiki tool actions a run offers, or None without the tool."""
    from docsgpt.agents.tools.wiki import WIKI_TOOL_ID, add_wiki_tool

    config = agent_kwargs.get("wiki_config")
    if not config:
        return None
    tools: dict = {}
    add_wiki_tool(tools, config)
    actions = tools[WIKI_TOOL_ID]["actions"]
    assert not any(a.get("require_approval") for a in actions)
    return {a["name"] for a in actions}


@pytest.mark.unit
class TestWebhookWiki:
    def test_reads_until_the_owner_allows_outside_edits(self, monkeypatch, pg_conn):
        sid = _wiki(pg_conn)
        seen = _run(monkeypatch, pg_conn, sid, endpoint="webhook")
        assert _actions(seen) == {"wiki_view"}
        assert seen["wiki_config"]["outside_caller"] is True
        assert seen["wiki_config"]["source_owner_id"] == OWNER

        SourcesRepository(pg_conn).set_wiki_outside_edits(sid, OWNER, True)
        assert _actions(_run(monkeypatch, pg_conn, sid, endpoint="webhook")) == ALL_ACTIONS

    @pytest.mark.parametrize("agent_type", ["classic", "research"])
    def test_every_tool_building_agent_type_gets_it(self, monkeypatch, pg_conn, agent_type):
        sid = _wiki(pg_conn)
        assert _actions(_run(monkeypatch, pg_conn, sid, agent_type=agent_type, endpoint="webhook")) == {"wiki_view"}

    def test_classic_source_gets_no_wiki_tool(self, monkeypatch, pg_conn):
        sid = str(SourcesRepository(pg_conn).create("Docs", user_id=OWNER)["id"])
        assert _actions(_run(monkeypatch, pg_conn, sid, endpoint="webhook")) is None


@pytest.mark.unit
class TestScheduledWiki:
    def test_owners_schedule_edits_like_the_owner(self, monkeypatch, pg_conn):
        sid = _wiki(pg_conn)
        seen = _run(monkeypatch, pg_conn, sid, endpoint="schedule")
        assert _actions(seen) == ALL_ACTIONS
        assert seen["wiki_config"]["outside_caller"] is False

    @pytest.mark.parametrize("flag", ["external_caller", "public_link_caller"])
    def test_outside_callers_schedule_follows_the_owners_switch(self, monkeypatch, pg_conn, flag):
        sid = _wiki(pg_conn)
        seen = _run(monkeypatch, pg_conn, sid, endpoint="schedule", **{flag: True})
        assert _actions(seen) == {"wiki_view"}
        assert seen["wiki_config"]["outside_caller"] is True

        SourcesRepository(pg_conn).set_wiki_outside_edits(sid, OWNER, True)
        assert _actions(_run(monkeypatch, pg_conn, sid, endpoint="schedule", **{flag: True})) == ALL_ACTIONS


@pytest.mark.unit
class TestWikiOwnership:
    def test_team_editor_owner_writes_as_the_wikis_owner(self, monkeypatch, pg_conn):
        sid = _wiki(pg_conn)
        _share(pg_conn, sid, "bob", "editor")
        seen = _run(monkeypatch, pg_conn, sid, agent_owner="bob", endpoint="schedule")
        assert _actions(seen) == ALL_ACTIONS
        assert seen["wiki_config"]["source_owner_id"] == OWNER
        assert seen["wiki_config"]["user"] == "bob"

    def test_agent_owner_who_only_views_the_wiki_gets_no_tool(self, monkeypatch, pg_conn):
        sid = _wiki(pg_conn)
        _share(pg_conn, sid, "bob", "viewer")
        assert _actions(_run(monkeypatch, pg_conn, sid, agent_owner="bob", endpoint="schedule")) is None
        assert _actions(_run(monkeypatch, pg_conn, sid, agent_owner="bob", endpoint="webhook")) is None
