"""The ported analytics schema against a golden fixture exported from arc-decide's ``arcd/analytics``.

``tests/fixtures/analytics_schema.json`` holds arc-decide's questions (in their ``criteria`` order), the states its
builders return for fixed inputs, its caps and its hash. The model reads all of them, so any difference is an
untrained input.
"""

import json
from pathlib import Path

import pytest

from docsgpt.analytics import schema as S
from docsgpt.decisions import Q
from docsgpt.decisions.questions import validate
from docsgpt.decisions.states import render

GOLDEN = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "analytics_schema.json").read_text(encoding="utf-8")
)


def _same(ours, theirs):
    """Equal, and every choice question's options in the same order."""
    assert ours == theirs
    if ours and ours.get("type") == "choice":
        assert list(ours["criteria"]) == list(theirs["criteria"])


@pytest.mark.unit
class TestSchemaPort:
    def test_schema_hash_is_the_published_one(self):
        assert S.SCHEMA_HASH == GOLDEN["schema_hash"] == "6bc095072836"
        assert S.SCHEMA_HASH == S._hash()

    def test_hash_tracks_wording(self, monkeypatch):
        monkeypatch.setitem(S.ANSWER_STATUS, "instructions", "reworded")
        assert S._hash() != S.SCHEMA_HASH
        monkeypatch.undo()
        monkeypatch.setattr(S, "TOPIC_INSTRUCTIONS", "Reworded?")
        assert S._hash() != S.SCHEMA_HASH

    def test_constants(self):
        assert S.SCHEMA_VERSION == GOLDEN["schema_version"]
        assert S.NONE_OPTION == GOLDEN["none_option"]
        assert S.CAPS == GOLDEN["caps"]
        assert S.TOPIC_INSTRUCTIONS == GOLDEN["topic_instructions"]
        assert S.TAG_GROUP_INSTRUCTIONS == GOLDEN["tag_group_instructions"]

    def test_every_label_matches_in_order(self):
        assert [(lab.name, lab.level) for lab in S.LABELS] == [(g["name"], g["level"]) for g in GOLDEN["labels"]]
        for lab, golden in zip(S.LABELS, GOLDEN["labels"]):
            _same(lab.question, golden["question"])

    def test_the_fixed_questions_are_the_harness_copies(self):
        """One copy of each trained question: the harness's, under the key it was trained with."""
        for key, question in {**S.questions("turn"), **S.questions("reaction"), **S.questions("message"),
                              **S.questions("conversation"), **S.questions("tool")}.items():
            assert question is getattr(Q, key.upper())
            validate({key: question})

    def test_parameterised_questions(self):
        _same(S.topic_question({"installation": "Pages such as: Install; Upgrade", "auth": None,
                                S.NONE_OPTION: "ignored"}), GOLDEN["topic_question"])
        assert list(GOLDEN["topic_question"]["criteria"])[-1] == S.NONE_OPTION
        assert S.tag_question("  Pricing question ", " Asks about plans or prices. ") == GOLDEN["tag_question"]

    @pytest.mark.parametrize("case", range(len(GOLDEN["states"])))
    def test_states_are_byte_equal(self, case):
        builder, args, expected = GOLDEN["states"][case]
        state = getattr(S, builder)(**args)
        assert state == expected
        assert render(state) == json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True)

    def test_a_long_chinese_answer_is_capped_in_units(self):
        _, args, state = GOLDEN["states"][1]
        assert len(args["answer"]) == 900
        assert len(state["answer"]) == 834 and state["answer"].endswith("…")
        assert S.units(state["answer"][:-1]) <= S.CAPS["answer"]

    def test_a_long_source_is_cut_to_its_cap_and_sorts_last(self):
        _, _, state = GOLDEN["states"][0]
        assert len(state["sources"][0]["text"]) == S.CAPS["source_each"]
        text = render(state)
        assert text.index("reset my password") < text.index("The reset page lives")

    def test_units_and_caps(self):
        assert S.units("你好") == 6
        for text, units in GOLDEN["units"]:
            assert S.units(text) == pytest.approx(units)
        for text, n, capped in GOLDEN["caps_cases"]:
            assert S.cap(text, n) == capped
