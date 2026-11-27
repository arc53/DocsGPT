"""Ingest of a team's sources.

A team's source is owned by the team's principal, whose event stream nobody
reads. The job runs as the principal (paths, rows) and names the person who
asked as ``actor_id``: its events reach that person, its model calls bill
them, and the new row records them as ``created_by``. A scheduled sync has
no actor: it bills the person who added the source while they are still an
Editor in the team, and is skipped otherwise.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt import worker
from docsgpt.quotas.payer import current_run_billing
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import principal_id
from tests.worker.test_ingest_worker import _patch_ingest_pipeline

SITE = {"entries": [{"url": "https://x.io/", "mode": "site"}]}


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    repo.add_member(tid, "vera", role="team_viewer")
    return tid, principal_id(tid)


@pytest.mark.unit
class TestEventsReachThePerson:
    def test_a_team_reingest_tells_the_editor_and_never_the_principal(
        self, pg_conn, patch_worker_db, task_self, published,
    ):
        _, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("Docs", user_id=principal, type="website")

        worker.reingest_source_worker(task_self, str(src["id"]), principal, actor_id="eddie")

        assert published.recipients("source.ingest.failed") == ["eddie"]
        assert principal not in published.users

    def test_someone_removed_before_their_reingest_ends_hears_nothing(
        self, pg_conn, patch_worker_db, task_self, published,
    ):
        tid, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("Docs", user_id=principal, type="website")
        TeamMembersRepository(pg_conn).remove_member(tid, "eddie")

        worker.reingest_source_worker(task_self, str(src["id"]), principal, actor_id="eddie")

        assert "eddie" not in published.users
        assert published.recipients("source.ingest.failed") == ["adam", "alice"]

    def test_a_failure_nobody_asked_for_reaches_the_teams_admins(
        self, pg_conn, patch_worker_db, task_self, published,
    ):
        _, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("Docs", user_id=principal, type="website")

        worker.reingest_source_worker(task_self, str(src["id"]), principal)

        assert published.recipients("source.ingest.failed") == ["adam", "alice"]
        assert principal not in published.users

    def test_a_personal_sources_events_still_reach_owner_and_editor(
        self, pg_conn, patch_worker_db, task_self, published,
    ):
        src = SourcesRepository(pg_conn).create("Docs", user_id="sam", type="website")

        worker.reingest_source_worker(task_self, str(src["id"]), "sam", actor_id="eddie")

        assert published.recipients("source.ingest.failed") == ["eddie", "sam"]

    def test_a_team_website_ingest_names_its_creator(
        self, pg_conn, patch_worker_db, task_self, published, remote_pipeline, monkeypatch, tmp_path,
    ):
        _, principal = _team(pg_conn)
        monkeypatch.setattr(worker, "_record_website_report", lambda *a, **k: {})

        worker.remote_worker(
            task_self, SITE, "Site", principal, "website", directory=str(tmp_path),
            source_id=str(uuid.uuid4()), actor_id="eddie",
        )

        assert published.recipients("source.ingest.queued") == ["eddie"]
        assert published.recipients("source.ingest.completed") == ["eddie"]
        assert principal not in published.users
        assert remote_pipeline.uploads[0]["user"] == principal
        assert remote_pipeline.uploads[0]["created_by"] == "eddie"

    def test_a_personal_ingest_sends_no_creator(
        self, pg_conn, patch_worker_db, task_self, published, remote_pipeline, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(worker, "_record_website_report", lambda *a, **k: {})

        worker.remote_worker(
            task_self, SITE, "Site", "sam", "website", directory=str(tmp_path), source_id=str(uuid.uuid4()),
        )

        assert "created_by" not in remote_pipeline.uploads[0]
        assert published.recipients("source.ingest.completed") == ["sam"]

    def test_a_team_upload_names_its_creator_and_tells_the_uploader(
        self, pg_conn, patch_worker_db, task_self, published, monkeypatch,
    ):
        _, principal = _team(pg_conn)
        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)

        worker.ingest_worker(
            task_self, directory="inputs", formats=[".txt"], job_name="job1",
            file_path="inputs/team/job1/a.txt", filename="a.txt", user=principal, actor_id="eddie",
        )

        assert captured[0]["user"] == principal
        assert captured[0]["created_by"] == "eddie"
        assert published.recipients("source.ingest.queued") == ["eddie"]
        assert published.recipients("source.ingest.completed") == ["eddie"]
        assert principal not in published.users


@pytest.mark.unit
class TestGraphExtractionPayer:
    def _run(self, pg_conn, task_self, monkeypatch, owner, created_by=None, actor_id=None):
        src = SourcesRepository(pg_conn).create(
            "graph-set", user_id=owner, created_by=created_by, type="file",
            config={"kind": "graphrag", "retrieval": {"retriever": "graphrag"}},
        )
        store = MagicMock(name="vectorstore")
        store.get_chunks.return_value = [{"doc_id": "c1", "text": "alpha"}]
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
        )
        monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
        payers = []

        def _extract(source_id, user, chunks, **kwargs):
            payers.append((user, kwargs.get("payer")))
            return {"nodes": 0, "edges": 0, "chunks_processed": 1}

        monkeypatch.setattr("docsgpt.graphrag.extraction.extract_graph_for_source", _extract)
        result = worker.extract_graph_worker(task_self, str(src["id"]), owner, actor_id=actor_id)
        return result, payers

    def test_the_editor_who_asked_pays(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
        _, principal = _team(pg_conn)

        _, payers = self._run(pg_conn, task_self, monkeypatch, principal, created_by="adam", actor_id="eddie")

        assert payers == [(principal, "eddie")]

    def test_with_no_actor_the_person_who_added_it_pays(
        self, pg_conn, patch_worker_db, task_self, published, monkeypatch,
    ):
        _, principal = _team(pg_conn)

        _, payers = self._run(pg_conn, task_self, monkeypatch, principal, created_by="eddie")

        assert payers == [(principal, "eddie")]

    def test_nobody_to_bill_skips_the_extraction(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
        _, principal = _team(pg_conn)

        # Vera can no longer add knowledge (a viewer), and nobody asked.
        result, payers = self._run(pg_conn, task_self, monkeypatch, principal, created_by="vera")

        assert payers == []
        assert result["status"] == "skipped"
        assert result["reason"] == "sync_no_payer"

    def test_a_personal_source_bills_its_owner(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
        _, payers = self._run(pg_conn, task_self, monkeypatch, "sam")

        assert payers == [("sam", "sam")]


@pytest.mark.unit
class TestExtractionBillsThePayer:
    def test_every_model_call_runs_billed_to_the_payer(self, monkeypatch):
        from docsgpt.graphrag import extraction
        from docsgpt.storage.db.source_config import SourceConfig

        seen = []

        def _build(model_id, user, request_id):
            seen.append(("build", user, getattr(current_run_billing(), "payer", None)))
            return MagicMock()

        def _extract_chunk(llm, text, chunk_id):
            seen.append(("call", None, getattr(current_run_billing(), "payer", None)))
            return None

        store = MagicMock()
        store.pending_chunks.return_value = ["c1"]
        monkeypatch.setattr("docsgpt.graphrag.store.GraphStore", lambda: store)
        monkeypatch.setattr(extraction, "get_embeddings", lambda: MagicMock())
        monkeypatch.setattr(extraction, "_resolve_extraction_model", lambda config, user: "m")
        monkeypatch.setattr(extraction, "_build_extraction_llm", _build)
        monkeypatch.setattr(extraction, "_extract_chunk", _extract_chunk)

        extraction.extract_graph_for_source(
            "s1", "__team__x", [{"doc_id": "c1", "text": "alpha"}], config=SourceConfig.parse({}), payer="eddie",
        )

        assert seen and all(payer == "eddie" for _, _, payer in seen)
        assert current_run_billing() is None


@pytest.mark.unit
class TestScheduledSyncPayer:
    @pytest.fixture
    def dispatched(self, monkeypatch) -> MagicMock:
        apply_async = MagicMock(name="sync_source.apply_async")
        monkeypatch.setattr("docsgpt.api.user.tasks.sync_source.apply_async", apply_async)
        return apply_async

    def _seed(self, conn, owner, created_by):
        return SourcesRepository(conn).create(
            "Site", user_id=owner, created_by=created_by, type="website", remote_data=SITE, sync_frequency="daily",
        )

    def test_a_team_sync_bills_the_editor_who_added_it(self, pg_conn, patch_worker_db, task_self, dispatched):
        _, principal = _team(pg_conn)
        self._seed(pg_conn, principal, "eddie")
        task_self.request.id = "tick-1"

        counts = worker.sync_worker(task_self, "daily")

        assert counts["sync_dispatched"] == 1
        kwargs = dispatched.call_args.kwargs["kwargs"]
        assert kwargs["user"] == principal
        assert kwargs["actor_id"] == "eddie"

    @pytest.mark.parametrize("created_by", ["vera", "mallory", None])
    def test_no_editor_to_bill_skips_and_flags_the_sync(
        self, pg_conn, patch_worker_db, task_self, dispatched, created_by,
    ):
        _, principal = _team(pg_conn)
        src = self._seed(pg_conn, principal, created_by)
        task_self.request.id = "tick-1"

        counts = worker.sync_worker(task_self, "daily")

        dispatched.assert_not_called()
        assert counts["sync_skipped"] == 1
        assert counts["sync_no_payer"] == 1
        row = SourcesRepository(pg_conn).get_by_id(str(src["id"]))
        assert row["metadata"]["sync_paused"]["reason"] == "sync_no_payer"

    def test_the_flag_clears_once_someone_can_pay_again(self, pg_conn, patch_worker_db, task_self, dispatched):
        tid, principal = _team(pg_conn)
        src = self._seed(pg_conn, principal, "vera")
        task_self.request.id = "tick-1"
        worker.sync_worker(task_self, "daily")
        pg_conn.execute(
            text("UPDATE team_members SET role = 'team_editor' WHERE team_id = CAST(:t AS uuid) AND user_id = 'vera'"),
            {"t": tid},
        )
        task_self.request.id = "tick-2"

        counts = worker.sync_worker(task_self, "daily")

        assert counts["sync_dispatched"] == 1
        row = SourcesRepository(pg_conn).get_by_id(str(src["id"]))
        assert "sync_paused" not in (row["metadata"] or {})

    def test_a_personal_sync_is_unchanged(self, pg_conn, patch_worker_db, task_self, dispatched):
        self._seed(pg_conn, "sam", None)
        task_self.request.id = "tick-1"

        worker.sync_worker(task_self, "daily")

        kwargs = dispatched.call_args.kwargs["kwargs"]
        assert kwargs["user"] == "sam"
        assert "actor_id" not in kwargs
