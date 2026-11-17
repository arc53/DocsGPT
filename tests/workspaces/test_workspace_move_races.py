"""A move against a concurrent write: each runs whole before or after the other, never in between.

Each test commits on two connections: one holds its write open while the other
starts, so the second must wait for the first and then see what it committed.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import pytest
from sqlalchemy import text

from docsgpt.api.user.folders.service import FolderError, create_folder
from docsgpt.workspaces.move import MoveError, apply_move, parse_move_request
from tests.workspaces.move_support import body, folder, owner_of, plan, team


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
