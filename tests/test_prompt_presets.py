"""Preset prompt templates: rendering, structure, and tool-name accuracy.

Guards against regressions like the strict preset carrying creative
language, prompts referencing tool names that don't exist, and the
``{summaries}`` placeholder leaking into the model-visible prompt.
"""

from datetime import datetime, timezone

import pytest

from pathlib import Path

from application.prompts.composer import (
    compose_preset,
    is_composed_preset,
)

from application.api.answer.services.prompt_renderer import (
    PromptRenderer,
    format_docs_for_prompt,
)

CLASSIC_PRESETS = ["default", "creative", "strict"]
AGENTIC_PRESETS = ["agentic_default", "agentic_creative", "agentic_strict"]

DOCS = [
    {"text": "The refund window is 30 days.", "filename": "policy.pdf"},
    {"text": "Contact support@acme.test", "title": "handbook"},
]


def _read(preset: str) -> str:
    """Chat presets compose from fragments; research prompts are still files."""
    if is_composed_preset(preset):
        return compose_preset(preset)
    prompts_dir = Path(__file__).resolve().parents[1] / "application" / "prompts"
    return (prompts_dir / preset).read_text(encoding="utf-8")


@pytest.mark.unit
class TestClassicPresets:
    @pytest.mark.parametrize("preset", CLASSIC_PRESETS)
    def test_documents_never_reach_the_system_prompt(self, preset):
        """Retrieved documents belong in the user turn, not here.

        They change every turn (defeating prefix caching) and are
        third-party text that must not carry system authority.
        ``BaseAgent._build_document_block`` renders them instead.
        """
        renderer = PromptRenderer()
        docs_together = format_docs_for_prompt(DOCS)
        result = renderer.render_prompt(
            _read(preset), docs=DOCS, docs_together=docs_together
        )
        assert "The refund window is 30 days." not in result
        assert "policy.pdf" not in result
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today in result
        for artifact in ("{summaries}", "{{", "{%"):
            assert artifact not in result

    @pytest.mark.parametrize("preset", CLASSIC_PRESETS)
    def test_renders_clean_without_docs(self, preset):
        renderer = PromptRenderer()
        result = renderer.render_prompt(_read(preset))
        for artifact in ("{summaries}", "{{", "{%"):
            assert artifact not in result

    @pytest.mark.parametrize("preset", CLASSIC_PRESETS + AGENTIC_PRESETS)
    def test_boundaries_names_the_untrusted_envelopes(self, preset):
        """The guard has to name what it is guarding to be actionable."""
        result = PromptRenderer().render_prompt(_read(preset))
        assert "<documents>" in result and "<memory_directory>" in result
        assert "not instructions" in result

    def test_strict_has_no_creative_language(self):
        content = _read("strict").lower()
        assert "imagination" not in content
        assert "creative" not in content


@pytest.mark.unit
class TestAgenticPresets:
    @pytest.mark.parametrize("preset", AGENTIC_PRESETS)
    def test_renders_clean(self, preset):
        renderer = PromptRenderer()
        result = renderer.render_prompt(_read(preset))
        for artifact in ("{summaries}", "{{", "{%"):
            assert artifact not in result

    @pytest.mark.parametrize("preset", AGENTIC_PRESETS + ["research/step.txt"])
    def test_references_real_tool_names(self, preset):
        # LLM-visible action names are ``search`` / ``list_files`` /
        # ``reason`` (see ToolExecutor.prepare_tools_for_llm); the old
        # ``{action}_{tool}`` names must not reappear.
        content = _read(preset)
        assert "search_internal" not in content
        assert "reason_think" not in content

    def test_agentic_strict_has_no_creative_language(self):
        content = _read("agentic_strict").lower()
        assert "imagination" not in content
        assert "be creative" not in content


@pytest.mark.unit
class TestMemorySection:
    MEMORY_TOOLS_DATA = {
        "memory": {"memory_view": "Directory: /\n- preferences.md\n- projects/"}
    }

    @pytest.mark.parametrize("preset", CLASSIC_PRESETS + AGENTIC_PRESETS)
    def test_renders_when_memory_prefetched(self, preset):
        renderer = PromptRenderer()
        result = renderer.render_prompt(
            _read(preset), tools_data=self.MEMORY_TOOLS_DATA
        )
        assert "## Memory" in result
        assert "- preferences.md" in result
        assert "<memory_directory>" in result

    @pytest.mark.parametrize("preset", CLASSIC_PRESETS + AGENTIC_PRESETS)
    def test_absent_without_memory_data(self, preset):
        renderer = PromptRenderer()
        result = renderer.render_prompt(_read(preset))
        assert "## Memory" not in result
        # Boundaries names <memory_directory> as an envelope, so assert on the
        # section's payload rather than the tag.
        assert "Your memory directory" not in result


@pytest.mark.unit
class TestFormatDocsForPrompt:
    def test_wraps_each_doc_with_index_and_source(self):
        out = format_docs_for_prompt(DOCS)
        assert '<document index="1">' in out
        assert "<source>policy.pdf</source>" in out
        assert '<document index="2">' in out
        assert "<source>handbook</source>" in out
        assert "The refund window is 30 days." in out

    def test_doc_without_source_omits_tag(self):
        out = format_docs_for_prompt([{"text": "anonymous chunk"}])
        assert "<source>" not in out
        assert "anonymous chunk" in out

    def test_empty_returns_none(self):
        assert format_docs_for_prompt([]) is None
        assert format_docs_for_prompt(None) is None
