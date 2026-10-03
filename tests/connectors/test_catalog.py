"""Tests for the connector catalog."""

from __future__ import annotations

import pytest

from docsgpt.connectors import catalog


@pytest.fixture(autouse=True)
def _fresh_registry():
    catalog.reset_registry_for_tests()
    yield
    catalog.reset_registry_for_tests()


class TestDefinitions:
    def test_built_ins_are_registered(self):
        keys = {d.key for d in catalog.all_definitions()}
        assert {
            "google_drive", "share_point", "confluence", "s3", "reddit",
            "brave", "telegram", "ntfy", "postgres", "custom_mcp", "custom_openapi",
        } <= keys

    def test_every_definition_uses_known_values(self):
        for definition in catalog.all_definitions():
            assert definition.category in catalog.CATEGORIES, definition.key
            assert definition.auth_kind in catalog.AUTH_KINDS, definition.key
            assert definition.publisher in catalog.PUBLISHERS, definition.key
            assert set(definition.capabilities) <= {"sync", "read", "write"}, definition.key

    def test_tool_connectors_match_tool_config_requirements(self):
        """Credential fields must be the keys the tool reads its secrets from."""
        import docsgpt.api.user  # noqa: F401  (mcp_tool imports it; load it first)
        from docsgpt.agents.tools.tool_manager import ToolManager

        tools = ToolManager(config={}).tools
        for definition in catalog.all_definitions():
            if definition.publisher != "built_in":
                continue
            for tool_name in definition.tool_templates:
                if tool_name == "mcp_tool":
                    # GitHub's MCP server gets the connection's token as a bearer token.
                    continue
                requirements = tools[tool_name].get_config_requirements()
                secret_keys = {k for k, spec in requirements.items() if spec.get("secret")}
                field_keys = {f.key for f in definition.credential_fields}
                assert secret_keys <= field_keys, definition.key

    def test_sync_connectors_link_their_setup_docs(self):
        for definition in catalog.all_definitions():
            if definition.publisher == "built_in" and "sync" in definition.capabilities:
                assert definition.docs_url, definition.key
        assert catalog.get_definition("reddit").docs_url.endswith("#reddit")

    def test_to_dict_has_no_server_secrets(self):
        payload = catalog.get_definition("google_drive").to_dict()
        assert "required_settings" not in payload
        assert payload["capabilities"] == ["sync"]


class TestAvailability:
    def test_missing_settings_listed(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
        definition = catalog.get_definition("google_drive")
        assert definition.missing_settings == ["GOOGLE_CLIENT_ID"]
        assert not definition.configured

    def test_configured_when_all_set(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
        assert catalog.get_definition("google_drive").configured

    def test_api_key_connectors_need_no_settings(self):
        assert catalog.get_definition("telegram").configured


class TestRowMapping:
    def test_oauth_provider_maps_to_key(self):
        assert catalog.connector_key_for_row({"provider": "share_point"}) == "share_point"

    def test_legacy_mcp_row_is_custom(self):
        row = {"provider": "mcp:https://mcp.unknown.dev", "server_url": "https://mcp.unknown.dev"}
        assert catalog.connector_key_for_row(row) == "custom_mcp"

    def test_stored_key_wins(self):
        assert catalog.connector_key_for_row({"provider": "telegram", "connector_key": "telegram"}) == "telegram"

    def test_unknown_provider(self):
        assert catalog.connector_key_for_row({"provider": "nope"}) is None

    def test_definition_for_tool(self):
        assert catalog.definition_for_tool("telegram").key == "telegram"
        assert catalog.definition_for_tool("memory") is None
        assert catalog.definition_for_tool("mcp_tool") is None


class TestPresets:
    def test_presets_load_from_yaml(self, tmp_path, monkeypatch):
        presets = tmp_path / "mcp.yaml"
        presets.write_text(
            "- key: mcp:example\n"
            "  name: Example\n"
            "  description: Example records.\n"
            "  icon: example\n"
            "  category: knowledge\n"
            "  mcp_url: https://mcp.example.com/mcp\n"
            "  auth_kind: mcp_oauth\n"
        )
        monkeypatch.setattr(catalog, "_PRESETS_FILE", presets)
        definition = catalog.get_definition("mcp:example")
        assert definition.publisher == "preset"
        assert definition.mcp_base_url == "https://mcp.example.com"
        assert catalog.preset_for_url("https://mcp.example.com/other").key == "mcp:example"
        row = {"provider": "mcp:https://mcp.example.com", "server_url": "https://mcp.example.com"}
        assert catalog.connector_key_for_row(row) == "mcp:example"

    def test_base_url(self):
        assert catalog.base_url("https://a.example.com:8443/x/y") == "https://a.example.com:8443"
        assert catalog.base_url("not a url") == ""


class TestFieldHints:
    """Hints are short, carry no "Optional" (the form stars required fields) and link inline."""

    @staticmethod
    def _field(connector: str, key: str) -> catalog.CredentialField:
        return {f.key: f for f in catalog.get_definition(connector).credential_fields}[key]

    def test_telegram_chat_hint_links_get_updates(self):
        chat = self._field("telegram", "chat_id")
        assert "<link>getUpdates</link>" in chat.hint
        assert chat.hint_url == "https://core.telegram.org/bots/api#getupdates"
        assert "https://" not in chat.hint
        assert len(chat.hint) <= 120
        assert chat.to_dict()["hint_url"] == chat.hint_url

    def test_github_token_hint_links_the_token_page(self):
        token = self._field("github", "access_token")
        assert "<link>Create a token on GitHub</link>" in token.hint
        assert token.hint_url == "https://github.com/settings/personal-access-tokens/new"

    def test_no_hint_says_optional(self):
        for definition in catalog.all_definitions():
            for field in (*definition.credential_fields, *definition.setup_fields):
                if field.hint:
                    assert "optional" not in field.hint.lower(), (definition.key, field.key)
                    # A link needs somewhere to go.
                    assert ("<link>" in field.hint) == bool(field.hint_url), (definition.key, field.key)

    def test_a_field_without_a_link_sends_none(self):
        assert self._field("telegram", "token").to_dict()["hint_url"] is None


def test_atlassian_preset_is_part_of_confluence():
    """One Confluence card: syncing pages and the Jira/Confluence agent actions."""
    from docsgpt.connectors import catalog

    atlassian = catalog.get_definition("mcp:atlassian")
    assert atlassian.part_of == "confluence"
    assert atlassian.to_dict()["part_of"] == "confluence"
    assert catalog.get_definition("confluence").to_dict()["part_of"] is None


def test_composio_connect_preset_is_available():
    """Composio Connect is exposed as a remote OAuth MCP preset."""
    composio = catalog.get_definition("mcp:composio")
    assert composio is not None
    assert composio.name == "Composio Connect"
    assert composio.category == "business"
    assert composio.icon == "composio"
    assert composio.mcp_url == "https://connect.composio.dev/mcp"
    assert composio.auth_kind == "mcp_oauth"
    assert composio.capabilities == ("read", "write")
    assert composio.docs_url == "https://docs.composio.dev/docs/composio-connect"
