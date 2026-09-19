"""Authentication, SSO and provisioning."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


#: Settings an OIDC deployment cannot run without; checked when AUTH_TYPE=oidc.
OIDC_REQUIRED = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_FRONTEND_URL")


class AuthSettings(SettingsGroup):
    """How users authenticate: none, a shared token, per-session JWTs, or OIDC SSO."""

    AUTH_TYPE: Optional[Literal["simple_jwt", "session_jwt", "oidc"]] = Field(
        default=None,
        description="Authentication mode: simple_jwt, session_jwt, oidc, or unset (None) for no authentication.",
    )
    JWT_SECRET_KEY: str = Field(
        default="",
        description=(
            "Signing key for session tokens and other signed capabilities. Required on every replica in "
            "production; local development may fall back to a key generated on disk."
        ),
    )
    ENCRYPTION_SECRET_KEY: str = Field(
        default="default-docsgpt-encryption-key",
        description="Key used to encrypt stored credentials such as tool and connector secrets.",
    )
    INTERNAL_KEY: Optional[str] = Field(
        default=None, description="Internal API key for worker-to-backend authentication."
    )

    # OIDC SSO (AUTH_TYPE=oidc): any OpenID Connect IdP with discovery (Authentik, Keycloak, ...).
    OIDC_ISSUER: Optional[str] = Field(
        default=None,
        description="OIDC issuer URL with discovery, e.g. https://auth.example.com/application/o/docsgpt/.",
    )
    OIDC_CLIENT_ID: Optional[str] = Field(default=None, description="OIDC client id.")
    OIDC_CLIENT_SECRET: Optional[str] = Field(
        default=None, description="OIDC client secret. Optional; PKCE is always used."
    )
    OIDC_SCOPES: str = Field(default="openid profile email", description="Scopes requested from the IdP.")
    OIDC_USER_ID_CLAIM: str = Field(
        default="sub", description="ID-token claim mapped to the DocsGPT user id."
    )
    OIDC_FRONTEND_URL: Optional[str] = Field(
        default=None, description="Browser-facing app origin, e.g. http://localhost:5173."
    )
    OIDC_REDIRECT_URI: Optional[str] = Field(
        default=None, description="Override for the callback URL; default is <request host>/api/auth/oidc/callback."
    )
    OIDC_SESSION_LIFETIME_SECONDS: int = Field(
        default=28800, gt=0, description="Lifetime of the minted session JWT in seconds (8h)."
    )
    OIDC_PROVIDER_NAME: Optional[str] = Field(
        default=None, description='Sign-in button label, e.g. "Acme SSO".'
    )
    OIDC_ALLOWED_GROUPS: Optional[str] = Field(
        default=None, description="Comma-separated group allowlist; unset admits any authenticated user."
    )
    OIDC_GROUPS_CLAIM: str = Field(
        default="groups", description="ID-token/userinfo claim carrying group membership."
    )
    OIDC_ADMIN_GROUPS: Optional[str] = Field(
        default=None, description="Comma-separated groups granted admin; unset means no OIDC admin mapping."
    )

    LOCAL_MODE_ADMIN: bool = Field(
        default=False,
        description=(
            "Grant admin without a database role. Persisted admin grants live in user_roles (AUTH_TYPE=oidc "
            "only); this is the only non-DB admin path, for AUTH_TYPE=None self-host. MUST stay False if "
            "networked."
        ),
    )

    # SCIM 2.0 provisioning (IdP-driven user create/deactivate at /scim/v2).
    SCIM_ENABLED: bool = Field(default=False, description="Enable SCIM 2.0 provisioning at /scim/v2.")
    SCIM_TOKEN: Optional[str] = Field(
        default=None, description="Bearer token for IdP SCIM clients (required when SCIM is enabled)."
    )

    # Personal access tokens: scoped user-level API credentials for CLI and CI/CD use.
    PAT_ENABLED: bool = Field(
        default=True,
        description=(
            "Allow users to create personal access tokens. Tokens are only issued under AUTH_TYPE=oidc or "
            "unset (None); simple_jwt and session_jwt have no stable user identity to bind a token to."
        ),
    )
    PAT_DEFAULT_LIFETIME_DAYS: int = Field(
        default=90, gt=0, description="Lifetime of a personal access token created without an explicit expiry."
    )
    PAT_MAX_LIFETIME_DAYS: int = Field(
        default=365, gt=0, description="Longest lifetime a user may request for a personal access token."
    )
    PAT_ALLOW_NON_EXPIRING: bool = Field(
        default=False,
        description="Let users create personal access tokens that never expire. Off by default.",
    )
    PAT_MAX_PER_USER: int = Field(
        default=25, gt=0, description="Maximum number of live personal access tokens per user."
    )

    @field_validator("AUTH_TYPE", mode="before")
    @classmethod
    def _normalize_auth_type(cls, v):
        # Unset spellings ("None", "") became None on the group base; this only case-folds a value.
        return normalize_choice(v)

    @model_validator(mode="after")
    def _require_dependent_settings(self):
        if self.AUTH_TYPE == "oidc":
            missing = [name for name in OIDC_REQUIRED if not getattr(self, name)]
            if missing:
                raise ValueError(f"AUTH_TYPE=oidc requires settings: {', '.join(missing)}")
        if self.SCIM_ENABLED and not self.SCIM_TOKEN:
            raise ValueError("SCIM_ENABLED requires settings: SCIM_TOKEN")
        if self.PAT_DEFAULT_LIFETIME_DAYS > self.PAT_MAX_LIFETIME_DAYS:
            raise ValueError("PAT_DEFAULT_LIFETIME_DAYS must not exceed PAT_MAX_LIFETIME_DAYS")
        return self
