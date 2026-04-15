"""Tests for application/api/internal/routes.py.

Previously used the removed ``mock_mongo_db`` fixture to patch in Mongo
collections (conversations_collection, sources_collection). Internal routes
now read via repositories; coverage will be rebuilt on pg_conn in a follow-up.
"""

import io
import json
import uuid
from unittest.mock import MagicMock

import pytest


def _str_oid():
    """Return a fresh 24-hex string suitable as a MongoDB-like _id."""
    return uuid.uuid4().hex[:24]


class _InMemoryCollection:
    """Minimal dict-backed collection for internal-routes tests."""

    def __init__(self):
        self._docs = []

    def _matches(self, doc, query):
        for k, v in query.items():
            if str(doc.get(k)) != str(v):
                return False
        return True

    def insert_one(self, doc):
        new_doc = dict(doc)
        if "_id" not in new_doc:
            new_doc["_id"] = _str_oid()
        self._docs.append(new_doc)
        result = MagicMock()
        result.inserted_id = new_doc["_id"]
        return result

    def find_one(self, query):
        import copy
        for doc in self._docs:
            if self._matches(doc, query):
                return copy.deepcopy(doc)
        return None

    def update_one(self, query, update, upsert=False):
        result = MagicMock()
        result.modified_count = 0
        for doc in self._docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                result.modified_count = 1
                return result
        if upsert:
            new_doc = dict(query)
            if "$set" in update:
                new_doc.update(update["$set"])
            self._docs.append(new_doc)
        return result


class _InMemoryDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _InMemoryCollection()
        return self._cols[name]


@pytest.fixture
def internal_app(monkeypatch):
    """Create a Flask app with the internal blueprint registered."""
    from flask import Flask

    db = _InMemoryDB()
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

    def test_no_internal_key_configured_rejects_access(
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
            resp = client.get("/api/download?user=u&name=n&file=f")
            assert resp.status_code == 401

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

    _TEST_INTERNAL_KEY = "test-internal-key"
    _AUTH_HEADERS = {"X-Internal-Key": "test-internal-key"}

    def _make_settings(self, vector_store="faiss"):
        return MagicMock(
            INTERNAL_KEY=self._TEST_INTERNAL_KEY,
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
            resp = client.post("/api/upload_index", data={}, headers=self._AUTH_HEADERS)
            assert resp.json["status"] == "no user"

    def test_missing_name_returns_no_name(self, internal_app, monkeypatch):
        app, db = internal_app
        monkeypatch.setattr(
            "application.api.internal.routes.settings", self._make_settings()
        )
        with app.test_client() as client:
            resp = client.post("/api/upload_index", data={"user": "testuser"}, headers=self._AUTH_HEADERS)
            assert resp.json["status"] == "no name"

    def test_creates_new_source_entry(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry is not None
        assert entry["user"] == "testuser"
        assert entry["name"] == "testjob"

    def test_updates_existing_source_entry(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["user"] == "new_user"
        assert entry["name"] == "new_name"

    def test_parses_directory_structure_json(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["directory_structure"] == dir_struct

    def test_invalid_directory_structure_defaults_empty(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["directory_structure"] == {}

    def test_file_name_map_parsed(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["file_name_map"] == fmap

    def test_faiss_missing_files_returns_no_file(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "no file"

    def test_faiss_empty_filename_returns_no_file_name(
        self, internal_app, monkeypatch
    ):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "no file name"

    def test_remote_data_and_sync_frequency(self, internal_app, monkeypatch):
        app, db = internal_app
        doc_id = _str_oid()
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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["sync_frequency"] == "daily"
        assert entry["remote_data"] == '{"url":"http://example.com"}'

    def test_faiss_upload_with_valid_files(self, internal_app, monkeypatch):
        """Cover lines 93-104: FAISS upload with both faiss and pkl files."""
        app, db = internal_app
        doc_id = _str_oid()
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
                    "file_faiss": (io.BytesIO(b"faiss data"), "index.faiss"),
                    "file_pkl": (io.BytesIO(b"pkl data"), "index.pkl"),
                },
                content_type="multipart/form-data",
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        mock_storage.save_file.assert_called()
        entry = db["sources"].find_one({"_id": doc_id})
        assert entry is not None

    def test_faiss_pkl_missing_returns_no_file(self, internal_app, monkeypatch):
        """Cover lines 93-95: FAISS upload with faiss file but no pkl file."""
        app, db = internal_app
        doc_id = _str_oid()
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
                    "file_faiss": (io.BytesIO(b"faiss data"), "index.faiss"),
                },
                content_type="multipart/form-data",
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "no file"

    def test_faiss_pkl_empty_name_returns_no_file_name(self, internal_app, monkeypatch):
        """Cover lines 97-98: FAISS upload with pkl but empty filename."""
        app, db = internal_app
        doc_id = _str_oid()
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
                    "file_faiss": (io.BytesIO(b"faiss data"), "index.faiss"),
                    "file_pkl": (io.BytesIO(b""), ""),
                },
                content_type="multipart/form-data",
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "no file name"

    def test_no_internal_key_rejects_upload(self, internal_app, monkeypatch):
        """Verify that upload_index is rejected when INTERNAL_KEY is not set."""
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
            resp = client.post("/api/upload_index", data={"user": "attacker"})
            assert resp.status_code == 401

    def test_update_existing_with_file_name_map(self, internal_app, monkeypatch):
        """Cover line 124: update existing entry with file_name_map."""
        app, db = internal_app
        doc_id = _str_oid()
        settings_mock = self._make_settings(vector_store="other")
        monkeypatch.setattr(
            "application.api.internal.routes.settings", settings_mock
        )
        mock_storage = MagicMock()
        monkeypatch.setattr(
            "application.api.internal.routes.StorageCreator",
            MagicMock(get_storage=MagicMock(return_value=mock_storage)),
        )

        db["sources"].insert_one({"_id": doc_id, "user": "old_user", "name": "old"})

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
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert entry["file_name_map"] == fmap

    def test_invalid_file_name_map_defaults_none(self, internal_app, monkeypatch):
        """Cover lines 77-79: invalid file_name_map JSON defaults to None."""
        app, db = internal_app
        doc_id = _str_oid()
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
                    "file_name_map": "not valid json{{{",
                },
                headers=self._AUTH_HEADERS,
            )
            assert resp.json["status"] == "ok"

        entry = db["sources"].find_one({"_id": doc_id})
        assert "file_name_map" not in entry
