import logging
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Generator, List, Optional

from bson.objectid import ObjectId

from application.agents.tools.tool_action_parser import ToolActionParser
from application.agents.tools.tool_manager import ToolManager
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.llm.handlers.handler_creator import LLMHandlerCreator
from application.llm.llm_creator import LLMCreator
from application.logging import build_stack_data, log_activity, LogContext
from application.security.encryption import decrypt_credentials

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
        self.tool_config: Dict = {}
        self.tools: List[Dict] = []
        self.tool_calls: List[Dict] = []
        self.chat_history: List[Dict] = chat_history if chat_history is not None else []
        self.llm = LLMCreator.create_llm(
            llm_name,
            api_key=api_key,
            user_api_key=user_api_key,
            decoded_token=decoded_token,
            model_id=model_id,
            agent_id=agent_id,
        )
        self.retrieved_docs = retrieved_docs or []
        self.llm_handler = LLMHandlerCreator.create_handler(
            llm_name if llm_name else "default"
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

    def _get_tools(self, api_key: str = None) -> Dict[str, Dict]:
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]
        tools_collection = db["user_tools"]

        agent_data = agents_collection.find_one({"key": api_key or self.user_api_key})
        tool_ids = agent_data.get("tools", []) if agent_data else []

        tools = (
            tools_collection.find(
                {"_id": {"$in": [ObjectId(tool_id) for tool_id in tool_ids]}}
            )
            if tool_ids
            else []
        )
        tools = list(tools)
        tools_by_id = {str(tool["_id"]): tool for tool in tools} if tools else {}

        return tools_by_id

    def _get_user_tools(self, user="local"):
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        user_tools_collection = db["user_tools"]
        user_tools = user_tools_collection.find({"user": user, "status": True})
        user_tools = list(user_tools)

        return {str(i): tool for i, tool in enumerate(user_tools)}

    def _build_tool_parameters(self, action):
        params = {"type": "object", "properties": {}, "required": []}
        for param_type in ["query_params", "headers", "body", "parameters"]:
            if param_type in action and action[param_type].get("properties"):
                for k, v in action[param_type]["properties"].items():
                    if v.get("filled_by_llm", True):
                        params["properties"][k] = {
                            key: value
                            for key, value in v.items()
                            if key not in ("filled_by_llm", "value", "required")
                        }
                        if v.get("required", False):
                            params["required"].append(k)
        return params

    def _prepare_tools(self, tools_dict):
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": f"{action['name']}_{tool_id}",
                    "description": action["description"],
                    "parameters": self._build_tool_parameters(action),
                },
            }
            for tool_id, tool in tools_dict.items()
            if (
                (tool["name"] == "api_tool" and "actions" in tool.get("config", {}))
                or (tool["name"] != "api_tool" and "actions" in tool)
            )
            for action in (
                tool["config"]["actions"].values()
                if tool["name"] == "api_tool"
                else tool["actions"]
            )
            if action.get("active", True)
        ]

    def _execute_tool_action(self, tools_dict, call):
        parser = ToolActionParser(self.llm.__class__.__name__)
        tool_id, action_name, call_args = parser.parse_args(call)

        call_id = getattr(call, "id", None) or str(uuid.uuid4())

        # Check if parsing failed

        if tool_id is None or action_name is None:
            error_message = f"Error: Failed to parse LLM tool call. Tool name: {getattr(call, 'name', 'unknown')}"
            logger.error(error_message)

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": getattr(call, "name", "unknown"),
                "arguments": call_args or {},
                "result": f"Failed to parse tool call. Invalid tool name format: {getattr(call, 'name', 'unknown')}",
            }
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return "Failed to parse tool call.", call_id
        # Check if tool_id exists in available tools

        if tool_id not in tools_dict:
            error_message = f"Error: Tool ID '{tool_id}' extracted from LLM call not found in available tools_dict. Available IDs: {list(tools_dict.keys())}"
            logger.error(error_message)

            # Return error result

            tool_call_data = {
                "tool_name": "unknown",
                "call_id": call_id,
                "action_name": f"{action_name}_{tool_id}",
                "arguments": call_args,
                "result": f"Tool with ID {tool_id} not found. Available tools: {list(tools_dict.keys())}",
            }
            yield {"type": "tool_call", "data": {**tool_call_data, "status": "error"}}
            self.tool_calls.append(tool_call_data)
            return f"Tool with ID {tool_id} not found.", call_id
        tool_call_data = {
            "tool_name": tools_dict[tool_id]["name"],
            "call_id": call_id,
            "action_name": f"{action_name}_{tool_id}",
            "arguments": call_args,
        }
        yield {"type": "tool_call", "data": {**tool_call_data, "status": "pending"}}

        tool_data = tools_dict[tool_id]
        action_data = (
            tool_data["config"]["actions"][action_name]
            if tool_data["name"] == "api_tool"
            else next(
                action
                for action in tool_data["actions"]
                if action["name"] == action_name
            )
        )

        query_params, headers, body, parameters = {}, {}, {}, {}
        param_types = {
            "query_params": query_params,
            "headers": headers,
            "body": body,
            "parameters": parameters,
        }

        for param_type, target_dict in param_types.items():
            if param_type in action_data and action_data[param_type].get("properties"):
                for param, details in action_data[param_type]["properties"].items():
                    if (
                        param not in call_args
                        and "value" in details
                        and details["value"]
                    ):
                        target_dict[param] = details["value"]
        for param, value in call_args.items():
            for param_type, target_dict in param_types.items():
                if param_type in action_data and param in action_data[param_type].get(
                    "properties", {}
                ):
                    target_dict[param] = value
        tm = ToolManager(config={})

        # Prepare tool_config and add tool_id for memory tools

        if tool_data["name"] == "api_tool":
            action_config = tool_data["config"]["actions"][action_name]
            tool_config = {
                "url": action_config["url"],
                "method": action_config["method"],
                "headers": headers,
                "query_params": query_params,
            }
            if "body_content_type" in action_config:
                tool_config["body_content_type"] = action_config.get(
                    "body_content_type", "application/json"
                )
                tool_config["body_encoding_rules"] = action_config.get(
                    "body_encoding_rules", {}
                )
        else:
            tool_config = tool_data["config"].copy() if tool_data["config"] else {}
            if tool_config.get("encrypted_credentials") and self.user:
                decrypted = decrypt_credentials(
                    tool_config["encrypted_credentials"], self.user
                )
                tool_config.update(decrypted)
                tool_config["auth_credentials"] = decrypted
                tool_config.pop("encrypted_credentials", None)
            tool_config["tool_id"] = str(tool_data.get("_id", tool_id))
            if hasattr(self, "conversation_id") and self.conversation_id:
                tool_config["conversation_id"] = self.conversation_id
            if tool_data["name"] == "mcp_tool":
                tool_config["query_mode"] = True
        tool = tm.load_tool(
            tool_data["name"],
            tool_config=tool_config,
            user_id=self.user,
        )
        resolved_arguments = (
            {"query_params": query_params, "headers": headers, "body": body}
            if tool_data["name"] == "api_tool"
            else parameters
        )
        if tool_data["name"] == "api_tool":
            logger.debug(
                f"Executing api: {action_name} with query_params: {query_params}, headers: {headers}, body: {body}"
            )
            result = tool.execute_action(action_name, **body)
        else:
            logger.debug(f"Executing tool: {action_name} with args: {call_args}")
            result = tool.execute_action(action_name, **parameters)

        get_artifact_id = (
            getattr(tool, "get_artifact_id", None)
            if tool_data["name"] != "api_tool"
            else None
        )

        artifact_id = None
        if callable(get_artifact_id):
            try:
                artifact_id = get_artifact_id(action_name, **parameters)
            except Exception:
                logger.exception(
                    "Failed to extract artifact_id from tool %s for action %s",
                    tool_data["name"],
                    action_name,
                )

        artifact_id = str(artifact_id).strip() if artifact_id is not None else ""
        if artifact_id:
            tool_call_data["artifact_id"] = artifact_id
        result_full = str(result)
        tool_call_data["resolved_arguments"] = resolved_arguments
        tool_call_data["result_full"] = result_full
        tool_call_data["result"] = (
            f"{result_full[:50]}..." if len(result_full) > 50 else result_full
        )

        stream_tool_call_data = {
            key: value
            for key, value in tool_call_data.items()
            if key not in {"result_full", "resolved_arguments"}
        }
        yield {"type": "tool_call", "data": {**stream_tool_call_data, "status": "completed"}}
        self.tool_calls.append(tool_call_data)

        return result, call_id

    def _get_truncated_tool_calls(self):
        return [
            {
                "tool_name": tool_call.get("tool_name"),
                "call_id": tool_call.get("call_id"),
                "action_name": tool_call.get("action_name"),
                "arguments": tool_call.get("arguments"),
                "artifact_id": tool_call.get("artifact_id"),
                "result": (
                    f"{str(tool_call['result'])[:50]}..."
                    if len(str(tool_call["result"])) > 50
                    else tool_call["result"]
                ),
                "status": "completed",
            }
            for tool_call in self.tool_calls
        ]

    def _calculate_current_context_tokens(self, messages: List[Dict]) -> int:
        """
        Calculate total tokens in current context (messages).

        Args:
            messages: List of message dicts

        Returns:
            Total token count
        """
        from application.api.answer.services.compression.token_counter import (
            TokenCounter,
        )

        return TokenCounter.count_message_tokens(messages)

    def _check_context_limit(self, messages: List[Dict]) -> bool:
        """
        Check if we're approaching context limit (80%).

        Args:
            messages: Current message list

        Returns:
            True if at or above 80% of context limit
        """
        from application.core.model_utils import get_token_limit
        from application.core.settings import settings

        try:
            # Calculate current tokens
            current_tokens = self._calculate_current_context_tokens(messages)
            self.current_token_count = current_tokens

            # Get context limit for model
            context_limit = get_token_limit(self.model_id)

            # Calculate threshold (80%)
            threshold = int(context_limit * settings.COMPRESSION_THRESHOLD_PERCENTAGE)

            # Check if we've reached the limit
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
        """
        Pre-flight validation before calling LLM. Logs warnings but never raises errors.

        Args:
            messages: Messages to be sent to LLM
        """
        from application.core.model_utils import get_token_limit

        current_tokens = self._calculate_current_context_tokens(messages)
        self.current_token_count = current_tokens
        context_limit = get_token_limit(self.model_id)

        percentage = (current_tokens / context_limit) * 100

        # Log based on usage level
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
        """
        Truncate text by removing content from the middle, preserving start and end.

        Args:
            text: Text to truncate
            max_tokens: Maximum tokens allowed

        Returns:
            Truncated text with middle removed if needed
        """
        from application.utils import num_tokens_from_string

        current_tokens = num_tokens_from_string(text)
        if current_tokens <= max_tokens:
            return text

        # Estimate chars per token (roughly 4 chars per token for English)
        chars_per_token = len(text) / current_tokens if current_tokens > 0 else 4
        target_chars = int(max_tokens * chars_per_token * 0.95)  # 5% safety margin

        if target_chars <= 0:
            return ""

        # Split: keep 40% from start, 40% from end, remove middle
        start_chars = int(target_chars * 0.4)
        end_chars = int(target_chars * 0.4)

        truncation_marker = "\n\n[... content truncated to fit context limit ...]\n\n"

        truncated = text[:start_chars] + truncation_marker + text[-end_chars:]

        logger.info(
            f"Truncated text from {current_tokens:,} to ~{max_tokens:,} tokens "
            f"(removed middle section)"
        )

        return truncated

    def _build_messages(
        self,
        system_prompt: str,
        query: str,
    ) -> List[Dict]:
        """Build messages using pre-rendered system prompt"""
        from application.core.model_utils import get_token_limit
        from application.utils import num_tokens_from_string

        # Append compression summary to system prompt if present
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

        # Reserve 10% for response/tools
        safety_buffer = int(context_limit * 0.1)
        available_after_system = context_limit - system_tokens - safety_buffer

        # Max tokens for query: 80% of available space (leave room for history)
        max_query_tokens = int(available_after_system * 0.8)
        query_tokens = num_tokens_from_string(query)

        # Truncate query from middle if it exceeds 80% of available context
        if query_tokens > max_query_tokens:
            query = self._truncate_text_middle(query, max_query_tokens)
            query_tokens = num_tokens_from_string(query)

        # Calculate remaining budget for chat history
        available_for_history = max(available_after_system - query_tokens, 0)

        # Truncate chat history to fit within available budget
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

                    function_call_dict = {
                        "function_call": {
                            "name": tool_call.get("action_name"),
                            "args": tool_call.get("arguments"),
                            "call_id": call_id,
                        }
                    }
                    function_response_dict = {
                        "function_response": {
                            "name": tool_call.get("action_name"),
                            "response": {"result": tool_call.get("result")},
                            "call_id": call_id,
                        }
                    }

                    messages.append(
                        {"role": "assistant", "content": [function_call_dict]}
                    )
                    messages.append(
                        {"role": "tool", "content": [function_response_dict]}
                    )
        messages.append({"role": "user", "content": query})
        return messages

    def _truncate_history_to_fit(
        self,
        history: List[Dict],
        max_tokens: int,
    ) -> List[Dict]:
        """
        Truncate chat history to fit within token budget, keeping most recent messages.

        Args:
            history: Full chat history
            max_tokens: Maximum tokens allowed for history

        Returns:
            Truncated history (most recent messages that fit)
        """
        from application.utils import num_tokens_from_string

        if not history or max_tokens <= 0:
            return []

        truncated = []
        current_tokens = 0

        # Iterate from newest to oldest
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
                truncated.insert(0, message)  # Maintain chronological order
            else:
                break

        if len(truncated) < len(history):
            logger.info(
                f"Truncated chat history from {len(history)} to {len(truncated)} messages "
                f"to fit within {max_tokens:,} token budget"
            )

        return truncated

    def _llm_gen(self, messages: List[Dict], log_context: Optional[LogContext] = None):
        # Pre-flight context validation - fail fast if over limit
        self._validate_context_size(messages)

        gen_kwargs = {"model": self.model_id, "messages": messages}
        if self.attachments:
            # Usage accounting only; stripped before provider invocation.
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
