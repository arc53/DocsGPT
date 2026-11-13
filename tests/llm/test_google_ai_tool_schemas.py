"""GoogleLLM tool schemas through the real google-genai types.

The converter must keep nested objects whole: every property name, its
``required`` list and its array ``items``, at any depth. These tests run the
drafter's own tool definitions and a generic nested schema through
``_clean_tools_format`` and read the result back off the ``types.Schema``
that would be sent to Gemini (no request is made).
"""

import pytest

from docsgpt.drafter import agent_recipe, prompt_recipe, topics_recipe  # noqa: F401  (registers the recipes)
from docsgpt.drafter.read_tools import tool_definitions
from docsgpt.drafter.recipe import _RECIPES
from docsgpt.drafter.runner import _terminal_definitions
from docsgpt.llm.google_ai import GoogleLLM


@pytest.fixture
def llm() -> GoogleLLM:
    """A GoogleLLM without a client: the schema converter needs none."""
    return GoogleLLM.__new__(GoogleLLM)


def _shape(schema: dict) -> dict:
    """The structure of a JSON schema: property names, required lists and items, recursively."""
    out: dict = {}
    if schema.get("properties"):
        out["properties"] = {name: _shape(sub) for name, sub in schema["properties"].items()}
    if schema.get("required"):
        out["required"] = list(schema["required"])
    if isinstance(schema.get("items"), dict):
        out["items"] = _shape(schema["items"])
    return out


def _converted(llm: GoogleLLM, tool: dict) -> dict:
    """The parameters Gemini would receive for ``tool``, dumped back to JSON-schema keys."""
    (genai_tool,) = llm._clean_tools_format([tool])
    params = genai_tool.function_declarations[0].parameters
    return params.model_dump(exclude_none=True, by_alias=True, mode="json")


def _drafter_tools() -> list[tuple[str, dict]]:
    tools = []
    for recipe_id, recipe in _RECIPES.items():
        for tool in tool_definitions(recipe.read_tools) + _terminal_definitions(recipe, True):
            tools.append((f"{recipe_id}:{tool['function']['name']}", tool))
    return tools


@pytest.mark.unit
@pytest.mark.parametrize("label,tool", _drafter_tools(), ids=[label for label, _ in _drafter_tools()])
def test_drafter_tool_keeps_its_whole_shape(llm, label, tool):
    assert _shape(_converted(llm, tool)) == _shape(tool["function"]["parameters"])


@pytest.mark.unit
def test_drafter_recipes_are_registered():
    assert {"agent", "prompt", "topics"} <= set(_RECIPES)


@pytest.mark.unit
def test_nested_schema_keeps_property_names_types_and_required(llm):
    tool = {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": "Open a ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "body": {
                        "type": "object",
                        "title": "dropped",
                        "properties": {
                            "summary": {"type": "string", "description": "One line."},
                            "priority": {"type": "string", "enum": ["low", "high"]},
                            "labels": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}, "color": {"type": "string"}},
                                    "required": ["name", "missing"],
                                },
                            },
                        },
                        "required": ["summary"],
                    },
                },
                "required": ["body"],
            },
        },
    }
    params = _converted(llm, tool)
    body = params["properties"]["body"]
    assert body["type"] == "OBJECT"
    assert "title" not in body
    assert set(body["properties"]) == {"summary", "priority", "labels"}
    assert body["required"] == ["summary"]
    assert body["properties"]["priority"] == {"type": "STRING", "enum": ["low", "high"]}
    label = body["properties"]["labels"]["items"]
    assert label["type"] == "OBJECT"
    assert set(label["properties"]) == {"name", "color"}
    assert label["required"] == ["name"]


@pytest.mark.unit
def test_property_named_like_a_keyword_is_kept(llm):
    schema = {
        "type": "object",
        "properties": {"format": {"type": "string"}, "title": {"type": "string"}},
        "required": ["format", "title"],
    }
    cleaned = llm._clean_schema(schema)
    assert set(cleaned["properties"]) == {"format", "title"}
    assert cleaned["required"] == ["format", "title"]


@pytest.mark.unit
def test_nullable_type_list_maps_to_nullable(llm):
    assert llm._clean_schema({"type": ["string", "null"]}) == {"type": "STRING", "nullable": True}


@pytest.mark.unit
def test_multi_type_list_maps_to_any_of(llm):
    cleaned = llm._clean_schema({"type": ["string", "number", "null"]})
    assert cleaned == {"anyOf": [{"type": "STRING"}, {"type": "NUMBER"}], "nullable": True}


@pytest.mark.unit
def test_any_of_and_one_of_are_cleaned_and_empty_branches_dropped(llm):
    cleaned = llm._clean_schema({
        "oneOf": [{"type": "string"}, {"type": "object", "properties": {"text": {"type": "string"}}}],
    })
    assert cleaned == {
        "anyOf": [{"type": "STRING"}, {"type": "OBJECT", "properties": {"text": {"type": "STRING"}}}],
    }
    assert llm._clean_schema({"type": "object", "anyOf": [{"required": ["a"]}]}) == {"type": "OBJECT"}


@pytest.mark.unit
def test_type_list_and_any_of_are_accepted_by_genai(llm):
    tool = {
        "type": "function",
        "function": {
            "name": "set_cell",
            "description": "Set a cell.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"anyOf": [{"type": ["string", "number", "null"]}, {"type": "object"}]},
                    "note": {"type": ["string", "null"]},
                },
            },
        },
    }
    params = _converted(llm, tool)
    assert params["properties"]["note"] == {"type": "STRING", "nullable": True}
    assert len(params["properties"]["value"]["anyOf"]) == 2
