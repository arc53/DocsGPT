"""When the system prompt asks for ``[n]`` citations, and when it does not.

Built-in prompts and plain-text (persona) prompts carry the Citations section
whenever the turn has sources attached. A template prompt (``{{ }}``) is the
author's own and gets nothing added: it opts in with
``{{ source.citation_rules }}``, and until then the documents' guard keeps
asking for source titles as it always did.
"""

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.answer.services.prompt_renderer import (
    PromptRenderer,
    prompt_requests_citations,
    resolve_prompt_skeleton,
)
from docsgpt.prompts.composer import compose_preset

pytestmark = pytest.mark.unit

SECTION = "## Citations"


def _render(template: str, attached: bool, persona: str | None = None) -> str:
    return PromptRenderer().render_prompt(
        template, sources_attached=attached, persona=persona
    )


@pytest.mark.parametrize("preset", ["default", "strict", "agentic_default", "agentic_creative"])
def test_a_built_in_prompt_cites_when_sources_are_attached(preset):
    rendered = _render(compose_preset(preset), attached=True)
    assert SECTION in rendered
    assert "[n]" in rendered
    # Placed after Answering, with the usual one blank line around it.
    assert rendered.index("## Answering") < rendered.index(SECTION) < rendered.index("## Formatting")
    assert "\n\n\n" not in rendered


@pytest.mark.parametrize("preset", ["default", "agentic_default"])
def test_a_built_in_prompt_without_sources_has_no_citations_section(preset):
    rendered = _render(compose_preset(preset), attached=False)
    assert SECTION not in rendered
    assert "\n\n\n" not in rendered


def test_a_persona_prompt_keeps_citations():
    template, persona = resolve_prompt_skeleton(
        "You are Vicky, a terse support assistant.", "custom-id"
    )
    rendered = _render(template, attached=True, persona=persona)
    assert "You are Vicky" in rendered
    assert SECTION in rendered


def test_a_master_prompt_gets_nothing_added():
    rendered = _render("Today is {{ system.date }}. Answer briefly.", attached=True)
    assert SECTION not in rendered


def test_a_master_prompt_opts_in_with_the_citation_rules():
    template = "You answer for Acme.\n\n{{ source.citation_rules }}"
    assert SECTION in _render(template, attached=True)
    # With nothing attached the line renders empty, never a stray artifact.
    assert _render(template, attached=False).strip() == "You answer for Acme."


def test_a_legacy_summaries_prompt_gets_nothing_added():
    assert SECTION not in _render("Use these: {summaries}", attached=True)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (compose_preset("default"), True),
        (compose_preset("agentic_strict"), True),
        ("{{ source.citation_rules }}", True),
        ("{% if source.attached %}{{ source.citation_rules }}{% endif %}", True),
        ("Today is {{ system.date }}.", False),
        ("Use these: {summaries}", False),
        ("", False),
        (None, False),
    ],
)
def test_prompt_requests_citations(prompt, expected):
    assert prompt_requests_citations(prompt) is expected


def _create_agent(prompt, data=None, active_docs=None):
    """Build a chat turn's agent for ``prompt``; return (render kwargs, agent kwargs)."""
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    sp = StreamProcessor(request_data=data or {}, decoded_token={"sub": "u"})
    sp._get_prompt_content = MagicMock(return_value=prompt)
    sp.agent_config = {
        "agent_type": "classic",
        "prompt_id": "custom",
        "user_api_key": None,
        "allow_system_prompt_override": True,
    }
    sp.model_id = "m1"
    sp.source = {"active_docs": active_docs} if active_docs else {}
    sp.prompt_renderer = MagicMock()
    sp.prompt_renderer.render_prompt.return_value = "rendered"
    agent_kwargs = {}

    def capture(_agent_type, **kwargs):
        agent_kwargs.update(kwargs)
        return MagicMock()

    with patch(
        "docsgpt.api.answer.services.stream_processor.get_provider_from_model_id",
        return_value="openai",
    ), patch(
        "docsgpt.api.answer.services.stream_processor.get_api_key_for_provider",
        return_value="key",
    ), patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()), patch(
        "docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler",
        return_value=MagicMock(),
    ), patch(
        "docsgpt.agents.agent_creator.AgentCreator.create_agent", side_effect=capture
    ), patch.object(StreamProcessor, "_enabled_tool_names", return_value=set()):
        sp.create_agent()
    render = sp.prompt_renderer.render_prompt.call_args
    return (render.kwargs if render else {}), agent_kwargs


class TestChatTurnPlumbing:
    def test_a_prompt_with_the_citation_rules_cites(self):
        render, agent = _create_agent("Acme.\n\n{{ source.citation_rules }}", active_docs=["s1"])
        assert render["sources_attached"] is True
        assert agent["prompt_cites_sources"] is True

    def test_a_prompt_without_them_keeps_the_title_rule(self):
        render, agent = _create_agent("Today is {{ system.date }}.")
        assert render["sources_attached"] is False
        assert agent["prompt_cites_sources"] is False

    def test_a_system_prompt_override_never_counts_as_citing(self):
        _, agent = _create_agent(
            "{{ source.citation_rules }}",
            data={"system_prompt_override": "Be brief."},
            active_docs=["s1"],
        )
        assert agent["prompt_cites_sources"] is False
