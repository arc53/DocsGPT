import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class NamespaceBuilder(ABC):
    """Base class for building template context namespaces"""

    @abstractmethod
    def build(self, **kwargs) -> Dict[str, Any]:
        """Build namespace context dictionary"""
        pass

    @property
    @abstractmethod
    def namespace_name(self) -> str:
        """Name of this namespace for template access"""
        pass


class SystemNamespace(NamespaceBuilder):
    """System metadata namespace: {{ system.* }}"""

    @property
    def namespace_name(self) -> str:
        return "system"

    def build(
        self, request_id: Optional[str] = None, user_id: Optional[str] = None, **kwargs
    ) -> Dict[str, Any]:
        """
        Build system context with metadata.

        Args:
            request_id: Unique request identifier
            user_id: Current user identifier

        Returns:
            Dictionary with system variables
        """
        now = datetime.now(timezone.utc)

        return {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": now.isoformat(),
            "request_id": request_id or str(uuid.uuid4()),
            "user_id": user_id,
        }


class PassthroughNamespace(NamespaceBuilder):
    """Request parameters namespace: {{ passthrough.* }}"""

    @property
    def namespace_name(self) -> str:
        return "passthrough"

    def build(
        self, passthrough_data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Dict[str, Any]:
        """
        Build passthrough context from request parameters.

        Args:
            passthrough_data: Dictionary of parameters from web request

        Returns:
            Dictionary with passthrough variables
        """
        if not passthrough_data:
            return {}
        safe_data = {}
        for key, value in passthrough_data.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                safe_data[key] = value
            else:
                logger.warning(
                    f"Skipping non-serializable passthrough value for key '{key}': {type(value)}"
                )
        return safe_data


class SourceNamespace(NamespaceBuilder):
    """RAG source documents namespace: {{ source.* }}"""

    @property
    def namespace_name(self) -> str:
        return "source"

    def build(
        self, docs: Optional[list] = None, docs_together: Optional[str] = None, **kwargs
    ) -> Dict[str, Any]:
        """
        Build source context from RAG retrieval results.

        Args:
            docs: List of retrieved documents
            docs_together: Concatenated document content (for backward compatibility)

        Returns:
            Dictionary with source variables
        """
        context = {}

        if docs:
            context["documents"] = docs
            context["count"] = len(docs)
        if docs_together:
            context["docs_together"] = docs_together  # Add docs_together for custom templates
            context["content"] = docs_together
            context["summaries"] = docs_together
        return context


class ToolsNamespace(NamespaceBuilder):
    """Pre-executed tools namespace: {{ tools.* }}"""

    @property
    def namespace_name(self) -> str:
        return "tools"

    def build(
        self, tools_data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Dict[str, Any]:
        """
        Build tools context with pre-executed tool results.

        Args:
            tools_data: Dictionary of pre-fetched tool results organized by tool name
                       e.g., {"memory": {"notes": "content", "tasks": "list"}}

        Returns:
            Dictionary with tool results organized by tool name
        """
        if not tools_data:
            return {}

        safe_data = {}
        for tool_name, tool_result in tools_data.items():
            if isinstance(tool_result, (str, dict, list, int, float, bool, type(None))):
                safe_data[tool_name] = tool_result
            else:
                logger.warning(
                    f"Skipping non-serializable tool result for '{tool_name}': {type(tool_result)}"
                )
        return safe_data


class NamespaceManager:
    """Manages all namespace builders and context assembly"""

    def __init__(self):
        self._builders = {
            "system": SystemNamespace(),
            "passthrough": PassthroughNamespace(),
            "source": SourceNamespace(),
            "tools": ToolsNamespace(),
        }

    def build_context(self, **kwargs) -> Dict[str, Any]:
        """
        Build complete template context from all namespaces.

        Args:
            **kwargs: Parameters to pass to namespace builders

        Returns:
            Complete context dictionary for template rendering
        """
        context = {}

        for namespace_name, builder in self._builders.items():
            try:
                namespace_context = builder.build(**kwargs)
                # Always include namespace, even if empty, to prevent undefined errors
                context[namespace_name] = namespace_context if namespace_context else {}
            except Exception as e:
                logger.error(f"Failed to build {namespace_name} namespace: {str(e)}")
                # Include empty namespace on error to prevent template failures
                context[namespace_name] = {}
        return context

    def get_builder(self, namespace_name: str) -> Optional[NamespaceBuilder]:
        """Get specific namespace builder"""
        return self._builders.get(namespace_name)
