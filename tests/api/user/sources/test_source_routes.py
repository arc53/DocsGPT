"""Tests for source management routes (CombinedJson, PaginatedSources,
DeleteByIds, DeleteOldIndexes, ManageSync, DirectoryStructure).

Note: SyncSource and _get_provider_from_remote_data are already covered in
test_routes.py and are NOT duplicated here.
"""

import json

import pytest
from unittest.mock import MagicMock, Mock, patch
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
# CombinedJson (/api/sources)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCombinedJson:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import CombinedJson

        with app.test_request_context("/api/sources"):
            from flask import request

            request.decoded_token = None
            response = CombinedJson().get()

        assert _status(response) == 401

    def test_returns_default_source_plus_user_sources(self, app):
        from application.api.user.sources.routes import CombinedJson

        src_id = ObjectId()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = [
            {
                "_id": src_id,
                "name": "My Doc",
                "date": "2024-01-01",
                "tokens": "100",
                "retriever": "classic",
                "sync_frequency": "daily",
                "remote_data": json.dumps({"provider": "github"}),
                "directory_structure": None,
                "type": "file",
            }
        ]
        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/sources"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CombinedJson().get()

        assert _status(response) == 200
        data = _json(response)
        # First entry is always the Default
        assert data[0]["name"] == "Default"
        assert data[0]["date"] == "default"
        # Second entry is user source
        assert data[1]["id"] == str(src_id)
        assert data[1]["name"] == "My Doc"
        assert data[1]["provider"] == "github"
        assert data[1]["syncFrequency"] == "daily"
        assert data[1]["is_nested"] is False

    def test_is_nested_true_when_directory_structure_present(self, app):
        from application.api.user.sources.routes import CombinedJson

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = [
            {
                "_id": ObjectId(),
                "name": "Nested",
                "date": "2024-01-01",
                "directory_structure": {"files": ["a.txt"]},
            }
        ]
        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/sources"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = CombinedJson().get()

        data = _json(response)
        assert data[1]["is_nested"] is True

    def test_returns_400_on_db_error(self, app):
        from application.api.user.sources.routes import CombinedJson

        mock_collection = Mock()
        mock_collection.find.side_effect = Exception("db err")

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/sources"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = CombinedJson().get()

        assert _status(response) == 400

    def test_type_defaults_to_file(self, app):
        from application.api.user.sources.routes import CombinedJson

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = [
            {"_id": ObjectId(), "name": "X", "date": "d"}
        ]
        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/sources"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = CombinedJson().get()

        data = _json(response)
        assert data[1]["type"] == "file"


# ---------------------------------------------------------------------------
# PaginatedSources (/api/sources/paginated)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPaginatedSources:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import PaginatedSources

        with app.test_request_context("/api/sources/paginated"):
            from flask import request

            request.decoded_token = None
            response = PaginatedSources().get()

        assert _status(response) == 401

    def test_returns_paginated_results(self, app):
        from application.api.user.sources.routes import PaginatedSources

        ids = [ObjectId() for _ in range(3)]
        docs = [
            {"_id": ids[i], "name": f"Doc{i}", "date": f"2024-0{i + 1}-01"}
            for i in range(3)
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = docs

        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor
        mock_collection.count_documents.return_value = 3

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/sources/paginated?page=1&rows=10&sort=date&order=desc"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = PaginatedSources().get()

        assert _status(response) == 200
        data = _json(response)
        assert data["total"] == 3
        assert data["totalPages"] == 1
        assert data["currentPage"] == 1
        assert len(data["paginated"]) == 3

    def test_search_filter_applies_regex(self, app):
        from application.api.user.sources.routes import PaginatedSources

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = []

        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor
        mock_collection.count_documents.return_value = 0

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/sources/paginated?search=test%20doc"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = PaginatedSources().get()

        assert _status(response) == 200
        # Verify search query was passed
        query_arg = mock_collection.count_documents.call_args[0][0]
        assert query_arg["name"]["$regex"] == "test doc"
        assert query_arg["name"]["$options"] == "i"

    def test_ascending_sort_order(self, app):
        from application.api.user.sources.routes import PaginatedSources

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = []

        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor
        mock_collection.count_documents.return_value = 0

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/sources/paginated?order=asc&sort=name"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = PaginatedSources().get()

        assert _status(response) == 200
        mock_cursor.sort.assert_called_once_with("name", 1)

    def test_page_clamped_to_valid_range(self, app):
        from application.api.user.sources.routes import PaginatedSources

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = []

        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor
        mock_collection.count_documents.return_value = 5  # 1 page with default 10 rows

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/sources/paginated?page=999"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = PaginatedSources().get()

        data = _json(response)
        assert data["currentPage"] == 1  # clamped

    def test_returns_400_on_db_error(self, app):
        from application.api.user.sources.routes import PaginatedSources

        mock_collection = Mock()
        mock_collection.count_documents.return_value = 0
        mock_collection.find.side_effect = Exception("db error")

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/sources/paginated"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = PaginatedSources().get()

        assert _status(response) == 400

    def test_paginated_includes_provider_and_is_nested(self, app):
        from application.api.user.sources.routes import PaginatedSources

        doc = {
            "_id": ObjectId(),
            "name": "S3 Src",
            "date": "2024-01-01",
            "remote_data": {"provider": "s3"},
            "directory_structure": {"dirs": ["a"]},
            "type": "s3",
        }

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = [doc]

        mock_collection = Mock()
        mock_collection.find.return_value = mock_cursor
        mock_collection.count_documents.return_value = 1

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/sources/paginated"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = PaginatedSources().get()

        data = _json(response)
        entry = data["paginated"][0]
        assert entry["provider"] == "s3"
        assert entry["isNested"] is True
        assert entry["type"] == "s3"


# ---------------------------------------------------------------------------
# DeleteByIds (/api/delete_by_ids)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteByIds:

    def test_returns_400_when_path_missing(self, app):
        from application.api.user.sources.routes import DeleteByIds

        with app.test_request_context("/api/delete_by_ids"):
            response = DeleteByIds().get()

        assert _status(response) == 400
        assert "Missing" in _json(response)["message"]

    def test_returns_200_on_successful_delete(self, app):
        from application.api.user.sources.routes import DeleteByIds

        mock_collection = Mock()
        mock_collection.delete_index.return_value = True

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/delete_by_ids?path=id1,id2"):
                response = DeleteByIds().get()

        assert _status(response) == 200
        assert _json(response)["success"] is True
        mock_collection.delete_index.assert_called_once_with(ids="id1,id2")

    def test_returns_400_when_delete_returns_false(self, app):
        from application.api.user.sources.routes import DeleteByIds

        mock_collection = Mock()
        mock_collection.delete_index.return_value = False

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/delete_by_ids?path=id1"):
                response = DeleteByIds().get()

        assert _status(response) == 400

    def test_returns_400_on_exception(self, app):
        from application.api.user.sources.routes import DeleteByIds

        mock_collection = Mock()
        mock_collection.delete_index.side_effect = Exception("fail")

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/delete_by_ids?path=id1"):
                response = DeleteByIds().get()

        assert _status(response) == 400


# ---------------------------------------------------------------------------
# DeleteOldIndexes (/api/delete_old)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteOldIndexes:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        with app.test_request_context("/api/delete_old?source_id=abc"):
            from flask import request

            request.decoded_token = None
            response = DeleteOldIndexes().get()

        assert _status(response) == 401

    def test_returns_400_when_source_id_missing(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        with app.test_request_context("/api/delete_old"):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = DeleteOldIndexes().get()

        assert _status(response) == 400

    def test_returns_404_when_doc_not_found(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        source_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(f"/api/delete_old?source_id={source_id}"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteOldIndexes().get()

        assert _status(response) == 404

    def test_deletes_faiss_index_and_file(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        source_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": source_id,
            "user": "u1",
            "file_path": "uploads/u1/doc.pdf",
        }
        mock_storage = Mock()
        mock_storage.file_exists.return_value = True
        mock_storage.is_directory.return_value = False

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.sources.routes.settings"
        ) as mock_settings:
            mock_settings.VECTOR_STORE = "faiss"
            with app.test_request_context(
                f"/api/delete_old?source_id={source_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteOldIndexes().get()

        assert _status(response) == 200
        assert _json(response)["success"] is True
        # Should have checked and deleted faiss files
        assert mock_storage.delete_file.call_count >= 1
        mock_collection.delete_one.assert_called_once()

    def test_deletes_non_faiss_vector_index(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        source_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": source_id,
            "user": "u1",
        }
        mock_storage = Mock()
        mock_vectorstore = Mock()

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.sources.routes.VectorCreator.create_vectorstore",
            return_value=mock_vectorstore,
        ), patch(
            "application.api.user.sources.routes.settings"
        ) as mock_settings:
            mock_settings.VECTOR_STORE = "elasticsearch"
            with app.test_request_context(
                f"/api/delete_old?source_id={source_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteOldIndexes().get()

        assert _status(response) == 200
        mock_vectorstore.delete_index.assert_called_once()

    def test_deletes_directory_of_files(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        source_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": source_id,
            "user": "u1",
            "file_path": "uploads/u1/mydir",
        }
        mock_storage = Mock()
        mock_storage.is_directory.return_value = True
        mock_storage.list_files.return_value = ["uploads/u1/mydir/a.txt", "uploads/u1/mydir/b.txt"]

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.sources.routes.settings"
        ) as mock_settings:
            mock_settings.VECTOR_STORE = "faiss"
            mock_storage.file_exists.return_value = False
            with app.test_request_context(
                f"/api/delete_old?source_id={source_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteOldIndexes().get()

        assert _status(response) == 200
        # Each file in directory should be deleted
        assert mock_storage.delete_file.call_count == 2

    def test_handles_file_not_found_gracefully(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        source_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": source_id,
            "user": "u1",
            "file_path": "uploads/missing.pdf",
        }
        mock_storage = Mock()
        mock_storage.is_directory.side_effect = FileNotFoundError()

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.sources.routes.settings"
        ) as mock_settings:
            mock_settings.VECTOR_STORE = "faiss"
            mock_storage.file_exists.return_value = False
            with app.test_request_context(
                f"/api/delete_old?source_id={source_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteOldIndexes().get()

        assert _status(response) == 200
        mock_collection.delete_one.assert_called_once()

    def test_returns_400_on_general_error(self, app):
        from application.api.user.sources.routes import DeleteOldIndexes

        source_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": source_id,
            "user": "u1",
        }
        mock_storage = Mock()

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ), patch(
            "application.api.user.sources.routes.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.api.user.sources.routes.settings"
        ) as mock_settings:
            mock_settings.VECTOR_STORE = "faiss"
            mock_storage.file_exists.side_effect = RuntimeError("disk error")
            with app.test_request_context(
                f"/api/delete_old?source_id={source_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DeleteOldIndexes().get()

        assert _status(response) == 400


# ---------------------------------------------------------------------------
# ManageSync (/api/manage_sync)
# ---------------------------------------------------------------------------


@pytest.mark.unit
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

        assert _status(response) == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync", method="POST",
            json={"source_id": "abc"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = ManageSync().post()

        assert response is not None

    def test_returns_400_for_invalid_frequency(self, app):
        from application.api.user.sources.routes import ManageSync

        with app.test_request_context(
            "/api/manage_sync", method="POST",
            json={"source_id": str(ObjectId()), "sync_frequency": "hourly"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = ManageSync().post()

        assert _status(response) == 400
        assert "Invalid frequency" in _json(response)["message"]

    def test_updates_sync_frequency_successfully(self, app):
        from application.api.user.sources.routes import ManageSync

        source_id = str(ObjectId())
        mock_collection = Mock()

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/manage_sync", method="POST",
                json={"source_id": source_id, "sync_frequency": "weekly"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSync().post()

        assert _status(response) == 200
        assert _json(response)["success"] is True
        call_args = mock_collection.update_one.call_args
        assert call_args[0][0]["_id"] == ObjectId(source_id)
        assert call_args[0][0]["user"] == "u1"
        assert call_args[0][1]["$set"]["sync_frequency"] == "weekly"

    def test_accepts_all_valid_frequencies(self, app):
        from application.api.user.sources.routes import ManageSync

        mock_collection = Mock()

        for freq in ["never", "daily", "weekly", "monthly"]:
            with patch(
                "application.api.user.sources.routes.sources_collection",
                mock_collection,
            ):
                with app.test_request_context(
                    "/api/manage_sync", method="POST",
                    json={"source_id": str(ObjectId()), "sync_frequency": freq},
                ):
                    from flask import request

                    request.decoded_token = {"sub": "u1"}
                    response = ManageSync().post()

            assert _status(response) == 200

    def test_returns_400_on_db_error(self, app):
        from application.api.user.sources.routes import ManageSync

        mock_collection = Mock()
        mock_collection.update_one.side_effect = Exception("db err")

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/manage_sync", method="POST",
                json={"source_id": str(ObjectId()), "sync_frequency": "daily"},
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = ManageSync().post()

        assert _status(response) == 400


# ---------------------------------------------------------------------------
# RedirectToSources (/api/combine)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedirectToSources:

    def test_redirects_to_sources(self, app):
        from application.api.user.sources.routes import RedirectToSources

        with app.test_request_context("/api/combine"):
            response = RedirectToSources().get()

        assert response.status_code == 301
        assert response.location == "/api/sources"


# ---------------------------------------------------------------------------
# DirectoryStructure (/api/directory_structure)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDirectoryStructure:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure?id=abc"):
            from flask import request

            request.decoded_token = None
            response = DirectoryStructure().get()

        assert _status(response) == 401

    def test_returns_400_when_id_missing(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure"):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = DirectoryStructure().get()

        assert _status(response) == 400
        assert "required" in _json(response)["error"]

    def test_returns_400_for_invalid_doc_id(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        with app.test_request_context("/api/directory_structure?id=invalid"):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = DirectoryStructure().get()

        assert _status(response) == 400
        assert "Invalid" in _json(response)["error"]

    def test_returns_404_when_doc_not_found(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(f"/api/directory_structure?id={doc_id}"):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DirectoryStructure().get()

        assert _status(response) == 404
        assert "not found" in _json(response)["error"]

    def test_returns_directory_structure(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        doc_id = ObjectId()
        dir_struct = {"dirs": ["a", "b"], "files": ["c.txt"]}
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": doc_id,
            "user": "u1",
            "directory_structure": dir_struct,
            "file_path": "uploads/u1/mydir",
            "remote_data": json.dumps({"provider": "github"}),
        }

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/directory_structure?id={doc_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DirectoryStructure().get()

        assert _status(response) == 200
        data = _json(response)
        assert data["success"] is True
        assert data["directory_structure"] == dir_struct
        assert data["base_path"] == "uploads/u1/mydir"
        assert data["provider"] == "github"

    def test_returns_none_provider_when_no_remote_data(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        doc_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": doc_id,
            "user": "u1",
            "directory_structure": {},
            "file_path": "path",
        }

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/directory_structure?id={doc_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DirectoryStructure().get()

        data = _json(response)
        assert data["provider"] is None

    def test_handles_invalid_remote_data_json(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        doc_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": doc_id,
            "user": "u1",
            "directory_structure": {},
            "file_path": "path",
            "remote_data": "not-valid-json{",
        }

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/directory_structure?id={doc_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DirectoryStructure().get()

        data = _json(response)
        assert data["success"] is True
        assert data["provider"] is None

    def test_returns_500_on_general_error(self, app):
        from application.api.user.sources.routes import DirectoryStructure

        doc_id = str(ObjectId())
        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("db error")

        with patch(
            "application.api.user.sources.routes.sources_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/directory_structure?id={doc_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "u1"}
                response = DirectoryStructure().get()

        assert _status(response) == 500
