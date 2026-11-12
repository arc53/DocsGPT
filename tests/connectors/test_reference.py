"""The docs' MCP preset list is generated from the preset files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docsgpt.connectors import catalog
from docsgpt.connectors.reference import build_presets, connectors_page_path, data_path, main, render_presets
from docsgpt.core.docs_pages import read_last_updated

_PAGE = "---\ntitle: Connectors\nlastUpdated: 2026-01-01\n---\n\n<McpPresetTable />\n"


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
        monkeypatch.setattr("docsgpt.connectors.reference.connectors_page_path", lambda: tmp_path / "missing.mdx")

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

    def test_write_dates_the_connectors_page_when_the_data_changes(self, tmp_path, monkeypatch):
        target = tmp_path / "mcp-presets.json"
        target.write_text("[]\n", encoding="utf-8")
        page = tmp_path / "index.mdx"
        page.write_text(_PAGE, encoding="utf-8")
        monkeypatch.setattr("docsgpt.connectors.reference.data_path", lambda: target)
        monkeypatch.setattr("docsgpt.connectors.reference.connectors_page_path", lambda: page)
        monkeypatch.setattr("docsgpt.connectors.reference.today", lambda: "2026-12-31")

        assert main(["--write"]) == 0
        assert target.read_text(encoding="utf-8") == render_presets()
        assert read_last_updated(page.read_text(encoding="utf-8")) == "2026-12-31"
        assert page.read_text(encoding="utf-8") == _PAGE.replace("2026-01-01", "2026-12-31")

    def test_write_dates_the_connectors_page_when_the_data_file_is_new(self, tmp_path, monkeypatch):
        target = tmp_path / "data" / "mcp-presets.json"
        page = tmp_path / "index.mdx"
        page.write_text(_PAGE, encoding="utf-8")
        monkeypatch.setattr("docsgpt.connectors.reference.data_path", lambda: target)
        monkeypatch.setattr("docsgpt.connectors.reference.connectors_page_path", lambda: page)
        monkeypatch.setattr("docsgpt.connectors.reference.today", lambda: "2026-12-31")

        assert main(["--write"]) == 0
        assert target.read_text(encoding="utf-8") == render_presets()
        assert read_last_updated(page.read_text(encoding="utf-8")) == "2026-12-31"

    def test_write_leaves_the_file_and_the_page_alone_when_the_data_is_unchanged(self, tmp_path, monkeypatch):
        target = tmp_path / "mcp-presets.json"
        target.write_text(render_presets(), encoding="utf-8")
        page = tmp_path / "index.mdx"
        page.write_text(_PAGE, encoding="utf-8")
        monkeypatch.setattr("docsgpt.connectors.reference.data_path", lambda: target)
        monkeypatch.setattr("docsgpt.connectors.reference.connectors_page_path", lambda: page)
        monkeypatch.setattr("docsgpt.connectors.reference.today", lambda: "2026-12-31")
        written = []
        real_write_text = Path.write_text
        monkeypatch.setattr(
            Path, "write_text", lambda self, *a, **k: written.append(self) or real_write_text(self, *a, **k)
        )

        assert main(["--write"]) == 0
        assert written == []
        assert page.read_text(encoding="utf-8") == _PAGE

    def test_write_without_the_page_still_writes_the_data(self, tmp_path, monkeypatch):
        target = tmp_path / "mcp-presets.json"
        monkeypatch.setattr("docsgpt.connectors.reference.data_path", lambda: target)
        monkeypatch.setattr("docsgpt.connectors.reference.connectors_page_path", lambda: tmp_path / "missing.mdx")

        assert main(["--write"]) == 0
        assert target.read_text(encoding="utf-8") == render_presets()
        assert not (tmp_path / "missing.mdx").exists()


@pytest.mark.unit
class TestPaths:
    def test_data_and_page_live_in_the_docs_tree(self, tmp_path):
        assert data_path(tmp_path) == tmp_path / "docs" / "data" / "mcp-presets.json"
        assert connectors_page_path(tmp_path) == tmp_path / "docs" / "content" / "Sources" / "Connectors" / "index.mdx"

    def test_the_default_root_is_the_checkout(self):
        root = Path(__file__).resolve().parents[2]
        assert data_path() == root / "docs" / "data" / "mcp-presets.json"
        assert connectors_page_path() == root / "docs" / "content" / "Sources" / "Connectors" / "index.mdx"
        assert connectors_page_path().exists()
