"""``GET /api/drafter/agent_gaps``: an agent's gap summary for the drawer's first screen."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.drafter.gaps import DAYS, NEEDED
from tests.drafter import insights_seed as seed


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _insights_on(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    monkeypatch.setattr("docsgpt.decisions.available", lambda: True)


@contextmanager
def _as(conn, user):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.storage.db.session.db_readonly", _yield), patch(
        "docsgpt.app.handle_auth", return_value={"sub": user}
    ), patch("docsgpt.app.resolve_roles", return_value=["user"]):
        yield


def _get(client, conn, user, agent_id):
    query = f"?agent_id={agent_id}" if agent_id else ""
    with _as(conn, user):
        return client.get(f"/api/drafter/agent_gaps{query}")


def _share(conn, agent_id, owner, member, level):
    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    team = str(TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)["id"])
    TeamMembersRepository(conn).add_member(team, member)
    TeamResourceGrantsRepository(conn).grant(team, "agent", agent_id, owner, owner, access_level=level)


@pytest.mark.unit
class TestAgentGapsRoute:
    def test_the_owner_and_an_editor_get_the_summary(self, client, pg_conn):
        bot = seed.agent(pg_conn)
        aid = str(bot["id"])
        for _ in range(NEEDED):
            seed.turn(pg_conn, aid, gap={"docs missing": 0.9})
        body = _get(client, pg_conn, "owner", aid).get_json()
        assert body == {"available": True, "reason": None, "conversations": NEEDED, "needed": NEEDED, "days": DAYS,
                        "rows": [{"topic": None, "gap_type": "docs missing", "expected": 9, "turns": NEEDED,
                                  "previous": None}]}
        _share(pg_conn, aid, "owner", "ed", "editor")
        assert _get(client, pg_conn, "ed", aid).get_json() == body

    def test_a_viewer_or_a_stranger_gets_404(self, client, pg_conn):
        bot = seed.agent(pg_conn)
        _share(pg_conn, str(bot["id"]), "owner", "viewer", "viewer")
        assert _get(client, pg_conn, "viewer", str(bot["id"])).status_code == 404
        assert _get(client, pg_conn, "stranger", str(bot["id"])).status_code == 404
        assert _get(client, pg_conn, "owner", str(uuid.uuid4())).status_code == 404

    def test_needs_an_agent_id(self, client, pg_conn):
        assert _get(client, pg_conn, "owner", None).status_code == 400

    def test_disabled_drafter(self, client, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DRAFTER_ENABLED", False)
        body = _get(client, pg_conn, "owner", str(seed.agent(pg_conn)["id"])).get_json()
        assert body["available"] is False and body["reason"] == "disabled" and body["rows"] == []

    def test_no_session_is_401_and_an_access_token_403(self, client):
        from docsgpt.api.pat.tokens import expand_scopes, SCOPES

        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/drafter/agent_gaps?agent_id=x").status_code == 401
        claims = {"sub": "alice", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
                  "scopes": sorted(expand_scopes(list(SCOPES))), "resource_filter": {}}
        with patch("docsgpt.app.handle_auth", return_value=claims):
            assert client.get("/api/drafter/agent_gaps?agent_id=x").status_code == 403
