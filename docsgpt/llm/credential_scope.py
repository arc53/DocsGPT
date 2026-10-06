"""Keep each deployment LLM credential on the endpoints it was configured for.

A deployment configures provider keys in settings (``OPENAI_API_KEY``,
``ANTHROPIC_API_KEY`` ..., the generic ``API_KEY`` for ``LLM_PROVIDER``,
``FALLBACK_LLM_API_KEY`` for ``FALLBACK_LLM_PROVIDER``) and in model catalogs
(an ``openai_compatible`` YAML's ``api_key_env`` with its ``base_url``). Each
of those keys belongs to the endpoints it was configured for, and to nothing
else.

The LLM classes call :func:`check_credential_scope` while they build their API
client, before any request is sent, with the endpoint they then pass to the
SDK explicitly: an SDK's own base-URL environment variable
(``OPENAI_BASE_URL`` read by the SDK rather than settings,
``ANTHROPIC_BASE_URL``, ``GOOGLE_GEMINI_BASE_URL``, the Vertex AI switch)
never decides where a key goes. A key the deployment configured may only
go to an origin (scheme, host and port) it was configured for, and over plain
http only to a local host (see :func:`plaintext_allowed`); anything else
raises :class:`CredentialScopeError` instead of sending it. Keys the deployment did
not configure (a user's own model key, the keyless placeholder, the public
DocsGPT key) are not deployment credentials and are not checked here: a user's
model carries its own endpoint, which ``LLMCreator`` pins.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Dict, Optional, Set
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: Endpoint the OpenAI client talks to when neither the model nor
#: ``OPENAI_BASE_URL`` names one.
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
#: Endpoint the Anthropic client is given when the model names none. Passed
#: explicitly, so the SDK's own ``ANTHROPIC_BASE_URL`` variable never applies.
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
#: The Gemini API endpoint the ``google-genai`` client is pinned to, so the
#: SDK's ``GOOGLE_GEMINI_BASE_URL`` and Vertex AI switches never apply.
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/"

# Settings that hold an LLM provider credential. Every value set here is a
# deployment credential, even when no endpoint claims it: such a key may not
# be sent anywhere.
_CREDENTIAL_SETTINGS = (
    "API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "OPEN_ROUTER_API_KEY",
    "NOVITA_API_KEY",
    "FALLBACK_LLM_API_KEY",
)


# Host-name suffixes that only resolve inside a private network: mDNS and
# Kubernetes cluster names (``.local``, ``.svc``), the reserved private-use
# ``.internal`` (Docker's ``host.docker.internal`` included) and ``.localhost``.
_INTERNAL_SUFFIXES = (".local", ".svc", ".internal", ".localhost")


class CredentialScopeError(ValueError):
    """An API key was about to be sent to an endpoint it does not belong to."""


def endpoint_origin(url: Optional[str]) -> str:
    """Return ``scheme://host:port`` for an http(s) ``url``, lowercased, with the default port.

    The scheme is part of the result, so an ``https`` endpoint and the same
    host over plain ``http`` are different origins.

    Args:
        url: An endpoint URL such as ``https://api.deepseek.com/v1``.

    Returns:
        The origin the URL connects to, or ``""`` when it is not an http(s)
        URL with a host.
    """
    if not url or not isinstance(url, str):
        return ""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return ""
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        port = 80 if scheme == "http" else 443
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}:{port}"


def plaintext_allowed(url: Optional[str]) -> bool:
    """Whether a configured key may be sent to ``url`` over plain http.

    Self-hosted model servers are commonly reached over http inside the
    deployment's own network, where the request never crosses the internet.
    Plain http is therefore accepted for a loopback, private (RFC 1918,
    ``fc00::/7``) or link-local address, a single-label host name (a Docker
    Compose service such as ``ollama``), and names under an internal suffix
    (``host.docker.internal``, ``*.svc.cluster.local``, ``*.internal``,
    ``*.local``, ``localhost`` and ``*.localhost``). Any other host needs https, unless
    ``LLM_ALLOW_PLAINTEXT_ENDPOINTS`` is set.

    Args:
        url: The endpoint URL.

    Returns:
        True for https, and for http to a local host or with the setting on.
    """
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() != "http":
        return True
    from docsgpt.core.settings import settings

    if getattr(settings, "LLM_ALLOW_PLAINTEXT_ENDPOINTS", False) is True:
        return True
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES)
    return address.is_loopback or address.is_private or address.is_link_local


def provider_endpoint(provider: str, settings) -> Optional[str]:
    """Return the endpoint a provider's LLM class uses when the model names none.

    Args:
        provider: A provider plugin name (``openai``, ``anthropic`` ...).
        settings: The application settings.

    Returns:
        The provider's endpoint URL, or ``None`` for providers that have no
        fixed endpoint (``openai_compatible``: each model carries its own) or
        that never send a deployment key (``docsgpt``).
    """
    if provider == "openai":
        base_url = settings.OPENAI_BASE_URL
        if isinstance(base_url, str) and base_url.strip():
            return base_url
        return OPENAI_DEFAULT_BASE_URL
    if provider == "anthropic":
        return ANTHROPIC_DEFAULT_BASE_URL
    if provider == "google":
        return GOOGLE_BASE_URL
    if provider == "groq":
        from docsgpt.llm.groq import GROQ_BASE_URL

        return GROQ_BASE_URL
    if provider == "openrouter":
        from docsgpt.llm.open_router import OPEN_ROUTER_BASE_URL

        return OPEN_ROUTER_BASE_URL
    if provider == "novita":
        from docsgpt.llm.novita import NOVITA_BASE_URL

        return NOVITA_BASE_URL
    return None


def credential_hosts(settings=None) -> Dict[str, Set[str]]:
    """Map every deployment LLM credential to the hosts it may be sent to.

    A provider's own key (as its plugin resolves it: the provider key, or
    ``API_KEY`` when the provider is ``LLM_PROVIDER``) belongs to the
    provider's endpoint. ``FALLBACK_LLM_API_KEY`` belongs to the endpoint of
    ``FALLBACK_LLM_PROVIDER``. A catalog model that names a ``base_url`` binds
    its key (its own, or its provider's) to that URL. A credential setting
    that nothing claims maps to an empty set.

    Args:
        settings: The settings to read; defaults to the process settings.

    Returns:
        ``{api_key: {"scheme://host:port", ...}}`` for every configured credential.
    """
    if settings is None:
        from docsgpt.core.settings import settings as process_settings

        settings = process_settings
    from docsgpt.llm.providers import ALL_PROVIDERS, PROVIDERS_BY_NAME

    hosts: Dict[str, Set[str]] = {}

    def claim(key, url: Optional[str] = None) -> None:
        if not key or not isinstance(key, str):
            return
        bucket = hosts.setdefault(key, set())
        origin = endpoint_origin(url)
        if origin:
            bucket.add(origin)

    def own_key(provider: str) -> Optional[str]:
        plugin = PROVIDERS_BY_NAME.get(provider)
        return plugin.get_api_key(settings) if plugin is not None else None

    for name in _CREDENTIAL_SETTINGS:
        claim(getattr(settings, name, None))

    for plugin in ALL_PROVIDERS:
        endpoint = provider_endpoint(plugin.name, settings)
        if endpoint:
            claim(plugin.get_api_key(settings), endpoint)

    fallback_provider = (settings.FALLBACK_LLM_PROVIDER or "").lower()
    fallback_key = settings.FALLBACK_LLM_API_KEY
    if fallback_key and fallback_provider:
        claim(fallback_key, provider_endpoint(fallback_provider, settings))

    try:
        from docsgpt.core.model_registry import ModelRegistry

        catalog = list(ModelRegistry.get_instance().models.values())
    except Exception as exc:  # noqa: BLE001 - fewer claims only refuses more
        logger.warning("Could not read the model catalog to scope API keys: %s", exc)
        catalog = []
    for model in catalog:
        provider = getattr(getattr(model, "provider", None), "value", None)
        if model.api_key:
            claim(model.api_key, model.base_url)
        if model.base_url and not model.api_key and provider not in ("openai_compatible", "docsgpt"):
            claim(own_key(provider), model.base_url)
        if fallback_key and model.base_url and model.id == settings.FALLBACK_LLM_NAME:
            claim(fallback_key, model.base_url)
    return hosts


def check_credential_scope(api_key: Optional[str], base_url: Optional[str], provider: str) -> None:
    """Refuse to send a deployment credential to a host it was not configured for.

    Called by the LLM classes while they build their API client, before any
    request is made.

    Args:
        api_key: The key the client is about to authenticate with.
        base_url: The endpoint the client will call.
        provider: The LLM class's provider name, for the error message.

    Raises:
        CredentialScopeError: ``api_key`` is a key this deployment configured,
            and ``base_url`` is not one of the origins it was configured for,
            or is plain http to a host that is not local (see
            :func:`plaintext_allowed`).
    """
    if not api_key or not isinstance(api_key, str):
        return
    allowed = credential_hosts().get(api_key)
    if allowed is None:
        return
    origin = endpoint_origin(base_url)
    target = origin or str(base_url)
    if origin and origin in allowed:
        if plaintext_allowed(base_url):
            return
        logger.error(
            "Refused to send a %s request to %s: plain http to a host that is not local.",
            provider,
            target,
        )
        raise CredentialScopeError(
            f"Refusing to send a {provider} request to {target}: the endpoint uses plain http and its host "
            "is not a loopback, private or single-label internal host, so the API key would cross the "
            "network unencrypted. Use https, or set LLM_ALLOW_PLAINTEXT_ENDPOINTS=true if this host is "
            "on your own network."
        )
    owners = ", ".join(sorted(allowed)) or "no LLM endpoint"
    logger.error(
        "Refused to send a %s request to %s: its API key is configured for %s.",
        provider,
        target,
        owners,
    )
    raise CredentialScopeError(
        f"Refusing to send a {provider} request to {target}: the API key it would use is "
        f"configured for {owners}. Check LLM_PROVIDER, the provider API keys and the model's endpoint."
    )
