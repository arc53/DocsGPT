"""Scheduled syncs of a team's connector sources, and who pays for them.

A team's connection is paid for by the person who connected it (``connected_by``), read again on every run, so a
Reconnect by another Admin moves the bill to them. While that person is deactivated, out of the team, below Admin or
missing, or (scheduled syncs only) out of allowance, the scheduler skips the source instead of running it.
"""

from __future__ import annotations

import datetime
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt import worker
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

SELECTION = {"provider": "google_drive", "file_ids": ["f1"], "folder_ids": []}


@pytest.fixture
def quota_db(pg_conn, monkeypatch):
    """Point the allowance check at the test's connection."""

    @contextmanager
    def _readonly():
        yield pg_conn

    monkeypatch.setattr("docsgpt.quotas.service.db_readonly", _readonly)
    monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "month")


@pytest.fixture
def connections_db(pg_conn, monkeypatch):
    """Point the connection service's own reads at the test's connection."""

    @contextmanager
    def _same():
        yield pg_conn

    monkeypatch.setattr("docsgpt.connectors.service.db_readonly", _same)
    monkeypatch.setattr("docsgpt.connectors.service.db_session", _same)


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "ana", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _connection(conn, owner, connected_by=None):
    return ConnectorSessionsRepository(conn).create(
        owner, "google_drive", connector_key="google_drive", auth_kind="oauth",
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=connected_by,
    )


def _link(conn, source, connection):
    conn.execute(
        text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
        {"c": str(connection["id"]), "s": str(source["id"])},
    )
    return source


def _source(conn, owner, connection, *, created_by=None, frequency="daily"):
    row = SourcesRepository(conn).create(
        "Drive", user_id=owner, created_by=created_by, type="connector:google_drive", remote_data=SELECTION,
        sync_frequency=frequency,
    )
    return _link(conn, row, connection)


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _deactivate(conn, user_id):
    UsersRepository(conn).upsert(user_id)
    conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": user_id})


def _out_of_allowance(conn, user_id):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, token_limit=100)
    TokenUsageRepository(conn).insert(
        user_id=user_id, api_key="k", prompt_tokens=150, timestamp=datetime.datetime.now(datetime.timezone.utc),
    )


def _forget_who_connected(conn, connection):
    """A row from before ``connected_by`` existed: only reachable with the check dropped (rolled back after)."""
    conn.execute(text("ALTER TABLE connector_sessions DROP CONSTRAINT connector_sessions_connected_by_chk"))
    conn.execute(
        text("UPDATE connector_sessions SET connected_by = NULL WHERE id = CAST(:id AS uuid)"),
        {"id": str(connection["id"])},
    )


#: Each way the person who connected a team's account stops paying for its scheduled syncs.
PAUSES = {
    "left": lambda conn, tid, row: _set_role(conn, tid, "adam", None),
    "demoted": lambda conn, tid, row: _set_role(conn, tid, "adam", "team_editor"),
    "deactivated": lambda conn, tid, row: _deactivate(conn, "adam"),
    "out_of_allowance": lambda conn, tid, row: _out_of_allowance(conn, "adam"),
    "nobody_recorded": lambda conn, tid, row: _forget_who_connected(conn, row),
}


@pytest.fixture
def queued(monkeypatch) -> MagicMock:
    delay = MagicMock(name="sync_connector_source.delay")
    monkeypatch.setattr("docsgpt.api.user.tasks.sync_connector_source.delay", delay)
    return delay


@pytest.mark.unit
class TestTheScheduler:
    def test_a_team_connector_source_is_synced_while_its_account_can_pay(
        self, pg_conn, patch_worker_db, quota_db, task_self, queued,
    ):
        _, principal = _team(pg_conn)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"), created_by="eddie")

        counts = worker.sync_worker(task_self, "daily")

        queued.assert_called_once_with(str(src["id"]))
        assert counts["sync_dispatched"] == 1

    @pytest.mark.parametrize("pause", sorted(PAUSES))
    def test_it_is_skipped_while_whoever_connected_it_cannot_pay(
        self, pg_conn, patch_worker_db, quota_db, task_self, queued, pause,
    ):
        tid, principal = _team(pg_conn)
        row = _connection(pg_conn, principal, "adam")
        _source(pg_conn, principal, row, created_by="eddie")
        PAUSES[pause](pg_conn, tid, row)

        counts = worker.sync_worker(task_self, "daily")

        queued.assert_not_called()
        assert counts["sync_skipped"] == 1
        assert counts["sync_no_payer"] == 1

    def test_nothing_is_written_while_it_is_paused(self, pg_conn, patch_worker_db, quota_db, task_self, queued):
        tid, principal = _team(pg_conn)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"), created_by="eddie")
        _set_role(pg_conn, tid, "adam", None)

        worker.sync_worker(task_self, "daily")

        assert "sync_paused" not in (SourcesRepository(pg_conn).get_by_id(str(src["id"]))["metadata"] or {})

    def test_a_personal_connector_source_is_unchanged(self, pg_conn, patch_worker_db, quota_db, task_self, queued):
        _out_of_allowance(pg_conn, "sam")
        src = _source(pg_conn, "sam", _connection(pg_conn, "sam"))

        worker.sync_worker(task_self, "daily")

        queued.assert_called_once_with(str(src["id"]))


@pytest.fixture
def ingest(monkeypatch) -> MagicMock:
    run = MagicMock(name="ingest_connector", return_value={"status": "complete"})
    monkeypatch.setattr(worker, "ingest_connector", run)
    monkeypatch.setattr("docsgpt.connectors.service.connector_enabled", lambda conn, row: True)
    return run


@pytest.mark.unit
class TestTheSyncRun:
    def test_it_bills_and_tells_whoever_connected_the_account(
        self, pg_conn, patch_worker_db, quota_db, connections_db, task_self, ingest,
    ):
        _, principal = _team(pg_conn)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"), created_by="eddie")

        result = worker.sync_connector_source(task_self, str(src["id"]))

        assert result["status"] == "success"
        args, kwargs = ingest.call_args
        assert args[2] == principal
        assert kwargs["actor_id"] == "adam"

    def test_after_a_reconnect_by_another_admin_it_bills_them(
        self, pg_conn, patch_worker_db, quota_db, connections_db, task_self, ingest,
    ):
        _, principal = _team(pg_conn)
        row = _connection(pg_conn, principal, "adam")
        src = _source(pg_conn, principal, row, created_by="eddie")
        ConnectorSessionsRepository(pg_conn).set_connected_by(str(row["id"]), "ana")

        worker.sync_connector_source(task_self, str(src["id"]))

        assert ingest.call_args.kwargs["actor_id"] == "ana"

    @pytest.mark.parametrize("pause", sorted(PAUSES))
    def test_a_run_queued_before_the_pause_does_not_sync(
        self, pg_conn, patch_worker_db, quota_db, connections_db, task_self, ingest, pause,
    ):
        tid, principal = _team(pg_conn)
        row = _connection(pg_conn, principal, "adam")
        src = _source(pg_conn, principal, row, created_by="eddie")
        PAUSES[pause](pg_conn, tid, row)

        result = worker.sync_connector_source(task_self, str(src["id"]))

        ingest.assert_not_called()
        assert result["status"] == "paused"

    def test_a_personal_source_runs_as_its_owner(
        self, pg_conn, patch_worker_db, quota_db, connections_db, task_self, ingest,
    ):
        src = _source(pg_conn, "sam", _connection(pg_conn, "sam"))

        worker.sync_connector_source(task_self, str(src["id"]))

        args, kwargs = ingest.call_args
        assert args[2] == "sam"
        assert kwargs.get("actor_id") is None

    def test_a_connection_of_another_owner_is_never_used(
        self, pg_conn, patch_worker_db, quota_db, connections_db, task_self, ingest,
    ):
        _, principal = _team(pg_conn)
        personal = _connection(pg_conn, "adam")
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        # Only a row from before the owner trigger can point elsewhere.
        pg_conn.execute(text("ALTER TABLE sources DISABLE TRIGGER sources_connection_owner_matches"))
        pg_conn.execute(
            text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
            {"c": str(personal["id"]), "s": str(src["id"])},
        )

        result = worker.sync_connector_source(task_self, str(src["id"]))

        ingest.assert_not_called()
        assert result["status"] == "skipped"


@pytest.mark.unit
class TestTheConnectorIngest:
    def test_an_ingest_for_a_team_refuses_a_personal_connection(
        self, pg_conn, patch_worker_db, task_self, published, monkeypatch,
    ):
        _, principal = _team(pg_conn)
        personal = _connection(pg_conn, "adam")
        create = MagicMock(name="create_connector")
        create.return_value.connection_id = str(personal["id"])
        monkeypatch.setattr("docsgpt.worker.ConnectorCreator.create_connector", create)
        monkeypatch.setattr("docsgpt.worker.close_failed_ingest_progress", lambda *a, **k: None)

        with pytest.raises(ValueError):
            worker.ingest_connector(
                task_self, "Drive", principal, "google_drive", connection_id=str(personal["id"]),
                file_ids=["f1"], source_id=str(uuid.uuid4()), actor_id="adam",
            )

        create.return_value.download_to_directory.assert_not_called()
        assert published.recipients("source.ingest.failed") == ["adam"]


@pytest.mark.unit
class TestRemoteSourcesOnATeamConnection:
    @pytest.fixture
    def dispatched(self, monkeypatch) -> MagicMock:
        apply_async = MagicMock(name="sync_source.apply_async")
        monkeypatch.setattr("docsgpt.api.user.tasks.sync_source.apply_async", apply_async)
        return apply_async

    def _s3(self, conn, owner, connected_by, created_by):
        row = ConnectorSessionsRepository(conn).create(
            owner, "s3", connector_key="s3", auth_kind="api_key", account_label=f"k-{uuid.uuid4().hex[:6]}",
            connected_by=connected_by,
        )
        _link(conn, SourcesRepository(conn).create(
            "Bucket", user_id=owner, created_by=created_by, type="s3", remote_data={"bucket": "b"},
            sync_frequency="daily",
        ), row)
        return row

    def test_a_scheduled_sync_bills_whoever_connected_the_account(
        self, pg_conn, patch_worker_db, quota_db, task_self, dispatched,
    ):
        _, principal = _team(pg_conn)
        self._s3(pg_conn, principal, "adam", "eddie")
        task_self.request.id = "tick-1"

        counts = worker.sync_worker(task_self, "daily")

        assert counts["sync_dispatched"] == 1
        assert dispatched.call_args.kwargs["kwargs"]["actor_id"] == "adam"

    @pytest.mark.parametrize("pause", ["left", "out_of_allowance"])
    def test_it_is_skipped_while_they_cannot_pay(
        self, pg_conn, patch_worker_db, quota_db, task_self, dispatched, pause,
    ):
        tid, principal = _team(pg_conn)
        row = self._s3(pg_conn, principal, "adam", "eddie")
        PAUSES[pause](pg_conn, tid, row)
        task_self.request.id = "tick-1"

        counts = worker.sync_worker(task_self, "daily")

        dispatched.assert_not_called()
        assert counts["sync_no_payer"] == 1

    def test_the_loader_never_reads_another_owners_keys(self, pg_conn, patch_worker_db):
        _, principal = _team(pg_conn)
        personal = ConnectorSessionsRepository(pg_conn).create(
            "adam", "s3", connector_key="s3", auth_kind="api_key", account_label="k-1",
        )

        assert worker._with_connection_credentials({"bucket": "b"}, str(personal["id"]), owner=principal) is None


@pytest.mark.unit
class TestGraphExtractionOfATeamConnectorSource:
    def _run(self, pg_conn, task_self, monkeypatch, source, owner, actor_id=None):
        store = MagicMock(name="vectorstore")
        store.get_chunks.return_value = [{"doc_id": "c1", "text": "alpha"}]
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
        )
        monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
        payers = []

        def _extract(source_id, user, chunks, **kwargs):
            payers.append(kwargs.get("payer"))
            return {"nodes": 0, "edges": 0, "chunks_processed": 1}

        monkeypatch.setattr("docsgpt.graphrag.extraction.extract_graph_for_source", _extract)
        result = worker.extract_graph_worker(task_self, str(source["id"]), owner, actor_id=actor_id)
        return result, payers

    def _graph_source(self, conn, owner, connection):
        return _link(conn, SourcesRepository(conn).create(
            "Drive", user_id=owner, created_by="eddie", type="connector:google_drive", remote_data=SELECTION,
            config={"kind": "graphrag", "retrieval": {"retriever": "graphrag"}},
        ), connection)

    def test_with_nobody_asking_whoever_connected_the_account_pays(
        self, pg_conn, patch_worker_db, task_self, published, monkeypatch,
    ):
        _, principal = _team(pg_conn)
        src = self._graph_source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        _, payers = self._run(pg_conn, task_self, monkeypatch, src, principal)

        assert payers == ["adam"]

    def test_nobody_pays_while_the_account_is_paused(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
        tid, principal = _team(pg_conn)
        src = self._graph_source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        _set_role(pg_conn, tid, "adam", None)

        result, payers = self._run(pg_conn, task_self, monkeypatch, src, principal)

        assert payers == []
        assert result["reason"] == "sync_no_payer"

    def test_the_person_who_asked_still_pays(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
        _, principal = _team(pg_conn)
        src = self._graph_source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        _, payers = self._run(pg_conn, task_self, monkeypatch, src, principal, actor_id="eddie")

        assert payers == ["eddie"]


class TestOneLookupPerSyncPass:
    """A scheduled sync pass reads each team connection and each person's team role once, however many sources."""

    @pytest.fixture
    def dispatched(self, monkeypatch) -> list:
        calls: list = []
        monkeypatch.setattr(worker, "_dispatch_scheduled_sync", lambda key, **kw: calls.append(kw) or "dispatched")
        return calls

    def _seed(self, conn, principal, row, count):
        for i in range(count):
            _link(conn, SourcesRepository(conn).create(
                f"Bucket {i}", user_id=principal, created_by="eddie", type="s3", remote_data={"bucket": f"b{i}"},
                sync_frequency="daily",
            ), row)
            _source(conn, principal, row, created_by="eddie")
            SourcesRepository(conn).create(
                f"Site {i}", user_id=principal, created_by="eddie", type="website",
                remote_data={"entries": [{"url": f"https://x{i}.io/", "mode": "site"}]}, sync_frequency="daily",
            )

    def _statements(self, conn, task_self) -> tuple:
        from sqlalchemy import event

        statements: list[str] = []

        def _count(_conn, _cursor, statement, *args):
            statements.append(statement)

        event.listen(conn, "before_cursor_execute", _count)
        try:
            counts = worker.sync_worker(task_self, "daily")
        finally:
            event.remove(conn, "before_cursor_execute", _count)
        return counts, statements

    def test_the_same_queries_for_one_source_of_each_kind_or_many(
        self, pg_conn, patch_worker_db, quota_db, task_self, queued, dispatched,
    ):
        _, principal = _team(pg_conn)
        row = _connection(pg_conn, principal, "adam")
        self._seed(pg_conn, principal, row, 1)
        one_counts, one = self._statements(pg_conn, task_self)

        self._seed(pg_conn, principal, row, 3)
        many_counts, many = self._statements(pg_conn, task_self)

        assert one_counts["sync_dispatched"] == 3 and many_counts["sync_dispatched"] == 12
        assert len(many) == len(one)

    def test_each_source_still_gets_its_own_payer(
        self, pg_conn, patch_worker_db, quota_db, task_self, queued, dispatched,
    ):
        tid, principal = _team(pg_conn)
        row = _connection(pg_conn, principal, "adam")
        self._seed(pg_conn, principal, row, 2)
        SourcesRepository(pg_conn).create(
            "Vera's site", user_id=principal, created_by="vera", type="website",
            remote_data={"entries": [{"url": "https://v.io/", "mode": "site"}]}, sync_frequency="daily",
        )
        TeamMembersRepository(pg_conn).add_member(tid, "vera", role="team_viewer")

        counts = worker.sync_worker(task_self, "daily")

        assert sorted(call.get("actor_id") for call in dispatched) == ["adam"] * 2 + ["eddie"] * 2
        assert queued.call_count == 2
        assert counts["sync_no_payer"] == 1
