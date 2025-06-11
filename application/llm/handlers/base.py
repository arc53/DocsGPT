import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Union

from application.logging import build_stack_data

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a tool/function call from the LLM."""

    id: str
    name: str
    arguments: Union[str, Dict]
    index: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "ToolCall":
        """Create ToolCall from dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
            index=data.get("index"),
        )


@dataclass
class LLMResponse:
    """Represents a response from the LLM."""

    content: str
    tool_calls: List[ToolCall]
    finish_reason: str
    raw_response: Any

    @property
    def requires_tool_call(self) -> bool:
        """Check if the response requires tool calls."""
        return bool(self.tool_calls) and self.finish_reason == "tool_calls"


class LLMHandler(ABC):
    """Abstract base class for LLM handlers."""

    def __init__(self):
        self.llm_calls = []
        self.tool_calls = []

    @abstractmethod
    def parse_response(self, response: Any) -> LLMResponse:
        """Parse raw LLM response into standardized format."""
        pass

    @abstractmethod
    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        """Create a tool result message for the conversation history."""
        pass

    @abstractmethod
    def _iterate_stream(self, response: Any) -> Generator:
        """Iterate through streaming response chunks."""
        pass

    def process_message_flow(
        self,
        agent,
        initial_response,
        tools_dict: Dict,
        messages: List[Dict],
        attachments: Optional[List] = None,
        stream: bool = False,
    ) -> Union[str, Generator]:
        """
        Main orchestration method for processing LLM message flow.

        Args:
            agent: The agent instance
            initial_response: Initial LLM response
            tools_dict: Dictionary of available tools
            messages: Conversation history
            attachments: Optional attachments
            stream: Whether to use streaming

        Returns:
            Final response or generator for streaming
        """
        messages = self.prepare_messages(agent, messages, attachments)

        if stream:
            return self.handle_streaming(agent, initial_response, tools_dict, messages)
        else:
            return self.handle_non_streaming(
                agent, initial_response, tools_dict, messages
            )

    def prepare_messages(
        self, agent, messages: List[Dict], attachments: Optional[List] = None
    ) -> List[Dict]:
        """
        Prepare messages with attachments and provider-specific formatting.

        Args:
            agent: The agent instance
            messages: Original messages
            attachments: List of attachments

        Returns:
            Prepared messages list
        """
        if not attachments:
            return messages
        logger.info(f"Preparing messages with {len(attachments)} attachments")
        supported_types = agent.llm.get_supported_attachment_types()

        supported_attachments = [
            a for a in attachments if a.get("mime_type") in supported_types
        ]
        unsupported_attachments = [
            a for a in attachments if a.get("mime_type") not in supported_types
        ]

        # Process supported attachments with the LLM's custom method

        if supported_attachments:
            logger.info(
                f"Processing {len(supported_attachments)} supported attachments"
            )
            messages = agent.llm.prepare_messages_with_attachments(
                messages, supported_attachments
            )
        # Process unsupported attachments with default method

        if unsupported_attachments:
            logger.info(
                f"Processing {len(unsupported_attachments)} unsupported attachments"
            )
            messages = self._append_unsupported_attachments(
                messages, unsupported_attachments
            )
        return messages

    def _append_unsupported_attachments(
        self, messages: List[Dict], attachments: List[Dict]
    ) -> List[Dict]:
        """
        Default method to append unsupported attachment content to system prompt.

        Args:
            messages: Current messages
            attachments: List of unsupported attachments

        Returns:
            Updated messages list
        """
        prepared_messages = messages.copy()
        attachment_texts = []

        for attachment in attachments:
            logger.info(f"Adding attachment {attachment.get('id')} to context")
            if "content" in attachment:
                attachment_texts.append(
                    f"Attached file content:\n\n{attachment['content']}"
                )
        if attachment_texts:
            combined_text = "\n\n".join(attachment_texts)

            system_msg = next(
                (msg for msg in prepared_messages if msg.get("role") == "system"),
                {"role": "system", "content": ""},
            )

            if system_msg not in prepared_messages:
                prepared_messages.insert(0, system_msg)
            system_msg["content"] += f"\n\n{combined_text}"
        return prepared_messages

    def handle_tool_calls(
        self, agent, tool_calls: List[ToolCall], tools_dict: Dict, messages: List[Dict]
    ) -> Generator:
        """
        Execute tool calls and update conversation history.

        Args:
            agent: The agent instance
            tool_calls: List of tool calls to execute
            tools_dict: Available tools dictionary
            messages: Current conversation history

        Returns:
            Updated messages list
        """
        updated_messages = messages.copy()

        for call in tool_calls:
            try:
                self.tool_calls.append(call)
                tool_executor_gen = agent._execute_tool_action(tools_dict, call)
                while True:
                    try:
                        yield next(tool_executor_gen)
                    except StopIteration as e:
                        tool_response, call_id = e.value
                        break

                updated_messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "function_call": {
                                    "name": call.name,
                                    "args": call.arguments,
                                    "call_id": call_id,
                                }
                            }
                        ],
                    }
                )

                updated_messages.append(self.create_tool_message(call, tool_response))

            except Exception as e:
                logger.error(f"Error executing tool: {str(e)}", exc_info=True)
                updated_messages.append(
                    {
                        "role": "tool",
                        "content": f"Error executing tool: {str(e)}",
                        "tool_call_id": call.id,
                    }
                )

        return updated_messages

    def handle_non_streaming(
        self, agent, response: Any, tools_dict: Dict, messages: List[Dict]
    ) -> Generator:
        """
        Handle non-streaming response flow.

        Args:
            agent: The agent instance
            response: Current LLM response
            tools_dict: Available tools dictionary
            messages: Conversation history

        Returns:
            Final response after processing all tool calls
        """
        parsed = self.parse_response(response)
        self.llm_calls.append(build_stack_data(agent.llm))

        while parsed.requires_tool_call:
            tool_handler_gen = self.handle_tool_calls(
                agent, parsed.tool_calls, tools_dict, messages
            )
            while True:
                try:
                    yield next(tool_handler_gen)
                except StopIteration as e:
                    messages = e.value
                    break

            response = agent.llm.gen(
                model=agent.gpt_model, messages=messages, tools=agent.tools
            )
            parsed = self.parse_response(response)
            self.llm_calls.append(build_stack_data(agent.llm))

        return parsed.content

    def handle_streaming(
        self, agent, response: Any, tools_dict: Dict, messages: List[Dict]
    ) -> Generator:
        """
        Handle streaming response flow.

        Args:
            agent: The agent instance
            response: Current LLM response
            tools_dict: Available tools dictionary
            messages: Conversation history

        Yields:
            Streaming response chunks
        """
        buffer = ""
        tool_calls = {}

        for chunk in self._iterate_stream(response):
            if isinstance(chunk, str):
                yield chunk
                continue
            parsed = self.parse_response(chunk)

            if parsed.tool_calls:
                for call in parsed.tool_calls:
                    if call.index not in tool_calls:
                        tool_calls[call.index] = call
                    else:
                        existing = tool_calls[call.index]
                        if call.id:
                            existing.id = call.id
                        if call.name:
                            existing.name = call.name
                        if call.arguments:
                            existing.arguments += call.arguments
            if parsed.finish_reason == "tool_calls":
                tool_handler_gen = self.handle_tool_calls(
                    agent, list(tool_calls.values()), tools_dict, messages
                )
                while True:
                    try:
                        yield next(tool_handler_gen)
                    except StopIteration as e:
                        messages = e.value
                        break
                tool_calls = {}

                response = agent.llm.gen_stream(
                    model=agent.gpt_model, messages=messages, tools=agent.tools
                )
                self.llm_calls.append(build_stack_data(agent.llm))

                yield from self.handle_streaming(agent, response, tools_dict, messages)
                return
            if parsed.content:
                buffer += parsed.content
                yield buffer
                buffer = ""
            if parsed.finish_reason == "stop":
                return
