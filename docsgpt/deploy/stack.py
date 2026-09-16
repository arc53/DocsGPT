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
) -> dict[str, Optional[str]]:
    """The ``.env`` changes for an ``up``: only keys that change, ``None`` for a key to remove.

    Settings the user did not ask to change are left alone, secrets are generated
    once, and the database password is only set for a database that does not exist
    yet (Postgres reads it when the volume is created).
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
    if not existing.get("POSTGRES_PASSWORD") and fresh_database:
        wanted["POSTGRES_PASSWORD"] = secret()
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


def health_url(env: Mapping[str, str]) -> str:
    """The API health check, reached from this machine whatever the exposure."""
    bind = env.get("DOCSGPT_BIND", "")
    host = "127.0.0.1" if bind in _LOCAL_BINDS or bind in _ALL_INTERFACES else bind
    return f"http://{host}:{_port(env)}/api/health"


def simple_jwt_token(secret_key: str) -> str:
    """The token the API accepts under ``AUTH_TYPE=simple_jwt`` (it signs the same payload at start)."""
    from jose import jwt

    return jwt.encode({"sub": "local"}, secret_key, algorithm="HS256")
