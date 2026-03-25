import logging
from typing import Dict, Generator, Optional

from application.agents.base import BaseAgent
from application.agents.tools.internal_search import (
    INTERNAL_TOOL_ENTRY,
    INTERNAL_TOOL_ID,
    build_internal_tool_config,
)
from application.logging import LogContext

logger = logging.getLogger(__name__)


class AgenticAgent(BaseAgent):
    """Agent where the LLM controls retrieval via tools.

    Unlike ClassicAgent which pre-fetches docs into the prompt,
    AgenticAgent gives the LLM an internal_search tool so it can
    decide when, what, and whether to search.
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
        # 1. Get user tools (same as ClassicAgent)
        tools_dict = self.tool_executor.get_tools()

        # 2. Add internal search as a synthetic tool (only if sources are configured)
        source = self.retriever_config.get("source", {})
        has_sources = bool(source.get("active_docs"))
        if self.retriever_config and has_sources:
            internal_entry = dict(INTERNAL_TOOL_ENTRY)
            internal_entry["config"] = build_internal_tool_config(
                **self.retriever_config
            )
            tools_dict[INTERNAL_TOOL_ID] = internal_entry

        # 3. Prepare all tools for the LLM
        self._prepare_tools(tools_dict)

        # 4. Build messages (prompt has NO pre-fetched docs)
        messages = self._build_messages(self.prompt, query)

        # 5. Call LLM — the handler manages the tool loop
        llm_response = self._llm_gen(messages, log_context)

        yield from self._handle_response(
            llm_response, tools_dict, messages, log_context
        )

        # 6. Collect sources from internal search tool results
        self._collect_internal_sources()

        yield {"sources": self.retrieved_docs}
        yield {"tool_calls": self._get_truncated_tool_calls()}

        log_context.stacks.append(
            {"component": "agent", "data": {"tool_calls": self.tool_calls.copy()}}
        )

    def _collect_internal_sources(self):
        """Collect retrieved docs from the cached InternalSearchTool instance."""
        cache_key = f"internal_search:{INTERNAL_TOOL_ID}:{self.user or ''}"
        tool = self.tool_executor._loaded_tools.get(cache_key)
        if tool and hasattr(tool, "retrieved_docs") and tool.retrieved_docs:
            self.retrieved_docs = tool.retrieved_docs
