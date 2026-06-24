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


# Artifact-reference metadata is the only thing that may enter template context;
# bytes (and anything non-primitive) are never exposed through this namespace.
_ARTIFACT_METADATA_KEYS = (
    "artifact_id",
    "version",
    "mime_type",
    "filename",
    "size",
    "kind",
    "title",
)


def _artifact_view(ref: Any) -> Optional[Dict[str, Any]]:
    """Project an artifact reference to a serializable metadata view, or None if it isn't one."""
    if not isinstance(ref, dict) or not ref.get("artifact_id"):
        return None
    view: Dict[str, Any] = {}
    for key in _ARTIFACT_METADATA_KEYS:
        value = ref.get(key)
        if isinstance(value, (str, int, float, bool, type(None))):
            view[key] = value
    # ``{{ artifacts.<name>.id }}`` is the documented accessor; mirror artifact_id to id.
    view["id"] = view.get("artifact_id")
    return view


class ArtifactsNamespace(NamespaceBuilder):
    """Artifact references namespace: {{ artifacts.<name>.id }} / .mime_type / .filename + artifact(id)."""

    @property
    def namespace_name(self) -> str:
        return "artifacts"

    def build(
        self,
        artifacts_data: Optional[Dict[str, Any]] = None,
        artifact_parent: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Build the artifacts namespace from named references plus a parent-scoped ``artifact(id)`` lookup.

        Args:
            artifacts_data: Map of output-variable name -> artifact reference dict.
            artifact_parent: Parent scope ({"conversation_id"|"workflow_run_id"}) for ``artifact(id)``.

        Returns:
            A dict of named metadata views plus an ``artifact`` callable; never any bytes.
        """
        context: Dict[str, Any] = {}
        for name, ref in (artifacts_data or {}).items():
            view = _artifact_view(ref)
            if view is not None:
                context[str(name)] = view
        context["artifact"] = self._make_lookup(artifact_parent or {})
        return context

    def _make_lookup(self, parent: Dict[str, Any]):
        """Return an ``artifact(id)`` helper that resolves metadata scoped to the run/conversation parent."""
        conversation_id = parent.get("conversation_id")
        workflow_run_id = parent.get("workflow_run_id")

        def artifact(artifact_id: Any) -> Dict[str, Any]:
            """Resolve one artifact's metadata by id, scoped to this parent (never cross-tenant)."""
            if not artifact_id or (conversation_id is None and workflow_run_id is None):
                return {}
            try:
                from application.storage.db.repositories.artifacts import (
                    ArtifactsRepository,
                )
                from application.storage.db.session import db_readonly

                with db_readonly() as conn:
                    repo = ArtifactsRepository(conn)
                    row = repo.get_artifact_in_parent(
                        str(artifact_id),
                        conversation_id=conversation_id,
                        workflow_run_id=workflow_run_id,
                    )
                    if row is None:
                        return {}
                    version = repo.get_version(str(artifact_id), row.get("current_version", 1))
            except Exception:
                logger.exception("Failed to resolve artifact %s in namespace", artifact_id)
                return {}
            view = {
                "artifact_id": str(row["id"]),
                "id": str(row["id"]),
                "version": row.get("current_version"),
                "kind": row.get("kind"),
                "title": row.get("title"),
            }
            if version is not None:
                for key in ("mime_type", "filename", "size"):
                    value = version.get(key)
                    if isinstance(value, (str, int, float, bool, type(None))):
                        view[key] = value
            return view

        return artifact


class NamespaceManager:
    """Manages all namespace builders and context assembly"""

    def __init__(self):
        self._builders = {
            "system": SystemNamespace(),
            "passthrough": PassthroughNamespace(),
            "source": SourceNamespace(),
            "tools": ToolsNamespace(),
            "artifacts": ArtifactsNamespace(),
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
