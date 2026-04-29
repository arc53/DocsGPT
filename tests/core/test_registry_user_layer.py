"""Tests for the BYOM per-user layer on ModelRegistry.

Covers: per-user lookups don't leak across users, lookups without
user_id stay built-in only, get_all_models / get_enabled_models /
model_exists all consult the user layer when given user_id, and the
explicit invalidate_user clears the cache.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from application.core.model_registry import ModelRegistry
from application.core.model_settings import ModelProvider
from application.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


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
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@contextmanager
def _yield(conn):
    yield conn


@pytest.mark.unit
class TestPerUserLayer:
    def test_user_models_isolated_per_user(self, pg_conn):
        """Alice's BYOM model must not appear in Bob's lookups."""
        repo = UserCustomModelsRepository(pg_conn)
        alice_model = repo.create(
            user_id="alice",
            upstream_model_id="alice-mistral",
            display_name="Alice Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-alice",
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            reg = ModelRegistry()
            assert reg.get_model(alice_model["id"], user_id="alice") is not None
            assert reg.get_model(alice_model["id"], user_id="bob") is None
            # And without a user_id at all, the per-user layer is invisible
            assert reg.get_model(alice_model["id"]) is None

    def test_get_all_models_includes_user_models(self, pg_conn):
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="mistral-large-latest",
            display_name="My Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-test",
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            reg = ModelRegistry()
            ids_no_user = {m.id for m in reg.get_all_models()}
            ids_with_user = {
                m.id for m in reg.get_all_models(user_id="user-1")
            }
        assert created["id"] not in ids_no_user
        assert created["id"] in ids_with_user

    def test_user_models_carry_decrypted_api_key_and_upstream_id(self, pg_conn):
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="mistral-large-latest",
            display_name="My Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-test-XYZ",
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            reg = ModelRegistry()
            m = reg.get_model(created["id"], user_id="user-1")

        assert m is not None
        assert m.provider == ModelProvider.OPENAI_COMPATIBLE
        assert m.upstream_model_id == "mistral-large-latest"
        assert m.api_key == "sk-test-XYZ"
        assert m.base_url == "https://api.mistral.ai/v1"
        assert m.source == "user"
        # The wire format never leaks the api_key
        d = m.to_dict()
        assert "api_key" not in d
        for v in d.values():
            assert v != "sk-test-XYZ"

    def test_invalidate_user_clears_cache(self, pg_conn):
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="x",
            display_name="X",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="k",
        )

        s = _make_settings()
        # Stub Redis so invalidate_user can publish its version bump
        # without hitting a real broker. The P1 fix calls ``incr`` on
        # invalidate; here we just need it not to raise.
        fake_redis = MagicMock()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ), patch(
            "application.cache.get_redis_instance", return_value=fake_redis
        ):
            reg = ModelRegistry()
            assert reg.get_model(created["id"], user_id="user-1") is not None
            # Cache populated
            assert "user-1" in reg._user_models
            ModelRegistry.invalidate_user("user-1")
            assert "user-1" not in reg._user_models
            # Re-lookup repopulates
            reg.get_model(created["id"], user_id="user-1")
            assert "user-1" in reg._user_models


@pytest.mark.unit
class TestLLMCreatorDispatchUsesUpstreamModelId:
    def test_llmcreator_sends_upstream_id_not_uuid(self, pg_conn):
        """End-to-end: LLMCreator with a BYOM uuid must construct the
        OpenAILLM with the user's upstream model name (e.g.
        ``mistral-large-latest``), not the registry uuid."""
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="mistral-large-latest",
            display_name="My Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-mistral-real",
        )

        captured = {}

        class _FakeLLM:
            def __init__(self, api_key, user_api_key, *args, **kwargs):
                captured["api_key"] = api_key
                captured["base_url"] = kwargs.get("base_url")
                captured["model_id"] = kwargs.get("model_id")

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"], "llm_class", _FakeLLM
            ):
                from application.llm.llm_creator import LLMCreator

                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="caller-passed-WRONG",
                    user_api_key=None,
                    decoded_token={"sub": "user-1"},
                    model_id=created["id"],
                )

        assert captured["api_key"] == "sk-mistral-real"
        assert captured["base_url"] == "https://api.mistral.ai/v1"
        assert captured["model_id"] == "mistral-large-latest"  # NOT the uuid!

    def test_llmcreator_forwards_byom_capabilities(self, pg_conn):
        """LLMCreator must thread the registry-resolved ``capabilities``
        into the LLM. Without it the OpenAILLM hard-codes ``True`` for
        tools/structured output and advertises image attachments
        unconditionally, leaking unsupported features to BYOMs that
        disabled them."""
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-2",
            upstream_model_id="my-text-only-model",
            display_name="Text-only BYOM",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-real",
            capabilities={
                "supports_tools": False,
                "supports_structured_output": False,
                "attachments": [],
                "context_window": 8192,
            },
        )

        captured = {}

        class _FakeLLM:
            def __init__(self, api_key, user_api_key, *args, **kwargs):
                captured["capabilities"] = kwargs.get("capabilities")

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            ModelRegistry()
            from application.llm.providers import PROVIDERS_BY_NAME

            with patch.object(
                PROVIDERS_BY_NAME["openai_compatible"], "llm_class", _FakeLLM
            ):
                from application.llm.llm_creator import LLMCreator

                LLMCreator.create_llm(
                    type="openai_compatible",
                    api_key="ignored",
                    user_api_key=None,
                    decoded_token={"sub": "user-2"},
                    model_id=created["id"],
                )

        caps = captured["capabilities"]
        assert caps is not None
        assert caps.supports_tools is False
        assert caps.supports_structured_output is False
        assert caps.supported_attachment_types == []

    def test_byom_image_alias_expands_to_mime_types(self, pg_conn):
        """A BYOM stored with ``attachments: ["image"]`` (the alias the
        UI sends) must surface as concrete MIME types on the registry
        record, matching the built-in YAML expansion. Without this,
        handlers/base.prepare_messages compares ``image/png`` against
        the bare alias and filters every image upload as unsupported.
        """
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="my-vision-model",
            display_name="Vision BYOM",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="sk-real",
            capabilities={"attachments": ["image"]},
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            reg = ModelRegistry()
            model = reg.get_model(created["id"], user_id="user-1")

        assert model is not None
        types = model.capabilities.supported_attachment_types
        assert "image" not in types, (
            "alias must be expanded, not stored verbatim"
        )
        assert any(t.startswith("image/") for t in types)
        # Must include at least the common web image types so any image
        # an end user uploads has a chance to match.
        assert "image/png" in types
        assert "image/jpeg" in types

    def test_byom_unknown_alias_is_skipped_at_runtime(self, pg_conn):
        """Operator alias-map edits could orphan a stored alias. The
        registry must drop the unknown entry rather than the entire
        layer (which would hide every BYOM the user has).
        """
        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="m",
            display_name="M",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="k",
            # Bypass the route validation: write a bad alias straight
            # to the row to simulate the post-edit orphan case.
            capabilities={"attachments": ["image", "not-a-real-alias"]},
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ):
            reg = ModelRegistry()
            model = reg.get_model(created["id"], user_id="user-1")

        assert model is not None
        types = model.capabilities.supported_attachment_types
        assert "not-a-real-alias" not in types
        assert any(t.startswith("image/") for t in types)


@pytest.mark.unit
class TestCrossProcessInvalidation:
    """The BYOM cache lives per-process. Without the P1 fix, a CRUD on
    web-1 would leave the decrypted record (with old api_key/base_url)
    cached forever in web-2 / Celery. These tests pin down that:

      * ``invalidate_user`` publishes a version bump to Redis
      * peers reload when the version they saw at load time is stale
      * the local TTL bounds staleness even when Redis is unreachable
      * unchanged version + expired TTL extends the entry without a
        DB read (the common-case fast path)
    """

    def test_invalidate_user_publishes_redis_version_bump(self, pg_conn):
        repo = UserCustomModelsRepository(pg_conn)
        repo.create(
            user_id="user-1",
            upstream_model_id="m1",
            display_name="M1",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="k",
        )

        fake_redis = MagicMock()
        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ), patch(
            "application.cache.get_redis_instance", return_value=fake_redis
        ):
            ModelRegistry().get_model("anything", user_id="user-1")
            ModelRegistry.invalidate_user("user-1")

        fake_redis.incr.assert_called_once_with("byom:registry_version:user-1")

    def test_peer_reloads_when_redis_version_changes(self, pg_conn):
        """Two-process simulation. Peer loads at version=0; another
        process's CRUD bumps the version and updates Postgres; peer's
        next post-TTL access sees the version mismatch and reloads,
        picking up the rotated key it never invalidated locally."""
        from application.core import model_registry as registry_mod

        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="m-orig",
            display_name="orig",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="orig-key",
        )

        state = {"version": 0}

        class _FakeRedis:
            def get(self, key):
                if key == "byom:registry_version:user-1":
                    return str(state["version"]).encode()
                return None

            def incr(self, key):
                if key == "byom:registry_version:user-1":
                    state["version"] += 1

        s = _make_settings()
        # Force TTL to 0 so any subsequent access takes the post-TTL
        # path without waiting 60s.
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ), patch(
            "application.cache.get_redis_instance", return_value=_FakeRedis()
        ), patch.object(
            registry_mod, "_USER_CACHE_TTL_SECONDS", 0.0
        ):
            reg = ModelRegistry()
            assert (
                reg.get_model(created["id"], user_id="user-1").api_key
                == "orig-key"
            )

            # Another process's CRUD: bump Redis counter + mutate the
            # row. Note we deliberately do NOT call ``invalidate_user``
            # in this process — that's the whole point of the test.
            state["version"] += 1
            repo.update(
                created["id"],
                "user-1",
                {"api_key_plaintext": "rotated-key"},
            )

            assert (
                reg.get_model(created["id"], user_id="user-1").api_key
                == "rotated-key"
            )

    def test_ttl_bounds_staleness_when_redis_unavailable(self, pg_conn):
        """Redis down → fall back to TTL-only invalidation. After the
        TTL elapses, peers reload regardless."""
        from application.core import model_registry as registry_mod

        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="m",
            display_name="m",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="orig",
        )

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            lambda: _yield(pg_conn),
        ), patch(
            "application.cache.get_redis_instance", return_value=None
        ), patch.object(
            registry_mod, "_USER_CACHE_TTL_SECONDS", 0.0
        ):
            reg = ModelRegistry()
            first = reg.get_model(created["id"], user_id="user-1")
            assert first.api_key == "orig"

            repo.update(
                created["id"],
                "user-1",
                {"api_key_plaintext": "rotated"},
            )

            second = reg.get_model(created["id"], user_id="user-1")
            assert second.api_key == "rotated"

    def test_unchanged_version_extends_ttl_without_db_read(self, pg_conn):
        """Hot path: TTL expires but Redis says no invalidation
        happened — extend the entry without re-reading Postgres."""
        from application.core import model_registry as registry_mod

        repo = UserCustomModelsRepository(pg_conn)
        created = repo.create(
            user_id="user-1",
            upstream_model_id="m",
            display_name="m",
            base_url="https://api.mistral.ai/v1",
            api_key_plaintext="k",
        )

        fake_redis = MagicMock()
        fake_redis.get.return_value = b"7"  # constant version

        db_open_count = {"n": 0}

        @contextmanager
        def _counting_db_readonly():
            db_open_count["n"] += 1
            yield pg_conn

        s = _make_settings()
        with patch("application.core.settings.settings", s), patch(
            "application.storage.db.session.db_readonly",
            _counting_db_readonly,
        ), patch(
            "application.cache.get_redis_instance", return_value=fake_redis
        ), patch.object(
            registry_mod, "_USER_CACHE_TTL_SECONDS", 0.0
        ):
            reg = ModelRegistry()
            reg.get_model(created["id"], user_id="user-1")
            first_open = db_open_count["n"]
            # TTL has expired, but Redis returns the same version we
            # captured at load time → no DB reload.
            reg.get_model(created["id"], user_id="user-1")
            reg.get_model(created["id"], user_id="user-1")
            assert db_open_count["n"] == first_open
