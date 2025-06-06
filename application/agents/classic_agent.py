from typing import Dict, Generator
from application.agents.base import BaseAgent
from application.logging import LogContext
from application.retriever.base import BaseRetriever
import logging

logger = logging.getLogger(__name__)


class ClassicAgent(BaseAgent):
    """A simplified classic agent with clear execution flow.

    Usage:
    1. Processes a query through retrieval
    2. Sets up available tools
    3. Generates responses using LLM
    4. Handles tool interactions if needed
    5. Returns standardized outputs

    Easy to extend by overriding specific steps.
    """

    def _gen_inner(
        self, query: str, retriever: BaseRetriever, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        """Main execution flow for the agent."""
        # Step 1: Retrieve relevant data
        retrieved_data = self._retriever_search(retriever, query, log_context)

        # Step 2: Prepare tools
        tools_dict = (
            self._get_user_tools(self.user)
            if not self.user_api_key
            else self._get_tools(self.user_api_key)
        )
        self._prepare_tools(tools_dict)

        # Step 3: Build and process messages
        messages = self._build_messages(self.prompt, query, retrieved_data)
        llm_response = self._llm_gen(messages, log_context)

        # Step 4: Handle the response
        yield from self._handle_response(
            llm_response, tools_dict, messages, log_context
        )

        # Step 5: Return metadata
        yield {"sources": retrieved_data}
        yield {"tool_calls": self._get_truncated_tool_calls()}

        # Log tool calls for debugging
        log_context.stacks.append(
            {"component": "agent", "data": {"tool_calls": self.tool_calls.copy()}}
        )

    def _handle_response(self, response, tools_dict, messages, log_context):
        """Handle different types of LLM responses consistently."""
        # Handle simple string responses
        if isinstance(response, str):
            yield {"answer": response}
            return

        # Handle content from message objects
        if hasattr(response, "message") and getattr(response.message, "content", None):
            yield {"answer": response.message.content}
            return

        # Handle complex responses that may require tool use
        processed_response = self._llm_handler(
            response, tools_dict, messages, log_context, self.attachments
        )

        # Yield the final processed response
        if isinstance(processed_response, str):
            yield {"answer": processed_response}
        elif hasattr(processed_response, "message") and getattr(
            processed_response.message, "content", None
        ):
            yield {"answer": processed_response.message.content}
        else:
            for line in processed_response:
                if isinstance(line, str):
                    yield {"answer": line}

    def _get_truncated_tool_calls(self):
        """Return tool calls with truncated results for cleaner output."""
        return [
            {
                **tool_call,
                "result": (
                    f"{str(tool_call['result'])[:50]}..."
                    if len(str(tool_call["result"])) > 50
                    else tool_call["result"]
                ),
            }
            for tool_call in self.tool_calls
        ]
