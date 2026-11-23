"""A team agent's publishing, key and outside access follow the team's outside policy, not a fixed Admin rule.

Under ``admins`` (the default) an Editor's copy of a template lands as a draft without a key; under ``editors``
the Editor publishes it with a key and may take over paying for outside access; under ``locked`` an Admin still
publishes, but no key is made and nobody, the Owner included, may take over.
"""

from __future__ import annotations

from flask import Flask
from sqlalchemy import text

from tests.api.user.test_outside_access_take_over import _agent, _take_over
from tests.api.user.test_workspace_followups import ADMIN, EDITOR, OWNER, _adopt, _team, _template


def _policy(conn, tid, policy):
    conn.execute(text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": tid})


class TestAdoptingFollowsThePolicy:
    def test_by_default_an_editors_copy_is_a_draft_without_a_key(self, pg_conn):
        tid, _ = _team(pg_conn)
        row = _adopt(pg_conn, EDITOR, _template(pg_conn), tid)
        assert row["status"] == "draft" and not row.get("key")

    def test_editors_too_lets_the_editor_publish_it_with_a_key(self, pg_conn):
        tid, _ = _team(pg_conn)
        _policy(pg_conn, tid, "editors")
        row = _adopt(pg_conn, EDITOR, _template(pg_conn), tid)
        assert row["status"] == "published" and row.get("key")
        assert row["access_payer_id"] == EDITOR

    def test_locked_publishes_for_an_admin_without_a_key(self, pg_conn):
        tid, _ = _team(pg_conn)
        _policy(pg_conn, tid, "locked")
        row = _adopt(pg_conn, ADMIN, _template(pg_conn), tid)
        assert row["status"] == "published" and not row.get("key")
        assert not row.get("access_payer_id")


class TestTakingOverFollowsThePolicy:
    def _members(self, conn, tid):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository

        # The take-over helpers name these people: adam pays, eddie is an Editor.
        repo = TeamMembersRepository(conn)
        repo.add_member(tid, "adam", role="team_admin")
        repo.add_member(tid, "eddie", role="team_editor")

    def test_an_editor_takes_over_only_under_editors_too(self, pg_conn, monkeypatch):
        from docsgpt.quotas.service import QuotaService

        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, *a, **k: None))
        app = Flask(__name__)
        tid, principal = _team(pg_conn)
        self._members(pg_conn, tid)
        agent = _agent(pg_conn, principal, payer="adam")

        status, _ = _take_over(app, pg_conn, str(agent["id"]), "eddie")
        assert status == 403
        _policy(pg_conn, tid, "editors")
        status, body = _take_over(app, pg_conn, str(agent["id"]), "eddie")
        assert status == 200, body

    def test_nobody_takes_over_a_locked_teams_outside_access(self, pg_conn, monkeypatch):
        from docsgpt.quotas.service import QuotaService

        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, *a, **k: None))
        app = Flask(__name__)
        tid, principal = _team(pg_conn)
        self._members(pg_conn, tid)
        agent = _agent(pg_conn, principal, payer="adam")
        _policy(pg_conn, tid, "locked")
        status, _ = _take_over(app, pg_conn, str(agent["id"]), OWNER)
        assert status == 403
