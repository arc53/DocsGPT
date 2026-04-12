from unittest.mock import Mock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestModelsListResource:

    def test_returns_models(self, app):
        from application.api.user.models.routes import ModelsListResource

        mock_model = Mock()
        mock_model.to_dict.return_value = {
            "id": "gpt-4",
            "name": "GPT-4",
            "provider": "openai",
        }

        mock_registry = Mock()
        mock_registry.get_enabled_models.return_value = [mock_model]
        mock_registry.default_model_id = "gpt-4"

        with patch(
            "application.api.user.models.routes.ModelRegistry.get_instance",
            return_value=mock_registry,
        ):
            with app.test_request_context("/api/models"):
                response = ModelsListResource().get()

        assert response.status_code == 200
        assert response.json["count"] == 1
        assert response.json["default_model_id"] == "gpt-4"
        assert response.json["models"][0]["id"] == "gpt-4"

    def test_returns_empty_models(self, app):
        from application.api.user.models.routes import ModelsListResource

        mock_registry = Mock()
        mock_registry.get_enabled_models.return_value = []
        mock_registry.default_model_id = None

        with patch(
            "application.api.user.models.routes.ModelRegistry.get_instance",
            return_value=mock_registry,
        ):
            with app.test_request_context("/api/models"):
                response = ModelsListResource().get()

        assert response.status_code == 200
        assert response.json["count"] == 0
        assert response.json["models"] == []

    def test_returns_500_on_error(self, app):
        from application.api.user.models.routes import ModelsListResource

        with patch(
            "application.api.user.models.routes.ModelRegistry.get_instance",
            side_effect=Exception("Registry error"),
        ):
            with app.test_request_context("/api/models"):
                response = ModelsListResource().get()

        assert response.status_code == 500
