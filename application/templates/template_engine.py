import logging
from typing import Any, Dict, List, Optional, Set

from jinja2 import (
    ChainableUndefined,
    Environment,
    nodes,
    select_autoescape,
    TemplateSyntaxError,
)
from jinja2.exceptions import UndefinedError

logger = logging.getLogger(__name__)


class TemplateRenderError(Exception):
    """Raised when template rendering fails"""

    pass


class TemplateEngine:
    """Jinja2-based template engine for dynamic prompt rendering"""

    def __init__(self):
        self._env = Environment(
            undefined=ChainableUndefined,
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
        except TemplateSyntaxError as e:
            logger.debug(f"Template syntax invalid at line {e.lineno}: {e.message}")
            return False
        except Exception as e:
            logger.debug(f"Template validation error: {type(e).__name__}: {str(e)}")
            return False

    def extract_variables(self, template_content: str) -> Set[str]:
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
        except TemplateSyntaxError as e:
            logger.debug(f"Cannot extract variables - syntax error at line {e.lineno}")
            return set()
        except Exception as e:
            logger.debug(f"Cannot extract variables: {type(e).__name__}")
            return set()

    def extract_tool_usages(
        self, template_content: str
    ) -> Dict[str, Set[Optional[str]]]:
        """Extract tool and action references from a template"""
        if not template_content:
            return {}
        try:
            ast = self._env.parse(template_content)
        except TemplateSyntaxError as e:
            logger.debug(f"extract_tool_usages - syntax error at line {e.lineno}")
            return {}
        except Exception as e:
            logger.debug(f"extract_tool_usages - parse error: {type(e).__name__}")
            return {}

        usages: Dict[str, Set[Optional[str]]] = {}

        def record(path: List[str]) -> None:
            if not path:
                return
            tool_name = path[0]
            action_name = path[1] if len(path) > 1 else None
            if not tool_name:
                return
            tool_entry = usages.setdefault(tool_name, set())
            tool_entry.add(action_name)

        for node in ast.find_all(nodes.Getattr):
            path = []
            current = node
            while isinstance(current, nodes.Getattr):
                path.append(current.attr)
                current = current.node
            if isinstance(current, nodes.Name) and current.name == "tools":
                path.reverse()
                record(path)

        for node in ast.find_all(nodes.Getitem):
            path = []
            current = node
            while isinstance(current, nodes.Getitem):
                key = current.arg
                if isinstance(key, nodes.Const) and isinstance(key.value, str):
                    path.append(key.value)
                else:
                    path = []
                    break
                current = current.node
            if path and isinstance(current, nodes.Name) and current.name == "tools":
                path.reverse()
                record(path)

        return usages
