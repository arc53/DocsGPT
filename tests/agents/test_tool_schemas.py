"""The schema every built-in tool action shows the model.

``ToolExecutor._build_tool_parameters`` turns an action's parameter schema
into the function schema the LLM sees, so a mistake there changes every
tool at once. The golden file pins the shape of each built-in action's
schema (types, enums, required lists, nested properties; not the prose), so
a converter change can't move a tool's required set unnoticed.

Regenerate the golden after a deliberate schema change::

    python -m tests.agents.test_tool_schemas --write
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

GOLDEN = Path(__file__).parent / "golden" / "tool_schemas.json"

#: Tools whose actions come from their stored config (an MCP server, an imported API), not from code.
_CONFIG_DEFINED = frozenset({"mcp_tool", "api_tool"})


def shape(schema: Any) -> Any:
    """The structural part of a JSON schema: types, enums, required lists and nesting; no descriptions."""
    if not isinstance(schema, dict):
        return schema
    out: Dict[str, Any] = {}
    for key in ("type", "enum", "required"):
        if key in schema:
            out[key] = schema[key]
    if isinstance(schema.get("properties"), dict):
        out["properties"] = {name: shape(sub) for name, sub in schema["properties"].items()}
    if isinstance(schema.get("items"), dict):
        out["items"] = shape(schema["items"])
    return out


def builtin_schemas() -> Dict[str, Any]:
    """``{"<module>.<action>": shape}`` for every action of every code-defined tool."""
    # Imported first so the tool modules load in the order the app loads them.
    import docsgpt.agents.tool_executor  # noqa: F401
    import docsgpt.agents.tools as tools_pkg
    from docsgpt.agents.tool_executor import ToolExecutor
    from docsgpt.agents.tools.base import Tool

    executor = ToolExecutor()
    out: Dict[str, Any] = {}
    for _finder, name, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if name == "base" or name.startswith("_") or name in _CONFIG_DEFINED:
            continue
        module = importlib.import_module(f"docsgpt.agents.tools.{name}")
        for _member, cls in inspect.getmembers(module, inspect.isclass):
            if not issubclass(cls, Tool) or cls is Tool or cls.__module__ != module.__name__:
                continue
            try:
                tool = cls({}, "schema-test-user")
            except TypeError:
                tool = cls({})
            for action in tool.get_actions_metadata():
                out[f"{name}.{action['name']}"] = shape(executor._build_tool_parameters(action))
    return dict(sorted(out.items()))


@pytest.mark.unit
class TestBuildToolParameters:
    def _build(self, action, hidden=None):
        from docsgpt.agents.tool_executor import ToolExecutor

        return ToolExecutor()._build_tool_parameters(action, hidden=hidden)

    def test_the_sections_required_list_decides(self):
        params = self._build(
            {
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["q"],
                }
            }
        )
        assert params["required"] == ["q"]

    def test_an_object_parameter_keeps_its_nested_required_and_stays_optional(self):
        params = self._build(
            {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "filter": {
                            "type": "object",
                            "properties": {"field": {"type": "string"}},
                            "required": ["field"],
                        },
                    },
                    "required": ["name"],
                }
            }
        )
        assert params["required"] == ["name"]
        assert params["properties"]["filter"]["required"] == ["field"]

    def test_a_required_flag_on_the_parameter_still_counts(self):
        """Imported API actions mark each parameter ``required: true`` (spec_parser)."""
        params = self._build(
            {
                "query_params": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "required": True, "filled_by_llm": True, "value": ""},
                        "page": {"type": "integer", "required": False, "filled_by_llm": True, "value": ""},
                    },
                }
            }
        )
        assert params["required"] == ["id"]
        assert "required" not in params["properties"]["id"]
        assert "required" not in params["properties"]["page"]

    def test_a_listed_parameter_the_model_does_not_fill_is_left_out(self):
        action = {
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "filled_by_llm": False, "value": "42"},
                    "text": {"type": "string"},
                },
                "required": ["chat_id", "text"],
            }
        }
        assert self._build(action)["required"] == ["text"]
        assert self._build(action, hidden={"text"})["required"] == []

    def test_monitor_create_requires_only_what_its_action_lists(self):
        from docsgpt.agents.tools.monitor import MonitorTool

        create = MonitorTool({}, "u1").get_actions_metadata()[0]
        params = self._build(create)
        assert params["required"] == ["description", "source", "on_match"]
        assert params["properties"]["source"]["required"] == ["type"]
        assert params["properties"]["check"]["required"] == ["type"]


@pytest.mark.unit
def test_builtin_tool_schemas_match_the_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = builtin_schemas()
    assert sorted(current) == sorted(golden), "a built-in tool action was added or removed; regenerate the golden"
    changed = [key for key in current if current[key] != golden[key]]
    assert not changed, f"LLM-facing schema changed for: {changed}; regenerate the golden if this is deliberate"


if __name__ == "__main__":  # pragma: no cover - golden regeneration
    if "--write" not in sys.argv:
        raise SystemExit("usage: python -m tests.agents.test_tool_schemas --write")
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(builtin_schemas(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN}")
