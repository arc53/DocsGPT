"""Model routes.

- ``GET /api/models`` — list available models for the current user.
  Combines the built-in catalog with the user's BYOM records.
- ``GET/POST/PATCH/DELETE /api/user/models[/<id>]`` — CRUD for the
  user's own OpenAI-compatible model registrations (BYOM).
- ``POST /api/user/models/<id>/test`` — sanity-check the upstream
  endpoint with a tiny request.

Every BYOM endpoint is user-scoped at the repository layer
(every query filters on ``user_id`` from ``request.decoded_token``).
"""

from __future__ import annotations

import logging

import requests
from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.api import api
from application.core.model_registry import ModelRegistry
from application.security.safe_url import (
    UnsafeUserUrlError,
    pinned_post,
    validate_user_base_url,
)
from application.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)
from application.storage.db.session import db_readonly, db_session
from application.utils import check_required_fields


logger = logging.getLogger(__name__)


models_ns = Namespace("models", description="Available models", path="/api")


_CONTEXT_WINDOW_MIN = 1_000
_CONTEXT_WINDOW_MAX = 10_000_000


def _user_id_or_401():
    decoded_token = request.decoded_token
    if not decoded_token:
        return None, make_response(jsonify({"success": False}), 401)
    user_id = decoded_token.get("sub")
    if not user_id:
        return None, make_response(jsonify({"success": False}), 401)
    return user_id, None


def _normalize_capabilities(raw) -> dict:
    """Coerce + bound the user-supplied capabilities payload."""
    raw = raw or {}
    out = {}
    if "supports_tools" in raw:
        out["supports_tools"] = bool(raw["supports_tools"])
    if "supports_structured_output" in raw:
        out["supports_structured_output"] = bool(raw["supports_structured_output"])
    if "supports_streaming" in raw:
        out["supports_streaming"] = bool(raw["supports_streaming"])
    if "attachments" in raw:
        atts = raw["attachments"] or []
        if not isinstance(atts, list):
            raise ValueError("'capabilities.attachments' must be a list")
        coerced = [str(a) for a in atts]
        # Reject unknown aliases at the API boundary so bad payloads
        # never reach the registry layer (where lenient expansion just
        # drops them). Raw MIME types (containing ``/``) pass through
        # unchanged for parity with the built-in YAML schema.
        from application.core.model_yaml import builtin_attachment_aliases

        aliases = builtin_attachment_aliases()
        for entry in coerced:
            if "/" in entry:
                continue
            if entry not in aliases:
                valid = ", ".join(sorted(aliases.keys())) or "<none defined>"
                raise ValueError(
                    f"unknown attachment alias '{entry}' in "
                    f"'capabilities.attachments'. Valid aliases: {valid}, "
                    f"or use a raw MIME type like 'image/png'."
                )
        out["attachments"] = coerced
    if "context_window" in raw:
        try:
            cw = int(raw["context_window"])
        except (TypeError, ValueError):
            raise ValueError("'capabilities.context_window' must be an integer")
        if not (_CONTEXT_WINDOW_MIN <= cw <= _CONTEXT_WINDOW_MAX):
            raise ValueError(
                f"'capabilities.context_window' must be between "
                f"{_CONTEXT_WINDOW_MIN} and {_CONTEXT_WINDOW_MAX}"
            )
        out["context_window"] = cw
    return out


def _row_to_response(row: dict) -> dict:
    """Wire-format projection — never includes the API key."""
    return {
        "id": str(row["id"]),
        "upstream_model_id": row["upstream_model_id"],
        "display_name": row["display_name"],
        "description": row.get("description") or "",
        "base_url": row["base_url"],
        "capabilities": row.get("capabilities") or {},
        "enabled": bool(row.get("enabled", True)),
        "source": "user",
    }


@models_ns.route("/models")
class ModelsListResource(Resource):
    def get(self):
        """Get list of available models with their capabilities.

        When the request is authenticated, the response includes the
        user's own BYOM registrations alongside the built-in catalog.
        """
        try:
            user_id = None
            decoded_token = getattr(request, "decoded_token", None)
            if decoded_token:
                user_id = decoded_token.get("sub")

            registry = ModelRegistry.get_instance()
            models = registry.get_enabled_models(user_id=user_id)

            response = {
                "models": [model.to_dict() for model in models],
                "default_model_id": registry.default_model_id,
                "count": len(models),
            }
        except Exception as err:
            current_app.logger.error(f"Error fetching models: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(response), 200)


@models_ns.route("/user/models")
class UserModelsCollectionResource(Resource):
    @api.doc(description="List the current user's BYOM custom models")
    def get(self):
        user_id, err = _user_id_or_401()
        if err:
            return err
        try:
            with db_readonly() as conn:
                rows = UserCustomModelsRepository(conn).list_for_user(user_id)
            return make_response(
                jsonify({"models": [_row_to_response(r) for r in rows]}), 200
            )
        except Exception as e:
            current_app.logger.error(
                f"Error listing user custom models: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

    @api.doc(description="Register a new BYOM custom model")
    def post(self):
        user_id, err = _user_id_or_401()
        if err:
            return err

        data = request.get_json() or {}
        missing = check_required_fields(
            data,
            ["upstream_model_id", "display_name", "base_url", "api_key"],
        )
        if missing:
            return missing

        # SECURITY: reject blank api_key — would leak instance API key
        # to the user-supplied base_url via LLMCreator fallback.
        for required_nonblank in (
            "upstream_model_id",
            "display_name",
            "base_url",
            "api_key",
        ):
            value = data.get(required_nonblank)
            if not isinstance(value, str) or not value.strip():
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "error": f"'{required_nonblank}' must be a non-empty string",
                        }
                    ),
                    400,
                )

        # SSRF guard at create time. Re-runs at dispatch time (LLMCreator)
        # as defense in depth against DNS rebinding and pre-guard rows.
        try:
            validate_user_base_url(data["base_url"])
        except UnsafeUserUrlError as e:
            return make_response(
                jsonify({"success": False, "error": str(e)}), 400
            )

        try:
            capabilities = _normalize_capabilities(data.get("capabilities"))
        except ValueError as e:
            return make_response(
                jsonify({"success": False, "error": str(e)}), 400
            )

        try:
            with db_session() as conn:
                row = UserCustomModelsRepository(conn).create(
                    user_id=user_id,
                    upstream_model_id=data["upstream_model_id"],
                    display_name=data["display_name"],
                    description=data.get("description") or "",
                    base_url=data["base_url"],
                    api_key_plaintext=data["api_key"],
                    capabilities=capabilities,
                    enabled=bool(data.get("enabled", True)),
                )
        except Exception as e:
            current_app.logger.error(
                f"Error creating user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

        ModelRegistry.invalidate_user(user_id)
        return make_response(jsonify(_row_to_response(row)), 201)


@models_ns.route("/user/models/<string:model_id>")
class UserModelResource(Resource):
    @api.doc(description="Get one BYOM custom model")
    def get(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err
        try:
            with db_readonly() as conn:
                row = UserCustomModelsRepository(conn).get(model_id, user_id)
        except Exception as e:
            current_app.logger.error(
                f"Error fetching user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)
        if row is None:
            return make_response(jsonify({"success": False}), 404)
        return make_response(jsonify(_row_to_response(row)), 200)

    @api.doc(description="Update a BYOM custom model (partial)")
    def patch(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err

        data = request.get_json() or {}

        # Reject present-but-blank values for fields where blank doesn't
        # mean "no change". (The api_key special case — blank means "keep
        # existing" — is handled below.)
        for required_nonblank in (
            "upstream_model_id",
            "display_name",
            "base_url",
        ):
            if required_nonblank in data:
                value = data[required_nonblank]
                if not isinstance(value, str) or not value.strip():
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": f"'{required_nonblank}' cannot be blank",
                            }
                        ),
                        400,
                    )

        if "base_url" in data and data["base_url"]:
            try:
                validate_user_base_url(data["base_url"])
            except UnsafeUserUrlError as e:
                return make_response(
                    jsonify({"success": False, "error": str(e)}), 400
                )

        update_fields: dict = {}
        for k in (
            "upstream_model_id",
            "display_name",
            "description",
            "base_url",
            "enabled",
        ):
            if k in data:
                update_fields[k] = data[k]

        if "capabilities" in data:
            try:
                update_fields["capabilities"] = _normalize_capabilities(
                    data["capabilities"]
                )
            except ValueError as e:
                return make_response(
                    jsonify({"success": False, "error": str(e)}), 400
                )

        # PATCH semantics: blank/missing api_key → keep the existing
        # ciphertext; non-empty api_key → re-encrypt and replace.
        if data.get("api_key"):
            update_fields["api_key_plaintext"] = data["api_key"]

        if not update_fields:
            return make_response(
                jsonify({"success": False, "error": "no updatable fields"}), 400
            )

        try:
            with db_session() as conn:
                ok = UserCustomModelsRepository(conn).update(
                    model_id, user_id, update_fields
                )
        except Exception as e:
            current_app.logger.error(
                f"Error updating user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

        if not ok:
            return make_response(jsonify({"success": False}), 404)

        ModelRegistry.invalidate_user(user_id)
        with db_readonly() as conn:
            row = UserCustomModelsRepository(conn).get(model_id, user_id)
        return make_response(jsonify(_row_to_response(row)), 200)

    @api.doc(description="Delete a BYOM custom model")
    def delete(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err
        try:
            with db_session() as conn:
                ok = UserCustomModelsRepository(conn).delete(model_id, user_id)
        except Exception as e:
            current_app.logger.error(
                f"Error deleting user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)
        if not ok:
            return make_response(jsonify({"success": False}), 404)

        ModelRegistry.invalidate_user(user_id)
        return make_response(jsonify({"success": True}), 200)


def _run_connection_test(
    base_url: str, api_key: str, upstream_model_id: str
):
    """Send a 1-token chat-completion to verify a BYOM endpoint.

    Returns ``(body, http_status)``. Upstream errors return 200 with
    ``ok=False`` so the UI can render inline errors; only local SSRF
    rejection returns 400.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": upstream_model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        # pinned_post closes the DNS-rebinding window. Redirects off
        # because 3xx could bounce to an internal address (the SSRF
        # guard only validates the supplied URL).
        resp = pinned_post(
            url,
            json=payload,
            headers=headers,
            timeout=5,
            allow_redirects=False,
        )
    except UnsafeUserUrlError as e:
        return {"ok": False, "error": str(e)}, 400
    except requests.RequestException as e:
        return {"ok": False, "error": f"connection error: {e}"}, 200

    if 300 <= resp.status_code < 400:
        return (
            {
                "ok": False,
                "error": (
                    f"upstream returned HTTP {resp.status_code} "
                    "redirect; refusing to follow"
                ),
            },
            200,
        )

    if resp.status_code >= 400:
        # Cap and only reflect JSON to avoid body-exfil via non-API responses.
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type:
            text = (resp.text or "")[:500]
            error_msg = f"upstream returned HTTP {resp.status_code}: {text}"
        else:
            error_msg = f"upstream returned HTTP {resp.status_code}"
        return {"ok": False, "error": error_msg}, 200

    return {"ok": True}, 200


@models_ns.route("/user/models/test")
class UserModelTestPayloadResource(Resource):
    @api.doc(
        description=(
            "Test an arbitrary BYOM payload (display_name / model id / "
            "base_url / api_key) without saving. Used by the UI's 'Test "
            "connection' button so the user can validate before they "
            "Save. Same SSRF guard, same 1-token request, same 5s "
            "timeout as the by-id variant."
        )
    )
    def post(self):
        user_id, err = _user_id_or_401()
        if err:
            return err

        data = request.get_json() or {}
        missing = check_required_fields(
            data, ["base_url", "api_key", "upstream_model_id"]
        )
        if missing:
            return missing

        body, status = _run_connection_test(
            data["base_url"], data["api_key"], data["upstream_model_id"]
        )
        return make_response(jsonify(body), status)


@models_ns.route("/user/models/<string:model_id>/test")
class UserModelTestResource(Resource):
    @api.doc(
        description=(
            "Test a saved BYOM record. Defaults to the stored "
            "base_url / upstream_model_id / encrypted api_key, but "
            "any of those can be overridden via the request body so "
            "the UI can test in-flight edits before saving. Used by "
            "the 'Test connection' button in edit mode."
        )
    )
    def post(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err

        data = request.get_json() or {}
        # Per-field overrides; blank/missing falls back to stored value.
        override_base_url = (data.get("base_url") or "").strip() or None
        override_upstream_model_id = (
            data.get("upstream_model_id") or ""
        ).strip() or None
        override_api_key = (data.get("api_key") or "").strip() or None

        try:
            with db_readonly() as conn:
                repo = UserCustomModelsRepository(conn)
                row = repo.get(model_id, user_id)
                if row is None:
                    return make_response(jsonify({"success": False}), 404)
                stored_api_key = (
                    repo._decrypt_api_key(
                        row.get("api_key_encrypted", ""), user_id
                    )
                    if not override_api_key
                    else None
                )
        except Exception as e:
            current_app.logger.error(
                f"Error loading user custom model for test: {e}", exc_info=True
            )
            return make_response(
                jsonify({"ok": False, "error": "internal error loading model"}),
                500,
            )

        api_key = override_api_key or stored_api_key
        if not api_key:
            return make_response(
                jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Stored API key could not be decrypted. The "
                            "encryption secret may have rotated. Re-save "
                            "the model with the API key to recover."
                        ),
                    }
                ),
                400,
            )

        base_url = override_base_url or row["base_url"]
        upstream_model_id = (
            override_upstream_model_id or row["upstream_model_id"]
        )
        body, status = _run_connection_test(
            base_url, api_key, upstream_model_id
        )
        return make_response(jsonify(body), status)
