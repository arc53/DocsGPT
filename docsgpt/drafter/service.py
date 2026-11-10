"""The drafter's entry points for the routes: its config, checking a draft request before it streams, and
stopping a turn from another request.
"""

from __future__ import annotations

import json
import logging
import re
import time
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
#: ``<prefix><user>`` is a sorted set of the user's running turns, each scored by when its claim runs out.
_RUNNING_PREFIX = "drafter:running:"
#: Seconds a running turn's claim outlives the turn deadline (or lives, without one).
_RUNNING_GRACE_SECONDS = 60
#: Most ``POST /api/drafter/turns/<id>/cancel`` calls a user makes in a minute.
CANCEL_RATE_PER_MINUTE = 60
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


def _running_key(user_id: str) -> str:
    """The Redis sorted set of the user's running turns."""
    return f"{_RUNNING_PREFIX}{user_id}"


def _claim_life() -> float:
    """Seconds a running turn's claim lasts: past the turn deadline, so a crashed turn stops counting."""
    deadline = float(settings.DRAFTER_TURN_TIMEOUT_SECONDS or 0)
    return (deadline if deadline > 0 else TURN_TTL_SECONDS) + _RUNNING_GRACE_SECONDS


def claim_running(user_id: str, turn_id: Optional[str]) -> bool:
    """Count a turn among the user's running ones, unless they already run ``DRAFTER_MAX_RUNNING_TURNS``.

    Each claim is scored by when it runs out, and claims past that are dropped
    first, so a turn whose worker died stops counting on its own. The claim is
    added before the count, so two turns starting at once can't both pass the
    cap. :func:`end_turn` drops it.

    Args:
        user_id: The turn's owner.
        turn_id: The turn's id from :func:`start_turn`; without one (no Redis) nothing is counted.

    Returns:
        False when the turn is one too many; True otherwise, also with no cap or when Redis fails.
    """
    cap = int(settings.DRAFTER_MAX_RUNNING_TURNS or 0)
    if cap <= 0 or not turn_id:
        return True
    client = _turn_store()
    if client is None:
        return True
    key, now = _running_key(user_id), time.time()
    try:
        client.zremrangebyscore(key, "-inf", now)
        client.zadd(key, {turn_id: now + _claim_life()})
        client.expire(key, int(_claim_life()) + 1)
        if int(client.zcard(key)) > cap:
            client.zrem(key, turn_id)
            return False
    except Exception:
        logger.warning("drafter: could not count running turns; allowing the turn", exc_info=True)
    return True


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
        if int(settings.DRAFTER_MAX_RUNNING_TURNS or 0) > 0:
            client.zrem(_running_key(user_id), turn_id)
    except Exception:
        # The keys expire on their own; an ended turn only leaves them a while longer.
        logger.debug("drafter: could not forget an ended turn", exc_info=True)


#: ``<prefix>user:<user id>`` holds a user's last task-model key failure, ``<prefix>instance`` the instance task
#: model's. Settings > General and Admin > Defaults read them to mark a task model that can't run.
_MODEL_FAILURE_PREFIX = "drafter:model_failure:"
#: How long a failure is remembered without another draft: the next draft with the model records or clears it.
MODEL_FAILURE_TTL_SECONDS = 30 * 24 * 60 * 60


def _failure_key(user_id: Optional[str]) -> str:
    """The Redis key of a user's remembered failure, or the instance's for None."""
    return f"{_MODEL_FAILURE_PREFIX}user:{user_id}" if user_id else f"{_MODEL_FAILURE_PREFIX}instance"


def record_model_failure(user_id: str, model_id: str, code: str, *, instance: bool = False) -> None:
    """Remember that a draft on ``model_id`` failed with ``code`` (``model_auth``: the key was refused).

    Best-effort: without Redis nothing is remembered and the draft's own
    error is all the user sees.

    Args:
        user_id: The caller.
        model_id: The task model that failed.
        code: The ``error`` event's code.
        instance: The model is the instance's task model, so Admin > Defaults shows the failure too.
    """
    client = _turn_store()
    if client is None:
        return
    from datetime import datetime, timezone

    value = json.dumps({"model_id": model_id, "code": code, "at": datetime.now(timezone.utc).isoformat()})
    try:
        client.set(_failure_key(user_id), value, ex=MODEL_FAILURE_TTL_SECONDS)
        if instance:
            client.set(_failure_key(None), value, ex=MODEL_FAILURE_TTL_SECONDS)
    except Exception:
        logger.warning("drafter: could not remember a model failure", exc_info=True)


def model_failure(user_id: Optional[str], model_id: Optional[str]) -> Optional[dict]:
    """The remembered failure of ``model_id`` for a user (or the instance for None), else None.

    A failure of another model reads as None: it no longer applies once the
    task model changed.

    Args:
        user_id: The user, or None for the instance's task model.
        model_id: The task model that runs now.

    Returns:
        ``{"model_id", "code", "at"}`` (ISO 8601, UTC), or None.
    """
    client = _turn_store()
    if client is None or not model_id:
        return None
    try:
        raw = client.get(_failure_key(user_id))
    except Exception:
        return None
    try:
        failure = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(failure, dict) or failure.get("model_id") != model_id:
        return None
    return {key: failure.get(key) for key in ("model_id", "code", "at")}


def clear_model_failure(user_id: str, model_id: str) -> None:
    """Forget the user's and the instance's remembered failure of ``model_id`` after a draft on it worked."""
    for scope in (user_id, None):
        if model_failure(scope, model_id) is not None:
            forget_model_failure(scope)


def forget_model_failure(user_id: Optional[str]) -> None:
    """Drop the user's (or, for None, the instance's) remembered failure: the task model was changed."""
    client = _turn_store()
    if client is None:
        return
    try:
        client.delete(_failure_key(user_id))
    except Exception:
        logger.debug("drafter: could not forget a model failure", exc_info=True)
