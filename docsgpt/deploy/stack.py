"""The stack ``docsgpt up`` runs: where it lives and what its ``.env`` holds."""

from __future__ import annotations

import ipaddress
import os
import secrets
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Optional

from docsgpt.core import paths

COMPOSE_FILE = "docker-compose.yaml"
RECORD_FILE = "install.json"
DEFAULT_PORT = 7091
# What the app uses when API_URL is unset (docsgpt/core/settings/workers.py).
DEFAULT_API_URL = f"http://localhost:{DEFAULT_PORT}"
EXPOSURES = ("local", "network", "ip", "domain")
# The decider sidecar: the Compose profile that starts it, and where the backend and worker reach it.
DECIDER_PROFILE = "decider"
DECIDER_URL = "http://decider:7095"
# User accounts: the Compose profile that starts Keycloak, and what its docsgpt realm holds
# (the realm itself is in the Compose file, imported on Keycloak's first start).
ACCOUNTS_PROFILE = "accounts"
KEYCLOAK_REALM = "docsgpt"
KEYCLOAK_CLIENT_ID = "docsgpt"
KEYCLOAK_ADMIN_USER = "admin"
KEYCLOAK_ADMIN_GROUP = "docsgpt-admins"
# The backend settings `--accounts` writes, recomputed from the address on every `up` while
# accounts are on and removed when they are turned off. OIDC_CLIENT_SECRET and
# KEYCLOAK_ADMIN_PASSWORD are not among them: the imported realm holds the secret, so it
# stays for the day accounts are turned on again.
ACCOUNT_SETTINGS = (
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_FRONTEND_URL",
    "OIDC_REDIRECT_URI",
    "OIDC_ADMIN_GROUPS",
)

PROVIDERS = {
    "docsgpt": "DocsGPT public API (free, no key)",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "openai-compatible": "OpenAI-compatible server (Ollama, vLLM, LM Studio, ...)",
}

# The public key credentials are sealed with when ENCRYPTION_SECRET_KEY is unset. Kept here
# rather than imported: docsgpt.security.encryption loads the settings of whatever runs this.
DEFAULT_ENCRYPTION_KEY = "default-docsgpt-encryption-key"

_LOCAL_BINDS = ("", "127.0.0.1", "localhost", "::1")
_ALL_INTERFACES = ("0.0.0.0", "::")


def compose_source() -> Path:
    """The Compose file for this version: shipped in the wheel, or ``deployment/`` in a checkout."""
    packaged = paths.package_dir() / "deploy" / COMPOSE_FILE
    if packaged.is_file():
        return packaged
    root = paths.checkout_root()
    if root is not None:
        in_checkout = root / "deployment" / "docker-compose-standalone.yaml"
        if in_checkout.is_file():
            return in_checkout
    raise FileNotFoundError("the Compose file is missing from this docsgpt installation; reinstall the package")


def stack_dir(explicit: Optional[str]) -> Path:
    """Where the stack lives: ``--dir``, else ``DOCSGPT_HOME``, else the default home (never a checkout)."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get(paths.HOME_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return paths.default_home()


def _profile_list(env: Mapping[str, str]) -> list[str]:
    return [name.strip() for name in env.get("COMPOSE_PROFILES", "").split(",") if name.strip()]


def _profiles(env: Mapping[str, str]) -> set[str]:
    return set(_profile_list(env))


def runs_decider(env: Mapping[str, str]) -> bool:
    """Whether the stack's ``.env`` starts the decider sidecar (``docsgpt up --decider``)."""
    return DECIDER_PROFILE in _profiles(env)


def runs_accounts(env: Mapping[str, str]) -> bool:
    """Whether the stack's ``.env`` starts Keycloak for user accounts (``docsgpt up --accounts``)."""
    return ACCOUNTS_PROFILE in _profiles(env)


def public_ipv4(address: str) -> str:
    """``address`` as a public IPv4 address, the only kind ``--expose ip`` can get a certificate for.

    Args:
        address: The address to check.

    Returns:
        The address in its canonical form.

    Raises:
        ValueError: When it is not an IPv4 address, or one Let's Encrypt cannot reach (private,
            loopback, reserved, ...).
    """
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        raise ValueError(f"{address!r} is not an IP address") from None
    if parsed.version != 4:
        raise ValueError(f"{address} is an IPv6 address; --expose ip takes a public IPv4 address")
    if not parsed.is_global:
        raise ValueError(
            f"{address} is not a public address, so Let's Encrypt cannot reach it to issue a certificate. "
            "Pass this machine's public IPv4 address with --ip, or use --expose network on a private network."
        )
    return str(parsed)


def exposure(env: Mapping[str, str]) -> str:
    """Who can reach the stack, read back from its ``.env``: local, network, ip or domain."""
    if "https" in _profiles(env) and env.get("DOCSGPT_DOMAIN"):
        return "ip" if env.get("DOCSGPT_TLS") == "ip" else "domain"
    if env.get("DOCSGPT_BIND", "") not in _LOCAL_BINDS:
        return "network"
    return "local"


def provider_settings(
    name: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """The model settings for a provider choice; keys another provider used are cleared."""
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose one of: {', '.join(PROVIDERS)}")
    if name == "docsgpt":
        return {"LLM_PROVIDER": "docsgpt", "API_KEY": None, "LLM_NAME": None, "OPENAI_BASE_URL": None}
    if name == "openai-compatible":
        if not base_url:
            raise ValueError("an OpenAI-compatible server needs a base URL, e.g. http://host.docker.internal:11434/v1")
        if not model:
            raise ValueError("an OpenAI-compatible server needs a model name")
        return {
            "LLM_PROVIDER": "openai",
            "API_KEY": api_key or "not-needed",
            "LLM_NAME": model,
            "OPENAI_BASE_URL": base_url,
        }
    if not api_key:
        raise ValueError(f"{PROVIDERS[name]} needs an API key")
    # Without LLM_NAME the model catalog picks the provider's first model.
    return {"LLM_PROVIDER": name, "API_KEY": api_key, "LLM_NAME": model or None, "OPENAI_BASE_URL": None}


def plan(
    existing: Mapping[str, str],
    *,
    image_tag: str,
    fresh_database: bool,
    expose: Optional[str] = None,
    domain: Optional[str] = None,
    port: Optional[int] = None,
    provider: Optional[Mapping[str, Optional[str]]] = None,
    docling: Optional[bool] = None,
    decider: Optional[bool] = None,
    ip: Optional[str] = None,
    accounts: Optional[bool] = None,
    secret: Optional[Callable[[], str]] = None,
    password: Optional[Callable[[], str]] = None,
    lan_ip: Optional[str] = None,
    written_api_url: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """The ``.env`` changes for an ``up``: only keys that change, ``None`` for a key to remove.

    Settings the user did not ask to change are left alone, secrets are generated
    once, and the database password and the credential encryption key are only set
    for a database that does not exist yet: Postgres reads the password when the
    volume is created, and credentials an existing database already holds are
    sealed with the key it ran with.

    ``decider`` turns the decider sidecar on (its Compose profile, and ``DECISION_BASE_URL``
    pointing at it) or off, leaving a ``DECISION_BASE_URL`` that names another server alone;
    ``None`` keeps what the last ``up`` chose. Without it the model runs in the API process.
    A stack that runs the decider gets a ``DECISION_KEY`` when it has none; turning the
    decider off keeps the key, which a server on the host may use.

    ``expose="ip"`` serves HTTPS on the public IPv4 address ``ip`` (a Let's Encrypt IP
    certificate, see the Compose file), with no domain. ``accounts`` turns Keycloak user
    accounts on or off (``None`` keeps what the last ``up`` chose); they need HTTPS, so
    the ``ip`` or ``domain`` exposure. While they are on, ``AUTH_TYPE=oidc`` and the
    ``OIDC_*`` settings follow the address; turned off, the stack goes back to the
    ``simple_jwt`` access token.

    Given ``lan_ip``, ``API_URL`` follows the address DocsGPT is opened at (see
    :func:`public_api_url`; ``written_api_url`` is the value the last ``up``
    recorded writing); the worker keeps its own in-stack value from the Compose
    file.
    """
    secret = secret or (lambda: secrets.token_hex(32))
    password = password or (lambda: secrets.token_urlsafe(12))
    wanted: dict[str, Optional[str]] = {"DOCSGPT_IMAGE_TAG": image_tag}

    if domain and expose is None:
        expose = "domain"
    if ip and expose is None:
        expose = "ip"
    if expose is None and "DOCSGPT_BIND" not in existing and "COMPOSE_PROFILES" not in existing:
        expose = "local"
    profiles = _profiles(existing)
    if expose == "local":
        wanted.update(DOCSGPT_BIND="127.0.0.1", DOCSGPT_DOMAIN=None, DOCSGPT_TLS=None)
        profiles.discard("https")
    elif expose == "network":
        wanted.update(DOCSGPT_BIND="0.0.0.0", DOCSGPT_DOMAIN=None, DOCSGPT_TLS=None)
        profiles.discard("https")
    elif expose == "ip":
        if not ip:
            raise ValueError("serving DocsGPT on this machine's IP address needs the address")
        wanted.update(DOCSGPT_BIND="127.0.0.1", DOCSGPT_DOMAIN=public_ipv4(ip), DOCSGPT_TLS="ip")
        profiles.add("https")
    elif expose == "domain":
        if not domain:
            raise ValueError("exposing DocsGPT on a domain needs the domain name")
        wanted.update(DOCSGPT_BIND="127.0.0.1", DOCSGPT_DOMAIN=domain, DOCSGPT_TLS=None)
        profiles.add("https")
    elif expose is not None:
        raise ValueError(f"unknown exposure {expose!r}; choose one of: {', '.join(EXPOSURES)}")
    if decider:
        # The sidecar speaks the decide protocol, whatever server the stack called before.
        wanted.update(DECISION_BASE_URL=DECIDER_URL, DECISION_PROTOCOL=None)
        profiles.add(DECIDER_PROFILE)
    elif decider is not None:
        if existing.get("DECISION_BASE_URL") == DECIDER_URL:
            wanted["DECISION_BASE_URL"] = None
            if existing.get("DECISION_MODE") == "api":  # without a URL that would leave no model at all
                wanted["DECISION_MODE"] = None
        profiles.discard(DECIDER_PROFILE)
    after_tls = {**existing, **wanted}
    https_site = after_tls.get("DOCSGPT_DOMAIN") if "https" in profiles else None
    if accounts is None:
        accounts = ACCOUNTS_PROFILE in profiles
    if accounts:
        if not https_site:
            raise ValueError(
                "user accounts sign people in over HTTPS: serve DocsGPT on this machine's IP address "
                "(--expose ip) or on a domain (--domain) with them, or turn them off with --no-accounts"
            )
        profiles.add(ACCOUNTS_PROFILE)
        site = f"https://{https_site}"
        wanted.update(
            DOCSGPT_ACCOUNTS="on",
            AUTH_TYPE="oidc",
            OIDC_ISSUER=f"{site}/auth/realms/{KEYCLOAK_REALM}",
            OIDC_CLIENT_ID=KEYCLOAK_CLIENT_ID,
            OIDC_FRONTEND_URL=site,
            OIDC_REDIRECT_URI=f"{site}/api/auth/oidc/callback",
            OIDC_ADMIN_GROUPS=KEYCLOAK_ADMIN_GROUP,
        )
        if not existing.get("OIDC_CLIENT_SECRET"):
            wanted["OIDC_CLIENT_SECRET"] = secret()
        if not existing.get("KEYCLOAK_ADMIN_PASSWORD"):
            wanted["KEYCLOAK_ADMIN_PASSWORD"] = password()
    elif ACCOUNTS_PROFILE in _profiles(existing):
        profiles.discard(ACCOUNTS_PROFILE)
        wanted.update({key: None for key in ACCOUNT_SETTINGS}, DOCSGPT_ACCOUNTS=None, AUTH_TYPE="simple_jwt")
    if profiles != _profiles(existing):
        kept = [name for name in _profile_list(existing) if name in profiles]
        wanted["COMPOSE_PROFILES"] = ",".join(kept + sorted(profiles - set(kept))) or None
    if expose in ("network", "ip", "domain") and not existing.get("AUTH_TYPE") and "AUTH_TYPE" not in wanted:
        wanted["AUTH_TYPE"] = "simple_jwt"

    keys = ["INTERNAL_KEY", "JWT_SECRET_KEY"]
    if DECIDER_PROFILE in profiles:
        # The decider listens on the stack network and refuses to start without its own key.
        keys.append("DECISION_KEY")
    for key in keys:
        if not existing.get(key):
            wanted[key] = secret()
    if fresh_database:
        for key in ("POSTGRES_PASSWORD", "ENCRYPTION_SECRET_KEY"):
            if not existing.get(key):
                wanted[key] = secret()
    if "VITE_API_STREAMING" not in existing:
        wanted["VITE_API_STREAMING"] = "true"
    if port is not None:
        wanted["DOCSGPT_PORT"] = str(port)
    if docling is not None:
        wanted["DOCSGPT_IMAGE_VARIANT"] = "-docling" if docling else None
    if provider is None and "LLM_PROVIDER" not in existing:
        provider = provider_settings("docsgpt")
    if provider:
        wanted.update(provider)
    if lan_ip is not None:
        after = {key: value for key, value in {**existing, **wanted}.items() if value is not None}
        api_url = public_api_url(existing, after, lan_ip, written_api_url)
        if api_url != "":
            wanted["API_URL"] = api_url

    return {
        key: value
        for key, value in wanted.items()
        if (value is None and key in existing) or (value is not None and existing.get(key) != value)
    }


def _port(env: Mapping[str, str]) -> str:
    return env.get("DOCSGPT_PORT") or str(DEFAULT_PORT)


def url(env: Mapping[str, str], lan_ip: str) -> str:
    """The address to open DocsGPT at."""
    mode = exposure(env)
    if mode in ("ip", "domain"):
        return f"https://{env['DOCSGPT_DOMAIN']}"
    if mode == "network":
        bind = env.get("DOCSGPT_BIND", "")
        host = lan_ip if bind in _ALL_INTERFACES else bind
        return f"http://{host}:{_port(env)}"
    return f"http://localhost:{_port(env)}"


def owns_api_url(existing: Mapping[str, str], written: Optional[str], lan_ip: str) -> bool:
    """Whether ``API_URL`` in ``existing`` is ``up``'s to change rather than the operator's.

    It is when it is unset, the app's default, the value the last ``up`` recorded
    writing, or the address ``up`` would write for these settings (installs from
    before the record kept it).

    Args:
        existing: The settings before this ``up``.
        written: The ``API_URL`` the last ``up`` recorded writing, if any.
        lan_ip: This machine's network address.

    Returns:
        True when ``up`` may replace or remove it.
    """
    current = existing.get("API_URL")
    return not current or current in (DEFAULT_API_URL, written, url(existing, lan_ip))


def public_api_url(
    existing: Mapping[str, str], after: Mapping[str, str], lan_ip: str, written: Optional[str] = None
) -> Optional[str]:
    """The ``API_URL`` for the settings in ``after``: a URL, ``None`` to remove it, ``""`` to leave it.

    The API builds agent image, webhook, device pairing and MCP OAuth callback
    URLs from ``API_URL``, and without it they point at ``http://localhost:7091``.
    It is set to the address :func:`url` prints, and dropped when that is the
    default anyway. A value the operator wrote (see :func:`owns_api_url`) is
    never touched.

    Args:
        existing: The settings before this ``up``.
        after: The settings this ``up`` writes.
        lan_ip: This machine's network address.
        written: The ``API_URL`` the last ``up`` recorded writing, if any.

    Returns:
        The new value, ``None`` to remove the key, or ``""`` to leave it as it is.
    """
    if not owns_api_url(existing, written, lan_ip):
        return ""
    wanted = url(after, lan_ip)
    return None if wanted == DEFAULT_API_URL else wanted


def health_url(env: Mapping[str, str]) -> str:
    """The API health check, reached from this machine whatever the exposure."""
    bind = env.get("DOCSGPT_BIND", "")
    host = "127.0.0.1" if bind in _LOCAL_BINDS or bind in _ALL_INTERFACES else bind
    return f"http://{host}:{_port(env)}/api/health"


def simple_jwt_token(secret_key: str) -> str:
    """The token the API accepts under ``AUTH_TYPE=simple_jwt`` (it signs the same payload at start)."""
    import jwt

    return jwt.encode({"sub": "local"}, secret_key, algorithm="HS256")
