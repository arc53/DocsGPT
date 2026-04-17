"""Tests for application/api/user/sources/routes.py."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.sources.routes.db_session", _yield
    ), patch(
        "application.api.user.sources.routes.db_readonly", _yield
    ):
        yield


def _seed_source(pg_conn, user, **kwargs):
    from application.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create(
        kwargs.pop("name", "src"),
        user_id=user,
        **kwargs,
    )


class TestGetProviderFromRemoteData:
    def test_returns_none_for_empty(self):
        from application.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert _get_provider_from_remote_data(None) is None
        assert _get_provider_from_remote_data("") is None

    def test_returns_from_dict(self):
        from application.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert (
            _get_provider_from_remote_data({"provider": "gdrive"})
            == "gdrive"
        )

    def test_returns_from_json_string(self):
        from application.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert (
            _get_provider_from_remote_data('{"provider": "github"}')
            == "github"
        )

    def test_returns_none_for_malformed_json(self):
        from application.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert _get_provider_from_remote_data("not-json") is None


class TestCombinedJson:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import CombinedJson

        with app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = None
            response = CombinedJson().get()
        assert response.status_code == 401

    def test_returns_default_plus_user_sources(self, app, pg_conn):
        from application.api.user.sources.routes import CombinedJson

        user = "u-list-sources"
        _seed_source(pg_conn, user, name="doc1", tokens="100")

        with _patch_db(pg_conn), app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CombinedJson().get()

        assert response.status_code == 200
        names = [d["name"] for d in response.json]
        assert "Default" in names
        assert "doc1" in names

    def test_db_error_returns_400(self, app):
        from application.api.user.sources.routes import CombinedJson

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.sources.routes.db_readonly", _broken
        ), app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CombinedJson().get()
        assert response.status_code == 400


class TestPaginatedSources:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import PaginatedSources

        with app.test_request_context("/api/sources/paginated"):
            from flask import request
            request.decoded_token = None
            response = PaginatedSources().get()
        assert response.status_code == 401

    def test_returns_pagination_shape(self, app, pg_conn):
        from application.api.user.sources.routes import PaginatedSources

        user = "u-pag"
        for i in range(5):
            _seed_source(pg_conn, user, name=f"doc-{i}")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=1&rows=2"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        assert response.status_code == 200
        data = response.json
        assert data["total"] == 5
        assert data["totalPages"] == 3
        assert data["currentPage"] == 1
        assert len(data["paginated"]) == 2

    def test_search_filter(self, app, pg_conn):
        from application.api.user.sources.routes import PaginatedSources

        user = "u-search"
        _seed_source(pg_conn, user, name="Alpha doc")
        _seed_source(pg_conn, user, name="Beta doc")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?search=alpha"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        assert response.status_code == 200
        data = response.json
        assert data["total"] == 1
        assert data["paginated"][0]["name"] == "Alpha doc"

    def test_pagination_across_multiple_pages(self, app, pg_conn):
        """Every seeded doc surfaces exactly once across paginated windows."""
        from application.api.user.sources.routes import PaginatedSources

        user = "u-multi-page"
        expected = {f"doc-{i}" for i in range(7)}
        for name in expected:
            _seed_source(pg_conn, user, name=name)

        seen: set[str] = set()
        for page in (1, 2, 3):
            with _patch_db(pg_conn), app.test_request_context(
                f"/api/sources/paginated?page={page}&rows=3"
            ):
                from flask import request
                request.decoded_token = {"sub": user}
                response = PaginatedSources().get()
            assert response.status_code == 200
            for doc in response.json["paginated"]:
                seen.add(doc["name"])
        assert seen == expected

    def test_out_of_range_page_returns_empty_window(self, app, pg_conn):
        from application.api.user.sources.routes import PaginatedSources

        user = "u-oor"
        _seed_source(pg_conn, user, name="only-one")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=99&rows=10"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        assert response.status_code == 200
        data = response.json
        assert data["total"] == 1
        # Prior behavior clamps ``currentPage`` back into range.
        assert data["currentPage"] == 1
        assert len(data["paginated"]) == 1

    def test_empty_result_set_shape(self, app, pg_conn):
        from application.api.user.sources.routes import PaginatedSources

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=1&rows=10"
        ):
            from flask import request
            request.decoded_token = {"sub": "u-empty"}
            response = PaginatedSources().get()
        assert response.status_code == 200
        data = response.json
        assert data["total"] == 0
        # Legacy route returned ``max(1, ceil(0/rows)) == 1`` for empties.
        assert data["totalPages"] == 1
        assert data["paginated"] == []

    def test_search_hits_sql_not_post_filter(self, app, pg_conn):
        """Search must narrow ``total`` at the DB level, not in Python."""
        from application.api.user.sources.routes import PaginatedSources

        user = "u-sql-search"
        _seed_source(pg_conn, user, name="needle in a haystack")
        _seed_source(pg_conn, user, name="plain")
        _seed_source(pg_conn, user, name="another plain")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?search=NEEDLE"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        data = response.json
        # ``total`` reflects the filtered count — would be 3 if filtering
        # happened after an unbounded fetch.
        assert data["total"] == 1
        assert data["paginated"][0]["name"] == "needle in a haystack"

    def test_response_shape_preserved(self, app, pg_conn):
        from application.api.user.sources.routes import PaginatedSources

        user = "u-shape"
        _seed_source(pg_conn, user, name="shape-doc")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=1&rows=10"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        data = response.json
        # Top-level contract the frontend relies on.
        assert set(data.keys()) >= {"total", "totalPages", "currentPage", "paginated"}
        # Each paginated entry exposes the legacy per-row keys.
        row = data["paginated"][0]
        for key in (
            "id", "name", "date", "model", "location", "tokens",
            "retriever", "syncFrequency", "provider", "isNested", "type",
        ):
            assert key in row


class TestDeleteOldIndexes:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        with app.test_request_context("/api/delete_old?source_id=x"):
            from flask import request
            request.decoded_token = None
            response = DeleteOldIndexes().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        with app.test_request_context("/api/delete_old"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteOldIndexes().get()
        assert response.status_code == 400

    def test_returns_404_missing_source(self, app, pg_conn):
        from application.api.user.sources.routes import DeleteOldIndexes

        with _patch_db(pg_conn), app.test_request_context(
            "/api/delete_old?source_id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteOldIndexes().get()
        assert response.status_code == 404

    def test_deletes_non_faiss_source(self, app, pg_conn):
        from application.api.user.sources.routes import DeleteOldIndexes

        user = "u-del-src"
        src = _seed_source(pg_conn, user, name="remove-me")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = False
        fake_vs = MagicMock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.settings.VECTOR_STORE",
            "milvus",
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.routes.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ), app.test_request_context(
            f"/api/delete_old?source_id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteOldIndexes().get()
        assert response.status_code == 200
        fake_vs.delete_index.assert_called_once()

    def test_deletes_faiss_source(self, app, pg_conn):
        from application.api.user.sources.routes import DeleteOldIndexes

        user = "u-faiss-del"
        src = _seed_source(
            pg_conn, user, name="faiss-src", file_path="/tmp/x"
        )

        fake_storage = MagicMock()
        fake_storage.file_exists.return_value = True
        fake_storage.is_directory.return_value = False

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.settings.VECTOR_STORE",
            "faiss",
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            f"/api/delete_old?source_id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteOldIndexes().get()
        assert response.status_code == 200
        assert fake_storage.delete_file.call_count >= 2

    def test_delete_ignores_missing_file_error(self, app, pg_conn):
        from application.api.user.sources.routes import DeleteOldIndexes

        user = "u-nofile"
        src = _seed_source(
            pg_conn, user, name="nofile", file_path="/tmp/missing",
        )

        fake_storage = MagicMock()
        fake_storage.file_exists.return_value = False
        fake_storage.is_directory.return_value = False
        fake_storage.delete_file.side_effect = FileNotFoundError("gone")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.settings.VECTOR_STORE",
            "milvus",
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.routes.VectorCreator.create_vectorstore",
            return_value=MagicMock(),
        ), app.test_request_context(
            f"/api/delete_old?source_id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteOldIndexes().get()
        assert response.status_code == 200


class TestRedirectToSources:
    def test_redirects(self, app):
        from application.api.user.sources.routes import RedirectToSources

        with app.test_request_context("/api/combine"):
            response = RedirectToSources().get()
        assert response.status_code == 301


class TestManageSync:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync", method="POST",
            json={"source_id": "x", "sync_frequency": "daily"},
        ):
            from flask import request
            request.decoded_token = None
            response = ManageSync().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSync().post()
        assert response.status_code == 400

    def test_returns_400_invalid_frequency(self, app):
        from application.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync",
            method="POST",
            json={"source_id": "x", "sync_frequency": "hourly"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSync().post()
        assert response.status_code == 400

    def test_returns_404_missing_source(self, app, pg_conn):
        from application.api.user.sources.routes import ManageSync

        with _patch_db(pg_conn), app.test_request_context(
            "/api/manage_sync",
            method="POST",
            json={
                "source_id": "00000000-0000-0000-0000-000000000000",
                "sync_frequency": "daily",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSync().post()
        assert response.status_code == 404

    def test_updates_sync_frequency(self, app, pg_conn):
        from application.api.user.sources.routes import ManageSync
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-sync"
        src = _seed_source(pg_conn, user, name="sync-src")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/manage_sync",
            method="POST",
            json={"source_id": str(src["id"]), "sync_frequency": "weekly"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSync().post()
        assert response.status_code == 200
        got = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert got["sync_frequency"] == "weekly"


class TestSyncSource:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import SyncSource

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = None
            response = SyncSource().post()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.sources.routes import SyncSource

        with app.test_request_context(
            "/api/sync_source", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = SyncSource().post()
        assert response.status_code == 400

    def test_returns_404_missing_source(self, app, pg_conn):
        from application.api.user.sources.routes import SyncSource

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = SyncSource().post()
        assert response.status_code == 404

    def test_returns_400_for_connector_type(self, app, pg_conn):
        from application.api.user.sources.routes import SyncSource

        user = "u-conn"
        src = _seed_source(
            pg_conn, user, name="connector-src", type="connector_github",
            remote_data=json.dumps({"provider": "github"}),
        )

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()
        assert response.status_code == 400

    def test_returns_400_for_non_syncable(self, app, pg_conn):
        from application.api.user.sources.routes import SyncSource

        user = "u-nosync"
        src = _seed_source(pg_conn, user, name="nosync", type="file")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()
        assert response.status_code == 400

    def test_triggers_sync_task(self, app, pg_conn):
        from application.api.user.sources.routes import SyncSource

        user = "u-trigger"
        src = _seed_source(
            pg_conn, user, name="remote-src", type="github",
            remote_data=json.dumps({"provider": "github", "url": "x"}),
        )

        fake_task = MagicMock(id="task-123")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.sync_source.delay",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()
        assert response.status_code == 200
        assert response.json["task_id"] == "task-123"

    def test_sync_task_raises_returns_400(self, app, pg_conn):
        from application.api.user.sources.routes import SyncSource

        user = "u-fail"
        src = _seed_source(
            pg_conn, user, name="fail-src", type="github",
            remote_data=json.dumps({"provider": "github"}),
        )

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.sync_source.delay",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()
        assert response.status_code == 400


class TestDirectoryStructure:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure?id=x"):
            from flask import request
            request.decoded_token = None
            response = DirectoryStructure().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DirectoryStructure().get()
        assert response.status_code == 400

    def test_returns_404_missing_doc(self, app, pg_conn):
        from application.api.user.sources.routes import DirectoryStructure

        with _patch_db(pg_conn), app.test_request_context(
            "/api/directory_structure?id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DirectoryStructure().get()
        assert response.status_code == 404

    def test_returns_structure(self, app, pg_conn):
        from application.api.user.sources.routes import DirectoryStructure

        user = "u-dir"
        src = _seed_source(
            pg_conn, user, name="nested",
            directory_structure={"root": {"a.txt": None}},
            file_path="/data/nested",
            remote_data=json.dumps({"provider": "gdrive"}),
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/directory_structure?id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DirectoryStructure().get()
        assert response.status_code == 200
        data = response.json
        assert data["provider"] == "gdrive"
        assert data["base_path"] == "/data/nested"
