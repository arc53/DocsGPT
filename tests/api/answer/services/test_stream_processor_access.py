"""Prompt and wiki-tool access in the answer pipeline (live grant checks)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository

OWNER = "alice"


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    monkeypatch.setattr("docsgpt.api.answer.services.stream_processor.db_readonly", _yield)
    return pg_conn


def _share(conn, rtype, rid, member, level="viewer"):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", OWNER)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(str(team["id"]), rtype, str(rid), OWNER, OWNER, access_level=level)
    return team


def _processor(data, caller):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    return StreamProcessor(data, {"sub": caller})


class TestAgentlessPrompt:
    def test_own_prompt_kept(self, use_conn):
        pid = str(PromptsRepository(use_conn).create(OWNER, "P", "C")["id"])
        proc = _processor({"question": "q", "prompt_id": pid}, OWNER)
        proc._configure_agent()
        assert proc.agent_config["prompt_id"] == pid

    def test_shared_prompt_kept_then_falls_back_when_revoked(self, use_conn):
        pid = str(PromptsRepository(use_conn).create(OWNER, "P", "C")["id"])
        team = _share(use_conn, "prompt", pid, "bob")
        proc = _processor({"question": "q", "prompt_id": pid}, "bob")
        proc._configure_agent()
        assert proc.agent_config["prompt_id"] == pid
        TeamResourceGrantsRepository(use_conn).revoke(str(team["id"]), "prompt", pid)
        proc = _processor({"question": "q", "prompt_id": pid}, "bob")
        proc._configure_agent()
        assert proc.agent_config["prompt_id"] == "default"

    def test_strangers_prompt_falls_back_to_default(self, use_conn):
        pid = str(PromptsRepository(use_conn).create(OWNER, "P", "secret")["id"])
        proc = _processor({"question": "q", "prompt_id": pid}, "eve")
        proc._configure_agent()
        assert proc.agent_config["prompt_id"] == "default"

    def test_presets_pass_through_without_db(self):
        proc = _processor({"question": "q", "prompt_id": "creative"}, "eve")
        proc._configure_agent()
        assert proc.agent_config["prompt_id"] == "creative"


class TestAgentPrompt:
    def _run(self, monkeypatch, agent_owner, prompt_id, caller="carol"):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        monkeypatch.setattr(
            StreamProcessor, "_get_data_from_api_key",
            lambda self, key: {"prompt_id": prompt_id, "user": agent_owner, "_id": None},
        )
        proc = _processor({"question": "q", "api_key": "k"}, caller)
        proc._configure_agent()
        return proc.agent_config["prompt_id"]

    def test_prompt_checked_against_agent_owner(self, use_conn, monkeypatch):
        pid = str(PromptsRepository(use_conn).create(OWNER, "P", "C")["id"])
        # Bob's agent uses Alice's prompt: allowed only while Bob has ``use``.
        assert self._run(monkeypatch, "bob", pid) == "default"
        _share(use_conn, "prompt", pid, "bob")
        assert self._run(monkeypatch, "bob", pid) == pid
        assert self._run(monkeypatch, OWNER, pid) == pid

    def test_deleted_prompt_falls_back(self, use_conn, monkeypatch):
        assert self._run(monkeypatch, OWNER, str(uuid.uuid4())) == "default"


class TestWikiConfigAccess:
    def _wiki(self, conn):
        return SourcesRepository(conn).create("W", user_id=OWNER, config={"kind": "wiki"})

    def _cfg(self, conn, caller, sid):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        proc = StreamProcessor.__new__(StreamProcessor)
        proc.all_sources = [{"id": sid}]
        proc.decoded_token = {"sub": caller}
        return proc._build_wiki_config()

    def test_owner_and_editor_get_tool_viewer_does_not(self, use_conn):
        sid = str(self._wiki(use_conn)["id"])
        assert self._cfg(use_conn, OWNER, sid)["source_owner_id"] == OWNER
        _share(use_conn, "source", sid, "ed", "editor")
        _share(use_conn, "source", sid, "vi", "viewer")
        cfg = self._cfg(use_conn, "ed", sid)
        assert cfg["source_owner_id"] == OWNER and cfg["user"] == "ed"
        assert self._cfg(use_conn, "vi", sid) is None
        assert self._cfg(use_conn, "eve", sid) is None


class TestWikiOutsideEdits:
    """API, widget and public-link runs edit a wiki only when its owner allows."""

    def _tools(self, conn, caller, sid, agent_config):
        from docsgpt.agents.tools.wiki import WIKI_TOOL_ID, add_wiki_tool
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        proc = StreamProcessor.__new__(StreamProcessor)
        proc.all_sources = [{"id": sid}]
        proc.decoded_token = {"sub": caller}
        proc.agent_config = agent_config
        cfg = proc._build_wiki_config()
        tools = {}
        add_wiki_tool(tools, cfg)
        return {a["name"] for a in tools[WIKI_TOOL_ID]["actions"]}

    @pytest.mark.parametrize("flag", ["external_api_caller", "public_link_caller"])
    def test_outside_caller_reads_until_the_owner_allows_edits(self, use_conn, flag):
        sid = str(SourcesRepository(use_conn).create("W", user_id=OWNER, config={"kind": "wiki"})["id"])
        assert self._tools(use_conn, OWNER, sid, {flag: True}) == {"wiki_view"}
        SourcesRepository(use_conn).set_wiki_outside_edits(sid, OWNER, True)
        assert "wiki_create" in self._tools(use_conn, OWNER, sid, {flag: True})

    def test_owner_and_team_editor_keep_every_action(self, use_conn):
        sid = str(SourcesRepository(use_conn).create("W", user_id=OWNER, config={"kind": "wiki"})["id"])
        _share(use_conn, "source", sid, "ed", "editor")
        assert "wiki_create" in self._tools(use_conn, OWNER, sid, {})
        assert "wiki_create" in self._tools(use_conn, "ed", sid, {})
