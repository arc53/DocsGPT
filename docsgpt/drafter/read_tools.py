"""The drafter's read tools: detail the workspace overview leaves out.

Every tool answers for the :class:`~docsgpt.drafter.catalog.Workspace` read
for the caller at the start of the turn, so it can only return what the caller
may attach, and none has side effects. The overview holds names and a line of
meta; the detail is read from the database while the turn runs, for the one
row a tool is asked about, and kept for the rest of the turn: a prompt's text
(``get_prompt``), a tool's actions (``get_tool``), a source's file tree
(``get_source``). Built-in prompts and tools answer from memory. The Insights
reads (``get_gap_examples``, ``get_conversations``) go through the workspace's
``insights_reader``, built for the one agent the caller may edit, and return a
few capped rows of its conversations.
Results go back to the model fenced as data; a result's ``shown`` is what the
panel lists as read (``read`` event) and is not sent to the model.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from docsgpt.drafter.catalog import is_template, prompt_text, row_of, source_files, tool_detail, Workspace
from docsgpt.drafter.fencing import clean_text
from docsgpt.storage.db.repositories.conversation_labels import LOG_LABELS, SUMMARY_GAP_TYPES

logger = logging.getLogger(__name__)

ReadTool = Callable[[Workspace, dict], dict]


def _id_arg(args: dict, key: str) -> str:
    """The id argument ``key``, stripped; ``""`` when missing or not a string."""
    value = args.get(key) if isinstance(args, dict) else None
    return value.strip() if isinstance(value, str) else ""


def get_prompt(ws: Workspace, args: dict) -> dict:
    """A prompt's full text by id (a built-in prompt by name), marked when it is a template."""
    prompt_id = _id_arg(args, "prompt_id")
    row = row_of(ws, "prompts", prompt_id)
    text = prompt_text(ws, prompt_id)
    if text is None:
        return {"error": "This prompt's text could not be read right now. Go by its name." if row
                else "No prompt with that id in the workspace."}
    out = {"id": prompt_id, "name": (row or {}).get("name", prompt_id), "content": text}
    if is_template(text):
        out["template"] = True
    return out


def get_source(ws: Workspace, args: dict) -> dict:
    """A source's details: its catalog row, how many files it lists and up to 50 of their paths.

    A workspace that caps the turn's source reads (``source_reads_left``, the agent recipe's improve mode) counts
    each read down and refuses the ones past it.
    """
    source_id = _id_arg(args, "source_id")
    row = row_of(ws, "sources", source_id)
    if row is None:
        return {"error": "No source with that id in the workspace."}
    left = getattr(ws, "source_reads_left", None)
    if left is not None:
        if left <= 0:
            return {"error": "You have read enough sources for this turn: draft from what you read."}
        ws.source_reads_left = left - 1
    files = source_files(ws, source_id)
    if files is None:
        return {"error": "This source's files could not be read right now. Go by its name."}
    return {**row, **files}


def get_tool(ws: Workspace, args: dict) -> dict:
    """A tool's actions with their descriptions and the parameters the model fills."""
    tool_id = _id_arg(args, "tool_id")
    row = row_of(ws, "tools", tool_id)
    detail = tool_detail(ws, tool_id) if row else None
    if detail is None:
        return {"error": "This tool's actions could not be read right now. Go by its name and description." if row
                else "No tool with that id in the workspace."}
    return detail


#: Characters of a topic argument.
_TOPIC_CHARS = 200
_NO_INSIGHTS = {"error": "This agent's Insights can't be read here."}
_READ_FAILED = {"error": "Insights could not be read right now. Go by the summary."}


def _topic_arg(args: dict) -> Optional[str]:
    """The optional ``topic`` argument, cleaned; None when missing or empty."""
    value = args.get("topic") if isinstance(args, dict) else None
    return clean_text(value, _TOPIC_CHARS) or None


def get_gap_examples(ws: Workspace, args: dict) -> dict:
    """Up to five questions of the agent's users that were one gap type (in one topic), the likeliest first."""
    reader = getattr(ws, "insights_reader", None)
    if reader is None:
        return dict(_NO_INSIGHTS)
    gap_type = _id_arg(args, "gap_type")
    if gap_type not in SUMMARY_GAP_TYPES:
        return {"error": f"gap_type is one of: {', '.join(SUMMARY_GAP_TYPES)}."}
    try:
        questions = reader.gap_examples(gap_type, _topic_arg(args))
    except Exception:
        logger.warning("drafter: could not read gap examples", exc_info=True)
        return dict(_READ_FAILED)
    return {"questions": questions, "shown": list(questions)}


def get_conversations(ws: Workspace, args: dict) -> dict:
    """Up to five question-and-answer excerpts of the agent's conversations the Logs filter ``label`` selects."""
    reader = getattr(ws, "insights_reader", None)
    if reader is None:
        return dict(_NO_INSIGHTS)
    label = _id_arg(args, "label")
    if label not in LOG_LABELS:
        return {"error": f"label is one of: {', '.join(LOG_LABELS)}."}
    try:
        conversations = reader.conversations(label, _topic_arg(args))
    except Exception:
        logger.warning("drafter: could not read conversations", exc_info=True)
        return dict(_READ_FAILED)
    return {"conversations": conversations, "shown": [c["question"] for c in conversations if c["question"]]}


def _insights_schema(name: str, description: str, param: str, values: tuple[str, ...], param_description: str
                     ) -> dict:
    """An Insights read tool's definition: one required choice and an optional topic."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    param: {"type": "string", "enum": list(values), "description": param_description},
                    "topic": {"type": "string",
                              "description": "Optional: a topic from the gap summary, exactly as it is named there."},
                },
                "required": [param],
            },
        },
    }


def _schema(name: str, description: str, param: str, param_description: str) -> dict:
    """A read tool's definition: one required string parameter."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {param: {"type": "string", "description": param_description}},
                "required": [param],
            },
        },
    }


#: name -> (tool definition, implementation)
READ_TOOLS: dict[str, tuple[dict, ReadTool]] = {
    "get_prompt": (
        _schema("get_prompt", "Read a prompt's full text. Use it before reusing or changing a prompt, but not a "
                "prompt whose whole text the form data already holds (its content is there).",
                "prompt_id", "The prompt's id from the workspace (default, creative, strict or a uuid)."),
        get_prompt,
    ),
    "get_source": (
        _schema("get_source", "List a knowledge source's files, to judge what it covers.",
                "source_id", "The source's id from the workspace."),
        get_source,
    ),
    "get_tool": (
        _schema("get_tool", "Read a tool's actions and what each one does.",
                "tool_id", "The tool's id from the workspace."),
        get_tool,
    ),
    "get_gap_examples": (
        _insights_schema("get_gap_examples", "Read up to 5 questions the agent's users asked that had this gap, "
                         "the likeliest first. Read only the gaps you will act on.",
                         "gap_type", SUMMARY_GAP_TYPES, "The gap type, as in the gap summary."),
        get_gap_examples,
    ),
    "get_conversations": (
        _insights_schema("get_conversations", "Read up to 5 of the agent's answered questions that Logs marks "
                         "with this label, each with the start of its answer.",
                         "label", tuple(LOG_LABELS), "docs_gap: the docs don't cover it; not_answered; "
                         "negative_reaction, negative_sentiment, frustrated, asks_human: how the user reacted."),
        get_conversations,
    ),
}


def tool_definitions(names: tuple[str, ...]) -> list[dict]:
    """The tool definitions for ``names``, in order."""
    return [READ_TOOLS[name][0] for name in names if name in READ_TOOLS]


def run_read_tool(name: str, ws: Workspace, args: Any, offered: Optional[tuple[str, ...]] = None) -> dict:
    """Run one read tool; an unknown tool or bad arguments come back as ``{"error"}``.

    Args:
        name: The tool the model called.
        ws: The caller's workspace.
        args: The call's arguments.
        offered: The tools the turn offered (the recipe's ``read_tools``); any other is unknown. None allows all.
    """
    entry = READ_TOOLS.get(name)
    if entry is None or (offered is not None and name not in offered):
        return {"error": f"Unknown tool {name!r}."}
    return entry[1](ws, args if isinstance(args, dict) else {})
