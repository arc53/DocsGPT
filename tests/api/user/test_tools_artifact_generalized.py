"""Tests for the generalized GET /api/tools/artifact/<id> document branch."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from flask import request

from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.notes import NotesRepository
from application.storage.db.repositories.user_tools import UserToolsRepository


@pytest.fixture
def _patch_db(pg_conn, monkeypatch):
    """Point both the tools and artifacts route DB helpers at the test conn."""

    @contextmanager
    def _use_conn():
        yield pg_conn

    monkeypatch.setattr("application.api.user.tools.routes.db_readonly", _use_conn)
    monkeypatch.setattr("application.api.user.artifacts.routes.db_readonly", _use_conn)
    return pg_conn


def _get(flask_app, artifact_id, token):
    from application.api.user.tools.routes import GetArtifact

    with flask_app.app_context():
        with flask_app.test_request_context():
            request.decoded_token = token
            return GetArtifact().get(artifact_id)


@pytest.mark.unit
class TestGeneralizedToolsArtifact:
    def test_document_branch_returns_metadata(
        self, _patch_db, flask_app, decoded_token
    ):
        conv = ConversationsRepository(_patch_db).create(
            decoded_token["sub"], name="conv"
        )
        art = ArtifactsRepository(_patch_db).create_artifact(
            decoded_token["sub"],
            "document",
            conversation_id=str(conv["id"]),
            title="Report",
            filename="report.pdf",
            mime_type="application/pdf",
            storage_path="inputs/u/artifacts/x/v1/report.pdf",
        )

        resp = _get(flask_app, art["id"], decoded_token)
        assert resp.status_code == 200
        body = resp.json["artifact"]
        assert body["artifact_type"] == "document"
        assert body["data"]["title"] == "Report"
        assert body["data"]["filename"] == "report.pdf"
        assert body["data"]["download_url"] == f"/api/artifacts/{art['id']}/download"

    def test_file_kind_maps_to_file_type(self, _patch_db, flask_app, decoded_token):
        conv = ConversationsRepository(_patch_db).create(
            decoded_token["sub"], name="conv"
        )
        art = ArtifactsRepository(_patch_db).create_artifact(
            decoded_token["sub"],
            "file",
            conversation_id=str(conv["id"]),
            storage_path="inputs/u/artifacts/y/v1/data.bin",
        )
        resp = _get(flask_app, art["id"], decoded_token)
        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "file"

    def test_stranger_document_not_found(self, _patch_db, flask_app, decoded_token):
        conv = ConversationsRepository(_patch_db).create("other_owner", name="conv")
        art = ArtifactsRepository(_patch_db).create_artifact(
            "other_owner",
            "document",
            conversation_id=str(conv["id"]),
            storage_path="inputs/o/artifacts/z/v1/x.pdf",
        )
        # Parent-derived authz denies a stranger -> falls through to 404.
        resp = _get(flask_app, art["id"], decoded_token)
        assert resp.status_code == 404

    def test_note_branch_still_works(self, _patch_db, flask_app, decoded_token):
        tool = UserToolsRepository(_patch_db).create(
            user_id=decoded_token["sub"], name="notes_tool"
        )
        note = NotesRepository(_patch_db).upsert(
            user_id=decoded_token["sub"],
            tool_id=str(tool["id"]),
            title="t",
            content="a\nb",
        )
        resp = _get(flask_app, str(note["id"]), decoded_token)
        assert resp.status_code == 200
        assert resp.json["artifact"]["artifact_type"] == "note"

    def test_unknown_id_404(self, _patch_db, flask_app, decoded_token):
        resp = _get(flask_app, str(uuid.uuid4()), decoded_token)
        assert resp.status_code == 404
