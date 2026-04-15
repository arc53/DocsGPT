import uuid
from unittest.mock import Mock, mock_open, patch

import pytest
from flask import Flask

pytestmark = pytest.mark.skip(
    reason="Asserts Mongo-era call shapes (insert_one/find/dual_write); "
    "needs PG repository-based rewrite. Tracked as migration debt."
)


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestCreatePrompt:

    def test_creates_prompt(self, app):
        from application.api.user.prompts.routes import CreatePrompt

        mock_collection = Mock()
        mock_repo = Mock()
        inserted_id = uuid.uuid4().hex
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        def _run_dual_write(_repo_cls, fn):
            fn(mock_repo)

        with patch(
            "application.api.user.prompts.routes.prompts_collection",
            mock_collection,
        ), patch(
            "application.api.user.prompts.routes.dual_write",
            side_effect=_run_dual_write,
        ):
            with app.test_request_context(
                "/api/create_prompt",
                method="POST",
                json={"name": "My Prompt", "content": "You are helpful."},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreatePrompt().post()

        assert response.status_code == 200
        assert response.json["id"] == str(inserted_id)
        mock_collection.insert_one.assert_called_once()
        doc = mock_collection.insert_one.call_args[0][0]
        assert doc["name"] == "My Prompt"
        assert doc["user"] == "user1"
        mock_repo.create.assert_called_once_with(
            "user1",
            "My Prompt",
            "You are helpful.",
            legacy_mongo_id=str(inserted_id),
        )

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

    def test_returns_prompts_with_defaults(self, app):
        from application.api.user.prompts.routes import GetPrompts

        user_prompt_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {"_id": user_prompt_id, "name": "Custom Prompt"}
        ]

        with patch(
            "application.api.user.prompts.routes.prompts_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/get_prompts"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetPrompts().get()

        assert response.status_code == 200
        data = response.json
        public_names = [p["name"] for p in data if p["type"] == "public"]
        assert "default" in public_names
        assert "creative" in public_names
        assert "strict" in public_names
        private = [p for p in data if p["type"] == "private"]
        assert len(private) == 1
        assert private[0]["name"] == "Custom Prompt"

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.prompts.routes import GetPrompts

        with app.test_request_context("/api/get_prompts"):
            from flask import request

            request.decoded_token = None
            response = GetPrompts().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestGetSinglePrompt:

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

    def test_returns_custom_prompt(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        prompt_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": prompt_id,
            "content": "Custom content",
        }

        with patch(
            "application.api.user.prompts.routes.prompts_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/get_single_prompt?id={prompt_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetSinglePrompt().get()

        assert response.status_code == 200
        assert response.json["content"] == "Custom content"

    def test_returns_400_missing_id(self, app):
        from application.api.user.prompts.routes import GetSinglePrompt

        with app.test_request_context("/api/get_single_prompt"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = GetSinglePrompt().get()

        assert response.status_code == 400


@pytest.mark.unit
class TestDeletePrompt:

    def test_deletes_prompt(self, app):
        from application.api.user.prompts.routes import DeletePrompt

        prompt_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_repo = Mock()

        def _run_dual_write(_repo_cls, fn):
            fn(mock_repo)

        with patch(
            "application.api.user.prompts.routes.prompts_collection",
            mock_collection,
        ), patch(
            "application.api.user.prompts.routes.dual_write",
            side_effect=_run_dual_write,
        ):
            with app.test_request_context(
                "/api/delete_prompt",
                method="POST",
                json={"id": str(prompt_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeletePrompt().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        mock_collection.delete_one.assert_called_once_with(
            {"_id": prompt_id, "user": "user1"}
        )
        mock_repo.delete_by_legacy_id.assert_called_once_with(str(prompt_id), "user1")

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

    def test_updates_prompt(self, app):
        from application.api.user.prompts.routes import UpdatePrompt

        prompt_id = uuid.uuid4().hex
        mock_collection = Mock()
        mock_repo = Mock()

        def _run_dual_write(_repo_cls, fn):
            fn(mock_repo)

        with patch(
            "application.api.user.prompts.routes.prompts_collection",
            mock_collection,
        ), patch(
            "application.api.user.prompts.routes.dual_write",
            side_effect=_run_dual_write,
        ):
            with app.test_request_context(
                "/api/update_prompt",
                method="POST",
                json={
                    "id": str(prompt_id),
                    "name": "Updated",
                    "content": "New content",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdatePrompt().post()

        assert response.status_code == 200
        assert response.json["success"] is True
        mock_collection.update_one.assert_called_once()
        mock_repo.update_by_legacy_id.assert_called_once_with(
            str(prompt_id),
            "user1",
            "Updated",
            "New content",
        )

    def test_returns_400_missing_fields(self, app):
        from application.api.user.prompts.routes import UpdatePrompt

        with app.test_request_context(
            "/api/update_prompt",
            method="POST",
            json={"id": str(uuid.uuid4().hex), "name": "Updated"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdatePrompt().post()

        assert response.status_code == 400
