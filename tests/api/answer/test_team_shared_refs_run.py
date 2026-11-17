"""Another team's source, tool and prompt, used through a share with the team that runs them.

Ops shares a source, a tool and a prompt with Dev. Dev's agents run them (the tool on Ops' stored account), and
a chat in Dev's workspace may pick them. Revoking the share stops them as ``team_share_ended``; locking Ops
pauses them as ``team_locked``; sharing again or unlocking brings them back as saved. A person's own agent using
one stops the same way when they leave the receiving team.

The run-time guard: when someone other than a holder's owner runs it (a person chatting, a schedule's setter, an
outside caller), a team's item that reader can't use themselves is left out of the run. That covers grants made
before team items were confined (inserted here by SQL). The owner and the owning team's members keep them; a
team's own agent keeps its own team's items for whoever it is shared with.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from docsgpt.api.user.resource_access import (
    REASON_TEAM_LOCKED,
    REASON_TEAM_SHARE_ENDED,
    authorized_holder_sources,
    current_run_reader,
    ref_access,
    resolve_holder_tools,
    run_reader,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from tests.workspaces.move_support import prompt, source, team, tool

KINDS = ("source", "tool", "prompt")


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
    """Ops (alice, adam, eddie, vera) owns a source, a tool and a prompt; Dev (dora, dan, rita) may receive them;
    Other (olga owner, oscar, vera) is a team eddie once shared his own agent with."""
    conn = use_conn
    ops, ops_p = team(conn)
    dev, dev_p = team(conn, owner="dora", name="Dev", members=(("dan", "team_editor"), ("rita", "team_viewer")))
    other, _ = team(conn, owner="olga", name="Other", members=(("oscar", "team_viewer"), ("vera", "team_viewer")))
    items = {"source": source(conn, ops_p), "tool": tool(conn, ops_p), "prompt": prompt(conn, ops_p)}
    return {"ops": ops, "ops_p": ops_p, "dev": dev, "dev_p": dev_p, "other": other, "items": items}


def _share(conn, w, kind, into="dev"):
    TeamItemSharesRepository(conn).share(w["ops"], w[into], kind, w["items"][kind], "adam")


def _revoke(conn, w, kind, into="dev"):
    TeamItemSharesRepository(conn).revoke(w[into], kind, w["items"][kind])


def _policy(conn, team_id, policy):
    conn.execute(text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id})


def _leave(conn, team_id, user):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user}
    )


def _holder(conn, owner, w, **extra) -> dict:
    """An agent of ``owner`` using Ops' source, tool and prompt."""
    items = w["items"]
    return AgentsRepository(conn).create(
        owner, "Uses Ops", "published", source_id=items["source"], tools=[items["tool"]],
        prompt_id=items["prompt"], created_by="dora" if owner.startswith("__team__") else owner, **extra,
    )


def _runs(conn, holder, kind, rid) -> bool:
    """Whether the holder's run gets ``rid`` through the resolver a run of that kind uses."""
    if kind == "source":
        return authorized_holder_sources(conn, "agent", holder, [rid]) == [rid]
    if kind == "tool":
        return rid in resolve_holder_tools(conn, "agent", holder, [rid])
    return ref_access(conn, "agent", holder, kind, rid).principal is not None


class TestAReceivingAgentRunsSharedItems:
    @pytest.mark.parametrize("kind", KINDS)
    def test_it_runs_them_as_the_receiving_team(self, use_conn, world, kind):
        for k in KINDS:
            _share(use_conn, world, k)
        holder = _holder(use_conn, world["dev_p"], world)
        rid = world["items"][kind]
        assert ref_access(use_conn, "agent", holder, kind, rid).principal == world["dev_p"]
        assert _runs(use_conn, holder, kind, rid)

    def test_the_tool_runs_on_the_owning_teams_account(self, use_conn, world):
        _share(use_conn, world, "tool")
        holder = _holder(use_conn, world["dev_p"], world)
        rid = world["items"]["tool"]
        assert resolve_holder_tools(use_conn, "agent", holder, [rid])[rid]["user_id"] == world["ops_p"]

    @pytest.mark.parametrize("kind", KINDS)
    def test_revoking_stops_them_and_sharing_again_brings_them_back(self, use_conn, world, kind):
        _share(use_conn, world, kind)
        holder = _holder(use_conn, world["dev_p"], world)
        rid = world["items"][kind]
        _revoke(use_conn, world, kind)
        stopped = ref_access(use_conn, "agent", holder, kind, rid)
        assert (stopped.principal, stopped.reason) == (None, REASON_TEAM_SHARE_ENDED)
        assert not _runs(use_conn, holder, kind, rid)
        _share(use_conn, world, kind)
        assert _runs(use_conn, holder, kind, rid)

    @pytest.mark.parametrize("kind", KINDS)
    def test_locking_pauses_them_and_unlocking_brings_them_back(self, use_conn, world, kind):
        _share(use_conn, world, kind)
        holder = _holder(use_conn, world["dev_p"], world)
        rid = world["items"][kind]
        _policy(use_conn, world["ops"], "locked")
        stopped = ref_access(use_conn, "agent", holder, kind, rid)
        assert (stopped.principal, stopped.reason) == (None, REASON_TEAM_LOCKED)
        assert not _runs(use_conn, holder, kind, rid)
        _policy(use_conn, world["ops"], "admins")
        assert _runs(use_conn, holder, kind, rid)

    def test_a_receivers_own_agent_stops_when_they_leave_the_receiving_team(self, use_conn, world):
        _share(use_conn, world, "source")
        holder = _holder(use_conn, "rita", world)
        rid = world["items"]["source"]
        assert ref_access(use_conn, "agent", holder, "source", rid).principal == "rita"
        _leave(use_conn, world["dev"], "rita")
        stopped = ref_access(use_conn, "agent", holder, "source", rid)
        assert (stopped.principal, stopped.reason) == (None, REASON_TEAM_SHARE_ENDED)

    def test_a_personal_items_lost_access_keeps_its_reason(self, use_conn, world):
        from docsgpt.api.user.resource_access import REASON_OWNER_LOST_ACCESS

        own = source(use_conn, "olga", name="Olga's")
        holder = AgentsRepository(use_conn).create("rita", "Other", "published", source_id=own)
        assert ref_access(use_conn, "agent", holder, "source", own).reason == REASON_OWNER_LOST_ACCESS


class TestATeamChatPicksSharedItems:
    def _processor(self, w, caller="rita", workspace="dev"):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        proc = StreamProcessor({"question": "q"}, {"sub": caller})
        proc.workspace_team_id = w[workspace] if workspace else None
        return proc

    def test_a_dev_chat_picks_a_prompt_shared_into_dev(self, use_conn, world):
        pid = world["items"]["prompt"]
        assert self._processor(world)._workspace_prompt_id(pid) == "default"
        _share(use_conn, world, "prompt")
        assert self._processor(world)._workspace_prompt_id(pid) == pid
        # Never in a Personal chat, and not while Ops is locked.
        assert self._processor(world, workspace=None)._workspace_prompt_id(pid) == "default"
        _policy(use_conn, world["ops"], "locked")
        assert self._processor(world)._workspace_prompt_id(pid) == "default"

    def test_a_dev_chat_searches_a_source_shared_into_dev(self, use_conn, world):
        sid = world["items"]["source"]
        _share(use_conn, world, "source")
        assert [e["id"] for e in self._processor(world)._load_request_sources([sid])] == [sid]
        assert self._processor(world, workspace=None)._load_request_sources([sid]) == []
        _revoke(use_conn, world, "source")
        assert self._processor(world)._load_request_sources([sid]) == []

    def test_a_dev_chat_offers_a_tool_shared_into_dev_that_the_member_switched_on(self, use_conn, world):
        from docsgpt.agents.tool_executor import ToolExecutor
        from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository

        tid = world["items"]["tool"]
        _share(use_conn, world, "tool")
        UserToolPreferencesRepository(use_conn).set_in_chat("rita", tid, True)

        def _tools(workspace):
            executor = ToolExecutor(user="rita", decoded_token={"sub": "rita"})
            executor.workspace_team_id = workspace
            return executor.get_tools()

        assert tid in {str(t.get("id")) for t in _tools(world["dev"]).values()}
        assert tid not in {str(t.get("id")) for t in _tools(None).values()}
        _revoke(use_conn, world, "tool")
        assert tid not in {str(t.get("id")) for t in _tools(world["dev"]).values()}


def _pre_t16_grant(conn, team_id, agent_id, owner):
    """A team grant on a personal agent, written straight to the table as before team items were confined."""
    conn.execute(
        text(
            "INSERT INTO team_resource_grants (team_id, resource_type, resource_id, owner_id, access_level, "
            "granted_by) VALUES (CAST(:t AS uuid), 'agent', CAST(:a AS uuid), :o, 'viewer', :o)"
        ),
        {"t": team_id, "a": agent_id, "o": owner},
    )


class TestTheRunGuard:
    @pytest.fixture
    def eddies(self, use_conn, world):
        """Eddie's own agent using Ops' items, shared (before confinement) with Other."""
        holder = _holder(use_conn, "eddie", world)
        _pre_t16_grant(use_conn, world["other"], str(holder["id"]), "eddie")
        return holder

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_grantee_outside_the_owning_team_runs_without_its_items(self, use_conn, world, eddies, kind):
        rid = world["items"][kind]
        with run_reader("oscar"):
            stopped = ref_access(use_conn, "agent", eddies, kind, rid)
            assert stopped.principal is None and stopped.reason == REASON_TEAM_SHARE_ENDED
            assert not _runs(use_conn, eddies, kind, rid)

    @pytest.mark.parametrize("reader", ["eddie", "vera", "alice"])
    @pytest.mark.parametrize("kind", KINDS)
    def test_the_owner_and_the_owning_teams_members_keep_them(self, use_conn, world, eddies, kind, reader):
        rid = world["items"][kind]
        with run_reader(reader):
            assert _runs(use_conn, eddies, kind, rid)

    def test_an_outside_caller_nobody_signed_in_as_runs_without_them(self, use_conn, world, eddies):
        with run_reader(None):
            assert not _runs(use_conn, eddies, "source", world["items"]["source"])

    def test_a_reader_in_a_team_that_receives_the_item_keeps_it(self, use_conn, world, eddies):
        _share(use_conn, world, "source", into="other")
        with run_reader("oscar"):
            assert _runs(use_conn, eddies, "source", world["items"]["source"])

    def test_a_locked_owning_team_is_the_reason_for_a_receiving_reader(self, use_conn, world, eddies):
        _share(use_conn, world, "source", into="other")
        _policy(use_conn, world["ops"], "locked")
        with run_reader("oscar"):
            assert ref_access(use_conn, "agent", eddies, "source", world["items"]["source"]).reason == (
                REASON_TEAM_LOCKED
            )

    def test_nothing_is_guarded_outside_a_run(self, use_conn, world, eddies):
        assert current_run_reader() is None
        assert _runs(use_conn, eddies, "source", world["items"]["source"])

    def test_folder_fed_sources_are_guarded_too(self, use_conn, world):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        folder = str(FoldersRepository(use_conn).create("eddie", "Ops docs", resource_type="source")["id"])
        FolderItemsRepository(use_conn).file("eddie", "source", world["items"]["source"], folder)
        holder = AgentsRepository(use_conn).create("eddie", "Folders", "published", knowledge_folder_ids=[folder])
        _, rows = authorized_agent_sources(use_conn, holder)
        assert [str(r["id"]) for r in rows] == [world["items"]["source"]]
        with run_reader("oscar"):
            assert authorized_agent_sources(use_conn, holder)[1] == []
        with run_reader("vera"):
            assert len(authorized_agent_sources(use_conn, holder)[1]) == 1

    def test_a_team_agent_keeps_its_own_teams_items_for_whoever_it_is_shared_with(self, use_conn, world):
        holder = _holder(use_conn, world["ops_p"], world)
        with run_reader("rita"):
            for kind in KINDS:
                assert _runs(use_conn, holder, kind, world["items"][kind])

    def test_a_team_agent_drops_another_teams_item_for_a_reader_it_doesnt_reach(self, use_conn, world):
        qa, qa_p = team(use_conn, owner="quinn", name="QA", members=())
        qa_source = source(use_conn, qa_p, name="QA docs")
        TeamItemSharesRepository(use_conn).share(qa, world["ops"], "source", qa_source, "quinn")
        holder = AgentsRepository(use_conn).create(world["ops_p"], "Uses QA", "published", source_id=qa_source)
        with run_reader("adam"):
            assert _runs(use_conn, holder, "source", qa_source)
        with run_reader("rita"):
            assert not _runs(use_conn, holder, "source", qa_source)


class TestWhoReads:
    def test_a_chat_reads_as_the_caller_through_setup_and_every_answer_step(self, use_conn, world, monkeypatch):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        seen: list = []
        proc = StreamProcessor({"question": "q"}, {"sub": "oscar"})

        class _Agent:
            def gen(self, query):
                seen.append(("step", current_run_reader()))
                yield "a"
                seen.append(("step", current_run_reader()))
                yield "b"

        monkeypatch.setattr(proc, "initialize", lambda: seen.append(("setup", current_run_reader())))
        monkeypatch.setattr(proc, "_exposure_partition", lambda: ([], []))
        monkeypatch.setattr(proc, "pre_fetch_tools", lambda: seen.append(("tools", current_run_reader())))
        monkeypatch.setattr(proc, "create_agent", lambda **_kw: proc._answers_read_by_caller(_Agent()))
        proc.agent_config["agent_type"] = "classic"
        agent = proc.build_agent("q")
        assert current_run_reader() is None
        assert list(agent.gen(query="q")) == ["a", "b"]
        assert current_run_reader() is None
        assert seen == [("setup", "oscar"), ("tools", "oscar"), ("step", "oscar"), ("step", "oscar")]

    def test_an_outside_key_caller_reads_as_nobody(self, use_conn, world, monkeypatch):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        seen: list = []
        proc = StreamProcessor({"question": "q", "api_key": "k"}, None)
        monkeypatch.setattr(proc, "initialize", lambda: seen.append(current_run_reader()))
        monkeypatch.setattr(proc, "_exposure_partition", lambda: ([], []))
        monkeypatch.setattr(proc, "pre_fetch_tools", lambda: None)
        monkeypatch.setattr(proc, "create_agent", lambda **_kw: None)
        proc.agent_config["agent_type"] = "classic"
        proc.build_agent("q")
        assert seen == [""]

    @pytest.mark.parametrize(("endpoint", "run_kind", "expected"), [
        ("schedule", "schedule", "oscar"),
        ("continuation", "chat", "oscar"),
        ("webhook", "published", ""),
    ])
    def test_a_headless_run_reads_as_its_payer_unless_it_is_outside_traffic(
        self, monkeypatch, endpoint, run_kind, expected
    ):
        from docsgpt.agents import headless_runner as hr

        seen: list = []

        def _fake_run(*_a, **_kw):
            seen.append(current_run_reader())
            return {"answer": ""}

        monkeypatch.setattr(hr, "_run_agent_headless", _fake_run)
        monkeypatch.setattr(hr.RunLimits, "start", classmethod(lambda cls, *a, **k: None))
        config = {"user_id": "eddie", "id": str(uuid.uuid4())}
        hr.run_agent_headless(config, "q", endpoint=endpoint, payer="oscar", run_kind=run_kind)
        assert seen == [expected]
        assert current_run_reader() is None
