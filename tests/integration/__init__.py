"""
DocsGPT Integration Tests Package

This package contains modular integration tests for all DocsGPT API endpoints.
Tests are organized by domain:

- test_chat.py: Chat/streaming endpoints (/stream, /api/answer, /api/feedback, /api/tts)
- test_sources.py: Source management (upload, remote, chunks, etc.)
- test_agents.py: Agent CRUD and sharing
- test_conversations.py: Conversation management
- test_prompts.py: Prompt CRUD
- test_tools.py: Tools CRUD
- test_analytics.py: Analytics endpoints
- test_connectors.py: External connectors
- test_mcp.py: MCP server endpoints
- test_misc.py: Models, images, attachments

Usage:
    # Run all integration tests
    python tests/integration/run_all.py

    # Run specific module
    python tests/integration/test_chat.py

    # Run multiple modules
    python tests/integration/run_all.py --module chat,agents

    # Run with custom server
    python tests/integration/run_all.py --base-url http://localhost:7091

    # List available modules
    python tests/integration/run_all.py --list
"""

from .base import Colors, DocsGPTTestBase, create_client_from_args, generate_jwt_token
from .test_chat import ChatTests
from .test_sources import SourceTests
from .test_agents import AgentTests
from .test_conversations import ConversationTests
from .test_prompts import PromptTests
from .test_tools import ToolsTests
from .test_analytics import AnalyticsTests
from .test_connectors import ConnectorTests
from .test_mcp import MCPTests
from .test_misc import MiscTests

__all__ = [
    # Base utilities
    "Colors",
    "DocsGPTTestBase",
    "create_client_from_args",
    "generate_jwt_token",
    # Test classes
    "ChatTests",
    "SourceTests",
    "AgentTests",
    "ConversationTests",
    "PromptTests",
    "ToolsTests",
    "AnalyticsTests",
    "ConnectorTests",
    "MCPTests",
    "MiscTests",
]
