"""ask_user: the chat model asks the user up to three clarifying questions.

A synthetic tool (no ``user_tools`` row) the server attaches to an interactive
chat turn by itself (``add_ask_user_tool`` from ``BaseAgent._prepare_tools``);
it is never listed, picked or toggled. Headless runs, workflow nodes and
research steps never get it.

The request decides how the questions show (``ToolExecutor.questions``):

* ``cards``: the turn pauses (``awaiting_answer``) and resumes with the answer
  the client sends back (``ToolExecutor.check_pause``).
* ``text``: the questions become the turn's answer as markdown and the turn
  ends; the user's next message is the answer (``ToolExecutor._ask_user_as_text``).

The executor runs both, so this module only holds the tool's description and
the texts the model reads.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from docsgpt.agents.questions import CHAT_QUESTIONS_SCHEMA, MAX_QUESTIONS
from docsgpt.agents.tools.base import Tool

ASK_USER_TOOL_ID = "ask_user"
ASK_USER = "ask_user"

#: The request's ``questions`` value that asks for question cards.
CARDS = "cards"
#: Every other interactive caller gets the questions as text.
TEXT = "text"
QUESTION_MODES = frozenset({CARDS, TEXT})

#: The pause type of a turn waiting for the user to answer its questions.
AWAITING_ANSWER = "awaiting_answer"

#: The tool result when the questions were shown as the turn's answer.
SHOWN_AS_TEXT = "Shown to the user as text; their next message is the answer."

#: The tool result when the user chose to skip the questions.
SKIPPED_TEXT = (
    "The user skipped the questions. Go ahead with your best assumptions and say briefly what you assumed."
)

#: The tool result of a second question round in one user message.
ONE_ROUND_TEXT = (
    "Not asked: you already asked the user in this turn. Don't ask again; answer now with your best "
    "assumptions and say briefly what you assumed."
)

#: The tool result of an ``ask_user`` call made beside other tool calls.
NOT_ALONE_TEXT = (
    "Not asked: ask_user must be the only tool call in its round (the other calls ran). If you still need "
    "to ask, call ask_user again on its own; otherwise answer."
)

#: The tool result where the caller can't be asked (should not happen: the tool is not attached there).
UNAVAILABLE_TEXT = "Not asked: questions can't be shown here. Answer with your best assumptions."


def questions_mode(value: Any) -> str:
    """How an interactive request shows questions: ``cards`` only when it asks for them.

    Args:
        value: The request's ``questions`` field.

    Returns:
        :data:`CARDS` or :data:`TEXT`.
    """
    return CARDS if value == CARDS else TEXT


def add_ask_user_tool(tools_dict: Dict[str, Any], enabled: bool) -> bool:
    """Attach ask_user to a turn's tools, or take it off.

    A saved ``ask_user`` entry (a paused turn's tools come back with it) is
    always replaced or removed, so only this turn's rules decide.

    Args:
        tools_dict: The turn's tools; mutated in place.
        enabled: Whether this turn offers questions.

    Returns:
        Whether the tool is in ``tools_dict`` now.
    """
    for key in [k for k, t in tools_dict.items() if isinstance(t, dict) and t.get("name") == ASK_USER
                and not t.get("client_side")]:
        del tools_dict[key]
    if not enabled:
        return False
    tools = [t for t in tools_dict.values() if isinstance(t, dict)]
    # A client tool or MCP action of the same name keeps it.
    if any(a.get("name") == ASK_USER for t in tools for a in t.get("actions") or [] if isinstance(a, dict)):
        return False
    actions = [{**meta, "active": True} for meta in AskUserTool().get_actions_metadata()]
    tools_dict[ASK_USER_TOOL_ID] = {"id": ASK_USER_TOOL_ID, "name": ASK_USER, "actions": actions, "config": {}}
    return True


def invalid_text(problems: List[str], last_try: bool) -> str:
    """The tool result for questions that can't be shown.

    Args:
        problems: What is wrong, addressed to the model.
        last_try: The model already had its corrected try.

    Returns:
        The text.
    """
    what = "; ".join(problems)
    if last_try:
        return (
            f"Not asked: the questions still can't be shown ({what}). Don't try again; answer now with your "
            "best assumptions and say briefly what you assumed."
        )
    return f"Not asked: the questions can't be shown ({what}). Fix them and call ask_user again, or answer."


class AskUserTool(Tool):
    """Ask User

    Asks the user a few clarifying questions in the chat.
    """

    internal = True

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": ASK_USER,
                "description": (
                    f"Ask the user up to {MAX_QUESTIONS} short clarifying questions, then stop. Ask only when your "
                    "answer would be materially different depending on something neither the conversation nor "
                    "the sources settle; otherwise answer with a sensible assumption and say what you assumed. "
                    "Never ask for small talk or about something already clear. Give each question 2-5 short "
                    "options (the user can always type their own), or none for something only the user can "
                    "type. An option that needs a detail typed gets an input instead of asking to type; never "
                    "invent contact details as options. Call it alone, with no other tool call in the same round, and write nothing else in "
                    "that turn: the user's reply comes back to you. One round of questions per user message."
                ),
                "parameters": copy.deepcopy(CHAT_QUESTIONS_SCHEMA),
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        return {}

    def execute_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        # The executor answers ask_user itself (it pauses the turn or ends it
        # with the questions); a call never reaches the tool.
        return {"status": "error", "error": "ask_user runs only inside a chat turn."}
