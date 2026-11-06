"""Draft with DocsGPT: the drafter fills a form from a description and never saves.

- ``GET /api/drafter/config`` -- whether the drafter is offered, and its model.
- ``POST /api/drafter/stream`` -- one draft turn as server-sent events.
- ``GET /api/drafter/topics/status`` -- whether an agent has enough conversations for topic suggestions.

All are session-only: ``docsgpt/api/pat/rules.py`` lists them in ``DENIED``,
so an access token gets 403. Nothing is stored: the client sends the whole
conversation each turn, and the turn reads the caller's workspace and writes
only its ``token_usage`` rows (source ``drafter``).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Iterator

from flask import jsonify, make_response, request, Response
from flask_restx import fields, Namespace, Resource

from docsgpt.api import api
from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, Recipe
from docsgpt.drafter.runner import run_draft
from docsgpt.drafter.service import drafter_config, prepare
from docsgpt.streaming.sse_keepalive import with_sse_keepalive

logger = logging.getLogger(__name__)

drafter_ns = Namespace("drafter", description="Draft with DocsGPT", path="/api")

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _frame(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _closed(*events: dict) -> Iterator[str]:
    """Frames for ``events`` followed by the closing ``end``."""
    for event in events:
        yield _frame(event)
    yield _frame({"type": "end"})


def _user_id():
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


@drafter_ns.route("/drafter/config")
class DrafterConfig(Resource):
    @api.doc(
        description=(
            "Whether Draft with DocsGPT is offered to the caller, and the model it runs on (the task model). "
            'Returns {"enabled", "model": {"id", "display_name"} | null, "reason": "disabled" | "no_model" | null}.'
        ),
        responses={200: "The drafter's config", 401: "Not signed in"},
    )
    def get(self) -> Response:
        """Report whether the drafter is on for the caller, and its model."""
        user_id = _user_id()
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        return make_response(jsonify(drafter_config(user_id)), 200)


@drafter_ns.route("/drafter/stream")
class DrafterStream(Resource):
    stream_model = api.model(
        "DrafterStreamModel",
        {
            "recipe": fields.String(
                required=True,
                description="What is drafted: agent (the agent form), prompt (a prompt), topics (Insights topics)",
            ),
            "messages": fields.List(
                fields.Raw,
                required=True,
                description=(
                    "The conversation so far, oldest first: {role: user | assistant, content}. An assistant "
                    "message is the JSON of an earlier questions or proposal event. Ends with a user message."
                ),
            ),
            "context": fields.Raw(
                description=(
                    "The recipe's screen state: the agent form's current values (agent), the prompt being "
                    "written or improved (prompt), or {agent_id} (topics)"
                )
            ),
        },
    )

    @api.expect(stream_model)
    @api.doc(
        description=(
            "Run one draft turn and stream it as server-sent events (data: <json>). Events: status, message, "
            "questions, proposal, error, and end (always last). Refusals (disabled, no_model, rate_limited, quota, "
            "bad_request) arrive as an error event in a 200 stream. Nothing is saved."
        ),
        responses={200: "text/event-stream of draft events", 401: "Not signed in"},
    )
    def post(self) -> Response:
        """Stream one draft turn."""
        user_id = _user_id()
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        refusal, draft, recipe, model = prepare(user_id, request.get_json(silent=True))
        if refusal is not None:
            return Response(_closed(refusal.event()), mimetype="text/event-stream", headers=_SSE_HEADERS)
        try:
            # Read now, in the request: the stream runs on a thread with no request context.
            workspace = recipe.load_workspace(user_id, draft.context)
        except BadDraftRequest as err:
            return Response(
                _closed({"type": "error", "code": "bad_request", "message": str(err)}),
                mimetype="text/event-stream",
                headers=_SSE_HEADERS,
            )
        except Exception:
            logger.exception("drafter: could not read the workspace")
            return Response(
                _closed({"type": "error", "code": "model_error",
                         "message": "Your workspace could not be read. Try again in a moment."}),
                mimetype="text/event-stream",
                headers=_SSE_HEADERS,
            )
        stopped = threading.Event()
        return Response(
            with_sse_keepalive(_stream(draft, recipe, workspace, model, stopped), on_disconnect=stopped.set),
            mimetype="text/event-stream",
            headers=_SSE_HEADERS,
        )


@drafter_ns.route("/drafter/topics/status")
class DrafterTopicsStatus(Resource):
    @api.doc(
        description=(
            "Whether Draft with DocsGPT suggests Insights topics for an agent from its conversations: Insights "
            "sorts them (on this server and for the agent) and it had enough in the last 30 days. Returns "
            "{\"available\", \"conversations\", \"needed\", \"reason\"}; reason is off_on_this_instance or "
            "turned_off_for_this_agent while Insights is off (conversations then 0, uncounted), else null. Needs "
            "edit access to the agent: the suggestions read its users' questions."
        ),
        params={"agent_id": "Agent id"},
        responses={200: "The agent's status", 400: "No agent_id", 401: "Not signed in",
                   403: "No edit access", 404: "Agent not found"},
    )
    def get(self) -> Response:
        """Report whether topic suggestions are available for an agent."""
        from docsgpt.api.user.resource_access import AccessDenied
        from docsgpt.drafter.topics_recipe import topics_status

        user_id = _user_id()
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        agent_id = (request.args.get("agent_id") or "").strip()
        if not agent_id:
            return make_response(jsonify({"success": False, "message": "agent_id is required"}), 400)
        try:
            status = topics_status(user_id, agent_id)
        except AccessDenied as denied:
            return make_response(jsonify({"success": False, "message": denied.message}), denied.status)
        except Exception:
            logger.exception("drafter: could not read the topics status")
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(status), 200)


def _stream(draft: DraftRequest, recipe: Recipe, workspace: Workspace, model: dict,
            stopped: threading.Event) -> Iterator[str]:
    """The turn's frames, always closed by ``end``; an unexpected failure becomes a ``model_error`` event."""
    try:
        for event in run_draft(draft, recipe, workspace, model, should_stop=stopped.is_set):
            yield _frame(event)
    except Exception:
        logger.exception("drafter: the draft failed")
        yield _frame({"type": "error", "code": "model_error", "message": "The draft failed. Try again."})
    yield _frame({"type": "end"})
