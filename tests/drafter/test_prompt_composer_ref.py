"""The drafter's view of what DocsGPT wraps around a persona: the real composed text, and a summary that can't drift."""

from __future__ import annotations

import pytest

from docsgpt.api.answer.services.prompt_renderer import resolve_prompt_skeleton
from docsgpt.drafter.composer_ref import composer_sections, PERSONA_MARKER, persona_frame
from docsgpt.drafter.prompt_rules import COMPOSER_ADDS, COMPOSER_SUMMARY, NOT_SUMMARISED
from docsgpt.prompts.composer import FRAGMENTS_DIR
from docsgpt.templates.namespaces import citation_rules


@pytest.mark.unit
class TestPersonaFrame:
    @pytest.mark.parametrize("agent_type,heading", [
        ("classic", "When documents are provided with the question"),
        ("agentic", "You have a `search` tool"),
        ("research", "You have a `search` tool"),
        ("", "When documents are provided with the question"),
    ])
    def test_it_is_the_skeleton_a_persona_is_staged_in(self, agent_type, heading):
        frame = persona_frame(agent_type)
        skeleton, persona = resolve_prompt_skeleton("You help.", "custom-id", agent_type)
        assert persona == "You help."
        assert heading in frame
        # Only the persona slot and the citation rules differ from the skeleton the answer path renders.
        expected = skeleton.replace("{{ system.persona }}", PERSONA_MARKER).replace(
            "{{ source.citation_rules }}", citation_rules().strip())
        assert frame == expected

    def test_the_persona_slot_is_marked(self):
        frame = persona_frame("classic")
        assert f"<persona>\n{PERSONA_MARKER}\n</persona>" in frame
        assert "{{ system.persona }}" not in frame

    def test_it_shows_the_citation_rules(self):
        assert "Cite only numbers you were given" in persona_frame("classic")

    def test_it_is_cached(self):
        assert persona_frame("agentic") is persona_frame("agentic")


@pytest.mark.unit
class TestComposerSummary:
    def test_it_covers_every_fragment_the_composer_adds(self):
        # A fragment added to or dropped from docsgpt/prompts/composer.py must be summarised here, or left out
        # on purpose in NOT_SUMMARISED.
        summarised = [name for key in COMPOSER_SUMMARY for name in key]
        assert sorted(summarised + list(NOT_SUMMARISED)) == sorted(composer_sections())
        assert len(set(summarised)) == len(summarised)

    def test_it_follows_the_composers_order(self):
        summarised = [name for key in COMPOSER_SUMMARY for name in key]
        assert summarised == [name for name in composer_sections() if name not in NOT_SUMMARISED]

    def test_every_section_is_a_fragment(self):
        for name in composer_sections():
            assert name == "answering" or (FRAGMENTS_DIR / name).is_file(), name

    def test_the_summary_is_one_line_per_entry(self):
        lines = COMPOSER_ADDS.split("\n")
        assert len(lines) == len(COMPOSER_SUMMARY)
        assert all(line.startswith("  - ") for line in lines)
        assert lines[0] == "  - who it is and today's date;"
        assert COMPOSER_ADDS.endswith("attached files, when those apply.")
