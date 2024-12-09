from application.llm.llm_creator import LLMCreator
from application.core.settings import settings
from application.tools.tool_manager import ToolManager
from application.core.mongo_db import MongoDB
import json

tool_tg = {
    "name": "telegram_send_message",
    "description": "Send a notification to telegram about current chat",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to send in the notification"
            }
        },
        "required": ["text"],
        "additionalProperties": False
    }
}

tool_crypto =   {
    "name": "cryptoprice_get",
    "description": "Retrieve the price of a specified cryptocurrency in a given currency",
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "The cryptocurrency symbol (e.g. BTC)"
            },
            "currency": {
                "type": "string",
                "description": "The currency in which you want the price (e.g. USD)"
            }
        },
        "required": ["symbol", "currency"],
        "additionalProperties": False
    }
}

class Agent:
    def __init__(self, llm_name, gpt_model, api_key, user_api_key=None):
        # Initialize the LLM with the provided parameters
        self.llm = LLMCreator.create_llm(llm_name, api_key=api_key, user_api_key=user_api_key)
        self.gpt_model = gpt_model
        # Static tool configuration (to be replaced later)
        self.tools = [
            {
                "type": "function",
                "function": tool_crypto
            }
        ]
        self.tool_config = {
        }
    
    def _get_user_tools(self, user="local"):
        mongo = MongoDB.get_client()
        db = mongo["docsgpt"]
        user_tools_collection = db["user_tools"]
        user_tools = user_tools_collection.find({"user": user, "status": True})
        user_tools = list(user_tools)
        for tool in user_tools:
            tool.pop("_id")
        user_tools = {tool["name"]: tool for tool in user_tools}
        return user_tools
    
    def _simple_tool_agent(self, messages):
        tools_dict = self._get_user_tools()
        # combine all tool_actions into one list
        self.tools.extend([
            {
                "type": "function",
                "function": tool_action
            }
            for tool in tools_dict.values()
            for tool_action in tool["actions"]
        ])


        resp = self.llm.gen(model=self.gpt_model, messages=messages, tools=self.tools)

        if isinstance(resp, str):
            # Yield the response if it's a string and exit
            yield resp
            return

        while resp.finish_reason == "tool_calls":
            # Append the assistant's message to the conversation
            messages.append(json.loads(resp.model_dump_json())['message'])
            # Handle each tool call
            tool_calls = resp.message.tool_calls
            for call in tool_calls:
                tm = ToolManager(config={})
                call_name = call.function.name
                call_args = json.loads(call.function.arguments)
                call_id = call.id
                # Determine the tool name and load it
                tool_name = call_name.split("_")[0]
                tool = tm.load_tool(tool_name, tool_config=tools_dict[tool_name]['config'])
                # Execute the tool's action
                resp_tool = tool.execute_action(call_name, **call_args)
                # Append the tool's response to the conversation
                messages.append(
                    {
                        "role": "tool",
                        "content": str(resp_tool),
                        "tool_call_id": call_id
                    }
                )
            # Generate a new response from the LLM after processing tools
            resp = self.llm.gen(model=self.gpt_model, messages=messages, tools=self.tools)

        # If no tool calls are needed, generate the final response
        if isinstance(resp, str):
            yield resp
        else:
            completion = self.llm.gen_stream(model=self.gpt_model, messages=messages, tools=self.tools)
            for line in completion:
                yield line

    def gen(self, messages):
        # Generate initial response from the LLM
        if self.llm.supports_tools():
            self._simple_tool_agent(messages)
        else:
            resp = self.llm.gen_stream(model=self.gpt_model, messages=messages)
            for line in resp:
                yield line