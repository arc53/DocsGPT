"""Every LLM request authenticates with a key that belongs to its endpoint.

Three layers keep a provider's key away from another provider's endpoint:

* ``LLMCreator`` lets a registered model decide its provider, key and
  endpoint together, and refuses (``ModelNotAvailableError``) a request that
  has no endpoint of its own instead of handing it to the OpenAI client's
  default endpoint.
* ``get_api_key_for_provider`` and the LLM classes only fall back to a
  provider's own key; ``API_KEY`` belongs to ``LLM_PROVIDER`` alone.
* The LLM classes check, while building their client, that a key the
  deployment configured goes only to a host it was configured for
  (``CredentialScopeError``).

The second half of the module walks the supported configurations end to end
(registry, provider and key resolution, client construction) and pins the key
and endpoint each one produces.
"""

from __future__ import annotations

import uuid
from textwrap import dedent
from typing import Optional

import pytest

from docsgpt.core.model_registry import ModelRegistry
from docsgpt.core.model_settings import AvailableModel, ModelCapabilities, ModelProvider
from docsgpt.core.model_utils import (
    get_api_key_for_provider,
    get_default_model_id,
    get_provider_from_model_id,
)
from docsgpt.core.model_yaml import BUILTIN_MODELS_DIR, load_model_yamls
from docsgpt.core.settings import settings
from docsgpt.llm.anthropic import AnthropicLLM
from docsgpt.llm.credential_scope import CredentialScopeError, credential_hosts, endpoint_origin
from docsgpt.llm.google_ai import GoogleLLM
from docsgpt.llm.groq import GroqLLM
from docsgpt.llm.llm_creator import LLMCreator, ModelNotAvailableError
from docsgpt.llm.novita import NovitaLLM
from docsgpt.llm.open_router import OpenRouterLLM
from docsgpt.llm.openai import NO_API_KEY, OpenAILLM

OPENAI_URL = "https://api.openai.com/v1"
DEEPSEEK_URL = "https://api.deepseek.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com"

_LLM_SETTINGS = (
    "LLM_PROVIDER",
    "LLM_NAME",
    "API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "OPEN_ROUTER_API_KEY",
    "NOVITA_API_KEY",
    "OPENAI_BASE_URL",
    "MODELS_CONFIG_DIR",
    "FALLBACK_LLM_PROVIDER",
    "FALLBACK_LLM_NAME",
    "FALLBACK_LLM_API_KEY",
)


@pytest.fixture(autouse=True)
def _deployment(monkeypatch):
    """No provider configured, no catalog key in the environment, an unloaded registry."""
    for name in _LLM_SETTINGS:
        monkeypatch.setattr(settings, name, None)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    for catalog in load_model_yamls([BUILTIN_MODELS_DIR]):
        if catalog.api_key_env:
            monkeypatch.delenv(catalog.api_key_env, raising=False)
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


def configure(monkeypatch, **values: str) -> None:
    """Set ``values`` as the deployment's settings; ``*_API_KEY`` names outside settings go to the env."""
    for name, value in values.items():
        if name in _LLM_SETTINGS:
            monkeypatch.setattr(settings, name, value)
        else:
            monkeypatch.setenv(name, value)
    ModelRegistry.reset()


def chat(model_id: Optional[str] = None, decoded_token: Optional[dict] = None):
    """Build the LLM a chat request builds: model, its provider, that provider's key."""
    model_id = model_id or get_default_model_id()
    user_id = (decoded_token or {}).get("sub")
    provider = (get_provider_from_model_id(model_id, user_id=user_id) if model_id else None) or settings.LLM_PROVIDER
    return LLMCreator.create_llm(
        provider,
        api_key=get_api_key_for_provider(provider),
        user_api_key=None,
        decoded_token=decoded_token,
        model_id=model_id,
    )


def target(llm) -> tuple:
    """``(key, endpoint)`` the LLM authenticates with."""
    if isinstance(llm, AnthropicLLM):
        return llm.api_key, str(llm.anthropic.base_url).rstrip("/")
    if isinstance(llm, GoogleLLM):
        return llm.api_key, "google"
    return llm.api_key, llm._effective_base_url


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnresolvableModels:
    def test_an_unregistered_openai_compatible_model_is_refused(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai_compatible", API_KEY="sk-ds", DEEPSEEK_API_KEY="sk-ds")
        with pytest.raises(ModelNotAvailableError, match="'not-a-model' is not available"):
            LLMCreator.create_llm("openai_compatible", "sk-ds", None, None, model_id="not-a-model")

    def test_openai_compatible_without_a_model_is_refused(self, monkeypatch):
        # The benchmark failure: an empty registry gave no default model, so
        # the request went out as LLM_PROVIDER with no model at all.
        configure(monkeypatch, LLM_PROVIDER="openai_compatible", API_KEY="sk-ds", DEEPSEEK_API_KEY="sk-ds")
        with pytest.raises(ModelNotAvailableError, match="needs a model id"):
            LLMCreator.create_llm("openai_compatible", "sk-ds", None, None, model_id=None)

    def test_a_custom_model_id_that_does_not_resolve_is_refused(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        missing = str(uuid.uuid4())
        with pytest.raises(ModelNotAvailableError, match=missing):
            LLMCreator.create_llm("openai", "sk-openai", None, None, model_id=missing)

    def test_model_not_available_is_a_value_error(self):
        # Existing handlers catch ValueError around create_llm.
        assert issubclass(ModelNotAvailableError, ValueError)

    def test_an_unregistered_name_for_a_provider_with_its_own_endpoint_still_goes_there(self, monkeypatch):
        # FALLBACK_LLM_NAME is documented to accept any name the provider serves.
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai", ANTHROPIC_API_KEY="sk-ant")
        llm = LLMCreator.create_llm("anthropic", "sk-ant", None, None, model_id="claude-from-the-future")
        assert isinstance(llm, AnthropicLLM)
        assert target(llm) == ("sk-ant", ANTHROPIC_URL)
        assert llm.model_id == "claude-from-the-future"


@pytest.mark.unit
class TestTheModelDecidesItsProvider:
    def test_a_stale_provider_name_does_not_pair_its_key_with_another_providers_model(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai", DEEPSEEK_API_KEY="sk-ds")
        llm = LLMCreator.create_llm("openai", "sk-openai", None, None, model_id="deepseek-v4-flash")
        assert target(llm) == ("sk-ds", DEEPSEEK_URL)
        assert llm._provider_plugin == "openai_compatible"

    def test_a_first_party_model_named_under_another_provider_uses_its_own_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai", ANTHROPIC_API_KEY="sk-ant")
        llm = LLMCreator.create_llm("openai", "sk-openai", None, None, model_id="claude-opus-4-7")
        assert isinstance(llm, AnthropicLLM)
        assert target(llm) == ("sk-ant", ANTHROPIC_URL)


@pytest.mark.unit
class TestOwnKeysOnly:
    def test_openai_compatible_has_no_deployment_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai_compatible", API_KEY="sk-ds")
        assert get_api_key_for_provider("openai_compatible") is None

    def test_api_key_belongs_to_llm_provider_only(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        assert get_api_key_for_provider("openai") == "sk-openai"
        assert get_api_key_for_provider("anthropic") is None
        assert get_api_key_for_provider("groq") is None

    def test_unknown_provider_names_get_no_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        assert get_api_key_for_provider("azure_foundry") is None
        assert get_api_key_for_provider(None) is None

    def test_provider_names_match_case_insensitively(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        assert get_api_key_for_provider("OpenAI") == "sk-openai"

    def test_llm_classes_do_not_borrow_another_providers_api_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        assert GroqLLM(api_key=None).api_key == NO_API_KEY
        assert OpenRouterLLM(api_key=None).api_key == NO_API_KEY
        assert NovitaLLM(api_key=None).api_key == NO_API_KEY
        assert AnthropicLLM(api_key=None).api_key is None
        # The Gemini client refuses to start without a key rather than
        # being handed the OpenAI one.
        with pytest.raises(ValueError, match="No API key"):
            GoogleLLM(api_key=None)

    def test_an_explicit_endpoint_does_not_get_the_openai_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        llm = OpenAILLM(api_key=None, base_url="https://llm.internal.example/v1")
        assert target(llm) == (NO_API_KEY, "https://llm.internal.example/v1")

    def test_the_openai_endpoint_still_falls_back_to_the_openai_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        assert target(OpenAILLM(api_key=None)) == ("sk-openai", OPENAI_URL)

    def test_global_fallback_uses_the_fallback_providers_own_key(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            API_KEY="sk-openai",
            ANTHROPIC_API_KEY="sk-ant",
            FALLBACK_LLM_PROVIDER="anthropic",
            FALLBACK_LLM_NAME="claude-sonnet-4-6",
        )
        primary = chat()
        fallback = primary.fallback_llm
        assert isinstance(fallback, AnthropicLLM)
        assert target(fallback) == ("sk-ant", ANTHROPIC_URL)


@pytest.mark.unit
class TestClientGuard:
    def test_a_catalog_key_cannot_go_to_the_openai_default_endpoint(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai_compatible", DEEPSEEK_API_KEY="sk-ds")
        with pytest.raises(
            CredentialScopeError,
            match=r"request to https://api\.openai\.com:443: .* configured for https://api\.deepseek\.com:443\.",
        ) as excinfo:
            OpenAILLM(api_key="sk-ds")
        # The message names hosts, never the key.
        assert "sk-ds" not in str(excinfo.value)

    def test_the_benchmark_pairing_is_refused_before_any_request(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="openai_compatible",
            LLM_NAME="deepseek-v4-flash",
            API_KEY="sk-ds",
            DEEPSEEK_API_KEY="sk-ds",
        )
        with pytest.raises(CredentialScopeError):
            OpenAILLM(api_key="sk-ds", base_url=None)

    def test_an_openai_key_cannot_go_to_groq(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        with pytest.raises(CredentialScopeError, match="api.groq.com"):
            GroqLLM(api_key="sk-openai")

    def test_an_openai_key_cannot_go_to_anthropic(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        with pytest.raises(CredentialScopeError, match="api.anthropic.com"):
            AnthropicLLM(api_key="sk-openai")

    def test_an_anthropic_key_cannot_go_to_google(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant")
        with pytest.raises(CredentialScopeError, match="generativelanguage.googleapis.com"):
            GoogleLLM(api_key="sk-ant")

    def test_an_unclaimed_api_key_goes_nowhere(self, monkeypatch):
        # LLM_PROVIDER=docsgpt sends the public key; API_KEY belongs to no endpoint.
        configure(monkeypatch, LLM_PROVIDER="docsgpt", API_KEY="sk-stray")
        with pytest.raises(CredentialScopeError, match="no LLM endpoint"):
            OpenAILLM(api_key="sk-stray")

    def test_a_key_the_deployment_did_not_configure_is_not_checked(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        llm = OpenAILLM(api_key="sk-users-own", base_url="https://api.example.com/v1")
        assert target(llm) == ("sk-users-own", "https://api.example.com/v1")

    def test_the_fallback_key_may_go_to_the_fallback_provider(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            API_KEY="sk-openai",
            FALLBACK_LLM_PROVIDER="anthropic",
            FALLBACK_LLM_API_KEY="sk-fallback",
        )
        assert target(AnthropicLLM(api_key="sk-fallback")) == ("sk-fallback", ANTHROPIC_URL)
        with pytest.raises(CredentialScopeError):
            OpenAILLM(api_key="sk-fallback")

    def test_a_shared_key_may_go_to_every_endpoint_it_was_configured_for(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-same", OPENAI_API_KEY="sk-same")
        assert credential_hosts()["sk-same"] == {"https://api.openai.com:443"}

    def test_a_fallback_key_may_go_to_its_catalog_models_endpoint(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            API_KEY="sk-openai",
            DEEPSEEK_API_KEY="sk-ds",
            FALLBACK_LLM_PROVIDER="openai_compatible",
            FALLBACK_LLM_NAME="deepseek-v4-flash",
            FALLBACK_LLM_API_KEY="sk-fallback",
        )
        assert credential_hosts()["sk-fallback"] == {"https://api.deepseek.com:443"}

    def test_an_unreadable_catalog_only_narrows_where_keys_may_go(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai", DEEPSEEK_API_KEY="sk-ds")

        def broken():
            raise ValueError("bad yaml")

        monkeypatch.setattr(ModelRegistry, "get_instance", staticmethod(broken))
        hosts = credential_hosts()
        assert hosts["sk-openai"] == {"https://api.openai.com:443"}
        # The catalog key is unknown without the catalog, so it is not checked.
        assert "sk-ds" not in hosts

    def test_endpoint_origin_normalises_scheme_ports_and_case(self):
        assert endpoint_origin("https://API.DeepSeek.com/v1") == "https://api.deepseek.com:443"
        assert endpoint_origin("HTTP://localhost:11434/v1") == "http://localhost:11434"
        assert endpoint_origin("http://ollama/v1") == "http://ollama:80"
        assert endpoint_origin("https://example.com:notaport/v1") == "https://example.com:443"
        assert endpoint_origin("ftp://example.com/") == ""
        assert endpoint_origin(None) == ""
        assert endpoint_origin("not a url") == ""


@pytest.mark.unit
class TestPlaintextEndpoints:
    """A configured key never crosses the public internet unencrypted.

    The scheme is part of the scope: a key configured for an https endpoint
    is not sent to the same host over http. Plain http is accepted for an
    endpoint the operator configured only when its host is local: loopback,
    a private or link-local address, a single-label name (a Docker service),
    ``host.docker.internal`` or an internal suffix. Anything else needs
    https, or ``LLM_ALLOW_PLAINTEXT_ENDPOINTS``.
    """

    def test_an_https_key_is_not_sent_to_the_same_host_over_http(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        with pytest.raises(CredentialScopeError, match=r"request to http://api\.openai\.com:443"):
            OpenAILLM(api_key="sk-openai", base_url="http://api.openai.com:443/v1")

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://localhost:11434/v1",
            "http://127.0.0.1:8000/v1",
            "http://[::1]:8000/v1",
            "http://10.0.0.5:8000/v1",
            "http://172.20.0.3:4000",
            "http://192.168.1.20:11434/v1",
            "http://169.254.10.10/v1",
            "http://[fd12:3456::1]:8000/v1",
            "http://ollama:11434/v1",
            "http://litellm:4000",
            "http://host.docker.internal:23333/v1",
            "http://ollama.llm.svc.cluster.local:11434/v1",
            "http://vllm.corp.internal/v1",
        ],
    )
    def test_plain_http_to_a_local_endpoint_is_allowed(self, monkeypatch, base_url):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-local", OPENAI_BASE_URL=base_url, LLM_NAME="m")
        assert target(chat()) == ("sk-local", base_url)

    @pytest.mark.parametrize(
        "base_url",
        ["http://llm.example.com/v1", "http://8.8.8.8:8000/v1", "http://api.deepseek.com/v1"],
    )
    def test_plain_http_to_a_public_endpoint_is_refused(self, monkeypatch, base_url):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-remote", OPENAI_BASE_URL=base_url, LLM_NAME="m")
        with pytest.raises(CredentialScopeError, match="plain http") as excinfo:
            chat()
        assert endpoint_origin(base_url) in str(excinfo.value)
        assert "LLM_ALLOW_PLAINTEXT_ENDPOINTS" in str(excinfo.value)
        assert "sk-remote" not in str(excinfo.value)

    def test_the_escape_hatch_allows_plain_http_to_a_configured_public_endpoint(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            API_KEY="sk-remote",
            OPENAI_BASE_URL="http://llm.example.com/v1",
            LLM_NAME="m",
        )
        monkeypatch.setattr(settings, "LLM_ALLOW_PLAINTEXT_ENDPOINTS", True)
        assert target(chat()) == ("sk-remote", "http://llm.example.com/v1")

    def test_the_escape_hatch_does_not_widen_where_a_key_may_go(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        monkeypatch.setattr(settings, "LLM_ALLOW_PLAINTEXT_ENDPOINTS", True)
        with pytest.raises(CredentialScopeError, match="is configured for https://api"):
            OpenAILLM(api_key="sk-openai", base_url="http://api.openai.com/v1")

    def test_a_plaintext_catalog_endpoint_is_refused_for_a_public_host(self, monkeypatch, tmp_path):
        (tmp_path / "plain.yaml").write_text(
            dedent(
                """
                provider: openai_compatible
                api_key_env: PLAIN_API_KEY
                base_url: http://llm.example.com/v1
                models:
                  - id: plain-model
                """
            )
        )
        configure(monkeypatch, LLM_PROVIDER="openai", MODELS_CONFIG_DIR=str(tmp_path), PLAIN_API_KEY="sk-plain")
        with pytest.raises(CredentialScopeError, match="plain http"):
            chat("plain-model")

    def test_https_endpoints_are_unchanged(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai", DEEPSEEK_API_KEY="sk-ds")
        assert target(chat()) == ("sk-openai", OPENAI_URL)
        assert target(chat("deepseek-v4-flash")) == ("sk-ds", DEEPSEEK_URL)

    def test_a_key_the_deployment_did_not_configure_is_not_held_to_the_policy(self, monkeypatch):
        # A user's own model is validated and pinned where it is saved.
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        llm = OpenAILLM(api_key="sk-users-own", base_url="http://llm.example.com/v1")
        assert target(llm) == ("sk-users-own", "http://llm.example.com/v1")


@pytest.mark.unit
class TestSdkEnvironmentEndpoints:
    """An SDK's own base-URL environment variable must not redirect a configured key.

    The google-genai, anthropic and openai SDKs each read an endpoint from the
    environment when the caller passes none. The guard checks the endpoint
    the LLM class passes, so the client must use exactly that endpoint.
    """

    def test_gemini_ignores_google_gemini_base_url(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="google", GOOGLE_API_KEY="g-key")
        monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", "https://collector.example.com/")
        llm = GoogleLLM(api_key=None)
        assert endpoint_origin(llm.client._api_client._http_options.base_url) == "https://generativelanguage.googleapis.com:443"

    def test_gemini_ignores_the_vertex_ai_switch(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="google", GOOGLE_API_KEY="g-key")
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
        monkeypatch.setenv("GOOGLE_VERTEX_BASE_URL", "https://collector.example.com/")
        llm = GoogleLLM(api_key=None)
        assert not llm.client._api_client.vertexai
        assert endpoint_origin(llm.client._api_client._http_options.base_url) == "https://generativelanguage.googleapis.com:443"

    def test_anthropic_ignores_anthropic_base_url(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://collector.example.com")
        llm = AnthropicLLM(api_key=None)
        assert target(llm) == ("sk-ant", ANTHROPIC_URL)
        assert "https://collector.example.com:443" not in credential_hosts()["sk-ant"]

    def test_anthropic_still_takes_a_models_own_endpoint(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant")
        llm = AnthropicLLM(api_key="sk-users-own", base_url="https://proxy.example.com/anthropic")
        assert target(llm) == ("sk-users-own", "https://proxy.example.com/anthropic")

    def test_openai_ignores_an_openai_base_url_the_settings_did_not_load(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://collector.example.com/v1")
        llm = OpenAILLM(api_key=None)
        assert target(llm) == ("sk-openai", OPENAI_URL)
        assert endpoint_origin(str(llm.client.base_url)) == "https://api.openai.com:443"


# ---------------------------------------------------------------------------
# Supported configurations, end to end
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSupportedConfigurations:
    def test_openai_with_the_generic_api_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        llm = chat()
        assert isinstance(llm, OpenAILLM)
        assert target(llm) == ("sk-openai", OPENAI_URL)

    def test_openai_with_only_the_provider_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai")
        assert target(chat()) == ("sk-openai", OPENAI_URL)

    def test_anthropic_with_the_generic_api_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="anthropic", API_KEY="sk-ant")
        llm = chat()
        assert isinstance(llm, AnthropicLLM)
        assert target(llm) == ("sk-ant", ANTHROPIC_URL)

    def test_google_with_its_provider_key(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="google", GOOGLE_API_KEY="g-key")
        llm = chat()
        assert isinstance(llm, GoogleLLM)
        assert llm.api_key == "g-key"

    @pytest.mark.parametrize(
        ("provider", "cls", "url"),
        [
            ("groq", GroqLLM, "https://api.groq.com/openai/v1"),
            ("openrouter", OpenRouterLLM, "https://openrouter.ai/api/v1"),
            ("novita", NovitaLLM, "https://api.novita.ai/openai"),
        ],
    )
    def test_openai_wire_providers_with_the_generic_api_key(self, monkeypatch, provider, cls, url):
        configure(monkeypatch, LLM_PROVIDER=provider, API_KEY="k-generic")
        llm = chat()
        assert isinstance(llm, cls)
        assert target(llm) == ("k-generic", url)

    def test_several_provider_keys_each_go_to_their_own_provider(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai", ANTHROPIC_API_KEY="sk-ant")
        assert target(chat("gpt-5.5")) == ("sk-openai", OPENAI_URL)
        assert target(chat("claude-opus-4-7")) == ("sk-ant", ANTHROPIC_URL)

    @pytest.mark.parametrize("api_key", ["None", "xxxx", "sk-local"])
    def test_own_openai_compatible_server(self, monkeypatch, api_key):
        # What setup.sh writes for Ollama and the local inference engines.
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            API_KEY=api_key,
            OPENAI_BASE_URL="http://localhost:11434/v1",
            LLM_NAME="llama3",
        )
        assert target(chat()) == (api_key, "http://localhost:11434/v1")

    def test_own_keyless_openai_compatible_server(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_BASE_URL="http://localhost:11434/v1", LLM_NAME="llama3")
        assert target(chat()) == (NO_API_KEY, "http://localhost:11434/v1")

    def test_own_server_with_an_openai_key_set(self, monkeypatch):
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            OPENAI_API_KEY="sk-vllm",
            OPENAI_BASE_URL="https://vllm.internal.example/v1",
            LLM_NAME="qwen3",
        )
        assert target(chat()) == ("sk-vllm", "https://vllm.internal.example/v1")

    def test_openai_compatible_catalog_as_the_provider(self, monkeypatch):
        # The benchmark configuration, now resolved by a loaded registry.
        configure(
            monkeypatch,
            LLM_PROVIDER="openai_compatible",
            LLM_NAME="deepseek-v4-flash",
            API_KEY="sk-ds",
            DEEPSEEK_API_KEY="sk-ds",
        )
        assert target(chat()) == ("sk-ds", DEEPSEEK_URL)

    def test_openai_compatible_catalog_next_to_openai(self, monkeypatch):
        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai", DEEPSEEK_API_KEY="sk-ds")
        assert target(chat()) == ("sk-openai", OPENAI_URL)
        assert target(chat("deepseek-v4-flash")) == ("sk-ds", DEEPSEEK_URL)

    def test_azure_foundry_catalog_from_models_config_dir(self, monkeypatch, tmp_path):
        (tmp_path / "azure_foundry.yaml").write_text(
            dedent(
                """
                provider: openai_compatible
                display_provider: azure_foundry
                api_key_env: AZURE_FOUNDRY_API_KEY
                base_url: https://my-resource.services.ai.azure.com/openai/v1
                models:
                  - id: gpt-5.6-foundry
                    display_name: GPT 5.6 (Foundry)
                    upstream_model_id: gpt-5.6
                """
            )
        )
        configure(
            monkeypatch,
            LLM_PROVIDER="openai",
            API_KEY="sk-openai",
            MODELS_CONFIG_DIR=str(tmp_path),
            AZURE_FOUNDRY_API_KEY="az-key",
        )
        llm = chat("gpt-5.6-foundry")
        assert target(llm) == ("az-key", "https://my-resource.services.ai.azure.com/openai/v1")
        assert llm.model_id == "gpt-5.6"
        # The display label a client stored still dispatches correctly.
        stored = LLMCreator.create_llm("openai", "sk-openai", None, None, model_id="gpt-5.6-foundry")
        assert target(stored) == ("az-key", "https://my-resource.services.ai.azure.com/openai/v1")

    def test_foundry_claude_with_a_per_model_endpoint(self, monkeypatch, tmp_path):
        (tmp_path / "foundry_claude.yaml").write_text(
            dedent(
                """
                provider: anthropic
                models:
                  - id: claude-foundry
                    display_name: Claude (Foundry)
                    base_url: https://my-resource.services.ai.azure.com/anthropic
                    upstream_model_id: claude-sonnet-4-6
                """
            )
        )
        configure(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant", MODELS_CONFIG_DIR=str(tmp_path))
        llm = chat("claude-foundry")
        assert isinstance(llm, AnthropicLLM)
        assert target(llm) == ("sk-ant", "https://my-resource.services.ai.azure.com/anthropic")

    def test_a_users_custom_model_uses_its_own_key_and_endpoint(self, monkeypatch):
        import docsgpt.security.safe_url as safe_url

        configure(monkeypatch, LLM_PROVIDER="openai", API_KEY="sk-openai")
        custom_id = str(uuid.uuid4())
        custom = AvailableModel(
            id=custom_id,
            provider=ModelProvider.OPENAI_COMPATIBLE,
            display_name="Mine",
            capabilities=ModelCapabilities(supports_tools=True),
            base_url="https://api.example.com/v1",
            upstream_model_id="my-model",
            source="user",
            api_key="sk-users-own",
        )
        monkeypatch.setattr(
            ModelRegistry,
            "_user_models_for",
            lambda self, user_id: {custom_id: custom} if user_id == "alice" else {},
        )
        monkeypatch.setattr(safe_url, "validate_user_base_url", lambda url: None)
        monkeypatch.setattr(safe_url, "pinned_httpx_client", lambda url: None)

        llm = chat(custom_id, decoded_token={"sub": "alice"})
        assert target(llm) == ("sk-users-own", "https://api.example.com/v1")
        assert llm.model_id == "my-model"
        # Another user cannot reach it, and the id does not fall through to OpenAI.
        with pytest.raises(ModelNotAvailableError):
            chat(custom_id, decoded_token={"sub": "mallory"})

    def test_the_v1_path_dispatches_the_agents_model_with_its_own_key(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        configure(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="sk-openai", DEEPSEEK_API_KEY="sk-ds")
        sp = StreamProcessor(request_data={}, decoded_token={"sub": "owner"}, trace_source="v1", external_caller=True)
        sp._prompt_content = "prompt"
        sp._get_prompt_content = MagicMock(return_value="prompt")
        sp.agent_config = {
            "agent_type": "classic",
            "prompt_id": "default",
            "user_api_key": "agent-key",
            "models": [],
            "external_api_caller": True,
        }
        sp.model_id = "deepseek-v4-flash"
        sp.model_user_id = "owner"
        sp.prompt_renderer = MagicMock()
        sp.prompt_renderer.render_prompt.return_value = "rendered"
        sp.data = {}
        sp.history = []
        sp.retrieved_docs = []
        sp.attachments = []
        sp.source = {}
        sp.retriever_config = {}
        sp.conversation_id = None
        monkeypatch.setattr(ModelRegistry, "_user_models_for", lambda self, user_id: {})

        captured = {}

        def capture(*args, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("docsgpt.agents.agent_creator.AgentCreator.create_agent", side_effect=capture):
            sp.create_agent()

        assert captured["is_v1"] is True
        assert target(captured["llm"]) == ("sk-ds", DEEPSEEK_URL)
        # Sub-LLMs the agent builds (rephrase, guardrails) get no OpenAI key to misroute.
        assert captured["api_key"] is None
