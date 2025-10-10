import logging
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Generator, List, Optional

from bson.objectid import ObjectId

from application.agents.tools.tool_action_parser import ToolActionParser
from application.agents.tools.tool_manager import ToolManager
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.llm.handlers.handler_creator import LLMHandlerCreator
from application.llm.llm_creator import LLMCreator
from application.logging import build_stack_data, log_activity, LogContext
from application.retriever.base import BaseRetriever

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        endpoint: str,
        llm_name: str,
        gpt_model: str,
        api_key: str,
        user_api_key: Optional[str] = None,
        prompt: str = "",
        chat_history: Optional[List[Dict]] = None,
        decoded_token: Optional[Dict] = None,
        attachments: Optional[List[Dict]] = None,
        json_schema: Optional[Dict] = None,
    ):
        self.endpoint = endpoint
        self.llm_name = llm_name
        self.gpt_model = gpt_model
        self.api_key = api_key
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
        )
        self.llm_handler = LLMHandlerCreator.create_handler(
            llm_name if llm_name else "default"
        )
        self.attachments = attachments or []
        self.json_schema = json_schema

    @log_activity()
    def gen(
        self, query: str, retriever: BaseRetriever, log_context: LogContext = None
    ) -> Generator[Dict, None, None]:
        yield from self._gen_inner(query, retriever, log_context)

    @abstractmethod
    def _gen_inner(
        self, query: str, retriever: BaseRetriever, log_context: LogContext
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
                            if key != "filled_by_llm" and key != "value"
                        }

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
                    if param not in call_args and "value" in details:
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
            tool_config = {
                "url": tool_data["config"]["actions"][action_name]["url"],
                "method": tool_data["config"]["actions"][action_name]["method"],
                "headers": headers,
                "query_params": query_params,
            }
        else:
            tool_config = tool_data["config"].copy() if tool_data["config"] else {}
            # Add tool_id from MongoDB _id for tools that need instance isolation (like memory tool)
            # Use MongoDB _id if available, otherwise fall back to enumerated tool_id
            tool_config["tool_id"] = str(tool_data.get("_id", tool_id))

        tool = tm.load_tool(
            tool_data["name"],
            tool_config=tool_config,
            user_id=self.user,  # Pass user ID for MCP tools credential decryption
        )
        if tool_data["name"] == "api_tool":
            print(
                f"Executing api: {action_name} with query_params: {query_params}, headers: {headers}, body: {body}"
            )
            result = tool.execute_action(action_name, **body)
        else:
            print(f"Executing tool: {action_name} with args: {call_args}")
            result = tool.execute_action(action_name, **parameters)
        tool_call_data["result"] = (
            f"{str(result)[:50]}..." if len(str(result)) > 50 else result
        )

        yield {"type": "tool_call", "data": {**tool_call_data, "status": "completed"}}
        self.tool_calls.append(tool_call_data)

        return result, call_id

    def _get_truncated_tool_calls(self):
        return [
            {
                **tool_call,
                "result": (
                    f"{str(tool_call['result'])[:50]}..."
                    if len(str(tool_call["result"])) > 50
                    else tool_call["result"]
                ),
                "status": "completed",
            }
            for tool_call in self.tool_calls
        ]

    def _build_messages(
        self,
        system_prompt: str,
        query: str,
        retrieved_data: List[Dict],
    ) -> List[Dict]:
        docs_with_filenames = []
        for doc in retrieved_data:
            filename = doc.get("filename") or doc.get("title") or doc.get("source")
            if filename:
                chunk_header = str(filename)
                docs_with_filenames.append(f"{chunk_header}\n{doc['text']}")
            else:
                docs_with_filenames.append(doc["text"])
        docs_together = "\n\n".join(docs_with_filenames)
        p_chat_combine = system_prompt.replace("{summaries}", docs_together)
        messages_combine = [{"role": "system", "content": p_chat_combine}]

        for i in self.chat_history:
            if "prompt" in i and "response" in i:
                messages_combine.append({"role": "user", "content": i["prompt"]})
                messages_combine.append({"role": "assistant", "content": i["response"]})
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

                    messages_combine.append(
                        {"role": "assistant", "content": [function_call_dict]}
                    )
                    messages_combine.append(
                        {"role": "tool", "content": [function_response_dict]}
                    )
        messages_combine.append({"role": "user", "content": query})
        return messages_combine

    def _retriever_search(
        self,
        retriever: BaseRetriever,
        query: str,
        log_context: Optional[LogContext] = None,
    ) -> List[Dict]:
        retrieved_data = retriever.search(query)
        if log_context:
            data = build_stack_data(retriever, exclude_attributes=["llm"])
            log_context.stacks.append({"component": "retriever", "data": data})
        return retrieved_data

    def _llm_gen(self, messages: List[Dict], log_context: Optional[LogContext] = None):
        gen_kwargs = {"model": self.gpt_model, "messages": messages}

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
