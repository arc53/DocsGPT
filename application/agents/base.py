import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional

from application.agents.tool_executor import ToolExecutor
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.settings import settings
from application.llm.handlers.base import ToolCall
from application.llm.handlers.handler_creator import LLMHandlerCreator
from application.llm.llm_creator import LLMCreator
from application.logging import build_stack_data, log_activity, LogContext

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        endpoint: str,
        llm_name: str,
        model_id: str,
        api_key: str,
        agent_id: Optional[str] = None,
        user_api_key: Optional[str] = None,
        prompt: str = "",
        chat_history: Optional[List[Dict]] = None,
        retrieved_docs: Optional[List[Dict]] = None,
        decoded_token: Optional[Dict] = None,
        attachments: Optional[List[Dict]] = None,
        json_schema: Optional[Dict] = None,
        limited_token_mode: Optional[bool] = False,
        token_limit: Optional[int] = settings.DEFAULT_AGENT_LIMITS["token_limit"],
        limited_request_mode: Optional[bool] = False,
        request_limit: Optional[int] = settings.DEFAULT_AGENT_LIMITS["request_limit"],
        compressed_summary: Optional[str] = None,
        llm=None,
        llm_handler=None,
        tool_executor: Optional[ToolExecutor] = None,
        backup_models: Optional[List[str]] = None,
    ):
        self.endpoint = endpoint
        self.llm_name = llm_name
        self.model_id = model_id
        self.api_key = api_key
        self.agent_id = agent_id
        self.user_api_key = user_api_key
        self.prompt = prompt
        self.decoded_token = decoded_token or {}
        self.user: str = self.decoded_token.get("sub")
        self.tools: List[Dict] = []
        self.chat_history: List[Dict] = chat_history if chat_history is not None else []

        # Dependency injection for LLM — fall back to creating if not provided
        if llm is not None:
            self.llm = llm
        else:
            self.llm = LLMCreator.create_llm(
                llm_name,
                api_key=api_key,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
                model_id=model_id,
                agent_id=agent_id,
                backup_models=backup_models,
            )

        self.retrieved_docs = retrieved_docs or []

        if llm_handler is not None:
            self.llm_handler = llm_handler
        else:
            self.llm_handler = LLMHandlerCreator.create_handler(
                llm_name if llm_name else "default"
            )

        # Tool executor — injected or created
        if tool_executor is not None:
            self.tool_executor = tool_executor
        else:
            self.tool_executor = ToolExecutor(
                user_api_key=user_api_key,
                user=self.user,
                decoded_token=decoded_token,
            )

        self.attachments = attachments or []
        self.json_schema = None
        if json_schema is not None:
            try:
                self.json_schema = normalize_json_schema_payload(json_schema)
            except JsonSchemaValidationError as exc:
                logger.warning("Ignoring invalid JSON schema payload: %s", exc)
        self.limited_token_mode = limited_token_mode
        self.token_limit = token_limit
        self.limited_request_mode = limited_request_mode
        self.request_limit = request_limit
        self.compressed_summary = compressed_summary
        self.current_token_count = 0
        self.context_limit_reached = False

    @log_activity()
    def gen(
        self, query: str, log_context: LogContext = None
    ) -> Generator[Dict, None, None]:
        yield from self._gen_inner(query, log_context)

    @abstractmethod
    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        pass

    def gen_continuation(
        self,
        messages: List[Dict],
        tools_dict: Dict,
        pending_tool_calls: List[Dict],
        tool_actions: List[Dict],
    ) -> Generator[Dict, None, None]:
        """Resume generation after tool actions are resolved.

        Processes the client-provided *tool_actions* (approvals, denials,
        or client-side results), appends the resulting messages, then
        hands back to the LLM to continue the conversation.

        Args:
            messages: The saved messages array from the pause point.
            tools_dict: The saved tools dictionary.
            pending_tool_calls: The pending tool call descriptors from the pause.
            tool_actions: Client-provided actions resolving the pending calls.
        """
        self._prepare_tools(tools_dict)

        actions_by_id = {a["call_id"]: a for a in tool_actions}

        # Build a single assistant message containing all tool calls so
        # the message history matches the format LLM providers expect
        # (one assistant message with N tool_calls, followed by N tool results).
        tc_objects: List[Dict[str, Any]] = []
        for pending in pending_tool_calls:
            call_id = pending["call_id"]
            args = pending["arguments"]
            args_str = (
                json.dumps(args) if isinstance(args, dict) else (args or "{}")
            )
            tc_obj: Dict[str, Any] = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": pending["name"],
                    "arguments": args_str,
                },
            }
            if pending.get("thought_signature"):
                tc_obj["thought_signature"] = pending["thought_signature"]
            tc_objects.append(tc_obj)

        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": tc_objects,
        })

        # Now process each pending call and append tool result messages
        for pending in pending_tool_calls:
            call_id = pending["call_id"]
            args = pending["arguments"]
            action = actions_by_id.get(call_id)
            if not action:
                action = {
                    "call_id": call_id,
                    "decision": "denied",
                    "comment": "No response provided",
                }

            if action.get("decision") == "approved":
                # Execute the tool server-side
                tc = ToolCall(
                    id=call_id,
                    name=pending["name"],
                    arguments=(
                        json.dumps(args) if isinstance(args, dict) else args
                    ),
                )
                tool_gen = self._execute_tool_action(tools_dict, tc)
                tool_response = None
                while True:
                    try:
                        event = next(tool_gen)
                        yield event
                    except StopIteration as e:
                        tool_response, _ = e.value
                        break
                messages.append(
                    self.llm_handler.create_tool_message(tc, tool_response)
                )

            elif action.get("decision") == "denied":
                comment = action.get("comment", "")
                denial = (
                    f"Tool execution denied by user. Reason: {comment}"
                    if comment
                    else "Tool execution denied by user."
                )
                tc = ToolCall(
                    id=call_id, name=pending["name"], arguments=args
                )
                messages.append(
                    self.llm_handler.create_tool_message(tc, denial)
                )
                yield {
                    "type": "tool_call",
                    "data": {
                        "tool_name": pending.get("tool_name", "unknown"),
                        "call_id": call_id,
                        "action_name": f"{pending['action_name']}_{pending['tool_id']}",
                        "arguments": args,
                        "status": "denied",
                    },
                }

            elif "result" in action:
                result = action["result"]
                result_str = (
                    json.dumps(result)
                    if not isinstance(result, str)
                    else result
                )
                tc = ToolCall(
                    id=call_id, name=pending["name"], arguments=args
                )
                messages.append(
                    self.llm_handler.create_tool_message(tc, result_str)
                )
                yield {
                    "type": "tool_call",
                    "data": {
                        "tool_name": pending.get("tool_name", "unknown"),
                        "call_id": call_id,
                        "action_name": f"{pending['action_name']}_{pending['tool_id']}",
                        "arguments": args,
                        "result": (
                            result_str[:50] + "..."
                            if len(result_str) > 50
                            else result_str
                        ),
                        "status": "completed",
                    },
                }

        # Resume the LLM loop with the updated messages
        llm_response = self._llm_gen(messages)
        yield from self._handle_response(
            llm_response, tools_dict, messages, None
        )

        yield {"sources": self.retrieved_docs}
        yield {"tool_calls": self._get_truncated_tool_calls()}

    # ---- Tool delegation (thin wrappers around ToolExecutor) ----

    @property
    def tool_calls(self) -> List[Dict]:
        return self.tool_executor.tool_calls

    @tool_calls.setter
    def tool_calls(self, value: List[Dict]):
        self.tool_executor.tool_calls = value

    def _get_tools(self, api_key: str = None) -> Dict[str, Dict]:
        return self.tool_executor._get_tools_by_api_key(api_key or self.user_api_key)

    def _get_user_tools(self, user="local"):
        return self.tool_executor._get_user_tools(user)

    def _build_tool_parameters(self, action):
        return self.tool_executor._build_tool_parameters(action)

    def _prepare_tools(self, tools_dict):
        self.tools = self.tool_executor.prepare_tools_for_llm(tools_dict)

    def _execute_tool_action(self, tools_dict, call):
        return self.tool_executor.execute(
            tools_dict, call, self.llm.__class__.__name__
        )

    def _get_truncated_tool_calls(self):
        return self.tool_executor.get_truncated_tool_calls()

    # ---- Context / token management ----

    def _calculate_current_context_tokens(self, messages: List[Dict]) -> int:
        from application.api.answer.services.compression.token_counter import (
            TokenCounter,
        )
        return TokenCounter.count_message_tokens(messages)

    def _check_context_limit(self, messages: List[Dict]) -> bool:
        from application.core.model_utils import get_token_limit

        try:
            current_tokens = self._calculate_current_context_tokens(messages)
            self.current_token_count = current_tokens
            context_limit = get_token_limit(self.model_id)
            threshold = int(context_limit * settings.COMPRESSION_THRESHOLD_PERCENTAGE)

            if current_tokens >= threshold:
                logger.warning(
                    f"Context limit approaching: {current_tokens}/{context_limit} tokens "
                    f"({(current_tokens/context_limit)*100:.1f}%)"
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking context limit: {str(e)}", exc_info=True)
            return False

    def _validate_context_size(self, messages: List[Dict]) -> None:
        from application.core.model_utils import get_token_limit

        current_tokens = self._calculate_current_context_tokens(messages)
        self.current_token_count = current_tokens
        context_limit = get_token_limit(self.model_id)
        percentage = (current_tokens / context_limit) * 100

        if current_tokens >= context_limit:
            logger.warning(
                f"Context at limit: {current_tokens:,}/{context_limit:,} tokens "
                f"({percentage:.1f}%). Model: {self.model_id}"
            )
        elif current_tokens >= int(
            context_limit * settings.COMPRESSION_THRESHOLD_PERCENTAGE
        ):
            logger.info(
                f"Context approaching limit: {current_tokens:,}/{context_limit:,} tokens "
                f"({percentage:.1f}%)"
            )

    def _truncate_text_middle(self, text: str, max_tokens: int) -> str:
        from application.utils import num_tokens_from_string

        current_tokens = num_tokens_from_string(text)
        if current_tokens <= max_tokens:
            return text

        chars_per_token = len(text) / current_tokens if current_tokens > 0 else 4
        target_chars = int(max_tokens * chars_per_token * 0.95)

        if target_chars <= 0:
            return ""

        start_chars = int(target_chars * 0.4)
        end_chars = int(target_chars * 0.4)

        truncation_marker = "\n\n[... content truncated to fit context limit ...]\n\n"
        truncated = text[:start_chars] + truncation_marker + text[-end_chars:]

        logger.info(
            f"Truncated text from {current_tokens:,} to ~{max_tokens:,} tokens "
            f"(removed middle section)"
        )
        return truncated

    # ---- Message building ----

    def _build_messages(
        self,
        system_prompt: str,
        query: str,
    ) -> List[Dict]:
        """Build messages using pre-rendered system prompt"""
        from application.core.model_utils import get_token_limit
        from application.utils import num_tokens_from_string

        if self.compressed_summary:
            compression_context = (
                "\n\n---\n\n"
                "This session is being continued from a previous conversation that "
                "has been compressed to fit within context limits. "
                "The conversation is summarized below:\n\n"
                f"{self.compressed_summary}"
            )
            system_prompt = system_prompt + compression_context

        context_limit = get_token_limit(self.model_id)
        system_tokens = num_tokens_from_string(system_prompt)

        safety_buffer = int(context_limit * 0.1)
        available_after_system = context_limit - system_tokens - safety_buffer

        max_query_tokens = int(available_after_system * 0.8)
        query_tokens = num_tokens_from_string(query)

        if query_tokens > max_query_tokens:
            query = self._truncate_text_middle(query, max_query_tokens)
            query_tokens = num_tokens_from_string(query)

        available_for_history = max(available_after_system - query_tokens, 0)

        working_history = self._truncate_history_to_fit(
            self.chat_history,
            available_for_history,
        )

        messages = [{"role": "system", "content": system_prompt}]

        for i in working_history:
            if "prompt" in i and "response" in i:
                messages.append({"role": "user", "content": i["prompt"]})
                messages.append({"role": "assistant", "content": i["response"]})
            if "tool_calls" in i:
                for tool_call in i["tool_calls"]:
                    call_id = tool_call.get("call_id") or str(uuid.uuid4())
                    args = tool_call.get("arguments")
                    args_str = (
                        json.dumps(args)
                        if isinstance(args, dict)
                        else (args or "{}")
                    )
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_call.get("action_name", ""),
                                "arguments": args_str,
                            },
                        }],
                    })
                    result = tool_call.get("result")
                    result_str = (
                        json.dumps(result)
                        if not isinstance(result, str)
                        else (result or "")
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_str,
                    })
        messages.append({"role": "user", "content": query})
        return messages

    def _truncate_history_to_fit(
        self,
        history: List[Dict],
        max_tokens: int,
    ) -> List[Dict]:
        from application.utils import num_tokens_from_string

        if not history or max_tokens <= 0:
            return []

        truncated = []
        current_tokens = 0

        for message in reversed(history):
            message_tokens = 0

            if "prompt" in message and "response" in message:
                message_tokens += num_tokens_from_string(message["prompt"])
                message_tokens += num_tokens_from_string(message["response"])

            if "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    tool_str = (
                        f"Tool: {tool_call.get('tool_name')} | "
                        f"Action: {tool_call.get('action_name')} | "
                        f"Args: {tool_call.get('arguments')} | "
                        f"Response: {tool_call.get('result')}"
                    )
                    message_tokens += num_tokens_from_string(tool_str)

            if current_tokens + message_tokens <= max_tokens:
                current_tokens += message_tokens
                truncated.insert(0, message)
            else:
                break

        if len(truncated) < len(history):
            logger.info(
                f"Truncated chat history from {len(history)} to {len(truncated)} messages "
                f"to fit within {max_tokens:,} token budget"
            )

        return truncated

    # ---- LLM generation ----

    def _llm_gen(self, messages: List[Dict], log_context: Optional[LogContext] = None):
        self._validate_context_size(messages)

        gen_kwargs = {"model": self.model_id, "messages": messages}
        if self.attachments:
            gen_kwargs["_usage_attachments"] = self.attachments

        if (
            hasattr(self.llm, "_supports_tools")
            and self.llm._supports_tools
            and self.tools
        ):
            gen_kwargs["tools"] = self.tools
        if (
            self.json_schema
            and hasattr(self.llm, "_supports_structured_output")
            and self.llm._supports_structured_output()
        ):
            structured_format = self.llm.prepare_structured_output_format(
                self.json_schema
            )
            if structured_format:
                if self.llm_name == "openai":
                    gen_kwargs["response_format"] = structured_format
                elif self.llm_name == "google":
                    gen_kwargs["response_schema"] = structured_format
        resp = self.llm.gen_stream(**gen_kwargs)

        if log_context:
            data = build_stack_data(self.llm, exclude_attributes=["client"])
            log_context.stacks.append({"component": "llm", "data": data})
        return resp

    def _llm_handler(
        self,
        resp,
        tools_dict: Dict,
        messages: List[Dict],
        log_context: Optional[LogContext] = None,
        attachments: Optional[List[Dict]] = None,
    ):
        resp = self.llm_handler.process_message_flow(
            self, resp, tools_dict, messages, attachments, True
        )
        if log_context:
            data = build_stack_data(self.llm_handler, exclude_attributes=["tool_calls"])
            log_context.stacks.append({"component": "llm_handler", "data": data})
        return resp

    def _handle_response(self, response, tools_dict, messages, log_context):
        is_structured_output = (
            self.json_schema is not None
            and hasattr(self.llm, "_supports_structured_output")
            and self.llm._supports_structured_output()
        )

        if isinstance(response, str):
            answer_data = {"answer": response}
            if is_structured_output:
                answer_data["structured"] = True
                answer_data["schema"] = self.json_schema
            yield answer_data
            return
        if hasattr(response, "message") and getattr(response.message, "content", None):
            answer_data = {"answer": response.message.content}
            if is_structured_output:
                answer_data["structured"] = True
                answer_data["schema"] = self.json_schema
            yield answer_data
            return
        processed_response_gen = self._llm_handler(
            response, tools_dict, messages, log_context, self.attachments
        )

        for event in processed_response_gen:
            if isinstance(event, str):
                answer_data = {"answer": event}
                if is_structured_output:
                    answer_data["structured"] = True
                    answer_data["schema"] = self.json_schema
                yield answer_data
            elif hasattr(event, "message") and getattr(event.message, "content", None):
                answer_data = {"answer": event.message.content}
                if is_structured_output:
                    answer_data["structured"] = True
                    answer_data["schema"] = self.json_schema
                yield answer_data
            elif isinstance(event, dict) and "type" in event:
                yield event
