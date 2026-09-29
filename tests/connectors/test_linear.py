"""Linear as Knowledge: the same MCP sign-in that gives agents Linear's tools syncs its issues."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
from docsgpt.connectors import catalog, linear, service
from docsgpt.security.encryption import encrypt_json


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.connector.connections", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield):
        yield


def _call(app, resource, method, path, user="alice", body=None, args=()):
    with app.test_request_context(path, method=method.upper(), json=body):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource(), method)(*args)


def _linear(conn, user="alice", status="connected") -> str:
    tokens = {"tokens": {"access_token": "lin-mcp", "token_type": "Bearer", "refresh_token": "r"}}
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "server_url, encrypted_credentials) VALUES (:u, 'mcp:https://mcp.linear.app', 'mcp:linear', "
            "'mcp_oauth', :s, 'alice@acme.com', 'https://mcp.linear.app', :e) RETURNING id"
        ),
        {"u": user, "s": status, "e": encrypt_json(tokens, user)},
    ).scalar())


class FakeLinear:
    def __init__(self, answers):
        self.answers = answers

    async def input_schema(self, name):
        return {"properties": {"limit": {}, "cursor": {}}} if name in self.answers else None

    async def call(self, name, arguments):
        return self.answers[name]


def _session(answers):
    """``run_connection_session`` answering from ``answers``, recording the connection it was given."""
    seen = {}

    def run(connection, server_url, work, **kwargs):
        seen.update(connection=connection, server_url=server_url)
        return asyncio.run(work(FakeLinear(answers)))

    return run, seen


class TestCatalog:
    @pytest.fixture(autouse=True)
    def _fresh_registry(self):
        catalog.reset_registry_for_tests()
        yield
        catalog.reset_registry_for_tests()

    def test_one_linear_sign_in_syncs_and_gives_tools(self):
        definition = catalog.get_definition("mcp:linear")
        assert definition.capabilities == ("sync", "read", "write")
        assert definition.sync_ingestor == "linear"
        assert definition.setup == {"tools": "auto", "sync": "ask"}
        assert definition.tool_templates == ("mcp_tool",)
        assert definition.auth_kind == "mcp_oauth"

    def test_other_presets_still_only_give_tools(self):
        notion = catalog.get_definition("mcp:notion")
        assert notion.sync_ingestor is None
        assert notion.setup == {"tools": "auto", "sync": "off"}
        assert "sync" not in notion.capabilities

    def test_linear_sources_have_a_loader(self):
        from docsgpt.parser.remote.linear_loader import LinearLoader
        from docsgpt.parser.remote.remote_creator import RemoteCreator, normalize_remote_data

        assert isinstance(RemoteCreator.create_loader("linear"), LinearLoader)
        stored = {"teams": [{"id": "t1"}], "include_comments": True}
        assert normalize_remote_data("linear", stored) == stored


class TestWorkspace:
    def test_lists_the_teams_and_projects_to_pick(self, app, pg_conn):
        from docsgpt.api.connector.connections import LinearWorkspace

        cid = _linear(pg_conn)
        run, seen = _session({
            "list_teams": {"teams": [{"id": "t2", "key": "OPS", "name": "Operations"},
                                     {"id": "t1", "key": "ENG", "name": "Engineering"}]},
            "list_projects": [{"id": "p1", "name": "Acme", "state": {"name": "Started"}, "teams": ["Engineering"]}],
        })
        with _db(pg_conn), patch("docsgpt.connectors.mcp.run_connection_session", side_effect=run):
            resp = _call(app, LinearWorkspace, "get", f"/api/connections/{cid}/linear", args=[cid])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["teams"] == [
            {"id": "t1", "key": "ENG", "name": "Engineering"}, {"id": "t2", "key": "OPS", "name": "Operations"},
        ]
        assert data["projects"] == [{"id": "p1", "name": "Acme", "state": "Started", "teams": ["Engineering"]}]
        assert str(seen["connection"]["id"]) == cid
        assert seen["server_url"] == "https://mcp.linear.app/mcp"
        assert "lin-mcp" not in resp.get_data(as_text=True)

    def test_a_lost_sign_in_asks_to_reconnect(self, app, pg_conn):
        from docsgpt.api.connector.connections import LinearWorkspace

        cid = _linear(pg_conn)
        with _db(pg_conn), patch("docsgpt.connectors.mcp.run_connection_session",
                                 side_effect=service.ConnectionUnavailable("expired", connection_id=cid)):
            resp = _call(app, LinearWorkspace, "get", f"/api/connections/{cid}/linear", args=[cid])
        assert resp.status_code == 409
        assert resp.get_json()["code"] == "reconnect"

    def test_linear_not_answering_is_worth_a_retry(self, app, pg_conn):
        from docsgpt.api.connector.connections import LinearWorkspace

        cid = _linear(pg_conn)
        with _db(pg_conn), patch("docsgpt.connectors.mcp.run_connection_session",
                                 side_effect=service.TransientConnectionError("rate limit")):
            resp = _call(app, LinearWorkspace, "get", f"/api/connections/{cid}/linear", args=[cid])
        assert resp.status_code == 503

    def test_only_the_owner_and_only_linear(self, app, pg_conn):
        from docsgpt.api.connector.connections import LinearWorkspace

        theirs = _linear(pg_conn, user="bob")
        github = str(pg_conn.execute(text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status) "
            "VALUES ('alice', 'github', 'github', 'api_key', 'connected') RETURNING id"
        )).scalar())
        with _db(pg_conn):
            for cid in (theirs, github):
                resp = _call(app, LinearWorkspace, "get", f"/api/connections/{cid}/linear", args=[cid])
                assert resp.status_code == 404


class TestSetup:
    def test_sync_queues_the_picked_teams_with_the_connection(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _linear(pg_conn)
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_remote.apply_async",
                                 return_value=MagicMock(id="t")) as apply:
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup", body={
                "create_tools": False,
                "sync": {"items": {"teams": [{"id": "t1", "key": "ENG", "name": "Engineering"}],
                                   "include_comments": False}, "frequency": "daily"},
            }, args=[cid])
        assert resp.status_code == 200
        kwargs = apply.call_args.kwargs["kwargs"]
        assert kwargs["loader"] == "linear"
        assert kwargs["connection_id"] == cid
        assert kwargs["sync_frequency"] == "daily"
        assert kwargs["source_data"] == {
            "teams": [{"id": "t1", "key": "ENG", "name": "Engineering"}], "projects": [],
            "include_comments": False, "include_documents": False,
        }
        assert resp.get_json()["sources"][0]["name"] == "Linear · Engineering"

    def test_nothing_picked_is_a_bad_request(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _linear(pg_conn)
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_remote.apply_async") as apply:
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup", body={
                "create_tools": False, "sync": {"items": {"teams": []}},
            }, args=[cid])
        assert resp.status_code == 400
        apply.assert_not_called()


class TestWorker:
    @staticmethod
    @contextmanager
    def _readonly(conn):
        from docsgpt import worker

        @contextmanager
        def _yield():
            yield conn

        with patch.object(worker, "db_readonly", _yield):
            yield worker

    def test_the_loader_gets_the_connection_not_its_tokens(self, pg_conn):
        cid = _linear(pg_conn)
        with self._readonly(pg_conn) as worker:
            data = worker._with_connection_credentials({"teams": [{"id": "t1"}]}, cid)
        assert data == {"teams": [{"id": "t1"}], "connection_id": cid}

    def test_a_connection_that_needs_reconnecting_gives_nothing(self, pg_conn):
        cid = _linear(pg_conn, status="reconnect_needed")
        with self._readonly(pg_conn) as worker:
            assert worker._with_connection_credentials({"teams": [{"id": "t1"}]}, cid) is None

    def test_scheduled_sync_reads_with_the_connection(self, pg_conn):
        cid = _linear(pg_conn)
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, remote_data) "
            "VALUES ('alice', 'Linear · Engineering', 'linear', 'daily', CAST(:c AS uuid), "
            "'{\"teams\": [{\"id\": \"t1\"}]}')"
        ), {"c": cid})
        with self._readonly(pg_conn) as worker, patch.object(worker, "sync", return_value={"status": "success"}) as sync:
            counts = worker.sync_worker(MagicMock(), "daily")
        assert counts["sync_success"] == 1
        args, kwargs = sync.call_args
        assert args[1] == {"teams": [{"id": "t1"}]}
        assert args[4] == "linear"
        assert kwargs["connection_id"] == cid

    def test_scheduled_sync_skips_a_source_paused_for_reconnect(self, pg_conn):
        cid = _linear(pg_conn, status="reconnect_needed")
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, remote_data, metadata) "
            "VALUES ('alice', 'Linear', 'linear', 'daily', CAST(:c AS uuid), '{\"teams\": [{\"id\": \"t1\"}]}', "
            "'{\"sync_state\": \"paused_reconnect\"}')"
        ), {"c": cid})
        with self._readonly(pg_conn) as worker, patch.object(worker, "sync") as sync:
            counts = worker.sync_worker(MagicMock(), "daily")
        sync.assert_not_called()
        assert counts["sync_skipped"] == 1

    def test_scheduled_sync_skips_a_source_whose_connection_was_removed(self, pg_conn):
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, remote_data) "
            "VALUES ('alice', 'Linear', 'linear', 'daily', '{\"teams\": [{\"id\": \"t1\"}]}')"
        ))
        with self._readonly(pg_conn) as worker, patch.object(worker, "sync") as sync:
            counts = worker.sync_worker(MagicMock(), "daily")
        sync.assert_not_called()
        assert counts["sync_skipped"] == 1

    def test_a_lost_sign_in_fails_the_ingest_without_retrying_forever(self):
        from docsgpt import worker

        loader = MagicMock()
        loader.load_data.side_effect = service.ConnectionUnavailable("expired", connection_id="c-1")
        task = MagicMock()
        task.request.retries = 1
        with patch.object(worker.RemoteCreator, "create_loader", return_value=loader), patch.object(
            worker, "_with_connection_credentials", return_value={"teams": [{"id": "t1"}], "connection_id": "c-1"},
        ), patch.object(worker, "publish_user_event") as publish:
            with pytest.raises(service.ConnectionUnavailable):
                worker.remote_worker(task, {"teams": [{"id": "t1"}]}, "Linear", "alice", "linear",
                                     connection_id="c-1")
        assert publish.call_args.args[1] == "source.ingest.failed"


def test_the_picker_lists_are_capped(monkeypatch):
    monkeypatch.setattr(linear, "MAX_PICKER_ITEMS", 2)
    session = FakeLinear({
        "list_teams": {"teams": [{"id": f"t{n}", "name": f"Team {n}"} for n in range(5)]},
        "list_projects": {"projects": []},
    })
    assert len(asyncio.run(linear.list_workspace(session))["teams"]) == 2
