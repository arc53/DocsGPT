"""Why a team's connection is paused, and who pays for its scheduled syncs, derived on every read.

The person who connected a team's account (``connected_by``) pays for its scheduled syncs. The account is not used
at all while they are deactivated (``owner_inactive``), left the team or lost the Admin role (``payer_left``), or
nobody is recorded (``no_payer``); scheduled syncs alone also wait while they are out of allowance.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.quotas.pause import ACCOUNT_PAUSES, Pause, connection_pause
from docsgpt.quotas.payer import connection_payer
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
NEXT_MONTH = datetime(2026, 12, 2, 12, tzinfo=timezone.utc)
RESETS_AT = datetime(2026, 12, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn(pg_conn, monkeypatch):
    @contextmanager
    def _readonly():
        yield pg_conn

    monkeypatch.setattr("docsgpt.quotas.service.db_readonly", _readonly)
    monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "month")
    return pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _connection(conn, owner, connected_by=None):
    return ConnectorSessionsRepository(conn).create(
        owner, "google_drive", connector_key="google_drive", auth_kind="oauth",
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=connected_by,
    )


def _deactivate(conn, user_id):
    UsersRepository(conn).upsert(user_id)
    conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": user_id})


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _out_of_allowance(conn, user_id):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, token_limit=100)
    TokenUsageRepository(conn).insert(
        user_id=user_id, api_key="k", prompt_tokens=150, timestamp=NOW - timedelta(days=1)
    )


def test_account_pauses_are_the_three_strongest():
    assert ACCOUNT_PAUSES == ("owner_inactive", "payer_left", "no_payer")


def test_a_personal_connection_is_never_paused_for_a_payer(conn):
    row = _connection(conn, "lena")
    _deactivate(conn, "lena")
    _out_of_allowance(conn, "lena")

    assert connection_pause(conn, row, allowance=True, now=NOW) is None
    assert connection_payer(conn, row) == "lena"


def test_a_usable_team_connection_is_not_paused_and_bills_who_connected_it(conn):
    _, principal = _team(conn)
    row = _connection(conn, principal, "adam")

    assert connection_pause(conn, row, allowance=True, now=NOW) is None
    assert connection_payer(conn, row) == "adam"


def test_a_deactivated_connector(conn):
    _, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _deactivate(conn, "adam")

    assert connection_pause(conn, row, now=NOW) == Pause("owner_inactive", "adam")
    assert connection_payer(conn, row) is None


@pytest.mark.parametrize("role", [None, "team_editor", "team_viewer"])
def test_a_connector_who_left_or_is_no_longer_an_admin(conn, role):
    team, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _set_role(conn, team, "adam", role)

    assert connection_pause(conn, row, now=NOW) == Pause("payer_left", "adam", left_team=role is None)
    assert connection_payer(conn, row) is None


def test_the_team_owner_keeps_paying_without_an_admin_row(conn):
    team, principal = _team(conn)
    row = _connection(conn, principal, "alice")
    _set_role(conn, team, "alice", None)

    assert connection_pause(conn, row, now=NOW) is None


def test_re_adding_the_connector_resumes_it_with_no_write(conn):
    team, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _set_role(conn, team, "adam", None)
    assert connection_pause(conn, row, now=NOW).reason == "payer_left"

    _set_role(conn, team, "adam", "team_admin")

    assert connection_pause(conn, row, now=NOW) is None
    assert ConnectorSessionsRepository(conn).get(str(row["id"]))["updated_at"] == row["updated_at"]


def test_a_team_row_with_nobody_recorded_has_no_payer(conn):
    _, principal = _team(conn)
    # Only a row stored before the check existed can look like this.
    row = {**_connection(conn, principal, "adam"), "connected_by": None}

    assert connection_pause(conn, row, now=NOW) == Pause("no_payer", None)
    assert connection_payer(conn, row) is None


def test_the_allowance_only_counts_when_asked(conn):
    _, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _out_of_allowance(conn, "adam")

    # Account use (a person's Sync now, a tool call, the picker) goes on: that person pays.
    assert connection_pause(conn, row, now=NOW) is None
    assert connection_pause(conn, row, allowance=True, now=NOW) == Pause("payer_out_of_allowance", "adam", RESETS_AT)
    assert connection_pause(conn, row, allowance=True, now=NEXT_MONTH) is None
    # Out of allowance is not an account pause: they still pay once it resets.
    assert connection_payer(conn, row) == "adam"


def test_deactivation_comes_before_a_lost_role_and_the_allowance(conn):
    team, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _set_role(conn, team, "adam", None)
    _deactivate(conn, "adam")
    _out_of_allowance(conn, "adam")

    assert connection_pause(conn, row, allowance=True, now=NOW).reason == "owner_inactive"


def test_a_lost_role_comes_before_the_allowance(conn):
    team, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _set_role(conn, team, "adam", "team_editor")
    _out_of_allowance(conn, "adam")

    assert connection_pause(conn, row, allowance=True, now=NOW).reason == "payer_left"


def test_the_payload_says_whether_they_left(conn):
    team, principal = _team(conn)
    row = _connection(conn, principal, "adam")
    _set_role(conn, team, "adam", None)

    assert connection_pause(conn, row, now=NOW).payload() == {"reason": "payer_left", "until": None, "left_team": True}
