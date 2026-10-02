"""Tests for docsgpt/api/user/sources/chunks.py."""

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
        "docsgpt.api.user.sources.chunks.db_readonly", _yield
    ):
        yield


def _seed_source(pg_conn, user="u", name="src"):
    from docsgpt.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create(name, user_id=user)


class TestResolveSource:
    def test_missing_raises_404(self, pg_conn):
        from docsgpt.api.user.resource_access import AccessDenied
        from docsgpt.api.user.sources.chunks import _resolve_source
        with _patch_db(pg_conn), pytest.raises(AccessDenied) as exc:
            _resolve_source("00000000-0000-0000-0000-000000000000", "u")
        assert exc.value.status == 404

    def test_returns_source_when_found(self, pg_conn):
        from docsgpt.api.user.sources.chunks import _resolve_source

        src = _seed_source(pg_conn, user="u-resolve")
        with _patch_db(pg_conn):
            got = _resolve_source(str(src["id"]), "u-resolve")
        assert got is not None
        assert str(got["id"]) == str(src["id"])

    def test_team_viewer_can_read_not_edit(self, pg_conn):
        from docsgpt.api.user.resource_access import AccessDenied
        from docsgpt.api.user.sources.chunks import _resolve_source
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        owner, viewer = "u-resolve-owner", "u-resolve-viewer"
        src = _seed_source(pg_conn, user=owner)
        team = TeamsRepository(pg_conn).create("Acme", "acme-chunks", owner)
        TeamMembersRepository(pg_conn).add_member(team["id"], viewer, role="team_member")
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", str(src["id"]), owner_id=owner, granted_by=owner,
            access_level="viewer",
        )
        with _patch_db(pg_conn):
            got = _resolve_source(str(src["id"]), viewer)
            with pytest.raises(AccessDenied) as edit:
                _resolve_source(str(src["id"]), viewer, "edit")
            with pytest.raises(AccessDenied) as stranger:
                _resolve_source(str(src["id"]), "u-resolve-stranger")
        assert str(got["id"]) == str(src["id"])
        assert edit.value.status == 403
        assert stranger.value.status == 404


class TestChunkMatchesPath:
    @pytest.mark.parametrize("metadata, path", [
        ({"source": "/a/b/file.txt"}, "b/file.txt"),
        ({"source": "file.txt"}, "file.txt"),
        ({"source": "https://x.io/guides/setup", "file_path": "guides/setup.md"}, "guides/setup.md"),
        ({"source": "https://github.com/o/r/blob/main/web/app.py", "title": "web/app.py"}, "web/app.py"),
        ({"source": "s3://bkt/docs/a.pdf", "key": "docs/a.pdf", "title": "a.pdf"}, "docs/a.pdf"),
        # Web and Reddit chunks carry no file_path/key: the tree keys them by title.
        ({"source": "https://docs.docsgpt.cloud/", "title": "Home - DocsGPT"}, "Home - DocsGPT"),
        ({"source": "https://reddit.com/r/x/comments/1", "title": "A post"}, "A post"),
    ])
    def test_matches(self, metadata, path):
        from docsgpt.api.user.sources.chunks import _chunk_matches_path
        assert _chunk_matches_path(metadata, path)

    @pytest.mark.parametrize("metadata, path", [
        ({"source": "/other.txt"}, "b/file.txt"),
        # Suffixes only match at a path boundary.
        ({"source": "docs/data.md"}, "a.md"),
        # Title only stands in for remote chunks the tree could not key by file_path/key.
        ({"source": "docs/readme.md", "title": "Readme"}, "Readme"),
        ({"source": "s3://bkt/docs/a.pdf", "key": "docs/a.pdf", "title": "Report"}, "Report"),
        ({"source": "https://x.io/a", "file_path": "a.md", "title": "A"}, "A"),
    ])
    def test_rejects(self, metadata, path):
        from docsgpt.api.user.sources.chunks import _chunk_matches_path
        assert not _chunk_matches_path(metadata, path)


class TestGetChunks:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.chunks import GetChunks

        with app.test_request_context("/api/get_chunks?id=abc"):
            from flask import request
            request.decoded_token = None
            response = GetChunks().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from docsgpt.api.user.sources.chunks import GetChunks

        with app.test_request_context("/api/get_chunks"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetChunks().get()
        assert response.status_code == 400

    def test_returns_400_on_resolve_error(self, app):
        from docsgpt.api.user.sources.chunks import GetChunks

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "docsgpt.api.user.sources.chunks.db_readonly", _broken
        ), app.test_request_context("/api/get_chunks?id=abc"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetChunks().get()
        assert response.status_code == 400

    def test_returns_404_when_source_missing(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import GetChunks

        with _patch_db(pg_conn), app.test_request_context(
            "/api/get_chunks?id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetChunks().get()
        assert response.status_code == 404

    def test_returns_paginated_chunks(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-chunks"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": f"chunk {i}", "metadata": {"title": f"T{i}"}}
            for i in range(5)
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
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
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-path"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": "a", "metadata": {"source": "/a/b/file.txt"}},
            {"text": "b", "metadata": {"source": "/other.txt"}},
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/get_chunks?id={src['id']}&path=b/file.txt"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 200
        assert response.json["total"] == 1

    def test_filters_title_keyed_web_page(self, app, pg_conn):
        # Single-URL sources ingested before WebLoader set ``file_path`` key
        # their only tree file by the page title; opening it must still list
        # the page's chunks without a re-ingest.
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-path-web"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": "home", "metadata": {
                "source": "https://docs.docsgpt.cloud/",
                "title": "Home - DocsGPT Documentation",
            }},
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/get_chunks?id={src['id']}&path=Home - DocsGPT Documentation"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 200
        assert response.json["total"] == 1

    def test_filters_by_search(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-srch"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"text": "the cat", "metadata": {"title": ""}},
            {"text": "a dog", "metadata": {"title": ""}},
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/get_chunks?id={src['id']}&search=cat"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 200
        assert response.json["total"] == 1

    def test_backfills_missing_token_count(self, app, pg_conn):
        # Chunks indexed before token_count was recorded (and any ingest path
        # that dropped it) came back without the key, so the UI printed "-".
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-tokens"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"doc_id": "a", "text": "hello world", "metadata": {}},
            {"doc_id": "b", "text": "second chunk", "metadata": None},
            {"doc_id": "c", "text": "third chunk", "metadata": {"token_count": 42}},
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(f"/api/get_chunks?id={src['id']}"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()

        assert response.status_code == 200
        chunks = response.json["chunks"]
        assert all(c["metadata"]["token_count"] > 0 for c in chunks)
        # An already-recorded count is left alone, whatever tokenizer produced it.
        assert chunks[2]["metadata"]["token_count"] == 42

    @pytest.mark.parametrize(
        "stored",
        ["", 0, -1, "abc", None, {"n": 1}, "inf", "-inf", "nan", float("inf")],
    )
    def test_recomputes_unusable_token_count(self, app, pg_conn, stored):
        from docsgpt.api.user.sources.chunks import GetChunks

        user = f"u-tok-{str(stored)[:6]}"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"doc_id": "a", "text": "some text here", "metadata": {"token_count": stored}}
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(f"/api/get_chunks?id={src['id']}"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()

        assert response.status_code == 200
        assert response.json["chunks"][0]["metadata"]["token_count"] > 0

    def test_keeps_numeric_string_token_count(self, app, pg_conn):
        # Some stores round-trip metadata values as strings; a usable count
        # there is still a count and must not be recomputed.
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-tok-str"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"doc_id": "a", "text": "some text here", "metadata": {"token_count": "17"}}
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(f"/api/get_chunks?id={src['id']}"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()

        assert response.json["chunks"][0]["metadata"]["token_count"] == "17"

    def test_backfills_only_the_requested_page(self, app, pg_conn):
        # Counting is per-response work, so it must not run over chunks the
        # caller never sees.
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-tok-page"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"doc_id": str(i), "text": f"chunk number {i}", "metadata": {}}
            for i in range(10)
        ]

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), patch(
            "docsgpt.api.user.sources.chunks.num_tokens_from_string",
            return_value=7,
        ) as counter, app.test_request_context(
            f"/api/get_chunks?id={src['id']}&per_page=2&page=1"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()

        assert response.status_code == 200
        assert counter.call_count == 2
        assert [c["metadata"]["token_count"] for c in response.json["chunks"]] == [7, 7]

    def test_returns_500_on_vector_store_error(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import GetChunks

        user = "u-err"
        src = _seed_source(pg_conn, user=user)

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(f"/api/get_chunks?id={src['id']}"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetChunks().get()
        assert response.status_code == 500


class TestAddChunk:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST",
            json={"id": "x", "text": "hello"},
        ):
            from flask import request
            request.decoded_token = None
            response = AddChunk().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from docsgpt.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST", json={"id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AddChunk().post()
        assert response.status_code == 400

    def test_returns_404_inaccessible_source(self, app, pg_conn):
        # No ownership and no team grant: the source isn't visible → 404
        # (403 is reserved for a visible source the role can't change).
        from docsgpt.api.user.sources.chunks import AddChunk

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
        from docsgpt.api.user.sources.chunks import AddChunk

        user = "u-add"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.add_chunk.return_value = "chunk-id-1"

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
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
        from docsgpt.api.user.sources.chunks import AddChunk

        user = "u-adderr"
        src = _seed_source(pg_conn, user=user)

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
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
        from docsgpt.api.user.sources.chunks import DeleteChunk

        with app.test_request_context(
            "/api/delete_chunk?id=x&chunk_id=y", method="DELETE"
        ):
            from flask import request
            request.decoded_token = None
            response = DeleteChunk().delete()
        assert response.status_code == 401

    def test_returns_404_inaccessible_source(self, app, pg_conn):
        # No ownership and no team grant: the source isn't visible → 404
        # (403 is reserved for a visible source the role can't change).
        from docsgpt.api.user.sources.chunks import DeleteChunk

        with _patch_db(pg_conn), app.test_request_context(
            "/api/delete_chunk?id=00000000-0000-0000-0000-000000000000&chunk_id=c",
            method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteChunk().delete()
        assert response.status_code == 404

    def test_deletes_chunk(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import DeleteChunk

        user = "u-del"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.delete_chunk.return_value = True

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            f"/api/delete_chunk?id={src['id']}&chunk_id=c", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteChunk().delete()
        assert response.status_code == 200

    def test_returns_404_chunk_not_found(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import DeleteChunk

        user = "u-missing-chunk"
        src = _seed_source(pg_conn, user=user)

        fake_store = MagicMock()
        fake_store.delete_chunk.return_value = False

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
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
        from docsgpt.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": "x", "chunk_id": "c"},
        ):
            from flask import request
            request.decoded_token = None
            response = UpdateChunk().put()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from docsgpt.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT", json={"id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateChunk().put()
        assert response.status_code == 400

    def test_returns_404_inaccessible_source(self, app, pg_conn):
        # No ownership and no team grant: the source isn't visible → 404
        # (403 is reserved for a visible source the role can't change).
        from docsgpt.api.user.sources.chunks import UpdateChunk

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
        from docsgpt.api.user.sources.chunks import UpdateChunk

        user = "u-upd-missing"
        src = _seed_source(pg_conn, user=user)
        fake_store = MagicMock()
        fake_store.get_chunks.return_value = []

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
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
        from docsgpt.api.user.sources.chunks import UpdateChunk

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
        fake_store.update_chunk.return_value = "chunk-123"

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
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
        assert response.json == {
            "message": "Chunk updated successfully",
            "chunk_id": "chunk-123",
            "original_chunk_id": "chunk-123",
        }
        fake_store.update_chunk.assert_called_once()
        chunk_id, new_text, new_metadata = fake_store.update_chunk.call_args[0]
        assert (chunk_id, new_text) == ("chunk-123", "new text")
        assert new_metadata["title"] == "T"
        assert new_metadata["token_count"] > 0
        fake_store.add_chunk.assert_not_called()
        fake_store.delete_chunk.assert_not_called()

    def test_update_failure_returns_500(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import UpdateChunk

        user = "u-upd-fail"
        src = _seed_source(pg_conn, user=user)
        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"doc_id": "chunk-123", "text": "old", "metadata": {}}
        ]
        fake_store.update_chunk.side_effect = RuntimeError("embed down")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": str(src["id"]), "chunk_id": "chunk-123", "text": "new"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateChunk().put()
        assert response.status_code == 500
        assert response.json == {"error": "Failed to update chunk - addition failed"}


    def test_invalid_metadata_keys_return_400(self, app, pg_conn):
        from docsgpt.api.user.sources.chunks import UpdateChunk
        from docsgpt.vectorstore.base import InvalidChunkMetadataError

        user = "u-upd-bad-meta"
        src = _seed_source(pg_conn, user=user)
        fake_store = MagicMock()
        fake_store.get_chunks.return_value = [
            {"doc_id": "chunk-123", "text": "old", "metadata": {}}
        ]
        fake_store.update_chunk.side_effect = InvalidChunkMetadataError(
            "Metadata key 'a.b' is not allowed"
        )

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={
                "id": str(src["id"]),
                "chunk_id": "chunk-123",
                "metadata": {"a.b": 1},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateChunk().put()
        assert response.status_code == 400
        # Generic message; the offending key is only logged.
        assert response.json == {"error": "Invalid metadata"}


class TestUpdateChunkGraphLinks:
    """A store that re-ids an edited chunk must take the graph links with it."""

    def _put(self, app, pg_conn, src, user, graph_store, fake_store=None):
        from docsgpt.api.user.sources.chunks import UpdateChunk

        if fake_store is None:
            fake_store = MagicMock()
            # The base fallback: the edit comes back under a new id.
            fake_store.update_chunk.return_value = "chunk-new"
        fake_store.get_chunks.return_value = [
            {"doc_id": "chunk-old", "text": "old", "metadata": {}}
        ]
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.chunks.get_vector_store",
            return_value=fake_store,
        ), patch(
            "docsgpt.graphrag.store.GraphStore", return_value=graph_store
        ), app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": str(src["id"]), "chunk_id": "chunk-old", "text": "new"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            return UpdateChunk().put()

    def _graph_source(self, pg_conn, user):
        from docsgpt.storage.db.repositories.sources import SourcesRepository
        from docsgpt.storage.db.source_config import SourceConfig

        return SourcesRepository(pg_conn).create(
            "g", user_id=user, config=SourceConfig.parse({}).graph_enabled()
        )

    def test_graphrag_source_remaps_links_to_the_new_chunk(self, app, pg_conn):
        user = "u-upd-graph"
        src = self._graph_source(pg_conn, user)
        graph_store = MagicMock()

        response = self._put(app, pg_conn, src, user, graph_store)

        assert response.status_code == 200
        graph_store.remap_chunk.assert_called_once_with(
            str(src["id"]), "chunk-old", "chunk-new"
        )

    def test_classic_source_skips_the_graph(self, app, pg_conn):
        user = "u-upd-classic"
        src = _seed_source(pg_conn, user=user)
        graph_store = MagicMock()

        response = self._put(app, pg_conn, src, user, graph_store)

        assert response.status_code == 200
        graph_store.remap_chunk.assert_not_called()

    def test_remap_failure_keeps_the_saved_edit(self, app, pg_conn):
        user = "u-upd-graph-fail"
        src = self._graph_source(pg_conn, user)
        graph_store = MagicMock()
        graph_store.remap_chunk.side_effect = RuntimeError("boom")

        response = self._put(app, pg_conn, src, user, graph_store)

        assert response.status_code == 200
        assert response.json["chunk_id"] == "chunk-new"

    def test_in_place_update_skips_the_graph_remap(self, app, pg_conn):
        user = "u-upd-graph-inplace"
        src = self._graph_source(pg_conn, user)
        graph_store = MagicMock()
        fake_store = MagicMock()
        fake_store.update_chunk.return_value = "chunk-old"

        response = self._put(app, pg_conn, src, user, graph_store, fake_store)

        assert response.status_code == 200
        assert response.json["chunk_id"] == "chunk-old"
        assert response.json["original_chunk_id"] == "chunk-old"
        graph_store.remap_chunk.assert_not_called()

    def test_default_fallback_store_remaps_to_the_new_id(self, app, pg_conn):
        """A store without its own update (e.g. Milvus) re-adds and re-ids."""
        from docsgpt.vectorstore.base import BaseVectorStore

        class _FallbackStore(BaseVectorStore):
            def __init__(self):
                super().__init__()
                self.deleted = []

            def search(self, *args, **kwargs):
                return []

            def add_texts(self, texts, metadatas=None, *args, **kwargs):
                return []

            def get_chunks(self):
                return [{"doc_id": "chunk-old", "text": "old", "metadata": {}}]

            def add_chunk(self, text, metadata=None):
                return "chunk-new"

            def delete_chunk(self, chunk_id):
                self.deleted.append(chunk_id)
                return True

        user = "u-upd-graph-fallback"
        src = self._graph_source(pg_conn, user)
        graph_store = MagicMock()
        store = _FallbackStore()
        store_proxy = MagicMock(wraps=store)

        response = self._put(app, pg_conn, src, user, graph_store, store_proxy)

        assert response.status_code == 200
        assert response.json["chunk_id"] == "chunk-new"
        assert store.deleted == ["chunk-old"]
        graph_store.remap_chunk.assert_called_once_with(
            str(src["id"]), "chunk-old", "chunk-new"
        )

    def test_default_fallback_failed_delete_returns_500_without_duplicate(self, app, pg_conn):
        """A failed old-chunk delete rolls the new chunk back and fails the request."""
        from docsgpt.vectorstore.base import BaseVectorStore

        class _FallbackStore(BaseVectorStore):
            def __init__(self):
                super().__init__()
                self.deleted = []

            def search(self, *args, **kwargs):
                return []

            def add_texts(self, texts, metadatas=None, *args, **kwargs):
                return []

            def get_chunks(self):
                return [{"doc_id": "chunk-old", "text": "old", "metadata": {}}]

            def add_chunk(self, text, metadata=None):
                return "chunk-new"

            def delete_chunk(self, chunk_id):
                self.deleted.append(chunk_id)
                return chunk_id != "chunk-old"

        user = "u-upd-graph-fallback-fail"
        src = self._graph_source(pg_conn, user)
        graph_store = MagicMock()
        store = _FallbackStore()
        store_proxy = MagicMock(wraps=store)

        response = self._put(app, pg_conn, src, user, graph_store, store_proxy)

        assert response.status_code == 500
        assert store.deleted == ["chunk-old", "chunk-new"]
        graph_store.remap_chunk.assert_not_called()


KEY = "0123456789abcdef" * 2


def _get_by_key(app, pg_conn, source_id, user, key=KEY, store=None):
    from docsgpt.api.user.sources.chunks import ChunkByKey

    with _patch_db(pg_conn), patch(
        "docsgpt.api.user.sources.chunks.get_vector_store",
        return_value=store or MagicMock(),
    ) as get_store, app.test_request_context(
        f"/api/sources/{source_id}/chunk?chunk_key={key}"
    ):
        from flask import request
        request.decoded_token = {"sub": user} if user else None
        response = ChunkByKey().get(str(source_id))
    return response, get_store


class TestChunkByKey:
    """The chunk behind a citation, found again by its content key."""

    def test_returns_401_unauthenticated(self, app, pg_conn):
        response, _ = _get_by_key(app, pg_conn, "s", None)
        assert response.status_code == 401

    @pytest.mark.parametrize("key", ["", "nothex" * 6, "ABC", KEY + "0"])
    def test_rejects_a_malformed_key(self, app, pg_conn, key):
        response, get_store = _get_by_key(app, pg_conn, "s", "u", key=key)
        assert response.status_code == 400
        get_store.assert_not_called()

    def test_accepts_an_uppercase_key(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-key")
        store = MagicMock()
        store.get_chunk_by_key.return_value = {"doc_id": "7", "text": "t", "metadata": {}}
        response, _ = _get_by_key(app, pg_conn, src["id"], "u-key", key=KEY.upper(), store=store)
        assert response.status_code == 200
        store.get_chunk_by_key.assert_called_once_with(KEY)

    def test_a_source_the_caller_cannot_see_is_404_and_never_queried(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-owner")
        response, get_store = _get_by_key(app, pg_conn, src["id"], "u-stranger")
        assert response.status_code == 404
        get_store.assert_not_called()

    def test_a_chunk_that_is_gone_is_404(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-key")
        store = MagicMock()
        store.get_chunk_by_key.return_value = None
        response, _ = _get_by_key(app, pg_conn, src["id"], "u-key", store=store)
        assert response.status_code == 404
        assert response.json["message"] == "Chunk not found"

    def test_a_store_failure_is_500_not_gone(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-key")
        store = MagicMock()
        store.get_chunk_by_key.side_effect = RuntimeError("down")
        response, _ = _get_by_key(app, pg_conn, src["id"], "u-key", store=store)
        assert response.status_code == 500

    def test_returns_the_chunk_and_what_the_reader_needs_about_its_source(self, app, pg_conn):
        src = _seed_source(pg_conn, user="u-key", name="Occupancy survey")
        store = MagicMock()
        store.get_chunk_by_key.return_value = {
            "doc_id": "7", "text": "full passage", "metadata": {"source": "a.pdf"},
        }
        response, get_store = _get_by_key(app, pg_conn, src["id"], "u-key", store=store)

        assert response.status_code == 200
        body = response.json
        get_store.assert_called_once_with(str(src["id"]))
        assert body["chunk"]["doc_id"] == "7"
        assert body["chunk"]["text"] == "full passage"
        # Filled in for the reader's length row, as the chunk browser does.
        assert body["chunk"]["metadata"]["token_count"] > 0
        assert body["source"]["id"] == str(src["id"])
        assert body["source"]["name"] == "Occupancy survey"
        assert body["source"]["kind"] == "classic"
        assert body["source"]["isNested"] is False
        assert body["source"]["access"] == "owner"
        assert "edit" in body["source"]["allowed_actions"]
        assert body["page_path"] is None

    def test_wiki_chunks_carry_their_page_path(self, app, pg_conn):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        src = SourcesRepository(pg_conn).create("Guide", user_id="u-wiki", type="wiki", config={"kind": "wiki"})
        store = MagicMock()
        store.get_chunk_by_key.return_value = {
            "doc_id": "7", "text": "p", "metadata": {"source": "/guide/levy.md"},
        }
        response, _ = _get_by_key(app, pg_conn, src["id"], "u-wiki", store=store)
        assert response.json["source"]["kind"] == "wiki"
        assert response.json["page_path"] == "/guide/levy.md"

    def test_a_team_viewer_can_read_but_not_edit(self, app, pg_conn):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        owner, viewer = "u-key-owner", "u-key-viewer"
        src = _seed_source(pg_conn, user=owner)
        team = TeamsRepository(pg_conn).create("Acme", "acme-cite", owner)
        TeamMembersRepository(pg_conn).add_member(team["id"], viewer, role="team_member")
        TeamResourceGrantsRepository(pg_conn).grant(
            team["id"], "source", str(src["id"]), owner_id=owner, granted_by=owner,
            access_level="viewer",
        )
        store = MagicMock()
        store.get_chunk_by_key.return_value = {"doc_id": "7", "text": "t", "metadata": {}}
        response, _ = _get_by_key(app, pg_conn, src["id"], viewer, store=store)
        assert response.status_code == 200
        assert response.json["source"]["access"] == "viewer"
        assert "edit" not in response.json["source"]["allowed_actions"]
