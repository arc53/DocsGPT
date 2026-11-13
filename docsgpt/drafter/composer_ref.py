"""What DocsGPT wraps around a persona, as the drafter shows it to the model.

A plain-text prompt runs inside one of the composed presets
(``docsgpt/prompts/composer.py``), picked by the agent's type in
``resolve_prompt_skeleton``. The prompt review reads that real text, so it
judges a persona against the instructions it will actually sit in, not a copy
that can drift. The write and improve modes read a short summary instead
(``COMPOSER_SUMMARY`` in ``docsgpt/drafter/prompt_rules.py``), which
:func:`composer_sections` keeps honest in the tests.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

#: What stands for the operator's persona inside the frame (``<persona>…</persona>``).
PERSONA_MARKER = "…"
#: The section of the composer that varies by retrieval mode and tone.
ANSWERING = "answering"

_PERSONA_SLOT = "{{ system.persona }}"
_CITATION_SLOT = "{{ source.citation_rules }}"
#: Any plain text: ``resolve_prompt_skeleton`` stages it as a persona and returns the skeleton around it.
_SAMPLE_PERSONA = "You help."


@lru_cache(maxsize=16)
def persona_frame(agent_type: Optional[str]) -> str:
    """The instructions DocsGPT wraps around a plain-text persona for one agent type.

    Built the way an answer builds it (``resolve_prompt_skeleton`` picks the
    classic or agentic skeleton), with the persona slot shown as
    :data:`PERSONA_MARKER` and ``{{ source.citation_rules }}`` as the citation
    rules it renders when knowledge is attached. The other ``{{ }}`` variables and
    ``{% if %}`` blocks stay as written: they say when a section applies.

    Args:
        agent_type: The agent's ``agent_type`` (``classic``, ``agentic``, ``research``…); anything else is classic.

    Returns:
        The frame's text (cached per agent type).
    """
    from docsgpt.api.answer.services.prompt_renderer import resolve_prompt_skeleton
    from docsgpt.templates.namespaces import citation_rules

    skeleton, _ = resolve_prompt_skeleton(_SAMPLE_PERSONA, "", agent_type or None)
    return (skeleton or "").replace(_PERSONA_SLOT, PERSONA_MARKER).replace(_CITATION_SLOT, citation_rules().strip())


def composer_sections() -> tuple[str, ...]:
    """The fragments every composed preset is built from, in order, with :data:`ANSWERING` for the varying slot.

    Returns:
        Fragment file names relative to ``docsgpt/prompts/fragments/`` (``identity.txt``…) and ``answering``.
    """
    from docsgpt.prompts import composer

    return tuple(ANSWERING if section is None else section for section in composer._SECTION_ORDER)
