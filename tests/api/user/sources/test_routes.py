"""Tests for docsgpt/api/user/sources/routes.py."""

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
        "docsgpt.api.user.sources.routes.db_session", _yield
    ), patch(
        "docsgpt.api.user.sources.routes.db_readonly", _yield
    ):
        yield


def _seed_source(pg_conn, user, **kwargs):
    from docsgpt.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create(
        kwargs.pop("name", "src"),
        user_id=user,
        **kwargs,
    )


class TestGetProviderFromRemoteData:
    def test_returns_none_for_empty(self):
        from docsgpt.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert _get_provider_from_remote_data(None) is None
        assert _get_provider_from_remote_data("") is None

    def test_returns_from_dict(self):
        from docsgpt.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert (
            _get_provider_from_remote_data({"provider": "gdrive"})
            == "gdrive"
        )

    def test_returns_from_json_string(self):
        from docsgpt.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert (
            _get_provider_from_remote_data('{"provider": "github"}')
            == "github"
        )

    def test_returns_none_for_malformed_json(self):
        from docsgpt.api.user.sources.routes import (
            _get_provider_from_remote_data,
        )
        assert _get_provider_from_remote_data("not-json") is None


class TestCombinedJson:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import CombinedJson

        with app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = None
            response = CombinedJson().get()
        assert response.status_code == 401

    def test_returns_only_real_user_sources(self, app, pg_conn):
        """No synthetic "Default" row: every entry is an ingested source
        with an id, so clients never have to special-case a placeholder."""
        from docsgpt.api.user.sources.routes import CombinedJson

        user = "u-list-sources"
        _seed_source(pg_conn, user, name="doc1", tokens="100")

        with _patch_db(pg_conn), app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CombinedJson().get()

        assert response.status_code == 200
        names = [d["name"] for d in response.json]
        assert "Default" not in names
        assert names == ["doc1"]
        assert all(d.get("id") for d in response.json)

    def test_a_web_source_carries_its_website_summary_and_file_count(self, app, pg_conn):
        # Citation links fall back to this list; without ``website`` a website
        # source would open as a plain file tree.
        from docsgpt.api.user.sources.routes import CombinedJson

        user = "u-list-web"
        leaf = {"type": "text/markdown", "size_bytes": 1, "token_count": 1}
        _seed_source(
            pg_conn, user, name="web", type="website",
            remote_data={"entries": [{"url": "https://www.docs.x.io/", "mode": "site"}]},
            directory_structure={
                "index.md": {**leaf, "url": "https://www.docs.x.io/"},
                "guide": {"a.md": {**leaf, "url": "https://www.docs.x.io/guide/a"}},
            },
        )
        _seed_source(pg_conn, user, name="flat", type="local")

        with _patch_db(pg_conn), app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CombinedJson().get()

        rows = {row["name"]: row for row in response.json}
        assert rows["web"]["website"] == {"hosts": ["docs.x.io"], "pages": 2}
        assert rows["web"]["files"] == 2
        assert rows["flat"]["website"] is None
        assert rows["flat"]["files"] is None

    def test_returns_empty_list_when_user_has_no_sources(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import CombinedJson

        with _patch_db(pg_conn), app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = {"sub": "u-no-sources"}
            response = CombinedJson().get()

        assert response.status_code == 200
        assert response.json == []

    def test_db_error_returns_400(self, app):
        from docsgpt.api.user.sources.routes import CombinedJson

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.sources.routes.db_readonly", _broken
        ), app.test_request_context("/api/sources"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CombinedJson().get()
        assert response.status_code == 400


class TestPaginatedSources:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import PaginatedSources

        with app.test_request_context("/api/sources/paginated"):
            from flask import request
            request.decoded_token = None
            response = PaginatedSources().get()
        assert response.status_code == 401

    def test_returns_pagination_shape(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

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

    def test_counts_files_in_the_tree(self, app, pg_conn):
        """A card shows how many files a synced source holds."""
        from docsgpt.api.user.sources.routes import PaginatedSources

        user = "u-files"
        _seed_source(
            pg_conn, user, name="bucket",
            directory_structure={
                "a.pdf": {"type": "application/pdf", "token_count": 10},
                "docs": {"b.md": {"type": "text/markdown", "token_count": 5}},
            },
        )
        _seed_source(pg_conn, user, name="flat")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?rows=10"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        by_name = {d["name"]: d for d in response.json["paginated"]}
        assert by_name["bucket"]["files"] == 2
        assert by_name["flat"]["files"] is None

    def test_search_filter(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

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
        from docsgpt.api.user.sources.routes import PaginatedSources

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
        from docsgpt.api.user.sources.routes import PaginatedSources

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
        from docsgpt.api.user.sources.routes import PaginatedSources

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
        from docsgpt.api.user.sources.routes import PaginatedSources

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
        from docsgpt.api.user.sources.routes import PaginatedSources

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

    def test_a_web_source_carries_its_hosts_and_page_count(self, app, pg_conn):
        # The Knowledge card shows where a website source comes from.
        from docsgpt.api.user.sources.routes import PaginatedSources

        user = "u-web-card"
        leaf = {"type": "text/markdown", "size_bytes": 1, "token_count": 1}
        _seed_source(
            pg_conn, user, name="web", type="website",
            remote_data={"entries": [
                {"url": "https://www.docs.x.io/", "mode": "site"},
                {"url": "https://github.com/a/b", "mode": "page"},
            ]},
            directory_structure={
                "docs.x.io": {"index.md": {**leaf, "url": "https://www.docs.x.io/"}},
                "github.com": {"a": {"b.md": {**leaf, "url": "https://github.com/a/b"}}},
            },
        )
        # Ingested before pages carried their URL: every leaf is still a page.
        _seed_source(
            pg_conn, user, name="legacy", type="crawler", remote_data={"url": "https://y.io/"},
            directory_structure={"index.md": leaf, "guide": {"a.md": leaf, "b.md": leaf}},
        )
        _seed_source(pg_conn, user, name="upload", type="local")
        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=1&rows=10&sort=name&order=asc"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        rows = {row["name"]: row for row in response.json["paginated"]}
        assert rows["web"]["website"] == {"hosts": ["docs.x.io", "github.com"], "pages": 2}
        assert rows["legacy"]["website"] == {"hosts": ["y.io"], "pages": 3}
        assert rows["upload"]["website"] is None

    def test_a_bad_stored_web_row_does_not_break_the_listing(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

        user = "u-web-bad"
        leaf = {"type": "text/markdown", "size_bytes": 1, "token_count": 1}
        _seed_source(pg_conn, user, name="bad-legacy", type="url", remote_data={"url": "http://[x"})
        _seed_source(
            pg_conn, user, name="bad-website", type="website",
            remote_data={"entries": [{"url": "http://[x", "mode": "page"}]},
        )
        _seed_source(
            pg_conn, user, name="good", type="website",
            remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
            directory_structure={"index.md": {**leaf, "url": "https://x.io/"}},
        )
        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/paginated?page=1&rows=10&sort=name&order=asc"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        assert response.status_code == 200
        rows = {row["name"]: row for row in response.json["paginated"]}
        assert rows["bad-legacy"]["website"] is None
        assert rows["bad-website"]["website"] is None
        assert rows["good"]["website"] == {"hosts": ["x.io"], "pages": 1}

    def test_an_address_stored_without_a_scheme_still_names_its_host(self, app):
        from docsgpt.api.user.sources.routes import _website_summary

        row = {"type": "website", "remote_data": {"entries": [
            {"url": "docs.x.io/a", "mode": "page"},
            {"url": "www.docs.x.io/b", "mode": "page"},
            {"url": "Y.io/c", "mode": "page"},
        ]}}
        with app.app_context():
            assert _website_summary(row) == {"hosts": ["docs.x.io", "y.io"], "pages": 0}

    def test_one_failing_summary_does_not_fail_the_listing(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

        user = "u-web-raise"
        _seed_source(
            pg_conn, user, name="web", type="website",
            remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
        )
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.config_from_legacy", side_effect=RuntimeError("boom")
        ), app.test_request_context("/api/sources/paginated?page=1&rows=10"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        assert response.status_code == 200
        assert response.json["paginated"][0]["website"] is None

    def test_a_converted_wiki_has_no_website_summary(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import PaginatedSources

        user = "u-web-wiki"
        leaf = {"type": "text/markdown", "size_bytes": 1, "token_count": 1}
        _seed_source(
            pg_conn, user, name="wiki", type="website", config={"kind": "wiki"},
            remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
            directory_structure={"index.md": {**leaf, "url": "https://x.io/"}},
        )
        with _patch_db(pg_conn), app.test_request_context("/api/sources/paginated?page=1&rows=10"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PaginatedSources().get()
        assert response.json["paginated"][0]["website"] is None

    def test_exposes_stalled_ingest_status(self, app, pg_conn):
        """A source whose ingest the reconciler escalated to 'stalled'
        surfaces ingestStatus='failed' so the UI can badge it.
        """
        from docsgpt.api.user.sources.routes import PaginatedSources

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
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        with app.test_request_context("/api/delete_old?source_id=x"):
            from flask import request
            request.decoded_token = None
            response = DeleteOldIndexes().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        with app.test_request_context("/api/delete_old"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteOldIndexes().get()
        assert response.status_code == 400

    def test_returns_404_missing_source(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        with _patch_db(pg_conn), app.test_request_context(
            "/api/delete_old?source_id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteOldIndexes().get()
        assert response.status_code == 404

    def test_deletes_non_faiss_source(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        user = "u-del-src"
        src = _seed_source(pg_conn, user, name="remove-me")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = False
        fake_vs = MagicMock()

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.settings.VECTOR_STORE",
            "milvus",
        ), patch(
            "docsgpt.api.user.sources.routes.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.routes.VectorCreator.create_vectorstore",
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
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        user = "u-faiss-del"
        src = _seed_source(
            pg_conn, user, name="faiss-src", file_path="/tmp/x"
        )

        fake_storage = MagicMock()
        fake_storage.file_exists.return_value = True
        fake_storage.is_directory.return_value = False

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.settings.VECTOR_STORE",
            "faiss",
        ), patch(
            "docsgpt.api.user.sources.routes.StorageCreator.get_storage",
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
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        user = "u-nofile"
        src = _seed_source(
            pg_conn, user, name="nofile", file_path="/tmp/missing",
        )

        fake_storage = MagicMock()
        fake_storage.file_exists.return_value = False
        fake_storage.is_directory.return_value = False
        fake_storage.delete_file.side_effect = FileNotFoundError("gone")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.settings.VECTOR_STORE",
            "milvus",
        ), patch(
            "docsgpt.api.user.sources.routes.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.routes.VectorCreator.create_vectorstore",
            return_value=MagicMock(),
        ), app.test_request_context(
            f"/api/delete_old?source_id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteOldIndexes().get()
        assert response.status_code == 200


class TestDeleteUnderTheIndexLock:
    """A delete holds the source's index lock: a sync or page change saving meanwhile would bring its index back."""

    def _delete(self, app, pg_conn, user, src, lock, storage):
        from docsgpt.api.user.sources.routes import DeleteOldIndexes

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.access.source_index_lock", lock,
        ), patch("docsgpt.api.user.sources.routes.settings.VECTOR_STORE", "faiss"), patch(
            "docsgpt.api.user.sources.routes.StorageCreator.get_storage", return_value=storage,
        ), app.test_request_context(f"/api/delete_old?source_id={src['id']}"):
            from flask import request
            request.decoded_token = {"sub": user}
            return DeleteOldIndexes().get()

    def test_the_index_and_row_go_while_the_lock_is_held(self, app, pg_conn):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        user = "u-del-locked"
        src = _seed_source(pg_conn, user, name="faiss-src")
        held = []
        storage = MagicMock()
        storage.file_exists.return_value = True
        storage.delete_file.side_effect = lambda path: held.append(("deleted", path))

        @contextmanager
        def fake_lock(source_id, wait_seconds, **kwargs):
            held.append(("locked", source_id, wait_seconds))
            yield
            held.append(("released", SourcesRepository(pg_conn).get_any(str(src["id"]), user)))

        response = self._delete(app, pg_conn, user, src, fake_lock, storage)

        assert response.status_code == 200, response.json
        assert held[0][:2] == ("locked", str(src["id"]))
        # A request waits seconds, not the worker's hour.
        assert 0 < held[0][2] <= 5
        assert ("deleted", f"indexes/{src['id']}/index.faiss") in held
        # The row is gone before the lock is released.
        assert held[-1] == ("released", None)

    def test_a_busy_source_is_409_and_kept(self, app, pg_conn):
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.vectorstore.index_lock import SourceBusy

        user = "u-del-busy"
        src = _seed_source(pg_conn, user, name="faiss-src")
        storage = MagicMock()
        storage.file_exists.return_value = True

        @contextmanager
        def busy(*args, **kwargs):
            raise SourceBusy("busy")
            yield

        response = self._delete(app, pg_conn, user, src, busy, storage)

        assert response.status_code == 409
        assert response.json["success"] is False
        assert response.json["code"] == "source_busy"
        storage.delete_file.assert_not_called()
        assert SourcesRepository(pg_conn).get_any(str(src["id"]), user) is not None

    def test_a_busy_source_fails_a_delete_that_asked_for_a_bool(self, app, pg_conn):
        # Removing a connection with its sources lists a busy one as failed.
        from docsgpt.api.user.sources.routes import delete_source
        from docsgpt.vectorstore.index_lock import SourceBusy

        user = "u-del-busy-bool"
        src = _seed_source(pg_conn, user, name="faiss-src")

        @contextmanager
        def busy(*args, **kwargs):
            raise SourceBusy("busy")
            yield

        with _patch_db(pg_conn), patch("docsgpt.api.user.sources.access.source_index_lock", busy), patch(
            "docsgpt.api.user.sources.routes.StorageCreator.get_storage", return_value=MagicMock(),
        ), app.app_context():
            assert delete_source(user, src) is False


class TestRedirectToSources:
    def test_redirects(self, app):
        from docsgpt.api.user.sources.routes import RedirectToSources

        with app.test_request_context("/api/combine"):
            response = RedirectToSources().get()
        assert response.status_code == 301


class TestManageSync:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync", method="POST",
            json={"source_id": "x", "sync_frequency": "daily"},
        ):
            from flask import request
            request.decoded_token = None
            response = ManageSync().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from docsgpt.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSync().post()
        assert response.status_code == 400

    def test_returns_400_invalid_frequency(self, app):
        from docsgpt.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync",
            method="POST",
            json={"source_id": "x", "sync_frequency": "hourly"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSync().post()
        assert response.status_code == 400
        assert response.json["code"] == "bad_sync_frequency"
        assert response.json["error"] == response.json["message"]

    def test_returns_404_missing_source(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import ManageSync

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
        from docsgpt.api.user.sources.routes import ManageSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

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

    def test_a_wiki_cannot_be_scheduled(self, app, pg_conn):
        """A sync would replace a wiki's pages with the remote content."""
        from docsgpt.api.user.sources.routes import ManageSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        user = "u-sync-wiki"
        src = _seed_source(pg_conn, user, name="wiki", config={"kind": "wiki"})

        with _patch_db(pg_conn), app.test_request_context(
            "/api/manage_sync",
            method="POST",
            json={"source_id": str(src["id"]), "sync_frequency": "weekly"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSync().post()
        assert response.status_code == 400
        assert response.json["code"] == "wiki"
        assert response.json["error"] == response.json["message"]
        got = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert got["sync_frequency"] in (None, "never")

    def test_a_wiki_can_still_be_set_to_never(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import ManageSync
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        user = "u-sync-wiki-never"
        src = _seed_source(
            pg_conn, user, name="wiki", config={"kind": "wiki"},
            sync_frequency="weekly",
        )

        with _patch_db(pg_conn), app.test_request_context(
            "/api/manage_sync",
            method="POST",
            json={"source_id": str(src["id"]), "sync_frequency": "never"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSync().post()
        assert response.status_code == 200
        got = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert got["sync_frequency"] == "never"


class TestSyncSource:
    def test_returns_400_for_a_wiki(self, app, pg_conn):
        """Sync now on a wiki would replace its pages with the remote content."""
        from docsgpt.api.user.sources.routes import SyncSource

        user = "u-sync-now-wiki"
        src = _seed_source(
            pg_conn, user, name="wiki", type="crawler", config={"kind": "wiki"},
            remote_data=json.dumps({"url": "https://example.com"}),
        )

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.sync_source.delay",
        ) as mock_delay, app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()
        assert response.status_code == 400
        mock_delay.assert_not_called()
        # The connection drawer reads ``error``; ``code`` lets the UI word it.
        assert response.json["code"] == "wiki"
        assert response.json["error"] == response.json["message"]

    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import SyncSource

        with app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = None
            response = SyncSource().post()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.sources.routes import SyncSource

        with app.test_request_context(
            "/api/sync_source", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = SyncSource().post()
        assert response.status_code == 400

    def test_returns_404_inaccessible_source(self, app, pg_conn):
        # No ownership and no team grant: the source isn't visible → 404
        # (403 is reserved for a visible source the role can't change).
        from docsgpt.api.user.sources.routes import SyncSource

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
        from docsgpt.api.user.sources.routes import SyncSource

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
        assert response.json["code"] == "connector_source"
        assert response.json["error"] == response.json["message"]

    def test_returns_400_for_non_syncable(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SyncSource

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
        assert response.json == {
            "success": False,
            "error": "Source is not syncable",
            "message": "Source is not syncable",
            "code": "not_syncable",
        }

    def test_triggers_sync_task(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SyncSource

        user = "u-trigger"
        src = _seed_source(
            pg_conn, user, name="remote-src", type="github",
            remote_data=json.dumps({"provider": "github", "url": "x"}),
        )

        fake_task = MagicMock(id="task-123")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.sync_source.delay",
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

    def test_syncs_with_the_sources_connection(self, app, pg_conn):
        """A source synced from a connection (S3, GitHub) reads with that connection's keys."""
        from sqlalchemy import text

        from docsgpt.api.user.sources.routes import SyncSource

        user = "u-conn-sync"
        cid = str(pg_conn.execute(text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status) "
            "VALUES (:u, 'github', 'github', 'api_key', 'connected') RETURNING id"
        ), {"u": user}).scalar())
        src = _seed_source(
            pg_conn, user, name="repo", type="github",
            remote_data=json.dumps({"repo_url": "acme/private"}),
        )
        pg_conn.execute(text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = :s"),
                        {"c": cid, "s": src["id"]})

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.sync_source.delay",
            return_value=MagicMock(id="task-conn"),
        ) as mock_delay, app.test_request_context(
            "/api/sync_source", method="POST", json={"source_id": str(src["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SyncSource().post()

        assert response.status_code == 200
        assert mock_delay.call_args.kwargs["connection_id"] == cid
        assert mock_delay.call_args.kwargs["source_data"] == "acme/private"

    def test_normalizes_dict_remote_data_before_dispatch(self, app, pg_conn):
        """The route hands the sync task the Website config converted from the legacy row."""
        from docsgpt.api.user.sources.routes import SyncSource

        user = "u-normalize"
        src = _seed_source(
            pg_conn, user, name="crawl-src", type="crawler",
            remote_data=json.dumps(
                {"url": "https://example.com", "provider": "crawler"}
            ),
        )

        fake_task = MagicMock(id="task-norm")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.sync_source.delay",
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
        assert mock_delay.call_args.kwargs["source_data"]["entries"] == [{
            "url": "https://example.com", "mode": "site", "max_pages": 10, "path_prefix": "",
            "include_subdomains": False, "discovery": "links", "sitemap_url": None,
        }]
        assert mock_delay.call_args.kwargs["loader"] == "crawler"

    def test_sync_task_raises_returns_400(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SyncSource

        user = "u-fail"
        src = _seed_source(
            pg_conn, user, name="fail-src", type="github",
            remote_data=json.dumps({"provider": "github"}),
        )

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.sync_source.delay",
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
        from docsgpt.api.user.sources.routes import ReingestSource

        with app.test_request_context(
            "/api/sources/reingest", method="POST", json={"source_id": "x"}
        ):
            from flask import request
            request.decoded_token = None
            response = ReingestSource().post()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.sources.routes import ReingestSource

        with app.test_request_context(
            "/api/sources/reingest", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ReingestSource().post()
        assert response.status_code == 400

    def test_returns_404_inaccessible_source(self, app, pg_conn):
        # No ownership and no team grant: the source isn't visible → 404
        # (403 is reserved for a visible source the role can't change).
        from docsgpt.api.user.sources.routes import ReingestSource

        with _patch_db(pg_conn), app.test_request_context(
            "/api/sources/reingest",
            method="POST",
            json={"source_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ReingestSource().post()
        assert response.status_code == 404

    def test_a_failed_lookup_is_400_with_a_code(self, app, pg_conn):
        """Shaped and coded as /api/sync_source's refusal, so the UI words it."""
        from docsgpt.api.user.sources.routes import ReingestSource

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.load_source", side_effect=RuntimeError("db down"),
        ), app.test_request_context(
            "/api/sources/reingest", method="POST", json={"source_id": "x"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ReingestSource().post()
        assert response.status_code == 400
        assert response.json == {
            "success": False, "error": "Invalid source ID", "message": "Invalid source ID", "code": "invalid_source",
        }

    def test_triggers_reingest_task(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import ReingestSource

        user = "u-reingest"
        src = _seed_source(pg_conn, user, name="stalled-src", type="file")

        fake_task = MagicMock(id="reingest-task-1")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.reingest_source_task.delay",
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
        assert mock_delay.call_args.kwargs["idempotency_key"].startswith(
            f"reingest-source:{user}:{src['id']}:"
        )

    def test_each_reingest_gets_its_own_key_unless_the_client_names_one(self, app, pg_conn):
        """A per-source key would replay the last completed reingest for 24h
        instead of running a new one; a client's Idempotency-Key still
        collapses its own repeats.
        """
        from docsgpt.api.user.sources.routes import ReingestSource

        user = "u-reingest-again"
        src = _seed_source(pg_conn, user, name="again-src", type="file")

        def reingest(headers):
            with _patch_db(pg_conn), patch(
                "docsgpt.api.user.sources.routes.reingest_source_task.delay",
                return_value=MagicMock(id="t"),
            ) as mock_delay, app.test_request_context(
                "/api/sources/reingest", method="POST",
                json={"source_id": str(src["id"])}, headers=headers,
            ):
                from flask import request
                request.decoded_token = {"sub": user}
                assert ReingestSource().post().status_code == 200
            return mock_delay.call_args.kwargs["idempotency_key"]

        assert reingest({}) != reingest({})
        assert reingest({"Idempotency-Key": "k1"}) == reingest({"Idempotency-Key": "k1"})

    def test_team_editor_reingests_as_owner(self, app, pg_conn):
        """A team editor (not the owner) can reingest a shared source; the
        task dispatches AS the real owner so the owner-scoped pipeline and
        the owner-agnostic vector partition stay consistent.
        """
        import uuid

        from docsgpt.api.user.sources.routes import ReingestSource
        from docsgpt.storage.db.repositories.team_members import (
            TeamMembersRepository,
        )
        from docsgpt.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from docsgpt.storage.db.repositories.teams import TeamsRepository

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
            "docsgpt.api.user.sources.routes.reingest_source_task.delay",
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
        assert mock_delay.call_args.kwargs["idempotency_key"].startswith(
            f"reingest-source:{owner}:{sid}:"
        )

    def test_clears_stalled_ingest_progress_row(self, app, pg_conn):
        """Reingest drops the stale chunk-progress row so the sources
        list stops deriving a 'failed' ingest status for the source.
        """
        from docsgpt.api.user.sources.routes import ReingestSource

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
            "docsgpt.api.user.sources.routes.reingest_source_task.delay",
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
        from docsgpt.api.user.sources.routes import ReingestSource

        user = "u-reingest-fail"
        src = _seed_source(pg_conn, user, name="fail-src", type="file")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.routes.reingest_source_task.delay",
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


def _reingest(app, pg_conn, user, source_id, headers=None, mocks=None, **patches):
    """POST /api/sources/reingest with the sync and reingest tasks stubbed; returns (response, mocks).

    ``mocks["sync"]`` and ``mocks["connector"]`` are called with each queued
    task's kwargs; ``mocks["task_ids"]`` lists the task id each was queued
    under (``None`` when the route didn't pick one). Pass ``mocks`` back in to
    send a second request against the same stubs.
    """
    from docsgpt.api.user.sources.routes import ReingestSource

    if mocks is None:
        mocks = {
            "reingest": MagicMock(return_value=MagicMock(id="reingest-task")),
            "sync": MagicMock(return_value=MagicMock(id="sync-task")),
            "connector": MagicMock(return_value=MagicMock(id="connector-task")),
            "task_ids": [],
        }

    def _apply_async(name):
        def queue(kwargs=None, task_id=None, **_options):
            mocks["task_ids"].append(task_id)
            result = mocks[name](**(kwargs or {}))
            return MagicMock(id=task_id) if task_id else result

        return queue

    @contextmanager
    def _yield():
        yield pg_conn

    with _patch_db(pg_conn), patch("docsgpt.api.user.sources.upload.db_session", _yield), patch(
        "docsgpt.api.user.sources.upload.db_readonly", _yield,
    ), patch(
        "docsgpt.api.user.sources.routes.reingest_source_task.delay", mocks["reingest"],
    ), patch(
        "docsgpt.api.user.sources.routes.sync_source.apply_async", side_effect=_apply_async("sync"),
    ), patch(
        "docsgpt.api.user.sources.routes.ingest_connector_task.apply_async", side_effect=_apply_async("connector"),
    ), patch(
        "docsgpt.connectors.service.owner_sync_connection", patches.get("connection", MagicMock(return_value=None)),
    ), app.test_request_context(
        "/api/sources/reingest", method="POST", json={"source_id": source_id}, headers=headers or {},
    ):
        from flask import request
        request.decoded_token = {"sub": user}
        response = ReingestSource().post()
    return response, mocks


def _connection(pg_conn, user, provider="google_drive", source=None):
    """A connector session row for ``user``, linked to ``source`` when given; its id."""
    from sqlalchemy import text

    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    connection = str(ConnectorSessionsRepository(pg_conn).upsert(user, provider, status="authorized")["id"])
    if source is not None:
        pg_conn.execute(
            text("UPDATE sources SET connection_id = CAST(:c AS uuid) WHERE id = CAST(:s AS uuid)"),
            {"c": connection, "s": str(source["id"])},
        )
    return connection


class TestReingestARemoteSource:
    """A source with no stored files (Website, crawler, connector) is rebuilt by a sync of its stored config.

    The UI waits on the returned ``task_id``; the sync's events carry that id.
    """

    @pytest.mark.parametrize("type_, remote_data", [
        ("website", {"entries": [{"url": "https://docs.x.io/a", "mode": "page"}]}),
        ("crawler", {"urls": ["https://docs.x.io/"]}),
        ("url", "https://docs.x.io/a"),
    ])
    def test_queues_a_sync(self, app, pg_conn, type_, remote_data):
        user = "u-reingest-site"
        src = _seed_source(pg_conn, user, name="Docs", type=type_, remote_data=remote_data, sync_frequency="weekly")

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]))

        assert response.status_code == 200
        assert response.json == {"success": True, "task_id": "sync-task"}
        mocks["reingest"].assert_not_called()
        kwargs = mocks["sync"].call_args.kwargs
        assert kwargs["doc_id"] == str(src["id"]) and kwargs["user"] == user and kwargs["loader"] == type_
        assert kwargs["source_data"]

    def test_a_connector_source_queues_a_connector_sync(self, app, pg_conn):
        user = "u-reingest-drive"
        src = _seed_source(
            pg_conn, user, name="Drive", type="connector:file", sync_frequency="daily",
            remote_data={"provider": "google_drive", "file_ids": ["f1"], "folder_ids": ["d1"], "recursive": False},
        )
        linked = _connection(pg_conn, user, source=src)
        connection = MagicMock(return_value={"id": "conn-1"})

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]), connection=connection)

        assert response.status_code == 200
        assert response.json == {"success": True, "task_id": "connector-task"}
        mocks["reingest"].assert_not_called()
        kwargs = mocks["connector"].call_args.kwargs
        assert kwargs["operation_mode"] == "sync" and kwargs["doc_id"] == str(src["id"])
        assert kwargs["user"] == user and kwargs["connection_id"] == "conn-1"
        assert kwargs["source_type"] == "google_drive"
        assert kwargs["file_ids"] == ["f1"] and kwargs["folder_ids"] == ["d1"] and kwargs["recursive"] is False
        assert connection.call_args.args[1:4] == (user, "google_drive", linked)
        assert kwargs["actor_id"] == user

    def test_a_team_editors_connector_reingest_runs_as_the_owner_and_reaches_the_editor(self, app, pg_conn):
        import uuid

        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        owner, editor = "alice-reingest-drive", "bob-reingest-drive"
        src = _seed_source(
            pg_conn, owner, name="Drive", type="connector:file", remote_data={"provider": "google_drive"},
        )
        linked = _connection(pg_conn, owner, source=src)
        team = TeamsRepository(pg_conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)
        TeamMembersRepository(pg_conn).add_member(team["id"], editor, role="team_member")
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", str(src["id"]), owner_id=owner, granted_by=owner, access_level="editor",
        )

        response, mocks = _reingest(
            app, pg_conn, editor, str(src["id"]), connection=MagicMock(return_value={"id": linked}),
        )

        assert response.status_code == 200, response.json
        kwargs = mocks["connector"].call_args.kwargs
        assert kwargs["user"] == owner and kwargs["connection_id"] == linked
        assert kwargs["actor_id"] == editor

    def test_a_connector_source_without_a_usable_connection_is_refused(self, app, pg_conn):
        user = "u-reingest-drive-off"
        src = _seed_source(
            pg_conn, user, name="Drive", type="connector:file", remote_data={"provider": "google_drive"},
        )
        _connection(pg_conn, user, source=src)

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]))

        assert response.status_code == 409
        assert response.json["success"] is False and response.json["code"] == "reconnect_needed"
        mocks["connector"].assert_not_called()
        mocks["reingest"].assert_not_called()

    def test_a_connector_source_whose_connection_was_removed_is_refused(self, app, pg_conn):
        """As its Sync now: another of the owner's accounts must not read the selection and re-link it."""
        user = "u-reingest-drive-gone"
        _connection(pg_conn, user)  # another account for the provider
        src = _seed_source(
            pg_conn, user, name="Drive", type="connector:file", remote_data={"provider": "google_drive"},
        )
        connection = MagicMock(return_value={"id": "conn-other"})

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]), connection=connection)

        assert response.status_code == 409
        assert response.json["code"] == "connection_missing"
        assert response.json["error"] == (
            "This source's account connection was removed; connect the account again to sync it."
        )
        connection.assert_not_called()
        mocks["connector"].assert_not_called()
        mocks["reingest"].assert_not_called()

    def test_a_wiki_is_refused(self, app, pg_conn):
        user = "u-reingest-wiki"
        src = _seed_source(
            pg_conn, user, name="Docs", type="website", config={"kind": "wiki"},
            remote_data={"entries": [{"url": "https://docs.x.io/a", "mode": "page"}]},
        )

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]))

        assert response.status_code == 400 and response.json["code"] == "wiki"
        mocks["sync"].assert_not_called()
        mocks["reingest"].assert_not_called()

    def test_a_wiki_with_stored_files_is_refused(self, app, pg_conn):
        """A wiki converted from an upload keeps its files; re-reading them would replace the wiki's pages."""
        user = "u-reingest-upload-wiki"
        src = _seed_source(
            pg_conn, user, name="Notes", type="local", config={"kind": "wiki"}, file_path=f"inputs/{user}/notes",
        )

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]))

        assert response.status_code == 400 and response.json["code"] == "wiki"
        mocks["reingest"].assert_not_called()
        mocks["sync"].assert_not_called()

    def test_a_source_with_stored_files_still_reingests(self, app, pg_conn):
        user = "u-reingest-local"
        src = _seed_source(pg_conn, user, name="Files", type="local", file_path=f"inputs/{user}/files")

        response, mocks = _reingest(app, pg_conn, user, str(src["id"]))

        assert response.json == {"success": True, "task_id": "reingest-task"}
        mocks["sync"].assert_not_called()


class TestReingestARemoteSourceWithAnIdempotencyKey:
    """A rebuild honours the Idempotency-Key header as a reingest does: one key, one sync."""

    def _website(self, pg_conn, user):
        return _seed_source(
            pg_conn, user, name="Docs", type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/a", "mode": "page"}]},
        )

    def test_a_repeated_key_queues_one_sync_and_answers_its_task(self, app, pg_conn):
        user = "u-rebuild-key"
        src = self._website(pg_conn, user)
        headers = {"Idempotency-Key": "retry-1"}

        first, mocks = _reingest(app, pg_conn, user, str(src["id"]), headers=headers)
        second, mocks = _reingest(app, pg_conn, user, str(src["id"]), headers=headers, mocks=mocks)

        assert first.status_code == 200 and second.status_code == 200, (first.json, second.json)
        assert mocks["sync"].call_count == 1
        assert first.json["task_id"] == mocks["task_ids"][0]
        assert second.json == {"success": True, "task_id": first.json["task_id"]}

    def test_another_key_or_none_queues_another_sync(self, app, pg_conn):
        user = "u-rebuild-keys"
        src = self._website(pg_conn, user)

        _, mocks = _reingest(app, pg_conn, user, str(src["id"]), headers={"Idempotency-Key": "a"})
        _reingest(app, pg_conn, user, str(src["id"]), headers={"Idempotency-Key": "b"}, mocks=mocks)
        _reingest(app, pg_conn, user, str(src["id"]), mocks=mocks)
        _reingest(app, pg_conn, user, str(src["id"]), mocks=mocks)

        assert mocks["sync"].call_count == 4

    def test_a_connector_rebuild_carries_the_reingest_key(self, app, pg_conn):
        user = "u-rebuild-key-drive"
        src = _seed_source(
            pg_conn, user, name="Drive", type="connector:file", remote_data={"provider": "google_drive"},
        )
        linked = _connection(pg_conn, user, source=src)
        connection = MagicMock(return_value={"id": linked})
        headers = {"Idempotency-Key": "retry-2"}

        first, mocks = _reingest(app, pg_conn, user, str(src["id"]), headers=headers, connection=connection)
        second, mocks = _reingest(
            app, pg_conn, user, str(src["id"]), headers=headers, mocks=mocks, connection=connection,
        )

        assert mocks["connector"].call_count == 1
        assert mocks["connector"].call_args.kwargs["idempotency_key"] == f"reingest-source:{user}:{src['id']}:retry-2"
        assert second.json["task_id"] == first.json["task_id"] == mocks["task_ids"][0]

    def test_a_keyless_connector_rebuild_gets_a_key_of_its_own(self, app, pg_conn):
        user = "u-rebuild-nokey-drive"
        src = _seed_source(
            pg_conn, user, name="Drive", type="connector:file", remote_data={"provider": "google_drive"},
        )
        connection = MagicMock(return_value={"id": _connection(pg_conn, user, source=src)})

        _, mocks = _reingest(app, pg_conn, user, str(src["id"]), connection=connection)
        _reingest(app, pg_conn, user, str(src["id"]), mocks=mocks, connection=connection)

        keys = [call.kwargs["idempotency_key"] for call in mocks["connector"].call_args_list]
        assert len(set(keys)) == 2
        assert all(key.startswith(f"reingest-source:{user}:{src['id']}:") for key in keys)

    def test_a_failed_dispatch_frees_the_key_for_a_retry(self, app, pg_conn):
        user = "u-rebuild-key-retry"
        src = self._website(pg_conn, user)
        headers = {"Idempotency-Key": "retry-3"}
        mocks = {
            "reingest": MagicMock(),
            "sync": MagicMock(side_effect=[RuntimeError("broker down"), MagicMock(id="sync-task")]),
            "connector": MagicMock(),
            "task_ids": [],
        }

        failed, mocks = _reingest(app, pg_conn, user, str(src["id"]), headers=headers, mocks=mocks)
        retried, mocks = _reingest(app, pg_conn, user, str(src["id"]), headers=headers, mocks=mocks)

        assert failed.status_code == 400
        assert retried.status_code == 200
        assert mocks["sync"].call_count == 2
        assert retried.json["task_id"] == mocks["task_ids"][1]


class TestDirectoryStructure:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure?id=x"):
            from flask import request
            request.decoded_token = None
            response = DirectoryStructure().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DirectoryStructure().get()
        assert response.status_code == 400

    def test_returns_404_missing_doc(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import DirectoryStructure

        with _patch_db(pg_conn), app.test_request_context(
            "/api/directory_structure?id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DirectoryStructure().get()
        assert response.status_code == 404

    def test_returns_structure(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import DirectoryStructure

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

    def test_team_viewer_can_read(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import DirectoryStructure
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        owner, viewer = "u-dir-owner", "u-dir-viewer"
        src = _seed_source(
            pg_conn, owner, name="shared",
            directory_structure={"a.docx": {"type": "application/docx"}},
        )
        team = TeamsRepository(pg_conn).create("Acme", "acme-dir", owner)
        TeamMembersRepository(pg_conn).add_member(team["id"], viewer, role="team_member")
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", str(src["id"]), owner_id=owner, granted_by=owner,
            access_level="viewer",
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/directory_structure?id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = DirectoryStructure().get()
        assert response.status_code == 200
        assert response.json["directory_structure"] == {"a.docx": {"type": "application/docx"}}

    def test_non_owner_without_grant_404(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import DirectoryStructure

        src = _seed_source(
            pg_conn, "u-dir-owner2", name="private",
            directory_structure={"a.txt": None},
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/directory_structure?id={src['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": "u-dir-stranger"}
            response = DirectoryStructure().get()
        assert response.status_code == 404


class TestSourceConfigResource:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.routes import SourceConfigResource

        with app.test_request_context(
            "/api/sources/x/config", method="PATCH", json={}
        ):
            from flask import request
            request.decoded_token = None
            response = SourceConfigResource().patch("x")
        assert response.status_code == 401

    def test_invalid_config_rejected(self, app, pg_conn):
        # Strict-on-write: an unknown field fails validation → 400.
        from docsgpt.api.user.sources.routes import SourceConfigResource

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
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository

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

    def test_relevance_and_llm_screening_together_say_why(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.source_config import RELEVANCE_OR_PRESCREEN

        user = "u-cfg-both"
        src = _seed_source(pg_conn, user, name="cfg-both", type="file")
        body = {"retrieval": {"reranker": {"min_relevance": 0.3}, "prescreen": {"candidate_k": 40}}}
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{src['id']}/config", method="PATCH", json=body
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(str(src["id"]))
        assert response.status_code == 400
        assert response.json["message"] == RELEVANCE_OR_PRESCREEN

    def test_retrieval_alone_keeps_the_saved_chunking(self, app, pg_conn):
        # The retrieval test's "Save to source" sends only the retrieval settings.
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        user = "u-cfg-keep"
        src = _seed_source(pg_conn, user, name="cfg-keep", type="file")
        SourcesRepository(pg_conn).update(
            str(src["id"]), user, {"config": {"chunking": {"max_tokens": 800}, "graph": {"gleanings": 1}}}
        )
        reranker = {"type": "decision", "min_relevance": 0.3, "candidate_k": None}
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{src['id']}/config", method="PATCH", json={"retrieval": {"reranker": reranker}}
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(str(src["id"]))
        assert response.status_code == 200 and response.json["requires_reingest"] is False
        got = SourcesRepository(pg_conn).get_any(str(src["id"]), user)["config"]
        assert got["chunking"]["max_tokens"] == 800 and got["graph"]["gleanings"] == 1
        assert got["retrieval"]["reranker"] == reranker

    def test_chunking_change_requires_reingest(self, app, pg_conn):
        from docsgpt.api.user.sources.routes import SourceConfigResource

        user = "u-cfg-chunk"
        src = _seed_source(pg_conn, user, name="cfg-chunk", type="file", file_path="inputs/u-cfg-chunk/cfg-chunk")

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
        # The next reingest re-chunks every file, not only edited ones.
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        row = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert row["metadata"]["rechunk_pending"] is True

    def test_chunking_change_on_a_source_without_files_sets_no_flag(self, app, pg_conn):
        # Its reingest is a sync, which re-chunks everything anyway.
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        user = "u-cfg-chunk-web"
        src = _seed_source(pg_conn, user, name="cfg-web", type="website")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/sources/{src['id']}/config",
            method="PATCH",
            json={"chunking": {"max_tokens": 800}},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = SourceConfigResource().patch(str(src["id"]))

        assert response.json["requires_reingest"] is True
        row = SourcesRepository(pg_conn).get_any(str(src["id"]), user)
        assert "rechunk_pending" not in (row["metadata"] or {})

    def test_viewer_rejected(self, app, pg_conn):
        # A team VIEWER (not editor) cannot edit config → 403.
        import uuid

        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.repositories.team_members import (
            TeamMembersRepository,
        )
        from docsgpt.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from docsgpt.storage.db.repositories.teams import TeamsRepository

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

        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.repositories.team_members import (
            TeamMembersRepository,
        )
        from docsgpt.storage.db.repositories.team_resource_grants import (
            TeamResourceGrantsRepository,
        )
        from docsgpt.storage.db.repositories.teams import TeamsRepository

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
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository

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
        from docsgpt.storage.db.source_config import SourceConfig

        got = SourcesRepository(pg_conn).get_any(sid, user)
        assert SourceConfig.parse(got.get("config")).kind != "wiki"

    def test_other_edits_work_on_wiki_source(self, app, pg_conn):
        # A wiki source can still edit retrieval (kind stays wiki, no reject).
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository

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
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.source_config import SourceConfig

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
        from docsgpt.api.user.sources.routes import SourceConfigResource
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.source_config import SourceConfig

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
