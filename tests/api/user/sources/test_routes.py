"""Tests for application/api/user/sources/routes.py."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text


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
            "ingestStatus",
        ):
            assert key in row

    def test_exposes_stalled_ingest_status(self, app, pg_conn):
        """A source whose ingest the reconciler escalated to 'stalled'
        surfaces ingestStatus='failed' so the UI can badge it.
        """
        from application.api.user.sources.routes import PaginatedSources

        user = "u-ingest-status"
        src = _seed_source(pg_conn, user, name="stalled-doc", type="file")
        pg_conn.execute(
            text(
                """
                INSERT INTO ingest_chunk_progress (
                    source_id, total_chunks, embedded_chunks, last_index,
                    status
                )
                VALUES (CAST(:sid AS uuid), 907, 9, 8, 'stalled')
                """
            ),
            {"sid": str(src["id"])},
        )
        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=1&rows=10"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        row = response.json["paginated"][0]
        assert row["ingestStatus"] == "failed"


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

    def test_returns_403_inaccessible_source(self, app, pg_conn):
        # No ownership and no team editor grant resolves to None, which the
        # owner-or-editor gate answers as 403 "Source not accessible".
        from application.api.user.sources.routes import SyncSource

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = SyncSource().post()
        assert response.status_code == 403

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

    def test_normalizes_dict_remote_data_before_dispatch(self, app, pg_conn):
        """The route must hand the sync task the normalized URL string."""
        from application.api.user.sources.routes import SyncSource

        user = "u-normalize"
        src = _seed_source(
            pg_conn, user, name="crawl-src", type="crawler",
            remote_data=json.dumps(
                {"url": "https://example.com", "provider": "crawler"}
            ),
        )

        fake_task = MagicMock(id="task-norm")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.sync_source.delay",
            return_value=fake_task,
        ) as mock_delay, app.test_request_context(
            "/api/sync_source",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()

        assert response.status_code == 200
        assert mock_delay.call_args.kwargs["source_data"] == "https://example.com"
        assert mock_delay.call_args.kwargs["loader"] == "crawler"

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


class TestReingestSource:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import ReingestSource

        with app.test_request_context(
            "/api/sources/reingest", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = None
            response = ReingestSource().post()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.sources.routes import ReingestSource

        with app.test_request_context(
            "/api/sources/reingest", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ReingestSource().post()
        assert response.status_code == 400

    def test_returns_403_inaccessible_source(self, app, pg_conn):
        # No ownership and no team editor grant resolves to None, which the
        # owner-or-editor gate answers as 403 "Source not accessible".
        from application.api.user.sources.routes import ReingestSource

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/reingest",
            method="POST",
            json={"source_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ReingestSource().post()
        assert response.status_code == 403

    def test_triggers_reingest_task(self, app, pg_conn):
        from application.api.user.sources.routes import ReingestSource

        user = "u-reingest"
        src = _seed_source(pg_conn, user, name="stalled-src", type="file")

        fake_task = MagicMock(id="reingest-task-1")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reingest_source_task.delay",
            return_value=fake_task,
        ) as mock_delay, app.test_request_context(
            "/api/sources/reingest",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ReingestSource().post()

        assert response.status_code == 200
        assert response.json["task_id"] == "reingest-task-1"
        assert mock_delay.call_args.kwargs["source_id"] == str(src["id"])
        assert mock_delay.call_args.kwargs["user"] == user
        # Scoped idempotency key engages the task's lease so repeated
        # clicks collapse onto one reingest instead of racing.
        assert mock_delay.call_args.kwargs["idempotency_key"] == (
            f"reingest-source:{user}:{src['id']}"
        )

    def test_team_editor_reingests_as_owner(self, app, pg_conn):
        """A team editor (not the owner) can reingest a shared source; the
        task dispatches AS the real owner so the owner-scoped pipeline and
        the owner-agnostic vector partition stay consistent.
        """
        import uuid

        from application.api.user.sources.routes import ReingestSource
        from application.storage.db.repositories.team_members import (
            TeamMembersRepository,
        )
        from application.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from application.storage.db.repositories.teams import TeamsRepository

        owner = "alice-reingest"
        editor = "bob-reingest"
        src = _seed_source(pg_conn, owner, name="shared-src", type="file")
        sid = str(src["id"])
        team = TeamsRepository(pg_conn).create(
            "Acme", f"acme-{uuid.uuid4().hex[:8]}", owner
        )
        TeamMembersRepository(pg_conn).add_member(
            team["id"], editor, role="team_member"
        )
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", sid, owner_id=owner, granted_by=owner,
            access_level="editor",
        )

        fake_task = MagicMock(id="reingest-task-editor")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reingest_source_task.delay",
            return_value=fake_task,
        ) as mock_delay, app.test_request_context(
            "/api/sources/reingest",
            method="POST",
            json={"source_id": sid},
        ):
            from flask import request
            request.decoded_token = {"sub": editor}
            response = ReingestSource().post()

        assert response.status_code == 200
        assert mock_delay.call_args.kwargs["source_id"] == sid
        # Dispatched AS the owner, not the editor caller.
        assert mock_delay.call_args.kwargs["user"] == owner
        assert mock_delay.call_args.kwargs["idempotency_key"] == (
            f"reingest-source:{owner}:{sid}"
        )

    def test_clears_stalled_ingest_progress_row(self, app, pg_conn):
        """Reingest drops the stale chunk-progress row so the sources
        list stops deriving a 'failed' ingest status for the source.
        """
        from application.api.user.sources.routes import ReingestSource

        user = "u-reingest-clear"
        src = _seed_source(pg_conn, user, name="stalled-doc", type="file")
        pg_conn.execute(
            text(
                """
                INSERT INTO ingest_chunk_progress (
                    source_id, total_chunks, embedded_chunks, last_index,
                    status
                )
                VALUES (CAST(:sid AS uuid), 100, 9, 8, 'stalled')
                """
            ),
            {"sid": str(src["id"])},
        )

        fake_task = MagicMock(id="reingest-task-2")
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reingest_source_task.delay",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/sources/reingest",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ReingestSource().post()

        assert response.status_code == 200
        remaining = pg_conn.execute(
            text(
                "SELECT count(*) FROM ingest_chunk_progress "
                "WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": str(src["id"])},
        ).scalar()
        assert remaining == 0

    def test_reingest_task_raises_returns_400(self, app, pg_conn):
        from application.api.user.sources.routes import ReingestSource

        user = "u-reingest-fail"
        src = _seed_source(pg_conn, user, name="fail-src", type="file")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.routes.reingest_source_task.delay",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/sources/reingest",
            method="POST",
            json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ReingestSource().post()
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


class TestSourceConfigResource:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import SourceConfigResource

        with app.test_request_context(
            "/api/sources/x/config", method="PATCH", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = SourceConfigResource().patch("x")
        assert response.status_code == 401

    def test_invalid_config_rejected(self, app, pg_conn):
        # Strict-on-write: an unknown field fails validation → 400.
        from application.api.user.sources.routes import SourceConfigResource

        user = "u-cfg-bad"
        src = _seed_source(pg_conn, user, name="cfg-src", type="file")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{src['id']}/config",
            method="PATCH",
            json={"retrieval": {"bogus_field": 1}},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(str(src["id"]))
        assert response.status_code == 400

    def test_owner_updates_retrieval_no_reingest(self, app, pg_conn):
        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-cfg-owner"
        src = _seed_source(pg_conn, user, name="cfg-live", type="file")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{src['id']}/config",
            method="PATCH",
            json={"retrieval": {"chunks": 7, "rephrase_query": False}},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(str(src["id"]))

        assert response.status_code == 200
        # Retrieval-only change takes effect live, no re-ingest needed.
        assert response.json["requires_reingest"] is False
        got = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert got["config"]["retrieval"]["chunks"] == 7
        assert got["config"]["retrieval"]["rephrase_query"] is False

    def test_chunking_change_requires_reingest(self, app, pg_conn):
        from application.api.user.sources.routes import SourceConfigResource

        user = "u-cfg-chunk"
        src = _seed_source(pg_conn, user, name="cfg-chunk", type="file")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{src['id']}/config",
            method="PATCH",
            json={"chunking": {"max_tokens": 800}},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(str(src["id"]))

        assert response.status_code == 200
        assert response.json["requires_reingest"] is True

    def test_viewer_rejected(self, app, pg_conn):
        # A team VIEWER (not editor) cannot edit config → 403.
        import uuid

        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.team_members import (
            TeamMembersRepository,
        )
        from application.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from application.storage.db.repositories.teams import TeamsRepository

        owner = "alice-cfg"
        viewer = "bob-cfg-viewer"
        src = _seed_source(pg_conn, owner, name="shared-cfg", type="file")
        sid = str(src["id"])
        team = TeamsRepository(pg_conn).create(
            "AcmeCfg", f"acmecfg-{uuid.uuid4().hex[:8]}", owner
        )
        TeamMembersRepository(pg_conn).add_member(
            team["id"], viewer, role="team_member"
        )
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", sid, owner_id=owner, granted_by=owner,
            access_level="viewer",
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"retrieval": {"chunks": 5}},
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = SourceConfigResource().patch(sid)
        assert response.status_code == 403
        # The write must NOT have landed.
        got = SourcesRepository(pg_conn).get_any(sid, owner)
        assert got["config"] == {}

    def test_team_editor_writes_under_owner(self, app, pg_conn):
        # A team EDITOR can edit; the write lands under the OWNER's id.
        import uuid

        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.repositories.team_members import (
            TeamMembersRepository,
        )
        from application.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from application.storage.db.repositories.teams import TeamsRepository

        owner = "alice-cfg-edit"
        editor = "bob-cfg-editor"
        src = _seed_source(pg_conn, owner, name="shared-cfg-edit", type="file")
        sid = str(src["id"])
        team = TeamsRepository(pg_conn).create(
            "AcmeEdit", f"acmeedit-{uuid.uuid4().hex[:8]}", owner
        )
        TeamMembersRepository(pg_conn).add_member(
            team["id"], editor, role="team_member"
        )
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", sid, owner_id=owner, granted_by=owner,
            access_level="editor",
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"retrieval": {"chunks": 9}},
        ):
            from flask import request
            request.decoded_token = {"sub": editor}
            response = SourceConfigResource().patch(sid)

        assert response.status_code == 200
        # The write landed under the owner id (not the editor's), so the
        # owner-scoped read sees it.
        got = SourcesRepository(pg_conn).get_any(sid, owner)
        assert got["config"]["retrieval"]["chunks"] == 9

    def test_kind_flip_to_wiki_rejected(self, app, pg_conn):
        # Flipping kind to wiki must route through /wiki/convert, not config.
        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-cfg-wiki-flip"
        src = _seed_source(pg_conn, user, name="cfg-wiki", type="file")
        sid = str(src["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"kind": "wiki"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(sid)

        assert response.status_code == 400
        # The kind must NOT have silently flipped.
        from application.storage.db.source_config import SourceConfig

        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert SourceConfig.parse(got.get("config")).kind != "wiki"

    def test_other_edits_work_on_wiki_source(self, app, pg_conn):
        # A wiki source can still edit retrieval (kind stays wiki, no reject).
        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository

        user = "u-cfg-wiki-edit"
        src = _seed_source(
            pg_conn, user, name="wiki-cfg", type="wiki",
            config={"kind": "wiki"},
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"kind": "wiki", "retrieval": {"chunks": 4}},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(sid)

        assert response.status_code == 200
        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert got["config"]["retrieval"]["chunks"] == 4

    def test_partial_edit_preserves_wiki_kind(self, app, pg_conn):
        # A partial edit that OMITS kind must not demote a wiki to classic
        # (SourceConfig.kind defaults to "classic" on a full-replace write).
        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.source_config import SourceConfig

        user = "u-cfg-wiki-partial"
        src = _seed_source(
            pg_conn, user, name="wiki-partial", type="wiki",
            config={"kind": "wiki"},
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"retrieval": {"chunks": 6}},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(sid)

        assert response.status_code == 200
        assert response.json["config"]["kind"] == "wiki"
        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert SourceConfig.parse(got.get("config")).kind == "wiki"
        assert got["config"]["retrieval"]["chunks"] == 6

    def test_explicit_kind_demotion_from_wiki_rejected(self, app, pg_conn):
        # Demoting wiki -> classic via config is rejected; use /wiki/convert.
        from application.api.user.sources.routes import SourceConfigResource
        from application.storage.db.repositories.sources import SourcesRepository
        from application.storage.db.source_config import SourceConfig

        user = "u-cfg-wiki-demote"
        src = _seed_source(
            pg_conn, user, name="wiki-demote", type="wiki",
            config={"kind": "wiki"},
        )
        sid = str(src["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{sid}/config",
            method="PATCH",
            json={"kind": "classic"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(sid)

        assert response.status_code == 400
        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert SourceConfig.parse(got.get("config")).kind == "wiki"
