"""Prompt-injection scores for MCP tool descriptions, taken when a server's actions are saved or re-read.

An MCP server's action names, descriptions and parameter descriptions reach the LLM verbatim as tool definitions,
so a hostile or compromised server can plant instructions there. While Admin > Guardrails warns on tool
descriptions and the operator has enabled the model (``DECISION_INJECTION_ENABLED``), each action's text is scored
when the actions are read from the server: on save, on refresh, and when a connection's tool is set up or switched
to another endpoint. Descriptions change only then, so nothing is scored at chat time.

Warn only. Legitimate descriptions are imperative instructions to an AI ("always call this first"), and how often
the model flags them is unmeasured, so an action is never turned off: its score is stored on it as
``injection: {p, scorer}`` and the save lists the actions at or above the flag threshold. A save waits at most the
hot-lane budget; the actions not scored in it are stored without a score, listed as unscored and queued, so the
next save or refresh finds them cached.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from docsgpt.core.settings import settings
from docsgpt.decisions import Budget
from docsgpt.decisions.features import INJECTION_TOOL_DESCRIPTION
from docsgpt.guardrails import injection_scoring

logger = logging.getLogger(__name__)


def warnings_on() -> bool:
    """Whether tool descriptions are scored: the Admin > Guardrails toggle and the operator's switch."""
    if not settings.DECISION_INJECTION_ENABLED:
        return False
    try:
        from docsgpt.guardrails.floor import mcp_description_warnings
        from docsgpt.storage.db.session import db_readonly

        with db_readonly() as conn:
            return mcp_description_warnings(conn)
    except Exception:  # noqa: BLE001 - an unreadable toggle warns on nothing
        logger.warning("Could not read the MCP tool-description warnings setting", exc_info=True)
        return False


def action_text(action: Dict[str, Any]) -> str:
    """What the LLM reads of an action: its name, description and parameter descriptions, one per line."""
    lines = [str(action.get("name") or ""), str(action.get("description") or "")]
    parameters = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
    for details in properties.values():
        if isinstance(details, dict) and isinstance(details.get("description"), str):
            lines.append(details["description"])
    return "\n".join(lines) + "\n"


def score_actions(actions: List[Dict[str, Any]]) -> Optional[Dict[str, List[str]]]:
    """Score MCP actions as read from their server and stamp each scored one with ``injection: {p, scorer}``.

    Args:
        actions: Action metadata, changed in place.

    Returns:
        ``{"flagged": [names], "unscored": [names]}``: the actions at or above the flag threshold (0.5), and
        those the model did not score in time, which are queued for background scoring. ``None`` while
        description warnings are off.
    """
    if not warnings_on():
        return None
    from docsgpt.guardrails.checks.model_injection import FLAG_THRESHOLD

    actions = [a for a in actions if isinstance(a, dict)]
    texts = [action_text(a) for a in actions]
    result = injection_scoring.score(texts, feature=INJECTION_TOOL_DESCRIPTION, budget=Budget.HOT)
    scorer = injection_scoring.scorer_id()
    flagged: List[str] = []
    unscored: List[str] = []
    later: List[str] = []
    for action, text, score, reason in zip(actions, texts, result, result.reasons):
        name = str(action.get("name") or "")
        # A window over the flag threshold settles it even when another went unanswered.
        if score is not None and (reason is None or score.p >= FLAG_THRESHOLD):
            action["injection"] = {"p": round(score.p, 4), "scorer": scorer}
            if score.p >= FLAG_THRESHOLD:
                flagged.append(name)
        else:
            action.pop("injection", None)
            unscored.append(name)
            later.append(text)
    for start in range(0, len(later), injection_scoring.LAZY_MAX_TEXTS):
        injection_scoring.enqueue_lazy(later[start:start + injection_scoring.LAZY_MAX_TEXTS])
    return {"flagged": flagged, "unscored": unscored}
