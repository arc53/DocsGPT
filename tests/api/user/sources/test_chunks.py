"""Tests for application/api/user/sources/chunks.py."""

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
        "application.api.user.sources.chunks.db_readonly", _yield
    ):
        yield


def _seed_source(pg_conn, user="u", name="src"):
    from application.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create(name, user_id=user)


class TestResolveSource:
    def test_returns_none_for_missing(self, pg_conn):
        from application.api.user.sources.chunks import _resolve_source
        with _patch_db(pg_conn):
            assert (
                _resolve_source(
                    "00000000-0000-0000-0000-000000000000", "u"
                )
                is None
            )

    def test_returns_source_when_found(self, pg_conn):
        from application.api.user.sources.chunks import _resolve_source

        src = _seed_source(pg_conn, user="u-resolve")
        with _patch_db(pg_conn):
            got = _resolve_source(str(src["id"]), "u-resolve")
        assert got is not None
        assert str(got["id"]) == str(src["id"])


class TestGetChunks:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import GetChunks

        with app.test_request_context("/api/get_chunks?id=abc"):
            from flask import request
            request.decoded_token = None
            response = GetChunks().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.sources.chunks import GetChunks

        with app.test_request_context("/api/get_chunks"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetChunks().get()
        assert response.status_code == 400

    def test_returns_400_on_resolve_error(self, app):
        from application.api.user.sources.chunks import GetChunks

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.sources.chunks.db_readonly", _broken
        ), app.test_request_context("/api/get_chunks?id=abc"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetChunks().get()
        assert response.status_code == 400

    def test_returns_404_when_source_missing(self, app, pg_conn):
        from application.api.user.sources.chunks import GetChunks

        with _patch_db(pg_conn), app.test_request_context(
            "/api/get_chunks?id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetChunks().get()
        assert response.status_code == 404

    def test_returns_paginated_chunks(self, app, pg_conn):
        from application.api.user.sources.chunks import GetChunks

        user = "u-chunks"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": f"chunk {i}", "metadata": {"title": f"T{i}"}}
            for i in range(5)
        ]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/get_chunks?id={src['id']}&per_page=2&page=1"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 200
        data = response.json
        assert data["total"] == 5
        assert len(data["chunks"]) == 2

    def test_filters_by_path(self, app, pg_conn):
        from application.api.user.sources.chunks import GetChunks

        user = "u-path"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": "a", "metadata": {"source": "/a/b/file.txt"}},
            {"text": "b", "metadata": {"source": "/other.txt"}},
        ]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/get_chunks?id={src['id']}&path=b/file.txt"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 200
        assert response.json["total"] == 1

    def test_filters_by_search(self, app, pg_conn):
        from application.api.user.sources.chunks import GetChunks

        user = "u-srch"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": "the cat", "metadata": {"title": ""}},
            {"text": "a dog", "metadata": {"title": ""}},
        ]

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/get_chunks?id={src['id']}&search=cat"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 200
        assert response.json["total"] == 1

    def test_returns_500_on_vector_store_error(self, app, pg_conn):
        from application.api.user.sources.chunks import GetChunks

        user = "u-err"
        src = _seed_source(pg_conn, user=user)

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(f"/api/get_chunks?id={src['id']}"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 500


class TestAddChunk:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST",
            json={"id": "x", "text": "hello"},
        ):
            from flask import request
            request.decoded_token = None
            response = AddChunk().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST", json={"id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AddChunk().post()
        assert response.status_code == 400

    def test_returns_404_source_not_found(self, app, pg_conn):
        from application.api.user.sources.chunks import AddChunk

        with _patch_db(pg_conn), app.test_request_context(
            "/api/add_chunk", method="POST",
            json={
                "id": "00000000-0000-0000-0000-000000000000",
                "text": "content",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AddChunk().post()
        assert response.status_code == 404

    def test_adds_chunk(self, app, pg_conn):
        from application.api.user.sources.chunks import AddChunk

        user = "u-add"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.add_chunk.return_value = "chunk-id-1"

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            "/api/add_chunk", method="POST",
            json={
                "id": str(src["id"]),
                "text": "the text of the chunk",
                "metadata": {"title": "My Chunk"},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AddChunk().post()
        assert response.status_code == 201
        assert response.json["chunk_id"] == "chunk-id-1"

    def test_returns_500_on_vector_error(self, app, pg_conn):
        from application.api.user.sources.chunks import AddChunk

        user = "u-adderr"
        src = _seed_source(pg_conn, user=user)

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            side_effect=RuntimeError("bad"),
        ), app.test_request_context(
            "/api/add_chunk", method="POST",
            json={"id": str(src["id"]), "text": "x"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AddChunk().post()
        assert response.status_code == 500


class TestDeleteChunk:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        with app.test_request_context(
            "/api/delete_chunk?id=x&chunk_id=y", method="DELETE"
        ):
            from flask import request
            request.decoded_token = None
            response = DeleteChunk().delete()
        assert response.status_code == 401

    def test_returns_404_source_not_found(self, app, pg_conn):
        from application.api.user.sources.chunks import DeleteChunk

        with _patch_db(pg_conn), app.test_request_context(
            "/api/delete_chunk?id=00000000-0000-0000-0000-000000000000&chunk_id=c",
            method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteChunk().delete()
        assert response.status_code == 404

    def test_deletes_chunk(self, app, pg_conn):
        from application.api.user.sources.chunks import DeleteChunk

        user = "u-del"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.delete_chunk.return_value = True

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/delete_chunk?id={src['id']}&chunk_id=c", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteChunk().delete()
        assert response.status_code == 200

    def test_returns_404_chunk_not_found(self, app, pg_conn):
        from application.api.user.sources.chunks import DeleteChunk

        user = "u-missing-chunk"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.delete_chunk.return_value = False

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/delete_chunk?id={src['id']}&chunk_id=c", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteChunk().delete()
        assert response.status_code == 404


class TestUpdateChunk:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": "x", "chunk_id": "c"},
        ):
            from flask import request
            request.decoded_token = None
            response = UpdateChunk().put()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT", json={"id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateChunk().put()
        assert response.status_code == 400

    def test_returns_404_source_not_found(self, app, pg_conn):
        from application.api.user.sources.chunks import UpdateChunk

        with _patch_db(pg_conn), app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={
                "id": "00000000-0000-0000-0000-000000000000",
                "chunk_id": "c",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateChunk().put()
        assert response.status_code == 404

    def test_returns_404_chunk_not_found(self, app, pg_conn):
        from application.api.user.sources.chunks import UpdateChunk

        user = "u-upd-missing"
        src = _seed_source(pg_conn, user=user)
        fake_store = MagicMock()
        fake_store.get_chunks.return_value = []

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": str(src["id"]), "chunk_id": "missing"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateChunk().put()
        assert response.status_code == 404

    def test_updates_chunk(self, app, pg_conn):
        from application.api.user.sources.chunks import UpdateChunk

        user = "u-upd"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {
                "doc_id": "chunk-123",
                "text": "old",
                "metadata": {"title": "T"},
            }
        ]
        fake_store.add_chunk.return_value = "new-chunk-id"
        fake_store.delete_chunk.return_value = True

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={
                "id": str(src["id"]),
                "chunk_id": "chunk-123",
                "text": "new text",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateChunk().put()
        assert response.status_code == 200
        assert response.json["chunk_id"] == "new-chunk-id"
