"""The drafter's read tools: detail the compact workspace catalog leaves out.

Each is a lookup in the :class:`~docsgpt.drafter.catalog.Workspace` loaded for
the caller before the draft started, so a tool can only return what the
caller may open, and never touches the database or anything with side
effects. Results go back to the model fenced as data.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from docsgpt.drafter.catalog import Workspace

ReadTool = Callable[[Workspace, dict], dict]


def _id_arg(args: dict, key: str) -> str:
    """The id argument ``key``, stripped; ``""`` when missing or not a string."""
    value = args.get(key) if isinstance(args, dict) else None
    return value.strip() if isinstance(value, str) else ""


def get_prompt(ws: Workspace, args: dict) -> dict:
    """A prompt's full text by id (a built-in prompt by name)."""
    prompt_id = _id_arg(args, "prompt_id")
    text = ws.prompt_texts.get(prompt_id)
    if text is None:
        return {"error": "No prompt with that id in the workspace."}
    row = next((p for p in ws.prompts if p["id"] == prompt_id), {})
    return {"id": prompt_id, "name": row.get("name", prompt_id), "content": text}


def get_source(ws: Workspace, args: dict) -> dict:
    """A source's details: its catalog row and up to 50 of its file paths."""
    source_id = _id_arg(args, "source_id")
    row = next((s for s in ws.sources if s["id"] == source_id), None)
    if row is None:
        return {"error": "No source with that id in the workspace."}
    return {**row, "file_paths": ws.source_files.get(source_id, [])}


def get_tool(ws: Workspace, args: dict) -> dict:
    """A tool's actions with their descriptions and the parameters the model fills."""
    tool_id = _id_arg(args, "tool_id")
    detail = ws.tool_details.get(tool_id)
    if detail is None or not any(t["id"] == tool_id for t in ws.tools):
        return {"error": "No tool with that id in the workspace."}
    return detail


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
        _schema("get_prompt", "Read a prompt's full text. Use it before reusing or changing a prompt.",
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
