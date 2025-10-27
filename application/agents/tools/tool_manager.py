import importlib
import inspect
import os
import pkgutil

from application.agents.tools.base import Tool


class ToolManager:
    def __init__(self, config):
        self.config = config
        self.tools = {}
        self.load_tools()

    def load_tools(self):
        tools_dir = os.path.join(os.path.dirname(__file__))
        for finder, name, ispkg in pkgutil.iter_modules([tools_dir]):
            if name == "base" or name.startswith("__"):
                continue
            module = importlib.import_module(f"application.agents.tools.{name}")
            for member_name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Tool) and obj is not Tool:
                    tool_config = self.config.get(name, {})
                    self.tools[name] = obj(tool_config)

    def load_tool(self, tool_name, tool_config, user_id=None):
        self.config[tool_name] = tool_config
        module = importlib.import_module(f"application.agents.tools.{tool_name}")
        for member_name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Tool) and obj is not Tool:
                if tool_name in {"mcp_tool", "notes", "memory", "todo_list"} and user_id:
                    return obj(tool_config, user_id)
                else:
                    return obj(tool_config)

    def execute_action(self, tool_name, action_name, user_id=None, **kwargs):
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not loaded")
        if tool_name in {"mcp_tool", "memory", "todo_list"} and user_id:
            tool_config = self.config.get(tool_name, {})
            tool = self.load_tool(tool_name, tool_config, user_id)
            return tool.execute_action(action_name, **kwargs)
        return self.tools[tool_name].execute_action(action_name, **kwargs)

    def get_all_actions_metadata(self):
        metadata = []
        for tool in self.tools.values():
            metadata.extend(tool.get_actions_metadata())
        return metadata
