"""A member of a receiving team chats with a team agent shared into it.

Ops owns an agent (with Ops' source, tool and prompt) and shares it with Dev. Rita, a Dev viewer, chats with it
in Dev's workspace: the chat and its usage are Dev's, she pays, and the agent runs as Ops with Ops' items (its
tool on Ops' stored account). From Personal the chat is a workspace mismatch. Revoking the share, locking Ops or
Rita leaving Dev refuses the chat; unlocking lets her old chat go on, with nothing rewritten.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from flask import Flask, request
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from tests.workspaces.move_support import prompt, source, team, tool


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    for module in (
        "docsgpt.api.answer.services.stream_processor",
        "docsgpt.api.answer.services.conversation_service",
        "docsgpt.agents.tool_executor",
    ):
        monkeypatch.setattr(f"{module}.db_readonly", _yield)
        monkeypatch.setattr(f"{module}.db_session", _yield, raising=False)
    return pg_conn


@pytest.fixture
def world(use_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer) owns an agent using its own source, tool and
    prompt; Dev (dora owner, dan editor, rita viewer) and QA (quinn owner, rita viewer) may receive it."""
    conn = use_conn
    ops, ops_p = team(conn)
    dev, _ = team(conn, owner="dora", name="Dev", members=(("dan", "team_editor"), ("rita", "team_viewer")))
    qa, _ = team(conn, owner="quinn", name="QA", members=(("rita", "team_viewer"),))
    src, tl, pr = source(conn, ops_p), tool(conn, ops_p), prompt(conn, ops_p)
    agent = AgentsRepository(conn).create(
        ops_p, "Ops helper", "published", key="ops-agent-key", source_id=src, tools=[tl], prompt_id=pr,
        created_by="alice",
    )
    return {"ops": ops, "ops_p": ops_p, "dev": dev, "qa": qa, "agent": str(agent["id"]),
            "source": src, "tool": tl, "prompt": pr}


def _share(conn, w, into="dev"):
    TeamItemSharesRepository(conn).share(w["ops"], w[into], "agent", w["agent"], "adam")


def _policy(conn, team_id, policy):
    conn.execute(text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id})


def _processor(data, caller):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    return StreamProcessor(data, {"sub": caller})


@contextmanager
def _request(workspace=None, caller="rita"):
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    with Flask(__name__).test_request_context("/stream", method="POST", headers=headers):
        request.decoded_token = {"sub": caller}
        yield


def _chat(w, caller="rita", **extra):
    proc = _processor({"question": "q", "agent_id": w["agent"], **extra}, caller)
    proc._configure_agent()
    return proc


class TestTheReceiversChat:
    def test_it_lives_in_the_receiving_team_and_runs_as_the_owning_team(self, use_conn, world):
        _share(use_conn, world)
        proc = _chat(world)
        assert proc.workspace_team_id == world["dev"]
        assert proc.decoded_token["sub"] == "rita"
        assert proc.is_shared_usage is True and proc.public_link_usage is False
        assert proc.agent_config["user_id"] == world["ops_p"]

    def test_the_chatter_pays_and_the_usage_is_the_receiving_teams(self, use_conn, world):
        from docsgpt.api.answer.routes.base import _run_billing

        _share(use_conn, world)
        proc = _chat(world)
        payer, kind, team_id = _run_billing(
            outside=False, decoded_token=proc.decoded_token, team_id=proc.workspace_team_id,
            agent_id=proc.agent_id, user_api_key=proc.agent_config.get("user_api_key"),
        )
        assert (payer, kind, team_id) == ("rita", "chat", world["dev"])

    def test_the_conversation_is_saved_in_the_receiving_team(self, use_conn, world):
        _share(use_conn, world)
        proc = _chat(world)
        cid = ConversationsRepository(use_conn).create(
            "rita", "Chat", team_id=proc.workspace_team_id, agent_id=world["agent"]
        )["id"]
        assert ConversationsRepository(use_conn).team_id_of(str(cid)) == world["dev"]

    def test_it_reads_the_owning_teams_source_and_prompt_and_runs_its_tool_on_its_account(self, use_conn, world):
        _share(use_conn, world)
        proc = _chat(world)
        assert [s["id"] for s in proc._agent_data["sources"]] == [world["source"]]
        assert str(proc.agent_config["prompt_id"]) == world["prompt"]
        tools = proc._run_tool_executor().get_tools()
        assert world["tool"] in tools
        # The row is Ops' own: its stored credentials decrypt as Ops.
        assert tools[world["tool"]]["user_id"] == world["ops_p"]

    def test_a_receiver_does_not_mark_the_agent_used(self, use_conn, world):
        _share(use_conn, world)
        _chat(world)
        assert AgentsRepository(use_conn).get(world["agent"], world["ops_p"])["last_used_at"] is None


class TestWhichWorkspace:
    def test_from_personal_it_is_a_mismatch(self, use_conn, world):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        _share(use_conn, world)
        with _request("personal"), pytest.raises(ChatWorkspaceError) as err:
            _chat(world)
        assert err.value.status == 409 and err.value.code == "workspace_mismatch"

    def test_the_owning_team_named_is_a_mismatch_for_a_receiver(self, use_conn, world):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        _share(use_conn, world)
        with _request(world["ops"]), pytest.raises(ChatWorkspaceError) as err:
            _chat(world)
        assert err.value.code == "workspace_not_found"

    def test_in_two_receiving_teams_the_named_one_decides_else_the_oldest_share(self, use_conn, world):
        _share(use_conn, world)
        _share(use_conn, world, into="qa")
        # One transaction stamps both shares alike: make QA's the newer one.
        use_conn.execute(
            text("UPDATE team_item_shares SET created_at = created_at + interval '1 minute' "
                 "WHERE team_id = CAST(:t AS uuid)"),
            {"t": world["qa"]},
        )
        with _request(world["qa"]):
            assert _chat(world).workspace_team_id == world["qa"]
        with _request(world["dev"]):
            assert _chat(world).workspace_team_id == world["dev"]
        with _request():
            assert _chat(world).workspace_team_id == world["dev"]

    def test_in_two_receiving_teams_an_existing_chat_keeps_its_team(self, use_conn, world):
        _share(use_conn, world)
        _share(use_conn, world, into="qa")
        cid = str(ConversationsRepository(use_conn).create(
            "rita", "Chat", team_id=world["qa"], agent_id=world["agent"]
        )["id"])
        with _request():
            assert _chat(world, conversation_id=cid).workspace_team_id == world["qa"]

    def test_an_owning_team_member_in_the_receiving_team_too_chats_in_the_owning_team(self, use_conn, world):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository

        TeamMembersRepository(use_conn).add_member(world["dev"], "vera", role="team_viewer")
        _share(use_conn, world)
        assert _chat(world, caller="vera").workspace_team_id == world["ops"]


class TestWhenItStops:
    @pytest.mark.parametrize("how", ["revoke", "lock", "leave"])
    def test_revoke_lock_or_leaving_refuses_the_chat(self, use_conn, world, how):
        _share(use_conn, world)
        assert _chat(world).workspace_team_id == world["dev"]
        if how == "revoke":
            TeamItemSharesRepository(use_conn).revoke(world["dev"], "agent", world["agent"])
        elif how == "lock":
            _policy(use_conn, world["ops"], "locked")
        else:
            use_conn.execute(
                text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = 'rita'"),
                {"t": world["dev"]},
            )
        with pytest.raises(Exception, match="Unauthorized"):
            _chat(world)

    def test_unlocking_lets_the_old_chat_go_on(self, use_conn, world):
        _share(use_conn, world)
        cid = str(ConversationsRepository(use_conn).create(
            "rita", "Chat", team_id=world["dev"], agent_id=world["agent"]
        )["id"])
        _policy(use_conn, world["ops"], "locked")
        with pytest.raises(Exception, match="Unauthorized"):
            _chat(world, conversation_id=cid)
        _policy(use_conn, world["ops"], "admins")
        assert _chat(world, conversation_id=cid).workspace_team_id == world["dev"]
