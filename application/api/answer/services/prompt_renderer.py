import logging
from typing import Any, Dict, Optional

from application.templates.namespaces import NamespaceManager

from application.templates.template_engine import TemplateEngine, TemplateRenderError

logger = logging.getLogger(__name__)


# Legacy prompts that interpolate the retrieved documents into the system
# prompt themselves. Documents now travel with the user turn, so a prompt
# using any of these keeps its old behaviour and suppresses the new block
# rather than receiving the documents twice.
# ``SourceNamespace.build`` exposes five document-bearing keys; ``documents``
# is the documented way to write a custom citation loop, so it must be here
# too. Subscript/alias forms (``source['summaries']``) are not detectable by
# substring and fall through to the user-turn block — that degrades to sending
# the documents twice, never to sending them nowhere.
_DOCUMENT_EMBEDDING_MARKERS = (
    "source.summaries",
    "source.content",
    "source.docs_together",
    "source.documents",
    "{summaries}",
)


def prompt_embeds_documents(prompt_content: Optional[str]) -> bool:
    """Return True when the prompt injects the retrieved documents itself.

    Args:
        prompt_content: The raw (unrendered) prompt template.

    Returns:
        bool: True if the template references a document-bearing variable.
    """
    if not prompt_content:
        return False
    return any(marker in prompt_content for marker in _DOCUMENT_EMBEDDING_MARKERS)


def format_docs_for_prompt(docs: Optional[list]) -> Optional[str]:
    """Format retrieved chunks as XML-tagged documents for prompt injection.

    Each chunk is wrapped in a ``<document index="n">`` block with a
    ``<source>`` subtag (when a filename/title is known) so the model can
    tell chunks apart and cite them by name.
    """
    if not docs:
        return None
    parts = []
    for i, doc in enumerate(docs, start=1):
        source = doc.get("filename") or doc.get("title") or doc.get("source")
        lines = [f'<document index="{i}">']
        if source:
            lines.append(f"<source>{source}</source>")
        lines.append(f"<content>\n{doc.get('text', '')}\n</content>")
        lines.append("</document>")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def resolve_prompt_skeleton(
    content: Optional[str], prompt_id: str, agent_type: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Split a resolved prompt into a template and an optional persona value.

    A custom prompt with no template syntax used to take a legacy path that
    substituted ``{summaries}`` and nothing else — so it silently shipped
    without the Boundaries rule (the prompt-injection guard), the platform
    block, the memory section or the attachment list. Staging it as a *value*
    inside the composed skeleton keeps all of those, and braces in the
    operator's text stay literal instead of being evaluated.

    Templated custom prompts are left alone: their authors opted into the
    namespaces and rely on them.

    Args:
        content: The raw prompt text resolved for this agent.
        prompt_id: The id it was resolved from.
        agent_type: Selects the classic or agentic skeleton.

    Returns:
        tuple: ``(template, persona)`` — ``persona`` is None when ``content``
        is already a usable template.
    """
    from application.prompts.composer import compose_preset, is_composed_preset

    if not content or is_composed_preset(prompt_id) or prompt_id == "reduce":
        return content, None
    if "{{" in content and "}}" in content:
        return content, None
    # A legacy prompt whose only marker is ``{summaries}`` still needs the
    # legacy substitution; as a persona value it would ship verbatim.
    if prompt_embeds_documents(content):
        return content, None
    skeleton = (
        "agentic_default" if agent_type in ("agentic", "research") else "default"
    )
    return compose_preset(skeleton), content


class PromptRenderer:
    """Service for rendering prompts with dynamic context using namespaces"""

    def __init__(self):
        self.template_engine = TemplateEngine()
        self.namespace_manager = NamespaceManager()

    def render_prompt(
        self,
        prompt_content: str,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        passthrough_data: Optional[Dict[str, Any]] = None,
        docs: Optional[list] = None,
        docs_together: Optional[str] = None,
        tools_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        """
        Render prompt with full context from all namespaces.

        Args:
            prompt_content: Raw prompt template string
            user_id: Current user identifier
            request_id: Unique request identifier
            passthrough_data: Parameters from web request
            docs: RAG retrieved documents
            docs_together: Concatenated document content
            tools_data: Pre-fetched tool results organized by tool name
            **kwargs: Additional parameters for namespace builders

        Returns:
            Rendered prompt string with all variables substituted

        Raises:
            TemplateRenderError: If template rendering fails
        """
        if not prompt_content:
            return ""

        uses_template = self._uses_template_syntax(prompt_content)

        if not uses_template:
            return self._apply_legacy_substitutions(prompt_content, docs_together)

        try:
            context = self.namespace_manager.build_context(
                user_id=user_id,
                request_id=request_id,
                passthrough_data=passthrough_data,
                docs=docs,
                docs_together=docs_together,
                tools_data=tools_data,
                **kwargs,
            )

            return self.template_engine.render(prompt_content, context)
        except TemplateRenderError:
            raise
        except Exception as e:
            error_msg = f"Prompt rendering failed: {str(e)}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e

    def _uses_template_syntax(self, prompt_content: str) -> bool:
        """Check if prompt uses Jinja2 template syntax"""
        return "{{" in prompt_content and "}}" in prompt_content

    def _apply_legacy_substitutions(
        self, prompt_content: str, docs_together: Optional[str] = None
    ) -> str:
        """
        Apply backward-compatible substitutions for old prompt format.

        Handles the legacy {summaries} placeholder. When no documents were
        retrieved the placeholder is removed so the model never sees the
        raw template artifact.
        """
        return prompt_content.replace("{summaries}", docs_together or "")

    def validate_template(self, prompt_content: str) -> bool:
        """Validate prompt template syntax"""
        return self.template_engine.validate_template(prompt_content)

    def extract_variables(self, prompt_content: str) -> set[str]:
        """Extract all variable names from prompt template"""
        return self.template_engine.extract_variables(prompt_content)
