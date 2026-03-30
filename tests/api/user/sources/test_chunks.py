"""Tests for source chunk management routes."""

import pytest
from unittest.mock import Mock, patch
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


def _status(response):
    if isinstance(response, tuple):
        return response[1]
    return response.status_code


def _json(response):
    if isinstance(response, tuple):
        return response[0].json
    return response.json


# ---------------------------------------------------------------------------
# GetChunks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetChunks:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import GetChunks

        with app.test_request_context("/api/get_chunks?id=abc"):
            from flask import request

            request.decoded_token = None
            response = GetChunks().get()

        assert _status(response) == 401

    def test_returns_400_for_invalid_doc_id(self, app):
        from application.api.user.sources.chunks import GetChunks

        with app.test_request_context("/api/get_chunks?id=invalid"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetChunks().get()

        assert _status(response) == 400
        assert "Invalid doc_id" in _json(response)["error"]

    def test_returns_404_when_doc_not_found(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(f"/api/get_chunks?id={doc_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetChunks().get()

        assert _status(response) == 404
        assert "not found" in _json(response)["error"]

    def test_returns_paginated_chunks(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}

        chunks = [
            {"text": f"chunk {i}", "metadata": {}, "doc_id": f"c{i}"}
            for i in range(25)
        ]
        mock_store = Mock()
        mock_store.get_chunks.return_value = chunks

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/get_chunks?id={doc_id}&page=2&per_page=10"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        assert _status(response) == 200
        data = _json(response)
        assert data["total"] == 25
        assert data["page"] == 2
        assert data["per_page"] == 10
        assert len(data["chunks"]) == 10

    def test_filters_chunks_by_path(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}

        chunks = [
            {"text": "a", "metadata": {"source": "inputs/dir/file.pdf"}, "doc_id": "c1"},
            {"text": "b", "metadata": {"source": "inputs/other.txt"}, "doc_id": "c2"},
            {"text": "c", "metadata": {"file_path": "guides/setup.md"}, "doc_id": "c3"},
        ]
        mock_store = Mock()
        mock_store.get_chunks.return_value = chunks

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/get_chunks?id={doc_id}&path=file.pdf"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        data = _json(response)
        assert data["total"] == 1
        assert data["chunks"][0]["text"] == "a"
        assert data["path"] == "file.pdf"

    def test_filters_chunks_by_file_path_metadata(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}

        chunks = [
            {"text": "a", "metadata": {"source": "inputs/dir/file.pdf"}, "doc_id": "c1"},
            {"text": "c", "metadata": {"file_path": "guides/setup.md"}, "doc_id": "c3"},
        ]
        mock_store = Mock()
        mock_store.get_chunks.return_value = chunks

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/get_chunks?id={doc_id}&path=setup.md"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        data = _json(response)
        assert data["total"] == 1
        assert data["chunks"][0]["text"] == "c"

    def test_filters_chunks_by_search_term(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}

        chunks = [
            {"text": "Python is great", "metadata": {"title": "intro"}, "doc_id": "c1"},
            {"text": "Java tutorial", "metadata": {"title": "java guide"}, "doc_id": "c2"},
            {"text": "Hello world", "metadata": {"title": "Python Basics"}, "doc_id": "c3"},
        ]
        mock_store = Mock()
        mock_store.get_chunks.return_value = chunks

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/get_chunks?id={doc_id}&search=python"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        data = _json(response)
        assert data["total"] == 2
        assert data["search"] == "python"

    def test_combines_path_and_search_filters(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}

        chunks = [
            {"text": "Python intro", "metadata": {"source": "dir/intro.md", "title": ""}, "doc_id": "c1"},
            {"text": "Python deep", "metadata": {"source": "dir/deep.md", "title": ""}, "doc_id": "c2"},
            {"text": "Java intro", "metadata": {"source": "dir/intro.md", "title": ""}, "doc_id": "c3"},
        ]
        mock_store = Mock()
        mock_store.get_chunks.return_value = chunks

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/get_chunks?id={doc_id}&path=intro.md&search=python"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        data = _json(response)
        assert data["total"] == 1
        assert data["chunks"][0]["doc_id"] == "c1"

    def test_returns_500_on_store_error(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.side_effect = Exception("Store error")

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(f"/api/get_chunks?id={doc_id}"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        assert _status(response) == 500

    def test_no_path_or_search_returns_null_fields(self, app):
        from application.api.user.sources.chunks import GetChunks

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.return_value = []

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(f"/api/get_chunks?id={doc_id}"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = GetChunks().get()

        data = _json(response)
        assert data["path"] is None
        assert data["search"] is None


# ---------------------------------------------------------------------------
# AddChunk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddChunk:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST", json={"id": "abc", "text": "hi"}
        ):
            from flask import request

            request.decoded_token = None
            response = AddChunk().post()

        assert _status(response) == 401

    def test_returns_400_missing_required_fields(self, app):
        from application.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST", json={"id": str(ObjectId())}
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = AddChunk().post()

        # check_required_fields returns a tuple (response, status)
        assert response is not None

    def test_returns_400_for_invalid_doc_id(self, app):
        from application.api.user.sources.chunks import AddChunk

        with app.test_request_context(
            "/api/add_chunk", method="POST", json={"id": "bad", "text": "hi"}
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = AddChunk().post()

        assert _status(response) == 400
        assert "Invalid doc_id" in _json(response)["error"]

    def test_returns_404_when_doc_not_found(self, app):
        from application.api.user.sources.chunks import AddChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/add_chunk", method="POST",
                json={"id": doc_id, "text": "hello"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = AddChunk().post()

        assert _status(response) == 404

    def test_adds_chunk_successfully(self, app):
        from application.api.user.sources.chunks import AddChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.add_chunk.return_value = "new-chunk-id"

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ), patch(
            "application.api.user.sources.chunks.num_tokens_from_string",
            return_value=5,
        ):
            with app.test_request_context(
                "/api/add_chunk", method="POST",
                json={"id": doc_id, "text": "hello world"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = AddChunk().post()

        assert _status(response) == 201
        data = _json(response)
        assert data["chunk_id"] == "new-chunk-id"
        assert "successfully" in data["message"]
        call_args = mock_store.add_chunk.call_args
        assert call_args[0][0] == "hello world"
        assert call_args[0][1]["token_count"] == 5

    def test_adds_chunk_with_custom_metadata(self, app):
        from application.api.user.sources.chunks import AddChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.add_chunk.return_value = "cid"

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ), patch(
            "application.api.user.sources.chunks.num_tokens_from_string",
            return_value=3,
        ):
            with app.test_request_context(
                "/api/add_chunk", method="POST",
                json={
                    "id": doc_id,
                    "text": "hi",
                    "metadata": {"source": "test.pdf"},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = AddChunk().post()

        assert _status(response) == 201
        meta = mock_store.add_chunk.call_args[0][1]
        assert meta["source"] == "test.pdf"
        assert meta["token_count"] == 3

    def test_returns_500_on_store_error(self, app):
        from application.api.user.sources.chunks import AddChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.add_chunk.side_effect = Exception("fail")

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ), patch(
            "application.api.user.sources.chunks.num_tokens_from_string",
            return_value=1,
        ):
            with app.test_request_context(
                "/api/add_chunk", method="POST",
                json={"id": doc_id, "text": "hello"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = AddChunk().post()

        assert _status(response) == 500


# ---------------------------------------------------------------------------
# DeleteChunk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteChunk:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        with app.test_request_context("/api/delete_chunk?id=abc&chunk_id=xyz"):
            from flask import request

            request.decoded_token = None
            response = DeleteChunk().delete()

        assert _status(response) == 401

    def test_returns_400_for_invalid_doc_id(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        with app.test_request_context("/api/delete_chunk?id=bad&chunk_id=xyz"):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = DeleteChunk().delete()

        assert _status(response) == 400
        assert "Invalid doc_id" in _json(response)["error"]

    def test_returns_404_when_doc_not_found(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/delete_chunk?id={doc_id}&chunk_id=cid"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteChunk().delete()

        assert _status(response) == 404

    def test_deletes_chunk_successfully(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.delete_chunk.return_value = True

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/delete_chunk?id={doc_id}&chunk_id=cid"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteChunk().delete()

        assert _status(response) == 200
        assert "successfully" in _json(response)["message"]
        mock_store.delete_chunk.assert_called_once_with("cid")

    def test_returns_404_when_chunk_not_deleted(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.delete_chunk.return_value = False

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/delete_chunk?id={doc_id}&chunk_id=missing"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteChunk().delete()

        assert _status(response) == 404
        assert "not found" in _json(response)["message"]

    def test_returns_500_on_store_error(self, app):
        from application.api.user.sources.chunks import DeleteChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.delete_chunk.side_effect = Exception("boom")

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                f"/api/delete_chunk?id={doc_id}&chunk_id=cid"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteChunk().delete()

        assert _status(response) == 500


# ---------------------------------------------------------------------------
# UpdateChunk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateChunk:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": "abc", "chunk_id": "cid"},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateChunk().put()

        assert _status(response) == 401

    def test_returns_400_missing_required_fields(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT", json={"id": str(ObjectId())}
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UpdateChunk().put()

        assert response is not None

    def test_returns_400_for_invalid_doc_id(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        with app.test_request_context(
            "/api/update_chunk", method="PUT",
            json={"id": "bad", "chunk_id": "cid"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UpdateChunk().put()

        assert _status(response) == 400

    def test_returns_404_when_doc_not_found(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={"id": doc_id, "chunk_id": "cid"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        assert _status(response) == 404

    def test_returns_404_when_chunk_not_found(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.return_value = [
            {"doc_id": "other", "text": "x", "metadata": {}},
        ]

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={"id": doc_id, "chunk_id": "missing"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        assert _status(response) == 404
        assert "Chunk not found" in _json(response)["error"]

    def test_updates_chunk_text_successfully(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.return_value = [
            {"doc_id": "cid", "text": "old text", "metadata": {"source": "f.pdf"}},
        ]
        mock_store.add_chunk.return_value = "new-cid"
        mock_store.delete_chunk.return_value = True

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ), patch(
            "application.api.user.sources.chunks.num_tokens_from_string",
            return_value=7,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={"id": doc_id, "chunk_id": "cid", "text": "new text"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        assert _status(response) == 200
        data = _json(response)
        assert data["chunk_id"] == "new-cid"
        assert data["original_chunk_id"] == "cid"
        # Verify add was called with new text and merged metadata
        add_call = mock_store.add_chunk.call_args
        assert add_call[0][0] == "new text"
        assert add_call[0][1]["source"] == "f.pdf"
        assert add_call[0][1]["token_count"] == 7
        mock_store.delete_chunk.assert_called_once_with("cid")

    def test_updates_chunk_metadata_only(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.return_value = [
            {"doc_id": "cid", "text": "keep me", "metadata": {"source": "f.pdf"}},
        ]
        mock_store.add_chunk.return_value = "new-cid"
        mock_store.delete_chunk.return_value = True

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={
                    "id": doc_id,
                    "chunk_id": "cid",
                    "metadata": {"title": "new title"},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        assert _status(response) == 200
        add_call = mock_store.add_chunk.call_args
        # text should be preserved
        assert add_call[0][0] == "keep me"
        # metadata should be merged
        assert add_call[0][1]["source"] == "f.pdf"
        assert add_call[0][1]["title"] == "new title"

    def test_update_warns_when_old_chunk_delete_fails(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.return_value = [
            {"doc_id": "cid", "text": "text", "metadata": {}},
        ]
        mock_store.add_chunk.return_value = "new-cid"
        mock_store.delete_chunk.return_value = False  # delete fails

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={"id": doc_id, "chunk_id": "cid"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        # Still returns 200 with a warning logged
        assert _status(response) == 200

    def test_returns_500_when_add_chunk_fails(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.return_value = [
            {"doc_id": "cid", "text": "text", "metadata": {}},
        ]
        mock_store.add_chunk.side_effect = Exception("add failed")

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={"id": doc_id, "chunk_id": "cid", "text": "new"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        assert _status(response) == 500
        assert "addition failed" in _json(response)["error"]

    def test_returns_500_on_general_store_error(self, app):
        from application.api.user.sources.chunks import UpdateChunk

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = {"_id": ObjectId(doc_id), "user": "u1"}
        mock_store = Mock()
        mock_store.get_chunks.side_effect = Exception("connection lost")

        with patch(
            "application.api.user.sources.chunks.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.chunks.get_vector_store",
            return_value=mock_store,
        ):
            with app.test_request_context(
                "/api/update_chunk", method="PUT",
                json={"id": doc_id, "chunk_id": "cid"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = UpdateChunk().put()

        assert _status(response) == 500
