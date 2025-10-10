from unittest.mock import Mock, patch

import pytest
from application.agents.tools.base import Tool
from application.agents.tools.tool_manager import ToolManager


class MockTool(Tool):
    def __init__(self, config):
        self.config = config

    def execute_action(self, action_name: str, **kwargs):
        return f"Executed {action_name} with {kwargs}"

    def get_actions_metadata(self):
        return [{"name": "test_action", "description": "Test action"}]

    def get_config_requirements(self):
        return {"required": ["api_key"]}


@pytest.mark.unit
class TestToolManager:

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    def test_tool_manager_initialization(self, mock_iter):
        mock_iter.return_value = []

        config = {"tool1": {"key": "value"}}
        manager = ToolManager(config)

        assert manager.config == config
        assert isinstance(manager.tools, dict)

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    @patch("application.agents.tools.tool_manager.importlib.import_module")
    def test_load_tools_skips_base_and_private(self, mock_import, mock_iter):
        mock_iter.return_value = [
            (None, "base", False),
            (None, "__init__", False),
            (None, "__pycache__", False),
            (None, "valid_tool", False),
        ]

        mock_module = Mock()
        mock_module.MockTool = MockTool
        mock_import.return_value = mock_module

        manager = ToolManager({})

        assert "base" not in manager.tools
        assert "__init__" not in manager.tools

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    def test_load_tools_creates_tool_instances(self, mock_iter):
        mock_iter.return_value = []

        manager = ToolManager({})

        mock_tool = MockTool({"test": "config"})
        manager.tools["mock_tool"] = mock_tool

        assert "mock_tool" in manager.tools
        assert isinstance(manager.tools["mock_tool"], MockTool)
        assert manager.tools["mock_tool"].config == {"test": "config"}

    def test_load_tool_with_user_id(self):
        with patch(
            "application.agents.tools.tool_manager.pkgutil.iter_modules",
            return_value=[],
        ):
            manager = ToolManager({})
        tool = MockTool({"key": "value"})
        assert tool.config == {"key": "value"}

        manager.config["test_tool"] = {"key": "value"}
        assert "test_tool" in manager.config

    def test_load_tool_without_user_id(self):
        tool = MockTool({"api_key": "test123"})

        assert isinstance(tool, MockTool)
        assert tool.config == {"api_key": "test123"}

        assert hasattr(tool, "execute_action")
        assert hasattr(tool, "get_actions_metadata")

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    def test_load_tool_updates_config(self, mock_iter):
        mock_iter.return_value = []

        manager = ToolManager({})
        new_config = {"new_key": "new_value"}

        manager.config["test_tool"] = new_config

        assert manager.config["test_tool"] == new_config
        assert "test_tool" in manager.config

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    @patch("application.agents.tools.tool_manager.importlib.import_module")
    def test_execute_action_on_loaded_tool(self, mock_import, mock_iter):
        mock_iter.return_value = [(None, "mock_tool", False)]

        mock_tool_instance = MockTool({})

        with patch("inspect.getmembers", return_value=[("MockTool", MockTool)]):
            with patch("inspect.isclass", return_value=True):
                with patch.object(MockTool, "__init__", return_value=None):
                    manager = ToolManager({})
                    manager.tools["mock_tool"] = mock_tool_instance

                    result = manager.execute_action(
                        "mock_tool", "test_action", param="value"
                    )

                    assert "Executed test_action" in result

    def test_execute_action_tool_not_loaded(self):
        with patch(
            "application.agents.tools.tool_manager.pkgutil.iter_modules",
            return_value=[],
        ):
            manager = ToolManager({})
        with pytest.raises(ValueError, match="Tool 'nonexistent' not loaded"):
            manager.execute_action("nonexistent", "action")

    @patch("application.agents.tools.tool_manager.importlib.import_module")
    def test_execute_action_with_user_id_for_mcp_tool(self, mock_import):
        mock_tool = MockTool({})

        with patch("inspect.getmembers", return_value=[("MockTool", MockTool)]):
            with patch("inspect.isclass", return_value=True):
                manager = ToolManager({"mcp_tool": {}})
                manager.tools["mcp_tool"] = mock_tool

                with patch.object(
                    manager, "load_tool", return_value=mock_tool
                ) as mock_load:
                    manager.execute_action("mcp_tool", "action", user_id="user123")

                    mock_load.assert_called_once_with("mcp_tool", {}, "user123")

    @patch("application.agents.tools.tool_manager.importlib.import_module")
    def test_execute_action_with_user_id_for_memory_tool(self, mock_import):
        mock_tool = MockTool({})

        with patch("inspect.getmembers", return_value=[("MockTool", MockTool)]):
            with patch("inspect.isclass", return_value=True):
                manager = ToolManager({"memory": {}})
                manager.tools["memory"] = mock_tool

                with patch.object(
                    manager, "load_tool", return_value=mock_tool
                ) as mock_load:
                    manager.execute_action("memory", "view", user_id="user456")

                    mock_load.assert_called_once_with("memory", {}, "user456")

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    @patch("application.agents.tools.tool_manager.importlib.import_module")
    def test_get_all_actions_metadata(self, mock_import, mock_iter):
        mock_iter.return_value = [(None, "tool1", False), (None, "tool2", False)]

        mock_tool1 = Mock()
        mock_tool1.get_actions_metadata.return_value = [{"name": "action1"}]

        mock_tool2 = Mock()
        mock_tool2.get_actions_metadata.return_value = [{"name": "action2"}]

        manager = ToolManager({})
        manager.tools = {"tool1": mock_tool1, "tool2": mock_tool2}

        metadata = manager.get_all_actions_metadata()

        assert len(metadata) == 2
        assert {"name": "action1"} in metadata
        assert {"name": "action2"} in metadata

    @patch("application.agents.tools.tool_manager.pkgutil.iter_modules")
    def test_get_all_actions_metadata_empty(self, mock_iter):
        mock_iter.return_value = []

        manager = ToolManager({})
        manager.tools = {}

        metadata = manager.get_all_actions_metadata()

        assert metadata == []

    def test_load_tool_with_notes_tool(self):
        tool = MockTool({"key": "value"})

        assert isinstance(tool, MockTool)
        assert tool.config == {"key": "value"}

        result = tool.execute_action("test_action", param="value")
        assert "test_action" in result


@pytest.mark.unit
class TestToolBase:

    def test_tool_base_is_abstract(self):
        with pytest.raises(TypeError):
            Tool()

    def test_mock_tool_implements_interface(self):
        tool = MockTool({"test": "config"})

        assert hasattr(tool, "execute_action")
        assert hasattr(tool, "get_actions_metadata")
        assert hasattr(tool, "get_config_requirements")

    def test_mock_tool_execute_action(self):
        tool = MockTool({})
        result = tool.execute_action("test", param="value")

        assert "Executed test" in result
        assert "param" in result

    def test_mock_tool_get_actions_metadata(self):
        tool = MockTool({})
        metadata = tool.get_actions_metadata()

        assert isinstance(metadata, list)
        assert len(metadata) > 0
        assert "name" in metadata[0]

    def test_mock_tool_get_config_requirements(self):
        tool = MockTool({})
        requirements = tool.get_config_requirements()

        assert isinstance(requirements, dict)
        assert "required" in requirements
