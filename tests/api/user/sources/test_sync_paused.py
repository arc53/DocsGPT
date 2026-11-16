"""A team source's scheduled sync paused for want of a payer shows on the source listings as ``sync_paused``.

The sync worker flags the source (``metadata.sync_paused = {reason, since}``) when nobody may pay for its
scheduled sync, and clears it once someone can. Both listings (``/api/sources`` and ``/api/sources/paginated``)
carry the flag as ``sync_paused: {reason, since}``, or None, and nothing else from the metadata.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

SINCE = "2026-11-10T08:00:00+00:00"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.sources.routes.db_session", _yield), patch(
        "docsgpt.api.user.sources.routes.db_readonly", _yield
    ):
        yield


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    TeamMembersRepository(conn).add_member(tid, "alice", role="team_admin")
    TeamMembersRepository(conn).add_member(tid, "vera", role="team_viewer")
    return tid, principal_id(tid)


def _source(conn, owner, name, *, paused=None, **metadata):
    row = SourcesRepository(conn).create(name, user_id=owner, type="github", sync_frequency="daily",
                                         created_by="alice" if owner.startswith("__team__") else None)
    repo = SourcesRepository(conn)
    for key, value in metadata.items():
        repo.set_metadata_key(str(row["id"]), owner, key, value)
    if paused is not None:
        repo.set_metadata_key(str(row["id"]), owner, "sync_paused", paused)
    return str(row["id"])


def _list(app, conn, resource, path, user, team_id):
    with _patch_db(conn), app.test_request_context(path, headers={WORKSPACE_HEADER: team_id}):
        from flask import request

        request.decoded_token = {"sub": user}
        response = resource().get()
    body = response.get_json()
    rows = body["paginated"] if isinstance(body, dict) else body
    return {row["id"]: row for row in rows}


@pytest.mark.parametrize("listing", ["paginated", "combined"])
def test_a_paused_sync_shows_its_reason_and_since(app, pg_conn, listing):
    from docsgpt.api.user.sources.routes import CombinedJson, PaginatedSources

    tid, principal = _team(pg_conn)
    paused = _source(pg_conn, principal, "paused", paused={"reason": "sync_no_payer", "since": SINCE},
                     sync_state={"cursor": "secret-ish"})
    running = _source(pg_conn, principal, "running")
    resource, path = (PaginatedSources, "/api/sources/paginated") if listing == "paginated" else (
        CombinedJson, "/api/sources")

    rows = _list(app, pg_conn, resource, path, "vera", tid)

    assert rows[paused]["sync_paused"] == {"reason": "sync_no_payer", "since": SINCE}
    assert rows[running]["sync_paused"] is None
    assert "metadata" not in rows[paused] and "sync_state" not in rows[paused]


def test_a_malformed_flag_reads_as_paused_with_what_it_says(app, pg_conn):
    """A flag written by hand or by an older worker still shows; only its known keys go out."""
    from docsgpt.api.user.sources.routes import PaginatedSources

    tid, principal = _team(pg_conn)
    odd = _source(pg_conn, principal, "odd", paused={"reason": "sync_no_payer", "extra": "x"})
    junk = _source(pg_conn, principal, "junk", paused="yes")

    rows = _list(app, pg_conn, PaginatedSources, "/api/sources/paginated", "alice", tid)

    assert rows[odd]["sync_paused"] == {"reason": "sync_no_payer", "since": None}
    assert rows[junk]["sync_paused"] == {"reason": None, "since": None}
