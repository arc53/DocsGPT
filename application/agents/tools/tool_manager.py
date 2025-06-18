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

    def load_tool(self, tool_name, tool_config):
        self.config[tool_name] = tool_config
        module = importlib.import_module(f"application.agents.tools.{tool_name}")
        for member_name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Tool) and obj is not Tool:
                return obj(tool_config)

    def execute_action(self, tool_name, action_name, **kwargs):
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not loaded")
        return self.tools[tool_name].execute_action(action_name, **kwargs)

    def get_all_actions_metadata(self):
        metadata = []
        for tool in self.tools.values():
            metadata.extend(tool.get_actions_metadata())
        return metadata
