"""Unit tests for application/api/internal/routes.py.

Covers:
  - verify_internal_key: key validation
  - /api/download: file download
  - /api/upload_index: index file upload (existing & new entries)
"""

import io
import json
from unittest.mock import MagicMock

import pytest
from bson.objectid import ObjectId


@pytest.fixture
def internal_app(monkeypatch, mock_mongo_db):
    """Create a Flask app with the internal blueprint registered."""
    from flask import Flask

    # Patch module-level MongoDB references before importing routes
    from application.core.settings import settings

    db = mock_mongo_db[settings.MONGO_DB_NAME]
    monkeypatch.setattr(
        "application.api.internal.routes.conversations_collection",
        db["conversations"],
    )
    monkeypatch.setattr(
        "application.api.internal.routes.sources_collection",
        db["sources"],
    )

    from application.api.internal.routes import internal

    app = Flask(__name__)
    app.register_blueprint(internal)
    app.config["TESTING"] = True
    return app, db


# ---------------------------------------------------------------------------
# verify_internal_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyInternalKey:

    def test_no_internal_key_configured_allows_access(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings",
            MagicMock(
                INTERNAL_KEY=None,
                UPLOAD_FOLDER="uploads",
                VECTOR_STORE="faiss",
                EMBEDDINGS_NAME="test",
                MONGO_DB_NAME="docsgpt",
            ),
        )
        with app.test_client() as client:
            # download will fail for missing file but should not be 401
            resp = client.get("/api/download?user=u&name=n&file=f")
            assert resp.status_code != 401

    def test_missing_key_returns_401(self, internal_app, monkeypatch):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings",
            MagicMock(
                INTERNAL_KEY="secret123",
                UPLOAD_FOLDER="uploads",
                VECTOR_STORE="faiss",
                EMBEDDINGS_NAME="test",
                MONGO_DB_NAME="docsgpt",
            ),
        )
        with app.test_client() as client:
            resp = client.get("/api/download?user=u&name=n&file=f")
            assert resp.status_code == 401

    def test_wrong_key_returns_401(self, internal_app, monkeypatch):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings",
            MagicMock(
                INTERNAL_KEY="secret123",
                UPLOAD_FOLDER="uploads",
                VECTOR_STORE="faiss",
                EMBEDDINGS_NAME="test",
                MONGO_DB_NAME="docsgpt",
            ),
        )
        with app.test_client() as client:
            resp = client.get(
                "/api/download?user=u&name=n&file=f",
                headers={"X-Internal-Key": "wrong"},
            )
            assert resp.status_code == 401

    def test_correct_key_allows_access(self, internal_app, monkeypatch):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings",
            MagicMock(
                INTERNAL_KEY="secret123",
                UPLOAD_FOLDER="uploads",
                VECTOR_STORE="faiss",
                EMBEDDINGS_NAME="test",
                MONGO_DB_NAME="docsgpt",
            ),
        )
        with app.test_client() as client:
            # Will 404 for missing file, but should pass auth check
            resp = client.get(
                "/api/download?user=u&name=n&file=f",
                headers={"X-Internal-Key": "secret123"},
            )
            assert resp.status_code != 401


# ---------------------------------------------------------------------------
# /api/upload_index
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadIndex:

    def _make_settings(self, vector_store="faiss"):
        return MagicMock(
            INTERNAL_KEY=None,
            UPLOAD_FOLDER="uploads",
            VECTOR_STORE=vector_store,
            EMBEDDINGS_NAME="test_embeddings",
            MONGO_DB_NAME="docsgpt",
        )

    def test_missing_user_returns_no_user(self, internal_app, monkeypatch):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings", self._make_settings()
        )
        with app.test_client() as client:
            resp = client.post("/api/upload_index", data={})
            assert resp.json["status"] == "no user"

    def test_missing_name_returns_no_name(self, internal_app, monkeypatch):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings", self._make_settings()
        )
        with app.test_client() as client:
            resp = client.post("/api/upload_index", data={"user": "testuser"})
            assert resp.json["status"] == "no name"

    def test_creates_new_source_entry(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "testuser",
                    "name": "testjob",
                    "tokens": "100",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "local",
                },
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": ObjectId(doc_id)})
        assert entry is not None
        assert entry["user"] == "testuser"
        assert entry["name"] == "testjob"

    def test_updates_existing_source_entry(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = ObjectId()
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        # Insert existing entry
        db["sources"].insert_one(
            {"_id": doc_id, "user": "old_user", "name": "old_name"}
        )

        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "new_user",
                    "name": "new_name",
                    "tokens": "200",
                    "retriever": "hybrid",
                    "id": str(doc_id),
                    "type": "remote",
                },
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["user"] == "new_user"
        assert entry["name"] == "new_name"

    def test_parses_directory_structure_json(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        dir_struct = {"root": {"files": ["a.txt", "b.txt"]}}
        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "u",
                    "name": "n",
                    "tokens": "0",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "local",
                    "directory_structure": json.dumps(dir_struct),
                },
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": ObjectId(doc_id)})
        assert entry["directory_structure"] == dir_struct

    def test_invalid_directory_structure_defaults_empty(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "u",
                    "name": "n",
                    "tokens": "0",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "local",
                    "directory_structure": "not valid json",
                },
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": ObjectId(doc_id)})
        assert entry["directory_structure"] == {}

    def test_file_name_map_parsed(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        fmap = {"hash1": "file1.txt"}
        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "u",
                    "name": "n",
                    "tokens": "0",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "local",
                    "file_name_map": json.dumps(fmap),
                },
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": ObjectId(doc_id)})
        assert entry["file_name_map"] == fmap

    def test_faiss_missing_files_returns_no_file(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="faiss")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "u",
                    "name": "n",
                    "tokens": "0",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "local",
                },
            )
            assert resp.json["status"] == "no file"

    def test_faiss_empty_filename_returns_no_file_name(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="faiss")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "u",
                    "name": "n",
                    "tokens": "0",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "local",
                    "file_faiss": (io.BytesIO(b""), ""),
                },
            )
            assert resp.json["status"] == "no file name"

    def test_remote_data_and_sync_frequency(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = str(ObjectId())
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        with app.test_client() as client:
            resp = client.post(
                "/api/upload_index",
                data={
                    "user": "u",
                    "name": "n",
                    "tokens": "0",
                    "retriever": "classic",
                    "id": doc_id,
                    "type": "remote",
                    "remote_data": '{"url":"http://example.com"}',
                    "sync_frequency": "daily",
                },
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": ObjectId(doc_id)})
        assert entry["sync_frequency"] == "daily"
        assert entry["remote_data"] == '{"url":"http://example.com"}'
