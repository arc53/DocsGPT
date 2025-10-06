"""Agent management webhook handlers."""

import secrets

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.api import api
from application.api.user.base import agents_collection, require_agent
from application.api.user.tasks import process_agent_webhook
from application.core.settings import settings


agents_webhooks_ns = Namespace(
    "agents", description="Agent management operations", path="/api"
)


@agents_webhooks_ns.route("/agent_webhook")
class AgentWebhook(Resource):
    @api.doc(
        params={"id": "ID of the agent"},
        description="Generate webhook URL for the agent",
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        agent_id = request.args.get("id")
        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "user": user}
            )
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            webhook_token = agent.get("incoming_webhook_token")
            if not webhook_token:
                webhook_token = secrets.token_urlsafe(32)
                agents_collection.update_one(
                    {"_id": ObjectId(agent_id), "user": user},
                    {"$set": {"incoming_webhook_token": webhook_token}},
                )
            base_url = settings.API_URL.rstrip("/")
            full_webhook_url = f"{base_url}/api/webhooks/agents/{webhook_token}"
        except Exception as err:
            current_app.logger.error(
                f"Error generating webhook URL: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Error generating webhook URL"}),
                400,
            )
        return make_response(
            jsonify({"success": True, "webhook_url": full_webhook_url}), 200
        )


@agents_webhooks_ns.route("/webhooks/agents/<string:webhook_token>")
class AgentWebhookListener(Resource):
    method_decorators = [require_agent]

    def _enqueue_webhook_task(self, agent_id_str, payload, source_method):
        if not payload:
            current_app.logger.warning(
                f"Webhook ({source_method}) received for agent {agent_id_str} with empty payload."
            )
        current_app.logger.info(
            f"Incoming {source_method} webhook for agent {agent_id_str}. Enqueuing task with payload: {payload}"
        )

        try:
            task = process_agent_webhook.delay(
                agent_id=agent_id_str,
                payload=payload,
            )
            current_app.logger.info(
                f"Task {task.id} enqueued for agent {agent_id_str} ({source_method})."
            )
            return make_response(jsonify({"success": True, "task_id": task.id}), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error enqueuing webhook task ({source_method}) for agent {agent_id_str}: {err}",
                exc_info=True,
            )
            return make_response(
                jsonify({"success": False, "message": "Error processing webhook"}), 500
            )

    @api.doc(
        description="Webhook listener for agent events (POST). Expects JSON payload, which is used to trigger processing.",
    )
    def post(self, webhook_token, agent, agent_id_str):
        payload = request.get_json()
        if payload is None:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Invalid or missing JSON data in request body",
                    }
                ),
                400,
            )
        return self._enqueue_webhook_task(agent_id_str, payload, source_method="POST")

    @api.doc(
        description="Webhook listener for agent events (GET). Uses URL query parameters as payload to trigger processing.",
    )
    def get(self, webhook_token, agent, agent_id_str):
        payload = request.args.to_dict(flat=True)
        return self._enqueue_webhook_task(agent_id_str, payload, source_method="GET")
