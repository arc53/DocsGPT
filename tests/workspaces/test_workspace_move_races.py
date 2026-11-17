"""A move against a concurrent write: each runs whole before or after the other, never in between.

Each test commits on two connections: one holds its write open while the other
starts, so the second must wait for the first and then see what it committed.
"""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack, contextmanager
from typing import Callable
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.folders.service import FolderError, create_folder
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.workspaces.move import MoveError, apply_move, parse_move_request
from tests.workspaces.move_support import agent, body, folder, owner_of, plan, source, team


def _waiting_on_advisory_lock(engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND wait_event = 'advisory' "
            "AND datname = current_database()"
        )).scalar())


def _race(engine, first: Callable, second: Callable) -> dict:
    """Run ``first`` in an open transaction, start ``second`` on its own, then commit ``first``.

    Returns:
        dict: ``second``'s ``result`` or ``error``.
    """
    out: dict = {}

    def run_second() -> None:
        try:
            with engine.begin() as conn:
                out["result"] = second(conn)
        except Exception as err:  # noqa: BLE001 - the test reads what the second action raised
            out["error"] = err

    with engine.begin() as conn:
        first(conn)
        thread = threading.Thread(target=run_second)
        thread.start()
        # Give the second action until it waits on a lock or finishes (the bug: it never waits).
        deadline = time.monotonic() + 10
        while thread.is_alive() and not _waiting_on_advisory_lock(engine) and time.monotonic() < deadline:
            time.sleep(0.02)
    thread.join(10)
    assert not thread.is_alive()
    return out


@pytest.mark.fresh_db
class TestFolderCreatedDuringAMove:
    def test_a_child_created_while_its_parent_moves_is_planned_or_refused_never_left_behind(self, pg_engine):
        with pg_engine.begin() as conn:
            tid, principal = team(conn)
            parent = folder(conn, "eddie", "Project")
            request = body(tid, [("folder", parent)])
            fingerprint = plan(conn, "eddie", request)["fingerprint"]
        made: dict = {}

        def create_child(conn) -> None:
            made["id"] = str(create_folder(conn, "eddie", "source", "Late", parent_id=parent)["id"])

        def move(conn):
            return apply_move(conn, "eddie", parse_move_request({**request, "fingerprint": fingerprint}))

        out = _race(pg_engine, create_child, move)

        # The move waited for the child and planned again, so the plan it was given is stale.
        assert isinstance(out.get("error"), MoveError), out
        assert out["error"].code == "move_plan_changed"
        fresh = out["error"].extra["plan"]
        assert ("folder", made["id"]) in {(m["type"], m["id"]) for m in fresh["moves_with"]}
        with pg_engine.begin() as conn:
            assert owner_of(conn, "folder", parent) == "eddie"
            apply_move(conn, "eddie", parse_move_request({**request, "fingerprint": fresh["fingerprint"]}))
            assert (owner_of(conn, "folder", parent), owner_of(conn, "folder", made["id"])) == (principal, principal)

    def test_a_child_created_after_the_move_started_finds_its_parent_gone(self, pg_engine):
        with pg_engine.begin() as conn:
            tid, principal = team(conn)
            parent = folder(conn, "eddie", "Project")
            request = body(tid, [("folder", parent)])
            fingerprint = plan(conn, "eddie", request)["fingerprint"]

        def move(conn) -> None:
            apply_move(conn, "eddie", parse_move_request({**request, "fingerprint": fingerprint}))

        out = _race(pg_engine, move, lambda conn: create_folder(conn, "eddie", "source", "Late", parent_id=parent))

        assert isinstance(out.get("error"), FolderError), out
        assert out["error"].code == "folder_not_found"
        with pg_engine.connect() as conn:
            assert owner_of(conn, "folder", parent) == principal
            assert conn.execute(text("SELECT count(*) FROM folders WHERE user_id = 'eddie'")).scalar() == 0


_ROUTE_MODULES = ("docsgpt.api.user.agents.routes", "docsgpt.api.user.agents.sharing",
                  "docsgpt.api.user.agents.webhooks", "docsgpt.api.user.workflows.routes")


@contextmanager
def _routes_on(conn_for: Callable):
    """Point the agent routes' ``db_session`` and ``db_readonly`` at ``conn_for()``, a context manager."""
    import importlib

    with ExitStack() as stack:
        for name in _ROUTE_MODULES:
            module = importlib.import_module(name)
            for attr in ("db_session", "db_readonly"):
                if hasattr(module, attr):
                    stack.enter_context(patch(f"{name}.{attr}", conn_for))
        yield


def _call(resource_cls, method: str, path: str, user: str, *, args: tuple = (), **kwargs):
    app = Flask(__name__)
    with app.test_request_context(path, method=method.upper(), **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        resp = getattr(resource_cls(), method)(*args)
    return (resp[1], resp[0]) if isinstance(resp, tuple) else (resp.status_code, resp.get_json())


@pytest.mark.fresh_db
class TestOutsideAccessTurnedOnDuringAMove:
    """A move in checks once that no agent with a key, link or webhook would use what it moves; turning one on
    checks once that the agent uses no one else's item. Run together, each must see the other's result."""

    def _setup(self, engine) -> tuple:
        with engine.begin() as conn:
            tid, principal = team(conn)
            src = source(conn, "eddie")
            moving = agent(conn, "eddie", "Moving", source_id=src)
            # Eddie's other agent on the same source: a move leaves it behind, fine while nothing reaches it
            # from outside.
            staying = agent(conn, "eddie", "Staying", source_id=src, status="published")
            request = body(tid, [("agent", moving)])
            fingerprint = plan(conn, "eddie", request)["fingerprint"]
        return tid, principal, src, staying, request, fingerprint

    def test_a_public_link_turned_on_while_a_move_runs_sees_the_moved_source_and_is_refused(self, pg_engine):
        from docsgpt.api.user.agents.sharing import ShareAgent

        tid, principal, src, staying, request, fingerprint = self._setup(pg_engine)

        def move(conn) -> None:
            apply_move(conn, "eddie", parse_move_request({**request, "fingerprint": fingerprint}))

        def share(_conn):
            return _call(ShareAgent, "put", "/api/share_agent", "eddie", json={"id": staying, "shared": True})

        with _routes_on(pg_engine.begin):
            out = _race(pg_engine, move, share)

        assert "error" not in out, out
        status, payload = out["result"]
        assert status == 403, payload
        with pg_engine.connect() as conn:
            assert owner_of(conn, "source", src) == principal
            assert not AgentsRepository(conn).get_by_id(staying).get("shared")

    def test_a_move_after_a_webhook_was_turned_on_sees_it_and_is_refused(self, pg_engine):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        tid, principal, src, staying, request, fingerprint = self._setup(pg_engine)

        def webhook(conn) -> None:
            @contextmanager
            def held():
                yield conn

            with _routes_on(held):
                status, payload = _call(AgentWebhook, "get", "/api/agent_webhook", "eddie",
                                        query_string={"id": staying})
            assert status == 200, payload

        def move(conn):
            return apply_move(conn, "eddie", parse_move_request({**request, "fingerprint": fingerprint}))

        out = _race(pg_engine, webhook, move)

        # The move waited for the webhook, so its plan now names the agent as reachable from outside.
        assert isinstance(out.get("error"), MoveError), out
        assert out["error"].code == "move_plan_changed"
        fresh = out["error"].extra["plan"]
        assert {a["id"]: a["published"] for a in fresh["borrowing_agents"]}[staying] is True
        with pg_engine.begin() as conn, pytest.raises(MoveError) as err:
            apply_move(conn, "eddie", parse_move_request({**request, "fingerprint": fresh["fingerprint"]}))
        assert err.value.code == "move_would_borrow"
        with pg_engine.connect() as conn:
            assert owner_of(conn, "source", src) == "eddie"


class TestEveryOutsideAccessPathHoldsTheMoveLock:
    """Each way to turn on a key, link or webhook, or to save refs on an agent that has one, holds the
    owner's move lock until it commits."""

    @staticmethod
    def _holds(conn, owner: str) -> bool:
        return bool(conn.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 1 "
            "AND ((classid::bigint << 32) | objid::bigint) = hashtextextended('owner-items:' || :o, 0)"
        ), {"o": owner}).scalar())

    def _call_on(self, conn, *call_args, **kwargs) -> tuple:
        @contextmanager
        def held():
            yield conn

        with _routes_on(held):
            return _call(*call_args, **kwargs)

    def test_the_lock_is_this_owners(self, pg_conn):
        from docsgpt.workspaces.locks import lock_owner_items

        lock_owner_items(pg_conn, "eddie")
        assert self._holds(pg_conn, "eddie")
        assert not self._holds(pg_conn, "adam")

    def test_creating_an_agent_with_a_key(self, pg_conn):
        from docsgpt.api.user.agents.routes import CreateAgent

        status, payload = self._call_on(pg_conn, CreateAgent, "post", "/api/create_agent", "eddie", json={
            "name": "Bot", "description": "d", "agent_type": "classic", "status": "published", "chunks": 6,
            "retriever": "classic", "prompt_id": "default", "source": source(pg_conn, "eddie"),
        })
        assert status == 201, payload
        assert payload["key"]
        assert self._holds(pg_conn, "eddie")

    def test_publishing_an_agent(self, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent

        ag = agent(pg_conn, "eddie", agent_type="classic", chunks=6, description="d")
        status, payload = self._call_on(pg_conn, UpdateAgent, "put", f"/api/update_agent/{ag}", "eddie",
                                        args=(ag,), json={"status": "published"})
        assert status == 200, payload
        assert self._holds(pg_conn, "eddie")

    def test_saving_refs_on_an_agent_with_a_webhook(self, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent

        ag = agent(pg_conn, "eddie", agent_type="classic", chunks=6, description="d",
                   incoming_webhook_token="w-move-lock")
        status, payload = self._call_on(pg_conn, UpdateAgent, "put", f"/api/update_agent/{ag}", "eddie",
                                        args=(ag,), json={"sources": [source(pg_conn, "eddie")]})
        assert status == 200, payload
        assert self._holds(pg_conn, "eddie")

    def test_saving_the_graph_of_a_workflow_whose_agent_has_a_key(self, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail
        from tests.api.user.test_resource_sponsors import _wf_body
        from tests.workspaces.move_support import workflow

        wid = workflow(pg_conn, "eddie")
        agent(pg_conn, "eddie", agent_type="workflow", workflow_id=wid, key="k-move-lock", status="published")
        status, payload = self._call_on(pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", "eddie",
                                        args=(wid,), json=_wf_body(source=source(pg_conn, "eddie")))
        assert status == 200, payload
        assert self._holds(pg_conn, "eddie")

    def test_turning_on_a_public_link(self, pg_conn):
        from docsgpt.api.user.agents.sharing import ShareAgent

        ag = agent(pg_conn, "eddie", status="published")
        status, payload = self._call_on(pg_conn, ShareAgent, "put", "/api/share_agent", "eddie",
                                        json={"id": ag, "shared": True})
        assert status == 200, payload
        assert self._holds(pg_conn, "eddie")

    def test_turning_on_a_webhook(self, pg_conn):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        ag = agent(pg_conn, "eddie", status="published")
        status, payload = self._call_on(pg_conn, AgentWebhook, "get", "/api/agent_webhook", "eddie",
                                        query_string={"id": ag})
        assert status == 200, payload
        assert self._holds(pg_conn, "eddie")

    def test_a_draft_save_nobody_reaches_from_outside_takes_no_lock(self, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent

        ag = agent(pg_conn, "eddie", agent_type="classic", chunks=6, description="d")
        status, payload = self._call_on(pg_conn, UpdateAgent, "put", f"/api/update_agent/{ag}", "eddie",
                                        args=(ag,), json={"name": "Renamed"})
        assert status == 200, payload
        assert not self._holds(pg_conn, "eddie")
