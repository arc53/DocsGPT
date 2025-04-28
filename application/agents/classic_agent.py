from typing import Dict, Generator

from application.agents.base import BaseAgent
from application.logging import LogContext

from application.retriever.base import BaseRetriever
import logging

logger = logging.getLogger(__name__)


class ClassicAgent(BaseAgent):
    def _gen_inner(
        self, query: str, retriever: BaseRetriever, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        retrieved_data = self._retriever_search(retriever, query, log_context)
        if self.user_api_key:
            tools_dict = self._get_tools(self.user_api_key)
        else:
            tools_dict = self._get_user_tools(self.user)
        self._prepare_tools(tools_dict)

        messages = self._build_messages(self.prompt, query, retrieved_data)

        resp = self._llm_gen(messages, log_context)

        attachments = self.attachments

        if isinstance(resp, str):
            yield {"answer": resp}
            return
        if (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            yield {"answer": resp.message.content}
            return

        resp = self._llm_handler(resp, tools_dict, messages, log_context, attachments)

        if isinstance(resp, str):
            yield {"answer": resp}
        elif (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            yield {"answer": resp.message.content}
        else:
            for line in resp:
                if isinstance(line, str):
                    yield {"answer": line}

        log_context.stacks.append(
            {"component": "agent", "data": {"tool_calls": self.tool_calls.copy()}}
        )

        yield {"sources": retrieved_data}
        yield {"tool_calls": self.tool_calls.copy()}
