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

    def _get_user_tools(self, user="local"):
        mongo = MongoDB.get_client()
        db = mongo["docsgpt"]
        user_tools_collection = db["user_tools"]
        user_tools = user_tools_collection.find({"user": user, "status": True})
        user_tools = list(user_tools)
        tools_by_id = {str(tool["_id"]): tool for tool in user_tools}
        return tools_by_id

    def _prepare_tools(self, tools_dict):
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": f"{action['name']}_{tool_id}",
                    "description": action["description"],
                    "parameters": {
                        **action["parameters"],
                        "properties": {
                            k: {
                                key: value
                                for key, value in v.items()
                                if key != "filled_by_llm" and key != "value"
                            }
                            for k, v in action["parameters"]["properties"].items()
                            if v.get("filled_by_llm", False)
                        },
                        "required": [
                            key
                            for key in action["parameters"]["required"]
                            if key in action["parameters"]["properties"]
                            and action["parameters"]["properties"][key].get(
                                "filled_by_llm", False
                            )
                        ],
                    },
                },
            }
            for tool_id, tool in tools_dict.items()
            for action in tool["actions"]
            if action["active"]
        ]

    def _execute_tool_action(self, tools_dict, call):
        parser = ToolActionParser(self.llm.__class__.__name__)
        tool_id, action_name, call_args = parser.parse_args(call)

        tool_data = tools_dict[tool_id]
        action_data = next(
            action for action in tool_data["actions"] if action["name"] == action_name
        )

        for param, details in action_data["parameters"]["properties"].items():
            if param not in call_args and "value" in details:
                call_args[param] = details["value"]

        tm = ToolManager(config={})
        tool = tm.load_tool(tool_data["name"], tool_config=tool_data["config"])
        print(f"Executing tool: {action_name} with args: {call_args}")
        result = tool.execute_action(action_name, **call_args)
        call_id = getattr(call, "id", None)
        return result, call_id

    def _simple_tool_agent(self, messages):
        tools_dict = self._get_user_tools()
        self._prepare_tools(tools_dict)

        resp = self.llm.gen(model=self.gpt_model, messages=messages, tools=self.tools)

        if isinstance(resp, str):
            yield resp
            return
        if hasattr(resp, "message") and hasattr(resp.message, "content"):
            yield resp.message.content
            return

        resp = self.llm_handler.handle_response(self, resp, tools_dict, messages)

        # If no tool calls are needed, generate the final response
        if isinstance(resp, str):
            yield resp
        elif hasattr(resp, "message") and hasattr(resp.message, "content"):
            yield resp.message.content
        else:
            completion = self.llm.gen_stream(
                model=self.gpt_model, messages=messages, tools=self.tools
            )
            for line in completion:
                yield line

        return

    def gen(self, messages):
        # Generate initial response from the LLM
        if self.llm.supports_tools():
            resp = self._simple_tool_agent(messages)
            for line in resp:
                yield line
        else:
            resp = self.llm.gen_stream(model=self.gpt_model, messages=messages)
            for line in resp:
                yield line
