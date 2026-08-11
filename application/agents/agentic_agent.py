import logging
from typing import Dict, Generator, Optional

from application.agents.base import BaseAgent
from application.agents.tools.internal_search import add_internal_search_tool
from application.agents.tools.wiki import add_wiki_tool
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
        wiki_config: Optional[Dict] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.retriever_config = retriever_config or {}
        self.wiki_config = wiki_config or {}

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        tools_dict = self.tool_executor.get_tools()
        add_internal_search_tool(tools_dict, self.retriever_config)
        if self.wiki_config:
            add_wiki_tool(tools_dict, self.wiki_config)
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
