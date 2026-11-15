"""Chat in a team workspace.

A member chats with a team agent as themselves (they own and pay for the chat)
while the agent runs as its owner, the team's principal. A chat lives in one
workspace, set when it is created and never changed; it uses only that
workspace's items, and someone who leaves the team loses sight of it.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from flask import Flask, request

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    for module in (
        "docsgpt.api.answer.services.stream_processor",
        "docsgpt.api.answer.services.conversation_service",
    ):
        monkeypatch.setattr(f"{module}.db_readonly", _yield)
        monkeypatch.setattr(f"{module}.db_session", _yield)
    return pg_conn


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _agent(conn, owner, **kw) -> dict:
    return AgentsRepository(conn).create(owner, "Bot", "published", **kw)


def _processor(data, caller):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    return StreamProcessor(data, {"sub": caller})


@contextmanager
def _request(workspace=None, caller="vera"):
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    with Flask(__name__).test_request_context("/stream", method="POST", headers=headers):
        request.decoded_token = {"sub": caller}
        yield


def _conversation(conn, user, team_id=None, agent_id=None) -> str:
    return str(ConversationsRepository(conn).create(user, "Chat", team_id=team_id, agent_id=agent_id)["id"])


class TestMemberChatsWithTeamAgent:
    def test_a_viewer_chats_as_themselves_and_the_agent_runs_as_the_team(self, use_conn):
        tid, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        proc = _processor({"question": "q", "agent_id": aid}, "vera")
        proc._configure_agent()
        assert proc.decoded_token["sub"] == "vera"
        assert proc.is_shared_usage is True
        assert proc.public_link_usage is False
        assert proc.agent_config["user_id"] == principal
        assert proc.workspace_team_id == tid

    def test_a_stranger_with_only_the_id_is_refused(self, use_conn):
        _, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        with pytest.raises(Exception, match="Unauthorized"):
            _processor({"question": "q", "agent_id": aid}, "eve")._configure_agent()

    def test_an_ex_member_is_refused(self, use_conn):
        tid, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        TeamMembersRepository(use_conn).remove_member(tid, "vera")
        with pytest.raises(Exception, match="Unauthorized"):
            _processor({"question": "q", "agent_id": aid}, "vera")._configure_agent()

    def test_a_link_user_chats_in_their_own_personal_workspace(self, use_conn):
        _, principal = _team(use_conn)
        agent = _agent(use_conn, principal, shared=True, shared_token="tok-1", access_payer_id="alice")
        proc = _processor({"question": "q", "agent_id": str(agent["id"]), "shared_token": "tok-1"}, "eve")
        proc._configure_agent()
        assert proc.public_link_usage is True
        assert proc.workspace_team_id is None

    def test_a_personal_agent_shared_by_grant_still_runs(self, use_conn):
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository

        tid, _ = _team(use_conn)
        aid = str(_agent(use_conn, "alice")["id"])
        TeamResourceGrantsRepository(use_conn).grant(tid, "agent", aid, "alice", "alice", access_level="viewer")
        proc = _processor({"question": "q", "agent_id": aid}, "vera")
        proc._configure_agent()
        assert proc.is_shared_usage is True and proc.public_link_usage is False
        assert proc.workspace_team_id is None


class TestWhereANewChatLives:
    def test_an_agentless_chat_takes_the_named_team(self, use_conn):
        tid, _ = _team(use_conn)
        with _request(tid):
            proc = _processor({"question": "q"}, "vera")
            proc._configure_agent()
        assert proc.workspace_team_id == tid

    def test_no_header_is_personal(self, use_conn):
        _team(use_conn)
        with _request():
            proc = _processor({"question": "q"}, "vera")
            proc._configure_agent()
        assert proc.workspace_team_id is None

    def test_a_team_the_caller_is_not_in_is_not_found(self, use_conn):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        tid, _ = _team(use_conn)
        with _request(tid, caller="eve"), pytest.raises(ChatWorkspaceError) as err:
            _processor({"question": "q"}, "eve")._configure_agent()
        assert err.value.status == 404 and err.value.code == "workspace_not_found"

    def test_the_team_agent_decides_without_a_header(self, use_conn):
        tid, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        with _request():
            proc = _processor({"question": "q", "agent_id": aid}, "vera")
            proc._configure_agent()
        assert proc.workspace_team_id == tid

    @pytest.mark.parametrize("named", ["personal", "other-team"])
    def test_a_team_agent_in_another_named_workspace_is_a_mismatch(self, use_conn, named):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        _, principal = _team(use_conn)
        other, _ = _team(use_conn, owner="olga", members=(("vera", "team_viewer"),))
        aid = str(_agent(use_conn, principal)["id"])
        with _request(other if named == "other-team" else "personal"), pytest.raises(ChatWorkspaceError) as err:
            _processor({"question": "q", "agent_id": aid}, "vera")._configure_agent()
        assert err.value.status == 409 and err.value.code == "workspace_mismatch"

    def test_a_personal_agent_in_a_team_workspace_is_a_mismatch(self, use_conn):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        tid, _ = _team(use_conn)
        aid = str(_agent(use_conn, "vera")["id"])
        with _request(tid), pytest.raises(ChatWorkspaceError) as err:
            _processor({"question": "q", "agent_id": aid}, "vera")._configure_agent()
        assert err.value.code == "workspace_mismatch"

    def test_an_existing_team_chat_continued_with_a_personal_agent_is_a_mismatch(self, use_conn):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        tid, _ = _team(use_conn)
        cid = _conversation(use_conn, "vera", team_id=tid)
        aid = str(_agent(use_conn, "vera")["id"])
        with pytest.raises(ChatWorkspaceError) as err:
            _processor({"question": "q", "agent_id": aid, "conversation_id": cid}, "vera")._configure_agent()
        assert err.value.code == "workspace_mismatch"

    def test_an_existing_chat_keeps_its_workspace_whatever_the_header(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _conversation(use_conn, "vera", team_id=tid)
        with _request("personal"):
            proc = _processor({"question": "q", "conversation_id": cid}, "vera")
            proc._configure_agent()
        assert proc.workspace_team_id == tid

    def test_an_api_key_run_takes_the_agents_workspace_whatever_the_header(self, use_conn):
        tid, principal = _team(use_conn)
        _agent(use_conn, principal, key="team-key-1", access_payer_id="alice")
        with _request("personal", caller="eve"):
            proc = _processor({"question": "q", "api_key": "team-key-1"}, "eve")
            proc._configure_agent()
        assert proc.decoded_token["sub"] == principal
        assert proc.workspace_team_id == tid


class TestChatItemsComeFromItsWorkspace:
    def test_a_personal_source_in_a_team_chat_is_dropped(self, use_conn):
        tid, principal = _team(use_conn)
        mine = str(SourcesRepository(use_conn).create("Mine", user_id="vera")["id"])
        theirs = str(SourcesRepository(use_conn).create("Team", user_id=principal)["id"])
        proc = _processor({"question": "q"}, "vera")
        proc.workspace_team_id = tid
        assert [e["id"] for e in proc._load_request_sources([mine, theirs])] == [theirs]

    def test_a_team_source_in_a_personal_chat_is_dropped(self, use_conn):
        _, principal = _team(use_conn)
        mine = str(SourcesRepository(use_conn).create("Mine", user_id="vera")["id"])
        theirs = str(SourcesRepository(use_conn).create("Team", user_id=principal)["id"])
        proc = _processor({"question": "q"}, "vera")
        assert [e["id"] for e in proc._load_request_sources([mine, theirs])] == [mine]

    def test_a_personal_folder_in_a_team_chat_adds_nothing(self, use_conn):
        from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository

        tid, _ = _team(use_conn)
        mine = str(SourcesRepository(use_conn).create("Mine", user_id="vera")["id"])
        folder = FoldersRepository(use_conn).create("vera", "Docs", resource_type="source")
        FolderItemsRepository(use_conn).file("vera", "source", mine, str(folder["id"]))
        proc = _processor({"question": "q"}, "vera")
        assert [e["id"] for e in proc._load_request_folder_sources([str(folder["id"])])] == [mine]
        proc.workspace_team_id = tid
        assert proc._load_request_folder_sources([str(folder["id"])]) == []

    def test_prompts_follow_the_chat_workspace(self, use_conn):
        tid, principal = _team(use_conn)
        mine = str(PromptsRepository(use_conn).create("vera", "Mine", "Be mine.")["id"])
        theirs = str(PromptsRepository(use_conn).create(principal, "Team", "Be ours.")["id"])
        with _request(tid):
            for pid, expected in ((mine, "default"), (theirs, theirs)):
                proc = _processor({"question": "q", "prompt_id": pid}, "vera")
                proc._configure_agent()
                assert proc.agent_config["prompt_id"] == expected
        with _request():
            proc = _processor({"question": "q", "prompt_id": theirs}, "vera")
            proc._configure_agent()
            assert proc.agent_config["prompt_id"] == "default"

    def test_in_chat_tools_get_the_chat_workspace(self, use_conn):
        tid, _ = _team(use_conn)
        proc = _processor({"question": "q"}, "vera")
        proc.workspace_team_id = tid
        assert proc._run_tool_executor().workspace_team_id == tid
        proc.workspace_team_id = None
        assert proc._run_tool_executor().workspace_team_id is None


class TestConversationTeamId:
    def _service(self):
        from docsgpt.api.answer.services.conversation_service import ConversationService

        return ConversationService()

    def _team_of(self, conn, cid):
        return ConversationsRepository(conn).team_id_of(cid)

    def test_a_chat_started_in_a_team_has_that_team(self, use_conn):
        tid, _ = _team(use_conn)
        out = self._service().save_user_question(None, "q", {"sub": "vera"}, team_id=tid)
        assert self._team_of(use_conn, out["conversation_id"]) == tid

    def test_a_chat_without_a_team_is_personal(self, use_conn):
        _team(use_conn)
        out = self._service().save_user_question(None, "q", {"sub": "vera"})
        assert self._team_of(use_conn, out["conversation_id"]) is None

    def test_a_members_chat_with_a_team_agent_takes_its_team(self, use_conn):
        tid, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        out = self._service().save_user_question(None, "q", {"sub": "vera"}, agent_id=aid, is_shared_usage=True)
        assert self._team_of(use_conn, out["conversation_id"]) == tid

    def test_an_api_key_chat_on_a_team_agent_has_its_team(self, use_conn):
        tid, principal = _team(use_conn)
        _agent(use_conn, principal, key="team-key-2", access_payer_id="alice")
        out = self._service().save_user_question(None, "q", {"sub": principal}, api_key="team-key-2")
        row = ConversationsRepository(use_conn).get_any(out["conversation_id"], principal)
        assert row["user_id"] == principal and str(row["team_id"]) == tid

    def test_an_outsiders_link_chat_on_a_team_agent_stays_personal(self, use_conn):
        _, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        out = self._service().save_user_question(None, "q", {"sub": "eve"}, agent_id=aid, is_shared_usage=True)
        assert self._team_of(use_conn, out["conversation_id"]) is None

    def test_the_fallback_save_takes_the_team_too(self, use_conn):
        tid, _ = _team(use_conn)
        cid = self._service().save_conversation(
            None, "q", "a", "", [], [], None, "m", {"sub": "vera"}, team_id=tid
        )
        assert self._team_of(use_conn, cid) == tid

    def test_appending_never_moves_a_chat(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _conversation(use_conn, "vera", team_id=tid)
        self._service().save_user_question(cid, "q2", {"sub": "vera"}, team_id=None)
        assert self._team_of(use_conn, cid) == tid


class TestExMemberLosesTheChat:
    def test_reading_and_continuing_need_membership(self, use_conn):
        from docsgpt.api.answer.services.conversation_service import ConversationService

        tid, _ = _team(use_conn)
        cid = _conversation(use_conn, "vera", team_id=tid)
        assert ConversationService().get_conversation(cid, "vera") is not None
        TeamMembersRepository(use_conn).remove_member(tid, "vera")
        assert ConversationService().get_conversation(cid, "vera") is None
        proc = _processor({"question": "q", "conversation_id": cid}, "vera")
        with pytest.raises(ValueError, match="not found"):
            proc._load_conversation_history()
        # Re-added, the chat is theirs again.
        TeamMembersRepository(use_conn).add_member(tid, "vera")
        assert ConversationService().get_conversation(cid, "vera") is not None

    def test_a_resume_needs_membership(self, use_conn):
        tid, _ = _team(use_conn)
        cid = _conversation(use_conn, "vera", team_id=tid)
        proc = _processor({"question": ""}, "vera")
        assert proc._resume_workspace(cid) == tid
        TeamMembersRepository(use_conn).remove_member(tid, "vera")
        with pytest.raises(ValueError):
            proc._resume_workspace(cid)

    def test_the_teams_own_principal_reads_its_key_chats(self, use_conn):
        tid, principal = _team(use_conn)
        cid = _conversation(use_conn, principal, team_id=tid)
        assert ConversationsRepository(use_conn).get_any(cid, principal) is not None


class TestAutoResume:
    def _allowed(self, conn, cid, user, monkeypatch):
        from docsgpt.background.context import auto_resume_allowed
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "AUTO_RESUME_ENABLED", True, raising=False)
        return auto_resume_allowed(conn, cid, user)

    def test_a_members_chat_on_a_team_agent_resumes_while_they_stay(self, use_conn, monkeypatch):
        tid, principal = _team(use_conn)
        aid = str(_agent(use_conn, principal)["id"])
        cid = str(ConversationsRepository(use_conn).create(
            "vera", "Chat", agent_id=aid, is_shared_usage=True, team_id=tid
        )["id"])
        assert self._allowed(use_conn, cid, "vera", monkeypatch) is True
        TeamMembersRepository(use_conn).remove_member(tid, "vera")
        assert self._allowed(use_conn, cid, "vera", monkeypatch) is False

    def test_an_agentless_team_chat_is_poll_only(self, use_conn, monkeypatch):
        tid, _ = _team(use_conn)
        cid = _conversation(use_conn, "vera", team_id=tid)
        assert self._allowed(use_conn, cid, "vera", monkeypatch) is False

    def test_someone_elses_personal_agent_still_does_not(self, use_conn, monkeypatch):
        aid = str(_agent(use_conn, "alice")["id"])
        cid = str(ConversationsRepository(use_conn).create("vera", "Chat", agent_id=aid, is_shared_usage=True)["id"])
        assert self._allowed(use_conn, cid, "vera", monkeypatch) is False


class TestRoutesAnswerTheWorkspaceRefusal:
    @pytest.mark.parametrize("route", ["/api/answer", "/stream"])
    def test_mismatch_is_409(self, monkeypatch, route):
        from docsgpt.api.answer.routes.answer import AnswerResource
        from docsgpt.api.answer.routes.stream import StreamResource
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError, StreamProcessor

        def _refuse(self, question):
            raise ChatWorkspaceError(409, "workspace_mismatch", "nope")

        monkeypatch.setattr(StreamProcessor, "build_agent", _refuse)
        resource = AnswerResource if route == "/api/answer" else StreamResource
        with Flask(__name__).test_request_context(route, method="POST", json={"question": "hi"}):
            request.decoded_token = {"sub": "vera"}
            response = resource().post()
        assert response.status_code == 409
        assert "workspace_mismatch" in response.get_data(as_text=True)
