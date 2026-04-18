import json
import logging
from typing import Dict, List, Optional

from application.agents.tools.base import Tool
from application.core.settings import settings
from application.retriever.retriever_creator import RetrieverCreator

logger = logging.getLogger(__name__)


class InternalSearchTool(Tool):
    """Wraps the ClassicRAG retriever as an LLM-callable tool.

    Instead of pre-fetching docs into the prompt, the LLM decides
    when and what to search. Supports multiple searches per session.

    Optional capabilities (enabled when sources have directory_structure):
    - path_filter on search: restrict results to a specific file/folder
    - list_files action: browse the file/folder structure
    """

    internal = True

    def __init__(self, config: Dict):
        self.config = config
        self.retrieved_docs: List[Dict] = []
        self._retriever = None
        self._directory_structure: Optional[Dict] = None
        self._dir_structure_loaded = False

    def _get_retriever(self):
        if self._retriever is None:
            self._retriever = RetrieverCreator.create_retriever(
                self.config.get("retriever_name", "classic"),
                source=self.config.get("source", {}),
                chat_history=[],
                prompt="",
                chunks=int(self.config.get("chunks", 2)),
                doc_token_limit=int(self.config.get("doc_token_limit", 50000)),
                model_id=self.config.get("model_id", "docsgpt-local"),
                user_api_key=self.config.get("user_api_key"),
                agent_id=self.config.get("agent_id"),
                llm_name=self.config.get("llm_name", settings.LLM_PROVIDER),
                api_key=self.config.get("api_key", settings.API_KEY),
                decoded_token=self.config.get("decoded_token"),
            )
        return self._retriever

    def _get_directory_structure(self) -> Optional[Dict]:
        """Load directory structure from Postgres for the configured sources."""
        if self._dir_structure_loaded:
            return self._directory_structure

        self._dir_structure_loaded = True
        source = self.config.get("source", {})
        active_docs = source.get("active_docs", [])
        if not active_docs:
            return None

        try:
            # Per-operation session: this tool runs inside the answer
            # generator hot path, so we open a short-lived read
            # connection for the batch lookup and release immediately.
            from application.storage.db.repositories.sources import (
                SourcesRepository,
            )
            from application.storage.db.session import db_readonly

            if isinstance(active_docs, str):
                active_docs = [active_docs]

            decoded_token = self.config.get("decoded_token") or {}
            user_id = decoded_token.get("sub") if decoded_token else None

            merged_structure = {}
            with db_readonly() as conn:
                repo = SourcesRepository(conn)
                for doc_id in active_docs:
                    try:
                        source_doc = repo.get_any(str(doc_id), user_id) if user_id else None
                        if not source_doc:
                            continue
                        dir_str = source_doc.get("directory_structure")
                        if dir_str:
                            if isinstance(dir_str, str):
                                dir_str = json.loads(dir_str)
                            source_name = source_doc.get("name", doc_id)
                            if len(active_docs) > 1:
                                merged_structure[source_name] = dir_str
                            else:
                                merged_structure = dir_str
                    except Exception as e:
                        logger.debug(f"Could not load dir structure for {doc_id}: {e}")

            self._directory_structure = merged_structure if merged_structure else None
        except Exception as e:
            logger.debug(f"Failed to load directory structures: {e}")

        return self._directory_structure

    def execute_action(self, action_name: str, **kwargs):
        if action_name == "search":
            return self._execute_search(**kwargs)
        elif action_name == "list_files":
            return self._execute_list_files(**kwargs)
        return f"Unknown action: {action_name}"

    def _execute_search(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        path_filter = kwargs.get("path_filter", "")

        if not query:
            return "Error: 'query' parameter is required."

        try:
            retriever = self._get_retriever()
            docs = retriever.search(query)
        except Exception as e:
            logger.error(f"Internal search failed: {e}", exc_info=True)
            return "Search failed: an internal error occurred."

        if not docs:
            return "No documents found matching your query."

        # Apply path filter if specified
        if path_filter:
            path_lower = path_filter.lower()
            docs = [
                d
                for d in docs
                if path_lower in d.get("source", "").lower()
                or path_lower in d.get("filename", "").lower()
                or path_lower in d.get("title", "").lower()
            ]
            if not docs:
                return f"No documents found matching query '{query}' in path '{path_filter}'."

        # Accumulate for source tracking
        for doc in docs:
            if doc not in self.retrieved_docs:
                self.retrieved_docs.append(doc)

        # Format results for the LLM
        formatted = []
        for i, doc in enumerate(docs, 1):
            title = doc.get("title", "Untitled")
            text = doc.get("text", "")
            source = doc.get("source", "Unknown")
            filename = doc.get("filename", "")
            header = filename or title
            formatted.append(f"[{i}] {header} (source: {source})\n{text}")

        return "\n\n---\n\n".join(formatted)

    def _execute_list_files(self, **kwargs) -> str:
        path = kwargs.get("path", "")
        dir_structure = self._get_directory_structure()

        if not dir_structure:
            return "No file structure available for the current sources."

        # Navigate to the requested path
        current = dir_structure
        if path:
            for part in path.strip("/").split("/"):
                if not part:
                    continue
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return f"Path '{path}' not found in the file structure."

        # Format the structure for the LLM
        return self._format_structure(current, path or "/")

    def _format_structure(self, node: Dict, current_path: str) -> str:
        if not isinstance(node, dict):
            return f"'{current_path}' is a file, not a directory."

        lines = [f"File structure at '{current_path}':\n"]
        folders = []
        files = []

        for name, value in sorted(node.items()):
            if isinstance(value, dict):
                # Check if it's a file metadata dict or a folder
                if "type" in value or "size_bytes" in value or "token_count" in value:
                    # It's a file with metadata
                    size = value.get("token_count", "")
                    ftype = value.get("type", "")
                    info_parts = []
                    if ftype:
                        info_parts.append(ftype)
                    if size:
                        info_parts.append(f"{size} tokens")
                    info = f" ({', '.join(info_parts)})" if info_parts else ""
                    files.append(f"  {name}{info}")
                else:
                    # It's a folder
                    count = self._count_files(value)
                    folders.append(f"  {name}/ ({count} items)")
            else:
                files.append(f"  {name}")

        if folders:
            lines.append("Folders:")
            lines.extend(folders)
        if files:
            lines.append("Files:")
            lines.extend(files)
        if not folders and not files:
            lines.append("  (empty)")

        return "\n".join(lines)

    def _count_files(self, node: Dict) -> int:
        count = 0
        for value in node.values():
            if isinstance(value, dict):
                if "type" in value or "size_bytes" in value or "token_count" in value:
                    count += 1
                else:
                    count += self._count_files(value)
            else:
                count += 1
        return count

    def get_actions_metadata(self):
        actions = [
            {
                "name": "search",
                "description": (
                    "Search the user's uploaded documents and knowledge base. "
                    "Use this to find relevant information before answering questions. "
                    "You can call this multiple times with different queries."
                ),
                "parameters": {
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query. Be specific and focused.",
                            "filled_by_llm": True,
                            "required": True,
                        },
                    }
                },
            }
        ]

        # Add path_filter and list_files only if directory structure exists
        has_structure = self.config.get("has_directory_structure", False)
        if has_structure:
            actions[0]["parameters"]["properties"]["path_filter"] = {
                "type": "string",
                "description": (
                    "Optional: filter results to a specific file or folder path. "
                    "Use list_files first to see available paths."
                ),
                "filled_by_llm": True,
                "required": False,
            }
            actions.append(
                {
                    "name": "list_files",
                    "description": (
                        "Browse the file and folder structure of the knowledge base. "
                        "Use this to see what files are available before searching. "
                        "Optionally provide a path to browse a specific folder."
                    ),
                    "parameters": {
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Optional: folder path to browse. Leave empty for root.",
                                "filled_by_llm": True,
                                "required": False,
                            }
                        }
                    },
                }
            )

        return actions

    def get_config_requirements(self):
        return {}


# Constants for building synthetic tools_dict entries
INTERNAL_TOOL_ID = "internal"


def build_internal_tool_entry(has_directory_structure: bool = False) -> Dict:
    """Build the tools_dict entry for InternalSearchTool.

    Dynamically includes list_files and path_filter based on
    whether the sources have directory structure.
    """
    search_params = {
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and focused.",
                "filled_by_llm": True,
                "required": True,
            }
        }
    }

    actions = [
        {
            "name": "search",
            "description": (
                "Search the user's uploaded documents and knowledge base. "
                "Use this to find relevant information before answering questions. "
                "You can call this multiple times with different queries."
            ),
            "active": True,
            "parameters": search_params,
        }
    ]

    if has_directory_structure:
        search_params["properties"]["path_filter"] = {
            "type": "string",
            "description": (
                "Optional: filter results to a specific file or folder path. "
                "Use list_files first to see available paths."
            ),
            "filled_by_llm": True,
            "required": False,
        }
        actions.append(
            {
                "name": "list_files",
                "description": (
                    "Browse the file and folder structure of the knowledge base. "
                    "Use this to see what files are available before searching. "
                    "Optionally provide a path to browse a specific folder."
                ),
                "active": True,
                "parameters": {
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Optional: folder path to browse. Leave empty for root.",
                            "filled_by_llm": True,
                            "required": False,
                        }
                    }
                },
            }
        )

    return {"name": "internal_search", "actions": actions}


# Keep backward compat
INTERNAL_TOOL_ENTRY = build_internal_tool_entry(has_directory_structure=False)


def sources_have_directory_structure(source: Dict) -> bool:
    """Check if any of the active sources have a ``directory_structure`` row."""
    active_docs = source.get("active_docs", [])
    if not active_docs:
        return False

    try:
        # TODO(pg-cutover): SourcesRepository.get_any requires ``user_id``
        # scoping, but callers in the agent build path don't always
        # thread the decoded token through here. Use a direct
        # short-lived SQL lookup instead of the repo until the call
        # sites are updated to propagate user context.
        from sqlalchemy import text as _text

        from application.storage.db.session import db_readonly

        if isinstance(active_docs, str):
            active_docs = [active_docs]

        with db_readonly() as conn:
            for doc_id in active_docs:
                try:
                    value = str(doc_id)
                    if len(value) == 36 and "-" in value:
                        row = conn.execute(
                            _text(
                                "SELECT directory_structure FROM sources "
                                "WHERE id = CAST(:id AS uuid)"
                            ),
                            {"id": value},
                        ).fetchone()
                    else:
                        row = conn.execute(
                            _text(
                                "SELECT directory_structure FROM sources "
                                "WHERE legacy_mongo_id = :lid"
                            ),
                            {"lid": value},
                        ).fetchone()
                    if row is not None and row[0]:
                        return True
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"Could not check directory structure: {e}")

    return False


def add_internal_search_tool(tools_dict: Dict, retriever_config: Dict) -> None:
    """Add the internal search tool to tools_dict if sources are configured.

    Shared by AgenticAgent and ResearchAgent to avoid duplicate setup logic.
    Mutates tools_dict in place.
    """
    source = retriever_config.get("source", {})
    has_sources = bool(source.get("active_docs"))
    if not retriever_config or not has_sources:
        return

    has_dir = sources_have_directory_structure(source)
    internal_entry = build_internal_tool_entry(has_directory_structure=has_dir)
    internal_entry["config"] = build_internal_tool_config(
        **retriever_config,
        has_directory_structure=has_dir,
    )
    tools_dict[INTERNAL_TOOL_ID] = internal_entry


def build_internal_tool_config(
    source: Dict,
    retriever_name: str = "classic",
    chunks: int = 2,
    doc_token_limit: int = 50000,
    model_id: str = "docsgpt-local",
    user_api_key: Optional[str] = None,
    agent_id: Optional[str] = None,
    llm_name: str = None,
    api_key: str = None,
    decoded_token: Optional[Dict] = None,
    has_directory_structure: bool = False,
) -> Dict:
    """Build the config dict for InternalSearchTool."""
    return {
        "source": source,
        "retriever_name": retriever_name,
        "chunks": chunks,
        "doc_token_limit": doc_token_limit,
        "model_id": model_id,
        "user_api_key": user_api_key,
        "agent_id": agent_id,
        "llm_name": llm_name or settings.LLM_PROVIDER,
        "api_key": api_key or settings.API_KEY,
        "decoded_token": decoded_token,
        "has_directory_structure": has_directory_structure,
    }
