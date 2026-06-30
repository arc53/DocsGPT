"""Route-layer tests for the artifacts API (parent-derived authz)."""

from __future__ import annotations

import io
import uuid
from contextlib import contextmanager

import pytest
from flask import request
from sqlalchemy import text

from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.shared_conversations import (
    SharedConversationsRepository,
)
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository


OWNER = "artifact_owner"
STRANGER = "artifact_stranger"
SHARED_USER = "artifact_shared_user"


@pytest.fixture
def _patch_db(pg_conn, monkeypatch):
    """Redirect the routes' ``db_readonly`` / ``db_session`` to the test conn."""

    @contextmanager
    def _use_conn():
        yield pg_conn

    monkeypatch.setattr("application.api.user.artifacts.routes.db_readonly", _use_conn)
    monkeypatch.setattr("application.api.user.artifacts.routes.db_session", _use_conn)
    return pg_conn


@pytest.fixture
def token_owner():
    return {"sub": OWNER, "email": "owner@example.com"}


def _make_conversation(conn, user_id=OWNER):
    return ConversationsRepository(conn).create(user_id, name="conv")


def _make_workflow(conn, user_id=OWNER):
    res = conn.execute(
        text("INSERT INTO workflows (user_id, name) VALUES (:u, 'wf') RETURNING id"),
        {"u": user_id},
    )
    return str(res.fetchone()[0])


def _make_artifact(conn, **kwargs):
    return ArtifactsRepository(conn).create_artifact(
        kwargs.pop("user_id", OWNER),
        kwargs.pop("kind", "document"),
        **kwargs,
    )


def _call(flask_app, resource_cls, *args, token=None, query=None, json_body=None, method="get"):
    with flask_app.app_context():
        with flask_app.test_request_context(query_string=query or {}, json=json_body):
            request.decoded_token = token
            resource = resource_cls()
            return getattr(resource, method)(*args)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestListArtifacts:
    def test_owner_lists_conversation_artifacts(
        self, _patch_db, flask_app, token_owner
    ):
        from application.api.user.artifacts.routes import ListArtifacts

        conv = _make_conversation(_patch_db)
        conv_id = str(conv["id"])
        _make_artifact(_patch_db, conversation_id=conv_id, title="a1")
        _make_artifact(_patch_db, conversation_id=conv_id, title="a2")

        resp = _call(
            flask_app, ListArtifacts, token=token_owner,
            query={"conversation_id": conv_id},
        )
        assert resp.status_code == 200
        assert len(resp.json["artifacts"]) == 2

    def test_stranger_denied_conversation_list(
        self, _patch_db, flask_app
    ):
        from application.api.user.artifacts.routes import ListArtifacts

        conv = _make_conversation(_patch_db)
        _make_artifact(_patch_db, conversation_id=str(conv["id"]))

        resp = _call(
            flask_app, ListArtifacts,
            token={"sub": STRANGER},
            query={"conversation_id": str(conv["id"])},
        )
        assert resp.status_code == 403

    def test_no_filter_scopes_to_user(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import ListArtifacts

        owner_conv = _make_conversation(_patch_db)
        owned = _make_artifact(
            _patch_db, conversation_id=str(owner_conv["id"]), user_id=OWNER
        )
        stranger = _make_artifact(
            _patch_db, conversation_id=str(_make_conversation(_patch_db)["id"]),
            user_id=STRANGER,
        )

        resp = _call(flask_app, ListArtifacts, token=token_owner)
        assert resp.status_code == 200
        # The owner id is accounting-only and must not leak in the summary.
        assert all("user_id" not in a for a in resp.json["artifacts"])
        returned_ids = {a["id"] for a in resp.json["artifacts"]}
        assert str(owned["id"]) in returned_ids
        assert str(stranger["id"]) not in returned_ids

    def test_unauthenticated_401(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import ListArtifacts

        resp = _call(flask_app, ListArtifacts, token=None)
        assert resp.status_code == 401

    def test_non_uuid_conversation_id_400(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import ListArtifacts

        # A malformed id must be rejected before reaching CAST(:id AS uuid),
        # which would otherwise raise a DataError and poison the transaction.
        resp = _call(
            flask_app, ListArtifacts, token=token_owner,
            query={"conversation_id": "not-a-uuid"},
        )
        assert resp.status_code == 400

    def test_non_uuid_workflow_run_id_400(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import ListArtifacts

        resp = _call(
            flask_app, ListArtifacts, token=token_owner,
            query={"workflow_run_id": "1234"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Get + versions
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGetArtifact:
    def test_owner_gets_artifact_with_versions(
        self, _patch_db, flask_app, token_owner
    ):
        from application.api.user.artifacts.routes import GetArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(
            _patch_db, conversation_id=str(conv["id"]), spec={"body": "v1"}
        )
        ArtifactsRepository(_patch_db).append_version(art["id"], spec={"body": "v2"})

        resp = _call(flask_app, GetArtifact, art["id"], token=token_owner)
        assert resp.status_code == 200
        assert resp.json["artifact"]["current_version"] == 2
        assert len(resp.json["artifact"]["versions"]) == 2
        assert resp.json["artifact"]["spec"] == {"body": "v2"}

    def test_stranger_denied_403(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))

        resp = _call(flask_app, GetArtifact, art["id"], token={"sub": STRANGER})
        assert resp.status_code == 403

    def test_missing_parent_fails_closed(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import GetArtifact
        from sqlalchemy import text

        conv = _make_conversation(_patch_db)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        # Delete the parent conversation -> the artifact must no longer be reachable.
        _patch_db.execute(
            text("DELETE FROM conversations WHERE id = CAST(:id AS uuid)"),
            {"id": str(conv["id"])},
        )

        resp = _call(flask_app, GetArtifact, art["id"], token=token_owner)
        assert resp.status_code == 403

    def test_unknown_artifact_404(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import GetArtifact

        resp = _call(flask_app, GetArtifact, str(uuid.uuid4()), token=token_owner)
        assert resp.status_code == 404

    def test_workflow_run_owner_access(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import GetArtifact

        wf_id = _make_workflow(_patch_db, OWNER)
        run = WorkflowRunsRepository(_patch_db).create(wf_id, OWNER, "completed")
        art = _make_artifact(_patch_db, workflow_run_id=str(run["id"]))

        resp = _call(flask_app, GetArtifact, art["id"], token=token_owner)
        assert resp.status_code == 200

        resp_other = _call(
            flask_app, GetArtifact, art["id"], token={"sub": STRANGER}
        )
        assert resp_other.status_code == 403


@pytest.mark.unit
class TestGetArtifactVersion:
    def test_version_returns_spec(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import GetArtifactVersion

        conv = _make_conversation(_patch_db)
        art = _make_artifact(
            _patch_db, conversation_id=str(conv["id"]), spec={"body": "one"}
        )
        resp = _call(flask_app, GetArtifactVersion, art["id"], 1, token=token_owner)
        assert resp.status_code == 200
        assert resp.json["version"]["spec"] == {"body": "one"}

    def test_missing_version_404(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import GetArtifactVersion

        conv = _make_conversation(_patch_db)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        resp = _call(flask_app, GetArtifactVersion, art["id"], 99, token=token_owner)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Shared-conversation inheritance
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSharedAccess:
    def test_shared_with_user_can_get(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        conv = _make_conversation(_patch_db)
        ConversationsRepository(_patch_db).add_shared_user(str(conv["id"]), SHARED_USER)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))

        resp = _call(flask_app, GetArtifact, art["id"], token={"sub": SHARED_USER})
        assert resp.status_code == 200

    def test_share_token_holder_can_download(self, _patch_db, flask_app, monkeypatch):
        from application.api.user.artifacts.routes import DownloadArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(
            _patch_db,
            conversation_id=str(conv["id"]),
            filename="report.pdf",
            mime_type="application/pdf",
            storage_path="inputs/owner/artifacts/x/v1/report.pdf",
        )
        share = SharedConversationsRepository(_patch_db).create(
            str(conv["id"]), OWNER
        )

        storage = _FakeStorage(b"PDFDATA")
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "backend",
            raising=False,
        )

        # Anonymous link holder (no JWT) supplies the share token.
        resp = _call(
            flask_app, DownloadArtifact, art["id"], token=None,
            query={"share_token": str(share["uuid"])},
        )
        assert resp.status_code == 200
        assert resp.data == b"PDFDATA"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
class _FakeStorage:
    def __init__(self, data: bytes = b""):
        self._data = data
        self.deleted: list = []

    def get_file(self, path):
        return io.BytesIO(self._data)

    def generate_presigned_url(self, path, expires_in=300):
        return f"https://signed.example/{path}?exp={expires_in}"

    def delete_file(self, path):
        self.deleted.append(path)
        return True


@pytest.mark.unit
class TestDownloadArtifact:
    def _seed(self, conn, **over):
        conv = _make_conversation(conn)
        defaults = dict(
            conversation_id=str(conv["id"]),
            filename="deck.pptx",
            mime_type="application/vnd.ms-powerpoint",
            storage_path="inputs/owner/artifacts/x/v1/deck.pptx",
        )
        defaults.update(over)
        return _make_artifact(conn, **defaults)

    def test_local_streams_bytes_with_content_disposition(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        from application.api.user.artifacts.routes import DownloadArtifact

        art = self._seed(_patch_db)
        storage = _FakeStorage(b"BINARY")
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "backend",
            raising=False,
        )

        resp = _call(flask_app, DownloadArtifact, art["id"], token=token_owner)
        assert resp.status_code == 200
        assert resp.data == b"BINARY"
        assert resp.headers["Content-Disposition"] == 'attachment; filename="deck.pptx"'
        assert resp.headers["Content-Type"] == "application/vnd.ms-powerpoint"

    def test_local_download_is_streamed_not_buffered(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        # The response body must be a stream (generator), not the whole object
        # buffered into memory via make_response(file_obj.read()).
        from application.api.user.artifacts.routes import DownloadArtifact

        art = self._seed(_patch_db)
        storage = _FakeStorage(b"Z" * 200_000)
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "backend", raising=False,
        )
        resp = _call(flask_app, DownloadArtifact, art["id"], token=token_owner)
        assert resp.is_streamed
        assert resp.get_data() == b"Z" * 200_000

    def test_s3_strategy_redirects_to_presigned(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        from application.api.user.artifacts.routes import DownloadArtifact

        art = self._seed(_patch_db)
        storage = _FakeStorage(b"unused")
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "s3",
            raising=False,
        )

        resp = _call(flask_app, DownloadArtifact, art["id"], token=token_owner)
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("https://signed.example/")

    def test_stranger_denied(self, _patch_db, flask_app, monkeypatch):
        from application.api.user.artifacts.routes import DownloadArtifact

        art = self._seed(_patch_db)
        resp = _call(flask_app, DownloadArtifact, art["id"], token={"sub": STRANGER})
        assert resp.status_code == 403

    def test_s3_strategy_misconfigured_backend_500(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        from application.api.user.artifacts.routes import DownloadArtifact

        art = self._seed(_patch_db)

        class _NoPresignStorage:
            def get_file(self, path):
                return io.BytesIO(b"unused")

            def generate_presigned_url(self, path, expires_in=300):
                raise NotImplementedError("backend cannot mint presigned URLs")

        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: _NoPresignStorage(),
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "s3",
            raising=False,
        )

        resp = _call(flask_app, DownloadArtifact, art["id"], token=token_owner)
        assert resp.status_code == 500

    def test_crlf_filename_sanitized_in_header(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        from application.api.user.artifacts.routes import DownloadArtifact

        art = self._seed(_patch_db, filename='a"\r\nInjected: x.txt')
        storage = _FakeStorage(b"X")
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "backend",
            raising=False,
        )
        resp = _call(flask_app, DownloadArtifact, art["id"], token=token_owner)
        disposition = resp.headers["Content-Disposition"]
        assert "\r" not in disposition and "\n" not in disposition
        assert disposition == 'attachment; filename="aInjected: x.txt"'


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRestoreArtifact:
    def test_restore_appends_new_version(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import RestoreArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(
            _patch_db, conversation_id=str(conv["id"]), spec={"body": "v1"}
        )
        ArtifactsRepository(_patch_db).append_version(art["id"], spec={"body": "v2"})

        resp = _call(
            flask_app, RestoreArtifact, art["id"], token=token_owner,
            json_body={"version": 1}, method="post",
        )
        assert resp.status_code == 200
        assert resp.json["version"]["version"] == 3
        assert resp.json["version"]["spec"] == {"body": "v1"}
        assert ArtifactsRepository(_patch_db).get_artifact(art["id"])["current_version"] == 3

    def test_restore_missing_version_field_400(
        self, _patch_db, flask_app, token_owner
    ):
        from application.api.user.artifacts.routes import RestoreArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        resp = _call(
            flask_app, RestoreArtifact, art["id"], token=token_owner,
            json_body={}, method="post",
        )
        assert resp.status_code == 400

    def test_restore_stranger_denied(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import RestoreArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        resp = _call(
            flask_app, RestoreArtifact, art["id"], token={"sub": STRANGER},
            json_body={"version": 1}, method="post",
        )
        assert resp.status_code == 403

    def test_restore_anonymous_share_token_holder_denied(
        self, _patch_db, flask_app
    ):
        # A share link inherits read/download access only; restore is a WRITE and
        # an anonymous link holder must NOT be able to mutate the artifact.
        from application.api.user.artifacts.routes import RestoreArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(
            _patch_db, conversation_id=str(conv["id"]), spec={"body": "v1"}
        )
        ArtifactsRepository(_patch_db).append_version(art["id"], spec={"body": "v2"})
        share = SharedConversationsRepository(_patch_db).create(str(conv["id"]), OWNER)

        resp = _call(
            flask_app, RestoreArtifact, art["id"], token=None,
            query={"share_token": str(share["uuid"])},
            json_body={"version": 1}, method="post",
        )
        assert resp.status_code == 403
        # The artifact is unchanged (still at version 2, not reverted/appended).
        assert ArtifactsRepository(_patch_db).get_artifact(art["id"])["current_version"] == 2

    def test_restore_shared_with_collaborator_denied(self, _patch_db, flask_app):
        # A read-only ``shared_with`` collaborator can GET but not restore.
        from application.api.user.artifacts.routes import RestoreArtifact

        conv = _make_conversation(_patch_db)
        ConversationsRepository(_patch_db).add_shared_user(str(conv["id"]), SHARED_USER)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        ArtifactsRepository(_patch_db).append_version(art["id"], spec={"body": "v2"})

        resp = _call(
            flask_app, RestoreArtifact, art["id"], token={"sub": SHARED_USER},
            json_body={"version": 1}, method="post",
        )
        assert resp.status_code == 403


@pytest.mark.unit
class TestDeleteArtifact:
    def _seed(self, conn, **over):
        conv = _make_conversation(conn)
        defaults = dict(
            conversation_id=str(conv["id"]),
            filename="f.bin",
            storage_path="inputs/owner/artifacts/x/v1/f.bin",
        )
        defaults.update(over)
        return _make_artifact(conn, **defaults)

    def test_owner_deletes_and_reaps_bytes(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        from application.api.user.artifacts.routes import GetArtifact

        art = self._seed(_patch_db)
        storage = _FakeStorage()
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        resp = _call(flask_app, GetArtifact, art["id"], token=token_owner, method="delete")
        assert resp.status_code == 200
        assert ArtifactsRepository(_patch_db).get_artifact(art["id"]) is None
        assert "inputs/owner/artifacts/x/v1/f.bin" in storage.deleted

    def test_stranger_denied(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        art = self._seed(_patch_db)
        resp = _call(
            flask_app, GetArtifact, art["id"], token={"sub": STRANGER}, method="delete"
        )
        assert resp.status_code == 403
        assert ArtifactsRepository(_patch_db).get_artifact(art["id"]) is not None

    def test_share_token_holder_denied(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        conv = _make_conversation(_patch_db)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        share = SharedConversationsRepository(_patch_db).create(str(conv["id"]), OWNER)
        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"share_token": str(share["uuid"])}, method="delete",
        )
        assert resp.status_code == 403
        assert ArtifactsRepository(_patch_db).get_artifact(art["id"]) is not None

    def test_unknown_artifact_404(self, _patch_db, flask_app, token_owner):
        from application.api.user.artifacts.routes import GetArtifact

        resp = _call(
            flask_app, GetArtifact, str(uuid.uuid4()), token=token_owner, method="delete"
        )
        assert resp.status_code == 404


@pytest.mark.unit
class TestConversationDeleteReapsArtifacts:
    def test_delete_conversation_removes_artifacts_frees_quota_and_reaps_bytes(
        self, _patch_db, flask_app, monkeypatch
    ):
        conv = _make_conversation(_patch_db)
        art = _make_artifact(
            _patch_db, conversation_id=str(conv["id"]),
            storage_path="k/reap.bin", filename="r.bin", size=42,
        )
        storage = _FakeStorage()
        monkeypatch.setattr(
            "application.storage.storage_creator.StorageCreator.get_storage",
            lambda: storage,
        )

        deleted = ConversationsRepository(_patch_db).delete(str(conv["id"]), OWNER)
        assert deleted is True

        repo = ArtifactsRepository(_patch_db)
        assert repo.get_artifact(art["id"]) is None  # cascade-removed with the parent
        assert repo.count_for_user(OWNER) == 0  # quota freed
        assert "k/reap.bin" in storage.deleted  # bytes reaped


# ---------------------------------------------------------------------------
# Malformed artifact_id path segment -> 404 (no CAST(:id AS uuid) txn poison)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMalformedArtifactId:
    @pytest.mark.parametrize(
        "resource_name, extra_args, method, json_body",
        [
            ("GetArtifact", (), "get", None),
            ("GetArtifactVersion", (1,), "get", None),
            ("DownloadArtifact", (), "get", None),
            ("RestoreArtifact", (), "post", {"version": 1}),
        ],
    )
    def test_non_uuid_id_returns_404(
        self, _patch_db, flask_app, token_owner, resource_name,
        extra_args, method, json_body,
    ):
        from application.api.user.artifacts import routes as routes_mod

        resource_cls = getattr(routes_mod, resource_name)
        resp = _call(
            flask_app, resource_cls, "legacy-mongo-objectid-aabbcc", *extra_args,
            token=token_owner, method=method, json_body=json_body,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# api_key -> agent-owner principal resolution
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestApiKeyPrincipal:
    def test_api_key_owner_can_get_owned_artifact(
        self, _patch_db, flask_app, monkeypatch
    ):
        from application.api.user.artifacts import authz
        from application.api.user.artifacts.routes import GetArtifact
        from application.storage.db.repositories.agents import AgentsRepository

        conv = _make_conversation(_patch_db, user_id=OWNER)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))

        # The api_key path opens its own readonly conn inside authz; point it at
        # the test conn and resolve the key to the artifact's owning agent.
        @contextmanager
        def _use_conn():
            yield _patch_db

        monkeypatch.setattr(authz, "db_readonly", _use_conn)
        monkeypatch.setattr(
            AgentsRepository, "find_by_key",
            lambda self, key: {"user_id": OWNER} if key == "secret-key" else None,
        )

        # No JWT -> principal must be resolved from the api_key query param.
        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "secret-key"},
        )
        assert resp.status_code == 200
        assert resp.json["artifact"]["id"] == str(art["id"])

    def test_api_key_resolving_to_stranger_denied(
        self, _patch_db, flask_app, monkeypatch
    ):
        from application.api.user.artifacts import authz
        from application.api.user.artifacts.routes import GetArtifact
        from application.storage.db.repositories.agents import AgentsRepository

        conv = _make_conversation(_patch_db, user_id=OWNER)
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))

        @contextmanager
        def _use_conn():
            yield _patch_db

        monkeypatch.setattr(authz, "db_readonly", _use_conn)
        monkeypatch.setattr(
            AgentsRepository, "find_by_key",
            lambda self, key: {"user_id": STRANGER},
        )

        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "stranger-key"},
        )
        assert resp.status_code == 403


# A full-app integration test (namespace registration + auth before_request)
# is covered by the e2e suite under tests/e2e; the unit tests above exercise
# the malformed-id gate and the api_key principal path directly against the
# Resource handlers without building the whole app.
