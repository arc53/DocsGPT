"""Route-layer tests for the artifacts API (parent-derived authz)."""

from __future__ import annotations

import io
import uuid
from contextlib import contextmanager

import pytest
from flask import request
from sqlalchemy import text

from application.api.user.artifacts import authz
from application.storage.db.repositories.agents import AgentsRepository
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


def _make_agent(conn, user_id=OWNER, key="secret-key"):
    return AgentsRepository(conn).create(user_id, "widget-agent", "active", key=key)


def _make_agent_conversation(conn, agent_id, user_id=OWNER):
    return ConversationsRepository(conn).create(
        user_id, name="conv", agent_id=str(agent_id)
    )


def _make_message(conn, conversation_id, prompt="q", response="a"):
    return ConversationsRepository(conn).append_message(
        conversation_id, {"prompt": prompt, "response": response}
    )


def _wire_api_key(monkeypatch, conn):
    """Point ``resolve_principal``'s own readonly conn at the test conn.

    ``resolve_principal`` opens ``db_readonly`` inside authz to resolve the
    api_key via the real ``find_by_key``, so it must see the seeded agent row.
    """
    from contextlib import contextmanager as _cm

    @_cm
    def _use_conn():
        yield conn

    monkeypatch.setattr(authz, "db_readonly", _use_conn)


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
        # Attach to the first message so it falls inside the first_n_queries snapshot.
        msg = _make_message(_patch_db, str(conv["id"]))
        art = _make_artifact(
            _patch_db,
            conversation_id=str(conv["id"]),
            message_id=str(msg["id"]),
            filename="report.pdf",
            mime_type="application/pdf",
            storage_path="inputs/owner/artifacts/x/v1/report.pdf",
        )
        share = SharedConversationsRepository(_patch_db).create(
            str(conv["id"]), OWNER, first_n_queries=1
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
# Share-token snapshot scoping (first_n_queries)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestShareTokenSnapshotScope:
    """A share link exposes only artifacts within its first_n_queries snapshot."""

    def _seed(self, conn, first_n=1):
        conv = _make_conversation(conn)
        conv_id = str(conv["id"])
        m0 = _make_message(conn, conv_id, prompt="q0")  # position 0 (in snapshot)
        m1 = _make_message(conn, conv_id, prompt="q1")  # position 1 (outside)
        in_art = _make_artifact(
            conn, conversation_id=conv_id, message_id=str(m0["id"]),
            title="in", filename="in.pdf",
            storage_path="inputs/owner/artifacts/in/v1/in.pdf",
        )
        out_art = _make_artifact(
            conn, conversation_id=conv_id, message_id=str(m1["id"]),
            title="out", filename="out.pdf",
            storage_path="inputs/owner/artifacts/out/v1/out.pdf",
        )
        null_art = _make_artifact(
            conn, conversation_id=conv_id, message_id=None, title="null",
            filename="null.pdf",
            storage_path="inputs/owner/artifacts/null/v1/null.pdf",
        )
        share = SharedConversationsRepository(conn).create(
            conv_id, OWNER, first_n_queries=first_n
        )
        return conv_id, in_art, out_art, null_art, str(share["uuid"])

    @staticmethod
    def _mock_storage(monkeypatch, data=b"BYTES"):
        storage = _FakeStorage(data)
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "backend", raising=False,
        )
        return storage

    def test_share_token_list_only_snapshot(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import ListArtifacts

        conv_id, in_art, out_art, null_art, token = self._seed(_patch_db)
        resp = _call(
            flask_app, ListArtifacts, token=None,
            query={"conversation_id": conv_id, "share_token": token},
        )
        assert resp.status_code == 200
        ids = {a["id"] for a in resp.json["artifacts"]}
        assert str(in_art["id"]) in ids
        assert str(out_art["id"]) not in ids  # outside first_n_queries
        assert str(null_art["id"]) not in ids  # NULL message_id -> not in snapshot

    def test_share_token_get_in_snapshot_200(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        _, in_art, _out, _null, token = self._seed(_patch_db)
        resp = _call(
            flask_app, GetArtifact, in_art["id"], token=None,
            query={"share_token": token},
        )
        assert resp.status_code == 200

    def test_share_token_get_out_of_snapshot_403(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        _, _in, out_art, _null, token = self._seed(_patch_db)
        resp = _call(
            flask_app, GetArtifact, out_art["id"], token=None,
            query={"share_token": token},
        )
        assert resp.status_code == 403

    def test_share_token_null_message_id_denied(self, _patch_db, flask_app):
        from application.api.user.artifacts.routes import GetArtifact

        _, _in, _out, null_art, token = self._seed(_patch_db)
        resp = _call(
            flask_app, GetArtifact, null_art["id"], token=None,
            query={"share_token": token},
        )
        assert resp.status_code == 403

    def test_share_token_download_in_snapshot_200(
        self, _patch_db, flask_app, monkeypatch
    ):
        from application.api.user.artifacts.routes import DownloadArtifact

        _, in_art, _out, _null, token = self._seed(_patch_db)
        self._mock_storage(monkeypatch, b"INDATA")
        resp = _call(
            flask_app, DownloadArtifact, in_art["id"], token=None,
            query={"share_token": token},
        )
        assert resp.status_code == 200
        assert resp.data == b"INDATA"

    def test_share_token_download_out_of_snapshot_403(
        self, _patch_db, flask_app, monkeypatch
    ):
        from application.api.user.artifacts.routes import DownloadArtifact

        _, _in, out_art, _null, token = self._seed(_patch_db)
        self._mock_storage(monkeypatch, b"OUTDATA")
        resp = _call(
            flask_app, DownloadArtifact, out_art["id"], token=None,
            query={"share_token": token},
        )
        assert resp.status_code == 403

    def test_owner_sees_all_artifacts(self, _patch_db, flask_app, token_owner):
        # Snapshot scoping is share-token-only: the owner lists every artifact and
        # can fetch one attached to a message outside the first_n_queries snapshot.
        from application.api.user.artifacts.routes import GetArtifact, ListArtifacts

        conv_id, in_art, out_art, null_art, _token = self._seed(_patch_db)
        listed = _call(
            flask_app, ListArtifacts, token=token_owner,
            query={"conversation_id": conv_id},
        )
        assert listed.status_code == 200
        ids = {a["id"] for a in listed.json["artifacts"]}
        assert {str(in_art["id"]), str(out_art["id"]), str(null_art["id"])} <= ids

        got = _call(flask_app, GetArtifact, out_art["id"], token=token_owner)
        assert got.status_code == 200

    def test_shared_with_collaborator_sees_all_artifacts(self, _patch_db, flask_app):
        # A read-only shared_with collaborator (JWT) is not snapshot-scoped either.
        from application.api.user.artifacts.routes import GetArtifact, ListArtifacts

        conv_id, in_art, out_art, null_art, _token = self._seed(_patch_db)
        ConversationsRepository(_patch_db).add_shared_user(conv_id, SHARED_USER)

        listed = _call(
            flask_app, ListArtifacts, token={"sub": SHARED_USER},
            query={"conversation_id": conv_id},
        )
        assert listed.status_code == 200
        ids = {a["id"] for a in listed.json["artifacts"]}
        assert {str(in_art["id"]), str(out_art["id"]), str(null_art["id"])} <= ids

        got = _call(
            flask_app, GetArtifact, out_art["id"], token={"sub": SHARED_USER}
        )
        assert got.status_code == 200


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

    def test_s3_strategy_disposition_url_returns_json(
        self, _patch_db, flask_app, token_owner, monkeypatch
    ):
        # ?disposition=url opts into a JSON envelope (for a top-level browser
        # navigation) instead of the CORS-blocked cross-origin 302.
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

        resp = _call(
            flask_app,
            DownloadArtifact,
            art["id"],
            token=token_owner,
            query={"disposition": "url"},
        )
        assert resp.status_code == 200
        assert resp.json["success"] is True
        assert resp.json["url"].startswith("https://signed.example/")
        # The envelope carries a distinctive media type so the client keys off
        # a server signal, not the JSON body shape (open-redirect gadget guard).
        assert resp.mimetype == "application/vnd.docsgpt.artifact-url+json"

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
# api_key -> agent-scoped principal (low-trust, widget-embedded credential)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestApiKeyPrincipal:
    def test_api_key_reads_artifact_with_matching_conversation_id(
        self, _patch_db, flask_app, monkeypatch
    ):
        # The public widget key reads an artifact ONLY when the request also
        # carries the parent conversation_id (the per-visitor bearer capability).
        from application.api.user.artifacts.routes import GetArtifact

        agent = _make_agent(_patch_db)
        conv = _make_agent_conversation(_patch_db, agent["id"])
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "secret-key", "conversation_id": str(conv["id"])},
        )
        assert resp.status_code == 200
        assert resp.json["artifact"]["id"] == str(art["id"])

    def test_api_key_get_without_conversation_id_denied(
        self, _patch_db, flask_app, monkeypatch
    ):
        # Regression (critical IDOR): the public widget key alone -- without the
        # unguessable per-visitor conversation_id -- cannot fetch a known artifact.
        from application.api.user.artifacts.routes import GetArtifact

        agent = _make_agent(_patch_db)
        conv = _make_agent_conversation(_patch_db, agent["id"])
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "secret-key"},
        )
        assert resp.status_code == 403

    def test_api_key_cannot_read_owner_artifact_outside_agent_scope(
        self, _patch_db, flask_app, monkeypatch
    ):
        # Regression (critical IDOR): a public widget key resolves to the owner
        # but must NOT reach an artifact from the owner's OTHER (non-agent)
        # conversation -- even when it supplies that conversation_id, the agent
        # scope gate still blocks it.
        from application.api.user.artifacts.routes import GetArtifact

        _make_agent(_patch_db)  # the widget agent (key=secret-key)
        other_conv = _make_conversation(_patch_db, user_id=OWNER)  # no agent_id
        art = _make_artifact(_patch_db, conversation_id=str(other_conv["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "secret-key", "conversation_id": str(other_conv["id"])},
        )
        assert resp.status_code == 403

    def test_api_key_download_requires_conversation_id(
        self, _patch_db, flask_app, monkeypatch
    ):
        # Download follows the same bearer-capability rule as get: the key alone is
        # denied; the key + matching conversation_id is served.
        from application.api.user.artifacts.routes import DownloadArtifact

        agent = _make_agent(_patch_db)
        conv = _make_agent_conversation(_patch_db, agent["id"])
        art = _make_artifact(
            _patch_db, conversation_id=str(conv["id"]),
            filename="f.bin", storage_path="inputs/owner/artifacts/x/v1/f.bin",
        )
        _wire_api_key(monkeypatch, _patch_db)
        storage = _FakeStorage(b"BYTES")
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.StorageCreator.get_storage",
            lambda: storage,
        )
        monkeypatch.setattr(
            "application.api.user.artifacts.routes.settings.URL_STRATEGY",
            "backend", raising=False,
        )

        denied = _call(
            flask_app, DownloadArtifact, art["id"], token=None,
            query={"api_key": "secret-key"},
        )
        assert denied.status_code == 403

        ok = _call(
            flask_app, DownloadArtifact, art["id"], token=None,
            query={"api_key": "secret-key", "conversation_id": str(conv["id"])},
        )
        assert ok.status_code == 200
        assert ok.data == b"BYTES"

    def test_api_key_list_without_conversation_id_forbidden(
        self, _patch_db, flask_app, monkeypatch
    ):
        # Regression (critical IDOR): the public widget key cannot enumerate the
        # agent's artifacts -- a list with no conversation_id is refused outright.
        from application.api.user.artifacts.routes import ListArtifacts

        agent = _make_agent(_patch_db)
        conv = _make_agent_conversation(_patch_db, agent["id"])
        _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(flask_app, ListArtifacts, token=None, query={"api_key": "secret-key"})
        assert resp.status_code == 403

    def test_api_key_list_with_conversation_id_scoped_to_it(
        self, _patch_db, flask_app, monkeypatch
    ):
        # With the per-visitor conversation_id the list returns only that
        # conversation's artifacts -- not the agent's other conversations.
        from application.api.user.artifacts.routes import ListArtifacts

        agent = _make_agent(_patch_db)
        conv_a = _make_agent_conversation(_patch_db, agent["id"])
        conv_b = _make_agent_conversation(_patch_db, agent["id"])
        in_scope = _make_artifact(_patch_db, conversation_id=str(conv_a["id"]))
        other = _make_artifact(_patch_db, conversation_id=str(conv_b["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, ListArtifacts, token=None,
            query={"api_key": "secret-key", "conversation_id": str(conv_a["id"])},
        )
        assert resp.status_code == 200
        ids = {a["id"] for a in resp.json["artifacts"]}
        assert str(in_scope["id"]) in ids
        assert str(other["id"]) not in ids

    def test_api_key_list_foreign_conversation_id_returns_empty(
        self, _patch_db, flask_app, monkeypatch
    ):
        # A conversation_id belonging to a DIFFERENT agent leaks nothing: the JOIN
        # filters it out, yielding an empty 200 rather than a cross-visitor leak.
        from application.api.user.artifacts.routes import ListArtifacts

        agent = _make_agent(_patch_db)
        agent_conv = _make_agent_conversation(_patch_db, agent["id"])
        _make_artifact(_patch_db, conversation_id=str(agent_conv["id"]))
        other_agent = _make_agent(_patch_db, user_id=OWNER, key="other-key")
        other_conv = _make_agent_conversation(_patch_db, other_agent["id"])
        _make_artifact(_patch_db, conversation_id=str(other_conv["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, ListArtifacts, token=None,
            query={"api_key": "secret-key", "conversation_id": str(other_conv["id"])},
        )
        assert resp.status_code == 200
        assert resp.json["artifacts"] == []

    def test_api_key_cannot_delete_even_in_scope(
        self, _patch_db, flask_app, monkeypatch
    ):
        # Mutations require a JWT owner; a low-trust agent key may never delete,
        # even an artifact inside its own agent scope.
        from application.api.user.artifacts.routes import GetArtifact

        agent = _make_agent(_patch_db)
        conv = _make_agent_conversation(_patch_db, agent["id"])
        art = _make_artifact(_patch_db, conversation_id=str(conv["id"]))
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "secret-key"}, method="delete",
        )
        assert resp.status_code == 403
        assert ArtifactsRepository(_patch_db).get_artifact(art["id"]) is not None

    def test_api_key_resolving_to_stranger_denied(
        self, _patch_db, flask_app, monkeypatch
    ):
        # A key owned by a different user cannot reach this owner's artifact.
        from application.api.user.artifacts.routes import GetArtifact

        owner_conv = _make_conversation(_patch_db, user_id=OWNER)
        art = _make_artifact(_patch_db, conversation_id=str(owner_conv["id"]))
        stranger_agent = _make_agent(_patch_db, user_id=STRANGER, key="stranger-key")
        _make_agent_conversation(_patch_db, stranger_agent["id"], user_id=STRANGER)
        _wire_api_key(monkeypatch, _patch_db)

        resp = _call(
            flask_app, GetArtifact, art["id"], token=None,
            query={"api_key": "stranger-key"},
        )
        assert resp.status_code == 403


# A full-app integration test (namespace registration + auth before_request)
# is covered by the e2e suite under tests/e2e; the unit tests above exercise
# the malformed-id gate and the api_key principal path directly against the
# Resource handlers without building the whole app.
