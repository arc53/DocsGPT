"""The prompt recipe: improving a prompt with checked edits, writing a new one, and its no-questions turn."""

from __future__ import annotations

import pytest

from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.prompt_recipe import (
    context_data,
    instructions,
    MAX_EDITS,
    parse_context,
    PROMPT_RECIPE,
    scope_to_agent,
    validate,
)
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, get_recipe, ProposalInvalid
from docsgpt.drafter.runner import build_messages, run_draft
from docsgpt.prompts.composer import compose_preset
from tests.drafter.fakes import calls, FakeLLM, tool_call

PERSONA = (
    "You answer customer questions for Meridian Freight Group.\n"
    "Use the context below to answer. Today is a good day.\n"
    "Be polite and concise."
)
MODEL = {"id": "m", "display_name": "M", "supports_tools": True}


def _req(mode="improve", content=PERSONA, agent=None, *user_messages, name="Support reply") -> DraftRequest:
    messages = [{"role": "user", "content": m} for m in (user_messages or ("Stop it from making up prices",))]
    context = parse_context({"mode": mode, "prompt": {"id": "p1", "name": name, "content": content},
                             "agent": agent})
    return DraftRequest("alice", "prompt", messages, context, "drafter:t")


def _improve(edits, content=PERSONA, agent=None, messages=(), **extra):
    args = {"message": "Done.", "edits": edits, **extra}
    return validate(args, _req("improve", content, agent, *messages), Workspace())


def _edit(find, replace, reason="Because."):
    return {"find": find, "replace": replace, "reason": reason}


@pytest.mark.unit
class TestContext:
    def test_values_are_cleaned(self):
        ctx = parse_context({
            "mode": "improve",
            "prompt": {"id": " p1 ", "name": "Sup\x00port", "content": "Hi\r\nthere"},
            "agent": {"sources": ["s1", "s1", 3], "tools": "nope", "agent_type": "research", "models": ["x"]},
        })
        assert ctx["prompt"] == {"id": "p1", "name": "Support", "content": "Hi\nthere"}
        assert ctx["agent"] == {"sources": ["s1"], "tools": [], "agent_type": "research"}

    def test_no_agent_is_none(self):
        assert parse_context({"mode": "write", "prompt": {"name": "", "content": ""}})["agent"] is None

    @pytest.mark.parametrize("raw", [
        {"mode": "rewrite", "prompt": {"content": "x"}},
        {"mode": "improve", "prompt": {"content": "   "}},
        {"mode": "improve"},
        {"mode": "write", "prompt": ["x"]},
        {"mode": "write", "prompt": {"content": "x"}, "agent": "a1"},
    ])
    def test_unusable_contexts_are_refused(self, raw):
        with pytest.raises(BadDraftRequest):
            parse_context(raw)

    def test_the_model_reads_the_prompt_and_its_mode(self):
        data = context_data(_req(agent={"sources": [], "tools": [], "agent_type": "classic"}), Workspace())
        assert data["mode"] == "improve"
        assert data["prompt"] == {"name": "Support reply", "content": PERSONA, "kind": "persona"}
        assert data["agent"] == {"agent_type": "classic"}
        assert context_data(_req(content="Hi {{ system.date }}"), Workspace())["prompt"]["kind"] == "template"
        assert "agent" not in context_data(_req(), Workspace())

    def test_the_workspace_keeps_only_the_agents_knowledge_and_tools(self):
        ws = Workspace(
            sources=[{"id": "s1", "name": "Help"}, {"id": "s2", "name": "Contracts"}],
            tools=[{"id": "t1", "name": "Tracking", "actions": []}, {"id": "t2", "name": "Mail", "actions": []}],
            prompts=[{"id": "p", "name": "P"}], models=[{"id": "m", "name": "M"}],
            prompt_texts={"p": "x"}, hidden={"sources": 3},
        )
        scoped = scope_to_agent(ws, {"sources": ["s2", "foreign"], "tools": ["t1"], "agent_type": "classic"})
        assert [s["id"] for s in scoped.sources] == ["s2"] and [t["id"] for t in scoped.tools] == ["t1"]
        assert scoped.prompts == [] and scoped.models == [] and scoped.hidden == {}
        assert scoped.counts() == {"sources": 1, "tools": 1, "prompts": 0, "models": 0}


@pytest.mark.unit
class TestInstructions:
    def test_key_rules_are_stated(self):
        text = instructions(_req(), Workspace())
        for rule in (
            "exactly once", "must not overlap", "'' deletes", "anchor",
            "plain text with no {{ }} variables", "today's date",
            "Never add {{ tools... }} variables unless the user asks",
            "keep its sections and {% if %} blocks", "{{ source.citation_rules }}",
            "change only what the user asked for", "{{ passthrough.",
        ):
            assert rule in text, rule

    def test_write_mode_asks_for_a_persona(self):
        text = instructions(_req("write", ""), Workspace())
        assert "Write a new prompt" in text and "name" in text
        assert "exactly once" not in text

    def test_the_turn_offers_no_questions(self):
        assert PROMPT_RECIPE.questions is False
        system = build_messages(_req(), PROMPT_RECIPE, Workspace(), tool_mode=True, allow_questions=False)[0]
        assert "submit_proposal" in system["content"] and "ask_user" not in system["content"]
        assert "asked enough questions" not in system["content"]

    def test_it_is_registered(self):
        assert get_recipe("prompt") is PROMPT_RECIPE


@pytest.mark.unit
class TestImprove:
    def test_edits_are_applied_in_text_order(self):
        proposal = _improve([
            _edit("Be polite and concise.", "Be polite and concise. Never quote a price.", "You asked."),
            _edit("Use the context below to answer. Today is a good day.\n", "", "DocsGPT adds the date."),
        ])
        assert proposal["mode"] == "improve"
        assert [e["id"] for e in proposal["edits"]] == ["e1", "e2"]
        assert proposal["edits"][0]["find"].startswith("Use the context")
        assert proposal["result"] == (
            "You answer customer questions for Meridian Freight Group.\n"
            "Be polite and concise. Never quote a price."
        )
        assert proposal["template_mode"] == {"before": False, "after": False}
        assert proposal["checks"] == [] and proposal["warnings"] == []

    def test_a_find_that_is_missing_goes_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match="not found"):
            _improve([_edit("Be rude.", "Be kind.")])

    def test_a_find_that_occurs_twice_goes_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match="2 times"):
            _improve([_edit("o", "O")], content="one two")

    def test_overlapping_edits_go_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match="overlap"):
            _improve([_edit("Be polite", "Be warm"), _edit("polite and concise", "brief")])

    def test_no_op_edits_are_dropped(self):
        proposal = _improve([_edit("Be polite", "Be polite")])
        assert proposal["edits"] == [] and proposal["result"] == PERSONA

    def test_too_many_edits(self):
        content = " ".join(f"w{i}." for i in range(MAX_EDITS + 2))
        with pytest.raises(ProposalInvalid, match="at most"):
            _improve([_edit(f"w{i}.", f"x{i}.") for i in range(MAX_EDITS + 1)], content=content)

    def test_an_edit_needs_a_reason(self):
        with pytest.raises(ProposalInvalid, match="reason"):
            _improve([_edit("Be polite", "Be warm", reason="  ")])

    def test_emptying_the_prompt_is_refused(self):
        with pytest.raises(ProposalInvalid, match="empty"):
            _improve([_edit(PERSONA, "")])

    def test_switching_a_persona_to_a_template_is_flagged(self):
        proposal = _improve([_edit("Be polite and concise.", "Be polite. Company: {{ passthrough.company }}")],
                            messages=("Use {{ passthrough.company }}",))
        assert proposal["template_mode"] == {"before": False, "after": True}
        assert proposal["checks"] == ["to_template"]

    def test_switching_a_template_to_a_persona_is_flagged(self):
        proposal = _improve([_edit(" {{ system.date }}", "")], content="Hi. Today {{ system.date }}")
        assert proposal["template_mode"] == {"before": True, "after": False}
        assert proposal["checks"] == ["to_persona"]

    def test_removing_boundaries_or_citations_from_a_template_is_flagged(self):
        template = compose_preset("default")
        boundaries = template[template.index("## Boundaries"):template.index("## Boundaries") + 200]
        citations = "{% if source.citation_rules %}\n{{ source.citation_rules }}\n\n{% endif %}\n"
        assert citations in template
        proposal = _improve([_edit(boundaries, ""), _edit(citations, "")], content=template)
        assert proposal["checks"] == ["boundaries_removed", "citations_removed"]

    def test_a_classic_copy_on_a_research_agent_is_flagged(self):
        template = compose_preset("default")
        edit = [_edit("## Formatting", "## Formatting\n- Keep answers short.")]
        research = _improve(edit, content=template, agent={"sources": [], "tools": [], "agent_type": "research"})
        assert research["checks"] == ["agentic_copy"]
        classic = _improve(edit, content=template, agent={"sources": [], "tools": [], "agent_type": "classic"})
        assert classic["checks"] == []

    def test_a_result_that_does_not_parse_goes_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match="parse"):
            _improve([_edit("Hi {{ system.date }}", "Hi {{ system.date ")], content="Hi {{ system.date }}")

    def test_a_prompt_that_never_parsed_is_not_blamed_on_the_edit(self):
        proposal = _improve([_edit("Be brief.", "Be brief and kind.")], content="Literal {% here. Be brief.")
        assert proposal["result"] == "Literal {% here. Be brief and kind."

    def test_tool_variables_need_the_users_ask(self):
        edit = [_edit("Be polite and concise.", "Memory: {{ tools.memory.memory_view }}")]
        with pytest.raises(ProposalInvalid, match="tools"):
            _improve(edit)
        asked = _improve(edit, messages=("Add {{ tools.memory.memory_view }}",))
        assert "memory_view" in asked["result"]

    def test_model_warnings_are_kept_and_capped(self):
        proposal = _improve([], warnings=["One", "", "Two", "Three", "Four"])
        assert proposal["warnings"] == ["One", "Two", "Three"]


@pytest.mark.unit
class TestWrite:
    def _write(self, content, name="HR handbook assistant", messages=(), **extra):
        args = {"message": "Wrote it.", "name": name, "content": content, "reason": "A persona.", **extra}
        return validate(args, _req("write", "", None, *(messages or ("HR helper",))), Workspace())

    def test_a_persona_is_returned(self):
        proposal = self._write("You help employees with the HR handbook.")
        assert proposal == {
            "mode": "write", "message": "Wrote it.", "name": "HR handbook assistant",
            "content": "You help employees with the HR handbook.", "reason": "A persona.",
            "warnings": [], "template_mode": {"before": False, "after": False}, "checks": [],
        }

    @pytest.mark.parametrize("name,content", [("", "x"), ("N", ""), ("x" * 101, "x"), ("N", "Hi {{ broken")])
    def test_fixable_problems_go_back_to_the_model(self, name, content):
        with pytest.raises(ProposalInvalid):
            self._write(content, name=name)

    def test_tool_variables_need_the_users_ask(self):
        with pytest.raises(ProposalInvalid, match="tools"):
            self._write("Memory: {{ tools.memory.memory_view }}")

    def test_a_template_is_flagged(self):
        proposal = self._write("Today is {{ system.date }}.", messages=("Put {{ system.date }} in it",))
        assert proposal["checks"] == ["to_template"]


@pytest.mark.unit
class TestTurn:
    def _run(self, *answers, req=None):
        fake = FakeLLM(*answers)
        events = list(run_draft(req or _req(), PROMPT_RECIPE, Workspace(), MODEL, llm_factory=fake.factory))
        return fake, events

    def test_ask_user_is_never_offered(self):
        fake, events = self._run(calls(tool_call("submit_proposal", {
            "message": "Done.", "edits": [_edit("Be polite", "Be warm")]})))
        assert [t["function"]["name"] for t in fake.calls[0]["tools"]] == ["get_source", "get_tool", "submit_proposal"]
        assert events[-1]["type"] == "proposal"
        assert events[-1]["proposal"]["result"].endswith("Be warm and concise.")

    def test_a_bad_edit_is_retried_once_then_invalid_output(self):
        bad = calls(tool_call("submit_proposal", {"message": "x", "edits": [_edit("Nope", "Yes")]}))
        fake, events = self._run(bad, bad)
        assert len(fake.calls) == 2
        assert "not found" in fake.calls[1]["messages"][-1]["content"]
        assert events[-1] == {"type": "error", "code": "invalid_output",
                              "message": "The draft didn't come out right. Try again, or rephrase your request."}

    def test_a_template_that_does_not_parse_is_retried_then_accepted(self):
        req = _req("write", "", None, "HR helper")
        bad = calls(tool_call("submit_proposal", {"message": "x", "name": "HR", "content": "Hi {{ x", "reason": "r"}))
        good = calls(tool_call("submit_proposal", {"message": "x", "name": "HR", "content": "Hi there", "reason": "r"}))
        fake, events = self._run(bad, good, req=req)
        assert "parse" in fake.calls[1]["messages"][-1]["content"]
        assert events[-1]["proposal"]["content"] == "Hi there"
