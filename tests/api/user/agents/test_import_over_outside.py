"""An import over an existing agent keeps the save-time rules for an agent that reaches outside its team.

A save that adds a tool on the team's account to an agent with a key, public link, webhook or a share with
another team is refused (409 ``team_connection_outside``), and so is one that adds a team's item to an agent
shared with someone who can't reach it (409 ``team_item_shared_outside``). An import that matches an agent by
id or slug writes the same columns as a save, so it is refused the same way and writes nothing. Real
repositories on ``pg_conn``.
"""

from __future__ import annotations

import threading
import time
import uuid
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.api.user.agents.portability import ImportAgent, ImportRefused, agent_to_yaml, apply_import
from docsgpt.connectors.team import TEAM_CONNECTION_OUTSIDE
from docsgpt.security.encryption import encrypt_json
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.locks import lock_owner_items
from tests.api.user.test_workspace_portability import ADMIN, EDITOR, _doc, _patch_db, _team, _team_ws

pytestmark = pytest.mark.integration


@pytest.fixture
def w(pg_conn):
    """Ops with a GitHub account it owns and a tool on it, a team agent, and Dev, another team."""
    return _world(pg_conn)


def _world(pg_conn) -> dict:
    """See :func:`w`."""
    tid, principal = _team(pg_conn)
    cid = str(ConnectorSessionsRepository(pg_conn).create(
        principal, "github", connector_key="github", auth_kind="oauth",
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=ADMIN,
        encrypted_credentials=encrypt_json({"access_token": "t"}, principal),
    )["id"])
    tool_id = str(UserToolsRepository(pg_conn).create(
        principal, "github", custom_name="Ops GitHub", connection_id=cid, created_by=ADMIN,
    )["id"])
    dev = str(TeamsRepository(pg_conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "dora")["id"])
    TeamMembersRepository(pg_conn).add_member(dev, "dora", role="team_admin")
    agent = str(AgentsRepository(pg_conn).create(
        principal, "Helper", "published", agent_type="classic", chunks=2, retriever="classic",
        created_by=ADMIN,
    )["id"])
    return {"ops": tid, "principal": principal, "tool": tool_id, "dev": dev, "agent": agent}


def _over(w, **spec):
    """A file that updates the fixture's agent (matched by id) and uses the team's GitHub tool."""
    spec.setdefault("name", "Helper")
    spec.setdefault("tools", [{"type": "github", "name": "Ops GitHub"}])
    return _doc(_metadata={"id": w["agent"]}, **spec)


def _tools(conn, w) -> list:
    return list(AgentsRepository(conn).get(w["agent"], w["principal"]).get("tools") or [])


class TestTeamConnection:
    def test_an_import_over_an_agent_with_a_key_cant_add_the_teams_account(self, pg_conn, w):
        AgentsRepository(pg_conn).update(w["agent"], w["principal"],
                                         {"key": f"k-{uuid.uuid4().hex}", "access_payer_id": ADMIN})
        with pytest.raises(ImportRefused) as refused:
            apply_import(pg_conn, ADMIN, _over(w), workspace=_team_ws(w["ops"], w["principal"], "admin"))

        assert refused.value.status == 409
        assert refused.value.body["error"] == TEAM_CONNECTION_OUTSIDE
        assert [t["id"] for t in refused.value.body["tools"]] == [w["tool"]]
        assert _tools(pg_conn, w) == []

    def test_an_import_over_an_agent_shared_with_another_team_cant_add_it(self, pg_conn, w):
        TeamItemSharesRepository(pg_conn).share(w["ops"], w["dev"], "agent", w["agent"], ADMIN)
        with pytest.raises(ImportRefused) as refused:
            apply_import(pg_conn, EDITOR, _over(w), workspace=_team_ws(w["ops"], w["principal"]))

        assert refused.value.body["error"] == TEAM_CONNECTION_OUTSIDE
        assert _tools(pg_conn, w) == []

    def test_one_already_on_the_agent_keeps_importing(self, pg_conn, w):
        AgentsRepository(pg_conn).update(w["agent"], w["principal"],
                                         {"tools": [w["tool"]], "key": f"k-{uuid.uuid4().hex}",
                                          "access_payer_id": ADMIN})
        result = apply_import(pg_conn, ADMIN, _over(w), workspace=_team_ws(w["ops"], w["principal"], "admin"))

        assert result["action"] == "updated"
        assert _tools(pg_conn, w) == [w["tool"]]

    def test_an_agent_inside_the_team_takes_it(self, pg_conn, w):
        result = apply_import(pg_conn, EDITOR, _over(w), workspace=_team_ws(w["ops"], w["principal"]))

        assert result["action"] == "updated"
        assert _tools(pg_conn, w) == [w["tool"]]

    def test_the_route_answers_409_and_writes_nothing(self, pg_conn, w):
        TeamItemSharesRepository(pg_conn).share(w["ops"], w["dev"], "agent", w["agent"], ADMIN)
        body = {"yaml": agent_to_yaml(_over(w, description="changed"))}
        app = Flask(__name__)
        with _patch_db(pg_conn), patch("docsgpt.api.user.agents.portability.ModelRegistry.invalidate_user"), \
                app.test_request_context("/api/import_agent", method="POST", json=body,
                                         headers={WORKSPACE_HEADER: w["ops"]}):
            from flask import request

            request.decoded_token = {"sub": EDITOR}
            resp = ImportAgent().post()

        assert resp.status_code == 409, resp.get_json()
        assert resp.get_json()["error"] == TEAM_CONNECTION_OUTSIDE
        row = AgentsRepository(pg_conn).get(w["agent"], w["principal"])
        assert row["description"] != "changed" and not row.get("tools")


class TestTeamItemSharedOutside:
    def test_another_teams_item_isnt_added_to_an_agent_shared_with_a_team_that_cant_reach_it(self, pg_conn, w):
        """Import resolves only the workspace's own items today; the rule still holds should that change."""
        from docsgpt.api.user.agents.portability import _items_before_import, _refuse_import_over

        data_tid, data_principal = _team(pg_conn, owner="dana", name="Data")
        shared_in = str(SourcesRepository(pg_conn).create("Data handbook", user_id=data_principal)["id"])
        TeamItemSharesRepository(pg_conn).share(data_tid, w["ops"], "source", shared_in, "dana")
        TeamItemSharesRepository(pg_conn).share(w["ops"], w["dev"], "agent", w["agent"], ADMIN)

        before = _items_before_import(pg_conn, w["principal"], {"action": "update", "agent_id": w["agent"]})
        with pytest.raises(ImportRefused) as refused:
            _refuse_import_over(pg_conn, before, {"extra_source_ids": [shared_in]}, EDITOR)

        assert refused.value.status == 409
        assert refused.value.body["error"] == "team_item_shared_outside"


def _waiting_on_advisory_lock(engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND wait_event = 'advisory' "
            "AND datname = current_database()"
        )).scalar())


@pytest.mark.fresh_db
class TestImportDuringAPublish:
    def test_an_import_waiting_on_a_publish_sees_the_new_key_and_is_refused(self, pg_engine):
        """A publish holds the owner lock while it mints a key; an import that waits on it reads the agent after."""
        with pg_engine.begin() as conn:
            w = _world(conn)
        out: dict = {}

        def run_import() -> None:
            try:
                with pg_engine.begin() as conn:
                    out["result"] = apply_import(
                        conn, ADMIN, _over(w), workspace=_team_ws(w["ops"], w["principal"], "admin"),
                    )
            except Exception as err:  # noqa: BLE001 - the test reads what the import raised
                out["error"] = err

        with pg_engine.begin() as conn:
            # What a publish does: take the owner lock, then give the agent a key.
            lock_owner_items(conn, w["principal"])
            AgentsRepository(conn).update(w["agent"], w["principal"],
                                          {"key": f"k-{uuid.uuid4().hex}", "access_payer_id": ADMIN})
            thread = threading.Thread(target=run_import)
            thread.start()
            deadline = time.monotonic() + 10
            while thread.is_alive() and not _waiting_on_advisory_lock(pg_engine) and time.monotonic() < deadline:
                time.sleep(0.02)
        thread.join(10)
        assert not thread.is_alive()

        assert isinstance(out.get("error"), ImportRefused), out
        assert out["error"].body["error"] == TEAM_CONNECTION_OUTSIDE
        with pg_engine.connect() as conn:
            row = AgentsRepository(conn).get(w["agent"], w["principal"])
            assert row["key"] and not row.get("tools")
