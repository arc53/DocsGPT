"""Current-principal endpoint.

``GET /api/user/me`` returns the caller's user id and resolved roles, sourced
only from ``request.decoded_token`` (already populated and role-resolved by the
auth chokepoint in ``app.py``). Auth-mode-agnostic. ``email``/``name``/
``picture`` are OIDC-only and optional — they are echoed from the token and are
never present for ``simple_jwt``/``session_jwt``/no-auth modes.

``GET /api/user/quota`` returns the caller's usage against the limits an admin
set for them, without naming the policies behind those limits.

``GET``/``PUT /api/user/preferences`` read and set the caller's settings that
follow them across devices: today the prompt their chats use
(``chat_prompt_id``), stored in ``users.tool_preferences``. ``GET`` also says
whether one was ever stored (``chat_prompt_set``), so a browser moves its
pre-upgrade choice only to an account that holds none; the move's ``PUT``
sends ``only_if_unset`` so a choice saved meanwhile elsewhere still wins.
"""

from __future__ import annotations

from typing import Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import Connection

from docsgpt.api import api
from docsgpt.api.pat.tokens import is_pat
from docsgpt.api.user.prompts.routes import PRESET_PROMPTS
from docsgpt.api.user.resource_access import AccessDenied, require, resolve
from docsgpt.api.user.utils import error_response
from docsgpt.core.settings import settings
from docsgpt.quotas.service import REQUEST_BUCKETS, QuotaService
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session

me_ns = Namespace("me", description="Current user identity and roles", path="/api")


@me_ns.route("/user/me")
class MeResource(Resource):
    def get(self):
        """Return ``{user_id, roles, email?, name?, picture?}`` for the caller."""
        decoded_token = getattr(request, "decoded_token", None)
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        body = {
            "success": True,
            "user_id": decoded_token.get("sub"),
            "roles": decoded_token.get("roles") or ["user"],
        }
        for field in ("email", "name", "picture"):
            value = decoded_token.get(field)
            if value:
                body[field] = value
        if is_pat(decoded_token):
            # Lets a CLI or pipeline confirm what its token is allowed to do.
            body["auth_method"] = "pat"
            body["token"] = {
                "id": decoded_token.get("pat_id"),
                "name": decoded_token.get("pat_name"),
                "scopes": decoded_token.get("scopes") or [],
                "resource_filter": decoded_token.get("resource_filter") or {},
            }
        return make_response(jsonify(body), 200)


def _own_budget(budget: dict) -> dict:
    return {"limit": budget["limit"], "used": budget["used"]}


@me_ns.route("/user/quota")
class MyQuotaResource(Resource):
    def get(self):
        """Return the caller's limited buckets: ``{bucket, tokens, cost, resets_at}`` each."""
        decoded_token = getattr(request, "decoded_token", None)
        user_id = decoded_token.get("sub") if decoded_token else None
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        statuses = QuotaService.status(user_id, ("all", *REQUEST_BUCKETS))
        buckets = []
        for status in statuses:
            if status.limits.unlimited:
                continue
            data = status.to_dict()
            buckets.append(
                {
                    "bucket": data["bucket"],
                    "tokens": _own_budget(data["tokens"]),
                    "cost": _own_budget(data["cost"]),
                    "resets_at": data["resets_at"],
                }
            )
        return make_response(
            jsonify({"success": True, "period": settings.QUOTA_PERIOD, "buckets": buckets}), 200
        )


#: The chat prompt of a user who never picked one, or whose pick is gone.
DEFAULT_CHAT_PROMPT = "default"


def _readable_chat_prompt(conn: Connection, user_id: str, stored: Optional[str]) -> str:
    """The stored chat prompt if the user may still read it, else ``default``.

    Args:
        conn: Open database connection.
        user_id: The caller.
        stored: The stored ``chat_prompt_id``, if any.

    Returns:
        str: A preset name or a prompt id the user can read today.
    """
    if not isinstance(stored, str) or not stored:
        return DEFAULT_CHAT_PROMPT
    if stored in PRESET_PROMPTS:
        return stored
    if not looks_like_uuid(stored):
        return DEFAULT_CHAT_PROMPT
    # A deleted prompt or a revoked share both read as no access.
    ra = resolve(conn, "prompt", stored, user_id)
    return ra.resource_id if ra is not None and ra.can("use") else DEFAULT_CHAT_PROMPT


@me_ns.route("/user/preferences")
class PreferencesResource(Resource):
    preferences_model = api.model(
        "UserPreferencesModel",
        {
            "chat_prompt_id": fields.String(
                required=True,
                description="The prompt chats use: default, creative, strict, or the id of a prompt the caller can read",
            ),
            "only_if_unset": fields.Boolean(
                required=False,
                description=(
                    "Store it only when no chat prompt was ever stored (moving a browser's old choice); "
                    "otherwise the stored one is kept and returned. Refused to a token restricted to "
                    "specific prompts"
                ),
            ),
        },
    )

    @api.doc(
        description=(
            "The caller's preferences: {success, chat_prompt_id, chat_prompt_set}. chat_prompt_id is "
            "default when none was set or the stored prompt was deleted or is no longer shared with the "
            "caller. chat_prompt_set is true once a chat prompt was ever stored, default included, even "
            "when it now reads as default."
        )
    )
    def get(self):
        """Return ``{success, chat_prompt_id, chat_prompt_set}`` for the caller."""
        decoded_token = getattr(request, "decoded_token", None)
        user_id = decoded_token.get("sub") if decoded_token else None
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_readonly() as conn:
                user_doc = UsersRepository(conn).get(user_id) or {}
                prefs = user_doc.get("tool_preferences") or {}
                stored = prefs.get("chat_prompt_id") if isinstance(prefs, dict) else None
                chat_prompt_id = _readable_chat_prompt(conn, user_id, stored)
        except Exception as err:
            current_app.logger.error(f"Error reading preferences: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        body = {
            "success": True,
            "chat_prompt_id": chat_prompt_id,
            # A stored default, or a prompt since deleted or unshared, is still a choice.
            "chat_prompt_set": isinstance(stored, str) and bool(stored),
        }
        return make_response(jsonify(body), 200)

    @api.expect(preferences_model)
    @api.doc(
        description=(
            "Set the prompt the caller's chats use: {success, chat_prompt_id, applied}. With only_if_unset "
            "and a chat prompt already stored, nothing is written, applied is false and chat_prompt_id is the "
            "stored one as GET reads it. 400 for a value that is neither a preset nor a prompt id, or a "
            "non-boolean only_if_unset; 403 for only_if_unset from a token restricted to specific prompts; "
            "404 when the caller can't read the prompt; 500 when the read or write fails."
        )
    )
    def put(self):
        """Store ``chat_prompt_id`` after checking the caller may use that prompt.

        Returns:
            Response: ``{success, chat_prompt_id, applied}``; ``applied`` is
            false only when ``only_if_unset`` found a stored chat prompt, whose
            readable value ``chat_prompt_id`` then carries.
        """
        decoded_token = getattr(request, "decoded_token", None)
        user_id = decoded_token.get("sub") if decoded_token else None
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        body = request.get_json(silent=True)
        value = body.get("chat_prompt_id") if isinstance(body, dict) else None
        if not isinstance(value, str) or not (value in PRESET_PROMPTS or looks_like_uuid(value)):
            return error_response(
                "chat_prompt_id must be default, creative, strict or a prompt id", 400, code="invalid_prompt"
            )
        only_if_unset = body.get("only_if_unset", False)
        if not isinstance(only_if_unset, bool):
            return error_response("only_if_unset must be a boolean", 400, code="invalid_request")
        try:
            with db_session() as conn:
                if value not in PRESET_PROMPTS:
                    value = require(conn, "prompt", value, user_id, "use").resource_id
                users = UsersRepository(conn)
                applied = users.set_chat_prompt_id(user_id, value, only_if_unset=only_if_unset)
                if not applied:
                    prefs = (users.get(user_id) or {}).get("tool_preferences") or {}
                    stored = prefs.get("chat_prompt_id") if isinstance(prefs, dict) else None
                    value = _readable_chat_prompt(conn, user_id, stored)
        except AccessDenied as err:
            return error_response(err.message, err.status)
        except Exception as err:
            current_app.logger.error(f"Error saving preferences: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify({"success": True, "chat_prompt_id": value, "applied": applied}), 200)
