"""ask_user: the chat model asks the user up to three clarifying questions.

A synthetic tool (no ``user_tools`` row) the server attaches to an interactive
chat turn by itself (``add_ask_user_tool`` from ``BaseAgent._prepare_tools``);
it is never listed, picked or toggled. Only a client that draws question forms
gets it (the request's ``capabilities``, :mod:`docsgpt.agents.client_capabilities`);
headless runs, workflow nodes, research steps and every other caller never do.

The turn pauses (``awaiting_answer``) and resumes with the answer the client
sends back (``ToolExecutor.check_pause``). The executor runs it, so this module
only holds the tool's description and the texts the model reads.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional

from docsgpt.agents.questions import CHAT_QUESTIONS_SCHEMA, MAX_QUESTIONS
from docsgpt.agents.tools.base import Tool

ASK_USER_TOOL_ID = "ask_user"
ASK_USER = "ask_user"

#: How a turn shows questions (``ToolExecutor.questions``): as cards the client draws.
CARDS = "cards"
#: The modes a turn (or its paused state) may hold; anything else offers no questions.
QUESTION_MODES = frozenset({CARDS})

#: The pause type of a turn waiting for the user to answer its questions.
AWAITING_ANSWER = "awaiting_answer"

#: What ``check_pause`` returns for question cards an output control blocked:
#: nothing is shown or kept, and the turn ends on the block.
QUESTIONS_BLOCKED = "questions_blocked"

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


def is_awaiting_answer(call: Any) -> bool:
    """Whether a pending call is paused on questions for the user.

    Args:
        call: A pending call (anything; only a dict can be one).

    Returns:
        Whether its ``pause_type`` is :data:`AWAITING_ANSWER`.
    """
    return isinstance(call, Mapping) and call.get("pause_type") == AWAITING_ANSWER


def question_payload(call: Mapping[str, Any]) -> Dict[str, Any]:
    """The cards a paused ``ask_user`` call shows: ``{"message", "questions"}``.

    A paused call holds them once, as its ``arguments`` (the screened cards).
    A call saved before that carries them beside the arguments too, and that
    copy is read first: the oldest such rows kept the model's own arguments.

    Args:
        call: The pending call (``awaiting_answer``).

    Returns:
        The lead-in line (or None) and the normalized questions.
    """
    if "questions" in call:
        message, questions = call.get("message"), call.get("questions")
    else:
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, Mapping) else {}
        message, questions = arguments.get("message"), arguments.get("questions")
    return {"message": message, "questions": questions or []}


def client_pending_call(call: Any) -> Any:
    """A pending call as clients receive it (``tool_calls_pending``).

    A call waiting on questions also carries ``message`` and ``questions``
    beside its arguments, as the API documents; any other call is unchanged.

    Args:
        call: The pending call as the pause keeps it.

    Returns:
        The call to send.
    """
    if not is_awaiting_answer(call):
        return call
    return {**call, **question_payload(call)}


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
                    "That includes a request that needs the user's own specifics: rather than writing a template "
                    "full of placeholders to fill in (\"write me a shipping policy\" without the regions, times "
                    "or costs), ask for them. Never ask for small talk or about something already clear. Ask "
                    "with this tool, never as questions written in your answer. Give each question 2-5 short "
                    "options (the user can always type their own), or none for something only the user can "
                    "type. Set multi when more than one option can apply, instead of an option like \"Several "
                    "of these\". An option that needs a detail typed gets an input instead of asking to type, "
                    "as in {\"label\": \"Another city\", \"input\": \"City name\"}; "
                    "never invent contact details as options. Call it alone, with no other tool call in the same "
                    "round, and write nothing else in that turn: the user's reply comes back to you. One round "
                    "of questions per user message."
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
