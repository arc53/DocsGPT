"""Workspace revamp on the source listings: ``used_by``, ``ingestStatus``, kind/usage filters, bulk delete."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository

ALICE = "alice"
BOB = "bob"
WEB = {"entries": [{"url": "https://docs.x.io/", "mode": "site"}]}


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


def _source(conn, name, owner=ALICE, **kwargs):
    return SourcesRepository(conn).create(name, user_id=owner, **kwargs)


def _share(conn, resource_type, resource_id, owner, member, level="viewer"):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, str(resource_id), owner, owner, access_level=level
    )


def _agent(conn, owner, name, **kwargs):
    return AgentsRepository(conn).create(owner, name, "published", **kwargs)


def _get(app, conn, resource_cls, path, user=ALICE):
    with _patch_db(conn), app.test_request_context(path):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource_cls().get()


@pytest.fixture
def library(pg_conn):
    """One source of every kind for Alice, plus Bob's file shared with her.

    ``web-scheduled`` is a website on a schedule: it stays a website.
    """
    ids = {
        "file": _source(pg_conn, "file", type="local"),
        "file-2": _source(pg_conn, "report", type="local"),
        "web": _source(pg_conn, "web", type="website", remote_data=WEB),
        "web-scheduled": _source(pg_conn, "web-scheduled", type="website", remote_data=WEB, sync_frequency="weekly"),
        "synced": _source(pg_conn, "synced", type="github", sync_frequency="daily"),
        "connector": _source(pg_conn, "drive", type="connector:google_drive"),
        "never": _source(pg_conn, "never-synced", type="github", sync_frequency="never"),
        "wiki": _source(pg_conn, "wiki", type="local", config={"kind": "wiki"}, sync_frequency="daily"),
        "shared": _source(pg_conn, "shared", owner=BOB, type="local"),
    }
    ids = {key: str(row["id"]) for key, row in ids.items()}
    _share(pg_conn, "source", ids["shared"], BOB, ALICE)
    return ids


class TestSourceKind:
    def test_kinds_and_precedence(self, pg_conn, library):
        from docsgpt.api.user.sources.routes import source_kind

        rows = {r["id"]: r for r in SourcesRepository(pg_conn).list_by_ids(list(library.values()))}
        kinds = {key: source_kind({**rows[sid], "id": sid}) for key, sid in library.items()}
        assert kinds == {
            "file": "files",
            "file-2": "files",
            "web": "websites",
            "web-scheduled": "websites",
            "synced": "synced",
            "connector": "synced",
            "never": "files",
            "wiki": "wikis",
            "shared": "files",
        }


class TestFullList:
    def test_used_by_and_ingest_status(self, app, pg_conn, library):
        from docsgpt.api.user.sources.routes import CombinedJson

        agent = _agent(pg_conn, ALICE, "Helper", source_id=library["file"], extra_source_ids=[library["shared"]])
        _agent(pg_conn, BOB, "Bob's", source_id=library["web"])
        pg_conn.execute(
            text(
                "INSERT INTO ingest_chunk_progress (source_id, total_chunks, embedded_chunks, last_index, status) "
                "VALUES (CAST(:a AS uuid), 10, 2, 1, 'active'), (CAST(:b AS uuid), 10, 2, 1, 'stalled')"
            ),
            {"a": library["file"], "b": library["shared"]},
        )
        resp = _get(app, pg_conn, CombinedJson, "/api/sources")
        assert resp.status_code == 200
        rows = {r["id"]: r for r in resp.json}
        assert rows[library["file"]]["used_by"] == {"agents": [{"id": str(agent["id"]), "name": "Helper"}], "others": 0}
        assert rows[library["web"]]["used_by"] == {"agents": [], "others": 1}
        assert rows[library["shared"]]["used_by"]["agents"][0]["name"] == "Helper"
        assert rows[library["file"]]["ingestStatus"] == "processing"
        assert rows[library["shared"]]["ingestStatus"] == "failed"
        assert rows[library["wiki"]]["ingestStatus"] is None
        # Own sources first (newest first), then the team's.
        assert [r["id"] for r in resp.json][-1] == library["shared"]


class TestPaginatedFilters:
    def _page(self, app, pg_conn, query=""):
        from docsgpt.api.user.sources.routes import PaginatedSources

        rows = "" if "rows=" in query else "rows=50&"
        resp = _get(app, pg_conn, PaginatedSources, f"/api/sources/paginated?{rows}{query}")
        assert resp.status_code == 200, resp.json
        return resp.json

    def test_default_lists_everything_with_counts(self, app, pg_conn, library):
        data = self._page(app, pg_conn)
        assert data["total"] == 9
        assert data["kind_counts"] == {"all": 9, "files": 4, "websites": 2, "synced": 2, "wikis": 1, "shared": 1}
        assert data["usage_counts"] == {"all": 9, "in_use": 0, "unused": 9}
        assert all(row["used_by"] == {"agents": [], "others": 0} for row in data["paginated"])

    @pytest.mark.parametrize(
        "kind, expected",
        [
            ("files", {"file", "file-2", "never", "shared"}),
            ("websites", {"web", "web-scheduled"}),
            ("synced", {"synced", "connector"}),
            ("wikis", {"wiki"}),
            ("shared", {"shared"}),
        ],
    )
    def test_kind_filter(self, app, pg_conn, library, kind, expected):
        data = self._page(app, pg_conn, f"kind={kind}")
        names = {sid: key for key, sid in library.items()}
        assert {names[row["id"]] for row in data["paginated"]} == expected
        assert data["total"] == len(expected)
        # The kind counts ignore the kind filter.
        assert data["kind_counts"]["all"] == 9

    def test_usage_filter_and_counts(self, app, pg_conn, library):
        _agent(pg_conn, ALICE, "Helper", source_id=library["file"])
        _agent(pg_conn, BOB, "Bob's", source_id=library["web"])  # only counted in others
        in_use = self._page(app, pg_conn, "usage=in_use")
        assert {row["id"] for row in in_use["paginated"]} == {library["file"], library["web"]}
        assert in_use["usage_counts"] == {"all": 9, "in_use": 2, "unused": 7}
        assert in_use["kind_counts"] == {"all": 2, "files": 1, "websites": 1, "synced": 0, "wikis": 0, "shared": 0}
        unused = self._page(app, pg_conn, "usage=unused&kind=websites")
        assert [row["id"] for row in unused["paginated"]] == [library["web-scheduled"]]
        assert unused["usage_counts"] == {"all": 2, "in_use": 1, "unused": 1}

    def test_filters_and_with_search_and_paginate(self, app, pg_conn, library):
        data = self._page(app, pg_conn, "search=web&kind=websites&rows=1&page=2&sort=name&order=asc")
        assert data["total"] == 2
        assert data["totalPages"] == 2
        assert [row["id"] for row in data["paginated"]] == [library["web-scheduled"]]
        assert data["kind_counts"] == {"all": 2, "files": 0, "websites": 2, "synced": 0, "wikis": 0, "shared": 0}

    def test_empty_filter_result(self, app, pg_conn, library):
        data = self._page(app, pg_conn, "kind=wikis&usage=in_use")
        assert data["paginated"] == []
        assert data["total"] == 0
        assert data["totalPages"] == 1

    @pytest.mark.parametrize("query", ["kind=pdfs", "usage=sometimes"])
    def test_unknown_filter_value_is_400(self, app, pg_conn, query):
        from docsgpt.api.user.sources.routes import PaginatedSources

        resp = _get(app, pg_conn, PaginatedSources, f"/api/sources/paginated?{query}")
        assert resp.status_code == 400


class TestBulkDelete:
    def _post(self, app, pg_conn, body, user=ALICE, lock=None):
        from docsgpt.api.user.sources.routes import BulkDeleteSources

        @contextmanager
        def _free(*args, **kwargs):
            yield

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.access.source_index_lock", lock or _free
        ), patch("docsgpt.api.user.sources.routes.settings.VECTOR_STORE", "faiss"), patch(
            "docsgpt.api.user.sources.routes.StorageCreator.get_storage", return_value=MagicMock()
        ), app.test_request_context("/api/sources/delete", method="POST", json=body):
            from flask import request

            request.decoded_token = {"sub": user}
            return BulkDeleteSources().post()

    def test_partial_failure_is_200(self, app, pg_conn):
        mine = str(_source(pg_conn, "mine")["id"])
        theirs = str(_source(pg_conn, "theirs", owner=BOB)["id"])
        _share(pg_conn, "source", theirs, BOB, ALICE)
        missing = str(uuid.uuid4())
        resp = self._post(app, pg_conn, {"ids": [mine, theirs, missing, mine]})
        assert resp.status_code == 200
        assert resp.json["deleted"] == [mine]
        failed = {f["id"]: f for f in resp.json["failed"]}
        assert set(failed) == {theirs, missing}
        assert failed[theirs]["code"] == "forbidden" and failed[theirs]["error"]
        assert failed[missing]["code"] == "not_found"
        assert SourcesRepository(pg_conn).get_any(mine, ALICE) is None
        assert SourcesRepository(pg_conn).get_any(theirs, BOB) is not None

    def test_busy_source_fails_with_its_code(self, app, pg_conn):
        from docsgpt.vectorstore.index_lock import SourceBusy

        sid = str(_source(pg_conn, "busy")["id"])

        @contextmanager
        def busy(*args, **kwargs):
            raise SourceBusy("busy")
            yield

        resp = self._post(app, pg_conn, {"ids": [sid]}, lock=busy)
        assert resp.status_code == 200
        assert resp.json == {"deleted": [], "failed": [{"id": sid, "error": resp.json["failed"][0]["error"],
                                                         "code": "source_busy"}]}

    @pytest.mark.parametrize(
        "body",
        [None, {}, {"ids": []}, {"ids": "abc"}, {"ids": [1]}, {"ids": [""]}, {"ids": ["x"] * 101}],
    )
    def test_bad_body_is_400(self, app, pg_conn, body):
        resp = self._post(app, pg_conn, body)
        assert resp.status_code == 400

    def test_unauthenticated_is_401(self, app):
        from docsgpt.api.user.sources.routes import BulkDeleteSources

        with app.test_request_context("/api/sources/delete", method="POST", json={"ids": ["a"]}):
            from flask import request

            request.decoded_token = None
            assert BulkDeleteSources().post().status_code == 401
