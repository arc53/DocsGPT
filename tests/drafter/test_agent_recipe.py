"""The agent recipe: its instructions, and the server-side check of an agent proposal."""

from __future__ import annotations

import pytest

from docsgpt.drafter.agent_recipe import (
    AGENT_RECIPE,
    context_data,
    instructions,
    NAME_MAX,
    parse_context,
    validate,
)
from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, ProposalInvalid
from docsgpt.drafter.runner import build_messages

TOOL_ID = "11111111-1111-1111-1111-111111111111"
SOURCE_ID = "22222222-2222-2222-2222-222222222222"
PROMPT_ID = "33333333-3333-3333-3333-333333333333"


def _ws(**kwargs) -> Workspace:
    ws = Workspace(
        sources=[{"id": SOURCE_ID, "name": "Help Center"}],
        tools=[{"id": TOOL_ID, "name": "Tracking", "kind": "api_tool", "actions": []}],
        prompts=[{"id": p, "name": p, "kind": "built-in"} for p in ("default", "creative", "strict")]
        + [{"id": PROMPT_ID, "name": "Support", "kind": "own"}],
        prompt_texts={"default": "You are DocsGPT {{ system.date }}", PROMPT_ID: "You help customers."},
    )
    for key, value in kwargs.items():
        setattr(ws, key, value)
    return ws


def _req(form=None, *user_messages) -> DraftRequest:
    messages = [{"role": "user", "content": m} for m in (user_messages or ("Build me a support agent",))]
    return DraftRequest("alice", "agent", messages, parse_context({"form": form or {}}), "drafter:t")


def _validate(fields, form=None, ws=None, messages=(), **extra):
    args = {"message": "Done.", "fields": fields, **extra}
    return validate(args, _req(form, *messages), ws or _ws())


@pytest.mark.unit
class TestContext:
    def test_values_are_cleaned_and_capped(self):
        ctx = parse_context({
            "agent_id": " a1 ",
            "form": {"name": "N\x00ame", "sources": ["s1", "s1", 3, ""], "tools": "nope",
                     "prompt_id": "strict", "pending_prompt": {"name": "P", "content": "x"},
                     "starters": ["Hi", "", 5], "models": ["gpt"]},
        })
        assert ctx["agent_id"] == "a1"
        form = ctx["form"]
        assert form["name"] == "Name" and form["sources"] == ["s1"] and form["tools"] == []
        assert form["pending_prompt"] == {"name": "P", "content": "x"} and form["starters"] == ["Hi"]
        assert "models" not in form

    def test_a_form_that_is_not_an_object_is_refused(self):
        with pytest.raises(BadDraftRequest):
            parse_context({"form": ["x"]})

    def test_the_model_reads_a_custom_prompts_text_and_its_mode(self):
        data = context_data(_req({"prompt_id": PROMPT_ID}), _ws())
        assert data["prompt"] == {"kind": "existing", "id": PROMPT_ID, "content": "You help customers.",
                                  "mode": "persona"}
        data = context_data(_req({}), _ws())
        assert data["prompt"] == {"kind": "existing", "id": "default", "mode": "template"}
        assert data["agent_type"] == "classic"


@pytest.mark.unit
class TestInstructions:
    def test_key_rules_are_stated(self):
        text = instructions(_req(), _ws())
        for rule in (
            '"classic"', '"research"', "at most 200 characters", "up to 4",
            "Never set or mention changing models, guardrails",
            "looks internal", "no tool supports", "off-topic",
            "plain text with no {{ }} variables", "today's date", "reply in the user's language",
            "Never add {{ tools... }} variables unless the user asks",
            "keep its sections and {% if %} blocks",
            "change only what the user asked for",
            "The form is empty",
        ):
            assert rule in text, rule
        assert "{{ source.citation_rules }}" not in text

    def test_a_filled_form_is_a_change_request(self):
        assert "change request" in instructions(_req({"name": "Shipping help"}), _ws())
        assert "change request" in instructions(_req(), _ws(agent={"id": "a"}))

    def test_system_prompt_carries_the_recipe_and_the_tool_protocol(self):
        messages = build_messages(_req(), AGENT_RECIPE, _ws(), tool_mode=True, allow_questions=True)
        system = messages[0]["content"]
        assert "DocsGPT drafter" in system and "drafting an AI agent" in system
        assert "submit_proposal" in system and "never save" in system


@pytest.mark.unit
class TestValidate:
    def test_ids_the_caller_cannot_attach_are_dropped_and_reported(self):
        proposal = _validate({"sources": [SOURCE_ID, "foreign"], "tools": ["x", TOOL_ID],
                              "prompt": {"kind": "existing", "id": "someone-elses"}})
        assert proposal["fields"] == {"sources": [SOURCE_ID], "tools": [TOOL_ID]}
        assert proposal["dropped"] == [
            {"field": "sources", "id": "foreign", "reason": "not_found"},
            {"field": "tools", "id": "x", "reason": "not_found"},
            {"field": "prompt", "id": "someone-elses", "reason": "not_found"},
        ]

    def test_ids_already_on_the_form_are_kept(self):
        proposal = _validate({"tools": ["owners-tool", TOOL_ID]}, form={"tools": ["owners-tool"]})
        assert proposal["fields"]["tools"] == ["owners-tool", TOOL_ID] and proposal["dropped"] == []

    def test_unknown_fields_never_reach_the_form(self):
        proposal = _validate({"name": "Help", "models": ["gpt"], "guardrails": {}, "json_schema": {}})
        assert proposal["fields"] == {"name": "Help"}

    def test_unchanged_fields_are_left_out(self):
        form = {"name": "Help", "agent_type": "classic", "prompt_id": PROMPT_ID, "starters": ["Hi"]}
        proposal = _validate({"name": "Help", "agent_type": "classic", "starters": ["Hi"],
                              "prompt": {"kind": "existing", "id": PROMPT_ID}, "description": "New"},
                             form=form, reasons=[{"field": "name", "summary": "kept"},
                                                 {"field": "description", "summary": "Says what it does"}])
        assert proposal["fields"] == {"description": "New"}
        assert proposal["reasons"] == [{"field": "description", "summary": "Says what it does"}]

    def test_starters_are_normalised(self):
        proposal = _validate({"starters": [" Where is my parcel? ", "where is my parcel?", ""]})
        assert proposal["fields"]["starters"] == ["Where is my parcel?"]

    @pytest.mark.parametrize("fields", [
        {"starters": ["a", "b", "c", "d", "e"]},
        {"starters": ["x" * 201]},
        {"name": "x" * (NAME_MAX + 1)},
        {"name": "  "},
        {"description": "x" * 501},
        {"prompt": {"kind": "new", "name": "P", "content": ""}},
        {"prompt": {"kind": "new", "name": "P", "content": "Hello {{ broken"}},
    ])
    def test_fixable_problems_go_back_to_the_model(self, fields):
        with pytest.raises(ProposalInvalid):
            _validate(fields)

    def test_a_new_plain_prompt_is_kept_as_a_persona(self):
        content = "You answer shipping questions for Meridian.\n- Refunds: point to support@meridian.example."
        proposal = _validate({"prompt": {"kind": "new", "name": "Shipping help", "content": content}})
        assert proposal["fields"]["prompt"] == {"kind": "new", "name": "Shipping help", "content": content}
        assert proposal["notes"] == []

    def test_switching_to_a_template_is_noted(self):
        proposal = _validate({"prompt": {"kind": "new", "name": "P", "content": "Today is {{ system.date }}."}},
                             form={"prompt_id": PROMPT_ID})
        assert any("template variables" in note for note in proposal["notes"])

    def test_tool_variables_need_the_users_ask(self):
        fields = {"prompt": {"kind": "new", "name": "P", "content": "Memory: {{ tools.memory.memory_view }}"}}
        with pytest.raises(ProposalInvalid, match="tools"):
            _validate(fields)
        asked = _validate(fields, messages=("Put {{ tools.memory.memory_view }} in the prompt",))
        assert asked["fields"]["prompt"]["content"].startswith("Memory:")

    def test_tool_variables_already_in_the_template_are_kept(self):
        template = "Hi {% if tools.memory.memory_view %}{{ tools.memory.memory_view }}{% endif %}"
        ws = _ws(prompt_texts={"default": template})
        proposal = _validate({"prompt": {"kind": "new", "name": "Copy", "content": template + " Be brief."}},
                             ws=ws)
        assert proposal["fields"]["prompt"]["name"] == "Copy"
