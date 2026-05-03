"""Agent management webhook handlers."""

import secrets
import uuid

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource
from sqlalchemy import text as sql_text

from application.api import api
from application.api.user.base import require_agent
from application.api.user.tasks import process_agent_webhook
from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.idempotency import IdempotencyRepository
from application.storage.db.session import db_readonly, db_session


agents_webhooks_ns = Namespace(
    "agents", description="Agent management operations", path="/api"
)


_IDEMPOTENCY_KEY_MAX_LEN = 256


def _read_idempotency_key():
    """Return (key, error_response). Empty header → (None, None); oversized → (None, 400)."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None
    if len(key) > _IDEMPOTENCY_KEY_MAX_LEN:
        return None, make_response(
            jsonify(
                {
                    "success": False,
                    "message": (
                        f"Idempotency-Key exceeds maximum length of "
                        f"{_IDEMPOTENCY_KEY_MAX_LEN} characters"
                    ),
                }
            ),
            400,
        )
    return key, None


def _scoped_idempotency_key(idempotency_key, scope):
    """Compose ``"{scope}:{idempotency_key}"`` so two agents (or two
    callers via different agent webhooks) sharing the same raw header
    value can't collapse onto a single ``webhook_dedup`` row. Returns
    ``None`` if either side is missing — caller treats that as "no
    dedup" rather than risking a global collision.
    """
    if not idempotency_key or not scope:
        return None
    return f"{scope}:{idempotency_key}"


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
            with db_readonly() as conn:
                agent = AgentsRepository(conn).get_any(agent_id, user)
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            webhook_token = agent.get("incoming_webhook_token")
            if not webhook_token:
                webhook_token = secrets.token_urlsafe(32)
                with db_session() as conn:
                    AgentsRepository(conn).update(
                        str(agent["id"]), user,
                        {"incoming_webhook_token": webhook_token},
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

    def _enqueue_webhook_task(self, agent_id_str, payload, source_method, agent=None):
        if not payload:
            current_app.logger.warning(
                f"Webhook ({source_method}) received for agent {agent_id_str} with empty payload."
            )
        current_app.logger.info(
            f"Incoming {source_method} webhook for agent {agent_id_str}. Enqueuing task with payload: {payload}"
        )

        idempotency_key, key_error = _read_idempotency_key()
        if key_error is not None:
            return key_error
        # Resolve to a real PG UUID up-front so the dedup write doesn't crash
        # when the path token corresponds to a legacy non-UUID agent id.
        agent_uuid = None
        if agent is not None:
            candidate = str(agent.get("id") or "")
            if looks_like_uuid(candidate):
                agent_uuid = candidate
        if idempotency_key and agent_uuid is None:
            current_app.logger.warning(
                "Skipping webhook idempotency dedup: agent %s has non-UUID id",
                agent_id_str,
            )
            idempotency_key = None
        # Scope dedup by ``agent_id`` so two agents (or callers behind
        # different webhook tokens) sharing the same raw header value
        # can't collapse onto a single ``webhook_dedup`` row. Webhooks
        # don't carry a user_id, so the agent UUID is the natural scope.
        scoped_key = _scoped_idempotency_key(idempotency_key, agent_uuid)
        # Claim before enqueue so concurrent same-key POSTs cannot both
        # call .delay(). Loser path returns the winner's task_id.
        predetermined_task_id = None
        if scoped_key:
            predetermined_task_id = str(uuid.uuid4())
            with db_session() as conn:
                claimed = IdempotencyRepository(conn).record_webhook(
                    key=scoped_key,
                    agent_id=agent_uuid,
                    task_id=predetermined_task_id,
                    response_json={
                        "success": True, "task_id": predetermined_task_id,
                    },
                )
            if claimed is None:
                with db_readonly() as conn:
                    cached = IdempotencyRepository(conn).get_webhook(scoped_key)
                if cached is not None:
                    return make_response(jsonify(cached["response_json"]), 200)
                return make_response(
                    jsonify({"success": True, "task_id": "deduplicated"}), 200
                )

        try:
            apply_kwargs = dict(
                kwargs={
                    "agent_id": agent_id_str,
                    "payload": payload,
                    # Pass the *scoped* key downstream so the worker
                    # decorator's ``task_dedup`` row is also user-distinct.
                    "idempotency_key": scoped_key or idempotency_key,
                },
            )
            if predetermined_task_id is not None:
                apply_kwargs["task_id"] = predetermined_task_id
            task = process_agent_webhook.apply_async(**apply_kwargs)
            current_app.logger.info(
                f"Task {task.id} enqueued for agent {agent_id_str} ({source_method})."
            )
            response_payload = {"success": True, "task_id": task.id}
            return make_response(jsonify(response_payload), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error enqueuing webhook task ({source_method}) for agent {agent_id_str}: {err}",
                exc_info=True,
            )
            if scoped_key:
                # Roll back the claim so a retry can succeed.
                try:
                    with db_session() as conn:
                        conn.execute(
                            sql_text(
                                "DELETE FROM webhook_dedup "
                                "WHERE idempotency_key = :k"
                            ),
                            {"k": scoped_key},
                        )
                except Exception:
                    current_app.logger.exception(
                        "Failed to release webhook_dedup claim for key=%s",
                        scoped_key,
                    )
            return make_response(
                jsonify({"success": False, "message": "Error processing webhook"}), 500
            )

    @api.doc(
        description=(
            "Webhook listener for agent events (POST). Expects JSON payload, which "
            "is used to trigger processing. Honors an optional ``Idempotency-Key`` "
            "header: a repeat request with the same key within 24h returns the "
            "original cached response and does not re-enqueue the task."
        ),
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
        return self._enqueue_webhook_task(
            agent_id_str, payload, source_method="POST", agent=agent,
        )

    @api.doc(
        description=(
            "Webhook listener for agent events (GET). Uses URL query parameters as "
            "payload to trigger processing. Honors an optional ``Idempotency-Key`` "
            "header: a repeat request with the same key within 24h returns the "
            "original cached response and does not re-enqueue the task."
        ),
    )
    def get(self, webhook_token, agent, agent_id_str):
        payload = request.args.to_dict(flat=True)
        return self._enqueue_webhook_task(
            agent_id_str, payload, source_method="GET", agent=agent,
        )
