"""The stack ``docsgpt up`` runs: where it lives and what its ``.env`` holds."""

from __future__ import annotations

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
EXPOSURES = ("local", "network", "domain")

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


def _profiles(env: Mapping[str, str]) -> set[str]:
    return {name.strip() for name in env.get("COMPOSE_PROFILES", "").split(",") if name.strip()}


def exposure(env: Mapping[str, str]) -> str:
    """Who can reach the stack, read back from its ``.env``: local, network or domain."""
    if "https" in _profiles(env) and env.get("DOCSGPT_DOMAIN"):
        return "domain"
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
    secret: Optional[Callable[[], str]] = None,
    lan_ip: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """The ``.env`` changes for an ``up``: only keys that change, ``None`` for a key to remove.

    Settings the user did not ask to change are left alone, secrets are generated
    once, and the database password and the credential encryption key are only set
    for a database that does not exist yet: Postgres reads the password when the
    volume is created, and credentials an existing database already holds are
    sealed with the key it ran with.

    Given ``lan_ip``, ``API_URL`` follows the address DocsGPT is opened at (see
    :func:`public_api_url`); the worker keeps its own in-stack value from the
    Compose file.
    """
    secret = secret or (lambda: secrets.token_hex(32))
    wanted: dict[str, Optional[str]] = {"DOCSGPT_IMAGE_TAG": image_tag}

    if domain and expose is None:
        expose = "domain"
    if expose is None and "DOCSGPT_BIND" not in existing and "COMPOSE_PROFILES" not in existing:
        expose = "local"
    if expose == "local":
        wanted.update(DOCSGPT_BIND="127.0.0.1", COMPOSE_PROFILES=None, DOCSGPT_DOMAIN=None)
    elif expose == "network":
        wanted.update(DOCSGPT_BIND="0.0.0.0", COMPOSE_PROFILES=None, DOCSGPT_DOMAIN=None)
    elif expose == "domain":
        if not domain:
            raise ValueError("exposing DocsGPT on a domain needs the domain name")
        wanted.update(DOCSGPT_BIND="127.0.0.1", COMPOSE_PROFILES="https", DOCSGPT_DOMAIN=domain)
    elif expose is not None:
        raise ValueError(f"unknown exposure {expose!r}; choose one of: {', '.join(EXPOSURES)}")
    if expose in ("network", "domain") and not existing.get("AUTH_TYPE"):
        wanted["AUTH_TYPE"] = "simple_jwt"

    for key in ("INTERNAL_KEY", "JWT_SECRET_KEY"):
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
        api_url = public_api_url(existing, after, lan_ip)
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
    if mode == "domain":
        return f"https://{env['DOCSGPT_DOMAIN']}"
    if mode == "network":
        bind = env.get("DOCSGPT_BIND", "")
        host = lan_ip if bind in _ALL_INTERFACES else bind
        return f"http://{host}:{_port(env)}"
    return f"http://localhost:{_port(env)}"


def public_api_url(existing: Mapping[str, str], after: Mapping[str, str], lan_ip: str) -> Optional[str]:
    """The ``API_URL`` for the settings in ``after``: a URL, ``None`` to remove it, ``""`` to leave it.

    The API builds agent image, webhook, device pairing and MCP OAuth callback
    URLs from ``API_URL``, and without it they point at ``http://localhost:7091``.
    It is set to the address :func:`url` prints, and dropped when that is the
    default anyway. A value the operator wrote (anything other than what this
    function would have written for the previous settings) is never touched.

    Args:
        existing: The settings before this ``up``.
        after: The settings this ``up`` writes.
        lan_ip: This machine's network address.

    Returns:
        The new value, ``None`` to remove the key, or ``""`` to leave it as it is.
    """
    current = existing.get("API_URL")
    if current and current != url(existing, lan_ip):
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
    from jose import jwt

    return jwt.encode({"sub": "local"}, secret_key, algorithm="HS256")
