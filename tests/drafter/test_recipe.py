"""Rules every recipe shares: request ids, and the checks on a drafted prompt text."""

from __future__ import annotations

import pytest

from docsgpt.drafter.prompt_recipe import check_drafted_prompt
from docsgpt.drafter.prompt_rules import TEMPLATE_PROBLEM
from docsgpt.drafter.recipe import clean_id, DraftRequest, ID_CHARS, ProposalInvalid

BROKEN = "{{ source.content }} {% if x %}"
TOOL = "Use {{ source.content }} and {{ tools.memory.memory_view }}."


def _req(*user_messages: str) -> DraftRequest:
    return DraftRequest("alice", "prompt", [{"role": "user", "content": m} for m in user_messages or ("Hi",)], {},
                        "drafter:t")


@pytest.mark.unit
class TestCleanId:
    @pytest.mark.parametrize("value", [None, 3, ["a"], "", "   "])
    def test_anything_but_a_non_empty_string_is_none(self, value):
        assert clean_id(value) is None

    def test_an_id_is_stripped_and_cut(self):
        assert clean_id("  abc ") == "abc"
        assert clean_id(" " + "x" * (ID_CHARS + 5)) == "x" * ID_CHARS


@pytest.mark.unit
class TestCheckDraftedPrompt:
    def test_a_whole_new_text_that_does_not_parse_is_always_refused(self):
        for previous in ("", "Plain.", BROKEN):
            with pytest.raises(ProposalInvalid) as raised:
                check_drafted_prompt(BROKEN, previous, _req(), edited=False)
            assert raised.value.problems == [TEMPLATE_PROBLEM]

    def test_edits_are_refused_unless_the_previous_text_never_parsed(self):
        check_drafted_prompt(BROKEN + " more", BROKEN, _req(), edited=True)
        for previous in ("", "Plain."):
            with pytest.raises(ProposalInvalid) as raised:
                check_drafted_prompt(BROKEN, previous, _req(), edited=True)
            assert raised.value.problems == [TEMPLATE_PROBLEM]

    def test_tool_variables_need_the_users_words_here_or_earlier(self):
        with pytest.raises(ProposalInvalid, match="tools"):
            check_drafted_prompt(TOOL, "", _req(), edited=False)
        check_drafted_prompt(TOOL, "", _req("add tools.memory"), edited=False)
        check_drafted_prompt(TOOL, "", _req(), edited=False, earlier=["add tools.memory.memory_view"])

    def test_only_edits_are_held_to_the_edit_rules(self):
        check_drafted_prompt("Email [support email].", "Plain.", _req(), edited=False)
        with pytest.raises(ProposalInvalid, match="Ask the user for it, or write around it"):
            check_drafted_prompt("Email [support email].", "Plain.", _req(), edited=True)
        with pytest.raises(ProposalInvalid, match="Give its finding an ask instead"):
            check_drafted_prompt("Email [support email].", "Plain.", _req(), edited=True,
                                 ask_instead="Give its finding an ask instead")
