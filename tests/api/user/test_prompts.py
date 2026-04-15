import uuid
from contextlib import contextmanager
from unittest.mock import mock_open, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@contextmanager
def _patch_db(conn):
    """Patch both db_session and db_readonly to yield the given conn."""
    @contextmanager
    def _yield_conn():
        yield conn

    with patch(
        "application.api.user.prompts.routes.db_session", _yield_conn
    ), patch(
        "application.api.user.prompts.routes.db_readonly", _yield_conn
    ):
        yield


@pytest.mark.unit
class TestCreatePrompt:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.prompts.routes import CreatePrompt

        with app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "P", "content": "C"},
        ):
            from flask import request

            request.decoded_token = None
            response = CreatePrompt().post()

        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from application.api.user.prompts.routes import CreatePrompt

        with app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "P"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = CreatePrompt().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestGetPrompts:
    pass

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.prompts.routes import GetPrompts

        with app.test_request_context("/api/get_prompts"):
            from flask import request

            request.decoded_token = None
            response = GetPrompts().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetSinglePrompt:
    pass

    def test_returns_default_prompt(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        with patch("builtins.open", mock_open(read_data="Default prompt content")):
            with app.test_request_context("/api/get_single_prompt?id=default"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSinglePrompt().get()

        assert response.status_code == 200
        assert response.json["content"] == "Default prompt content"

    def test_returns_creative_prompt(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        with patch("builtins.open", mock_open(read_data="Creative content")):
            with app.test_request_context("/api/get_single_prompt?id=creative"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSinglePrompt().get()

        assert response.status_code == 200
        assert response.json["content"] == "Creative content"

    def test_returns_strict_prompt(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        with patch("builtins.open", mock_open(read_data="Strict content")):
            with app.test_request_context("/api/get_single_prompt?id=strict"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSinglePrompt().get()

        assert response.status_code == 200
        assert response.json["content"] == "Strict content"


    def test_returns_400_missing_id(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        with app.test_request_context("/api/get_single_prompt"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetSinglePrompt().get()

        assert response.status_code == 400


@pytest.mark.unit
class TestDeletePrompt:
    pass

    def test_returns_400_missing_id(self, app):
        from application.api.user.prompts.routes import DeletePrompt

        with app.test_request_context(
            "/api/delete_prompt",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = DeletePrompt().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestUpdatePrompt:
    pass

    def test_returns_400_missing_fields(self, app):
        from application.api.user.prompts.routes import UpdatePrompt

        with app.test_request_context(
            "/api/update_prompt",
            method="POST",
            json={"id": str(uuid.uuid4().hex[:24]), "name": "Updated"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdatePrompt().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Happy-path tests using the ephemeral pg_conn fixture
# ---------------------------------------------------------------------------


class TestCreatePromptHappyPath:
    def test_creates_prompt_returns_id(self, app, pg_conn):
        from application.api.user.prompts.routes import CreatePrompt

        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "P1", "content": "c1"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user-create"}
            response = CreatePrompt().post()

        assert response.status_code == 200
        assert "id" in response.json

    def test_create_error_returns_400(self, app, pg_conn):
        from application.api.user.prompts.routes import CreatePrompt

        # Force repository error by closing the connection first
        @contextmanager
        def _broken():
            raise RuntimeError("simulated db error")
            yield  # unreachable

        with patch(
            "application.api.user.prompts.routes.db_session", _broken
        ), app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "P", "content": "c"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = CreatePrompt().post()

        assert response.status_code == 400


class TestGetPromptsHappyPath:
    def test_returns_builtin_plus_user_prompts(self, app, pg_conn):
        from application.api.user.prompts.routes import CreatePrompt, GetPrompts

        user = "user-list"
        # Seed two prompts via the same endpoint
        for name in ("alpha", "beta"):
            with _patch_db(pg_conn), app.test_request_context(
                "/api/create_prompt",
                method="POST",
                json={"name": name, "content": f"content-{name}"},
            ):
                from flask import request

                request.decoded_token = {"sub": user}
                CreatePrompt().post()

        with _patch_db(pg_conn), app.test_request_context("/api/get_prompts"):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetPrompts().get()

        assert response.status_code == 200
        names = [p["name"] for p in response.json]
        # Three built-ins always present
        assert "default" in names and "creative" in names and "strict" in names
        assert "alpha" in names and "beta" in names

    def test_get_error_returns_400(self, app):
        from application.api.user.prompts.routes import GetPrompts

        @contextmanager
        def _broken():
            raise RuntimeError("simulated db error")
            yield

        with patch(
            "application.api.user.prompts.routes.db_readonly", _broken
        ), app.test_request_context("/api/get_prompts"):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = GetPrompts().get()

        assert response.status_code == 400


class TestGetSinglePromptHappyPath:
    def test_returns_private_prompt_content(self, app, pg_conn):
        from application.api.user.prompts.routes import (
            CreatePrompt,
            GetSinglePrompt,
        )

        user = "user-get1"
        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "custom", "content": "hello world"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            created = CreatePrompt().post()
        prompt_id = created.json["id"]

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/get_single_prompt?id={prompt_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetSinglePrompt().get()

        assert response.status_code == 200
        assert response.json["content"] == "hello world"

    def test_returns_404_for_unknown_prompt(self, app, pg_conn):
        from application.api.user.prompts.routes import GetSinglePrompt

        bogus_id = str(uuid.uuid4())
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/get_single_prompt?id={bogus_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": "whoever"}
            response = GetSinglePrompt().get()

        assert response.status_code == 404

    def test_file_read_exception_returns_400(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        with patch("builtins.open", side_effect=OSError("boom")), \
             app.test_request_context("/api/get_single_prompt?id=default"):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = GetSinglePrompt().get()

        assert response.status_code == 400


class TestDeletePromptHappyPath:
    def test_deletes_existing_prompt(self, app, pg_conn):
        from application.api.user.prompts.routes import (
            CreatePrompt,
            DeletePrompt,
            GetSinglePrompt,
        )

        user = "user-del"
        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "to-delete", "content": "bye"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            created = CreatePrompt().post()
        prompt_id = created.json["id"]

        with _patch_db(pg_conn), app.test_request_context(
            "/api/delete_prompt",
            method="POST",
            json={"id": prompt_id},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = DeletePrompt().post()

        assert response.status_code == 200
        assert response.json["success"] is True

        # Verify gone
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/get_single_prompt?id={prompt_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            check = GetSinglePrompt().get()
        assert check.status_code == 404

    def test_delete_returns_401_unauthenticated(self, app):
        from application.api.user.prompts.routes import DeletePrompt

        with app.test_request_context(
            "/api/delete_prompt",
            method="POST",
            json={"id": "something"},
        ):
            from flask import request

            request.decoded_token = None
            response = DeletePrompt().post()

        assert response.status_code == 401

    def test_delete_error_returns_400(self, app):
        from application.api.user.prompts.routes import DeletePrompt

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.prompts.routes.db_session", _broken
        ), app.test_request_context(
            "/api/delete_prompt",
            method="POST",
            json={"id": "pid"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = DeletePrompt().post()

        assert response.status_code == 400


class TestUpdatePromptHappyPath:
    def test_updates_prompt(self, app, pg_conn):
        from application.api.user.prompts.routes import (
            CreatePrompt,
            GetSinglePrompt,
            UpdatePrompt,
        )

        user = "user-upd"
        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_prompt",
            method="POST",
            json={"name": "orig", "content": "v1"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            created = CreatePrompt().post()
        prompt_id = created.json["id"]

        with _patch_db(pg_conn), app.test_request_context(
            "/api/update_prompt",
            method="POST",
            json={"id": prompt_id, "name": "renamed", "content": "v2"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = UpdatePrompt().post()
        assert response.status_code == 200

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/get_single_prompt?id={prompt_id}"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            check = GetSinglePrompt().get()
        assert check.status_code == 200
        assert check.json["content"] == "v2"

    def test_update_returns_401_unauthenticated(self, app):
        from application.api.user.prompts.routes import UpdatePrompt

        with app.test_request_context(
            "/api/update_prompt",
            method="POST",
            json={"id": "x", "name": "n", "content": "c"},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdatePrompt().post()

        assert response.status_code == 401

    def test_update_error_returns_400(self, app):
        from application.api.user.prompts.routes import UpdatePrompt

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.prompts.routes.db_session", _broken
        ), app.test_request_context(
            "/api/update_prompt",
            method="POST",
            json={"id": "x", "name": "n", "content": "c"},
        ):
            from flask import request

            request.decoded_token = {"sub": "u1"}
            response = UpdatePrompt().post()

        assert response.status_code == 400
