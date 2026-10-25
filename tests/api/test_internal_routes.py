"""Tests for docsgpt/api/internal/routes.py.

Uses the ephemeral ``pg_conn`` fixture so the sources repository writes
happen against a real Postgres schema.
"""

import io
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from flask import Flask

from docsgpt.storage.local import LocalStorage


_TEST_KEY = "test-internal-key"
_AUTH = {"X-Internal-Key": _TEST_KEY}


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "docsgpt.api.internal.routes.db_session", _yield
    ):
        yield


def _make_app():
    from docsgpt.api.internal.routes import internal

    app = Flask(__name__)
    app.register_blueprint(internal)
    app.config["TESTING"] = True
    return app


class TestVerifyInternalKey:
    def test_rejects_when_internal_key_not_configured(self):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", ""
        ):
            with app.test_client() as c:
                r = c.get("/api/download")
        assert r.status_code == 401

    def test_rejects_when_key_missing(self):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ):
            with app.test_client() as c:
                r = c.get("/api/download")
        assert r.status_code == 401

    def test_rejects_when_key_mismatch(self):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ):
            with app.test_client() as c:
                r = c.get("/api/download", headers={"X-Internal-Key": "wrong"})
        assert r.status_code == 401


    def test_compares_the_key_in_constant_time(self):
        app = _make_app()
        seen = []

        def compare(given, expected):
            seen.append((given, expected))
            return False

        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch("docsgpt.api.internal.routes.hmac.compare_digest", compare):
            with app.test_client() as c:
                r = c.get("/api/download", headers=_AUTH)
        assert r.status_code == 401
        assert seen == [(_TEST_KEY.encode(), _TEST_KEY.encode())]


class TestDownloadFile:
    def test_returns_404_for_missing_file(self, tmp_path):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.UPLOAD_FOLDER",
            str(tmp_path),
        ), patch(
            "docsgpt.api.internal.routes.current_dir", ""
        ):
            with app.test_client() as c:
                r = c.get(
                    "/api/download?user=alice&name=job1&file=missing.txt",
                    headers=_AUTH,
                )
        assert r.status_code == 404

    def test_returns_file_when_present(self, tmp_path):
        app = _make_app()
        user_dir = tmp_path / "bob" / "job1"
        user_dir.mkdir(parents=True)
        (user_dir / "hello.txt").write_text("hi there")

        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.UPLOAD_FOLDER",
            str(tmp_path),
        ), patch(
            "docsgpt.api.internal.routes.current_dir", ""
        ):
            with app.test_client() as c:
                r = c.get(
                    "/api/download?user=bob&name=job1&file=hello.txt",
                    headers=_AUTH,
                )
        assert r.status_code == 200
        assert r.data == b"hi there"


class _RecordingStorage(LocalStorage):
    """Local storage that records the name of each file it writes."""

    def __init__(self, base_dir):
        super().__init__(base_dir=base_dir)
        self.written = []

    def save_file(self, file_data, path, **kwargs):
        self.written.append(path.rsplit("/", 1)[-1])
        return super().save_file(file_data, path, **kwargs)


class TestUploadIndex:
    def _base_form(self, *, source_id="source-1"):
        return {
            "user": "alice",
            "name": "Job A",
            "tokens": "100",
            "retriever": "classic",
            "id": source_id,
            "type": "file",
        }

    def test_rejects_without_auth(self):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ):
            with app.test_client() as c:
                r = c.post("/api/upload_index")
        assert r.status_code == 401

    def test_rejects_missing_user(self):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ):
            with app.test_client() as c:
                r = c.post("/api/upload_index", headers=_AUTH, data={})
        assert r.status_code == 200
        assert r.json == {"status": "no user"}

    def test_rejects_missing_name(self):
        app = _make_app()
        form = {"user": "alice"}
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ):
            with app.test_client() as c:
                r = c.post("/api/upload_index", headers=_AUTH, data=form)
        assert r.status_code == 200
        assert r.json == {"status": "no name"}

    def test_creates_new_source_for_non_faiss_store(self, pg_conn):
        """For non-faiss VECTOR_STORE the route skips file uploads entirely."""
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        app = _make_app()
        form = {**self._base_form(source_id="legacy-source-1")}
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "milvus"
        ), patch(
            "docsgpt.api.internal.routes.settings.EMBEDDINGS_NAME", "emb"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), _patch_db(pg_conn):
            with app.test_client() as c:
                r = c.post("/api/upload_index", headers=_AUTH, data=form)

        assert r.status_code == 200
        assert r.json == {"status": "ok"}
        repo = SourcesRepository(pg_conn)
        found = repo.get_by_legacy_id("legacy-source-1", "alice")
        assert found is not None

    def test_updates_existing_source(self, pg_conn):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        repo = SourcesRepository(pg_conn)
        created = repo.create(
            "initial",
            user_id="alice",
            legacy_mongo_id="legacy-src-2",
            tokens="0",
        )
        app = _make_app()
        form = {**self._base_form(source_id="legacy-src-2"), "tokens": "999"}
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "milvus"
        ), patch(
            "docsgpt.api.internal.routes.settings.EMBEDDINGS_NAME", "emb"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), _patch_db(pg_conn):
            with app.test_client() as c:
                r = c.post("/api/upload_index", headers=_AUTH, data=form)
        assert r.status_code == 200

        updated = repo.get(str(created["id"]), "alice")
        assert updated["tokens"] == "999"

    def test_handles_directory_structure_and_file_name_map(self, pg_conn):
        import json

        app = _make_app()
        form = {
            **self._base_form(source_id="legacy-src-3"),
            "directory_structure": json.dumps({"root": {"a.txt": None}}),
            "file_name_map": json.dumps({"a.txt": "Original A.txt"}),
        }
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "milvus"
        ), patch(
            "docsgpt.api.internal.routes.settings.EMBEDDINGS_NAME", "emb"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), _patch_db(pg_conn):
            with app.test_client() as c:
                r = c.post("/api/upload_index", headers=_AUTH, data=form)
        assert r.status_code == 200

    def test_invalid_json_falls_back_to_empty(self, pg_conn):
        app = _make_app()
        form = {
            **self._base_form(source_id="legacy-src-4"),
            "directory_structure": "not-json",
            "file_name_map": "also-not-json",
        }
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "milvus"
        ), patch(
            "docsgpt.api.internal.routes.settings.EMBEDDINGS_NAME", "emb"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), _patch_db(pg_conn):
            with app.test_client() as c:
                r = c.post("/api/upload_index", headers=_AUTH, data=form)
        assert r.status_code == 200

    def test_faiss_missing_file_faiss(self, pg_conn):
        app = _make_app()
        form = self._base_form(source_id="legacy-src-5")
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "faiss"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=MagicMock(),
        ):
            with app.test_client() as c:
                r = c.post(
                    "/api/upload_index",
                    headers=_AUTH,
                    data=form,
                    content_type="multipart/form-data",
                )
        assert r.status_code == 200
        assert r.json == {"status": "no file"}

    def test_faiss_missing_file_pkl(self, pg_conn):
        app = _make_app()
        data = {
            **self._base_form(source_id="legacy-src-6"),
            "file_faiss": (io.BytesIO(b"faiss-data"), "index.faiss"),
        }
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "faiss"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=MagicMock(),
        ):
            with app.test_client() as c:
                r = c.post(
                    "/api/upload_index",
                    headers=_AUTH,
                    data=data,
                    content_type="multipart/form-data",
                )
        assert r.status_code == 200
        assert r.json == {"status": "no file"}

    def _post_faiss(self, pg_conn, storage, data):
        app = _make_app()
        with patch(
            "docsgpt.api.internal.routes.settings.INTERNAL_KEY", _TEST_KEY
        ), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "faiss"
        ), patch(
            "docsgpt.api.internal.routes.settings.EMBEDDINGS_NAME", "emb"
        ), patch(
            "docsgpt.api.internal.routes.StorageCreator.get_storage",
            return_value=storage,
        ), _patch_db(pg_conn):
            with app.test_client() as c:
                return c.post(
                    "/api/upload_index",
                    headers=_AUTH,
                    data=data,
                    content_type="multipart/form-data",
                )

    def _index_files(self, texts=("alpha", "beta", "gamma")):
        """index.faiss and index.pkl bytes, as a worker's upload sends them."""
        import numpy as np

        from docsgpt.vectorstore.faiss import _dependable_faiss_import
        from docsgpt.vectorstore.faiss_docstore import dump_pickle_sidecar

        faiss = _dependable_faiss_import()
        index = faiss.IndexFlatL2(2)
        index.add(np.array([[float(i), 1.0] for i in range(len(texts))], dtype=np.float32))
        documents = {f"id-{i}": {"page_content": text, "metadata": {}} for i, text in enumerate(texts)}
        mapping = {i: f"id-{i}" for i in range(len(texts))}
        return faiss.serialize_index(index).tobytes(), dump_pickle_sidecar(documents, mapping)

    def _faiss_form(self, source_id, index_bytes, pickle_bytes):
        return {
            **self._base_form(source_id=source_id),
            "file_faiss": (io.BytesIO(index_bytes), "index.faiss"),
            "file_pkl": (io.BytesIO(pickle_bytes), "index.pkl"),
        }

    def test_faiss_upload_stores_a_json_sidecar_naming_the_uploaded_index(self, pg_conn, tmp_path):
        import hashlib
        import json

        index_bytes, pickle_bytes = self._index_files()
        r = self._post_faiss(
            pg_conn, LocalStorage(str(tmp_path)), self._faiss_form("legacy-src-7", index_bytes, pickle_bytes)
        )

        assert r.status_code == 200
        assert r.json == {"status": "ok"}
        folder = tmp_path / "indexes" / "legacy-src-7"
        assert (folder / "index.faiss").read_bytes() == index_bytes
        assert (folder / "index.pkl").read_bytes() == pickle_bytes
        payload = json.loads((folder / "index.json").read_text())
        assert payload["index_sha256"] == hashlib.sha256(index_bytes).hexdigest()
        assert payload["index_to_docstore_id"] == {"0": "id-0", "1": "id-1", "2": "id-2"}
        assert payload["documents"]["id-1"]["page_content"] == "beta"

    def test_faiss_upload_over_a_named_index_writes_the_json_last(self, pg_conn, tmp_path):
        """Pickle first while the stored json names the stored index: a stop before the json still reads a pair."""
        storage = _RecordingStorage(str(tmp_path))
        self._post_faiss(pg_conn, storage, self._faiss_form("legacy-src-8", *self._index_files()))
        storage.written.clear()

        self._post_faiss(pg_conn, storage, self._faiss_form("legacy-src-8", *self._index_files(("x", "y", "z"))))

        assert storage.written == ["index.pkl", "index.faiss", "index.json"]

    def test_faiss_upload_over_a_legacy_index_writes_the_json_first(self, pg_conn, tmp_path):
        """With no index.json the stored pickle is what pairs, so it is replaced last."""
        storage = _RecordingStorage(str(tmp_path))
        folder = tmp_path / "indexes" / "legacy-src-9"
        folder.mkdir(parents=True)
        old_index, old_pickle = self._index_files(("old-a", "old-b", "old-c"))
        (folder / "index.faiss").write_bytes(old_index)
        (folder / "index.pkl").write_bytes(old_pickle)

        self._post_faiss(pg_conn, storage, self._faiss_form("legacy-src-9", *self._index_files()))

        assert storage.written == ["index.json", "index.faiss", "index.pkl"]

    def test_faiss_upload_with_an_unreadable_pickle_is_refused(self, pg_conn, tmp_path):
        storage = _RecordingStorage(str(tmp_path))
        index_bytes, _ = self._index_files()

        r = self._post_faiss(pg_conn, storage, self._faiss_form("legacy-src-10", index_bytes, b"pkl-data"))

        assert r.status_code == 400
        assert r.json == {"status": "invalid index"}
        assert storage.written == []

    def _sync_seeing(self, pg_conn, storage, source_id, *rows):
        """Post a sync whose two looks at the source row find ``rows`` in turn."""
        data = {**self._faiss_form(source_id, *self._index_files()), "operation": "sync"}
        found = iter(rows)
        with patch("docsgpt.api.internal.routes._locked_source", side_effect=lambda *a: next(found)):
            return self._post_faiss(pg_conn, storage, data)

    def test_faiss_sync_of_a_source_deleted_while_its_files_saved_removes_them(self, pg_conn, tmp_path):
        storage = _RecordingStorage(str(tmp_path))

        r = self._sync_seeing(pg_conn, storage, "legacy-src-11", {"id": "legacy-src-11", "config": {}}, None)

        assert r.json == {"status": "skipped", "reason": "gone"}
        assert storage.written, "the first look found the source, so the files were stored"
        assert list((tmp_path / "indexes" / "legacy-src-11").iterdir()) == []

    def test_faiss_sync_of_a_source_converted_while_its_files_saved_keeps_them(self, pg_conn, tmp_path):
        storage = _RecordingStorage(str(tmp_path))
        wiki = {"id": "legacy-src-12", "config": {"kind": "wiki"}}

        r = self._sync_seeing(pg_conn, storage, "legacy-src-12", {"id": "legacy-src-12", "config": {}}, wiki)

        assert r.json == {"status": "skipped", "reason": "wiki"}
        assert (tmp_path / "indexes" / "legacy-src-12" / "index.faiss").exists()
