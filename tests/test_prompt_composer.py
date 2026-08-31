"""The composed presets must stay byte-identical to the files they replaced.

Six near-identical preset files became fragments + a load-time composer. These
goldens are the regression net: they pin the exact bytes each preset produced
before the refactor, so a fragment edit that changes one preset can never
silently change the other five.
"""

from pathlib import Path

import pytest

from application.prompts.composer import (
    FRAGMENTS_DIR,
    PRESET_VARIANTS,
    compose_preset,
    is_composed_preset,
)

GOLDEN_DIR = Path(__file__).parent / "golden_prompts"


@pytest.mark.unit
class TestComposedPresets:
    @pytest.mark.parametrize("preset_id", sorted(PRESET_VARIANTS))
    def test_matches_golden(self, preset_id):
        golden = (GOLDEN_DIR / f"{preset_id}.txt").read_text(encoding="utf-8")
        assert compose_preset(preset_id) == golden

    @pytest.mark.parametrize("preset_id", sorted(PRESET_VARIANTS))
    def test_shared_sections_are_identical_across_presets(self, preset_id):
        """The whole point of the refactor: shared prose exists once.

        A fix applied to Formatting/Boundaries/Memory must reach every preset,
        which is exactly what drifted when these were six separate files.
        """
        composed = compose_preset(preset_id)
        for shared in ("formatting.txt", "boundaries.txt", "memory.txt"):
            assert (FRAGMENTS_DIR / shared).read_text(encoding="utf-8") in composed

    def test_only_answering_differs_between_tones(self):
        default = compose_preset("default")
        creative = compose_preset("creative")
        # Everything from Formatting onward is shared verbatim.
        tail = default[default.index("## Formatting") :]
        assert tail == creative[creative.index("## Formatting") :]

    def test_no_tool_usage_section_in_the_prompt(self):
        """Per-tool policy belongs in the tool schema, not here.

        A prompt section describing a tool renders whether or not the tool is
        attached, which is how the old gate told users' models to produce
        artifacts they had no tool for.
        """
        for preset_id in PRESET_VARIANTS:
            composed = compose_preset(preset_id)
            assert "## Producing documents and running code" not in composed
            assert "artifact_generator" not in composed

    def test_forbids_inventing_a_download_link(self):
        """The one file rule that cannot live in a tool description.

        Models announce generated files with a ``sandbox:`` URL taken from
        their own pretraining — including on turns that made no tool call at
        all, where no tool description is even sent. That is a formatting rule
        about the answer, so it belongs here.
        """
        for preset_id in PRESET_VARIANTS:
            composed = compose_preset(preset_id)
            assert "download link" in composed
            assert "artifact_generator" not in composed

    def test_unknown_preset_is_not_composed(self):
        assert not is_composed_preset("reduce")
        assert not is_composed_preset("some-uuid")

    def test_composition_is_cached_and_stable(self):
        assert compose_preset("default") == compose_preset("default")


@pytest.mark.unit
class TestPersonaSlot:
    """A plain-text custom prompt keeps the platform's safety rules.

    It used to take a legacy path that substituted ``{summaries}`` and nothing
    else, so it shipped without Boundaries (the injection guard), the platform
    block, memory or the attachment list.
    """

    def _render(self, persona):
        from application.templates.namespaces import NamespaceManager
        from application.templates.template_engine import TemplateEngine

        context = NamespaceManager().build_context(persona=persona)
        return TemplateEngine().render(compose_preset("default"), context)

    def test_persona_appears_with_the_invariants_intact(self):
        out = self._render("You are Vicky, a support bot for example.com.")
        assert "You are Vicky" in out
        assert "## Your role" in out
        assert "not instructions" in out, "Boundaries must survive a custom prompt"
        assert "## The DocsGPT platform" in out

    def test_persona_braces_are_inert(self):
        """The operator's text is a value, so it can never break the skeleton."""
        out = self._render("Answer as {{ system.date }} and {% if x %}oops{% endif %}")
        assert "{{ system.date }}" in out
        assert "{% if x %}" in out

    def test_no_persona_leaves_no_empty_section(self):
        assert "## Your role" not in self._render(None)
