"""The prompt recipe: improving a prompt with checked edits, writing a new one after questions, and starters."""

from __future__ import annotations

import pytest

from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.prompt_recipe import (
    context_data,
    instructions,
    MAX_EDITS,
    parse_context,
    PROMPT_RECIPE,
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


def _req(mode="improve", content=PERSONA, *user_messages, name="Support reply", **extra) -> DraftRequest:
    messages = [{"role": "user", "content": m} for m in (user_messages or ("Stop it from making up prices",))]
    context = parse_context({"mode": mode, "prompt": {"id": "p1", "name": name, "content": content}, **extra})
    return DraftRequest("alice", "prompt", messages, context, "drafter:t")


def _improve(edits, content=PERSONA, messages=(), **extra):
    args = {"message": "Done.", "edits": edits, **extra}
    return validate(args, _req("improve", content, *messages), Workspace())


def _edit(find, replace, reason="Because."):
    return {"find": find, "replace": replace, "reason": reason}


@pytest.mark.unit
class TestContext:
    def test_values_are_cleaned(self):
        ctx = parse_context({
            "mode": "improve",
            "prompt": {"id": " p1 ", "name": "Sup\x00port", "content": "Hi\r\nthere"},
        })
        assert ctx == {"mode": "improve", "prompt": {"id": "p1", "name": "Support", "content": "Hi\nthere"},
                       "starter": None, "skip_questions": False}

    def test_a_starter_and_skip_are_read_for_write_only(self):
        write = parse_context({"mode": "write", "prompt": {"content": ""}, "starter": "website",
                               "skip_questions": True})
        assert (write["starter"], write["skip_questions"]) == ("website", True)
        assert parse_context({"mode": "write", "prompt": {}, "starter": "space-station"})["starter"] is None
        improve = parse_context({"mode": "improve", "prompt": {"content": "x"}, "starter": "website",
                                 "skip_questions": True})
        assert (improve["starter"], improve["skip_questions"]) == (None, False)

    @pytest.mark.parametrize("raw", [
        {"mode": "rewrite", "prompt": {"content": "x"}},
        {"mode": "improve", "prompt": {"content": "   "}},
        {"mode": "improve"},
        {"mode": "write", "prompt": ["x"]},
    ])
    def test_unusable_contexts_are_refused(self, raw):
        with pytest.raises(BadDraftRequest):
            parse_context(raw)

    def test_the_model_reads_the_prompt_and_its_mode(self):
        data = context_data(_req(), Workspace())
        assert data == {"mode": "improve", "prompt": {"name": "Support reply", "content": PERSONA, "kind": "persona"}}
        assert context_data(_req(content="Hi {{ system.date }}"), Workspace())["prompt"]["kind"] == "template"


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

    def test_improve_offers_no_questions(self):
        req = _req()
        assert PROMPT_RECIPE.asks(req) is False
        system = build_messages(req, PROMPT_RECIPE, Workspace(), tool_mode=True, allow_questions=False)[0]
        assert "submit_proposal" in system["content"] and "ask_user" not in system["content"]
        assert "asked enough questions" not in system["content"]

    def test_write_asks_first_unless_skipped(self):
        assert PROMPT_RECIPE.asks(_req("write", "")) is True
        assert PROMPT_RECIPE.asks(_req("write", "", skip_questions=True)) is False
        text = instructions(_req("write", ""), Workspace())
        for rule in ("company or product", "where it sends people", "no options", "placeholder",
                     "Never leave placeholders", "assumptions", "suggestions"):
            assert rule in text, rule

    @pytest.mark.parametrize("starter,marker", [
        ("website", "public website"), ("helpdesk", "staff"), ("research", "documents disagree"),
    ])
    def test_a_starter_brings_its_brief(self, starter, marker):
        assert marker in instructions(_req("write", "", starter=starter), Workspace())
        assert marker not in instructions(_req("write", ""), Workspace())

    def test_improve_suggests_next_changes(self):
        assert "suggestions" in instructions(_req(), Workspace())

    @pytest.mark.parametrize("mode,content", [("write", ""), ("improve", PERSONA)])
    def test_follow_ups_stay_on_the_prompts_text(self, mode, content):
        text = instructions(_req(mode, content), Workspace())
        assert "changes to the prompt's text" in text
        assert "knowledge or tools" in text

    @pytest.mark.parametrize("mode,content", [("write", ""), ("improve", PERSONA)])
    def test_hand_offs_say_where_to_go_not_promise_a_transfer(self, mode, content):
        text = instructions(_req(mode, content), Workspace())
        assert "can't transfer the chat to a person" in text
        assert "never \"I'll connect you\"" in text

    def test_the_first_round_fits_the_question_cap(self):
        text = instructions(_req("write", ""), Workspace())
        assert "one round of at most 3 questions" in text
        assert "Don't ask about off-limits topics" in text
        assert "off-limits topics as a pick-any question" not in text

    def test_a_second_round_asks_for_the_details_a_pick_needs(self):
        text = instructions(_req("write", ""), Workspace())
        for rule in ("a detail only the user knows", "the email address", "the form or page link",
                     "how people reach a person", "only for what the user picked"):
            assert rule in text, rule

    def test_a_person_is_offered_as_a_way_to_reach_one(self):
        assert "a person (live chat or phone)" in instructions(_req("write", ""), Workspace())

    def test_it_is_registered(self):
        assert get_recipe("prompt") is PROMPT_RECIPE

    def test_it_reads_no_workspace(self):
        assert PROMPT_RECIPE.reads_workspace is False


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

    def test_suggestions_come_with_the_edits(self):
        proposal = _improve([_edit("Be polite", "Be warm")], suggestions=["Add a hand-off"], assumptions=["x"])
        assert proposal["suggestions"] == ["Add a hand-off"]
        assert "assumptions" not in proposal

    def test_model_warnings_are_kept_and_capped(self):
        proposal = _improve([], warnings=["One", "", "Two", "Three", "Four"])
        assert proposal["warnings"] == ["One", "Two", "Three"]


@pytest.mark.unit
class TestWrite:
    def _write(self, content, name="HR handbook assistant", messages=(), **extra):
        args = {"message": "Wrote it.", "name": name, "content": content, "reason": "A persona.", **extra}
        return validate(args, _req("write", "", *(messages or ("HR helper",))), Workspace())

    def test_a_persona_is_returned(self):
        proposal = self._write("You help employees with the HR handbook.")
        assert proposal == {
            "mode": "write", "message": "Wrote it.", "name": "HR handbook assistant",
            "content": "You help employees with the HR handbook.", "reason": "A persona.",
            "warnings": [], "template_mode": {"before": False, "after": False}, "checks": [],
            "assumptions": [], "suggestions": [],
        }

    def test_assumptions_and_suggestions_are_cleaned_and_capped(self):
        proposal = self._write(
            "You help employees.",
            assumptions=["Hand-offs go to HR.", " ", "x" * 500, "Three", "Four"],
            suggestions=["Add office hours", "add office hours", "Make it shorter", "Four", "Five"],
        )
        assert proposal["assumptions"][:2] == ["Hand-offs go to HR.", "x" * 199 + "…"]
        assert len(proposal["assumptions"]) == 3
        assert proposal["suggestions"] == ["Add office hours", "Make it shorter", "Four"]

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

    def test_write_may_ask_with_a_typed_question(self):
        req = _req("write", "", "Website chat for customers", starter="website")
        fake, events = self._run(calls(tool_call("ask_user", {"questions": [
            {"text": "Which company is it for?", "options": [], "placeholder": "e.g. Meridian Freight"},
            {"text": "Where should it send people?", "options": ["Support email", "Live chat"]},
        ]})), req=req)
        assert "ask_user" in [t["function"]["name"] for t in fake.calls[0]["tools"]]
        assert events[-1]["type"] == "questions"
        assert events[-1]["questions"][0]["options"] == []

    def test_a_skipped_round_drafts_without_asking(self):
        req = _req("write", "", "Website chat for customers", starter="website", skip_questions=True)
        fake, events = self._run(calls(tool_call("submit_proposal", {
            "message": "Wrote it.", "name": "Website chat", "content": "You help visitors.", "reason": "r",
            "assumptions": ["Hand-offs go to the support team."]})), req=req)
        assert [t["function"]["name"] for t in fake.calls[0]["tools"]] == ["submit_proposal"]
        assert events[-1]["proposal"]["assumptions"] == ["Hand-offs go to the support team."]

    def test_ask_user_is_never_offered(self):
        fake, events = self._run(calls(tool_call("submit_proposal", {
            "message": "Done.", "edits": [_edit("Be polite", "Be warm")]})))
        assert [t["function"]["name"] for t in fake.calls[0]["tools"]] == ["submit_proposal"]
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
        req = _req("write", "", "HR helper")
        bad = calls(tool_call("submit_proposal", {"message": "x", "name": "HR", "content": "Hi {{ x", "reason": "r"}))
        good = calls(tool_call("submit_proposal", {"message": "x", "name": "HR", "content": "Hi there", "reason": "r"}))
        fake, events = self._run(bad, good, req=req)
        assert "parse" in fake.calls[1]["messages"][-1]["content"]
        assert events[-1]["proposal"]["content"] == "Hi there"
