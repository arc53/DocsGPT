"""Agent import refuses a team the same tools the tools routes refuse: one rule, kept in the tools routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.api.user.agents.portability import _team_tool_refusal
from docsgpt.api.user.tools.routes import (
    CODE_CONNECTOR_PERSONAL_ONLY,
    CODE_OAUTH_PERSONAL_ONLY,
    CODE_REMOTE_DEVICE_PERSONAL_ONLY,
)


@pytest.mark.parametrize(
    ("tool_type", "config", "expected"),
    [
        ("remote_device", None, CODE_REMOTE_DEVICE_PERSONAL_ONLY),
        ("telegram", {}, CODE_CONNECTOR_PERSONAL_ONLY),
        ("mcp_tool", {"auth_type": "oauth"}, CODE_OAUTH_PERSONAL_ONLY),
        ("mcp_tool", {"auth_type": "bearer"}, None),
        ("mcp_tool", "not-a-dict", None),
        ("api_tool", None, None),
    ],
)
def test_import_reads_the_tools_rule(tool_type, config, expected):
    assert _team_tool_refusal(tool_type, config) == expected


def test_import_asks_the_tools_routes():
    with patch("docsgpt.api.user.tools.routes.team_tool_refusal", return_value="sentinel") as rule:
        assert _team_tool_refusal("api_tool", {"a": 1}) == "sentinel"
    rule.assert_called_once_with("api_tool", {"a": 1})
