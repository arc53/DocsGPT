from application.core.mongo_db import MongoDB
from application.llm.llm_creator import LLMCreator
from application.tools.llm_handler import get_llm_handler
from application.tools.tool_action_parser import ToolActionParser
from application.tools.tool_manager import ToolManager


class Agent:
    def __init__(self, llm_name, gpt_model, api_key, user_api_key=None):
        # Initialize the LLM with the provided parameters
        self.llm = LLMCreator.create_llm(
            llm_name, api_key=api_key, user_api_key=user_api_key
        )
        self.llm_handler = get_llm_handler(llm_name)
        self.gpt_model = gpt_model
        # Static tool configuration (to be replaced later)
        self.tools = []
        self.tool_config = {}
        self.tool_calls = []

    def _get_user_tools(self, user="local"):
        mongo = MongoDB.get_client()
        db = mongo["docsgpt"]
        user_tools_collection = db["user_tools"]
        user_tools = user_tools_collection.find({"user": user, "status": True})
        user_tools = list(user_tools)
        tools_by_id = {str(tool["_id"]): tool for tool in user_tools}
        return tools_by_id

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
        tool = tm.load_tool(
            tool_data["name"],
            tool_config=(
                {
                    "url": tool_data["config"]["actions"][action_name]["url"],
                    "method": tool_data["config"]["actions"][action_name]["method"],
                    "headers": headers,
                    "query_params": query_params,
                }
                if tool_data["name"] == "api_tool"
                else tool_data["config"]
            ),
        )
        if tool_data["name"] == "api_tool":
            print(
                f"Executing api: {action_name} with query_params: {query_params}, headers: {headers}, body: {body}"
            )
            result = tool.execute_action(action_name, **body)
        else:
            print(f"Executing tool: {action_name} with args: {call_args}")
            result = tool.execute_action(action_name, **parameters)
        call_id = getattr(call, "id", None)

        tool_call_data = {
            "tool_name": tool_data["name"],
            "call_id": call_id if call_id is not None else "None",
            "action_name": f"{action_name}_{tool_id}",
            "arguments": call_args,
            "result": result,
        }
        self.tool_calls.append(tool_call_data)

        return result, call_id

    def _simple_tool_agent(self, messages):
        tools_dict = self._get_user_tools()
        self._prepare_tools(tools_dict)

        resp = self.llm.gen(model=self.gpt_model, messages=messages, tools=self.tools)

        if isinstance(resp, str):
            yield resp
            return
        if (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            yield resp.message.content
            return

        resp = self.llm_handler.handle_response(self, resp, tools_dict, messages)

        if isinstance(resp, str):
            yield resp
        elif (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            yield resp.message.content
        else:
            completion = self.llm.gen_stream(
                model=self.gpt_model, messages=messages, tools=self.tools
            )
            for line in completion:
                yield line

        return

    def gen(self, messages):
        self.tool_calls = []
        if self.llm.supports_tools():
            resp = self._simple_tool_agent(messages)
            for line in resp:
                yield line
        else:
            resp = self.llm.gen_stream(model=self.gpt_model, messages=messages)
            for line in resp:
                yield line
