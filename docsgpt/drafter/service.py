"""The drafter's entry points for the routes: its config, checking a draft request before it streams, and
stopping a turn from another request.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from docsgpt.core.settings import settings
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.model import drafter_model
from docsgpt.drafter.output import EVENT_CHARS
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, get_recipe, Recipe

logger = logging.getLogger(__name__)

#: Most messages a conversation sends back, and characters of one user / assistant message. An assistant
#: message is an event the server sent, echoed back; the runner keeps every event within the limit.
MAX_MESSAGES = 24
USER_MESSAGE_CHARS = 8000
ASSISTANT_MESSAGE_CHARS = EVENT_CHARS

#: The rate-limit scope in Redis (``monitors:<scope>:rate:<user>:<minute>``).
RATE_SCOPE = "drafter"

#: How long a running turn's mark and a stop request live in Redis: longer than any turn runs.
TURN_TTL_SECONDS = 30 * 60
#: ``<prefix><user>:<turn id>`` marks the user's running turn; ``<prefix><user>:<turn id>:stop`` asks it to
#: stop. Both are keyed by the user, so a stop only ever reaches the caller's own turns.
_TURN_PREFIX = "drafter:turn:"
#: A turn id: 32 lowercase hex characters (a UUID's hex). The panel picks it and sends it with the turn.
TURN_ID = re.compile(r"[0-9a-f]{32}")


@dataclass
class Refusal:
    """Why a draft can't start: the ``error`` event's code and message."""

    code: str
    message: str

    def event(self) -> dict:
        """The refusal as the stream's ``error`` event."""
        return {"type": "error", "code": self.code, "message": self.message}


def drafter_config(user_id: Optional[str]) -> dict:
    """``GET /api/drafter/config``: whether the drafter is offered and on which model.

    Args:
        user_id: The caller.

    Returns:
        ``{"enabled", "model": {"id", "display_name"} | None, "reason": "disabled" | "no_model" | None}``.
    """
    if not settings.DRAFTER_ENABLED:
        return {"enabled": False, "model": None, "reason": "disabled"}
    model = drafter_model(user_id)
    if model is None:
        return {"enabled": False, "model": None, "reason": "no_model"}
    return {"enabled": True, "model": {"id": model["id"], "display_name": model["display_name"]}, "reason": None}


def parse_messages(raw: Any) -> list[dict]:
    """Check and clean the client-held conversation.

    Raises:
        BadDraftRequest: Not a list of ``{role, content}`` with user and
            assistant roles, empty, too long, or not ending with a user message.
    """
    if not isinstance(raw, list) or not raw:
        raise BadDraftRequest("messages must be a non-empty list")
    if len(raw) > MAX_MESSAGES:
        raise BadDraftRequest(f"A draft conversation can have at most {MAX_MESSAGES} messages; start a new one")
    out: list[dict] = []
    for message in raw:
        if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
            raise BadDraftRequest("Each message needs a role of user or assistant")
        content = message.get("content")
        if not isinstance(content, str):
            raise BadDraftRequest("Each message needs text content")
        limit = USER_MESSAGE_CHARS if message["role"] == "user" else ASSISTANT_MESSAGE_CHARS
        if len(content) > limit:
            raise BadDraftRequest(f"A message can be at most {limit} characters")
        text = clean_text(content, limit)
        if not text:
            raise BadDraftRequest("A message can't be empty")
        out.append({"role": message["role"], "content": text})
    if out[-1]["role"] != "user":
        raise BadDraftRequest("The last message must be the user's")
    return out


def prepare(user_id: str, body: Any) -> tuple[Optional[Refusal], Optional[DraftRequest], Optional[Recipe],
                                              Optional[dict]]:
    """Every check a draft passes before it streams, in order: enabled, request shape, model, quota, rate.

    The quota comes before the rate limit so a refused request doesn't use up the minute's budget.

    Args:
        user_id: The caller.
        body: The parsed JSON body.

    Returns:
        ``(refusal, request, recipe, model)``: a refusal and Nones, or no
        refusal and what the stream needs.
    """
    if not settings.DRAFTER_ENABLED:
        return Refusal("disabled", "Drafting is turned off on this instance."), None, None, None
    if not isinstance(body, dict):
        return Refusal("bad_request", "The request body must be a JSON object."), None, None, None
    recipe = get_recipe(body.get("recipe"))
    try:
        if recipe is None:
            raise BadDraftRequest("Unknown recipe")
        messages = parse_messages(body.get("messages"))
        context = body.get("context") if body.get("context") is not None else {}
        if not isinstance(context, dict):
            raise BadDraftRequest("context must be an object")
        context = recipe.parse_context(context)
    except BadDraftRequest as err:
        return Refusal("bad_request", str(err)), None, None, None
    model = drafter_model(user_id)
    if model is None:
        return Refusal("no_model", "No model is set up to draft with."), None, None, None
    from docsgpt.quotas.service import QuotaService

    exceeded = QuotaService.check(user_id, "direct")
    if exceeded is not None:
        return Refusal("quota", exceeded.to_payload().get("message") or "Usage quota reached."), None, None, None
    limit = int(settings.DRAFTER_RATE_LIMIT_PER_MINUTE or 0)
    if limit > 0:
        from docsgpt.monitors.triggers import rate_limited

        if rate_limited(RATE_SCOPE, user_id, limit):
            return Refusal("rate_limited", "Too many drafts in a minute. Wait a moment and try again."), \
                None, None, None
    request = DraftRequest(
        user_id=user_id,
        recipe=recipe.id,
        messages=messages,
        context=context,
        request_id=f"drafter:{uuid.uuid4()}",
    )
    return None, request, recipe, model


def _turn_store() -> Any:
    """The Redis client for turn stops (the chat Stop's client: reads time out), or None without Redis."""
    from docsgpt.activity.flags import _stop_redis

    return _stop_redis()


def _turn_key(user_id: str, turn_id: str) -> str:
    """The Redis key that marks the user's running turn; its stop request adds ``:stop``."""
    return f"{_TURN_PREFIX}{user_id}:{turn_id}"


def start_turn(user_id: str, requested: Any = None) -> Optional[str]:
    """Register a turn so another request can stop it (``POST /api/drafter/turns/<id>/cancel``).

    A turn only learns that its client went away when the server closes its
    response early. The production ASGI adapter drains the response first, so
    the panel stops a turn it gives up on (Stop, Start over, closing the panel)
    through this id instead. The panel picks the id and sends it with the turn,
    so it can stop the turn before the ``turn`` event arrives; a stop stored
    before the turn starts still stops it.

    Args:
        user_id: The turn's owner, the only caller who may stop it.
        requested: The id the panel sent. One that isn't a turn id, or that
            names a turn of the caller's still running, is replaced by a new one.

    Returns:
        The turn id, or None when Redis is unavailable (the turn then runs to its end).
    """
    client = _turn_store()
    if client is None:
        return None
    turn_id = requested if isinstance(requested, str) and TURN_ID.fullmatch(requested) else uuid.uuid4().hex
    try:
        # nx: two running turns never share an id, so a stop for one never stops the other.
        if not client.set(_turn_key(user_id, turn_id), "1", ex=TURN_TTL_SECONDS, nx=True):
            turn_id = uuid.uuid4().hex
            client.set(_turn_key(user_id, turn_id), "1", ex=TURN_TTL_SECONDS)
    except Exception:
        logger.warning("drafter: could not register a turn", exc_info=True)
        return None
    return turn_id


def cancel_turn(user_id: str, turn_id: str) -> bool:
    """Ask the caller's turn to stop before its next model call, whether it has started yet or not.

    The stop is stored under the caller's name, so it reaches only a turn of
    theirs with that id: one running now, or one that starts later (the panel
    names its turn before the server has registered it). Another user's turn
    with the same id is never touched.

    Args:
        user_id: The caller.
        turn_id: The turn's id, checked against :data:`TURN_ID` by the route.

    Returns:
        True when the stop was stored, False when Redis is unavailable.
    """
    client = _turn_store()
    if client is None:
        return False
    try:
        client.set(f"{_turn_key(user_id, turn_id)}:stop", "1", ex=TURN_TTL_SECONDS)
    except Exception:
        logger.warning("drafter: could not store a turn stop", exc_info=True)
        return False
    return True


def turn_cancelled(user_id: str, turn_id: Optional[str]) -> bool:
    """Whether the user stopped their turn; False without an id or when Redis can't be read."""
    if not turn_id:
        return False
    client = _turn_store()
    if client is None:
        return False
    try:
        return bool(client.exists(f"{_turn_key(user_id, turn_id)}:stop"))
    except Exception:
        return False


def end_turn(user_id: str, turn_id: Optional[str]) -> None:
    """Forget an ended turn's mark and stop request (best-effort; they expire anyway)."""
    if not turn_id:
        return
    client = _turn_store()
    if client is None:
        return
    key = _turn_key(user_id, turn_id)
    try:
        client.delete(key, f"{key}:stop")
    except Exception:
        # The keys expire on their own; an ended turn only leaves them a while longer.
        logger.debug("drafter: could not forget an ended turn", exc_info=True)
