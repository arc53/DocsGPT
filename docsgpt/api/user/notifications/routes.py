"""Notifications REST API: presence reports, Web Push subscriptions, and clearing a conversation's unread mark.

All of it is the web app talking about its own browser tab, so every route
is the signed-in user's own and personal access tokens can't call them.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from docsgpt.api import api
from docsgpt.notifications import presence
from docsgpt.notifications.push import (
    MAX_SUBSCRIPTIONS_PER_USER,
    InvalidSubscription,
    parse_subscription,
    vapid_config,
)
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository
from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository
from docsgpt.storage.db.session import db_session

logger = logging.getLogger(__name__)

notifications_ns = Namespace(
    "notifications", description="Presence, Web Push subscriptions and unread conversations", path="/api"
)

_TAB_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

#: Characters of the User-Agent kept with a subscription.
_USER_AGENT_MAX_CHARS = 300

presence_model = api.model(
    "PresenceReport",
    {
        "tab_id": fields.String(required=True, description="The tab's own random id (1-64 of A-Z a-z 0-9 _ . : -)"),
        "conversation_id": fields.String(description="The conversation the tab shows, or null"),
        "visible": fields.Boolean(required=True, description="Whether the tab is visible"),
        "closing": fields.Boolean(description="The tab is closing; forget it"),
    },
)

subscription_model = api.model(
    "PushSubscription",
    {
        "endpoint": fields.String(required=True, description="The push service URL (https, a known push service)"),
        "keys": fields.Raw(required=True, description="{p256dh, auth}, base64url, as the browser gives them"),
        "expirationTime": fields.Raw(description="Ignored"),
    },
)


def _user_id() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if isinstance(decoded, dict) else None


def _err(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


def _json() -> Any:
    return request.get_json(silent=True)


@notifications_ns.route("/presence")
class Presence(Resource):
    @api.expect(presence_model)
    @api.doc(
        description=(
            "Report what one tab shows: sent when its visibility or route changes and every ~20 s while visible. "
            "A report counts for 45 s; `closing: true` forgets the tab at once. A user is not notified about a "
            "conversation a visible tab of theirs shows."
        )
    )
    def post(self):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        data = _json()
        if not isinstance(data, dict):
            return _err("A JSON body is required", 400)
        tab_id = data.get("tab_id")
        if not isinstance(tab_id, str) or not _TAB_ID.match(tab_id):
            return _err("tab_id is required", 400)
        conversation_id = data.get("conversation_id")
        if conversation_id is not None and not looks_like_uuid(conversation_id):
            return _err("conversation_id must be a conversation id or null", 400)
        visible = data.get("visible", False)
        closing = data.get("closing", False)
        if not isinstance(visible, bool) or not isinstance(closing, bool):
            return _err("visible and closing must be booleans", 400)
        stored = presence.report(user_id, tab_id, conversation_id, visible, closing=closing)
        return make_response(jsonify({"success": True, "stored": stored}), 200)


@notifications_ns.route("/push/public_key")
class PushPublicKey(Resource):
    @api.doc(
        description=(
            "Whether Web Push is configured, and the VAPID public key browsers subscribe with "
            "(`applicationServerKey`, raw base64url)."
        )
    )
    def get(self):
        if not _user_id():
            return _err("Unauthorized", 401)
        config = vapid_config()
        return make_response(
            jsonify({"enabled": config is not None, "public_key": config.public_key if config else None}), 200
        )


@notifications_ns.route("/push/subscriptions")
class PushSubscriptions(Resource):
    @api.expect(subscription_model)
    @api.doc(
        description=(
            "Save this browser's Web Push subscription (the browser's `PushSubscription` JSON) for the caller. "
            "The endpoint must be https on a known push service. Saving a known endpoint moves it to the caller. "
            "503 when Web Push is not configured."
        )
    )
    def post(self):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if vapid_config() is None:
            return _err("Web Push is not configured on this server", 503)
        try:
            parsed = parse_subscription(_json())
        except InvalidSubscription as exc:
            return _err(str(exc), 400)
        user_agent = (request.headers.get("User-Agent") or "")[:_USER_AGENT_MAX_CHARS] or None
        try:
            with db_session() as conn:
                repo = PushSubscriptionsRepository(conn)
                repo.upsert(user_id=user_id, user_agent=user_agent, **parsed)
                repo.trim_for_user(user_id, MAX_SUBSCRIPTIONS_PER_USER)
        except Exception:
            logger.exception("saving a push subscription failed")
            return _err("Failed to save the subscription", 500)
        return make_response(jsonify({"success": True}), 201)

    @api.expect(api.model("PushUnsubscribe", {"endpoint": fields.String(required=True)}))
    @api.doc(
        description="Forget this browser's Web Push subscription: `{endpoint}` in the body, or `?endpoint=`.",
        params={"endpoint": "The subscription's endpoint, when not in the body"},
    )
    def delete(self):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        data = _json()
        endpoint = data.get("endpoint") if isinstance(data, dict) else None
        endpoint = endpoint or request.args.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            return _err("endpoint is required", 400)
        try:
            with db_session() as conn:
                deleted = PushSubscriptionsRepository(conn).delete_for_user(user_id, endpoint)
        except Exception:
            logger.exception("deleting a push subscription failed")
            return _err("Failed to delete the subscription", 500)
        return make_response(jsonify({"success": True, "deleted": deleted}), 200)


@notifications_ns.route("/conversations/<string:conversation_id>/read")
class ConversationRead(Resource):
    @api.doc(description="Clear the conversation's unread mark (the user opened it). Idempotent.")
    def post(self, conversation_id: str):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if not looks_like_uuid(conversation_id):
            return _err("Invalid conversation id", 400)
        try:
            with db_session() as conn:
                cleared = ConversationUnreadRepository(conn).mark_read(conversation_id, user_id)
        except Exception:
            logger.exception("clearing an unread mark failed")
            return _err("Failed to mark the conversation read", 500)
        return make_response(jsonify({"success": True, "cleared": cleared}), 200)
