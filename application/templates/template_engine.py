import logging
from typing import Any, Dict

from jinja2 import Environment, select_autoescape, StrictUndefined, TemplateSyntaxError
from jinja2.exceptions import UndefinedError

logger = logging.getLogger(__name__)


class TemplateRenderError(Exception):
    """Raised when template rendering fails"""

    pass


class TemplateEngine:
    """Jinja2-based template engine for dynamic prompt rendering"""

    def __init__(self):
        self._env = Environment(
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=select_autoescape(default_for_string=True, default=True),
        )

    def render(self, template_content: str, context: Dict[str, Any]) -> str:
        """
        Render template with provided context.

        Args:
            template_content: Raw template string with Jinja2 syntax
            context: Dictionary of variables to inject into template

        Returns:
            Rendered template string

        Raises:
            TemplateRenderError: If template syntax is invalid or variables undefined
        """
        if not template_content:
            return ""
        try:
            template = self._env.from_string(template_content)
            return template.render(**context)
        except TemplateSyntaxError as e:
            error_msg = f"Template syntax error at line {e.lineno}: {e.message}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e
        except UndefinedError as e:
            error_msg = f"Undefined variable in template: {e.message}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e
        except Exception as e:
            error_msg = f"Template rendering failed: {str(e)}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e

    def validate_template(self, template_content: str) -> bool:
        """
        Validate template syntax without rendering.

        Args:
            template_content: Template string to validate

        Returns:
            True if template is syntactically valid
        """
        if not template_content:
            return True
        try:
            self._env.from_string(template_content)
            return True
        except TemplateSyntaxError:
            return False

    def extract_variables(self, template_content: str) -> set[str]:
        """
        Extract all variable names from template.

        Args:
            template_content: Template string to analyze

        Returns:
            Set of variable names found in template
        """
        if not template_content:
            return set()
        try:
            ast = self._env.parse(template_content)
            return set(self._env.get_template_module(ast).make_module().keys())
        except Exception:
            return set()
