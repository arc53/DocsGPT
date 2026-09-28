"""Tests for read / write classification and permissions."""

from __future__ import annotations

import pytest

from docsgpt.connectors import permissions as p


class TestActionAccess:
    def test_explicit_access_wins(self):
        assert p.action_access("telegram", {"name": "search", "access": "write"}) == "write"

    def test_mcp_annotations(self):
        assert p.action_access("mcp_tool", {"name": "create_page", "annotations": {"readOnlyHint": True}}) == "read"
        assert p.action_access("mcp_tool", {"name": "search", "annotations": {"destructiveHint": True}}) == "write"

    def test_api_tool_method(self):
        assert p.action_access("api_tool", {"name": "x", "method": "get"}) == "read"
        assert p.action_access("api_tool", {"name": "x", "method": "POST"}) == "write"

    @pytest.mark.parametrize(
        "name,expected",
        [("search_pages", "read"), ("list_issues", "read"), ("create_issue", "write"), ("send_message", "write")],
    )
    def test_name_heuristic(self, name, expected):
        assert p.action_access("mcp_tool", {"name": name}) == expected


class TestPermissions:
    def test_permission_from_flags(self):
        assert p.action_permission({"active": False, "require_approval": True}) == "off"
        assert p.action_permission({"active": True, "require_approval": True}) == "ask"
        assert p.action_permission({"active": True}) == "always"

    def test_apply_permission(self):
        assert p.apply_permission({"name": "a"}, "ask") == {"name": "a", "active": True, "require_approval": True}
        assert p.apply_permission({"name": "a"}, "off")["active"] is False
        with pytest.raises(ValueError):
            p.apply_permission({}, "sometimes")

    def test_defaults_writes_to_approval(self):
        stamped = p.apply_default_permissions(
            "mcp_tool", [{"name": "search"}, {"name": "delete_page"}]
        )
        assert stamped[0] == {"name": "search", "access": "read"}
        assert stamped[1]["access"] == "write" and stamped[1]["require_approval"] is True
