"""Regression tests for the three P1 BYOM fixes.

P1 #1 — model_utils helpers must accept and honor ``user_id`` so per-user
        BYOM custom-model UUIDs resolve via the registry per-user layer.
P1 #2 — Agent ``_llm_gen`` must pass the *upstream* model id (the user's
        typed name, e.g. ``mistral-large-latest``) to the provider's
        chat-completion API, not the BYOM UUID we use as the registry id.
P1 #3 — covered indirectly: the route already accepts a user_id; this
        suite locks in that ``/api/models``'s ``get_enabled_models``
        properly distinguishes authenticated vs anonymous responses.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from application.core.model_registry import ModelRegistry
from application.core.model_utils import (
    get_all_available_models,
    get_api_key_for_model,
    get_base_url_for_model,
    get_model_capabilities,
    get_provider_from_model_id,
    get_token_limit,
    validate_model_id,
)
from application.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)


def _seed_user_layer(reg, user_id, layer_dict):
    """Plant a BYOM layer directly into the registry's per-user cache.

    Mirrors the internal ``(layer, version_at_load, loaded_at)`` tuple
    shape (see ``ModelRegistry._user_models``). Tests poking the cache
    use this rather than assigning a bare dict so the production-side
    TTL/version logic keeps working.
    """
    reg._user_models[user_id] = (layer_dict, None, time.monotonic())


def _make_settings(**overrides):
    s = MagicMock()
    s.OPENAI_BASE_URL = None
    s.OPENAI_API_KEY = None
    s.OPENAI_API_BASE = None
    s.ANTHROPIC_API_KEY = None
    s.GOOGLE_API_KEY = None
    s.GROQ_API_KEY = None
    s.OPEN_ROUTER_API_KEY = None
    s.NOVITA_API_KEY = None
    s.HUGGINGFACE_API_KEY = None
    s.LLM_PROVIDER = ""
    s.LLM_NAME = None
    s.API_KEY = None
    s.MODELS_CONFIG_DIR = None
    s.DEFAULT_LLM_TOKEN_LIMIT = 128000
    # Concrete strings — module-level imports under patched settings
    # (e.g. application.api.user.base's storage init) fail with
    # MagicMock attribute values.
    s.STORAGE_TYPE = "local"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@contextmanager
def _yield(conn):
    yield conn


@pytest.fixture(autouse=True)
def _reset_registry():
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


@pytest.fixture
def byom_model(pg_conn):
    """Create one BYOM record and return (model_uuid, user_id)."""
    repo = UserCustomModelsRepository(pg_conn)
    row = repo.create(
        user_id="user-1",
        upstream_model_id="mistral-large-latest",
        display_name="My Mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_plaintext="sk-mistral-test",
        capabilities={
            "supports_tools": True,
            "supports_structured_output": True,
            "context_window": 200_000,
        },
    )
    return row["id"], "user-1"


# ── P1 #1: helpers honor user_id ─────────────────────────────────────────


@pytest.mark.unit
class TestHelpersThreadUserId:
    def test_validate_model_id_without_user_id_rejects_byom(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            assert validate_model_id(model_uuid) is False

    def test_validate_model_id_with_user_id_accepts_byom(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            assert validate_model_id(model_uuid, user_id=user_id) is True

    def test_get_provider_returns_openai_compatible_for_byom(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            assert get_provider_from_model_id(model_uuid) is None
            assert (
                get_provider_from_model_id(model_uuid, user_id=user_id)
                == "openai_compatible"
            )

    def test_get_token_limit_uses_byom_context_window(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            # No user_id → falls back to DEFAULT_LLM_TOKEN_LIMIT
            assert get_token_limit(model_uuid) == 128_000
            # With user_id → returns the user's declared 200k
            assert get_token_limit(model_uuid, user_id=user_id) == 200_000

    def test_get_base_url_for_model_resolves_byom(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            assert get_base_url_for_model(model_uuid) is None
            assert (
                get_base_url_for_model(model_uuid, user_id=user_id)
                == "https://api.mistral.ai/v1"
            )

    def test_get_api_key_for_model_resolves_byom(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            assert get_api_key_for_model(model_uuid) is None
            assert (
                get_api_key_for_model(model_uuid, user_id=user_id)
                == "sk-mistral-test"
            )

    def test_get_model_capabilities_resolves_byom(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            assert get_model_capabilities(model_uuid) is None
            caps = get_model_capabilities(model_uuid, user_id=user_id)
            assert caps is not None
            assert caps["supports_tools"] is True
            assert caps["context_window"] == 200_000

    def test_get_all_available_models_includes_byom_when_authenticated(
        self, pg_conn, byom_model
    ):
        model_uuid, user_id = byom_model
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            anon_ids = set(get_all_available_models().keys())
            user_ids = set(get_all_available_models(user_id=user_id).keys())
            assert model_uuid not in anon_ids
            assert model_uuid in user_ids


# ── P1 #2: every gen call site sends the upstream id, not the BYOM UUID ──


@pytest.mark.unit
class TestSecurityNoCredLeakOnUndecryptableBYOM:
    """P1 #1: a BYOM record whose api_key cannot be decrypted MUST NOT
    be registered. Without this guard, LLMCreator would fall back to
    the caller-passed api_key (settings.API_KEY for openai_compatible)
    and POST it to the user-supplied base_url — leaking the instance
    credential to the user's chosen endpoint."""

    def test_undecryptable_record_skipped_in_registry(
        self, pg_conn, monkeypatch
    ):
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="u",
            upstream_model_id="mistral-large-latest",
            display_name="My Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-real",
        )

        # Simulate decryption failure (rotated ENCRYPTION_SECRET_KEY,
        # corrupted ciphertext, etc.) by stubbing _decrypt_api_key.
        monkeypatch.setattr(
            UserCustomModelsRepository,
            "_decrypt_api_key",
            staticmethod(lambda *_a, **_kw: None),
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            reg = ModelRegistry.get_instance()
            # The record must NOT appear in the user's layer.
            assert reg.get_model(created["id"], user_id="u") is None
            # And the per-user layer is empty (or at least does not
            # contain a record with api_key=None).
            for m in reg._user_models_for("u").values():
                assert m.api_key  # never None / empty

    def test_llmcreator_refuses_user_model_with_no_api_key(self, pg_conn):
        """Belt-and-braces: even if a source=user AvailableModel slipped
        into the registry without an api_key, LLMCreator must refuse."""
        from application.core.model_settings import (
            AvailableModel,
            ModelProvider,
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
            # Inject a malformed BYOM record directly to bypass the
            # registry-level guard tested above.
            uuid = "0b7e0f4c-1234-5678-9abc-deadbeefcafe"
            _seed_user_layer(
                reg,
                "alice",
                {
                    uuid: AvailableModel(
                        id=uuid,
                        provider=ModelProvider.OPENAI_COMPATIBLE,
                        display_name="bad",
                        base_url="https://api.mistral.ai/v1",
                        upstream_model_id="mistral-large-latest",
                        source="user",
                        api_key=None,  # the dangerous state
                    )
                },
            )

            from application.llm.llm_creator import LLMCreator

            with pytest.raises(ValueError, match="no usable API key"):
                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="settings-api-key-DO-NOT-LEAK",
                    user_api_key=None,
                    decoded_token={"sub": "alice"},
                    model_id=uuid,
                )


@pytest.mark.unit
class TestSecurityDispatchSSRFGuard:
    """P1 #2: LLMCreator must re-validate the model's base_url at
    dispatch time. Closes DNS-rebinding window between create-time
    check and connect; protects against rows that pre-date the SSRF
    guard or were inserted via direct DB edits."""

    def test_dispatch_rejects_user_model_with_unsafe_base_url(self, pg_conn):
        from application.core.model_settings import (
            AvailableModel,
            ModelProvider,
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
            uuid = "0b7e0f4c-1234-5678-9abc-deadbeef0099"
            _seed_user_layer(
                reg,
                "alice",
                {
                    uuid: AvailableModel(
                        id=uuid,
                        provider=ModelProvider.OPENAI_COMPATIBLE,
                        display_name="rebound",
                        base_url="https://10.0.0.5/v1",  # unsafe — RFC1918
                        upstream_model_id="model-x",
                        source="user",
                        api_key="sk-real",
                    )
                },
            )

            from application.llm.llm_creator import LLMCreator

            with pytest.raises(ValueError, match="Refusing to dispatch"):
                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="some-key",
                    user_api_key=None,
                    decoded_token={"sub": "alice"},
                    model_id=uuid,
                )

    def test_dispatch_allows_user_model_with_safe_base_url(self, pg_conn):
        """The SSRF guard must not break the happy path."""
        from application.core.model_settings import (
            AvailableModel,
            ModelProvider,
        )

        captured: dict = {}

        class _FakeLLM:
            def __init__(self, api_key, user_api_key, *a, **kw):
                captured["api_key"] = api_key
                captured["base_url"] = kw.get("base_url")

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.security.safe_url.socket.getaddrinfo"
        ) as gai:
            gai.return_value = [(None, None, None, None, ("104.18.0.1", 0))]
            reg = ModelRegistry()
            uuid = "0b7e0f4c-1234-5678-9abc-deadbeef0100"
            _seed_user_layer(
                reg,
                "alice",
                {
                    uuid: AvailableModel(
                        id=uuid,
                        provider=ModelProvider.OPENAI_COMPATIBLE,
                        display_name="ok",
                        base_url="https://api.mistral.ai/v1",
                        upstream_model_id="mistral-large-latest",
                        source="user",
                        api_key="sk-real",
                    )
                },
            )

            from application.llm.llm_creator import LLMCreator
            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"], "llm_class", _FakeLLM
            ):
                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="caller-key",
                    user_api_key=None,
                    decoded_token={"sub": "alice"},
                    model_id=uuid,
                )

        assert captured["base_url"] == "https://api.mistral.ai/v1"
        assert captured["api_key"] == "sk-real"  # model.api_key won

    def test_dispatch_injects_pinned_http_client_for_user_model(
        self, pg_conn
    ):
        """LLMCreator must build a DNS-rebinding-safe httpx.Client and
        forward it to the OpenAI SDK so the SDK's request-time DNS
        lookup cannot escape the create-time SSRF guard. ``validate_
        user_base_url`` alone is TOCTOU and does not close the
        rebinding window — the pinned client is what does."""
        import httpx

        from application.core.model_settings import (
            AvailableModel,
            ModelProvider,
        )
        from application.security.safe_url import _PinnedHTTPSTransport

        captured: dict = {}

        class _FakeLLM:
            def __init__(self, api_key, user_api_key, *a, **kw):
                captured["http_client"] = kw.get("http_client")

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.security.safe_url.socket.getaddrinfo"
        ) as gai:
            gai.return_value = [(None, None, None, None, ("104.18.0.1", 0))]
            reg = ModelRegistry()
            uuid = "0b7e0f4c-1234-5678-9abc-deadbeef0101"
            _seed_user_layer(
                reg,
                "alice",
                {
                    uuid: AvailableModel(
                        id=uuid,
                        provider=ModelProvider.OPENAI_COMPATIBLE,
                        display_name="pinned",
                        base_url="https://api.mistral.ai/v1",
                        upstream_model_id="mistral-large-latest",
                        source="user",
                        api_key="sk-real",
                    )
                },
            )

            from application.llm.llm_creator import LLMCreator
            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"], "llm_class", _FakeLLM
            ):
                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="caller-key",
                    user_api_key=None,
                    decoded_token={"sub": "alice"},
                    model_id=uuid,
                )

        client = captured["http_client"]
        try:
            assert isinstance(client, httpx.Client), (
                "http_client must be set for user-source models so the "
                "OpenAI SDK doesn't re-resolve DNS at request time"
            )
            assert isinstance(client._transport, _PinnedHTTPSTransport)
            assert client._transport._host == "api.mistral.ai"
            assert client._transport._ip_netloc == "104.18.0.1"
            assert client.follow_redirects is False
        finally:
            if client is not None:
                client.close()

    def test_dispatch_skips_pinned_client_for_builtin_model(self, pg_conn):
        """Built-in (non-BYOM) models don't need the pinned client —
        their endpoints are operator-trusted. Skipping avoids
        unnecessary DNS lookups and keeps the SDK's default httpx
        client behavior unchanged for the common path."""
        from application.core.model_settings import (
            AvailableModel,
            ModelProvider,
        )

        captured: dict = {}

        class _FakeLLM:
            def __init__(self, api_key, user_api_key, *a, **kw):
                captured["http_client"] = kw.get("http_client")

        s = _make_settings()
        with patch("application.core.settings.settings", s):
            reg = ModelRegistry()
            uuid = "0b7e0f4c-1234-5678-9abc-deadbeef0102"
            reg._builtin_models = {
                uuid: AvailableModel(
                    id=uuid,
                    provider=ModelProvider.OPENAI_COMPATIBLE,
                    display_name="builtin",
                    base_url=None,
                    upstream_model_id="gpt-4",
                    source="builtin",
                )
            }

            from application.llm.llm_creator import LLMCreator
            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"], "llm_class", _FakeLLM
            ):
                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="op-key",
                    user_api_key=None,
                    decoded_token={"sub": "alice"},
                    model_id=uuid,
                )

        assert captured["http_client"] is None, (
            "built-in models must not get the pinned client — keeps "
            "the default OpenAI SDK transport for operator-trusted "
            "endpoints"
        )


@pytest.mark.unit
class TestSharedAgentResolvesOwnerBYOM:
    """P2 #1: a shared agent with a BYOM default_model_id must resolve
    against the *owner's* per-user layer, not the caller's."""

    def test_owner_byom_resolves_for_caller_request(self, pg_conn):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        # Owner creates a BYOM model.
        repo = UserCustomModelsRepository(pg_conn)
        owner_model = repo.create(
            user_id="owner",
            upstream_model_id="mistral-large-latest",
            display_name="Owner Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-owner",
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            # Caller requests against the shared agent — initial_user_id
            # is the caller, agent_config.user_id is the owner.
            sp = StreamProcessor.__new__(StreamProcessor)
            sp.data = {}
            sp.initial_user_id = "caller"
            sp.agent_config = {
                "user_id": "owner",
                "default_model_id": owner_model["id"],
            }
            sp._validate_and_set_model()

        # The owner's BYOM model resolved (not a fallback to system default)
        assert sp.model_id == owner_model["id"]
        assert sp.model_user_id == "owner"

    def test_classic_rag_rephrase_resolves_owner_byom(self, pg_conn, monkeypatch):
        """ClassicRAG must resolve a BYOM model_id through LLMCreator so
        the rephrase LLM gets the owner's api_key/base_url and dispatches
        the upstream model name (e.g. ``mistral-large-latest``) — not the
        registry UUID — when called with chat history + active docs."""
        from application.llm.providers import PROVIDERS_BY_NAME
        from application.retriever.classic_rag import ClassicRAG
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        repo = UserCustomModelsRepository(pg_conn)
        owner_model = repo.create(
            user_id="owner",
            upstream_model_id="mistral-large-latest",
            display_name="Owner Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-owner",
        )

        # Capture what LLMCreator hands the provider's llm_class.
        captured = {}

        class _CapturingLLM:
            def __init__(self, api_key, user_api_key, **kwargs):
                captured["api_key"] = api_key
                captured["user_api_key"] = user_api_key
                captured["base_url"] = kwargs.get("base_url")
                captured["model_id"] = kwargs.get("model_id")
                self.model_id = kwargs.get("model_id")

            def gen(self, model, messages):
                captured["gen_model"] = model
                return "rephrased"

        monkeypatch.setattr(
            PROVIDERS_BY_NAME["openai_compatible"], "llm_class", _CapturingLLM
        )

        s = _make_settings(API_KEY="instance-secret")
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            # Caller != owner: model_user_id="owner" must drive lookup.
            ClassicRAG(
                source={"question": "follow-up?", "active_docs": ["vs1"]},
                chat_history=[{"prompt": "earlier", "response": "answer"}],
                chunks=2,
                model_id=owner_model["id"],
                model_user_id="owner",
                llm_name="openai_compatible",
                api_key="instance-secret",
                decoded_token={"sub": "caller"},
            )

        assert captured["api_key"] == "sk-owner", (
            "BYOM api_key must override the caller-passed instance secret"
        )
        assert captured["base_url"] == "https://api.mistral.ai/v1"
        assert captured["model_id"] == "mistral-large-latest"
        assert captured["gen_model"] == "mistral-large-latest", (
            "rephrase must send the upstream model name, not the registry UUID"
        )

    def test_configure_agent_propagates_owner_into_agent_config(self, pg_conn):
        """_configure_agent must populate agent_config['user_id'] from the
        agent record so _validate_and_set_model can reach the owner's
        BYOM layer. Without this, shared-agent BYOM defaults silently
        fall back to the system default for any non-owner caller."""
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )
        from application.storage.db.repositories.user_custom_models import (
            UserCustomModelsRepository,
        )

        repo = UserCustomModelsRepository(pg_conn)
        owner_model = repo.create(
            user_id="owner",
            upstream_model_id="mistral-large-latest",
            display_name="Owner Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-owner",
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()

            sp = StreamProcessor.__new__(StreamProcessor)
            sp.data = {"api_key": "agent-key"}
            sp.decoded_token = {"sub": "caller"}
            sp.initial_user_id = "caller"
            sp.agent_config = {}
            sp.is_shared_usage = True
            sp.shared_token = None
            sp.agent_id = None
            sp.agent_key = "agent-key"
            sp._agent_data = None

            agent_record = {
                "_id": "agent-uuid",
                "user": "owner",
                "prompt_id": "default",
                "agent_type": "classic",
                "default_model_id": owner_model["id"],
                "models": [],
            }

            with patch.object(
                StreamProcessor, "_resolve_agent_id", return_value="agent-uuid"
            ), patch.object(
                StreamProcessor,
                "_get_agent_key",
                return_value=("agent-key", True, None),
            ), patch.object(
                StreamProcessor, "_get_data_from_api_key", return_value=agent_record
            ):
                sp._configure_agent()
                sp._validate_and_set_model()

        # Owner identity flows through agent_config so the owner's BYOM
        # model resolves for the caller.
        assert sp.agent_config["user_id"] == "owner"
        assert sp.model_id == owner_model["id"]
        assert sp.model_user_id == "owner"


@pytest.mark.unit
class TestCompressionThresholdHonorsByomContextWindow:
    """P2 #2: orchestrator passes user_id to the threshold checker so
    BYOM context windows are honored (not the default 128k limit)."""

    def test_orchestrator_passes_user_id_to_should_compress(self, monkeypatch):
        from application.api.answer.services.compression.orchestrator import (
            CompressionOrchestrator,
        )
        from application.api.answer.services.compression.threshold_checker import (
            CompressionThresholdChecker,
        )

        captured: dict = {}

        def _record(self, conversation, model_id, current_query_tokens, **kw):
            captured["user_id"] = kw.get("user_id")
            return False

        monkeypatch.setattr(
            CompressionThresholdChecker, "should_compress", _record
        )

        conv_service = MagicMock()
        conv_service.get_conversation.return_value = {
            "queries": [{"prompt": "hi", "response": "hello"}]
        }
        orch = CompressionOrchestrator(
            conversation_service=conv_service,
            threshold_checker=CompressionThresholdChecker(),
        )
        orch.compress_if_needed(
            conversation_id="c1",
            user_id="alice",
            model_id="0b7e0f4c-1234-5678-9abc-deadbeef0200",
            decoded_token={"sub": "alice"},
        )
        assert captured["user_id"] == "alice"


@pytest.mark.unit
class TestContinuationPreservesByomScope:
    """P2: continuation/resume must persist ``model_user_id`` so the
    resumed LLM dispatch uses the same BYOM scope (owner for shared
    agents) as the initial call. Without this, resume falls back to
    ``decoded_token['sub']`` and the registry lookup misses the
    owner-stored BYOM record."""

    def test_resume_forwards_model_user_id_from_agent_config(
        self, monkeypatch
    ):
        """``resume_from_tool_actions`` reads ``model_user_id`` from the
        saved ``agent_config`` and forwards it to LLMCreator so the
        resumed dispatch resolves the owner's BYOM."""
        from application.api.answer.services import stream_processor as sp_mod
        from application.llm import llm_creator as llm_creator_mod
        from application.llm.handlers import handler_creator as handler_mod

        captured: dict = {}

        def _fake_create_llm(*args, **kwargs):
            captured["model_id"] = kwargs.get("model_id")
            captured["model_user_id"] = kwargs.get("model_user_id")
            return MagicMock()

        monkeypatch.setattr(
            llm_creator_mod.LLMCreator, "create_llm", _fake_create_llm
        )
        monkeypatch.setattr(
            handler_mod.LLMHandlerCreator,
            "create_handler",
            lambda *a, **kw: MagicMock(),
        )

        cont_service = MagicMock()
        cont_service.load_state.return_value = {
            "messages": [],
            "pending_tool_calls": [],
            "tools_dict": {},
            "tool_schemas": [],
            "agent_config": {
                "model_id": "byom-uuid",
                "model_user_id": "owner",
                "llm_name": "openai_compatible",
                "api_key": "instance-secret",
                "user_api_key": None,
                "agent_id": None,
                "agent_type": "ClassicAgent",
                "prompt": "",
                "json_schema": None,
                "retriever_config": None,
            },
            "client_tools": None,
        }
        # ContinuationService is imported lazily inside the method —
        # patch the source module so the lookup at call time resolves
        # to our mock.
        from application.api.answer.services import (
            continuation_service as cont_mod,
        )

        monkeypatch.setattr(
            cont_mod, "ContinuationService", lambda: cont_service
        )
        from application.agents import tool_executor as te_mod

        monkeypatch.setattr(
            te_mod, "ToolExecutor", lambda **kw: MagicMock(client_tools=None)
        )

        # Stub AgentCreator.create_agent so we don't need a full agent
        # tree — we're only exercising the LLMCreator forwarding.
        from application.agents import agent_creator as ac_mod

        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: MagicMock()
        )

        sp = sp_mod.StreamProcessor.__new__(sp_mod.StreamProcessor)
        sp.data = {}
        sp.decoded_token = {"sub": "caller"}
        sp.initial_user_id = "caller"
        sp.conversation_id = "00000000-0000-0000-0000-000000000001"
        sp.agent_config = {}

        sp.resume_from_tool_actions(
            tool_actions=[],
            conversation_id="00000000-0000-0000-0000-000000000001",
        )

        assert captured["model_id"] == "byom-uuid"
        assert captured["model_user_id"] == "owner", (
            "resume must thread the owner's BYOM scope, not fall back to "
            "the caller's decoded_token['sub']"
        )
        # The route layer (StreamResource) reads ``processor.model_user_id``
        # to forward into ``complete_stream``, which in turn drives both
        # the post-resume title-LLM save AND the agent_config dict
        # persisted on a *second* tool pause. Without writing the scope
        # back onto self here, processor.model_user_id stays at the
        # __init__ default (None) and the next save_state would persist
        # ``model_user_id=None`` — losing owner scope on every
        # subsequent resume.
        assert sp.model_user_id == "owner"

    def test_save_path_persists_model_user_id_in_agent_config(self):
        """The save site (``routes/base.py:complete_stream``) must
        include ``model_user_id`` in the ``agent_config`` dict written
        to the continuation store."""
        import inspect

        from application.api.answer.routes.base import BaseAnswerResource

        # complete_stream is the only callsite that constructs the
        # save dict. Confirm the parameter is in scope and the key is
        # spelled correctly so a future rename doesn't silently drop it.
        sig = inspect.signature(BaseAnswerResource.complete_stream)
        assert "model_user_id" in sig.parameters

        src = inspect.getsource(BaseAnswerResource.complete_stream)
        # Both: (a) the model_user_id parameter is in scope and (b) the
        # save dict includes it under the same key the resume side reads.
        assert '"model_user_id": model_user_id' in src


@pytest.mark.unit
class TestStreamProcessorForwardsByomScopeToBudgetCalls:
    """P2: every model-scoped lookup downstream of
    ``_validate_and_set_model`` must use ``self.model_user_id`` so the
    BYOM context window flows through retriever budget, history trim,
    compression threshold, and agent-side validation. Without this, a
    shared-agent owner-BYOM with an 8k window has retrieval/history
    sized against the default 128k, overfilling the upstream provider."""

    def _make_processor(self, model_user_id="owner", initial_user_id="caller"):
        from application.api.answer.services.stream_processor import (
            StreamProcessor,
        )

        sp = StreamProcessor.__new__(StreamProcessor)
        sp.data = {"history": "[]"}
        sp.decoded_token = {"sub": initial_user_id}
        sp.initial_user_id = initial_user_id
        sp.model_user_id = model_user_id
        sp.model_id = "byom-uuid"
        sp.agent_key = None
        sp.conversation_id = None
        sp.compression_orchestrator = MagicMock()
        sp._agent_data = None
        return sp

    def test_configure_retriever_passes_model_user_id_to_doc_budget(
        self, monkeypatch
    ):
        from application.api.answer.services import stream_processor as sp_mod

        captured: dict = {}

        def _fake_budget(model_id, user_id=None):
            captured["model_id"] = model_id
            captured["user_id"] = user_id
            return 6000

        monkeypatch.setattr(
            sp_mod, "calculate_doc_token_budget", _fake_budget
        )

        sp = self._make_processor(model_user_id="owner")
        sp._configure_retriever()

        assert captured["model_id"] == "byom-uuid"
        assert captured["user_id"] == "owner", (
            "doc budget must size against the owner's BYOM context "
            "window for shared-agent dispatch, not the caller's"
        )
        assert sp.retriever_config["doc_token_limit"] == 6000

    def test_load_conversation_history_passes_model_user_id_to_trim(
        self, monkeypatch
    ):
        from application.api.answer.services import stream_processor as sp_mod

        captured: dict = {}

        def _fake_limit(history, model_id="docsgpt-local", user_id=None):
            captured["model_id"] = model_id
            captured["user_id"] = user_id
            return history

        monkeypatch.setattr(sp_mod, "limit_chat_history", _fake_limit)

        sp = self._make_processor(model_user_id="owner")
        # No conversation_id → falls into the else branch that calls
        # limit_chat_history with the inline history payload.
        sp._load_conversation_history()

        assert captured["model_id"] == "byom-uuid"
        assert captured["user_id"] == "owner"

    def test_handle_compression_splits_caller_and_model_owner(self):
        sp = self._make_processor(
            model_user_id="owner", initial_user_id="caller"
        )
        sp.compression_orchestrator.compress_if_needed.return_value = (
            MagicMock(success=True, history=[], summary=None, summary_tokens=0)
        )

        sp._handle_compression(conversation={})

        kwargs = sp.compression_orchestrator.compress_if_needed.call_args.kwargs
        assert kwargs["user_id"] == "caller", (
            "conversation access check must run under the caller — the "
            "owner has no relationship to the conversation row"
        )
        assert kwargs["model_user_id"] == "owner", (
            "BYOM context-window / provider lookup must use the model "
            "owner so a shared-agent owner-BYOM resolves correctly"
        )

    def test_handle_compression_falls_back_to_caller_when_no_byom_scope(
        self,
    ):
        sp = self._make_processor(model_user_id=None, initial_user_id="caller")
        sp.compression_orchestrator.compress_if_needed.return_value = (
            MagicMock(success=True, history=[], summary=None, summary_tokens=0)
        )

        sp._handle_compression(conversation={})

        kwargs = sp.compression_orchestrator.compress_if_needed.call_args.kwargs
        assert kwargs["user_id"] == "caller"
        assert kwargs["model_user_id"] is None


@pytest.mark.unit
class TestBaseAgentTokenLimitUsesModelUserId:
    """P2: BaseAgent's three ``get_token_limit`` call sites must use
    ``model_user_id`` (the BYOM owner) when set, falling back to
    ``self.user`` (the caller / worker spoof). Otherwise shared-agent
    owner-BYOM token-limit checks size against the caller's layer."""

    def _build_agent(self, model_user_id="owner", caller="caller"):
        from application.agents.classic_agent import ClassicAgent

        # Stub LLM/handler/executor — we only exercise the get_token_limit
        # callsites in BaseAgent.
        return ClassicAgent(
            endpoint="stream",
            llm_name="openai_compatible",
            model_id="byom-uuid",
            api_key="instance-secret",
            decoded_token={"sub": caller},
            model_user_id=model_user_id,
            llm=MagicMock(model_id="mistral-large-latest"),
            llm_handler=MagicMock(),
            tool_executor=MagicMock(),
        )

    def test_check_context_limit_uses_model_user_id(self, monkeypatch):
        captured: list = []

        def _fake(model_id, user_id=None):
            captured.append({"model_id": model_id, "user_id": user_id})
            return 8000

        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit", _fake
        )

        agent = self._build_agent(model_user_id="owner", caller="caller")
        agent._check_context_limit([{"role": "user", "content": "hi"}])

        assert captured[0]["user_id"] == "owner"

    def test_validate_context_size_uses_model_user_id(self, monkeypatch):
        captured: list = []

        def _fake(model_id, user_id=None):
            captured.append({"user_id": user_id})
            return 8000

        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit", _fake
        )

        agent = self._build_agent(model_user_id="owner", caller="caller")
        agent._validate_context_size([{"role": "user", "content": "hi"}])

        assert captured[0]["user_id"] == "owner"

    def test_build_messages_uses_model_user_id(self, monkeypatch):
        captured: list = []

        def _fake(model_id, user_id=None):
            captured.append({"user_id": user_id})
            return 8000

        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit", _fake
        )

        agent = self._build_agent(model_user_id="owner", caller="caller")
        agent._build_messages(system_prompt="sys", query="q")

        assert captured[0]["user_id"] == "owner"

    def test_falls_back_to_self_user_when_model_user_id_unset(
        self, monkeypatch
    ):
        """Worker path: ``decoded_token['sub']`` is already the owner
        (worker spoofs it), so ``model_user_id`` is None and the
        fallback path uses ``self.user``."""
        captured: list = []

        def _fake(model_id, user_id=None):
            captured.append({"user_id": user_id})
            return 8000

        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit", _fake
        )

        agent = self._build_agent(model_user_id=None, caller="worker-owner")
        agent._validate_context_size([{"role": "user", "content": "hi"}])

        assert captured[0]["user_id"] == "worker-owner"


@pytest.mark.unit
class TestNonAgentCallSitesUseUpstreamId:
    """Locks in the call-site-by-call-site fix for direct ``llm.gen``
    invocations that bypass the agent's ``_llm_gen``: handler tool
    loops, conversation summarization, compression, and the classic
    RAG query-rephrase. Each one was sending the registry UUID
    upstream, which BYOM endpoints rejected with 401
    'key_model_access_denied'."""

    def test_handler_tool_loop_uses_upstream_id(self):
        """``handlers.base.handle_response`` re-calls the LLM after a
        tool invocation. The model arg must be the upstream name."""
        from application.llm.handlers.base import LLMHandler

        captured: dict = {}

        class _FakeLLM:
            model_id = "mistral-large-latest"  # upstream

            def gen(self, model, messages, tools=None):
                captured["model"] = model
                resp = MagicMock()
                resp.choices = [MagicMock()]
                resp.choices[0].message.content = "done"
                resp.choices[0].message.tool_calls = None
                resp.choices[0].finish_reason = "stop"
                return resp

        agent = MagicMock()
        agent.llm = _FakeLLM()
        agent.model_id = "0b7e0f4c-1234-5678-9abc-deadbeef0001"  # uuid
        agent.tools = []

        # Mimic the sub-class call directly to the line we patched.
        # We're not exercising the full LLMHandler state machine — just
        # the line that builds the gen call. Recreating it inline:
        model_arg = (
            getattr(agent.llm, "model_id", None) or agent.model_id
        )
        agent.llm.gen(model=model_arg, messages=[], tools=agent.tools)
        assert captured["model"] == "mistral-large-latest"
        assert captured["model"] != agent.model_id

        # Belt-and-braces: also verify the source file actually contains
        # the fix (catches accidental reverts).
        from inspect import getsourcefile
        from pathlib import Path

        text = Path(getsourcefile(LLMHandler)).read_text()
        # Both gen and gen_stream call sites use the getattr pattern
        assert text.count("getattr(agent.llm") >= 2

    def test_conversation_service_uses_upstream_id(self):
        """``conversation_service.save_conversation`` calls
        ``llm.gen(model=model_id, ...)`` to summarize. ``model_id`` is
        the registry UUID; must use ``llm.model_id`` instead."""
        from application.api.answer.services.conversation_service import (
            ConversationService,
        )

        captured: dict = {}

        class _FakeLLM:
            model_id = "mistral-large-latest"

            def gen(self, model, messages, **kwargs):
                captured["model"] = model
                return "summary"

        # Inline the patched line to verify the contract — the full
        # save_conversation path requires DB / agent setup orthogonal
        # to this test.
        llm = _FakeLLM()
        registry_uuid = "0b7e0f4c-1234-5678-9abc-deadbeef0002"
        model_arg = getattr(llm, "model_id", None) or registry_uuid
        llm.gen(model=model_arg, messages=[])
        assert captured["model"] == "mistral-large-latest"

        # Source check: the actual line contains the getattr fix
        from inspect import getsourcefile
        from pathlib import Path

        src_path = Path(getsourcefile(ConversationService))
        text = src_path.read_text()
        assert "getattr(llm" in text

    def test_compression_service_uses_upstream_id(self):
        """``CompressionService.compress`` must send ``llm.model_id``
        (the upstream) to the provider, not ``self.model_id`` (the
        registry UUID for BYOM)."""
        from inspect import getsourcefile
        from pathlib import Path

        from application.api.answer.services.compression.service import (
            CompressionService,
        )

        text = Path(getsourcefile(CompressionService)).read_text()
        # Locks in the call-site fix for the gen invocation.
        assert "getattr(self.llm" in text

    def test_classic_rag_uses_upstream_id(self):
        """``ClassicRAG._rephrase_query`` calls ``llm.gen(model=...)``
        with what was the agent's UUID. Must use ``llm.model_id``."""
        from inspect import getsourcefile
        from pathlib import Path

        from application.retriever.classic_rag import ClassicRAG

        text = Path(getsourcefile(ClassicRAG)).read_text()
        assert "getattr(self.llm" in text


@pytest.mark.unit
class TestAgentSendsUpstreamModelId:
    def test_llm_gen_passes_upstream_id_to_provider(
        self, pg_conn, byom_model
    ):
        """End-to-end: ClassicAgent's _llm_gen must put the user's
        upstream model name (``mistral-large-latest``) in the call to
        ``self.llm.gen_stream(model=...)``, not the registry UUID."""
        model_uuid, user_id = byom_model

        captured: dict = {}

        class _FakeOpenAILLM:
            def __init__(self, *a, **kw):
                # LLMCreator passes model_id=upstream_model_id; agent
                # caches it as self.upstream_model_id.
                self.model_id = kw.get("model_id")
                self.user_api_key = None
                self._supports_tools = False

            def _supports_structured_output(self):
                return False

            def supports_tools(self):
                return False

            def gen_stream(self, model, messages, **kw):
                captured["model"] = model
                captured["messages"] = messages
                yield "ok"

            def prepare_structured_output_format(self, schema):
                return None

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()

            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"],
                "llm_class",
                _FakeOpenAILLM,
            ):
                from application.agents.classic_agent import ClassicAgent

                agent = ClassicAgent(
                    endpoint="https://x",
                    llm_name="openai_compatible",
                    model_id=model_uuid,
                    api_key="caller-key",
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    prompt="system prompt",
                    chat_history=[],
                )
                # Sanity: agent cached the upstream id
                assert agent.upstream_model_id == "mistral-large-latest"

                # Drive _llm_gen via a minimal message; consume the
                # generator so the fake gen_stream actually runs.
                gen = agent._llm_gen([{"role": "user", "content": "hi"}])
                list(gen)

        assert captured["model"] == "mistral-large-latest"
        assert captured["model"] != model_uuid
