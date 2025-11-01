import logging
from typing import Any, Dict, Optional

from application.templates.namespaces import NamespaceManager

from application.templates.template_engine import TemplateEngine, TemplateRenderError

logger = logging.getLogger(__name__)


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

        Handles legacy {summaries} and {query} placeholders during transition period.
        """
        if docs_together:
            prompt_content = prompt_content.replace("{summaries}", docs_together)
        return prompt_content

    def validate_template(self, prompt_content: str) -> bool:
        """Validate prompt template syntax"""
        return self.template_engine.validate_template(prompt_content)

    def extract_variables(self, prompt_content: str) -> set[str]:
        """Extract all variable names from prompt template"""
        return self.template_engine.extract_variables(prompt_content)
