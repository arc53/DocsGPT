"""Tests for the connector catalog."""

from __future__ import annotations

import pytest
import yaml

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

    def test_drive_offers_its_picker_client_id_with_per_file_access(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-123.apps.googleusercontent.com")
        monkeypatch.setattr(settings, "GOOGLE_DRIVE_ACCESS", "file")
        assert catalog.get_definition("google_drive").to_dict()["picker_client_id"] == (
            "client-123.apps.googleusercontent.com"
        )
        monkeypatch.setattr(settings, "GOOGLE_DRIVE_ACCESS", "readonly")
        assert catalog.get_definition("google_drive").to_dict()["picker_client_id"] is None
        assert catalog.get_definition("share_point").to_dict()["picker_client_id"] is None


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
    def test_drawio_preset_connects_without_oauth(self):
        definition = catalog.get_definition("mcp:drawio")

        assert definition.publisher == "preset"
        assert definition.icon == "drawio"
        assert definition.category == "projects"
        assert definition.auth_kind == "mcp"
        assert definition.mcp_url == "https://mcp.draw.io/mcp"
        assert definition.capabilities == ("read",)
        assert definition.docs_url == "https://github.com/jgraph/drawio-mcp"
        assert definition.configured

    def test_coingecko_preset_connects_without_oauth(self):
        definition = catalog.get_definition("mcp:coingecko")

        assert definition.name == "CoinGecko"
        assert definition.publisher == "preset"
        assert definition.icon == "coingecko"
        assert definition.category == "business"
        assert definition.auth_kind == "mcp"
        assert definition.mcp_url == "https://mcp.api.coingecko.com/mcp"
        assert definition.capabilities == ("read",)
        assert definition.docs_url == "https://docs.coingecko.com/docs/mcp-server"
        assert definition.configured

    def test_trello_preset(self):
        definition = catalog.get_definition("mcp:trello")

        assert definition.name == "Trello"
        assert definition.description == "Find Trello boards and cards, and create and update cards."
        assert definition.icon == "trello"
        assert definition.category == "projects"
        assert definition.mcp_url == "https://mcp.trello.com/v1"
        assert definition.auth_kind == "mcp_oauth"
        assert definition.capabilities == ("read", "write")
        assert definition.docs_url == (
            "https://support.atlassian.com/trello/docs/connect-trello-to-ai-assistants-with-trello-mcp/"
        )


    def test_miro_preset_uses_the_catalog_contract(self):
        definition = catalog.get_definition("mcp:miro")

        assert definition is not None
        assert definition.name == "Miro"
        assert definition.icon == "miro"
        assert definition.category == "projects"
        assert definition.mcp_url == "https://mcp.miro.com/"
        assert definition.auth_kind == "mcp_oauth"
        assert definition.capabilities == ("read", "write")
        assert definition.docs_url == "https://developers.miro.com/docs/miro-mcp"

    def test_miro_preset_is_listed_with_the_other_remote_servers(self):
        presets = [d for d in catalog.all_definitions() if d.publisher == "preset"]

        assert "mcp:miro" in {preset.key for preset in presets}


    def test_resend_preset_exposes_email_actions(self):
        definition = catalog.get_definition("mcp:resend")

        assert definition.name == "Resend"
        assert definition.category == "messaging"
        assert definition.mcp_url == "https://mcp.resend.com/mcp"
        assert definition.auth_kind == "mcp_oauth"
        assert definition.capabilities == ("read", "write")
        assert definition.docs_url == "https://resend.com/docs/knowledge-base/mcp-server"

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


def test_clickup_is_a_remote_oauth_preset():
    clickup = catalog.get_definition("mcp:clickup")

    assert clickup.name == "ClickUp"
    assert clickup.icon == "clickup"
    assert clickup.category == "projects"
    assert clickup.auth_kind == "mcp_oauth"
    assert clickup.mcp_base_url == "https://mcp.clickup.com"
    assert clickup.capabilities == ("read", "write")
    assert clickup.docs_url == (
        "https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server"
    )


def test_zapier_preset_uses_remote_oauth_catalog_contract():
    zapier = catalog.get_definition("mcp:zapier")

    assert zapier.name == "Zapier"
    assert zapier.icon == "zapier"
    assert zapier.category == "business"
    assert zapier.mcp_url == "https://mcp.zapier.com/api/v1/connect"
    assert zapier.auth_kind == "mcp_oauth"
    assert zapier.capabilities == ("read", "write")
    assert zapier.docs_url == "https://docs.zapier.com/mcp/get-started/connect"

def test_canva_preset_in_catalog():
    canva_preset = catalog.get_definition("mcp:canva")
    
    assert canva_preset is not None
    assert canva_preset.mcp_url == "https://mcp.canva.com/mcp"
    assert canva_preset.auth_kind == "mcp_oauth"
    assert canva_preset.icon == "canva"
    assert "read" in canva_preset.capabilities
    assert "write" in canva_preset.capabilities

def test_calcom_preset_uses_remote_oauth_catalog_contract():
    calcom = catalog.get_definition("mcp:calcom")

    assert calcom.name == "Cal.com"
    assert calcom.icon == "calcom"
    assert calcom.category == "business"
    assert calcom.mcp_url == "https://mcp.cal.com/mcp"
    assert calcom.auth_kind == "mcp_oauth"
    assert calcom.capabilities == ("read", "write")
    assert calcom.docs_url == "https://cal.com/docs/mcp-server"


def test_airtable_preset_uses_remote_oauth_catalog_contract():
    airtable = catalog.get_definition("mcp:airtable")

    assert airtable.name == "Airtable"
    assert airtable.icon == "airtable"
    assert airtable.category == "database"
    assert airtable.mcp_url == "https://mcp.airtable.com/mcp"
    assert airtable.auth_kind == "mcp_oauth"
    assert airtable.capabilities == ("read", "write")
    assert airtable.docs_url == "https://airtable.com/developers/agents/mcp/getting-started"
def test_alphavantage_preset_uses_remote_oauth_catalog_contract():
    alphavantage = catalog.get_definition("mcp:alphavantage")

    assert alphavantage.name == "Alpha Vantage"
    assert alphavantage.icon == "alphavantage"
    assert alphavantage.category == "business"
    assert alphavantage.mcp_url == "https://mcp.alphavantage.co/mcp"
    assert alphavantage.auth_kind == "mcp_oauth"
    assert alphavantage.capabilities == ("read",)
    assert alphavantage.docs_url == "https://github.com/alphavantage/alpha_vantage_mcp"


def test_alphavantage_starts_with_core_tools_under_the_openai_limit():
    """133 tools exceed OpenAI's 128 per request; the core ones and the TOOL_CALL fallback start on."""
    default_actions = catalog.get_definition("mcp:alphavantage").default_actions

    assert 0 < len(default_actions) <= 32
    assert len(set(default_actions)) == len(default_actions)
    assert {"GLOBAL_QUOTE", "SYMBOL_SEARCH", "COMPANY_OVERVIEW", "EARNINGS", "CPI", "TOOL_CALL"} <= set(
        default_actions
    )


def test_presets_without_default_actions_turn_every_action_on():
    assert catalog.get_definition("mcp:notion").default_actions == ()


def test_preset_default_actions_load_from_yaml(tmp_path, monkeypatch):
    presets = tmp_path / "mcp.yaml"
    presets.write_text(
        "- key: mcp:example\n"
        "  name: Example\n"
        "  description: Example records.\n"
        "  mcp_url: https://mcp.example.com/mcp\n"
        "  default_actions: [search, fetch]\n"
    )
    monkeypatch.setattr(catalog, "_PRESETS_FILE", presets)

    assert catalog.get_definition("mcp:example").default_actions == ("search", "fetch")
def test_neon_preset_uses_remote_oauth_catalog_contract():
    neon = catalog.get_definition("mcp:neon")

    assert neon.name == "Neon"
    assert neon.icon == "neon"
    assert neon.category == "database"
    assert neon.mcp_url == "https://mcp.neon.tech/mcp"
    assert neon.auth_kind == "mcp_oauth"
    assert neon.capabilities == ("read", "write")
    assert neon.docs_url == "https://neon.com/docs/ai/neon-mcp-server"


def test_context7_preset_uses_remote_oauth_catalog_contract() -> None:
    context7 = catalog.get_definition("mcp:context7")

    assert context7.name == "Context7"
    assert context7.icon == "context7"
    assert context7.category == "dev"
    assert context7.mcp_url == "https://mcp.context7.com/mcp/oauth"
    assert context7.auth_kind == "mcp_oauth"
    assert context7.capabilities == ("read",)
    assert context7.docs_url == "https://context7.com/docs/resources/all-clients"


def test_twelvedata_preset_uses_remote_oauth_catalog_contract():
    twelvedata = catalog.get_definition("mcp:twelvedata")

    assert twelvedata is not None
    assert twelvedata.name == "Twelve Data"
    assert twelvedata.icon == "twelvedata"
    assert twelvedata.category == "business"
    assert twelvedata.mcp_url == "https://mcp.twelvedata.com/mcp"
    assert twelvedata.mcp_base_url == "https://mcp.twelvedata.com"
    assert twelvedata.auth_kind == "mcp_oauth"
    assert twelvedata.capabilities == ("read",)
    assert twelvedata.docs_url == "https://twelvedata.com/docs/mcp"


def test_presets_have_unique_keys_and_servers():
    """A repeated key overwrites a preset and a repeated host makes preset_for_url pick one."""
    entries = yaml.safe_load(catalog._PRESETS_FILE.read_text(encoding="utf-8"))
    keys = [entry["key"] for entry in entries]
    hosts = [catalog.base_url(entry["mcp_url"]) for entry in entries]

    assert len(keys) == len(set(keys))
    assert len(hosts) == len(set(hosts))


def test_cloudflare_preset_signs_in_with_mcp_oauth():
    cloudflare = catalog.get_definition("mcp:cloudflare")
    assert cloudflare.publisher == "preset"
    assert cloudflare.mcp_url == "https://mcp.cloudflare.com/mcp"
    assert cloudflare.auth_kind == "mcp_oauth"
    assert cloudflare.capabilities == ("read",)
    assert catalog.preset_for_url("https://mcp.cloudflare.com/mcp").key == "mcp:cloudflare"
