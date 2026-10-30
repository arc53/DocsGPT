"""An API tool, made from a new personal access token, for agents to read this account.

The tool's actions are the read endpoints an agent can use to look at the
account's agents, logs, feedback and conversations. Only the ones the token
may call are included: its scopes allow them and its resource filter does not
close them (see ``RULES``). Every action sends the token as its
``Authorization`` header, stored sealed like any API tool secret.
"""

from __future__ import annotations

from typing import Any, Optional

from docsgpt.api.pat.rules import RULES
from docsgpt.api.pat.tokens import expand_scopes


def _param(description: str, *, type_: str = "string", required: bool = False) -> dict:
    return {
        "type": type_,
        "description": description,
        "value": "",
        "filled_by_llm": True,
        "required": required,
    }


_AGENT_ID = "The agent's id, from list_agents. Leave empty for the whole account."
_PERIOD = "One of last_hour, last_24_hour, last_7_days, last_15_days, last_30_days."

#: ``(action name, method, path, description, query params, body params)``.
CATALOG: tuple[tuple[str, str, str, str, dict, dict], ...] = (
    (
        "list_agents",
        "GET",
        "/api/get_agents",
        "List the agents of this account with their ids and names.",
        {},
        {},
    ),
    (
        "get_logs",
        "POST",
        "/api/get_user_logs",
        (
            "Read the Logs timeline, newest first: each chat turn's question, answer, "
            "conversation_id, passthrough values (who asked) and feedback (like or dislike)."
        ),
        {},
        {
            "api_key_id": _param(_AGENT_ID),
            "date_from": _param("Only rows at or after this ISO 8601 moment, e.g. 2026-10-17T00:00:00Z."),
            "date_to": _param("Only rows before this ISO 8601 moment."),
            "feedback": _param("like or dislike: only turns rated this way."),
            "event_type": _param("One of chat, schedule, webhook, workflow, system, search, graph."),
            "level": _param("One of info, warning, error."),
            "search": _param("Text the question must contain."),
            "conversation_id": _param("Only the turns of this conversation."),
            "page": _param("Page number, from 1.", type_="integer"),
            "page_size": _param("Rows per page, up to 100.", type_="integer"),
        },
    ),
    (
        "get_feedback_counts",
        "POST",
        "/api/get_feedback_analytics",
        "Count likes and dislikes over a period, per hour or day.",
        {},
        {"api_key_id": _param(_AGENT_ID), "filter_option": _param(_PERIOD)},
    ),
    (
        "get_message_counts",
        "POST",
        "/api/get_message_analytics",
        "Count messages over a period, per hour or day.",
        {},
        {"api_key_id": _param(_AGENT_ID), "filter_option": _param(_PERIOD)},
    ),
    (
        "get_conversation",
        "GET",
        "/api/get_single_conversation",
        "Read a whole conversation by its id: every question, answer and rating, and its passthrough values.",
        {"id": _param("The conversation id, from a log row.", required=True)},
        {},
    ),
    (
        "get_trace",
        "GET",
        "/api/traces",
        "Read the execution trace of one answer (retrieval, model calls, tool calls) by its message id.",
        {
            "message_id": _param("The message id, from a log row.", required=True),
            "api_key_id": _param(_AGENT_ID),
        },
        {},
    ),
)


def _token_may_call(method: str, path: str, scopes: list[str], resource_filter: dict) -> bool:
    rule = RULES.get((path, method))
    if rule is None:
        return False
    if rule.scopes and not set(rule.scopes) & expand_scopes(scopes):
        return False
    return not set(rule.blocked_by) & set(resource_filter or {})


def build_actions(base_url: str, token: str, scopes: list[str], resource_filter: Optional[dict]) -> dict[str, Any]:
    """The API tool ``actions`` for a token: the catalog entries it may call.

    Args:
        base_url: Where the DocsGPT API is reached, e.g. ``https://docs.example.com``.
        token: The token's plaintext secret, sent as a Bearer header.
        scopes: The token's scopes.
        resource_filter: The token's resource filter.

    Returns:
        ``{action name: action}`` in the API tool config shape; empty when the
        token can call none of them.
    """
    root = base_url.rstrip("/")
    actions: dict[str, Any] = {}
    for name, method, path, description, query, body in CATALOG:
        if not _token_may_call(method, path, scopes, resource_filter or {}):
            continue
        actions[name] = {
            "name": name,
            "url": f"{root}{path}",
            "method": method,
            "description": description,
            "query_params": {"type": "object", "properties": {k: dict(v) for k, v in query.items()}},
            "headers": {
                "type": "object",
                "properties": {
                    "Authorization": {
                        "type": "string",
                        "description": "DocsGPT personal access token",
                        "value": f"Bearer {token}",
                        "filled_by_llm": False,
                        "required": True,
                    }
                },
            },
            "body": {"type": "object", "properties": {k: dict(v) for k, v in body.items()}},
            "body_content_type": "application/json",
            "active": True,
        }
    return actions
