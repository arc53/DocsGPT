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
    """

    def __init__(self, config: Dict):
        self.config = config
        self.retrieved_docs: List[Dict] = []
        self._retriever = None

    def _get_retriever(self):
        if self._retriever is None:
            self._retriever = RetrieverCreator.create_retriever(
                self.config.get("retriever_name", "classic"),
                source=self.config.get("source", {}),
                chat_history=[],  # no rephrasing — LLM controls the query
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

    def execute_action(self, action_name: str, **kwargs):
        if action_name != "search":
            return f"Unknown action: {action_name}"

        query = kwargs.get("query", "")
        if not query:
            return "Error: 'query' parameter is required."

        try:
            retriever = self._get_retriever()
            docs = retriever.search(query)
        except Exception as e:
            logger.error(f"Internal search failed: {e}", exc_info=True)
            return f"Search failed: {str(e)}"

        if not docs:
            return "No documents found matching your query."

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

    def get_actions_metadata(self):
        return [
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
                        }
                    }
                },
            }
        ]

    def get_config_requirements(self):
        return {}


# Constants for building synthetic tools_dict entries
INTERNAL_TOOL_ID = "internal"

INTERNAL_TOOL_ENTRY = {
    "name": "internal_search",
    "actions": [
        {
            "name": "search",
            "description": (
                "Search the user's uploaded documents and knowledge base. "
                "Use this to find relevant information before answering questions. "
                "You can call this multiple times with different queries."
            ),
            "active": True,
            "parameters": {
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Be specific and focused.",
                        "filled_by_llm": True,
                        "required": True,
                    }
                }
            },
        }
    ],
}


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
    }
