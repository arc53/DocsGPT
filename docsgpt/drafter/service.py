"""The drafter's entry points for the routes: its config, and checking a draft request before it streams."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from docsgpt.core.settings import settings
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.model import drafter_model
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, get_recipe, Recipe

logger = logging.getLogger(__name__)

#: Most messages a conversation sends back, and characters of one user / assistant message.
MAX_MESSAGES = 24
USER_MESSAGE_CHARS = 8000
ASSISTANT_MESSAGE_CHARS = 60000

#: The rate-limit scope in Redis (``monitors:<scope>:rate:<user>:<minute>``).
RATE_SCOPE = "drafter"


@dataclass
class Refusal:
    """Why a draft can't start: the ``error`` event's code and message."""

    code: str
    message: str

    def event(self) -> dict:
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
    """Every check a draft passes before it streams, in order: enabled, request shape, model, rate, quota.

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
    limit = int(settings.DRAFTER_RATE_LIMIT_PER_MINUTE or 0)
    if limit > 0:
        from docsgpt.monitors.triggers import rate_limited

        if rate_limited(RATE_SCOPE, user_id, limit):
            return Refusal("rate_limited", "Too many drafts in a minute. Wait a moment and try again."), \
                None, None, None
    from docsgpt.quotas.service import QuotaService

    exceeded = QuotaService.check(user_id, "direct")
    if exceeded is not None:
        return Refusal("quota", exceeded.to_payload().get("message") or "Usage quota reached."), None, None, None
    request = DraftRequest(
        user_id=user_id,
        recipe=recipe.id,
        messages=messages,
        context=context,
        request_id=f"drafter:{uuid.uuid4()}",
    )
    return None, request, recipe, model
