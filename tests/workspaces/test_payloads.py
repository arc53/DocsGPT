"""The payload fields every workspace list shares: the envelope's ``workspace`` and each row's ``created_by``."""

from __future__ import annotations

import uuid

from docsgpt.api.user.resource_access import created_by_payload, creator_payloads
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import Workspace
from docsgpt.workspaces.principal import principal_id


def _team(conn, owner="alice", members=(("eddie", "team_editor"),)):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


class TestWorkspaceEnvelope:
    def test_personal(self):
        ws = Workspace(kind="personal", team_id=None, owner_id="bob", role="owner")
        assert ws.payload() == {"kind": "personal", "team_id": None, "role": "owner"}

    def test_team(self):
        ws = Workspace(kind="team", team_id="t1", owner_id="__team__t1", role="editor")
        assert ws.payload() == {"kind": "team", "team_id": "t1", "role": "editor"}


class TestCreatedBy:
    def test_a_team_item_names_who_added_it_even_after_they_left(self, pg_conn):
        _, principal = _team(pg_conn)
        UsersRepository(pg_conn).upsert("gone", email="gone@example.com")
        rows = [{"user_id": principal, "created_by": "gone"}]
        creators = creator_payloads(pg_conn, "eddie", rows)
        assert created_by_payload(rows[0], creators) == {"user_id": "gone", "label": "gone@example.com"}

    def test_a_person_without_an_email_is_labelled_by_id(self, pg_conn):
        _, principal = _team(pg_conn)
        rows = [{"user_id": principal, "created_by": "eddie"}]
        assert created_by_payload(rows[0], creator_payloads(pg_conn, "alice", rows)) == {
            "user_id": "eddie", "label": "eddie"
        }

    def test_own_and_teammates_personal_items_are_named(self, pg_conn):
        _team(pg_conn)
        rows = [{"user_id": "alice", "created_by": "alice"}, {"user_id": "eddie", "created_by": "eddie"}]
        creators = creator_payloads(pg_conn, "alice", rows)
        assert created_by_payload(rows[0], creators)["user_id"] == "alice"
        assert created_by_payload(rows[1], creators)["user_id"] == "eddie"

    def test_a_stranger_on_a_personal_item_stays_unnamed(self, pg_conn):
        rows = [{"user_id": "stranger", "created_by": "stranger"}]
        creators = creator_payloads(pg_conn, "alice", rows)
        assert created_by_payload(rows[0], creators) == {"user_id": None, "label": None}

    def test_a_row_with_no_creator(self, pg_conn):
        rows = [{"user_id": "alice", "created_by": None}, {"user_id": "alice"}]
        creators = creator_payloads(pg_conn, "alice", rows)
        assert creators == {}
        assert created_by_payload(rows[0], creators) is None
        assert created_by_payload(rows[1], creators) is None
