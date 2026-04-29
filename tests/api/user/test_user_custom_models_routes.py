"""Tests for the BYOM REST API at /api/user/models."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    """Patch the routes' db helpers to yield the given pg connection."""

    @contextmanager
    def _yield_conn():
        yield conn

    with patch(
        "application.api.user.models.routes.db_session", _yield_conn
    ), patch(
        "application.api.user.models.routes.db_readonly", _yield_conn
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_registry():
    from application.core.model_registry import ModelRegistry

    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


# Auth


@pytest.mark.unit
class TestAuth:
    def test_list_unauthenticated_returns_401(self, app):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with app.test_request_context("/api/user/models"):
            from flask import request

            request.decoded_token = None
            resp = UserModelsCollectionResource().get()
        assert resp.status_code == 401

    def test_create_unauthenticated_returns_401(self, app):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with app.test_request_context(
            "/api/user/models",
            method="POST",
            json={
                "upstream_model_id": "x",
                "display_name": "x",
                "base_url": "https://api.openai.com/v1",
                "api_key": "k",
            },
        ):
            from flask import request

            request.decoded_token = None
            resp = UserModelsCollectionResource().post()
        assert resp.status_code == 401


# Create


@pytest.mark.unit
class TestCreate:
    def test_creates_and_returns_201_without_api_key(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        # Mock DNS so the SSRF check passes for api.mistral.ai without
        # hitting the network.
        with patch("application.security.safe_url.socket.getaddrinfo") as gai:
            gai.return_value = [
                (None, None, None, None, ("104.18.0.1", 0))
            ]
            with app.test_request_context(
                "/api/user/models",
                method="POST",
                json={
                    "upstream_model_id": "mistral-large-latest",
                    "display_name": "My Mistral",
                    "base_url": "https://api.mistral.ai/v1",
                    "api_key": "sk-mistral-test",
                    "capabilities": {
                        "supports_tools": True,
                        "context_window": 128000,
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user-1"}
                with _patch_db(pg_conn):
                    resp = UserModelsCollectionResource().post()

        assert resp.status_code == 201
        body = resp.get_json()
        assert body["upstream_model_id"] == "mistral-large-latest"
        assert body["source"] == "user"
        # Critical: api_key must NEVER appear in the response
        assert "api_key" not in body
        for v in body.values():
            assert v != "sk-mistral-test"

    def test_create_rejects_missing_required_fields(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with app.test_request_context(
            "/api/user/models",
            method="POST",
            json={"upstream_model_id": "x"},  # missing the others
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelsCollectionResource().post()
        assert resp.status_code == 400

    def test_create_rejects_loopback_url(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with app.test_request_context(
            "/api/user/models",
            method="POST",
            json={
                "upstream_model_id": "x",
                "display_name": "x",
                "base_url": "https://127.0.0.1/v1",
                "api_key": "k",
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelsCollectionResource().post()
        assert resp.status_code == 400
        body = resp.get_json()
        assert "error" in body

    def test_create_rejects_unknown_attachment_alias(self, app, pg_conn):
        """The UI sends ``["image"]`` as an alias; bad strings ("video",
        typos) must reject at the boundary so the DB never holds
        garbage that the registry would later silently drop.
        """
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with patch("application.security.safe_url.socket.getaddrinfo") as gai:
            gai.return_value = [
                (None, None, None, None, ("104.18.0.1", 0))
            ]
            with app.test_request_context(
                "/api/user/models",
                method="POST",
                json={
                    "upstream_model_id": "m",
                    "display_name": "M",
                    "base_url": "https://api.mistral.ai/v1",
                    "api_key": "k",
                    "capabilities": {"attachments": ["video"]},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user-1"}
                with _patch_db(pg_conn):
                    resp = UserModelsCollectionResource().post()
        assert resp.status_code == 400
        body = resp.get_json()
        assert "video" in body["error"]

    def test_create_accepts_image_alias_and_raw_mime(self, app, pg_conn):
        """The known ``image`` alias and raw MIME types both pass."""
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with patch("application.security.safe_url.socket.getaddrinfo") as gai:
            gai.return_value = [
                (None, None, None, None, ("104.18.0.1", 0))
            ]
            with app.test_request_context(
                "/api/user/models",
                method="POST",
                json={
                    "upstream_model_id": "m",
                    "display_name": "M",
                    "base_url": "https://api.mistral.ai/v1",
                    "api_key": "k",
                    "capabilities": {
                        "attachments": ["image", "application/pdf"],
                    },
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user-1"}
                with _patch_db(pg_conn):
                    resp = UserModelsCollectionResource().post()
        assert resp.status_code == 201

    def test_create_rejects_private_ip_dns(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with patch("application.security.safe_url.socket.getaddrinfo") as gai:
            # Hostname resolves to a private IP only — must reject
            gai.return_value = [
                (None, None, None, None, ("10.0.0.5", 0))
            ]
            with app.test_request_context(
                "/api/user/models",
                method="POST",
                json={
                    "upstream_model_id": "x",
                    "display_name": "x",
                    "base_url": "https://evil.example.com/v1",
                    "api_key": "k",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user-1"}
                with _patch_db(pg_conn):
                    resp = UserModelsCollectionResource().post()
        assert resp.status_code == 400


# List / get / patch / delete


def _create_via_repo(pg_conn, user_id="user-1", **kwargs):
    from application.storage.db.repositories.user_custom_models import (
        UserCustomModelsRepository,
    )

    return UserCustomModelsRepository(pg_conn).create(
        user_id=user_id,
        upstream_model_id=kwargs.pop("upstream_model_id", "mistral-large-latest"),
        display_name=kwargs.pop("display_name", "My Mistral"),
        base_url=kwargs.pop("base_url", "https://api.mistral.ai/v1"),
        api_key_plaintext=kwargs.pop("api_key_plaintext", "sk-mistral-test"),
        **kwargs,
    )


@pytest.mark.unit
class TestList:
    def test_lists_only_users_own(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        _create_via_repo(pg_conn, user_id="alice", upstream_model_id="alice-1")
        _create_via_repo(pg_conn, user_id="bob", upstream_model_id="bob-1")

        with app.test_request_context("/api/user/models"):
            from flask import request

            request.decoded_token = {"sub": "alice"}
            with _patch_db(pg_conn):
                resp = UserModelsCollectionResource().get()
        assert resp.status_code == 200
        body = resp.get_json()
        upstream_ids = {m["upstream_model_id"] for m in body["models"]}
        assert upstream_ids == {"alice-1"}
        # Never expose the api_key
        for m in body["models"]:
            assert "api_key" not in m


@pytest.mark.unit
class TestGet:
    def test_returns_404_for_other_users_model(self, app, pg_conn):
        from application.api.user.models.routes import UserModelResource

        created = _create_via_repo(pg_conn, user_id="alice")
        with app.test_request_context(
            f"/api/user/models/{created['id']}"
        ):
            from flask import request

            request.decoded_token = {"sub": "bob"}
            with _patch_db(pg_conn):
                resp = UserModelResource().get(model_id=created["id"])
        assert resp.status_code == 404


@pytest.mark.unit
class TestPatch:
    def test_patch_updates_display_name(self, app, pg_conn):
        from application.api.user.models.routes import UserModelResource

        created = _create_via_repo(pg_conn, user_id="user-1")
        with app.test_request_context(
            f"/api/user/models/{created['id']}",
            method="PATCH",
            json={"display_name": "Renamed"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelResource().patch(model_id=created["id"])
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["display_name"] == "Renamed"

    def test_patch_blank_api_key_keeps_existing(self, app, pg_conn):
        """Critical PATCH semantic: empty/missing api_key in body must
        preserve the stored ciphertext (the UI sends a blank password
        field when the user wants to keep the existing key)."""
        from application.api.user.models.routes import UserModelResource
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        created = _create_via_repo(pg_conn, user_id="user-1")
        original_key_plaintext = "sk-mistral-test"

        with app.test_request_context(
            f"/api/user/models/{created['id']}",
            method="PATCH",
            json={"display_name": "Just rename me", "api_key": ""},
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelResource().patch(model_id=created["id"])
        assert resp.status_code == 200

        # Decrypted key is unchanged
        repo = UserCustomModelsRepository(pg_conn)
        assert (
            repo.get_decrypted_api_key(created["id"], "user-1")
            == original_key_plaintext
        )


@pytest.mark.unit
class TestDelete:
    def test_delete_removes_row_and_invalidates_cache(self, app, pg_conn):
        from application.api.user.models.routes import UserModelResource
        from application.core.model_registry import ModelRegistry

        created = _create_via_repo(pg_conn, user_id="user-1")
        # Warm the registry's per-user cache via a lookup
        with patch(
            "application.storage.db.session.db_readonly"
        ) as ro:
            @contextmanager
            def _y():
                yield pg_conn

            ro.side_effect = _y
            ModelRegistry.get_instance().get_model(created["id"], user_id="user-1")
        # Now delete via the route — invalidation must happen so a
        # subsequent lookup misses
        with app.test_request_context(
            f"/api/user/models/{created['id']}", method="DELETE"
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelResource().delete(model_id=created["id"])
        assert resp.status_code == 200
        # Cache invalidated → next lookup re-queries DB and finds nothing
        assert "user-1" not in ModelRegistry.get_instance()._user_models


# /api/models combined view


@pytest.mark.unit
class TestSecurityCreateRejectsBlankFields:
    """P1 #1 partial: blank api_key on create must be rejected so we
    can never end up with an unroutable BYOM record that would cause
    LLMCreator to leak settings.API_KEY to the user-supplied URL."""

    def test_create_rejects_blank_api_key(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelsCollectionResource,
        )

        with patch("application.security.safe_url.socket.getaddrinfo") as gai:
            gai.return_value = [(None, None, None, None, ("104.18.0.1", 0))]
            with app.test_request_context(
                "/api/user/models",
                method="POST",
                json={
                    "upstream_model_id": "x",
                    "display_name": "x",
                    "base_url": "https://api.mistral.ai/v1",
                    "api_key": "   ",  # whitespace only
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "u"}
                with _patch_db(pg_conn):
                    resp = UserModelsCollectionResource().post()
        assert resp.status_code == 400
        body = resp.get_json()
        assert "api_key" in (body.get("error") or "").lower()

    def test_patch_rejects_blank_required_field(self, app, pg_conn):
        from application.api.user.models.routes import UserModelResource
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        created = UserCustomModelsRepository(pg_conn).create(
            user_id="u",
            upstream_model_id="x",
            display_name="x",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-x",
        )

        with app.test_request_context(
            f"/api/user/models/{created['id']}",
            method="PATCH",
            json={"base_url": "  "},
        ):
            from flask import request

            request.decoded_token = {"sub": "u"}
            with _patch_db(pg_conn):
                resp = UserModelResource().patch(model_id=created["id"])
        assert resp.status_code == 400


@pytest.mark.unit
class TestPayloadConnectionTest:
    """Verifies the payload-based test endpoint. Lets the UI's 'Test
    connection' button work *before* the model is saved — operators
    expect to validate their endpoint + key before committing."""

    def test_payload_test_rejects_unsafe_url(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelTestPayloadResource,
        )

        with app.test_request_context(
            "/api/user/models/test",
            method="POST",
            json={
                "base_url": "https://127.0.0.1/v1",
                "api_key": "sk-anything",
                "upstream_model_id": "x",
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelTestPayloadResource().post()
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["ok"] is False

    def test_payload_test_returns_ok_when_upstream_responds_2xx(
        self, app, pg_conn
    ):
        from application.api.user.models.routes import (
            UserModelTestPayloadResource,
        )

        # pinned_post is the IP-pinned dispatch helper. Patching it
        # bypasses both the SSRF guard and the network — the success
        # path we're verifying here is the route's response handling.
        with patch("application.api.user.models.routes.pinned_post") as rp:
            rp.return_value = MagicMock(
                status_code=200,
                headers={"Content-Type": "application/json"},
                text='{"ok": true}',
            )
            with app.test_request_context(
                "/api/user/models/test",
                method="POST",
                json={
                    "base_url": "https://api.mistral.ai/v1",
                    "api_key": "sk-mistral-test",
                    "upstream_model_id": "mistral-large-latest",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user-1"}
                with _patch_db(pg_conn):
                    resp = UserModelTestPayloadResource().post()
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        # Verify the upstream call carried the user's submitted key (not
        # whatever's in the DB) and the right model name.
        call_args = rp.call_args
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer sk-mistral-test"
        assert call_args.kwargs["json"]["model"] == "mistral-large-latest"

    def test_payload_test_unauthenticated_returns_401(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelTestPayloadResource,
        )

        with app.test_request_context(
            "/api/user/models/test",
            method="POST",
            json={
                "base_url": "https://api.mistral.ai/v1",
                "api_key": "k",
                "upstream_model_id": "x",
            },
        ):
            from flask import request

            request.decoded_token = None
            with _patch_db(pg_conn):
                resp = UserModelTestPayloadResource().post()
        assert resp.status_code == 401

    def test_payload_test_missing_fields_returns_400(self, app, pg_conn):
        from application.api.user.models.routes import (
            UserModelTestPayloadResource,
        )

        with app.test_request_context(
            "/api/user/models/test",
            method="POST",
            json={"base_url": "https://api.mistral.ai/v1"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user-1"}
            with _patch_db(pg_conn):
                resp = UserModelTestPayloadResource().post()
        assert resp.status_code == 400


@pytest.mark.unit
class TestByIdConnectionTestAcceptsOverrides:
    """P3: in edit mode the modal sends current form state as overrides
    so the test reflects in-flight edits (not the saved record)."""

    def _make_row(self, pg_conn):
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        return UserCustomModelsRepository(pg_conn).create(
            user_id="u",
            upstream_model_id="stored-model",
            display_name="Stored",
            base_url="https://stored.example.com/v1",
            api_key_plaintext="sk-stored",
        )

    def _post_test(self, app, pg_conn, model_id, body):
        from application.api.user.models.routes import UserModelTestResource

        with patch("application.api.user.models.routes.pinned_post") as rp:
            rp.return_value = MagicMock(
                status_code=200,
                headers={"Content-Type": "application/json"},
                text='{"ok": true}',
            )
            with app.test_request_context(
                f"/api/user/models/{model_id}/test", method="POST", json=body
            ):
                from flask import request

                request.decoded_token = {"sub": "u"}
                with _patch_db(pg_conn):
                    UserModelTestResource().post(model_id=model_id)
            return rp.call_args

    def test_overrides_win_when_supplied(self, app, pg_conn):
        row = self._make_row(pg_conn)
        ca = self._post_test(
            app,
            pg_conn,
            row["id"],
            {
                "base_url": "https://new.example.com/v1",
                "api_key": "sk-new",
                "upstream_model_id": "new-model",
            },
        )
        assert ca.args[0] == "https://new.example.com/v1/chat/completions"
        assert ca.kwargs["headers"]["Authorization"] == "Bearer sk-new"
        assert ca.kwargs["json"]["model"] == "new-model"

    def test_blank_overrides_fall_back_to_stored(self, app, pg_conn):
        """The classic edit-mode flow: user changed base_url, left
        api_key blank — server uses the new URL but the stored key."""
        row = self._make_row(pg_conn)
        ca = self._post_test(
            app,
            pg_conn,
            row["id"],
            {
                "base_url": "https://new.example.com/v1",
                "api_key": "",
                "upstream_model_id": "",
            },
        )
        assert ca.args[0] == "https://new.example.com/v1/chat/completions"
        # Stored key (decrypted) was used.
        assert ca.kwargs["headers"]["Authorization"] == "Bearer sk-stored"
        # Stored upstream_model_id was used.
        assert ca.kwargs["json"]["model"] == "stored-model"

    def test_empty_body_uses_all_stored_values(self, app, pg_conn):
        row = self._make_row(pg_conn)
        ca = self._post_test(app, pg_conn, row["id"], {})
        assert ca.args[0] == "https://stored.example.com/v1/chat/completions"
        assert ca.kwargs["headers"]["Authorization"] == "Bearer sk-stored"
        assert ca.kwargs["json"]["model"] == "stored-model"


@pytest.mark.unit
class TestApiModelsListWithUser:
    def test_includes_user_models_when_authenticated(self, app, pg_conn):
        """GET /api/models with auth should surface the user's BYOM
        records alongside built-ins, each tagged with `source`."""
        from application.api.user.models.routes import ModelsListResource
        from application.core.model_registry import ModelRegistry

        created = _create_via_repo(
            pg_conn, user_id="user-1", display_name="My Mistral"
        )

        # Patch the *registry's* db_readonly so the per-user layer load
        # uses the test connection.
        @contextmanager
        def _yield():
            yield pg_conn

        with patch(
            "application.storage.db.session.db_readonly", _yield
        ):
            ModelRegistry.reset()
            with app.test_request_context("/api/models"):
                from flask import request

                request.decoded_token = {"sub": "user-1"}
                resp = ModelsListResource().get()

        assert resp.status_code == 200
        body = resp.get_json()
        ids = [m["id"] for m in body["models"]]
        assert created["id"] in ids
        # Source label tags it for the UI
        user_entries = [m for m in body["models"] if m["id"] == created["id"]]
        assert user_entries[0]["source"] == "user"
        # Built-ins still present
        assert any(m.get("source") == "builtin" for m in body["models"])
