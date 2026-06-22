import logging
from typing import Dict, Generator, Optional

from application.agents.base import BaseAgent
from application.agents.tools.internal_search import (
    INTERNAL_TOOL_ID,
    add_internal_search_tool,
)
from application.logging import LogContext

logger = logging.getLogger(__name__)


class ClassicAgent(BaseAgent):
    """A simplified agent with clear execution flow.

    Pre-fetches ``prefetch`` sources into the prompt and, when a
    ``retriever_config`` is supplied, also exposes ``agentic_tool`` sources
    via the internal_search tool. With no ``retriever_config`` (every source
    at the default ``prefetch`` exposure) no search tool is added and behavior
    is identical to plain pre-fetch.
    """

    def __init__(
        self,
        retriever_config: Optional[Dict] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.retriever_config = retriever_config or {}

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        """Core generator function for ClassicAgent execution flow"""

        tools_dict = self.tool_executor.get_tools()
        if self.retriever_config:
            add_internal_search_tool(tools_dict, self.retriever_config)
        self._prepare_tools(tools_dict)

        messages = self._build_messages(self.prompt, query)
        llm_response = self._llm_gen(messages, log_context)

        yield from self._handle_response(
            llm_response, tools_dict, messages, log_context
        )

        if self.retriever_config:
            self._collect_internal_sources()

        yield {"sources": self.retrieved_docs}
        yield {"tool_calls": self._get_truncated_tool_calls()}

        log_context.stacks.append(
            {"component": "agent", "data": {"tool_calls": self.tool_calls.copy()}}
        )

    def _collect_internal_sources(self):
        """Merge the cached InternalSearchTool's docs into ``retrieved_docs``,
        deduped, preserving any pre-fetched docs so a mixed-exposure agent cites
        both pre-fetched and tool-retrieved sources (not just the tool's)."""
        cache_key = f"internal_search:{INTERNAL_TOOL_ID}:{self.user or ''}"
        tool = self.tool_executor._loaded_tools.get(cache_key)
        if not (tool and getattr(tool, "retrieved_docs", None)):
            return

        def _key(d):
            if isinstance(d, dict):
                return (d.get("source"), d.get("title"), d.get("text"))
            return id(d)

        merged = list(self.retrieved_docs or [])
        seen = {_key(d) for d in merged}
        for doc in tool.retrieved_docs:
            k = _key(doc)
            if k not in seen:
                seen.add(k)
                merged.append(doc)
        self.retrieved_docs = merged
