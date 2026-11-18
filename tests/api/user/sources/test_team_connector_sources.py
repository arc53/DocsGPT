"""Sources a team reads through the team's own connection.

Only the Admin who connected a team's account creates sources from it (they alone browse it); the source is the
team's, names them as its creator and is filed in the team's tree. Editors and up may Sync now or rebuild it, which
bills whoever clicked; Admins alone change how often it syncs. While the account is paused (whoever connected it
was deactivated, left the team or lost the Admin role) nothing syncs: 409 ``connection_paused`` with the reason.
A personal connection named in a team is still refused with ``connector_personal_only``.
"""

from __future__ import annotations

import datetime
import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request
from sqlalchemy import text

from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

MODULES = (
    "docsgpt.api.user.sources.upload",
    "docsgpt.api.user.sources.routes",
    "docsgpt.api.connector.routes",
    "docsgpt.connectors.service",
)

SELECTION = {"provider": "google_drive", "file_ids": ["f1"], "folder_ids": []}


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    patches = [patch(f"{module}.{name}", _yield) for module in MODULES for name in ("db_session", "db_readonly")]
    patches.append(patch("docsgpt.quotas.service.db_readonly", _yield))
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; adam connected its Drive and ana is another Admin; eddie edits, vera views."""
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    members.add_member(tid, "alice", role="team_admin")
    for user, role in (("adam", "team_admin"), ("ana", "team_admin"), ("eddie", "team_editor"),
                       ("vera", "team_viewer")):
        members.add_member(tid, user, role=role)
    return tid


def _connection(conn, owner, connected_by=None, provider="google_drive", auth_kind="oauth"):
    return ConnectorSessionsRepository(conn).create(
        owner, provider, connector_key=provider, auth_kind=auth_kind,
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=connected_by,
    )


def _source(conn, owner, connection, *, type="connector:google_drive", remote_data=None, frequency="daily"):
    row = SourcesRepository(conn).create(
        "Drive", user_id=owner, created_by="adam" if owner.startswith("__team__") else None, type=type,
        remote_data=remote_data or SELECTION, sync_frequency=frequency,
    )
    if connection is not None:
        conn.execute(
            text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
            {"c": str(connection["id"]), "s": str(row["id"])},
        )
    return str(row["id"])


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


def _call(app, conn, resource, method, path, user, team_id=None, **kwargs):
    headers = {WORKSPACE_HEADER: team_id} if team_id else {}
    with _patch_db(conn), app.test_request_context(path, method=method, headers=headers, **kwargs):
        request.decoded_token = {"sub": user}
        return getattr(resource(), method.lower())()


def _create(app, conn, user, team_id, source, payload, folder_id=None):
    from docsgpt.api.user.sources.upload import UploadRemote

    remote = MagicMock(return_value=MagicMock(id="task-r"))
    connector = MagicMock(return_value=MagicMock(id="task-c"))
    data = {"user": user, "source": source, "name": "Drive", "data": json.dumps(payload)}
    if folder_id:
        data["folder_id"] = folder_id
    with patch("docsgpt.api.user.sources.upload.ingest_remote.apply_async", remote), patch(
        "docsgpt.api.user.sources.upload.ingest_connector_task.apply_async", connector,
    ):
        response = _call(app, conn, UploadRemote, "POST", "/api/remote", user, team_id, data=data,
                         content_type="multipart/form-data")
    return response, remote, connector


class TestCreatingFromTheTeamsConnection:
    def test_whoever_connected_it_adds_a_team_source_filed_in_the_team(self, app, pg_conn, team):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam")
        folder = FoldersRepository(pg_conn).create(principal, "Drive")

        response, _, connector = _create(
            app, pg_conn, "adam", team, "google_drive", {"connection_id": str(row["id"]), "file_ids": ["f1"]},
            folder_id=str(folder["id"]),
        )

        assert response.status_code == 200
        kwargs = connector.call_args.kwargs["kwargs"]
        assert kwargs["user"] == principal
        assert kwargs["actor_id"] == "adam"
        assert kwargs["connection_id"] == str(row["id"])
        assert kwargs["folder_id"] == str(folder["id"])

    @pytest.mark.parametrize("user", ["ana", "eddie"])
    def test_nobody_else_creates_from_it(self, app, pg_conn, team, user):
        row = _connection(pg_conn, principal_id(team), "adam")

        response, _, connector = _create(
            app, pg_conn, user, team, "google_drive", {"connection_id": str(row["id"]), "file_ids": ["f1"]},
        )

        assert response.status_code == 403
        assert response.json["error"] == "connection_picker_owner_only"
        connector.assert_not_called()

    def test_a_personal_connection_named_in_a_team_stays_personal(self, app, pg_conn, team):
        row = _connection(pg_conn, "adam")

        response, _, connector = _create(
            app, pg_conn, "adam", team, "google_drive", {"connection_id": str(row["id"]), "file_ids": ["f1"]},
        )

        assert response.status_code == 403
        assert response.json["error"] == "connector_personal_only"
        connector.assert_not_called()

    def test_another_teams_connection_is_refused(self, app, pg_conn, team):
        other = TeamsRepository(pg_conn).create("Other", f"o-{uuid.uuid4().hex[:6]}", "adam")
        TeamMembersRepository(pg_conn).add_member(str(other["id"]), "adam", role="team_admin")
        row = _connection(pg_conn, principal_id(str(other["id"])), "adam")

        response, _, connector = _create(
            app, pg_conn, "adam", team, "google_drive", {"connection_id": str(row["id"]), "file_ids": ["f1"]},
        )

        assert response.status_code == 403
        assert response.json["error"] == "connector_personal_only"
        connector.assert_not_called()

    def test_a_connection_of_another_service_is_refused(self, app, pg_conn, team):
        row = _connection(pg_conn, principal_id(team), "adam", provider="confluence")

        response, _, connector = _create(
            app, pg_conn, "adam", team, "google_drive", {"connection_id": str(row["id"]), "file_ids": ["f1"]},
        )

        assert response.status_code == 401
        connector.assert_not_called()

    def test_a_paused_account_is_refused_with_the_reason(self, app, pg_conn, team):
        row = _connection(pg_conn, principal_id(team), "adam")
        _deactivate(pg_conn, "adam")

        response, _, connector = _create(
            app, pg_conn, "adam", team, "google_drive", {"connection_id": str(row["id"]), "file_ids": ["f1"]},
        )

        assert response.status_code == 409
        assert response.json["error"] == "connection_paused"
        assert response.json["paused_for"]["reason"] == "owner_inactive"
        connector.assert_not_called()

    def test_an_s3_source_on_the_teams_keys(self, app, pg_conn, team):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam", provider="s3", auth_kind="api_key")

        response, remote, _ = _create(
            app, pg_conn, "adam", team, "s3", {"connection_id": str(row["id"]), "bucket": "b"},
        )

        assert response.status_code == 200
        kwargs = remote.call_args.kwargs["kwargs"]
        assert kwargs["user"] == principal
        assert kwargs["actor_id"] == "adam"
        assert kwargs["connection_id"] == str(row["id"])

    def test_another_admin_cannot_use_the_teams_keys(self, app, pg_conn, team):
        row = _connection(pg_conn, principal_id(team), "adam", provider="s3", auth_kind="api_key")

        response, remote, _ = _create(app, pg_conn, "ana", team, "s3", {"connection_id": str(row["id"]), "bucket": "b"})

        assert response.status_code == 403
        assert response.json["error"] == "connection_picker_owner_only"
        remote.assert_not_called()

    def test_keys_pasted_in_a_team_still_stay_personal(self, app, pg_conn, team):
        response, remote, _ = _create(
            app, pg_conn, "adam", team, "s3", {"aws_access_key_id": "AKIA", "aws_secret_access_key": "x", "bucket": "b"},
        )

        assert response.status_code == 403
        assert response.json["error"] == "connector_personal_only"
        remote.assert_not_called()


def _sync_now(app, conn, user, source_id, body=None):
    from docsgpt.api.connector.routes import ConnectorSync

    delay = MagicMock(return_value=MagicMock(id="task-s"))
    with patch("docsgpt.api.connector.routes.ingest_connector_task.delay", delay):
        response = _call(app, conn, ConnectorSync, "POST", "/api/connectors/sync", user,
                         json={"source_id": source_id, **(body or {})})
    return response, delay


class TestSyncNow:
    def test_an_editors_sync_runs_as_the_team_and_bills_the_editor(self, app, pg_conn, team):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam")
        src = _source(pg_conn, principal, row)

        response, delay = _sync_now(app, pg_conn, "eddie", src)

        assert response.status_code == 200
        kwargs = delay.call_args.kwargs
        assert kwargs["user"] == principal
        assert kwargs["actor_id"] == "eddie"
        assert kwargs["connection_id"] == str(row["id"])

    def test_a_named_connection_is_ignored(self, app, pg_conn, team):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam")
        mine = _connection(pg_conn, "adam")
        src = _source(pg_conn, principal, row)

        response, delay = _sync_now(app, pg_conn, "adam", src, {"connection_id": str(mine["id"])})

        assert response.status_code == 200
        assert delay.call_args.kwargs["connection_id"] == str(row["id"])

    def test_a_viewer_cannot_sync(self, app, pg_conn, team):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        response, delay = _sync_now(app, pg_conn, "vera", src)

        assert response.status_code == 403
        delay.assert_not_called()

    @pytest.mark.parametrize("pause, reason", [
        ("left", "payer_left"), ("demoted", "payer_left"), ("deactivated", "owner_inactive"),
    ])
    def test_a_paused_account_is_refused(self, app, pg_conn, team, pause, reason):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        if pause == "deactivated":
            _deactivate(pg_conn, "adam")
        else:
            _set_role(pg_conn, team, "adam", None if pause == "left" else "team_editor")

        response, delay = _sync_now(app, pg_conn, "eddie", src)

        assert response.status_code == 409
        assert response.json["error"] == "connection_paused"
        assert response.json["paused_for"]["reason"] == reason
        delay.assert_not_called()

    def test_out_of_allowance_does_not_stop_someone_else_paying(self, app, pg_conn, team):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        _out_of_allowance(pg_conn, "adam")

        response, delay = _sync_now(app, pg_conn, "eddie", src)

        assert response.status_code == 200
        assert delay.call_args.kwargs["actor_id"] == "eddie"

    def test_a_team_source_whose_connection_was_removed(self, app, pg_conn, team):
        src = _source(pg_conn, principal_id(team), None)

        response, delay = _sync_now(app, pg_conn, "eddie", src)

        assert response.status_code == 409
        assert response.json["code"] == "connection_missing"
        delay.assert_not_called()


def _reingest(app, conn, user, source_id):
    from docsgpt.api.user.sources.routes import ReingestSource

    apply_async = MagicMock(return_value=MagicMock(id="task-r"))
    with patch("docsgpt.api.user.sources.routes.ingest_connector_task.apply_async", apply_async):
        response = _call(app, conn, ReingestSource, "POST", "/api/sources/reingest", user,
                         json={"source_id": source_id})
    return response, apply_async


class TestRebuild:
    def test_an_editors_rebuild_bills_the_editor(self, app, pg_conn, team):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        response, apply_async = _reingest(app, pg_conn, "eddie", src)

        assert response.status_code == 200
        kwargs = apply_async.call_args.kwargs["kwargs"]
        assert kwargs["user"] == principal
        assert kwargs["actor_id"] == "eddie"

    def test_a_paused_account_is_refused(self, app, pg_conn, team):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        _set_role(pg_conn, team, "adam", None)

        response, apply_async = _reingest(app, pg_conn, "eddie", src)

        assert response.status_code == 409
        assert response.json["error"] == "connection_paused"
        apply_async.assert_not_called()


class TestRemoteSourceOnTheTeamsKeys:
    def _sync(self, app, conn, user, source_id):
        from docsgpt.api.user.sources.routes import SyncSource

        delay = MagicMock(return_value=MagicMock(id="task-s"))
        with patch("docsgpt.api.user.sources.routes.sync_source.delay", delay):
            response = _call(app, conn, SyncSource, "POST", "/api/sync_source", user, json={"source_id": source_id})
        return response, delay

    def test_an_editors_sync_bills_the_editor(self, app, pg_conn, team):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam", provider="s3", auth_kind="api_key")
        src = _source(pg_conn, principal, row, type="s3", remote_data={"bucket": "b"})

        response, delay = self._sync(app, pg_conn, "eddie", src)

        assert response.status_code == 200
        assert delay.call_args.kwargs["actor_id"] == "eddie"

    def test_a_paused_account_is_refused(self, app, pg_conn, team):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam", provider="s3", auth_kind="api_key")
        src = _source(pg_conn, principal, row, type="s3", remote_data={"bucket": "b"})
        _set_role(pg_conn, team, "adam", None)

        response, delay = self._sync(app, pg_conn, "eddie", src)

        assert response.status_code == 409
        assert response.json["error"] == "connection_paused"
        delay.assert_not_called()


class TestSyncFrequency:
    def _set(self, app, conn, user, source_id):
        from docsgpt.api.user.sources.routes import ManageSync

        return _call(app, conn, ManageSync, "POST", "/api/manage_sync", user,
                     json={"source_id": source_id, "sync_frequency": "weekly"})

    def test_an_editor_cannot_change_it(self, app, pg_conn, team):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        response = self._set(app, pg_conn, "eddie", src)

        assert response.status_code == 403
        assert response.json["error"] == "connection_admin_required"
        assert SourcesRepository(pg_conn).get_by_id(src)["sync_frequency"] == "daily"

    def test_any_admin_can(self, app, pg_conn, team):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        response = self._set(app, pg_conn, "ana", src)

        assert response.status_code == 200
        assert SourcesRepository(pg_conn).get_by_id(src)["sync_frequency"] == "weekly"

    def test_an_editor_still_changes_a_team_website(self, app, pg_conn, team):
        src = _source(pg_conn, principal_id(team), None, type="website",
                      remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]})

        response = self._set(app, pg_conn, "eddie", src)

        assert response.status_code == 200


def _listed(app, conn, user, team_id, listing):
    from docsgpt.api.user.sources.routes import CombinedJson, PaginatedSources

    resource, path = (PaginatedSources, "/api/sources/paginated") if listing == "paginated" else (
        CombinedJson, "/api/sources")
    response = _call(app, conn, resource, "GET", path, user, team_id)
    body = response.get_json()
    rows = body["paginated"] if isinstance(body, dict) else body
    return {row["id"]: row for row in rows}


@pytest.mark.parametrize("listing", ["paginated", "combined"])
class TestListedPause:
    def test_an_account_pause_shows_on_every_source_of_the_connection(self, app, pg_conn, team, listing):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam")
        scheduled = _source(pg_conn, principal, row)
        manual = _source(pg_conn, principal, row, frequency="never")
        _set_role(pg_conn, team, "adam", None)

        rows = _listed(app, pg_conn, "vera", team, listing)

        expected = {"reason": "payer_left", "until": None, "left_team": True, "connection_id": str(row["id"])}
        assert rows[scheduled]["sync_paused"] == expected
        assert rows[manual]["sync_paused"] == expected

    def test_out_of_allowance_shows_only_where_a_sync_is_scheduled(self, app, pg_conn, team, listing):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam")
        scheduled = _source(pg_conn, principal, row)
        manual = _source(pg_conn, principal, row, frequency="never")
        _out_of_allowance(pg_conn, "adam")

        rows = _listed(app, pg_conn, "vera", team, listing)

        assert rows[scheduled]["sync_paused"]["reason"] == "payer_out_of_allowance"
        assert rows[scheduled]["sync_paused"]["until"]
        assert rows[manual]["sync_paused"] is None

    def test_a_usable_connection_shows_nothing(self, app, pg_conn, team, listing):
        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))

        rows = _listed(app, pg_conn, "vera", team, listing)

        assert rows[src]["sync_paused"] is None

    def test_another_team_it_is_shared_with_does_not_see_the_accounts_pause(self, app, pg_conn, team, listing):
        """Why a team's account is paused, and which connection, stay in that team."""
        from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository

        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        _set_role(pg_conn, team, "adam", None)
        other = str(TeamsRepository(pg_conn).create("QA", f"qa-{uuid.uuid4().hex[:6]}", "quinn")["id"])
        TeamMembersRepository(pg_conn).add_member(other, "quinn", role="team_admin")
        TeamItemSharesRepository(pg_conn).share(team, other, "source", src, "alice")

        rows = _listed(app, pg_conn, "quinn", other, listing)

        assert src in rows
        assert rows[src]["sync_paused"] is None


@pytest.mark.parametrize("listing", ["paginated", "combined"])
class TestListedConnection:
    def test_the_team_sees_which_connection_its_source_syncs_from(self, app, pg_conn, team, listing):
        principal = principal_id(team)
        row = _connection(pg_conn, principal, "adam")
        src = _source(pg_conn, principal, row)

        rows = _listed(app, pg_conn, "vera", team, listing)

        assert rows[src]["connectionId"] == str(row["id"])

    def test_another_team_it_is_shared_with_does_not_see_the_connection(self, app, pg_conn, team, listing):
        from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository

        principal = principal_id(team)
        src = _source(pg_conn, principal, _connection(pg_conn, principal, "adam"))
        other = str(TeamsRepository(pg_conn).create("QA", f"qa-{uuid.uuid4().hex[:6]}", "quinn")["id"])
        TeamMembersRepository(pg_conn).add_member(other, "quinn", role="team_admin")
        TeamItemSharesRepository(pg_conn).share(team, other, "source", src, "alice")

        rows = _listed(app, pg_conn, "quinn", other, listing)

        assert src in rows
        assert rows[src]["connectionId"] is None

    def test_a_teammate_does_not_see_the_connection_of_a_personal_source_shared_with_them(
        self, app, pg_conn, team, listing,
    ):
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository

        src = _source(pg_conn, "adam", _connection(pg_conn, "adam"))
        TeamResourceGrantsRepository(pg_conn).grant(team, "source", src, "adam", "adam")

        rows = _listed(app, pg_conn, "eddie", None, listing)

        assert src in rows
        assert rows[src]["connectionId"] is None


class TestUsageTab:
    def test_a_paused_connection_is_listed_with_who_pays(self, pg_conn, team, monkeypatch):
        from docsgpt.api.user.teams.usage import paused_items

        @contextmanager
        def _same():
            yield pg_conn

        monkeypatch.setattr("docsgpt.quotas.service.db_readonly", _same)
        principal = principal_id(team)
        paused = ConnectorSessionsRepository(pg_conn).create(
            principal, "google_drive", connector_key="google_drive", auth_kind="oauth",
            account_label="lena@example.com", display_name="Team Drive", connected_by="adam",
        )
        _connection(pg_conn, principal, "ana")
        _set_role(pg_conn, team, "adam", None)

        items = [item for item in paused_items(pg_conn, team) if item["type"] == "connection"]

        assert items == [{
            "type": "connection",
            "id": str(paused["id"]),
            "name": "Team Drive",
            "connector_key": "google_drive",
            "paused_for": {"reason": "payer_left", "until": None, "left_team": True},
            "paid_by": {"user_id": "adam", "label": "adam"},
        }]
