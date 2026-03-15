from flask import current_app, jsonify, make_response
from flask_restx import Namespace, Resource

from application.core.model_settings import ModelRegistry

models_ns = Namespace("models", description="Available models", path="/api")


@models_ns.route("/models")
class ModelsListResource(Resource):
    def get(self):
        """Get list of available models with their capabilities."""
        try:
            registry = ModelRegistry.get_instance()
            models = registry.get_enabled_models()

            response = {
                "models": [model.to_dict() for model in models],
                "default_model_id": registry.default_model_id,
                "count": len(models),
            }
        except Exception as err:
            current_app.logger.error(f"Error fetching models: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(response), 200)
