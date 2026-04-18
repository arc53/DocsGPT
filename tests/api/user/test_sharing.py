"""Tests for application/api/user/sharing/routes.py.

Post-PG cutover: routes use the PG repositories (ConversationsRepository,
SharedConversationsRepository, AgentsRepository, AttachmentsRepository) and
the ``db_session`` / ``db_readonly`` context managers. These tests use the
ephemeral ``pg_conn`` fixture to exercise real SQL.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_sharing_db(conn):
    @contextmanager
    def _yield_conn():
        yield conn

    with patch(
        "application.api.user.sharing.routes.db_session", _yield_conn
    ), patch(
        "application.api.user.sharing.routes.db_readonly", _yield_conn
    ):
        yield


def _seed_conversation(pg_conn, user_id, name="Test Conv", message_count=0):
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )
    repo = ConversationsRepository(pg_conn)
    conv = repo.create(user_id, name=name)
    conv_id = str(conv["id"])
    for i in range(message_count):
        repo.append_message(conv_id, {"prompt": f"p{i}", "response": f"r{i}"})
    return conv_id


# ---------------------------------------------------------------------------
# ShareConversation — /share endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShareConversation:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.sharing.routes import ShareConversation

        with app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={"conversation_id": "x"},
        ):
            from flask import request

            request.decoded_token = None
            response = ShareConversation().post()

        assert response.status_code == 401

    def test_returns_400_missing_conversation_id(self, app):
        from application.api.user.sharing.routes import ShareConversation

        with app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = ShareConversation().post()

        assert response.status_code == 400

    def test_returns_400_missing_isPromptable(self, app):
        from application.api.user.sharing.routes import ShareConversation

        with app.test_request_context(
            "/api/share",
            method="POST",
            json={"conversation_id": "x"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = ShareConversation().post()

        assert response.status_code == 400

    def test_returns_404_for_missing_conversation(self, app, pg_conn):
        from application.api.user.sharing.routes import ShareConversation

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={"conversation_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = ShareConversation().post()

        assert response.status_code == 404

    def test_creates_non_promptable_share(self, app, pg_conn):
        from application.api.user.sharing.routes import ShareConversation

        user = "user-npshare"
        conv_id = _seed_conversation(pg_conn, user, message_count=3)

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={"conversation_id": conv_id},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = ShareConversation().post()

        assert response.status_code == 201
        assert response.json["success"] is True
        assert "identifier" in response.json

    def test_reuse_non_promptable_share_returns_same_identifier(
        self, app, pg_conn,
    ):
        from application.api.user.sharing.routes import ShareConversation

        user = "user-reuse-np"
        conv_id = _seed_conversation(pg_conn, user, message_count=1)

        ids = []
        for _ in range(2):
            with _patch_sharing_db(pg_conn), app.test_request_context(
                "/api/share?isPromptable=false",
                method="POST",
                json={"conversation_id": conv_id},
            ):
                from flask import request

                request.decoded_token = {"sub": user}
                r = ShareConversation().post()
            ids.append(r.json["identifier"])
        assert ids[0] == ids[1]

    def test_creates_promptable_share(self, app, pg_conn):
        from application.api.user.sharing.routes import ShareConversation

        user = "user-pshare"
        conv_id = _seed_conversation(pg_conn, user, message_count=2)

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=true",
            method="POST",
            json={"conversation_id": conv_id, "chunks": 4},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = ShareConversation().post()

        assert response.status_code == 201
        assert response.json["success"] is True

    def test_reuse_promptable_share_returns_200(self, app, pg_conn):
        from application.api.user.sharing.routes import ShareConversation

        user = "user-reuse-p"
        conv_id = _seed_conversation(pg_conn, user, message_count=1)

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=true",
            method="POST",
            json={"conversation_id": conv_id, "chunks": 2},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            first = ShareConversation().post()
        assert first.status_code == 201

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=true",
            method="POST",
            json={"conversation_id": conv_id, "chunks": 2},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            second = ShareConversation().post()
        # Second call reuses agent → status 200
        assert second.status_code == 200

    def test_promptable_with_invalid_chunks_coerces_none(self, app, pg_conn):
        from application.api.user.sharing.routes import ShareConversation

        user = "user-bad-chunks"
        conv_id = _seed_conversation(pg_conn, user, message_count=1)

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=true",
            method="POST",
            json={"conversation_id": conv_id, "chunks": "notanumber"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = ShareConversation().post()

        assert response.status_code == 201

    def test_db_error_returns_400(self, app):
        from application.api.user.sharing.routes import ShareConversation

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.sharing.routes.db_session", _broken
        ), app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={"conversation_id": "x"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            response = ShareConversation().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GetPubliclySharedConversations — /shared_conversation/<identifier>
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPubliclySharedConversations:
    def test_returns_404_for_missing_identifier(self, app, pg_conn):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/shared_conversation/abc-does-not-exist"
        ):
            response = GetPubliclySharedConversations().get(
                "00000000-0000-0000-0000-000000000000"
            )

        assert response.status_code == 404

    def test_returns_shared_conversation(self, app, pg_conn):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
            ShareConversation,
        )

        user = "user-get-shared"
        conv_id = _seed_conversation(pg_conn, user, name="Chat A", message_count=2)

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=false",
            method="POST",
            json={"conversation_id": conv_id},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            share_resp = ShareConversation().post()
        identifier = share_resp.json["identifier"]

        with _patch_sharing_db(pg_conn), app.test_request_context(
            f"/api/shared_conversation/{identifier}"
        ):
            response = GetPubliclySharedConversations().get(identifier)

        assert response.status_code == 200
        data = response.json
        assert data["success"] is True
        assert data["title"] == "Chat A"
        assert isinstance(data["queries"], list)
        assert len(data["queries"]) == 2
        # Non-promptable share should not expose api_key
        assert "api_key" not in data

    def test_returns_api_key_for_promptable_share(self, app, pg_conn):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
            ShareConversation,
        )

        user = "user-promptable"
        conv_id = _seed_conversation(pg_conn, user, message_count=1)

        with _patch_sharing_db(pg_conn), app.test_request_context(
            "/api/share?isPromptable=true",
            method="POST",
            json={"conversation_id": conv_id, "chunks": 2},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            share_resp = ShareConversation().post()
        identifier = share_resp.json["identifier"]

        with _patch_sharing_db(pg_conn), app.test_request_context(
            f"/api/shared_conversation/{identifier}"
        ):
            response = GetPubliclySharedConversations().get(identifier)

        assert response.status_code == 200
        assert "api_key" in response.json
        assert response.json["api_key"]

    def test_db_error_returns_400(self, app):
        from application.api.user.sharing.routes import (
            GetPubliclySharedConversations,
        )

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.sharing.routes.db_readonly", _broken
        ), app.test_request_context("/api/shared_conversation/abc"):
            response = GetPubliclySharedConversations().get("abc")

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvePromptPgId:
    def test_returns_none_for_default(self, pg_conn):
        from application.api.user.sharing.routes import _resolve_prompt_pg_id

        assert _resolve_prompt_pg_id(pg_conn, "default", "u") is None
        assert _resolve_prompt_pg_id(pg_conn, "", "u") is None
        assert _resolve_prompt_pg_id(pg_conn, None, "u") is None

    def test_resolves_uuid_by_ownership(self, pg_conn):
        from application.api.user.sharing.routes import _resolve_prompt_pg_id
        from application.storage.db.repositories.prompts import PromptsRepository

        prompt = PromptsRepository(pg_conn).create("owner", "p", "c")
        pid = str(prompt["id"])
        assert _resolve_prompt_pg_id(pg_conn, pid, "owner") == pid
        # Other user cannot claim
        assert _resolve_prompt_pg_id(pg_conn, pid, "someone-else") is None

    def test_returns_none_for_unknown_legacy(self, pg_conn):
        from application.api.user.sharing.routes import _resolve_prompt_pg_id

        assert _resolve_prompt_pg_id(pg_conn, "507f1f77bcf86cd799439011", "u") is None


@pytest.mark.unit
class TestResolveSourcePgId:
    def test_returns_none_for_falsy(self, pg_conn):
        from application.api.user.sharing.routes import _resolve_source_pg_id

        assert _resolve_source_pg_id(pg_conn, None) is None
        assert _resolve_source_pg_id(pg_conn, "") is None

    def test_returns_none_for_unknown_uuid(self, pg_conn):
        from application.api.user.sharing.routes import _resolve_source_pg_id

        assert (
            _resolve_source_pg_id(pg_conn, "00000000-0000-0000-0000-000000000000")
            is None
        )

    def test_returns_none_for_unknown_legacy(self, pg_conn):
        from application.api.user.sharing.routes import _resolve_source_pg_id

        assert _resolve_source_pg_id(pg_conn, "507f1f77bcf86cd799439011") is None
