"""The connector catalog: every service DocsGPT can connect to.

A connector is something the user connects once (an OAuth sign-in, an API key
or an MCP server). Each connection it produces can feed Sources (content
synced into DocsGPT) and Tools (actions an agent can take). The definitions
here are declarative: they say how a connector signs in, which server
settings it needs, what it can sync and which tools it creates, so the API
and the frontend never hard-code a list of services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import yaml

from docsgpt.core.settings import settings

CATEGORIES = ("files", "knowledge", "projects", "dev", "business", "messaging", "database", "search", "custom")
AUTH_KINDS = ("oauth", "mcp_oauth", "api_key", "none", "mcp")
PUBLISHERS = ("built_in", "preset", "custom")


@dataclass(frozen=True)
class CredentialField:
    """One field the user fills in to connect an ``api_key`` connector.

    Attributes:
        key: Name the credential is stored and passed to the tool or loader
            under, e.g. ``token`` or ``aws_access_key_id``.
        label: English label; the frontend shows the translated
            ``settings.connectors.fields.<key>`` when it has one.
        secret: Masked in the form and never returned by the API.
        required: Whether connecting fails without it.
        parameter: A tool parameter this field sets. When the connection has
            a value for it, every call through the connection uses that
            value and the model is not asked for the parameter (Telegram's
            default chat).
        hint: English help shown under the field; the frontend shows the
            translated ``settings.connectors.fieldHints.<connector>_<key>``.
    """

    key: str
    label: str
    secret: bool = True
    required: bool = True
    parameter: Optional[str] = None
    hint: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "secret": self.secret,
            "required": self.required,
            "parameter": self.parameter,
            "hint": self.hint,
        }


@dataclass(frozen=True)
class ConnectorDefinition:
    """How one connector signs in and what a connection to it provides.

    Attributes:
        key: Catalog key, stored on each connection as ``connector_key``.
        name: Display name.
        description: One line shown on the catalog card.
        icon: Frontend asset key (``assets/connectors/<icon>.svg``).
        category: One of :data:`CATEGORIES`.
        auth_kind: ``oauth`` (server-side OAuth app), ``mcp_oauth`` (MCP
            OAuth with dynamic client registration), ``api_key`` (fields the
            user pastes), ``none`` or ``mcp`` (a custom MCP server whose auth
            the user picks).
        capabilities: Any of ``sync``, ``read``, ``write``.
        credential_fields: Fields asked for by ``api_key`` connectors.
        required_settings: Server settings that must be set for the
            connector to be usable, e.g. ``GOOGLE_CLIENT_ID``.
        sync_ingestor: Ingest loader a synced source uses (``google_drive``,
            ``s3``), or None when the connector cannot sync.
        default_sync_frequency: Sync frequency preselected in the wizard.
        setup_fields: Per-source fields asked when choosing what to sync
            (an S3 bucket, Reddit search queries).
        tool_templates: ``user_tools`` names created on connect.
        setup: What the wizard does after sign-in: ``tools`` is ``auto``
            (created and enabled), ``ask`` or ``off``; ``sync`` likewise.
        mcp_url: MCP endpoint for presets, and for a built-in connector whose
            tool is its service's own MCP server (GitHub).
        mcp_write_url: The same server's endpoint that also offers write
            actions, which a connection opts into and an admin can forbid
            (GitHub's full server beside its read-only one). ``mcp_url``
            stays the default.
        publisher: ``built_in``, ``preset`` or ``custom``.
        docs_url: Setup guide for admins.
        oauth_scopes: Scopes an MCP preset requests.
        part_of: Another connector this one is shown under, for one service
            offered two ways (the Atlassian MCP preset under Confluence).
        oauth_settings: Server settings that add a second sign-in, OAuth,
            to an ``api_key`` connector (GitHub's "Sign in with GitHub"
            through a GitHub App). Unlike ``required_settings`` the
            connector works without them, with pasted credentials only.
    """

    key: str
    name: str
    description: str
    icon: str
    category: str
    auth_kind: str
    capabilities: tuple[str, ...] = ()
    credential_fields: tuple[CredentialField, ...] = ()
    required_settings: tuple[str, ...] = ()
    sync_ingestor: Optional[str] = None
    default_sync_frequency: str = "weekly"
    setup_fields: tuple[CredentialField, ...] = ()
    tool_templates: tuple[str, ...] = ()
    setup: dict = field(default_factory=lambda: {"tools": "auto", "sync": "ask"})
    mcp_url: Optional[str] = None
    mcp_write_url: Optional[str] = None
    publisher: str = "built_in"
    docs_url: Optional[str] = None
    oauth_scopes: tuple[str, ...] = ()
    part_of: Optional[str] = None
    oauth_settings: tuple[str, ...] = ()

    @property
    def oauth_configured(self) -> bool:
        """Whether the optional OAuth sign-in has every server setting it needs."""
        return bool(self.oauth_settings) and all(getattr(settings, name, None) for name in self.oauth_settings)

    @property
    def sign_in_methods(self) -> list[str]:
        """How a user can connect, preferred first: ``auth_kind``, after OAuth when that is set up."""
        return ["oauth", self.auth_kind] if self.oauth_configured else [self.auth_kind]

    @property
    def missing_settings(self) -> list[str]:
        """Server settings this connector needs that are not set."""
        return [name for name in self.required_settings if not getattr(settings, name, None)]

    @property
    def configured(self) -> bool:
        """Whether every required server setting is set."""
        return not self.missing_settings

    @property
    def mcp_base_url(self) -> Optional[str]:
        """``scheme://host`` of the preset's MCP endpoint (the MCP session key)."""
        return base_url(self.mcp_url) if self.mcp_url else None

    def to_dict(self) -> dict:
        """Serialise the parts the frontend needs (never server secrets)."""
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "category": self.category,
            "auth_kind": self.auth_kind,
            "capabilities": list(self.capabilities),
            "credential_fields": [f.to_dict() for f in self.credential_fields],
            "setup_fields": [f.to_dict() for f in self.setup_fields],
            "sync_ingestor": self.sync_ingestor,
            "default_sync_frequency": self.default_sync_frequency,
            "tool_templates": list(self.tool_templates),
            "setup": dict(self.setup),
            "mcp_url": self.mcp_url,
            "writes_opt_in": bool(self.mcp_write_url),
            "publisher": self.publisher,
            "docs_url": self.docs_url,
            "oauth_scopes": list(self.oauth_scopes),
            "part_of": self.part_of,
            "sign_in_methods": self.sign_in_methods,
        }


def base_url(url: Optional[str]) -> str:
    """``scheme://netloc`` of ``url``, the key MCP sessions are stored under."""
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


_DOCS = "https://docs.docsgpt.cloud/Guides/Connectors"
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/readonly"
GITHUB_MCP_WRITE_URL = "https://api.githubcopilot.com/mcp/"

# Tool templates any connector's server can use (an MCP server, an OpenAPI
# spec): a tool made from one belongs to its connection, not to a connector.
_GENERIC_TOOL_TEMPLATES = frozenset({"mcp_tool", "api_tool"})

_BUILT_IN: tuple[ConnectorDefinition, ...] = (
    ConnectorDefinition(
        key="google_drive",
        name="Google Drive",
        description="Sync Docs, Sheets and PDFs into Knowledge.",
        icon="drive",
        category="files",
        auth_kind="oauth",
        capabilities=("sync",),
        required_settings=("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
        sync_ingestor="google_drive",
        setup={"tools": "off", "sync": "ask"},
        docs_url=f"{_DOCS}#google-drive",
    ),
    ConnectorDefinition(
        key="share_point",
        name="SharePoint",
        description="Sync files from SharePoint sites and OneDrive into Knowledge.",
        icon="sharepoint",
        category="files",
        auth_kind="oauth",
        capabilities=("sync",),
        required_settings=("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"),
        sync_ingestor="share_point",
        setup={"tools": "off", "sync": "ask"},
        docs_url=f"{_DOCS}#sharepoint-and-onedrive",
    ),
    ConnectorDefinition(
        key="confluence",
        name="Confluence",
        description="Sync Confluence spaces and pages into Knowledge.",
        icon="confluence",
        category="knowledge",
        auth_kind="oauth",
        capabilities=("sync",),
        required_settings=("CONFLUENCE_CLIENT_ID", "CONFLUENCE_CLIENT_SECRET"),
        sync_ingestor="confluence",
        setup={"tools": "off", "sync": "ask"},
        docs_url=f"{_DOCS}#confluence",
    ),
    ConnectorDefinition(
        key="github",
        name="GitHub",
        description="Sync repositories into Knowledge and let agents read code, issues and pull requests.",
        icon="github",
        category="dev",
        # A token works with no admin setup; a GitHub App adds Sign in with GitHub.
        auth_kind="api_key",
        capabilities=("sync", "read"),
        credential_fields=(CredentialField("access_token", "Personal access token"),),
        oauth_settings=("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_APP_SLUG"),
        sync_ingestor="github",
        setup_fields=(CredentialField("repo_url", "Repository", secret=False),),
        # GitHub's own MCP server, read-only unless the connection opts into
        # changes (issues, comments, pull requests) and an admin allows them.
        tool_templates=("mcp_tool",),
        mcp_url=GITHUB_MCP_URL,
        mcp_write_url=GITHUB_MCP_WRITE_URL,
        setup={"tools": "ask", "sync": "ask"},
        docs_url=f"{_DOCS}#github",
    ),
    ConnectorDefinition(
        key="s3",
        name="Amazon S3",
        description="Sync documents from an S3 bucket into Knowledge.",
        icon="s3",
        category="files",
        auth_kind="api_key",
        capabilities=("sync",),
        credential_fields=(
            CredentialField("aws_access_key_id", "Access key ID", secret=False),
            CredentialField("aws_secret_access_key", "Secret access key"),
            CredentialField("region", "Region", secret=False, required=False),
            CredentialField("endpoint_url", "Custom endpoint URL", secret=False, required=False),
        ),
        sync_ingestor="s3",
        setup_fields=(
            CredentialField("bucket", "Bucket", secret=False),
            CredentialField("prefix", "Path prefix", secret=False, required=False),
        ),
        setup={"tools": "off", "sync": "ask"},
        docs_url=f"{_DOCS}#amazon-s3",
    ),
    ConnectorDefinition(
        key="reddit",
        name="Reddit",
        description="Sync Reddit posts that match your searches into Knowledge.",
        icon="reddit",
        category="search",
        auth_kind="api_key",
        capabilities=("sync",),
        credential_fields=(
            CredentialField("client_id", "Client ID", secret=False),
            CredentialField("client_secret", "Client secret"),
            CredentialField("user_agent", "User agent", secret=False),
        ),
        sync_ingestor="reddit",
        setup_fields=(
            CredentialField("search_queries", "Search queries", secret=False),
            CredentialField("number_posts", "Number of posts", secret=False),
        ),
        setup={"tools": "off", "sync": "ask"},
    ),
    ConnectorDefinition(
        key="brave",
        name="Brave Search",
        description="Search the web and images with the Brave Search API.",
        icon="tool_brave",
        category="search",
        auth_kind="api_key",
        capabilities=("read",),
        credential_fields=(CredentialField("token", "API key"),),
        tool_templates=("brave",),
        setup={"tools": "auto", "sync": "off"},
    ),
    ConnectorDefinition(
        key="telegram",
        name="Telegram",
        description="Send messages and images to a Telegram chat.",
        icon="tool_telegram",
        category="messaging",
        auth_kind="api_key",
        capabilities=("write",),
        credential_fields=(
            CredentialField("token", "Bot token"),
            CredentialField(
                "chat_id",
                "Default chat ID",
                secret=False,
                required=False,
                parameter="chat_id",
                hint=(
                    "Optional. Messages go to this chat, and the AI cannot pick another. Add the bot to the "
                    "chat, send it a message, then find the chat's id in "
                    "https://api.telegram.org/bot<token>/getUpdates."
                ),
            ),
        ),
        tool_templates=("telegram",),
        setup={"tools": "auto", "sync": "off"},
    ),
    ConnectorDefinition(
        key="ntfy",
        name="ntfy",
        description="Send push notifications through an ntfy server.",
        icon="tool_ntfy",
        category="messaging",
        auth_kind="api_key",
        capabilities=("write",),
        credential_fields=(CredentialField("token", "Access token"),),
        tool_templates=("ntfy",),
        setup={"tools": "auto", "sync": "off"},
    ),
    ConnectorDefinition(
        key="postgres",
        name="PostgreSQL",
        description="Read the schema and run SQL against a Postgres database.",
        icon="tool_postgres",
        category="database",
        auth_kind="api_key",
        capabilities=("read", "write"),
        credential_fields=(CredentialField("token", "Connection string"),),
        tool_templates=("postgres",),
        setup={"tools": "auto", "sync": "off"},
    ),
    ConnectorDefinition(
        key="custom_mcp",
        name="MCP server",
        description="Connect any remote Model Context Protocol server.",
        icon="tool_mcp_tool",
        category="custom",
        auth_kind="mcp",
        capabilities=("read", "write"),
        tool_templates=("mcp_tool",),
        setup={"tools": "auto", "sync": "off"},
        publisher="custom",
    ),
    ConnectorDefinition(
        key="custom_openapi",
        name="OpenAPI / REST",
        description="Import an OpenAPI spec and call its endpoints as tools.",
        icon="tool_api_tool",
        category="custom",
        auth_kind="none",
        capabilities=("read", "write"),
        tool_templates=("api_tool",),
        setup={"tools": "ask", "sync": "off"},
        publisher="custom",
    ),
)

_PRESETS_FILE = Path(__file__).parent / "presets" / "mcp.yaml"


def _load_presets(path: Optional[Path] = None) -> tuple[ConnectorDefinition, ...]:
    """Read the curated MCP server presets shipped with the repository."""
    path = path or _PRESETS_FILE
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as fh:
        entries = yaml.safe_load(fh) or []
    presets = []
    for entry in entries:
        presets.append(
            ConnectorDefinition(
                key=entry["key"],
                name=entry["name"],
                description=entry["description"],
                icon=entry.get("icon") or "tool_mcp_tool",
                category=entry.get("category", "knowledge"),
                auth_kind=entry.get("auth_kind", "mcp_oauth"),
                capabilities=tuple(entry.get("capabilities") or ("read", "write")),
                tool_templates=("mcp_tool",),
                # Linear also syncs into Knowledge, read through its MCP server.
                sync_ingestor=entry.get("sync_ingestor"),
                setup={"tools": "auto", "sync": "ask" if entry.get("sync_ingestor") else "off"},
                mcp_url=entry["mcp_url"],
                publisher="preset",
                docs_url=entry.get("docs_url"),
                oauth_scopes=tuple(entry.get("oauth_scopes") or ()),
                part_of=entry.get("part_of"),
            )
        )
    return tuple(presets)


_REGISTRY: dict[str, ConnectorDefinition] = {}


def _registry() -> dict[str, ConnectorDefinition]:
    if not _REGISTRY:
        for definition in (*_BUILT_IN, *_load_presets()):
            _REGISTRY[definition.key] = definition
    return _REGISTRY


def all_definitions() -> list[ConnectorDefinition]:
    """Every catalog entry, built-ins first, then presets."""
    return list(_registry().values())


def get_definition(key: Optional[str]) -> Optional[ConnectorDefinition]:
    """The definition for ``key``, or None when it is not in the catalog."""
    if not key:
        return None
    return _registry().get(key)


def preset_for_url(url: Optional[str]) -> Optional[ConnectorDefinition]:
    """The MCP preset whose server shares ``url``'s base URL, if any."""
    target = base_url(url)
    if not target:
        return None
    for definition in _registry().values():
        if definition.publisher == "preset" and definition.mcp_base_url == target:
            return definition
    return None


def definition_for_tool(tool_name: str) -> Optional[ConnectorDefinition]:
    """The built-in connector that provides the ``user_tools`` template ``tool_name``."""
    if tool_name in _GENERIC_TOOL_TEMPLATES:
        return None
    for definition in _BUILT_IN:
        if definition.publisher == "built_in" and tool_name in definition.tool_templates:
            return definition
    return None


def parameter_fields(key: Optional[str]) -> tuple[CredentialField, ...]:
    """The credential fields of connector ``key`` that set a tool parameter."""
    definition = get_definition(key)
    if definition is None:
        return ()
    return tuple(f for f in definition.credential_fields if f.parameter)


def connector_key_for_row(row: dict) -> Optional[str]:
    """Catalog key for a ``connector_sessions`` row.

    Rows written before ``0038_connections`` carry no key; they are named from
    ``provider``. A custom MCP row whose server matches a preset is reported
    as that preset.
    """
    key = row.get("connector_key")
    provider = row.get("provider") or ""
    if not key:
        if provider.startswith("mcp:"):
            key = "custom_mcp"
        elif get_definition(provider):
            key = provider
    if key == "custom_mcp":
        preset = preset_for_url(row.get("server_url") or provider[4:])
        if preset:
            return preset.key
    return key


def tool_connector_keys() -> set[str]:
    """``user_tools`` names that belong to a built-in service connector."""
    return {
        name
        for definition in _BUILT_IN
        if definition.publisher == "built_in"
        for name in definition.tool_templates
        if name not in _GENERIC_TOOL_TEMPLATES
    }


def iter_by_category(definitions: Iterable[ConnectorDefinition]) -> dict[str, list[ConnectorDefinition]]:
    """Group definitions by category, keeping :data:`CATEGORIES` order."""
    grouped: dict[str, list[ConnectorDefinition]] = {c: [] for c in CATEGORIES}
    for definition in definitions:
        grouped.setdefault(definition.category, []).append(definition)
    return grouped


def reset_registry_for_tests() -> None:
    """Drop the cached registry so a test can load a different presets file."""
    _REGISTRY.clear()


def to_public(definition: ConnectorDefinition, **extra: Any) -> dict:
    """Definition dict plus request-specific fields (availability, counts)."""
    return {**definition.to_dict(), **extra}
