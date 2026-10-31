"""``used_by`` on GET /api/get_tools and GET /api/get_prompts, and prompt previews."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.agents.default_tools import default_tool_id
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

ALICE = "alice"
BOB = "bob"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, module):
    @contextmanager
    def _yield():
        yield conn

    with patch(f"{module}.db_session", _yield), patch(f"{module}.db_readonly", _yield):
        yield


def _get(app, conn, resource_cls, module, user, path, token=None):
    with _patch_db(conn, module), app.test_request_context(path):
        from flask import request

        request.decoded_token = token or {"sub": user}
        return resource_cls().get()


def _share(conn, resource_type, resource_id, owner, member):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, str(resource_id), owner, owner, access_level="viewer"
    )


def _agent(conn, owner, name, **kwargs):
    return AgentsRepository(conn).create(owner, name, "published", **kwargs)


class TestToolsUsedBy:
    def _tools(self, app, conn, user, token=None):
        from docsgpt.api.user.tools.routes import GetTools

        resp = _get(app, conn, GetTools, "docsgpt.api.user.tools.routes", user, "/api/get_tools", token)
        assert resp.status_code == 200
        return {t["id"]: t for t in resp.json["tools"]}

    def test_tool_named_by_its_legacy_object_id(self, app, pg_conn):
        oid = "65a1b2c3d4e5f6a7b8c9d0e1"
        tool = UserToolsRepository(pg_conn).create(
            ALICE, "read_webpage", config={}, display_name="Web", legacy_mongo_id=oid,
        )
        tid = str(tool["id"])
        agent = _agent(pg_conn, ALICE, "Migrated", tools=[oid])

        tools = self._tools(app, pg_conn, ALICE)
        assert tools[tid]["used_by"] == {
            "agents": [{"id": str(agent["id"]), "name": "Migrated", "agent_type": "classic", "can_edit": True, "status": "published"}],
            "others": 0,
        }

    def test_own_shared_and_default_tools(self, app, pg_conn):
        tool = UserToolsRepository(pg_conn).create(ALICE, "read_webpage", config={}, display_name="Web")
        tid = str(tool["id"])
        _share(pg_conn, "tool", tid, ALICE, BOB)
        agent = _agent(pg_conn, ALICE, "Researcher", tools=[tid, default_tool_id("memory")])
        _agent(pg_conn, BOB, "Bob's", tools=[tid])

        tools = self._tools(app, pg_conn, ALICE)
        assert tools[tid]["used_by"] == {
            "agents": [{"id": str(agent["id"]), "name": "Researcher", "agent_type": "classic", "can_edit": True, "status": "published"}],
            "others": 1,
        }
        memory = tools[default_tool_id("memory")]
        assert memory["default"] is True
        assert memory["used_by"]["agents"] == [
            {"id": str(agent["id"]), "name": "Researcher", "agent_type": "classic", "can_edit": True, "status": "published"}
        ]
        assert memory["used_by"]["others"] == 0
        # Every row carries the field, used or not.
        assert all("used_by" in t for t in tools.values())

        bob_view = self._tools(app, pg_conn, BOB)[tid]["used_by"]
        assert [a["name"] for a in bob_view["agents"]] == ["Bob's"]
        assert bob_view["others"] == 0


class TestPromptsUsedByAndPreview:
    def _prompts(self, app, conn, user, token=None):
        from docsgpt.api.user.prompts.routes import GetPrompts

        resp = _get(app, conn, GetPrompts, "docsgpt.api.user.prompts.routes", user, "/api/get_prompts", token)
        assert resp.status_code == 200
        return {p["id"]: p for p in resp.json}

    def test_used_by_on_presets_own_and_team_prompts(self, app, pg_conn):
        own = PromptsRepository(pg_conn).create(ALICE, "Mine", "x")
        team = PromptsRepository(pg_conn).create(BOB, "Bob's", "y")
        _share(pg_conn, "prompt", team["id"], BOB, ALICE)
        _agent(pg_conn, ALICE, "Uses mine", prompt_id=str(own["id"]))
        _agent(pg_conn, ALICE, "Default one")
        _agent(pg_conn, ALICE, "Uses Bob's", prompt_id=str(team["id"]))
        _agent(pg_conn, BOB, "Bob private", prompt_id=str(team["id"]))

        prompts = self._prompts(app, pg_conn, ALICE)
        assert [a["name"] for a in prompts["default"]["used_by"]["agents"]] == ["Default one"]
        assert prompts["creative"]["used_by"] == {"agents": [], "others": 0}
        assert prompts["strict"]["used_by"] == {"agents": [], "others": 0}
        assert [a["name"] for a in prompts[str(own["id"])]["used_by"]["agents"]] == ["Uses mine"]
        shared = prompts[str(team["id"])]["used_by"]
        assert [a["name"] for a in shared["agents"]] == ["Uses Bob's"]
        # Alice doesn't own Bob's prompt: his private agent isn't counted for her.
        assert shared["others"] == 0
        assert self._prompts(app, pg_conn, BOB)[str(team["id"])]["used_by"]["others"] == 1

    def test_preview_collapses_whitespace_and_caps_length(self, app, pg_conn):
        long = PromptsRepository(pg_conn).create(ALICE, "Long", "Hello\n\n  world\t" + "x" * 400)
        team = PromptsRepository(pg_conn).create(BOB, "Team", "  Shared   text ")
        _share(pg_conn, "prompt", team["id"], BOB, ALICE)

        prompts = self._prompts(app, pg_conn, ALICE)
        preview = prompts[str(long["id"])]["preview"]
        assert preview.startswith("Hello world x")
        assert len(preview) == 200
        assert prompts[str(team["id"])]["preview"] == "Shared text"
        for preset in ("default", "creative", "strict"):
            assert "preview" not in prompts[preset]


def _pat(scopes):
    from docsgpt.api.pat.tokens import expand_scopes

    return {
        "sub": ALICE, "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
        "scopes": sorted(expand_scopes(scopes)), "resource_filter": {},
    }


class TestTokenWithoutAgentsRead:
    """A token that may not read agents learns no agent names from ``used_by``, only the count."""

    def test_prompts(self, app, pg_conn):
        own = PromptsRepository(pg_conn).create(ALICE, "Mine", "x")
        _agent(pg_conn, ALICE, "Uses mine", prompt_id=str(own["id"]))
        _agent(pg_conn, ALICE, "Default one")
        helper = TestPromptsUsedByAndPreview()

        prompts = helper._prompts(app, pg_conn, ALICE, token=_pat(["prompts:read"]))
        assert prompts[str(own["id"])]["used_by"] == {"agents": [], "others": 1}
        # A preset has no owner: nothing is counted.
        assert prompts["default"]["used_by"] == {"agents": [], "others": 0}

        allowed = helper._prompts(app, pg_conn, ALICE, token=_pat(["prompts:read", "agents:read"]))
        assert [a["name"] for a in allowed[str(own["id"])]["used_by"]["agents"]] == ["Uses mine"]

    def test_tools(self, app, pg_conn):
        tid = str(UserToolsRepository(pg_conn).create(ALICE, "read_webpage", config={}, display_name="Web")["id"])
        _agent(pg_conn, ALICE, "Researcher", tools=[tid, default_tool_id("memory")])
        helper = TestToolsUsedBy()

        tools = helper._tools(app, pg_conn, ALICE, token=_pat(["tools:read"]))
        assert tools[tid]["used_by"] == {"agents": [], "others": 1}
        assert tools[default_tool_id("memory")]["used_by"] == {"agents": [], "others": 0}

        writer = helper._tools(app, pg_conn, ALICE, token=_pat(["tools:read", "agents:write"]))
        assert [a["name"] for a in writer[tid]["used_by"]["agents"]] == ["Researcher"]

    def test_sources(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson, PaginatedSources
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        sid = str(SourcesRepository(pg_conn).create("src", user_id=ALICE)["id"])
        _agent(pg_conn, ALICE, "Helper", source_id=sid)
        module = "docsgpt.api.user.sources.routes"
        token = _pat(["sources:read"])

        listing = _get(app, pg_conn, CombinedJson, module, ALICE, "/api/sources", token).json
        assert {r["id"]: r["used_by"] for r in listing}[sid] == {"agents": [], "others": 1}
        page = _get(app, pg_conn, PaginatedSources, module, ALICE, "/api/sources/paginated?usage=in_use", token).json
        assert [(r["id"], r["used_by"]) for r in page["paginated"]] == [(sid, {"agents": [], "others": 1})]
