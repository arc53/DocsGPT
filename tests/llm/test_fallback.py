"""Integration tests for LLM fallback behaviour.

Verifies that when a primary model fails (immediately or mid-stream), the
per-agent backup model is used before the global FALLBACK_* settings.
"""

from unittest.mock import MagicMock

import pytest

from application.llm.base import BaseLLM


# Concrete LLM stubs


class FakeLLM(BaseLLM):
    """Minimal concrete BaseLLM for testing."""

    def __init__(self, responses=None, stream_chunks=None, fail_at=None, **kwargs):
        # Accept and discard api_key / user_api_key so LLMCreator.create_llm
        # signatures work without errors.
        kwargs.pop("api_key", None)
        kwargs.pop("user_api_key", None)
        super().__init__(**kwargs)
        self.responses = responses or ["fake response"]
        self.stream_chunks = stream_chunks or ["chunk1", "chunk2"]
        self.fail_at = fail_at  # None = no failure, 0 = immediate, N = after N chunks
        self.user_api_key = None
        self.gen_called = False
        self.gen_stream_called = False
        self.last_model_received = None  # tracks the model kwarg passed to gen/gen_stream

    # Track at the raw-method level. _execute_with_fallback applies
    # decorators to the fallback's raw method directly and
    # never calls .gen() / .gen_stream() on it, so a public-method
    # override would not register fallback hops.
    def _raw_gen(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.gen_called = True
        self.last_model_received = model
        if self.fail_at is not None:
            raise RuntimeError("primary model unavailable")
        return self.responses[0]

    def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.gen_stream_called = True
        self.last_model_received = model
        yielded = 0
        for chunk in self.stream_chunks:
            if self.fail_at is not None and yielded >= self.fail_at:
                raise RuntimeError("mid-stream failure")
            yield chunk
            yielded += 1


# Helpers


def _noop_decorator(func):
    """Pass-through decorator that replaces cache / token-usage wrappers."""

    def wrapper(self_llm, model, messages, stream, tools=None, **kwargs):
        return func(self_llm, model, messages, stream, tools, **kwargs)

    return wrapper


def _noop_stream_decorator(func):
    """Pass-through generator decorator for streaming wrappers."""

    def wrapper(self_llm, model, messages, stream, tools=None, **kwargs):
        yield from func(self_llm, model, messages, stream, tools, **kwargs)

    return wrapper


@pytest.fixture(autouse=True)
def _patch_decorators(monkeypatch):
    """Replace cache & token-usage decorators with no-ops so tests focus on
    fallback logic without needing Redis or token-counting infra."""
    monkeypatch.setattr("application.llm.base.gen_cache", _noop_decorator)
    monkeypatch.setattr("application.llm.base.gen_token_usage", _noop_decorator)
    monkeypatch.setattr("application.llm.base.stream_cache", _noop_stream_decorator)
    monkeypatch.setattr(
        "application.llm.base.stream_token_usage", _noop_stream_decorator
    )


@pytest.fixture
def patch_model_utils(monkeypatch):
    """Patch model_utils functions used by fallback_llm property."""

    def _apply(get_provider=None, get_api_key=None, create_llm=None):
        if get_provider:
            monkeypatch.setattr(
                "application.core.model_utils.get_provider_from_model_id",
                get_provider,
            )
        if get_api_key:
            monkeypatch.setattr(
                "application.core.model_utils.get_api_key_for_provider",
                get_api_key,
            )
        if create_llm:
            monkeypatch.setattr(
                "application.llm.llm_creator.LLMCreator.create_llm",
                create_llm,
            )

    return _apply


CALL_ARGS = dict(model="test-model", messages=[{"role": "user", "content": "hi"}])


# Tests — fallback_llm property resolution


@pytest.mark.integration
class TestFallbackLLMResolution:

    def test_backup_model_preferred_over_global_fallback(self, patch_model_utils):
        """When agent has backup models configured, the first valid one is used
        as fallback — not the global FALLBACK_* settings."""
        backup_llm = FakeLLM(responses=["backup response"])

        patch_model_utils(
            get_provider=lambda mid, **_kwargs: "openai",
            get_api_key=lambda prov: "fake-key",
            create_llm=lambda type, **kw: backup_llm,
        )

        primary = FakeLLM(backup_models=["backup-model-id"])
        fallback = primary.fallback_llm

        assert fallback is backup_llm

    def test_global_fallback_used_when_no_backup_models(
        self, monkeypatch, patch_model_utils
    ):
        """When no per-agent backup models exist, global FALLBACK_* is used."""
        global_fallback = FakeLLM(responses=["global fallback"])

        patch_model_utils(
            create_llm=lambda type, **kw: global_fallback,
        )
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(
                FALLBACK_LLM_PROVIDER="openai",
                FALLBACK_LLM_NAME="gpt-4o",
                FALLBACK_LLM_API_KEY="key",
                API_KEY="key",
            ),
        )

        primary = FakeLLM(backup_models=[])
        fallback = primary.fallback_llm

        assert fallback is global_fallback

    def test_skips_unresolvable_backup_model_tries_next(self, patch_model_utils):
        """If the first backup model can't be resolved, skip it and try the next."""
        good_backup = FakeLLM(responses=["good backup"])
        call_count = {"n": 0}

        def fake_get_provider(model_id, **_kwargs):
            call_count["n"] += 1
            if model_id == "bad-model":
                return None  # unresolvable
            return "openai"

        patch_model_utils(
            get_provider=fake_get_provider,
            get_api_key=lambda prov: "key",
            create_llm=lambda type, **kw: good_backup,
        )

        primary = FakeLLM(backup_models=["bad-model", "good-model"])
        fallback = primary.fallback_llm

        assert fallback is good_backup
        assert call_count["n"] == 2  # tried both

    def test_no_fallback_when_nothing_configured(self, monkeypatch):
        """No backup models + no global FALLBACK_* → fallback_llm is None."""
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )
        primary = FakeLLM(backup_models=[])
        assert primary.fallback_llm is None


# Tests — non-streaming fallback (gen)


@pytest.mark.integration
class TestNonStreamingFallback:

    def test_primary_success_no_fallback(self):
        """When primary succeeds, fallback is never touched."""
        primary = FakeLLM(responses=["primary ok"])
        result = primary.gen(**CALL_ARGS)
        assert result == "primary ok"

    def test_primary_fails_uses_backup_model(self, patch_model_utils):
        """Primary fails immediately → backup model from agent config is used."""
        backup = FakeLLM(responses=["backup ok"])

        patch_model_utils(
            get_provider=lambda mid, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(fail_at=0, backup_models=["backup-model"])
        result = primary.gen(**CALL_ARGS)
        assert result == "backup ok"
        assert backup.gen_called

    def test_no_fallback_raises(self, monkeypatch):
        """Primary fails and no fallback configured → exception propagates."""
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )
        primary = FakeLLM(fail_at=0, backup_models=[])
        with pytest.raises(RuntimeError, match="primary model unavailable"):
            primary.gen(**CALL_ARGS)


# Tests — streaming fallback (gen_stream)


@pytest.mark.integration
class TestStreamingFallback:

    def test_stream_primary_success(self):
        """Full stream completes without triggering fallback."""
        primary = FakeLLM(stream_chunks=["a", "b", "c"])
        chunks = list(primary.gen_stream(**CALL_ARGS))
        assert chunks == ["a", "b", "c"]

    def test_stream_immediate_failure_uses_backup(self, patch_model_utils):
        """Primary fails before yielding anything → entire backup stream returned."""
        backup = FakeLLM(stream_chunks=["fallback1", "fallback2"])

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            stream_chunks=["x", "y"],
            fail_at=0,  # fail before first chunk
            backup_models=["backup-model"],
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))
        assert chunks == ["fallback1", "fallback2"]
        assert backup.gen_stream_called

    def test_stream_mid_stream_failure_uses_backup(self, patch_model_utils):
        """Primary yields some chunks then fails → backup stream follows partial output."""
        backup = FakeLLM(stream_chunks=["recovery1", "recovery2"])

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            stream_chunks=["ok1", "ok2", "ok3"],
            fail_at=2,  # yields ok1, ok2, then fails before ok3
            backup_models=["backup-model"],
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))
        # First two from primary, then full backup stream
        assert chunks == ["ok1", "ok2", "recovery1", "recovery2"]

    def test_stream_no_fallback_raises(self, monkeypatch):
        """Primary stream fails and no fallback → exception propagates."""
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )
        primary = FakeLLM(stream_chunks=["x"], fail_at=0, backup_models=[])
        with pytest.raises(RuntimeError, match="mid-stream failure"):
            list(primary.gen_stream(**CALL_ARGS))

    def test_fallback_emits_stream_start_with_fallback_provider(
        self, patch_model_utils, caplog
    ):
        # The fallback raw-stream path bypasses ``gen_stream``, so it must
        # emit its own ``llm_stream_start`` event tagged with the fallback
        # vendor — otherwise dashboards record only the failed primary
        # even when the response came from the backup.
        import logging as _logging

        class FallbackProvider(FakeLLM):
            provider_name = "fallback-vendor"

        backup = FallbackProvider(
            stream_chunks=["b1"], model_id="backup-model-id"
        )
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        class PrimaryProvider(FakeLLM):
            provider_name = "primary-vendor"

        primary = PrimaryProvider(
            stream_chunks=["x"],
            fail_at=0,
            backup_models=["backup-model-id"],
        )

        with caplog.at_level(_logging.INFO, logger="root"):
            list(
                primary.gen_stream(
                    model="primary-model",
                    messages=[{"role": "user", "content": "hi"}],
                )
            )

        starts = [r for r in caplog.records if r.message == "llm_stream_start"]
        assert len(starts) == 2
        assert starts[0].provider == "primary-vendor"
        assert starts[0].model == "primary-model"
        assert starts[1].provider == "fallback-vendor"
        assert starts[1].model == "backup-model-id"


# Tests — fallback never re-enters the orchestrator (Option B regression)


@pytest.mark.integration
class TestFallbackNoRecursion:
    """When the primary fails, _execute_with_fallback applies decorators to
    the fallback's raw method directly. The fallback's own ``fallback_llm``
    property must never be accessed — otherwise a fallback failure would
    re-enter the orchestrator and walk the global FALLBACK_LLM_* chain
    unboundedly."""

    def test_backup_fallback_llm_property_never_accessed_on_gen_failure(
        self, monkeypatch, patch_model_utils
    ):
        backup = FakeLLM(fail_at=0)  # backup also fails

        accessed_on = []
        original_property = BaseLLM.fallback_llm

        def tracked_fallback_llm(self_llm):
            accessed_on.append(self_llm)
            return original_property.fget(self_llm)

        monkeypatch.setattr(
            BaseLLM, "fallback_llm", property(tracked_fallback_llm)
        )

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(fail_at=0, backup_models=["backup-model"])
        with pytest.raises(RuntimeError, match="primary model unavailable"):
            primary.gen(**CALL_ARGS)

        assert primary in accessed_on  # primary lazy-loaded its fallback
        assert backup not in accessed_on  # backup's chain was never walked

    def test_backup_fallback_llm_property_never_accessed_on_stream_failure(
        self, monkeypatch, patch_model_utils
    ):
        backup = FakeLLM(stream_chunks=["x"], fail_at=0)

        accessed_on = []
        original_property = BaseLLM.fallback_llm

        def tracked_fallback_llm(self_llm):
            accessed_on.append(self_llm)
            return original_property.fget(self_llm)

        monkeypatch.setattr(
            BaseLLM, "fallback_llm", property(tracked_fallback_llm)
        )

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            stream_chunks=["y"], fail_at=0, backup_models=["backup-model"]
        )
        with pytest.raises(RuntimeError, match="mid-stream failure"):
            list(primary.gen_stream(**CALL_ARGS))

        assert primary in accessed_on
        assert backup not in accessed_on

    def test_fallback_failure_propagates_without_chain(self, patch_model_utils):
        """When both primary and fallback fail, the fallback's exception
        propagates cleanly — no third hop, no extra retries."""
        backup = FakeLLM(fail_at=0)

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(fail_at=0, backup_models=["backup-model"])
        with pytest.raises(RuntimeError, match="primary model unavailable"):
            primary.gen(**CALL_ARGS)

        assert backup.gen_called  # confirms fallback raw method WAS invoked


# Tests — backup model priority over global fallback


@pytest.mark.integration
class TestBackupModelPriority:

    def test_agent_backup_tried_before_global_on_gen_failure(self, patch_model_utils):
        """On gen() failure, agent's backup model is used — not the global fallback."""
        backup = FakeLLM(responses=["agent backup"])
        created_models = []

        def fake_create_llm(type, **kw):
            created_models.append(kw.get("model_id"))
            return backup

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=fake_create_llm,
        )

        primary = FakeLLM(fail_at=0, backup_models=["agent-backup-model"])
        result = primary.gen(**CALL_ARGS)

        assert result == "agent backup"
        assert "agent-backup-model" in created_models

    def test_agent_backup_tried_before_global_on_stream_failure(
        self, patch_model_utils
    ):
        """On gen_stream() failure, agent's backup model is used — not the global."""
        backup = FakeLLM(stream_chunks=["agent-stream"])
        created_models = []

        def fake_create_llm(type, **kw):
            created_models.append(kw.get("model_id"))
            return backup

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=fake_create_llm,
        )

        primary = FakeLLM(
            stream_chunks=["x"], fail_at=0, backup_models=["agent-backup-model"]
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["agent-stream"]
        assert "agent-backup-model" in created_models

    def test_global_fallback_used_when_all_backup_models_fail(
        self, monkeypatch, patch_model_utils
    ):
        """If every agent backup model fails to initialize, fall through to global."""
        global_fallback = FakeLLM(responses=["global ok"])
        call_order = []

        def fake_get_provider(mid, **_kwargs):
            if mid == "broken-backup":
                return "nonexistent_provider"
            return "openai"

        def fake_create_llm(type, **kw):
            model_id = kw.get("model_id")
            call_order.append(model_id)
            if model_id == "broken-backup":
                raise ValueError("provider init failed")
            return global_fallback

        patch_model_utils(
            get_provider=fake_get_provider,
            get_api_key=lambda p: "k",
            create_llm=fake_create_llm,
        )
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(
                FALLBACK_LLM_PROVIDER="openai",
                FALLBACK_LLM_NAME="global-model",
                FALLBACK_LLM_API_KEY="gk",
                API_KEY="gk",
            ),
        )

        primary = FakeLLM(fail_at=0, backup_models=["broken-backup"])
        result = primary.gen(**CALL_ARGS)

        assert result == "global ok"
        # Tried broken-backup first, then fell through to global-model
        assert call_order == ["broken-backup", "global-model"]


# Tests — fallback uses its own model_id, not the primary's


@pytest.mark.integration
class TestFallbackModelIdOverride:
    """The fallback LLM must be called with its own model_id — not the
    primary's.  Otherwise providers like Groq receive an unknown model name
    (e.g. a Qwen model_id) and return 404."""

    def test_gen_fallback_receives_own_model_id(self, patch_model_utils):
        """Non-streaming: fallback.gen() is called with fallback.model_id."""
        backup = FakeLLM(
            responses=["backup ok"], model_id="groq-gpt-oss-120b"
        )

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "groq",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            fail_at=0,
            model_id="qwen/qwen3-4b-2507",
            backup_models=["groq-gpt-oss-120b"],
        )
        result = primary.gen(**CALL_ARGS)

        assert result == "backup ok"
        assert backup.last_model_received == "groq-gpt-oss-120b"

    def test_gen_stream_fallback_receives_own_model_id(self, patch_model_utils):
        """Streaming: fallback.gen_stream() is called with fallback.model_id."""
        backup = FakeLLM(
            stream_chunks=["ok"], model_id="groq-gpt-oss-120b"
        )

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "groq",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            stream_chunks=["x"],
            fail_at=0,
            model_id="qwen/qwen3-4b-2507",
            backup_models=["groq-gpt-oss-120b"],
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["ok"]
        assert backup.last_model_received == "groq-gpt-oss-120b"

    def test_mid_stream_fallback_receives_own_model_id(self, patch_model_utils):
        """Mid-stream failure: fallback still gets its own model_id, not the
        primary's that was already partially streaming."""
        backup = FakeLLM(
            stream_chunks=["recovered"], model_id="groq-gpt-oss-120b"
        )

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "groq",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            stream_chunks=["partial1", "partial2", "boom"],
            fail_at=2,
            model_id="qwen/qwen3-4b-2507",
            backup_models=["groq-gpt-oss-120b"],
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["partial1", "partial2", "recovered"]
        assert backup.last_model_received == "groq-gpt-oss-120b"


# Tests — model_user_id (BYOM owner scope) propagates into fallback resolution


@pytest.mark.integration
class TestFallbackModelUserIdScope:
    """A shared agent dispatched by user B but owned by user A stores
    A's BYOM UUIDs as backup_models. Without the P2 fix the fallback
    property looks up those UUIDs against ``decoded_token['sub']`` (B,
    the caller), which can't see A's per-user layer — backups are
    silently skipped and the global FALLBACK_* settings are used
    instead. These tests pin down that ``model_user_id`` (the owner)
    is used both for the registry lookup and for the recursive
    ``LLMCreator.create_llm`` call."""

    def test_backup_lookup_uses_model_user_id_not_caller(
        self, patch_model_utils
    ):
        captured = {"user_id": None}

        def fake_get_provider(model_id, **kwargs):
            captured["user_id"] = kwargs.get("user_id")
            return "openai"

        backup = FakeLLM(responses=["ok"])
        patch_model_utils(
            get_provider=fake_get_provider,
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        primary = FakeLLM(
            decoded_token={"sub": "caller-bob"},
            model_user_id="owner-alice",
            backup_models=["alice-byom-uuid"],
        )
        _ = primary.fallback_llm
        assert captured["user_id"] == "owner-alice"

    def test_backup_create_llm_receives_model_user_id(self, patch_model_utils):
        backup = FakeLLM(responses=["ok"])
        captured = {}

        def fake_create_llm(type, **kw):
            captured["model_user_id"] = kw.get("model_user_id")
            captured["model_id"] = kw.get("model_id")
            return backup

        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=fake_create_llm,
        )

        primary = FakeLLM(
            decoded_token={"sub": "caller-bob"},
            model_user_id="owner-alice",
            backup_models=["alice-byom-uuid"],
        )
        _ = primary.fallback_llm
        assert captured["model_user_id"] == "owner-alice"
        assert captured["model_id"] == "alice-byom-uuid"

    def test_global_fallback_create_llm_receives_model_user_id(
        self, monkeypatch, patch_model_utils
    ):
        """The global FALLBACK_LLM_NAME path must also forward
        ``model_user_id`` — operators can configure it to a BYOM UUID
        that's owned by the same user as the primary model."""
        backup = FakeLLM(responses=["ok"])
        captured = {}

        def fake_create_llm(type, **kw):
            captured["model_user_id"] = kw.get("model_user_id")
            return backup

        patch_model_utils(create_llm=fake_create_llm)
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(
                FALLBACK_LLM_PROVIDER="openai",
                FALLBACK_LLM_NAME="some-uuid",
                FALLBACK_LLM_API_KEY="k",
                API_KEY="k",
            ),
        )

        primary = FakeLLM(
            decoded_token={"sub": "caller-bob"},
            model_user_id="owner-alice",
            backup_models=[],
        )
        _ = primary.fallback_llm
        assert captured["model_user_id"] == "owner-alice"

    def test_falls_back_to_caller_when_model_user_id_unset(
        self, patch_model_utils
    ):
        """Built-in models / pre-P2 callers don't pass model_user_id.
        In that case the caller's sub is still used — preserving
        existing behaviour."""
        captured = {}

        def fake_get_provider(model_id, **kwargs):
            captured["user_id"] = kwargs.get("user_id")
            return "openai"

        patch_model_utils(
            get_provider=fake_get_provider,
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: FakeLLM(responses=["ok"]),
        )

        primary = FakeLLM(
            decoded_token={"sub": "caller-bob"},
            model_user_id=None,
            backup_models=["some-builtin-id"],
        )
        _ = primary.fallback_llm
        assert captured["user_id"] == "caller-bob"


# Tests — LLMCreator wires model_user_id through to BaseLLM


@pytest.mark.unit
class TestLLMCreatorPassesModelUserId:
    """End-to-end through ``LLMCreator.create_llm``: the constructed
    LLM must store ``model_user_id`` so its fallback property can
    resolve under the right scope."""

    def test_model_user_id_set_on_constructed_llm(self, monkeypatch):
        from application.llm.llm_creator import LLMCreator
        from application.llm.providers import PROVIDERS_BY_NAME

        captured = {}

        class _CapturingLLM:
            def __init__(self, api_key, user_api_key, *args, **kwargs):
                captured["model_user_id"] = kwargs.get("model_user_id")

        # Pick any registered provider — we only need the constructor
        # call to land in our fake.
        monkeypatch.setattr(
            PROVIDERS_BY_NAME["openai"], "llm_class", _CapturingLLM
        )

        LLMCreator.create_llm(
            type="openai",
            api_key="k",
            user_api_key=None,
            decoded_token={"sub": "caller-bob"},
            model_id=None,
            model_user_id="owner-alice",
        )

        assert captured["model_user_id"] == "owner-alice"
