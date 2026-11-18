"""Worker paths of a team's items: webhooks, ingest markers and wiki pages.

A team's agent and sources are owned by the team's principal, which never pays
and is never a person: a webhook on a team agent needs a person who pays for its
outside access, an ingest's Activity marker names the workspace it runs in, and
a wiki page written by a conversion names the person who asked for it.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt import worker
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.repositories.wiki_pages import WikiPagesRepository
from docsgpt.workspaces.principal import principal_id


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _deactivate(conn, user_id):
    UsersRepository(conn).upsert(user_id)
    conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": user_id})


def _no_run(monkeypatch):
    from docsgpt.agents import headless_runner

    ran = MagicMock(name="run_agent_headless", return_value={"answer": "ok"})
    monkeypatch.setattr(headless_runner, "run_agent_headless", ran)
    return ran


@pytest.mark.unit
class TestWebhookOnATeamAgent:
    def test_a_team_agent_with_no_payer_answers_no_payer(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        _, principal = _team(pg_conn)
        agent = AgentsRepository(pg_conn).create(principal, "Team bot", "published", agent_type="classic")
        ran = _no_run(monkeypatch)

        result = worker.agent_webhook_worker(task_self, str(agent["id"]), {"event": "ping"})

        assert result["status"] == "no_payer"
        assert "nobody to pay" in result["error"]
        ran.assert_not_called()

    def test_a_deactivated_payer_pauses_the_team_agent(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        _, principal = _team(pg_conn)
        agent = AgentsRepository(pg_conn).create(
            principal, "Team bot", "published", agent_type="classic", access_payer_id="adam",
        )
        _deactivate(pg_conn, "adam")
        ran = _no_run(monkeypatch)

        result = worker.agent_webhook_worker(task_self, str(agent["id"]), {"event": "ping"})

        assert result["status"] == "agent_paused"
        ran.assert_not_called()

    def test_an_active_payer_runs_it_and_pays(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        _, principal = _team(pg_conn)
        agent = AgentsRepository(pg_conn).create(
            principal, "Team bot", "published", agent_type="classic", access_payer_id="adam",
        )
        ran = _no_run(monkeypatch)

        result = worker.agent_webhook_worker(task_self, str(agent["id"]), {"event": "ping"})

        assert result["status"] == "success"
        assert ran.call_args.kwargs["payer"] == "adam"

    def test_a_deactivated_personal_owner_still_pauses(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        agent = AgentsRepository(pg_conn).create("sam", "Mine", "published", agent_type="classic")
        _deactivate(pg_conn, "sam")
        ran = _no_run(monkeypatch)

        result = worker.agent_webhook_worker(task_self, str(agent["id"]), {"event": "ping"})

        assert result["status"] == "agent_paused"
        ran.assert_not_called()


@pytest.mark.unit
class TestQueuedIngestNamesItsWorkspace:
    def test_a_team_reingest_carries_the_team(self, pg_conn, patch_worker_db, task_self, published, busy_lock):
        tid, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("Docs", user_id=principal, type="local", file_path="inputs/x")
        busy_lock()

        worker.reingest_source_worker(task_self, str(src["id"]), principal, actor_id="eddie")

        queued = [payload for kind, payload in published if kind == "source.ingest.queued"]
        assert queued and all(payload["team_id"] == tid for payload in queued)

    def test_a_personal_reingest_carries_none(self, pg_conn, patch_worker_db, task_self, published, busy_lock):
        src = SourcesRepository(pg_conn).create("Docs", user_id="sam", type="local", file_path="inputs/x")
        busy_lock()

        worker.reingest_source_worker(task_self, str(src["id"]), "sam")

        queued = [payload for kind, payload in published if kind == "source.ingest.queued"]
        assert queued and all(payload["team_id"] is None for payload in queued)

    def test_a_retried_team_ingest_marks_the_team(self, monkeypatch):
        tid = str(uuid.uuid4())
        marked = []
        monkeypatch.setattr(worker, "mark_ingest_running", lambda user, payload: marked.append((user, payload)))

        worker._mark_ingest_running(principal_id(tid), "eddie", {"source_id": "s1", "operation": "upload"})

        assert marked == [("eddie", {"source_id": "s1", "operation": "upload", "team_id": tid})]

    def test_the_marker_keeps_the_workspace(self, monkeypatch):
        from docsgpt.activity import flags

        seen = {}
        monkeypatch.setattr(flags, "mark_run_started", lambda user, run, info, ttl_seconds: seen.update(info))

        flags.mark_ingest_running("eddie", {"source_id": "s1", "team_id": "t1"})
        assert seen["team_id"] == "t1"
        flags.mark_ingest_running("eddie", {"source_id": "s1"})
        assert seen["team_id"] is None


def _patch_wiki_io(monkeypatch, chunks):
    store = MagicMock(name="vectorstore")
    store.get_chunks.return_value = chunks
    monkeypatch.setattr(
        "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
    )
    monkeypatch.setattr("docsgpt.api.user.tasks.reembed_wiki_page.delay", MagicMock(name="reembed_delay"))


@pytest.mark.unit
class TestWikiPagesNameAPerson:
    def _source(self, conn, owner, created_by=None):
        src = SourcesRepository(conn).create(
            "doc-set", user_id=owner, type="crawler", retriever="classic", created_by=created_by,
        )
        return str(src["id"])

    def _authors(self, conn, source_id):
        return {page["updated_by"] for page in WikiPagesRepository(conn).list_for_source(source_id)}

    def test_a_team_source_names_the_person_who_asked(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        _, principal = _team(pg_conn)
        source_id = self._source(pg_conn, principal, created_by="adam")
        _patch_wiki_io(monkeypatch, [{"doc_id": "g1", "text": "body", "metadata": {"source": "guide.md"}}])

        worker.convert_source_to_wiki_worker(task_self, source_id, principal, actor_id="eddie")

        assert self._authors(pg_conn, source_id) == {"eddie"}

    def test_with_no_actor_the_sources_creator(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        _, principal = _team(pg_conn)
        source_id = self._source(pg_conn, principal, created_by="adam")
        _patch_wiki_io(monkeypatch, [{"doc_id": "g1", "text": "body", "metadata": {"source": "guide.md"}}])

        worker.convert_source_to_wiki_worker(task_self, source_id, principal)

        assert self._authors(pg_conn, source_id) == {"adam"}

    def test_a_personal_source_still_names_its_owner(self, pg_conn, patch_worker_db, task_self, monkeypatch):
        source_id = self._source(pg_conn, "sam")
        _patch_wiki_io(monkeypatch, [{"doc_id": "g1", "text": "body", "metadata": {"source": "guide.md"}}])

        worker.convert_source_to_wiki_worker(task_self, source_id, "sam", actor_id="eddie")

        assert self._authors(pg_conn, source_id) == {"sam"}
