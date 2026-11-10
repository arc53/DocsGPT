"""The drafter's text patterns stay linear on adversarial input and match what they matched before."""

import random
import re
import time

import pytest

from docsgpt.drafter import agent_recipe, prompt_checks, prompt_recipe

# The patterns as they were, to check the linear ones match the same texts.
_OLD_MASKED = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)|`[^`\n]+`", re.S)
_OLD_STATED_LIMITS = re.compile(r"\d[\d,.\s  ']*k?\s*(?:requests?|tokens?)\b")
_OLD_CLAIM_LIMITS = re.compile(r"\d[\d,.\s  ']*k?\s*-?\s*(?:requests?|tokens?)\b", re.I)
_CHECK_NAMES = r"(?:pii|personal data|injection|groundedness|grounded|secrets?)"
_OLD_STATED_GUARDRAILS = re.compile(
    rf"\b{_CHECK_NAMES}\b(?:\s+(?:and|or|,)?\s*\w+){{0,3}}\s+(?:checks?|guardrails?)\b|\bguardrails?\b.*\b{_CHECK_NAMES}\b"
)
_OLD_CODE_NOTE = re.compile(
    r"\s*\((\s*(?:server\s+)?checks?(?:\s+codes?)?\s*:)?\s*([a-z][a-z0-9_]*(?:\s*,\s*[a-z][a-z0-9_]*)*)\s*\)", re.I
)

BUDGET = 0.5


def _fast(fn, *args) -> object:
    started = time.perf_counter()
    result = fn(*args)
    assert time.perf_counter() - started < BUDGET
    return result


def _samples(alphabet: list[str], count: int = 3000, seed: int = 7) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24))) for _ in range(count)]


def _old_masked(text: str) -> str:
    return _OLD_MASKED.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


@pytest.mark.unit
class TestMasked:
    @pytest.mark.parametrize("unit", ["{{", "{%", "{#", "{{ a", "`", "``", "{{}}", "{"])
    def test_unclosed_openers_are_linear(self, unit: str) -> None:
        text = unit * (100_000 // len(unit))
        assert len(_fast(prompt_checks._masked, text)) == len(text)

    def test_same_masking_as_the_regex(self) -> None:
        alphabet = ["{", "}", "%", "#", "`", "~", "\n", "a", " ", "{{", "}}", "```", "~~~"]
        for text in _samples(alphabet):
            assert prompt_checks._masked(text) == _old_masked(text), text

    def test_blank_after_unclosed_template_is_still_found(self) -> None:
        text = "Email us at [support email]. {{ oops"
        assert prompt_checks._masked(text) == text


@pytest.mark.unit
class TestAgentRecipePatterns:
    @pytest.mark.parametrize("unit", ["1 ", "1,", " ", "1 k", "1 -", "9"])
    def test_limits_patterns_are_linear(self, unit: str) -> None:
        text = unit * (100_000 // len(unit))
        assert not _fast(agent_recipe._STATED["limits"].search, text)
        assert not _fast(agent_recipe._CLAIM_MENTIONS["limits"].search, text)

    def test_guardrails_pattern_is_linear(self) -> None:
        assert not _fast(agent_recipe._STATED["guardrails"].search, "guardrail " * 10_000)

    def test_limits_patterns_match_what_they_did(self) -> None:
        alphabet = ["1", "0", ",", ".", " ", "'", " ", "k", "K", "-", "requests", "token", "tokens", "a", "\n"]
        for text in _samples(alphabet):
            assert bool(agent_recipe._STATED["limits"].search(text)) == bool(_OLD_STATED_LIMITS.search(text)), text
            assert bool(agent_recipe._CLAIM_MENTIONS["limits"].search(text)) == bool(
                _OLD_CLAIM_LIMITS.search(text)
            ), text

    def test_guardrails_pattern_matches_what_it_did(self) -> None:
        alphabet = ["guardrail", "guardrails", "pii", "secrets", " ", "\n", "checks", "and", "x", ","]
        for text in _samples(alphabet):
            assert bool(agent_recipe._STATED["guardrails"].search(text)) == bool(
                _OLD_STATED_GUARDRAILS.search(text)
            ), text

    def test_numbers_survive_long_digit_runs(self) -> None:
        assert _fast(agent_recipe._numbers, "1" * 100_000) == set()
        assert _fast(agent_recipe._numbers, "1" * 100_000 + "k") == set()
        assert _fast(agent_recipe._numbers, "1 " * 50_000) == {1}

    def test_numbers_still_read_groupings(self) -> None:
        assert agent_recipe._numbers("Cap it at 1,000 requests or 2k tokens, 5 000 a day") == {1000, 2, 2000, 5000}


@pytest.mark.unit
class TestCodeNote:
    def test_whitespace_runs_are_linear(self) -> None:
        assert _fast(prompt_recipe._no_codes, "a" + " " * 100_000 + "b") == "a" + " " * 100_000 + "b"

    def test_same_matches_as_before(self) -> None:
        alphabet = [" ", "\n", "(", ")", "server", " check", "checks", ":", "a_b", ",", "x", "boundaries_missing"]
        for text in _samples(alphabet):
            old = [m.span() for m in _OLD_CODE_NOTE.finditer(text)]
            assert [m.span() for m in prompt_recipe._CODE_NOTE.finditer(text)] == old, text


@pytest.mark.unit
class TestPromptChecksBudget:
    """Whole prompts at the 100,000-character cap are checked in about linear time."""

    @pytest.fixture(autouse=True)
    def _warm(self) -> None:
        # The first call imports the template helpers once; that isn't the check's cost.
        prompt_checks.prompt_checks("warm up")

    @pytest.mark.parametrize("unit", [
        "Never use markdown.\n", "Never use markdown ", "no cite sources ", "<foo>\n", "<foo bar> ",
    ])
    def test_repeated_units_are_linear(self, unit: str) -> None:
        _fast(prompt_checks.prompt_checks, unit * (100_000 // len(unit)))

    def test_many_distinct_blanks_are_linear(self) -> None:
        text = "".join(f"[blank {n}]\n" for n in range(100_000 // 12))
        checks = _fast(prompt_checks.prompt_checks, text)
        assert checks[0] == {"code": "placeholder", "text": "[blank 0]", "line": 1}

    def test_a_negated_line_after_many_clauses_is_still_negated(self) -> None:
        text = "Be kind. " * 2000 + "Never use markdown.\nUse markdown headings."
        repeats = [c for c in prompt_checks.prompt_checks(text) if c["code"] == "repeats_builtin"]
        assert [c["line"] for c in repeats if c["topic"] == "formatting"] == [2]
