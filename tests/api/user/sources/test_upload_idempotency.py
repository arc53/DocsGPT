"""Idempotency-Key behavior on the /api/upload and /api/remote routes."""

import io
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
        "application.api.user.sources.upload.db_session", _yield
    ), patch(
        "application.api.user.sources.upload.db_readonly", _yield
    ):
        yield


def _apply_async_mock():
    """Mock for ``ingest.apply_async``; ``task.id`` mirrors the predetermined id."""
    def _side_effect(*args, **kwargs):
        return MagicMock(id=kwargs.get("task_id") or "auto-task-id")
    m = MagicMock(side_effect=_side_effect)
    return m


class TestUploadIdempotency:
    def test_no_header_enqueues_normally(self, app, pg_conn):
        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        assert apply_mock.call_count == 1
        # No key → no predetermined id was passed.
        assert "task_id" not in apply_mock.call_args.kwargs

    def test_header_first_post_records_row(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": "up-key-1"},
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        assert apply_mock.call_count == 1
        predetermined_id = apply_mock.call_args.kwargs["task_id"]
        assert response.json["task_id"] == predetermined_id

        # The dedup row is keyed on the *scoped* form ``"{user}:{key}"``
        # so two users sending the same raw header don't collapse.
        row = pg_conn.execute(
            text(
                "SELECT task_id, task_name, status FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": "alice:up-key-1"},
        ).fetchone()
        assert row is not None
        assert row[0] == predetermined_id
        assert row[1] == "ingest"
        assert row[2] == "pending"

    def test_header_forwards_idempotency_key_to_delay(self, app, pg_conn):
        """The Celery task body needs the key so ``with_idempotency`` can
        record terminal status and ``_derive_source_id`` can pick it up.
        """
        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"c"), "doc.txt"),
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": "up-fwd"},
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            UploadFile().post()
        # Worker sees the scoped form so its ``with_idempotency`` row
        # and ``_derive_source_id`` are also user-distinct.
        assert (
            apply_mock.call_args.kwargs["kwargs"]["idempotency_key"]
            == "alice:up-fwd"
        )

    def test_same_header_second_post_returns_cached(self, app, pg_conn):
        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ):
            with app.test_request_context(
                "/api/upload", method="POST",
                data={
                    "user": "alice", "name": "j",
                    "file": (io.BytesIO(b"content"), "doc.txt"),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "up-rep"},
            ):
                from flask import request
                request.decoded_token = {"sub": "alice"}
                first = UploadFile().post()
            with app.test_request_context(
                "/api/upload", method="POST",
                data={
                    "user": "alice", "name": "j",
                    "file": (io.BytesIO(b"content"), "doc.txt"),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "up-rep"},
            ):
                from flask import request
                request.decoded_token = {"sub": "alice"}
                second = UploadFile().post()

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json == second.json
        assert apply_mock.call_count == 1

    def test_same_key_different_users_does_not_collide(self, app, pg_conn):
        """Cross-user collision regression: two users sending the same
        raw ``Idempotency-Key`` must each get their own dedup row, both
        requests enqueue, and the responses carry distinct ``task_id``s.
        (Pre-fix, the second user's request was silently deduplicated
        against the first user's row.)
        """
        from sqlalchemy import text as sql_text

        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        def _fire(user):
            with _patch_db(pg_conn), patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                return_value=fake_storage,
            ), patch(
                "application.api.user.sources.upload.ingest.apply_async",
                apply_mock,
            ), app.test_request_context(
                "/api/upload", method="POST",
                data={
                    "user": user, "name": "j",
                    "file": (io.BytesIO(b"c"), "doc.txt"),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "shared-key"},
            ):
                from flask import request
                request.decoded_token = {"sub": user}
                return UploadFile().post()

        first = _fire("alice")
        second = _fire("bob")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json["task_id"] != second.json["task_id"]
        assert apply_mock.call_count == 2

        rows = pg_conn.execute(
            sql_text(
                "SELECT idempotency_key FROM task_dedup "
                "WHERE idempotency_key LIKE :pat ORDER BY idempotency_key"
            ),
            {"pat": "%:shared-key"},
        ).fetchall()
        assert {r[0] for r in rows} == {"alice:shared-key", "bob:shared-key"}

    def test_concurrent_same_key_only_one_apply_async(self, app, pg_engine):
        """Race test (M3): N parallel POSTs with same key → only ONE apply_async.

        Uses ``pg_engine`` (not ``pg_conn``) so each thread can check out
        its own DB connection — sharing a single Connection across
        threads serializes at the driver level and defeats the race.
        """
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager

        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        @contextmanager
        def _engine_session():
            with pg_engine.begin() as conn:
                yield conn

        @contextmanager
        def _engine_readonly():
            with pg_engine.connect() as conn:
                yield conn

        def fire(idx):
            # Patches sit OUTSIDE the threads (see below); only the
            # per-thread Flask request context is set up inside.
            with app.test_request_context(
                "/api/upload", method="POST",
                data={
                    "user": "alice", "name": "j",
                    "file": (io.BytesIO(b"x"), "doc.txt"),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "up-race"},
            ):
                from flask import request
                request.decoded_token = {"sub": "alice"}
                return UploadFile().post()

        # ``unittest.mock.patch`` is not thread-safe — concurrent
        # ``__enter__`` calls race on saving/restoring the module
        # attribute and can leave threads pointing at the real
        # function instead of the mock. Set up patches once, share
        # across threads.
        with patch(
            "application.api.user.sources.upload.db_session",
            _engine_session,
        ), patch(
            "application.api.user.sources.upload.db_readonly",
            _engine_readonly,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ), ThreadPoolExecutor(max_workers=8) as ex:
            responses = list(ex.map(fire, range(8)))
        assert all(r.status_code == 200 for r in responses)
        # Only one writer wins the claim, so only one apply_async is fired.
        assert apply_mock.call_count == 1
        # All 8 responses share the same task_id (winner's predetermined id).
        ids = {r.json["task_id"] for r in responses}
        assert len(ids) == 1
        assert "deduplicated" not in ids

    def test_empty_header_treated_as_absent(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": ""},
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        assert apply_mock.call_count == 1
        count = pg_conn.execute(
            text("SELECT count(*) FROM task_dedup")
        ).scalar()
        assert count == 0

    def test_oversized_header_rejected_with_400(self, app, pg_conn):
        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        oversized = "x" * 257

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
        ) as mock_apply, app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": oversized},
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 400
        assert mock_apply.call_count == 0

    def test_stale_dedup_row_does_not_block_new_work(self, app, pg_conn):
        """Regression for the TTL fail-shut bug: a >24h-old dedup row
        must not silently drop a new upload. Pre-fix, the second POST
        returned ``task_id="deduplicated"`` and never enqueued.
        """
        from sqlalchemy import text

        from application.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.sources.upload.ingest.apply_async",
            apply_mock,
        ):
            with app.test_request_context(
                "/api/upload", method="POST",
                data={
                    "user": "alice", "name": "j",
                    "file": (io.BytesIO(b"content"), "doc.txt"),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "stale-up"},
            ):
                from flask import request
                request.decoded_token = {"sub": "alice"}
                first = UploadFile().post()
            assert first.status_code == 200
            first_task_id = first.json["task_id"]
            assert first_task_id != "deduplicated"

            # Backdate the row past TTL.
            pg_conn.execute(
                text(
                    "UPDATE task_dedup SET created_at = "
                    "clock_timestamp() - make_interval(hours => 25) "
                    "WHERE idempotency_key = :k"
                ),
                {"k": "alice:stale-up"},
            )

            with app.test_request_context(
                "/api/upload", method="POST",
                data={
                    "user": "alice", "name": "j",
                    "file": (io.BytesIO(b"content"), "doc.txt"),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "stale-up"},
            ):
                from flask import request
                request.decoded_token = {"sub": "alice"}
                second = UploadFile().post()

        assert second.status_code == 200
        assert second.json["task_id"] != "deduplicated"
        assert second.json["task_id"] != first_task_id
        assert apply_mock.call_count == 2


class TestRemoteIdempotency:
    def test_no_header_enqueues_normally(self, app, pg_conn):
        from application.api.user.sources.upload import UploadRemote

        apply_mock = _apply_async_mock()
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "g",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200
        assert apply_mock.call_count == 1

    def test_header_first_post_records_row(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.sources.upload import UploadRemote

        apply_mock = _apply_async_mock()
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "g",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": "rem-key-1"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200
        assert apply_mock.call_count == 1
        predetermined_id = apply_mock.call_args.kwargs["task_id"]
        # Scoped key: ``"{user}:{key}"``.
        row = pg_conn.execute(
            text("SELECT task_id, task_name FROM task_dedup WHERE idempotency_key = :k"),
            {"k": "u:rem-key-1"},
        ).fetchone()
        assert row is not None
        assert row[0] == predetermined_id
        assert row[1] == "ingest_remote"

    def test_same_header_second_post_returns_cached(self, app, pg_conn):
        from application.api.user.sources.upload import UploadRemote

        apply_mock = _apply_async_mock()
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
            apply_mock,
        ):
            with app.test_request_context(
                "/api/remote", method="POST",
                data={
                    "user": "u", "source": "github", "name": "g",
                    "data": json.dumps({"repo_url": "https://github.com/x/y"}),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "rem-rep"},
            ):
                from flask import request
                request.decoded_token = {"sub": "u"}
                first = UploadRemote().post()
            with app.test_request_context(
                "/api/remote", method="POST",
                data={
                    "user": "u", "source": "github", "name": "g",
                    "data": json.dumps({"repo_url": "https://github.com/x/y"}),
                },
                content_type="multipart/form-data",
                headers={"Idempotency-Key": "rem-rep"},
            ):
                from flask import request
                request.decoded_token = {"sub": "u"}
                second = UploadRemote().post()

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json == second.json
        assert apply_mock.call_count == 1

    def test_oversized_header_rejected_with_400(self, app, pg_conn):
        from application.api.user.sources.upload import UploadRemote

        oversized = "x" * 257
        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.ingest_remote.apply_async",
        ) as mock_apply, app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "g",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": oversized},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 400
        assert mock_apply.call_count == 0


def _seed_source(pg_conn, user="u", **kw):
    from application.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create("manage-src", user_id=user, **kw)


class TestManageSourceFilesIdempotency:
    """Same-key dedup contract for ``ManageSourceFiles.post``: a duplicate
    POST must not enqueue a second ``reingest_source_task``. The worker
    decorator only deduplicates *post-completion*, so the HTTP handler is
    the only place that can serialize concurrent in-flight requests.
    """

    def _add_request(self, app, src_id, user, key=None):
        kwargs = dict(
            data={
                "source_id": str(src_id),
                "operation": "add",
                "file": (io.BytesIO(b"content"), "new.txt"),
            },
            content_type="multipart/form-data",
        )
        if key is not None:
            kwargs["headers"] = {"Idempotency-Key": key}
        return app.test_request_context(
            "/api/manage_source_files", method="POST", **kwargs,
        )

    def test_no_header_enqueues_normally_no_claim_row(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-noh"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ), self._add_request(app, src["id"], user):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 200
        assert apply_mock.call_count == 1
        # No key → predetermined task_id is None, Celery generates one.
        assert apply_mock.call_args.kwargs["task_id"] is None
        n = pg_conn.execute(
            text("SELECT count(*) FROM task_dedup")
        ).scalar()
        assert n == 0

    def test_header_records_dedup_row_with_predetermined_id(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-rec"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ), self._add_request(app, src["id"], user, key="mgr-key-1"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 200
        assert apply_mock.call_count == 1
        predetermined_id = apply_mock.call_args.kwargs["task_id"]
        assert predetermined_id is not None
        assert response.json["reingest_task_id"] == predetermined_id

        row = pg_conn.execute(
            text(
                "SELECT task_id, task_name, status FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": f"{user}:mgr-key-1"},
        ).fetchone()
        assert row is not None
        assert row[0] == predetermined_id
        assert row[1] == "reingest_source_task"
        assert row[2] == "pending"

    def test_same_key_second_post_returns_cached(self, app, pg_conn):
        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-rep"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ):
            with self._add_request(app, src["id"], user, key="mgr-rep"):
                from flask import request
                request.decoded_token = {"sub": user}
                first = ManageSourceFiles().post()
            with self._add_request(app, src["id"], user, key="mgr-rep"):
                from flask import request
                request.decoded_token = {"sub": user}
                second = ManageSourceFiles().post()

        assert first.status_code == 200
        assert second.status_code == 200
        # Loser short-circuits before any storage mutation.
        assert apply_mock.call_count == 1
        # Loser's response carries the winner's task_id, not the
        # original 200-with-added_files payload.
        assert second.json["task_id"] == first.json["reingest_task_id"]
        # Confirm the loser never invoked the file-save path.
        assert fake_storage.save_file.call_count == 1

    def test_concurrent_same_key_only_one_apply_async(self, app, pg_engine):
        """N parallel same-key POSTs → exactly one apply_async."""
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager

        from application.api.user.sources.upload import ManageSourceFiles
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        user = "alice-mgr-race"
        with pg_engine.begin() as conn:
            src = SourcesRepository(conn).create(
                "race-src", user_id=user, file_path="/data",
            )

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        @contextmanager
        def _engine_session():
            with pg_engine.begin() as conn:
                yield conn

        @contextmanager
        def _engine_readonly():
            with pg_engine.connect() as conn:
                yield conn

        def fire(_idx):
            # Patches sit outside the thread pool (see below); only the
            # per-thread Flask request context is set up inside.
            with self._add_request(app, src["id"], user, key="mgr-race"):
                from flask import request
                request.decoded_token = {"sub": user}
                return ManageSourceFiles().post()

        # ``unittest.mock.patch`` is not thread-safe; set up the
        # module-attribute patches once before fanning out so every
        # thread sees the mock instead of racing on save/restore.
        with patch(
            "application.api.user.sources.upload.db_session",
            _engine_session,
        ), patch(
            "application.api.user.sources.upload.db_readonly",
            _engine_readonly,
        ), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ), ThreadPoolExecutor(max_workers=8) as ex:
            responses = list(ex.map(fire, range(8)))
        assert all(r.status_code == 200 for r in responses)
        assert apply_mock.call_count == 1

    def test_remove_directory_failure_releases_claim(self, app, pg_conn):
        """When storage.remove_directory returns False the handler must
        release the dedup row so a client retry can win the claim. Without
        the release, the next retry would silently 200-cache to a task_id
        that was never enqueued.
        """
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-rmfail"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = True
        fake_storage.remove_directory.return_value = False
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "subdir",
            },
            content_type="multipart/form-data",
            headers={"Idempotency-Key": "mgr-rmfail"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 500
        assert apply_mock.call_count == 0
        # Claim row was released so a retry can re-claim.
        n = pg_conn.execute(
            text(
                "SELECT count(*) FROM task_dedup "
                "WHERE idempotency_key = :k AND status = 'pending'"
            ),
            {"k": f"{user}:mgr-rmfail"},
        ).scalar()
        assert n == 0

    def test_storage_save_failure_releases_claim(self, app, pg_conn):
        """Regression: an exception from ``storage.save_file`` after the
        claim must release the dedup row. Pre-fix the outer ``except``
        logged + 500'd without releasing, so a retry within 24h returned
        a cached predetermined ``task_id`` for a task that never enqueued.
        """
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-storefail"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        fake_storage.save_file.side_effect = RuntimeError("disk full")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ), self._add_request(app, src["id"], user, key="mgr-storefail"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 500
        assert apply_mock.call_count == 0
        n = pg_conn.execute(
            text(
                "SELECT count(*) FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": f"{user}:mgr-storefail"},
        ).scalar()
        assert n == 0

    def test_apply_async_failure_releases_claim(self, app, pg_conn):
        """If the broker is unreachable, ``apply_async`` raises *after*
        the claim was made. The claim row must be released so a retry
        can re-claim with a fresh task_id.
        """
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-brokerdown"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()

        def _broker_down(*args, **kwargs):
            raise ConnectionError("broker unreachable")

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            side_effect=_broker_down,
        ), self._add_request(app, src["id"], user, key="mgr-brokerdown"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 500
        n = pg_conn.execute(
            text(
                "SELECT count(*) FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": f"{user}:mgr-brokerdown"},
        ).scalar()
        assert n == 0

    def test_db_update_failure_releases_claim(self, app, pg_conn):
        """A DB blip during the ``file_name_map`` update happens after
        storage mutated and the claim was made. Must still release.
        """
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles
        from application.storage.db.repositories import sources as src_module

        user = "alice-mgr-dbfail"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        original_update = src_module.SourcesRepository.update

        def _explode(self, *args, **kwargs):
            raise RuntimeError("db transient")

        src_module.SourcesRepository.update = _explode
        try:
            with _patch_db(pg_conn), patch(
                "application.api.user.sources.upload.StorageCreator.get_storage",
                return_value=fake_storage,
            ), patch(
                "application.api.user.tasks.reingest_source_task.apply_async",
                apply_mock,
            ), self._add_request(app, src["id"], user, key="mgr-dbfail"):
                from flask import request
                request.decoded_token = {"sub": user}
                response = ManageSourceFiles().post()
        finally:
            src_module.SourcesRepository.update = original_update

        assert response.status_code == 500
        # apply_async never ran because the DB raise pre-empted it.
        assert apply_mock.call_count == 0
        n = pg_conn.execute(
            text(
                "SELECT count(*) FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": f"{user}:mgr-dbfail"},
        ).scalar()
        assert n == 0

    def test_successful_path_keeps_claim_for_worker(self, app, pg_conn):
        """The claim row must persist after a successful ``apply_async``
        — the worker owns the predetermined task_id and same-key retries
        should resolve to the in-flight task, not re-enqueue.
        """
        from sqlalchemy import text

        from application.api.user.sources.upload import ManageSourceFiles

        user = "alice-mgr-keep"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "application.api.user.tasks.reingest_source_task.apply_async",
            apply_mock,
        ), self._add_request(app, src["id"], user, key="mgr-keep"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 200
        # Row is still there in pending status — worker has not finalised yet.
        row = pg_conn.execute(
            text(
                "SELECT status FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": f"{user}:mgr-keep"},
        ).fetchone()
        assert row is not None
        assert row[0] == "pending"
