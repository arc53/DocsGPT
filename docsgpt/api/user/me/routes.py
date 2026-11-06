"""Current-principal endpoint.

``GET /api/user/me`` returns the caller's user id and resolved roles, sourced
only from ``request.decoded_token`` (already populated and role-resolved by the
auth chokepoint in ``app.py``). Auth-mode-agnostic. ``email``/``name``/
``picture`` are OIDC-only and optional — they are echoed from the token and are
never present for ``simple_jwt``/``session_jwt``/no-auth modes.

``GET /api/user/quota`` returns the caller's usage against the limits an admin
set for them, without naming the policies behind those limits.

``GET``/``PUT /api/user/preferences`` read and set the caller's settings that
follow them across devices, stored in ``users.tool_preferences``: the prompt
their chats use (``chat_prompt_id``) and the model their DocsGPT jobs run on
(``task_model_id``: the drafter, graph extraction, the monitor judge). ``GET``
also says whether a chat prompt was ever stored (``chat_prompt_set``), so a
browser moves its pre-upgrade choice only to an account that holds none; the
move's ``PUT`` sends ``only_if_unset`` so a choice saved meanwhile elsewhere
still wins.
"""

from __future__ import annotations

from typing import Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import Connection

from docsgpt.api import api
from docsgpt.api.pat.rules import allowed_ids, missing_scope_response
from docsgpt.api.pat.tokens import is_pat
from docsgpt.api.user.prompts.routes import PRESET_PROMPTS
from docsgpt.api.user.resource_access import AccessDenied, require, resolve
from docsgpt.api.user.utils import error_response
from docsgpt.core.model_utils import model_is_usable, resolve_task_model_id
from docsgpt.core.settings import settings
from docsgpt.quotas.service import REQUEST_BUCKETS, QuotaService
from docsgpt.storage.db import model_defaults
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


#: Longest model id ``task_model_id`` accepts; registry ids are far shorter.
MAX_MODEL_ID_LENGTH = 256


def _task_models(conn: Connection, user_id: str) -> dict:
    """The caller's task model as GET reports it.

    Args:
        conn: Open database connection.
        user_id: The caller.

    Returns:
        dict: ``task_model_id``, the caller's choice while they can still run
        it (else ``None``), and ``instance_task_model_id``, what runs without
        one (the admin's, ``TASK_MODEL_ID`` or the default model).
    """
    user_choice, instance_choice = model_defaults.stored_task_models(conn, user_id)
    return {
        "task_model_id": user_choice if model_is_usable(user_choice, user_id) else None,
        "instance_task_model_id": resolve_task_model_id(None, None, instance_choice),
    }


def _task_model_value(value) -> tuple[bool, Optional[str]]:
    """``(valid, model_id)`` for a sent ``task_model_id``: null or a blank string clears it to ``None``."""
    if value is None:
        return True, None
    if not isinstance(value, str) or len(value) > MAX_MODEL_ID_LENGTH:
        return False, None
    return True, value.strip() or None


@me_ns.route("/user/preferences")
class PreferencesResource(Resource):
    preferences_model = api.model(
        "UserPreferencesModel",
        {
            "chat_prompt_id": fields.String(
                required=False,
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
            "task_model_id": fields.String(
                required=False,
                description=(
                    "The model the caller's DocsGPT jobs run on (drafting, graph extraction, monitor judging): "
                    "a model the caller can use, their own custom models included; null uses the instance's. "
                    "A token needs models:write to send it"
                ),
            ),
        },
    )

    @api.doc(
        description=(
            "The caller's preferences: {success, chat_prompt_id, chat_prompt_set, task_model_id, "
            "instance_task_model_id}. chat_prompt_id is default when none was set or the stored prompt was "
            "deleted or is no longer shared with the caller. chat_prompt_set is true once a chat prompt was "
            "ever stored, default included, even when it now reads as default. task_model_id is the model the "
            "caller's DocsGPT jobs run on, null when they picked none or can no longer use it; "
            "instance_task_model_id is the one that runs then, null when no model can. A token gets the chat "
            "prompt fields with prompts:read (never when restricted to specific prompts) and the task model "
            "fields with models:read."
        )
    )
    def get(self):
        """Return ``{success, chat_prompt_id, chat_prompt_set, task_model_id, instance_task_model_id}``.

        A token reads only the parts its scopes cover: the chat prompt with
        ``prompts:read`` and no prompt allowlist (the stored id can't be
        proven inside one), the task model with ``models:read``.

        Returns:
            Response: The preferences the caller may read.
        """
        decoded_token = getattr(request, "decoded_token", None)
        user_id = decoded_token.get("sub") if decoded_token else None
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        reads_prompt = (
            missing_scope_response(request, "prompts:read") is None and allowed_ids(request, "prompts") is None
        )
        reads_task_model = missing_scope_response(request, "models:read") is None
        body: dict = {"success": True}
        try:
            with db_readonly() as conn:
                if reads_prompt:
                    user_doc = UsersRepository(conn).get(user_id) or {}
                    prefs = user_doc.get("tool_preferences") or {}
                    stored = prefs.get("chat_prompt_id") if isinstance(prefs, dict) else None
                    body["chat_prompt_id"] = _readable_chat_prompt(conn, user_id, stored)
                    # A stored default, or a prompt since deleted or unshared, is still a choice.
                    body["chat_prompt_set"] = isinstance(stored, str) and bool(stored)
                if reads_task_model:
                    body.update(_task_models(conn, user_id))
        except Exception as err:
            current_app.logger.error(f"Error reading preferences: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(body), 200)

    @api.expect(preferences_model)
    @api.doc(
        description=(
            "Set the prompt the caller's chats use, the model their DocsGPT jobs run on, or both; send at "
            "least one. Answers {success} with chat_prompt_id and applied when a chat prompt was sent, and "
            "task_model_id when one was. With only_if_unset and a chat prompt already stored, the chat prompt "
            "is not written, applied is false and chat_prompt_id is the stored one as GET reads it. 400 for a "
            "chat_prompt_id that is neither a preset nor a prompt id, a non-boolean only_if_unset, or a "
            "task_model_id the caller can't use (code invalid_model), in which case nothing is written; 403 "
            "for only_if_unset from a token restricted to specific prompts, or a token without prompts:write "
            "(chat_prompt_id) or models:write (task_model_id); 404 when the caller can't read the prompt; 500 "
            "when the read or write fails."
        )
    )
    def put(self):
        """Store ``chat_prompt_id`` and/or ``task_model_id`` after checking the caller may use them.

        Returns:
            Response: ``{success}`` plus, for a sent chat prompt,
            ``chat_prompt_id`` and ``applied`` (false only when
            ``only_if_unset`` found a stored chat prompt, whose readable value
            ``chat_prompt_id`` then carries), and for a sent task model,
            ``task_model_id`` as stored (``None``: the instance's applies).
        """
        decoded_token = getattr(request, "decoded_token", None)
        user_id = decoded_token.get("sub") if decoded_token else None
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        sets_prompt = "chat_prompt_id" in body or "only_if_unset" in body or "task_model_id" not in body
        sets_task_model = "task_model_id" in body
        for wanted, scope in ((sets_prompt, "prompts:write"), (sets_task_model, "models:write")):
            refused = missing_scope_response(request, scope) if wanted else None
            if refused:
                return make_response(jsonify(refused[0]), refused[1])
        value = body.get("chat_prompt_id")
        if sets_prompt and not (isinstance(value, str) and (value in PRESET_PROMPTS or looks_like_uuid(value))):
            return error_response(
                "chat_prompt_id must be default, creative, strict or a prompt id", 400, code="invalid_prompt"
            )
        only_if_unset = body.get("only_if_unset", False)
        if not isinstance(only_if_unset, bool):
            return error_response("only_if_unset must be a boolean", 400, code="invalid_request")
        valid, task_model_id = _task_model_value(body.get("task_model_id"))
        if sets_task_model and not (valid and (task_model_id is None or model_is_usable(task_model_id, user_id))):
            return error_response("task_model_id must be a model you can use, or null", 400, code="invalid_model")
        response: dict = {"success": True}
        try:
            with db_session() as conn:
                users = UsersRepository(conn)
                if sets_prompt:
                    if value not in PRESET_PROMPTS:
                        value = require(conn, "prompt", value, user_id, "use").resource_id
                    applied = users.set_chat_prompt_id(user_id, value, only_if_unset=only_if_unset)
                    if not applied:
                        prefs = (users.get(user_id) or {}).get("tool_preferences") or {}
                        stored = prefs.get("chat_prompt_id") if isinstance(prefs, dict) else None
                        value = _readable_chat_prompt(conn, user_id, stored)
                    response.update(chat_prompt_id=value, applied=applied)
                if sets_task_model:
                    users.set_task_model_id(user_id, task_model_id)
                    response["task_model_id"] = task_model_id
        except AccessDenied as err:
            return error_response(err.message, err.status)
        except Exception as err:
            current_app.logger.error(f"Error saving preferences: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(response), 200)
