"""Model routes.

- ``GET /api/models`` — list available models for the current user.
  Combines the built-in catalog with the user's BYOM records; in a team
  workspace, the catalog and the team's own models (never a person's).
- ``GET/POST/PATCH/DELETE /api/user/models[/<id>]`` — CRUD for
  OpenAI-compatible model registrations (BYOM): the caller's own, or with
  ``owner=team`` the models of the team the workspace header names.
- ``POST /api/user/models/<id>/test`` — sanity-check the upstream
  endpoint with a tiny request.
- ``POST /api/user/models/<id>/copy`` — copy one's own model into a team
  one administers, its key re-sealed for the team.

A list or create is the caller's own unless it says ``owner=team``; a route
about one model loads it by id and goes by its owner, never the header
(``docsgpt/workspaces/team_models.py``). Only a team's Admins and Owner
change a team's model, and never through a personal access token.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.api.pat.tokens import is_pat
from docsgpt.core.model_registry import ModelRegistry
from docsgpt.quotas.pause import PayerChecks
from docsgpt.security.safe_url import (
    UnsafeUserUrlError,
    pinned_post,
    validate_user_base_url,
)
from docsgpt.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields
from docsgpt.workspaces.context import current_workspace, parse_workspace_ref, WorkspaceError
from docsgpt.workspaces.principal import canonical_team_id, principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for
from docsgpt.workspaces.team_models import (
    CODE_MODEL_NOT_FOUND,
    CODE_NOT_AVAILABLE_TO_TOKENS,
    MODEL_ACTIONS,
    ModelDenied,
    authorize_model,
    creation_owner,
    is_team_model,
    listed_owner,
    matching_model,
    model_access,
    model_fields,
    wants_team,
)


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
    if not isinstance(raw, dict):
        raise ValueError("'capabilities' must be an object")
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
        from docsgpt.core.model_yaml import builtin_attachment_aliases

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
    if "api_flavor" in raw:
        from docsgpt.core.model_yaml import VALID_API_FLAVORS

        api_flavor = raw["api_flavor"]
        if not isinstance(api_flavor, str) or api_flavor not in VALID_API_FLAVORS:
            valid = ", ".join(sorted(VALID_API_FLAVORS))
            raise ValueError(
                f"'capabilities.api_flavor' must be one of [{valid}]"
            )
        out["api_flavor"] = api_flavor
    if "tool_result_images" in raw and raw["tool_result_images"] is not None:
        from docsgpt.core.model_yaml import VALID_TOOL_RESULT_IMAGES

        if not isinstance(raw["tool_result_images"], str) or raw["tool_result_images"] not in VALID_TOOL_RESULT_IMAGES:
            valid = ", ".join(sorted(VALID_TOOL_RESULT_IMAGES))
            raise ValueError(f"'capabilities.tool_result_images' must be one of [{valid}]")
        out["tool_result_images"] = raw["tool_result_images"]
    if "reasoning_effort" in raw and raw["reasoning_effort"] is not None:
        from docsgpt.core.model_yaml import VALID_REASONING_EFFORTS

        reasoning_effort = raw["reasoning_effort"]
        if not isinstance(reasoning_effort, str) or reasoning_effort not in VALID_REASONING_EFFORTS:
            valid = ", ".join(sorted(VALID_REASONING_EFFORTS))
            raise ValueError(
                f"'capabilities.reasoning_effort' must be one of [{valid}]"
            )
        out["reasoning_effort"] = reasoning_effort
    return out


def _row_to_response(conn, row: dict, viewer: str, checks: PayerChecks | None = None) -> dict:
    """Wire-format projection for ``viewer`` — never includes the API key.

    Args:
        conn: Open connection.
        row: The ``user_custom_models`` row.
        viewer: The person reading it.
        checks: The request's :class:`PayerChecks`, shared across a list.

    Returns:
        The model's fields plus ``owner``, ``team_id``, ``created_by`` and ``allowed_actions``. ``base_url``
        only for someone who may manage it: on a team's model, its Admins and Owner.
    """
    fields = model_fields(conn, row, viewer, checks=checks)
    body = {
        "id": str(row["id"]),
        "upstream_model_id": row["upstream_model_id"],
        "display_name": row["display_name"],
        "description": row.get("description") or "",
        "capabilities": row.get("capabilities") or {},
        "enabled": bool(row.get("enabled", True)),
        "source": "team" if fields["owner"] == "team" else "user",
        **fields,
    }
    if "manage" in fields["allowed_actions"]:
        body["base_url"] = row["base_url"]
    return body


def _token_refused():
    """403 for a personal access token changing a team's model: it carries a key every team chat uses."""
    return make_response(
        jsonify(
            {
                "success": False,
                "error": CODE_NOT_AVAILABLE_TO_TOKENS,
                "message": "A team's custom models can only be changed in the app",
            }
        ),
        403,
    )


def _is_token() -> bool:
    return is_pat(getattr(request, "decoded_token", None))


#: A stored key may not follow its model to another host: a new origin needs the key typed again.
CODE_API_KEY_REQUIRED_FOR_NEW_HOST = "api_key_required_for_new_host"
_NEW_HOST_MESSAGE = (
    "The base URL points to another host. Enter the API key again: the saved key is only sent to the host it "
    "was saved for."
)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(base_url: Any) -> Optional[tuple]:
    """The origin of a base URL: its scheme, host and port, with case and the default port normalized.

    Args:
        base_url: The endpoint URL.

    Returns:
        ``(scheme, host, port)``, or None when the URL can't be parsed (never the same origin as anything).
    """
    try:
        parts = urlsplit(str(base_url or "").strip())
        scheme = parts.scheme.lower()
        port = parts.port or _DEFAULT_PORTS.get(scheme)
    except ValueError:
        return None
    if not scheme or not parts.hostname:
        return None
    return scheme, parts.hostname.lower(), port


def _changes_host(stored_url: Any, new_url: Any) -> bool:
    """Whether ``new_url`` sends requests to another origin than ``stored_url``.

    The stored key was entered for one host; sending it anywhere else (a test, or every chat after a save)
    would hand it to whoever runs that host, so the caller must supply the key again.

    Args:
        stored_url: The saved base URL.
        new_url: The base URL the request asks for.

    Returns:
        bool: True unless both parse to the same origin.
    """
    stored, new = _origin(stored_url), _origin(new_url)
    return stored is None or stored != new


def _audit_team_model(conn, actor: str, event: str, row: dict, **detail) -> None:
    """Record ``event`` on the team's audit trail when ``row`` is a team's model (best-effort).

    Args:
        conn: Open connection inside the action's transaction.
        actor: Who did it.
        event: ``team.model_added``, ``team.model_updated`` or ``team.model_removed``.
        row: The model.
        **detail: More metadata; None values are dropped.
    """
    if not is_team_model(row):
        return
    # Lazy: the teams routes import the user API, which imports this module.
    from docsgpt.api.user.teams.routes import _audit

    _audit(conn, actor, event, team_id=team_of_principal(row["user_id"]), model_id=str(row["id"]), **detail)


@models_ns.route("/models")
class ModelsListResource(Resource):
    def get(self):
        """Get list of available models with their capabilities.

        When the request is authenticated, the response includes the
        user's own BYOM registrations alongside the built-in catalog. In a
        team workspace it lists the team's enabled models instead
        (``source: "team"``, without ``base_url``) and never the person's:
        saving one on a team item is refused, so a team's pickers never
        offer one.
        """
        try:
            user_id = None
            decoded_token = getattr(request, "decoded_token", None)
            if decoded_token:
                user_id = decoded_token.get("sub")
            if user_id and parse_workspace_ref(request) is not None:
                # Only a named team is looked up; Personal needs no membership read.
                try:
                    with db_readonly() as conn:
                        workspace = current_workspace(conn)
                except WorkspaceError as err:
                    return err.response()
                if workspace.is_team:
                    # The team's own models resolve in its principal's layer; a person's never do.
                    user_id = workspace.owner_id

            registry = ModelRegistry.get_instance()
            models = registry.get_enabled_models(user_id=user_id)
            if user_id and user_id != request.decoded_token.get("sub"):
                models = [model for model in models if model.source != "user"]
            entries = []
            for model in models:
                entry = model.to_dict()
                if model.source == "team":
                    # Members use a team's model; only its Admins see where it points (Custom models page).
                    entry.pop("base_url", None)
                entries.append(entry)

            response = {
                "models": entries,
                "default_model_id": registry.default_model_id,
                "count": len(models),
            }
        except Exception as err:
            current_app.logger.error(f"Error fetching models: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(response), 200)


@models_ns.route("/user/models")
class UserModelsCollectionResource(Resource):
    @api.doc(
        description=(
            "List the current user's BYOM custom models; with owner=team, the models of the team the "
            "workspace header names (any member)"
        ),
        params={"owner": "personal (default) or team"},
    )
    def get(self):
        user_id, err = _user_id_or_401()
        if err:
            return err
        try:
            with db_readonly() as conn:
                owner_id = listed_owner(conn, user_id, request.args.get("owner"))
                rows = UserCustomModelsRepository(conn).list_for_user(owner_id)
                checks = PayerChecks()
                # One lookup names whoever added each team model, instead of one per row.
                checks.emails(conn, [r.get("created_by") for r in rows if is_team_model(r)])
                models = [_row_to_response(conn, r, user_id, checks) for r in rows]
            return make_response(jsonify({"models": models}), 200)
        except WorkspaceError as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(
                f"Error listing user custom models: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

    @api.doc(
        description=(
            "Register a new BYOM custom model. owner=team adds it for the team the workspace header "
            "names (Admins, in the app only); without it the model is the caller's own, whatever the header."
        )
    )
    def post(self):
        user_id, err = _user_id_or_401()
        if err:
            return err

        data = request.get_json() or {}
        try:
            for_team = wants_team(data.get("owner"))
        except WorkspaceError as e:
            return e.response()
        if for_team and _is_token():
            return _token_refused()
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
                owner_id, created_by = creation_owner(conn, user_id, data.get("owner"))
                # A team's key is sealed with the principal, so any Admin can replace it and runs open it.
                row = UserCustomModelsRepository(conn).create(
                    user_id=owner_id,
                    upstream_model_id=data["upstream_model_id"],
                    display_name=data["display_name"],
                    description=data.get("description") or "",
                    base_url=data["base_url"],
                    api_key_plaintext=data["api_key"],
                    capabilities=capabilities,
                    enabled=bool(data.get("enabled", True)),
                    created_by=created_by,
                )
                _audit_team_model(
                    conn, user_id, "team.model_added", row, display_name=row["display_name"],
                    upstream_model_id=row["upstream_model_id"], copied=False,
                )
                body = _row_to_response(conn, row, user_id)
        except WorkspaceError as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(
                f"Error creating user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

        ModelRegistry.invalidate_user(owner_id)
        return make_response(jsonify(body), 201)


@models_ns.route("/user/models/<string:model_id>")
class UserModelResource(Resource):
    @api.doc(description="Get one BYOM custom model: the caller's own, or a team's they are in")
    def get(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err
        try:
            with db_readonly() as conn:
                access = authorize_model(conn, model_id, user_id, "view")
                body = _row_to_response(conn, dict(access.row), user_id)
        except ModelDenied as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(
                f"Error fetching user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(body), 200)

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
                access = authorize_model(conn, model_id, user_id, "manage")
                if access.is_team and _is_token():
                    return _token_refused()
                owner_id = access.owner_id
                if (
                    "base_url" in update_fields
                    and "api_key_plaintext" not in update_fields
                    and _changes_host(access.row.get("base_url"), update_fields["base_url"])
                ):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": CODE_API_KEY_REQUIRED_FOR_NEW_HOST,
                                "message": _NEW_HOST_MESSAGE,
                            }
                        ),
                        400,
                    )
                repo = UserCustomModelsRepository(conn)
                # The owner's id seals a replaced key, so a team's stays the team's.
                ok = repo.update(model_id, owner_id, update_fields)
                if not ok:
                    return make_response(jsonify({"success": False}), 404)
                row = repo.get(model_id, owner_id)
                _audit_team_model(
                    conn, user_id, "team.model_updated", row, display_name=row["display_name"],
                    fields=sorted(k for k in update_fields if k != "api_key_plaintext"),
                    key_replaced="api_key_plaintext" in update_fields,
                )
                body = _row_to_response(conn, row, user_id)
        except ModelDenied as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(
                f"Error updating user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

        ModelRegistry.invalidate_user(owner_id)
        return make_response(jsonify(body), 200)

    @api.doc(
        description=(
            "Delete a BYOM custom model. On a team's model (Admins, in the app only) the answer also has "
            "usage: the team's agents and workflows that named it; agents fall back to the default model, "
            "workflow steps set to it stop."
        )
    )
    def delete(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err
        body: dict = {"success": True}
        try:
            with db_session() as conn:
                access = authorize_model(conn, model_id, user_id, "manage")
                if access.is_team and _is_token():
                    return _token_refused()
                owner_id = access.owner_id
                row = dict(access.row)
                repo = UserCustomModelsRepository(conn)
                usage = repo.usage(owner_id, model_id) if access.is_team else None
                if not repo.delete(model_id, owner_id):
                    return make_response(jsonify({"success": False}), 404)
                if usage is not None:
                    body["usage"] = usage
                    _audit_team_model(
                        conn, user_id, "team.model_removed", row, display_name=row["display_name"],
                        agents=len(usage["agents"]), workflows=len(usage["workflows"]),
                    )
        except ModelDenied as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(
                f"Error deleting user custom model: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 500)

        ModelRegistry.invalidate_user(owner_id)
        return make_response(jsonify(body), 200)


@models_ns.route("/user/models/<string:model_id>/usage")
class UserModelUsageResource(Resource):
    @api.doc(
        description=(
            "The owner's agents and workflows that name a custom model. If it is deleted, agents fall back to "
            "the default model and workflow steps set to it stop: "
            "{usage: {agents: [{id, name}], workflows: [{id, name}]}}. Anyone who may see the model: every member "
            "for a team's model, only its owner for a person's own."
        )
    )
    def get(self, model_id):
        """Answer which of the owner's agents and workflows use the model, so a delete confirm can name them.

        Args:
            model_id: The model's id.

        Returns:
            200 ``{success, usage}``; 404 ``model_not_found`` to anyone who may not see the model.
        """
        user_id, err = _user_id_or_401()
        if err:
            return err
        try:
            with db_readonly() as conn:
                access = authorize_model(conn, model_id, user_id, "view")
                usage = UserCustomModelsRepository(conn).usage(access.owner_id, str(access.row["id"]))
        except ModelDenied as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(f"Error reading custom model usage: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify({"success": True, "usage": usage}), 200)


@models_ns.route("/user/models/<string:model_id>/copy")
class UserModelCopyResource(Resource):
    @api.doc(
        description=(
            "Copy the caller's own custom model into a team where they are an Admin or the Owner (body: "
            "team_id). The team's copy has its key re-sealed for the team and names the caller as the one who "
            "added it; the caller's model is left as it was. 409 model_already_in_team when the team already "
            "has a model with the same base URL and upstream model id. In the app only."
        )
    )
    def post(self, model_id):
        user_id, err = _user_id_or_401()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        try:
            with db_session() as conn:
                repo = UserCustomModelsRepository(conn)
                row = repo.get_by_id(model_id)
                access = model_access(conn, row, user_id)
                # Only a person's own model is copied; a team's or anyone else's doesn't exist for this.
                if access is None or access.is_team:
                    return ModelDenied(404, CODE_MODEL_NOT_FOUND, "Model not found").response()
                if _is_token():
                    return _token_refused()
                principal, err = _copy_target(conn, user_id, data.get("team_id"))
                if err:
                    return err
                existing = matching_model(repo.list_for_user(principal), row["base_url"], row["upstream_model_id"])
                if existing is not None:
                    return make_response(jsonify({
                        "success": False, "error": "model_already_in_team", "model_id": str(existing["id"]),
                        "message": "The team already has this model",
                    }), 409)
                api_key = repo.get_decrypted_api_key(str(row["id"]), user_id)
                if not api_key:
                    return make_response(jsonify({
                        "success": False, "error": "credentials_unreadable",
                        "message": "This model's key can't be read. Replace it, then copy the model.",
                    }), 409)
                # A fresh row the principal owns, its key sealed for the team; the person's row stays as it was.
                copied = repo.create(
                    user_id=principal,
                    upstream_model_id=row["upstream_model_id"],
                    display_name=row["display_name"],
                    description=row.get("description") or "",
                    base_url=row["base_url"],
                    api_key_plaintext=api_key,
                    capabilities=row.get("capabilities") or {},
                    enabled=bool(row.get("enabled", True)),
                    created_by=user_id,
                )
                _audit_team_model(
                    conn, user_id, "team.model_added", copied, display_name=copied["display_name"],
                    upstream_model_id=copied["upstream_model_id"], copied=True,
                )
                body = _row_to_response(conn, copied, user_id)
        except Exception as e:
            current_app.logger.error(f"Error copying a custom model to a team: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)

        ModelRegistry.invalidate_user(principal)
        return make_response(jsonify(body), 201)


def _copy_target(conn, user_id: str, team_id) -> tuple:
    """The principal of the team a model is copied into, when ``user_id`` may add models there.

    Args:
        conn: Open connection.
        user_id: The person copying.
        team_id: The body's ``team_id``.

    Returns:
        ``(principal, None)``, or ``(None, error response)``: 400 ``team_id_required``, 404
        ``workspace_not_found`` outside the team, 403 ``workspace_role_required`` below Admin.
    """
    if not isinstance(team_id, str) or not team_id.strip():
        return None, make_response(jsonify({
            "success": False, "error": "team_id_required", "message": "Pick the team to copy the model to",
        }), 400)
    try:
        canonical = canonical_team_id(team_id.strip())
    except ValueError:
        canonical = None
    role = team_role_for(conn, user_id, canonical) if canonical else None
    if role is None:
        return None, WorkspaceError(404, "workspace_not_found", "Workspace not found").response()
    if not role_at_least(role, MODEL_ACTIONS["manage"]):
        return None, WorkspaceError(
            403, "workspace_role_required", "Only the team's Admins add models for it",
        ).response()
    return principal_id(canonical), None


def _run_connection_test(
    base_url: str,
    api_key: str,
    upstream_model_id: str,
    api_flavor: str = "chat_completions",
):
    """Send a minimal generation request to verify a BYOM endpoint.

    Returns ``(body, http_status)``. Upstream errors return 200 with
    ``ok=False`` so the UI can render inline errors; only local SSRF
    rejection returns 400.
    """
    if api_flavor == "responses":
        url = base_url.rstrip("/") + "/responses"
        payload = {
            "model": upstream_model_id,
            "input": "hi",
            "max_output_tokens": 16,
            "stream": False,
            "store": False,
        }
    else:
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
            "Save. Uses the selected API protocol with the same SSRF guard "
            "and 5s timeout as the by-id variant."
        )
    )
    def post(self):
        user_id, err = _user_id_or_401()
        if err:
            return err

        data = request.get_json() or {}
        try:
            if wants_team(data.get("owner")):
                # Testing a model for the team is a step of adding one: the same Admins, in the app.
                if _is_token():
                    return _token_refused()
                with db_readonly() as conn:
                    creation_owner(conn, user_id, data.get("owner"))
        except WorkspaceError as e:
            return e.response()
        missing = check_required_fields(
            data, ["base_url", "api_key", "upstream_model_id"]
        )
        if missing:
            return missing

        try:
            capabilities = _normalize_capabilities(data.get("capabilities"))
        except ValueError as e:
            return make_response(jsonify({"ok": False, "error": str(e)}), 400)
        body, status = _run_connection_test(
            data["base_url"],
            data["api_key"],
            data["upstream_model_id"],
            capabilities.get("api_flavor", "chat_completions"),
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
                access = authorize_model(conn, model_id, user_id, "manage")
                if access.is_team and _is_token():
                    return _token_refused()
                row = dict(access.row)
                if (
                    override_base_url
                    and not override_api_key
                    and _changes_host(row.get("base_url"), override_base_url)
                ):
                    return make_response(
                        jsonify({"ok": False, "error": _NEW_HOST_MESSAGE, "code": CODE_API_KEY_REQUIRED_FOR_NEW_HOST}),
                        400,
                    )
                # The key was sealed with the owner's id: the team's principal on a team's model.
                stored_api_key = (
                    UserCustomModelsRepository._decrypt_api_key(
                        row.get("api_key_encrypted", ""), access.owner_id
                    )
                    if not override_api_key
                    else None
                )
        except ModelDenied as e:
            return e.response()
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
        try:
            capabilities = (
                _normalize_capabilities(data["capabilities"])
                if "capabilities" in data
                else (row.get("capabilities") or {})
            )
        except ValueError as e:
            return make_response(jsonify({"ok": False, "error": str(e)}), 400)
        body, status = _run_connection_test(
            base_url,
            api_key,
            upstream_model_id,
            capabilities.get("api_flavor", "chat_completions"),
        )
        return make_response(jsonify(body), status)
