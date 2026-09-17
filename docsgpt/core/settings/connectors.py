"""OAuth credentials for external source connectors."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class ConnectorSettings(SettingsGroup):
    """Client credentials and callback URLs for Google Drive, Microsoft, Confluence, GitHub and MCP."""

    # Google Drive integration.
    GOOGLE_CLIENT_ID: Optional[str] = Field(default=None, description="Google OAuth client id.")
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(default=None, description="Google OAuth client secret.")
    CONNECTOR_REDIRECT_BASE_URI: str = Field(
        default="http://127.0.0.1:7091/api/connectors/callback",
        description="OAuth callback URL; register it as-is in your provider's console (e.g. GCP).",
    )
    CONNECTOR_ALLOWED_ORIGINS: Optional[str] = Field(
        default=None,
        description=(
            "Comma-separated frontend origins allowed to receive connector OAuth results, e.g. "
            "https://docsgpt.example.com. The callback origin and OIDC_FRONTEND_URL are always allowed; a "
            "loopback callback also allows localhost:5173."
        ),
    )

    # Microsoft Entra ID (Azure AD) integration.
    MICROSOFT_CLIENT_ID: Optional[str] = Field(default=None, description="Azure AD application (client) id.")
    MICROSOFT_CLIENT_SECRET: Optional[str] = Field(default=None, description="Azure AD application client secret.")
    MICROSOFT_TENANT_ID: str = Field(
        default="common", description="Azure AD tenant id, or 'common' for multi-tenant."
    )
    MICROSOFT_AUTHORITY: Optional[str] = Field(
        default=None, description='Authority URL override, e.g. "https://login.microsoftonline.com/{tenant_id}".'
    )

    # Confluence Cloud integration.
    CONFLUENCE_CLIENT_ID: Optional[str] = Field(default=None, description="Confluence Cloud OAuth client id.")
    CONFLUENCE_CLIENT_SECRET: Optional[str] = Field(default=None, description="Confluence Cloud OAuth client secret.")

    # GitHub source.
    GITHUB_ACCESS_TOKEN: Optional[str] = Field(default=None, description="GitHub PAT with read access to repositories.")

    MCP_OAUTH_REDIRECT_URI: Optional[str] = Field(
        default=None, description="Public callback URL for MCP OAuth; unset derives it from CONNECTOR_REDIRECT_BASE_URI."
    )
