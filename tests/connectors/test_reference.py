"""The docs' MCP preset list is generated from the preset files."""

from __future__ import annotations

import json

import pytest

from docsgpt.connectors import catalog
from docsgpt.connectors.reference import build_presets, main, render_presets


@pytest.mark.unit
class TestBuildPresets:
    def test_lists_every_preset_and_nothing_else(self):
        expected = {d.key for d in catalog.all_definitions() if d.publisher == "preset"}

        assert {entry["key"] for entry in build_presets()} == expected

    def test_is_in_name_order(self):
        names = [entry["name"].casefold() for entry in build_presets()]

        assert names == sorted(names)

    def test_says_how_a_preset_signs_in(self):
        by_key = {entry["key"]: entry for entry in build_presets()}

        assert by_key["mcp:notion"]["sign_in"] == "oauth"
        assert by_key["mcp:drawio"]["sign_in"] == "none"

    def test_carries_what_the_docs_table_shows(self):
        notion = next(entry for entry in build_presets() if entry["key"] == "mcp:notion")

        assert notion == {
            "key": "mcp:notion",
            "name": "Notion",
            "description": "Search, read and update Notion pages and databases.",
            "category": "knowledge",
            "sign_in": "oauth",
            "capabilities": ["read", "write"],
            "mcp_url": "https://mcp.notion.com/mcp",
            "docs_url": "https://developers.notion.com/docs/mcp",
        }


@pytest.mark.unit
class TestCli:
    def test_write_then_check_passes(self, tmp_path, monkeypatch):
        target = tmp_path / "data" / "mcp-presets.json"
        monkeypatch.setattr("docsgpt.connectors.reference.data_path", lambda: target)

        assert main(["--write"]) == 0
        assert main(["--check"]) == 0
        assert json.loads(target.read_text(encoding="utf-8")) == build_presets()

    def test_check_fails_on_a_stale_file(self, tmp_path, monkeypatch, capsys):
        stale = tmp_path / "mcp-presets.json"
        stale.write_text("[]\n", encoding="utf-8")
        monkeypatch.setattr("docsgpt.connectors.reference.data_path", lambda: stale)

        assert main(["--check"]) == 1
        assert "--write" in capsys.readouterr().err

    def test_prints_without_an_action(self, capsys):
        assert main([]) == 0
        assert capsys.readouterr().out == render_presets()
