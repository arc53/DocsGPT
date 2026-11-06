"""Draft with DocsGPT: the drafter fills a form from a description and never saves.

- ``GET /api/drafter/config`` -- whether the drafter is offered, and its model.
- ``POST /api/drafter/stream`` -- one draft turn as server-sent events.
- ``POST /api/drafter/turns/<turn_id>/cancel`` -- stop the caller's running turn.
- ``GET /api/drafter/topics/status`` -- whether an agent has enough conversations for topic suggestions.

All are session-only: ``docsgpt/api/pat/rules.py`` lists them in ``DENIED``,
so an access token gets 403. Nothing is stored: the client sends the whole
conversation each turn, and the turn reads the caller's workspace and writes
only its ``token_usage`` rows (source ``drafter``).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Iterator, Optional

from flask import jsonify, make_response, request, Response
from flask_restx import fields, Namespace, Resource

from docsgpt.api import api
from docsgpt.core.settings import settings
from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, Recipe
from docsgpt.drafter.runner import run_draft
from docsgpt.drafter.service import cancel_turn, drafter_config, end_turn, prepare, start_turn, turn_cancelled
from docsgpt.streaming.sse_keepalive import with_sse_keepalive

logger = logging.getLogger(__name__)

drafter_ns = Namespace("drafter", description="Draft with DocsGPT", path="/api")

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_TURN_ID = re.compile(r"[0-9a-f]{32}")


def _frame(event: dict) -> str:
    """One server-sent event frame carrying ``event`` as JSON."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _closed(*events: dict) -> Iterator[str]:
    """Frames for ``events`` followed by the closing ``end``."""
    for event in events:
        yield _frame(event)
    yield _frame({"type": "end"})


def _user_id() -> Optional[str]:
    """The signed-in caller's id from the request's decoded token, or None without one."""
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
            "Run one draft turn and stream it as server-sent events (data: <json>). Events: turn (first, "
            "{\"id\"}: the id POST /api/drafter/turns/<id>/cancel stops; absent when the server can't stop turns), "
            "status, message, questions, proposal, error, and end (always last). Refusals (disabled, no_model, "
            "rate_limited, quota, bad_request) arrive as an error event in a 200 stream. Nothing is saved."
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
        # Under Werkzeug a disconnect closes the stream early (``stopped``); the production ASGI adapter drains
        # it first, so the panel stops a turn it gives up on through the turn id instead.
        stopped = threading.Event()
        turn_id = start_turn(user_id)
        return Response(
            with_sse_keepalive(_stream(draft, recipe, workspace, model, stopped, turn_id), on_disconnect=stopped.set),
            mimetype="text/event-stream",
            headers=_SSE_HEADERS,
        )


@drafter_ns.route("/drafter/turns/<string:turn_id>/cancel")
class DrafterTurnCancel(Resource):
    @api.doc(
        description=(
            "Stop the caller's running draft turn: it makes no further model calls and its stream ends with "
            "end. The id is the stream's first event (turn). Answers 202 once the request is stored."
        ),
        responses={202: "The stop was requested", 401: "Not signed in",
                   404: "The caller has no such turn (unknown, ended, or someone else's)",
                   503: "Stopping is unavailable right now"},
    )
    def post(self, turn_id: str) -> Response:
        """Ask a running draft turn to stop.

        Args:
            turn_id: The id from the turn's ``turn`` event.

        Returns:
            202 when the stop was requested, 404 when the caller has no such
            turn, 503 without Redis.
        """
        user_id = _user_id()
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        if not _TURN_ID.fullmatch(turn_id):
            return make_response(jsonify({"success": False, "message": "Turn not found"}), 404)
        cancelled = cancel_turn(user_id, turn_id)
        if cancelled is None:
            return make_response(jsonify({"success": False, "message": "Stopping is unavailable right now"}), 503)
        if not cancelled:
            return make_response(jsonify({"success": False, "message": "Turn not found"}), 404)
        return make_response(jsonify({"success": True}), 202)


@drafter_ns.route("/drafter/topics/status")
class DrafterTopicsStatus(Resource):
    @api.doc(
        description=(
            "Whether Draft with DocsGPT suggests Insights topics for an agent from its conversations: Insights "
            "sorts them (on this server and for the agent) and it had enough in the last 30 days. Returns "
            "{\"available\", \"conversations\", \"needed\", \"reason\"}; reason is disabled (the drafter is "
            "off), off_on_this_instance or turned_off_for_this_agent (Insights is off), with conversations 0 and "
            "uncounted, else null. Needs edit access to the agent: the suggestions read its users' questions."
        ),
        params={"agent_id": "Agent id"},
        responses={200: "The agent's status", 400: "No agent_id", 401: "Not signed in",
                   403: "No edit access", 404: "Agent not found", 500: "The status could not be read"},
    )
    def get(self) -> Response:
        """Report whether topic suggestions are available for an agent."""
        from docsgpt.api.user.resource_access import AccessDenied
        from docsgpt.drafter.topics_recipe import MIN_CONVERSATIONS, topics_status

        user_id = _user_id()
        if not user_id:
            return make_response(jsonify({"success": False}), 401)
        agent_id = (request.args.get("agent_id") or "").strip()
        if not agent_id:
            return make_response(jsonify({"success": False, "message": "agent_id is required"}), 400)
        if not settings.DRAFTER_ENABLED:
            return make_response(jsonify({"available": False, "conversations": 0, "needed": MIN_CONVERSATIONS,
                                          "reason": "disabled"}), 200)
        try:
            status = topics_status(user_id, agent_id)
        except AccessDenied as denied:
            return make_response(jsonify({"success": False, "message": denied.message}), denied.status)
        except Exception:
            logger.exception("drafter: could not read the topics status")
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify(status), 200)


def _stream(draft: DraftRequest, recipe: Recipe, workspace: Workspace, model: dict,
            stopped: threading.Event, turn_id: Optional[str] = None) -> Iterator[str]:
    """The turn's frames, always closed by ``end``; an unexpected failure becomes a ``model_error`` event.

    Args:
        draft: The checked request.
        recipe: Its recipe.
        workspace: The caller's workspace, read in the request.
        model: The drafter model.
        stopped: Set when the server closes the stream early (the client went away).
        turn_id: The turn's id for a stop from another request; its ``turn`` event comes first. None when
            turns can't be stopped that way.

    Yields:
        SSE frames.
    """
    def should_stop() -> bool:
        return stopped.is_set() or turn_cancelled(turn_id)

    try:
        if turn_id:
            yield _frame({"type": "turn", "id": turn_id})
        for event in run_draft(draft, recipe, workspace, model, should_stop=should_stop):
            yield _frame(event)
    except Exception:
        logger.exception("drafter: the draft failed")
        yield _frame({"type": "error", "code": "model_error", "message": "The draft failed. Try again."})
    finally:
        end_turn(turn_id)
    yield _frame({"type": "end"})
