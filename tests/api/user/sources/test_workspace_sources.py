"""Sources in a team workspace.

A team's sources are owned by the team's principal and name who added them
(``created_by``). Lists and creates follow the ``X-DocsGPT-Workspace`` header;
an item by id goes by its own workspace. Creating in a team needs the Editor
role, and connector-synced sources stay personal in v1.
"""

from __future__ import annotations

import io
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.utils import safe_filename
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

MODULES = (
    "docsgpt.api.user.sources.upload",
    "docsgpt.api.user.sources.routes",
    "docsgpt.api.user.sources.from_attachments",
    "docsgpt.api.connector.routes",
)


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    patches = [patch(f"{module}.{name}", _yield) for module in MODULES for name in ("db_session", "db_readonly")]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _headers(team_id):
    return {WORKSPACE_HEADER: team_id} if team_id else {}


def _upload(app, conn, user, team_id=None, folder_id=None):
    from docsgpt.api.user.sources.upload import UploadFile

    ingest = MagicMock(return_value=MagicMock(id="task-1"))
    data = {"user": user, "name": "handbook", "file": (io.BytesIO(b"content"), "doc.txt")}
    if folder_id:
        data["folder_id"] = folder_id
    with _patch_db(conn), patch(
        "docsgpt.api.user.sources.upload.StorageCreator.get_storage", return_value=MagicMock(),
    ), patch("docsgpt.api.user.sources.upload.ingest.apply_async", ingest), app.test_request_context(
        "/api/upload", method="POST", data=data, content_type="multipart/form-data", headers=_headers(team_id),
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        response = UploadFile().post()
    return response, ingest


def _remote(app, conn, user, team_id, source, payload):
    import json

    from docsgpt.api.user.sources.upload import UploadRemote

    remote = MagicMock(return_value=MagicMock(id="task-r"))
    connector = MagicMock(return_value=MagicMock(id="task-c"))
    with _patch_db(conn), patch("docsgpt.api.user.sources.upload.ingest_remote.apply_async", remote), patch(
        "docsgpt.api.user.sources.upload.ingest_connector_task.apply_async", connector,
    ), app.test_request_context(
        "/api/remote", method="POST", headers=_headers(team_id),
        data={"user": user, "source": source, "name": "site", "data": json.dumps(payload)},
        content_type="multipart/form-data",
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        response = UploadRemote().post()
    return response, remote, connector


class TestUploadInATeam:
    def test_an_editors_upload_is_owned_by_the_team_and_names_the_uploader(self, app, pg_conn):
        tid, principal = _team(pg_conn)

        response, ingest = _upload(app, pg_conn, "eddie", tid)

        assert response.status_code == 200
        call = ingest.call_args.kwargs
        assert call["args"][3] == principal
        assert call["kwargs"]["actor_id"] == "eddie"
        # Paths follow the owner: the stored files belong to the team's source.
        assert call["kwargs"]["file_path"].startswith(f"{settings.UPLOAD_FOLDER}/{safe_filename(principal)}/")

    def test_a_viewer_cannot_upload(self, app, pg_conn):
        tid, _ = _team(pg_conn)

        response, ingest = _upload(app, pg_conn, "vera", tid)

        assert response.status_code == 403
        assert response.json["error"] == "workspace_role_required"
        ingest.assert_not_called()

    def test_someone_outside_the_team_gets_404(self, app, pg_conn):
        tid, _ = _team(pg_conn)

        response, ingest = _upload(app, pg_conn, "mallory", tid)

        assert response.status_code == 404
        assert response.json["error"] == "workspace_not_found"
        ingest.assert_not_called()

    def test_a_personal_upload_keeps_its_call_shape(self, app, pg_conn):
        response, ingest = _upload(app, pg_conn, "alice")

        assert response.status_code == 200
        call = ingest.call_args.kwargs
        assert call["args"][3] == "alice"
        assert "actor_id" not in call["kwargs"]

    def test_a_personal_folder_is_refused_for_a_team_upload(self, app, pg_conn):
        tid, _ = _team(pg_conn)
        folder = FoldersRepository(pg_conn).create("eddie", "Mine")

        response, ingest = _upload(app, pg_conn, "eddie", tid, folder_id=str(folder["id"]))

        assert response.status_code == 400
        assert response.json["error"] == "workspace_mismatch"
        ingest.assert_not_called()

    def test_a_team_folder_files_the_new_source(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        folder = FoldersRepository(pg_conn).create(principal, "Handbooks")

        response, ingest = _upload(app, pg_conn, "eddie", tid, folder_id=str(folder["id"]))

        assert response.status_code == 200
        assert ingest.call_args.kwargs["kwargs"]["folder_id"] == str(folder["id"])

    def test_a_team_folder_is_not_found_from_personal(self, app, pg_conn):
        _, principal = _team(pg_conn)
        folder = FoldersRepository(pg_conn).create(principal, "Handbooks")

        response, ingest = _upload(app, pg_conn, "eddie", folder_id=str(folder["id"]))

        assert response.status_code == 404
        ingest.assert_not_called()


class TestRemoteInATeam:
    def test_a_website_is_owned_by_the_team(self, app, pg_conn):
        tid, principal = _team(pg_conn)

        response, remote, _ = _remote(
            app, pg_conn, "eddie", tid, "website", {"entries": [{"url": "https://x.io/", "mode": "page"}]},
        )

        assert response.status_code == 200
        kwargs = remote.call_args.kwargs["kwargs"]
        assert kwargs["user"] == principal
        assert kwargs["actor_id"] == "eddie"

    def test_a_connector_source_stays_personal(self, app, pg_conn):
        tid, _ = _team(pg_conn)

        response, remote, connector = _remote(
            app, pg_conn, "eddie", tid, "google_drive", {"connection_id": str(uuid.uuid4()), "file_ids": ["f"]},
        )

        assert response.status_code == 403
        assert response.json["error"] == "connector_personal_only"
        remote.assert_not_called()
        connector.assert_not_called()

    @pytest.mark.parametrize("source", ["s3", "reddit"])
    def test_a_source_bound_to_a_connection_stays_personal(self, app, pg_conn, source):
        tid, _ = _team(pg_conn)

        response, remote, _ = _remote(
            app, pg_conn, "eddie", tid, source, {"connection_id": str(uuid.uuid4()), "bucket": "b"},
        )

        assert response.status_code == 403
        assert response.json["error"] == "connector_personal_only"
        remote.assert_not_called()

    def test_a_viewer_cannot_add_a_website(self, app, pg_conn):
        tid, _ = _team(pg_conn)

        response, remote, _ = _remote(
            app, pg_conn, "vera", tid, "website", {"entries": [{"url": "https://x.io/", "mode": "page"}]},
        )

        assert response.status_code == 403
        remote.assert_not_called()


class TestWikiInATeam:
    def _create(self, app, conn, user, team_id):
        from docsgpt.api.user.sources.routes import CreateWikiSource

        with _patch_db(conn), patch("docsgpt.api.user.sources.routes._wiki_store_refusal", return_value=None), \
                app.test_request_context(
                    "/api/sources/wiki", method="POST", json={"name": "Runbook"}, headers=_headers(team_id),
                ):
            from flask import request

            request.decoded_token = {"sub": user}
            return CreateWikiSource().post()

    def test_an_editors_wiki_is_owned_by_the_team(self, app, pg_conn):
        tid, principal = _team(pg_conn)

        response = self._create(app, pg_conn, "eddie", tid)

        assert response.status_code == 200
        row = SourcesRepository(pg_conn).get_by_id(response.json["source_id"])
        assert row["user_id"] == principal
        assert row["created_by"] == "eddie"

    def test_a_viewer_cannot_create_one(self, app, pg_conn):
        tid, _ = _team(pg_conn)

        response = self._create(app, pg_conn, "vera", tid)

        assert response.status_code == 403


class TestFromAttachmentsInATeam:
    def test_the_new_source_is_the_teams(self, app, pg_conn):
        from docsgpt.api.user.sources.from_attachments import SourceFromAttachments
        from docsgpt.storage.db.repositories.attachments import AttachmentsRepository

        tid, principal = _team(pg_conn)
        att = AttachmentsRepository(pg_conn).create(
            "eddie", "notes.txt", "inputs/eddie/attachments/notes.txt", size=10,
        )
        storage = MagicMock()
        storage.file_exists.return_value = True
        ingest = MagicMock(return_value=MagicMock(id="task-a"))
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.from_attachments.StorageCreator.get_storage", return_value=storage,
        ), patch("docsgpt.api.user.sources.from_attachments.ingest.apply_async", ingest), app.test_request_context(
            "/api/sources/from_attachments", method="POST", json={"attachment_ids": [str(att["id"])]},
            headers=_headers(tid),
        ):
            from flask import request

            request.decoded_token = {"sub": "eddie"}
            response = SourceFromAttachments().post()

        assert response.status_code == 200, response.json
        call = ingest.call_args.kwargs
        assert call["args"][3] == principal
        assert call["kwargs"]["actor_id"] == "eddie"
        assert call["kwargs"]["file_path"].startswith(f"{settings.UPLOAD_FOLDER}/{safe_filename(principal)}/")


def _list(app, conn, resource, path, user, team_id=None):
    with _patch_db(conn), app.test_request_context(path, headers=_headers(team_id)):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource().get()


class TestListsPerWorkspace:
    def test_the_team_list_holds_only_the_teams_sources(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

        tid, principal = _team(pg_conn)
        repo = SourcesRepository(pg_conn)
        team_src = repo.create("Team doc", user_id=principal, created_by="eddie")
        repo.create("Eddie's own", user_id="eddie")

        response = _list(app, pg_conn, PaginatedSources, "/api/sources/paginated", "vera", tid)

        assert response.status_code == 200
        body = response.json
        assert [row["id"] for row in body["paginated"]] == [str(team_src["id"])]
        row = body["paginated"][0]
        assert row["workspace"] == {"kind": "team", "team_id": tid}
        assert row["team_role"] == "viewer"
        assert row["access"] == "viewer"
        assert row["origin"] == "team"
        assert "edit" not in row["allowed_actions"]
        assert row["created_by"] == {"user_id": "eddie", "label": "eddie"}
        # Compat: the team's own rows are not "shared with you".
        assert row["ownership"] == "user"
        assert body["workspace"] == {"kind": "team", "team_id": tid, "role": "viewer"}
        assert body["kind_counts"]["shared"] == 0

    def test_personal_never_lists_a_teams_source(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson, PaginatedSources

        _, principal = _team(pg_conn)
        repo = SourcesRepository(pg_conn)
        repo.create("Team doc", user_id=principal, created_by="eddie")
        own = repo.create("Mine", user_id="eddie")

        paged = _list(app, pg_conn, PaginatedSources, "/api/sources/paginated", "eddie")
        combined = _list(app, pg_conn, CombinedJson, "/api/sources", "eddie")

        assert [row["id"] for row in paged.json["paginated"]] == [str(own["id"])]
        assert paged.json["workspace"] == {"kind": "personal", "team_id": None, "role": "owner"}
        assert paged.json["paginated"][0]["created_by"]["user_id"] == "eddie"
        assert [row["id"] for row in combined.json] == [str(own["id"])]

    def test_the_combined_list_follows_the_workspace(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson

        tid, principal = _team(pg_conn)
        team_src = SourcesRepository(pg_conn).create("Team doc", user_id=principal, created_by="eddie")

        response = _list(app, pg_conn, CombinedJson, "/api/sources", "eddie", tid)

        assert response.status_code == 200
        assert [row["id"] for row in response.json] == [str(team_src["id"])]
        assert response.json[0]["team_role"] == "editor"
        assert "edit" in response.json[0]["allowed_actions"]

    def test_a_stranger_cannot_list_a_team(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

        tid, principal = _team(pg_conn)
        SourcesRepository(pg_conn).create("Team doc", user_id=principal)

        response = _list(app, pg_conn, PaginatedSources, "/api/sources/paginated", "mallory", tid)

        assert response.status_code == 404


class TestRepositoryDefensiveFilter:
    def test_extra_ids_never_bring_in_a_principal_owned_row(self, pg_conn):
        _, principal = _team(pg_conn)
        repo = SourcesRepository(pg_conn)
        team_src = repo.create("Team doc", user_id=principal)
        other = repo.create("Bob's", user_id="bob")

        rows = repo.list_for_user("eddie", extra_ids=[str(team_src["id"]), str(other["id"])])
        facets = repo.list_facets_for_user("eddie", extra_ids=[str(team_src["id"])])

        assert [str(r["id"]) for r in rows] == [str(other["id"])]
        assert facets == []

    def test_the_principal_lists_its_own_rows(self, pg_conn):
        _, principal = _team(pg_conn)
        repo = SourcesRepository(pg_conn)
        team_src = repo.create("Team doc", user_id=principal)

        assert [str(r["id"]) for r in repo.list_for_user(principal)] == [str(team_src["id"])]

    def test_create_records_who_added_it(self, pg_conn):
        _, principal = _team(pg_conn)

        row = SourcesRepository(pg_conn).create("Team doc", user_id=principal, created_by="eddie")

        assert row["created_by"] == "eddie"

    def test_a_principal_is_never_recorded_as_creator(self, pg_conn):
        _, principal = _team(pg_conn)

        row = SourcesRepository(pg_conn).create("Team doc", user_id=principal, created_by=principal)

        assert row["created_by"] is None


class TestItemRoutesByTeamRole:
    def test_an_editor_resyncs_a_team_website_as_the_team(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SyncSource

        tid, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create(
            "Site", user_id=principal, type="website",
            remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
        )
        delay = MagicMock(return_value=MagicMock(id="task-s"))
        with _patch_db(pg_conn), patch("docsgpt.api.user.sources.routes.sync_source.delay", delay), \
                app.test_request_context("/api/sync_source", method="POST", json={"source_id": str(src["id"])}):
            from flask import request

            request.decoded_token = {"sub": "eddie"}
            response = SyncSource().post()

        assert response.status_code == 200
        assert delay.call_args.kwargs["user"] == principal
        assert delay.call_args.kwargs["actor_id"] == "eddie"

    def test_a_viewer_cannot_resync(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SyncSource

        _, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("Site", user_id=principal, type="website")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(src["id"])},
        ):
            from flask import request

            request.decoded_token = {"sub": "vera"}
            response = SyncSource().post()

        assert response.status_code == 403

    def test_a_connector_source_owned_by_a_team_is_not_synced(self, app, pg_conn):
        from docsgpt.api.connector.routes import ConnectorSync

        _, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create(
            "Drive", user_id=principal, type="connector:google_drive", remote_data={"provider": "google_drive"},
        )
        delay = MagicMock()
        with _patch_db(pg_conn), patch("docsgpt.api.connector.routes.ingest_connector_task.delay", delay), \
                app.test_request_context(
                    "/api/connectors/sync", method="POST", json={"source_id": str(src["id"])},
                ):
            from flask import request

            request.decoded_token = {"sub": "adam"}
            response = ConnectorSync().post()

        assert response.status_code == 403
        assert response.json["error"] == "connector_personal_only"
        delay.assert_not_called()

    def test_graph_enable_bills_the_editor_who_asked(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import EnableSourceGraphRAG

        _, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("Doc", user_id=principal, type="local")
        delay = MagicMock(return_value=MagicMock(id="task-g"))
        with _patch_db(pg_conn), patch("docsgpt.api.user.sources.routes.graphrag_available", return_value=True), \
                patch("docsgpt.api.user.sources.routes.extract_graph.delay", delay), \
                patch("docsgpt.worker._reset_graph_for_source"), app.test_request_context(
                    f"/api/sources/{src['id']}/graphrag/enable", method="POST",
                ):
            from flask import request

            request.decoded_token = {"sub": "eddie"}
            response = EnableSourceGraphRAG().post(str(src["id"]))

        assert response.status_code == 200
        assert delay.call_args.args[1] == principal
        assert delay.call_args.kwargs["actor_id"] == "eddie"


class TestInternalUploadIndex:
    def test_a_team_source_is_created_with_its_creator(self, pg_conn):
        from docsgpt.app import app as flask_app

        _, principal = _team(pg_conn)
        source_id = str(uuid.uuid4())

        @contextmanager
        def _yield():
            yield pg_conn

        with patch("docsgpt.api.internal.routes.db_session", _yield), \
                patch("docsgpt.api.internal.routes.settings.INTERNAL_KEY", "k"), \
                patch("docsgpt.api.internal.routes.settings.VECTOR_STORE", "pgvector"):
            response = flask_app.test_client().post(
                "/api/upload_index",
                data={
                    "user": principal, "name": "Doc", "tokens": "1", "retriever": "classic",
                    "id": source_id, "type": "local", "created_by": "eddie",
                },
                headers={"X-Internal-Key": "k"},
            )

        assert response.status_code == 200
        row = SourcesRepository(pg_conn).get_by_id(source_id)
        assert row["user_id"] == principal
        assert row["created_by"] == "eddie"
