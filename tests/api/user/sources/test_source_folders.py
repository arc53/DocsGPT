"""The caller's source folders in the sources listings and on new uploads."""

from __future__ import annotations

import io
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository

USER, OTHER = "sf-user", "sf-other"
ROUTES = "docsgpt.api.user.sources.routes"
UPLOAD = "docsgpt.api.user.sources.upload"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, *modules):
    @contextmanager
    def _yield():
        yield conn

    with patch(f"{modules[0]}.db_session", _yield), patch(f"{modules[0]}.db_readonly", _yield):
        yield


def _get(app, conn, path, user=USER):
    from docsgpt.api.user.sources.routes import CombinedJson, PaginatedSources

    resource = PaginatedSources if path.startswith("/api/sources/paginated") else CombinedJson
    with _patch_db(conn, ROUTES), app.test_request_context(path):
        from flask import request

        request.decoded_token = {"sub": user}
        response = resource().get()
    return response.status_code, response.get_json()


@pytest.fixture
def tree(pg_conn):
    """Carriers (a, b) › Archive (c); Customs (d); e unfiled; a team's shared source filed in Carriers."""
    folders = FoldersRepository(pg_conn)
    carriers = folders.create(USER, "Carriers", resource_type="source")
    archive = folders.create(USER, "Archive", resource_type="source", parent_id=carriers["id"])
    customs = folders.create(USER, "Customs", resource_type="source")
    sources = SourcesRepository(pg_conn)
    ids = {name: str(sources.create(name, user_id=USER)["id"]) for name in "abcde"}
    shared = str(sources.create("shared", user_id=OTHER)["id"])
    team = TeamsRepository(pg_conn).create("T", f"t-{uuid.uuid4().hex[:8]}", OTHER)
    TeamMembersRepository(pg_conn).add_member(str(team["id"]), USER)
    TeamResourceGrantsRepository(pg_conn).grant(
        str(team["id"]), "source", shared, OTHER, OTHER, access_level="viewer", target_user_id=USER,
    )
    ids["shared"] = shared
    items = FolderItemsRepository(pg_conn)
    for name, folder in (("a", carriers), ("b", carriers), ("c", archive), ("d", customs), ("shared", carriers)):
        items.file(USER, "source", ids[name], folder["id"])
    return {"carriers": carriers["id"], "archive": archive["id"], "customs": customs["id"], **ids}


def _names(body, tree) -> set:
    by_id = {v: k for k, v in tree.items()}
    return {by_id[row["id"]] for row in body["paginated"]}


class TestListingFields:
    def test_sources_carry_the_callers_folder_and_path(self, app, pg_conn, tree):
        status, body = _get(app, pg_conn, "/api/sources")
        assert status == 200
        rows = {row["id"]: row for row in body}
        assert rows[tree["c"]]["folder_id"] == tree["archive"]
        assert rows[tree["c"]]["folder_path"] == [
            {"id": tree["carriers"], "name": "Carriers"},
            {"id": tree["archive"], "name": "Archive"},
        ]
        assert rows[tree["shared"]]["folder_id"] == tree["carriers"]
        assert (rows[tree["e"]]["folder_id"], rows[tree["e"]]["folder_path"]) == (None, [])

    def test_another_users_filing_is_not_shown(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, "/api/sources", user=OTHER)
        assert {row["id"]: row["folder_id"] for row in body}[tree["shared"]] is None

    def test_paginated_rows_carry_them_too(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, "/api/sources/paginated?rows=50")
        rows = {row["id"]: row for row in body["paginated"]}
        assert rows[tree["a"]]["folder_path"] == [{"id": tree["carriers"], "name": "Carriers"}]
        assert "subtree_total" not in body


class TestPaginatedFolder:
    def test_a_folder_covers_its_subtree(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, f"/api/sources/paginated?rows=50&folder={tree['carriers']}")
        assert _names(body, tree) == {"a", "b", "c", "shared"}
        assert body["total"] == body["subtree_total"] == 4
        assert body["kind_counts"]["all"] == 4
        assert body["kind_counts"]["shared"] == 1
        assert body["usage_counts"]["unused"] == 4

    def test_direct_lists_only_its_own_sources_but_counts_the_subtree(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, f"/api/sources/paginated?rows=50&folder={tree['carriers']}&direct=true")
        assert _names(body, tree) == {"a", "b", "shared"}
        assert body["total"] == 3
        assert body["subtree_total"] == 4
        assert body["kind_counts"]["all"] == 4

    def test_root_direct_lists_the_unfiled(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, "/api/sources/paginated?rows=50&folder=root&direct=true")
        assert _names(body, tree) == {"e"}
        assert body["subtree_total"] == 6
        assert body["kind_counts"]["all"] == 6

    def test_root_without_direct_is_everything(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, "/api/sources/paginated?rows=50&folder=root")
        assert len(body["paginated"]) == body["total"] == 6

    def test_paging_and_filters_apply_inside_the_folder(self, app, pg_conn, tree):
        _, body = _get(app, pg_conn, f"/api/sources/paginated?rows=2&page=2&folder={tree['carriers']}")
        assert (body["totalPages"], body["currentPage"], len(body["paginated"])) == (2, 2, 2)
        _, body = _get(app, pg_conn, f"/api/sources/paginated?rows=50&kind=shared&folder={tree['carriers']}")
        assert _names(body, tree) == {"shared"}

    def test_unknown_folder_and_bad_direct(self, app, pg_conn, tree):
        status, body = _get(app, pg_conn, f"/api/sources/paginated?folder={uuid.uuid4()}")
        assert (status, body["error"]) == (404, "folder_not_found")
        status, _ = _get(app, pg_conn, f"/api/sources/paginated?folder={tree['carriers']}", user=OTHER)
        assert status == 404
        status, _ = _get(app, pg_conn, "/api/sources/paginated?folder=root&direct=maybe")
        assert status == 400


class TestUploadFolder:
    def _upload(self, app, conn, folder_id):
        from docsgpt.api.user.sources.upload import UploadFile

        data = {"user": USER, "name": "job", "file": (io.BytesIO(b"hello"), "a.txt")}
        if folder_id is not None:
            data["folder_id"] = folder_id
        task = MagicMock(id="task-1")
        with _patch_db(conn, UPLOAD), patch(f"{UPLOAD}.StorageCreator.get_storage", return_value=MagicMock()), patch(
            f"{UPLOAD}.ingest.apply_async", return_value=task
        ) as dispatch, patch(f"{UPLOAD}._audit_source_created"), app.test_request_context(
            "/api/upload", method="POST", data=data, content_type="multipart/form-data"
        ):
            from flask import request

            request.decoded_token = {"sub": USER}
            response = UploadFile().post()
        return response, dispatch

    def test_the_folder_travels_to_the_worker(self, app, pg_conn):
        folder = FoldersRepository(pg_conn).create(USER, "K", resource_type="source")
        response, dispatch = self._upload(app, pg_conn, folder["id"])
        assert response.status_code == 200
        assert dispatch.call_args.kwargs["kwargs"]["folder_id"] == folder["id"]

    def test_no_folder_keeps_the_call_shape(self, app, pg_conn):
        response, dispatch = self._upload(app, pg_conn, None)
        assert response.status_code == 200
        assert "folder_id" not in dispatch.call_args.kwargs["kwargs"]

    def test_only_the_callers_source_folder(self, app, pg_conn):
        agent_folder = FoldersRepository(pg_conn).create(USER, "A")
        theirs = FoldersRepository(pg_conn).create(OTHER, "K", resource_type="source")
        for folder_id in (agent_folder["id"], theirs["id"]):
            response, dispatch = self._upload(app, pg_conn, folder_id)
            assert response.status_code == 404
            assert response.get_json()["error"] == "folder_not_found"
            dispatch.assert_not_called()


class TestRemoteFolder:
    def test_the_folder_travels_to_the_worker(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import UploadRemote

        folder = FoldersRepository(pg_conn).create(USER, "K", resource_type="source")
        data = {"user": USER, "source": "url", "name": "job", "data": '{"url": "https://example.com/a"}',
                "folder_id": folder["id"]}
        with _patch_db(pg_conn, UPLOAD), patch(
            f"{UPLOAD}.ingest_remote.apply_async", return_value=MagicMock(id="task-1")
        ) as dispatch, patch(f"{UPLOAD}._audit_source_created"), patch(
            f"{UPLOAD}._join_in_flight_ingest", return_value=None
        ), app.test_request_context("/api/remote", method="POST", data=data):
            from flask import request

            request.decoded_token = {"sub": USER}
            response = UploadRemote().post()
        assert response.status_code == 200, response.get_json()
        assert dispatch.call_args.kwargs["kwargs"]["folder_id"] == folder["id"]


class TestWorkerFiling:
    def test_files_the_new_source_for_the_uploader(self, pg_conn):
        from docsgpt.worker import _file_new_source

        @contextmanager
        def _yield():
            yield pg_conn

        folder = FoldersRepository(pg_conn).create(USER, "K", resource_type="source")
        source = str(SourcesRepository(pg_conn).create("s", user_id=USER)["id"])
        with patch("docsgpt.worker.db_session", _yield):
            _file_new_source(USER, source, folder["id"])
            # A folder that went away meanwhile is skipped quietly.
            _file_new_source(USER, source, str(uuid.uuid4()))
        assert FolderItemsRepository(pg_conn).filing(USER, "source", source) == folder["id"]
