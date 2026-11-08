"""A run reads its knowledge folders: agents, headless runs, agent search, workflow nodes and agentless chat.

Each holder's folders expand at run time into their owner's filed sources
(``folder_knowledge.folder_source_ids``), unioned with the holder's own
authorized sources, each source once. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

from tests.api.user.test_resource_sponsors import EDITOR, OWNER, _patch_db

OTHER = "kr-other"


def _folder(conn, owner=OWNER, name="Carriers", parent=None):
    return str(FoldersRepository(conn).create(owner, name, resource_type="source", parent_id=parent)["id"])


def _source(conn, owner=OWNER, name="doc"):
    return str(SourcesRepository(conn).create(name, user_id=owner)["id"])


def _file(conn, sid, folder, owner=OWNER):
    FolderItemsRepository(conn).file(owner, "source", sid, folder)


def _agent(conn, **extra):
    extra.setdefault("agent_type", "classic")
    return AgentsRepository(conn).create(OWNER, "A", "published", key="k-runs", **extra)


class TestAgentRuns:
    def test_folder_sources_follow_the_agents_own(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        folder = _folder(pg_conn)
        child = _folder(pg_conn, name="EU", parent=folder)
        own = _source(pg_conn, name="own")
        filed = _source(pg_conn, name="filed")
        deep = _source(pg_conn, name="deep")
        _file(pg_conn, own, folder)
        _file(pg_conn, filed, folder)
        _file(pg_conn, deep, child)
        agent = _agent(pg_conn, source_id=own, knowledge_folder_ids=[folder])
        primary, rows = authorized_agent_sources(pg_conn, agent)
        assert str(primary["id"]) == own
        assert [str(r["id"]) for r in rows] == [own, filed, deep]

    def test_a_folder_only_agent_reads_its_folder(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        folder = _folder(pg_conn)
        sid = _source(pg_conn)
        _file(pg_conn, sid, folder)
        primary, rows = authorized_agent_sources(pg_conn, _agent(pg_conn, knowledge_folder_ids=[folder]))
        assert primary is None
        assert [str(r["id"]) for r in rows] == [sid]

    def test_an_editors_folder_reads_as_the_editors_filing(self, pg_conn):
        """The folder owner (an editor) files their own source; the agent's owner never could use it."""
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        folder = _folder(pg_conn, owner=EDITOR)
        sid = _source(pg_conn, owner=EDITOR)
        _file(pg_conn, sid, folder, owner=EDITOR)
        agent = _agent(pg_conn, knowledge_folder_ids=[folder])
        # Only while the folder's owner edits the agent (see TestTeammateFolders).
        assert authorized_agent_sources(pg_conn, agent)[1] == []
        _grant(pg_conn, "agent", str(agent["id"]), OWNER, EDITOR, "editor")
        _, rows = authorized_agent_sources(pg_conn, agent)
        assert [str(r["id"]) for r in rows] == [sid]

    def test_agent_search_covers_its_folders(self, pg_conn):
        from docsgpt.services import search_service

        folder = _folder(pg_conn)
        sid = _source(pg_conn)
        _file(pg_conn, sid, folder)
        _agent(pg_conn, knowledge_folder_ids=[folder])
        seen = {}

        def _search_sources(query, source_ids, chunks):
            seen["ids"] = source_ids
            return []

        @contextmanager
        def _conn():
            yield pg_conn

        with patch.object(search_service, "db_readonly", _conn), \
             patch.object(search_service, "_search_sources", _search_sources):
            search_service.search("k-runs", "q", 5)
        assert seen["ids"] == [sid]


class TestHeadless:
    def test_a_folder_only_agent_reads_its_sources(self, monkeypatch):
        from docsgpt.agents import headless_runner as hr

        agent = MagicMock(name="agent")
        agent.gen.return_value = iter([{"answer": "ok"}])
        agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
        retriever = MagicMock(name="retriever")
        retriever.search.return_value = []
        tool_executor = MagicMock(name="tool_executor")
        tool_executor.headless_denials = []
        seen: dict = {}

        def _dispatcher(_legacy, sources=None, **kwargs):
            seen["source"] = kwargs.get("source")
            seen["retriever"] = _legacy
            return retriever

        def _authorized(_conn, row):
            seen["row"] = row
            return None, [{"id": "s1", "config": {}}]

        @contextmanager
        def _conn():
            yield MagicMock()

        monkeypatch.setattr(hr, "get_prompt", lambda pid: "p")
        monkeypatch.setattr(hr, "db_readonly", _conn)
        monkeypatch.setattr(hr, "authorized_agent_sources", _authorized)
        monkeypatch.setattr(hr, "build_dispatcher", _dispatcher)
        monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
        monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, t, **kw: agent))
        config = {
            "user_id": "owner-1", "id": "agent-1", "default_model_id": "m", "agent_type": "classic",
            "prompt_id": "default", "source_id": None, "retriever": None,
            "knowledge_folder_ids": ["f1"],
        }
        with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
             patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
             patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
             patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000), \
             patch("docsgpt.agents.headless_runner.QuotaService.check", return_value=None):
            hr.run_agent_headless(config, "q", endpoint="webhook")
        assert seen["row"]["knowledge_folder_ids"] == ["f1"]
        assert seen["source"] == {"active_docs": ["s1"]}
        # With no primary source to name one, an unset retriever is classic.
        with patch.object(hr.RetrieverCreator, "create_retriever") as create:
            seen["retriever"]()
        assert create.call_args.args[0] == "classic"


class TestWorkflowNodes:
    def _engine(self, pg_conn):
        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.agent = SimpleNamespace(
            workflow_row=WorkflowsRepository(pg_conn).get_by_id(str(wf["id"])),
            _resolve_owner_id=lambda: OWNER, user=OWNER, decoded_token={"sub": OWNER},
        )
        return engine

    def test_node_sources_union_its_folders(self, pg_conn):
        engine = self._engine(pg_conn)
        own = _source(pg_conn, name="own")
        folder = _folder(pg_conn)
        filed = _source(pg_conn, name="filed")
        _file(pg_conn, own, folder)
        _file(pg_conn, filed, folder)
        from docsgpt.agents.workflows.schemas import AgentNodeConfig

        with _patch_db(pg_conn):
            assert engine._node_source_ids(AgentNodeConfig(sources=[own], folders=[folder])) == [own, filed]
            # A folder lists its sources by name.
            assert engine._node_source_ids(AgentNodeConfig(folders=[folder])) == [filed, own]
            assert engine._node_source_ids(AgentNodeConfig(sources=[own])) == [own]

    def test_a_folder_only_node_retrieves(self, pg_conn):
        from docsgpt.agents.workflows.schemas import AgentNodeConfig

        engine = self._engine(pg_conn)
        engine.state = {"query": "q"}
        engine._loop_item = None
        folder = _folder(pg_conn)
        sid = _source(pg_conn)
        _file(pg_conn, sid, folder)
        retriever = MagicMock()
        retriever.search.return_value = []
        with _patch_db(pg_conn), patch(
            "docsgpt.retriever.retriever_creator.RetrieverCreator.create_retriever", return_value=retriever
        ) as create:
            engine._retrieve_node_sources(AgentNodeConfig(folders=[folder]))
        assert create.call_args.kwargs["source"] == {"active_docs": [sid]}


class TestAgentlessChat:
    def _processor(self, data, user=OWNER, agent_data=None):
        import docsgpt.api.answer.services.stream_processor as sp_mod

        sp = sp_mod.StreamProcessor.__new__(sp_mod.StreamProcessor)
        sp.data = data
        sp.decoded_token = {"sub": user}
        sp.initial_user_id = user
        sp._agent_data = agent_data
        sp.source = {}
        sp.all_sources = []
        return sp

    def _configure(self, pg_conn, sp):
        import docsgpt.api.answer.services.stream_processor as sp_mod

        @contextmanager
        def _conn():
            yield pg_conn

        with patch.object(sp_mod, "db_readonly", _conn):
            sp._configure_source()
        return sp

    @pytest.fixture
    def filed(self, pg_conn):
        folder = _folder(pg_conn)
        a, b = _source(pg_conn, name="a"), _source(pg_conn, name="b")
        _file(pg_conn, a, folder)
        _file(pg_conn, b, folder)
        return folder, a, b

    def test_active_folders_read_the_callers_folder(self, pg_conn, filed):
        folder, a, b = filed
        sp = self._configure(pg_conn, self._processor({"active_folders": [folder]}))
        assert sp.source == {"active_docs": [a, b]}
        assert [e["id"] for e in sp.all_sources] == [a, b]

    def test_unioned_with_active_docs_each_once(self, pg_conn, filed):
        folder, a, b = filed
        extra = _source(pg_conn, name="extra")
        sp = self._configure(pg_conn, self._processor({"active_docs": [extra, a], "active_folders": [folder]}))
        assert sp.source == {"active_docs": [extra, a, b]}
        sp = self._configure(pg_conn, self._processor({"active_docs": extra, "active_folders": [folder]}))
        assert sp.source == {"active_docs": [extra, a, b]}

    def test_a_single_active_doc_without_folders_is_unchanged(self, pg_conn):
        sid = _source(pg_conn)
        sp = self._configure(pg_conn, self._processor({"active_docs": sid, "active_folders": []}))
        assert sp.source == {"active_docs": sid}

    def test_someone_elses_folder_adds_nothing(self, pg_conn, filed):
        folder, _, _ = filed
        sp = self._configure(pg_conn, self._processor({"active_folders": [folder]}, user=OTHER))
        assert sp.source == {}
        assert sp.all_sources == []

    def test_ignored_in_an_agent_chat(self, pg_conn, filed):
        folder, _, _ = filed
        sp = self._processor({"active_folders": [folder]}, agent_data={"sources": [], "source": None})
        assert self._configure(pg_conn, sp).source == {}

    @pytest.mark.parametrize("raw", ["not-a-list", {"id": "x"}, ["junk"]])
    def test_malformed_values_add_nothing(self, pg_conn, raw):
        sp = self._configure(pg_conn, self._processor({"active_folders": raw}))
        assert sp.source == {}


def _grant(conn, resource_type, resource_id, owner, member, level):
    import uuid

    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, resource_id, owner, owner, access_level=level, target_user_id=member
    )


class TestTeammateFolders:
    """A folder its holder's owner doesn't own feeds only what its owner could sponsor, while they edit the holder."""

    def _setup(self, pg_conn):
        from tests.api.user.test_resource_sponsors import _agent as _shared_agent

        agent_id, team_id = _shared_agent(pg_conn)
        folder = _folder(pg_conn, owner=EDITOR, name="Editor's")
        own = _source(pg_conn, owner=EDITOR, name="a-own")
        viewed = _source(pg_conn, owner=OTHER, name="b-viewed")
        edited = _source(pg_conn, owner=OTHER, name="c-edited")
        owners = _source(pg_conn, owner=OWNER, name="d-owners")
        _grant(pg_conn, "source", viewed, OTHER, EDITOR, "viewer")
        _grant(pg_conn, "source", edited, OTHER, EDITOR, "editor")
        _grant(pg_conn, "source", owners, OWNER, EDITOR, "viewer")
        for sid in (own, viewed, edited, owners):
            _file(pg_conn, sid, folder, owner=EDITOR)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"knowledge_folder_ids": [folder]})
        agent = AgentsRepository(pg_conn).get_by_id(agent_id)
        return agent, team_id, folder, own, viewed, edited, owners

    def test_feeds_only_what_the_folder_owner_could_sponsor(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources
        from docsgpt.api.user.folder_knowledge import folder_details

        agent, _, folder, own, viewed, edited, owners = self._setup(pg_conn)
        _, rows = authorized_agent_sources(pg_conn, agent)
        # A source the editor only views is not theirs to extend; one the owner can use always runs.
        assert [str(r["id"]) for r in rows] == [own, edited, owners]
        details = folder_details(pg_conn, [folder], EDITOR, holder_type="agent", holder=agent)
        assert details == [{"id": folder, "name": "Editor's", "source_count": 3}]

    def test_feeds_nothing_once_the_folder_owner_cannot_edit_the_agent(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources
        from docsgpt.api.user.folder_knowledge import folder_details
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository

        agent, team_id, folder, *_ = self._setup(pg_conn)
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", str(agent["id"]), target_user_id=EDITOR)
        _, rows = authorized_agent_sources(pg_conn, agent)
        assert rows == []
        assert folder_details(pg_conn, [folder], OWNER, holder_type="agent", holder=agent) == [
            {"id": folder, "name": "Editor's", "source_count": 0, "stopped": True,
             "reason": "sponsor_cannot_edit_agent"}
        ]

    def test_the_owners_own_folder_is_unchanged(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        folder = _folder(pg_conn)
        viewed = _source(pg_conn, owner=OTHER, name="viewed")
        _grant(pg_conn, "source", viewed, OTHER, OWNER, "viewer")
        _file(pg_conn, viewed, folder)
        _, rows = authorized_agent_sources(pg_conn, _agent(pg_conn, knowledge_folder_ids=[folder]))
        assert [str(r["id"]) for r in rows] == [viewed]

    def test_a_missing_folder_reads_stopped(self, pg_conn):
        import uuid

        from docsgpt.api.user.folder_knowledge import folder_details

        gone = str(uuid.uuid4())
        assert folder_details(pg_conn, [gone], OWNER) == [
            {"id": gone, "name": None, "source_count": 0, "stopped": True, "reason": "deleted"}
        ]

    def test_a_workflow_node_folder_of_an_editor_who_left(self, pg_conn):
        from docsgpt.agents.workflows.schemas import AgentNodeConfig
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
        from tests.api.user.test_resource_sponsors import _agent as _shared_agent

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        agent_id, team_id = _shared_agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        folder = _folder(pg_conn, owner=EDITOR)
        sid = _source(pg_conn, owner=EDITOR)
        _file(pg_conn, sid, folder, owner=EDITOR)
        engine = TestWorkflowNodes()._engine(pg_conn)
        engine.agent.workflow_row = WorkflowsRepository(pg_conn).get_by_id(str(wf["id"]))
        with _patch_db(pg_conn):
            assert engine._node_source_ids(AgentNodeConfig(folders=[folder])) == [sid]
            TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
            assert engine._node_source_ids(AgentNodeConfig(folders=[folder])) == []
