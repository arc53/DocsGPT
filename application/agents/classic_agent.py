import logging
from typing import Dict, Generator

from application.agents.base import BaseAgent
from application.logging import LogContext

logger = logging.getLogger(__name__)


class ClassicAgent(BaseAgent):
    """A simplified agent with clear execution flow"""

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        """Core generator function for ClassicAgent execution flow"""

        tools_dict = (
            self._get_user_tools(self.user)
            if not self.user_api_key
            else self._get_tools(self.user_api_key)
        )
        self._prepare_tools(tools_dict)

        messages = self._build_messages(self.prompt, query)
        llm_response = self._llm_gen(messages, log_context)

        yield from self._handle_response(
            llm_response, tools_dict, messages, log_context
        )

        yield {"sources": self.retrieved_docs}
        yield {"tool_calls": self._get_truncated_tool_calls()}

        log_context.stacks.append(
            {"component": "agent", "data": {"tool_calls": self.tool_calls.copy()}}
        )
