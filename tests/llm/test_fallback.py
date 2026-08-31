"""Integration tests for LLM fallback behaviour.

Verifies that when a primary model fails (immediately or mid-stream), the
per-agent backup model is used before the global FALLBACK_* settings.
"""

import copy
import logging
import types
from unittest.mock import MagicMock

import httpx
import pytest

from application.llm.anthropic import AnthropicLLM
from application.llm.base import BaseLLM
from application.llm.google_ai import GoogleLLM
from application.llm.groq import GroqLLM
from application.llm.openai import OpenAILLM


# Concrete LLM stubs


class FakeLLM(BaseLLM):
    """Minimal concrete BaseLLM for testing."""

    def __init__(self, responses=None, stream_chunks=None, fail_at=None, **kwargs):
        # Accept and discard api_key / user_api_key so LLMCreator.create_llm
        # signatures work without errors.
        kwargs.pop("api_key", None)
        kwargs.pop("user_api_key", None)
        # Retry-once tests supply these; strip before BaseLLM.__init__.
        error_class = kwargs.pop("error_class", RuntimeError)
        fail_schedule = kwargs.pop("fail_schedule", None)
        error_schedule = kwargs.pop("error_schedule", None)
        super().__init__(**kwargs)
        self.responses = responses or ["fake response"]
        self.stream_chunks = stream_chunks or ["chunk1", "chunk2"]
        self.fail_at = fail_at  # None = no failure, 0 = immediate, N = after N chunks
        self.error_class = error_class
        self.fail_schedule = fail_schedule
        self.error_schedule = error_schedule
        self.stream_calls = 0
        self.user_api_key = None
        self.gen_called = False
        self.gen_stream_called = False
        self.last_model_received = None  # tracks the model kwarg passed to gen/gen_stream
        self.last_messages_received = None  # tracks the messages kwarg at the raw level
        self.last_kwargs_received = None  # tracks the extra gen kwargs at the raw level

    # Track at the raw-method level. _execute_with_fallback applies
    # decorators to the fallback's raw method directly and
    # never calls .gen() / .gen_stream() on it, so a public-method
    # override would not register fallback hops.
    def _raw_gen(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.gen_called = True
        self.last_model_received = model
        self.last_messages_received = messages
        self.last_kwargs_received = dict(kwargs)
        if self.fail_at is not None:
            raise RuntimeError("primary model unavailable")
        return self.responses[0]

    def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.gen_stream_called = True
        self.stream_calls = getattr(self, "stream_calls", 0) + 1
        self.last_model_received = model
        self.last_messages_received = messages
        self.last_kwargs_received = dict(kwargs)
        yielded = 0
        # Per-attempt failure schedule: `fail_schedule[n]` = fail_at value
        # for the n-th call (0-indexed). Falls back to the constant
        # ``fail_at`` when the schedule is exhausted or unset. Lets a test
        # simulate "fail then succeed" without a custom subclass.
        schedule = getattr(self, "fail_schedule", None)
        if schedule is not None and self.stream_calls - 1 < len(schedule):
            local_fail_at = schedule[self.stream_calls - 1]
        else:
            local_fail_at = self.fail_at
        # Per-attempt exception class: same rationale as fail_schedule.
        error_schedule = getattr(self, "error_schedule", None)
        if (
            error_schedule is not None
            and self.stream_calls - 1 < len(error_schedule)
        ):
            local_error_class = error_schedule[self.stream_calls - 1]
        else:
            local_error_class = getattr(self, "error_class", RuntimeError)
        for chunk in self.stream_chunks:
            if local_fail_at is not None and yielded >= local_fail_at:
                raise local_error_class("mid-stream failure")
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

    def test_stream_transport_error_retries_primary_once(
        self, patch_model_utils
    ):
        """Transport error before any yield → retry same primary once,
        succeed, and skip the fallback entirely.

        Covers the Azure Responses-API pattern (Front Door reset within
        seconds, no output produced): the request never reached a
        content-producing state, so the same primary is safe to replay.
        """
        backup = FakeLLM(stream_chunks=["fallback"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = FakeLLM(
            stream_chunks=["ok1", "ok2"],
            backup_models=["backup-model"],
        )
        # First attempt: transport error before yielding. Second attempt:
        # full stream. The fallback should NEVER be called.
        primary.fail_schedule = [0, None]
        primary.error_schedule = [httpx.RemoteProtocolError, RuntimeError]

        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["ok1", "ok2"]
        assert primary.stream_calls == 2
        assert not backup.gen_stream_called

    def test_stream_transport_error_retry_then_fails_uses_fallback(
        self, patch_model_utils
    ):
        """Transport error both times → after retry exhausted, fall back."""
        backup = FakeLLM(stream_chunks=["b1", "b2"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = FakeLLM(
            stream_chunks=["ok1"],
            backup_models=["backup-model"],
        )
        primary.fail_schedule = [0, 0]
        primary.error_schedule = [
            httpx.RemoteProtocolError,
            httpx.RemoteProtocolError,
        ]

        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["b1", "b2"]
        assert primary.stream_calls == 2
        assert backup.gen_stream_called

    def test_stream_transport_error_after_yield_skips_retry(
        self, patch_model_utils
    ):
        """Transport error AFTER a chunk was yielded → don't retry the
        primary (would duplicate delivered content), go straight to
        fallback.
        """
        backup = FakeLLM(stream_chunks=["b1"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = FakeLLM(
            stream_chunks=["ok1", "ok2", "ok3"],
            fail_at=2,  # yields ok1, ok2, then RemoteProtocolError
            error_class=httpx.RemoteProtocolError,
            backup_models=["backup-model"],
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))

        # Primary emitted two chunks, then straight to fallback (no retry).
        assert chunks == ["ok1", "ok2", "b1"]
        assert primary.stream_calls == 1
        assert backup.gen_stream_called

    def test_stream_non_transport_error_skips_retry(self, patch_model_utils):
        """Non-transport errors (e.g. app-level RuntimeError, 4xx) don't
        get the retry — repeating won't help — but fallback still runs."""
        backup = FakeLLM(stream_chunks=["b1"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = FakeLLM(
            stream_chunks=["x"],
            fail_at=0,
            error_class=RuntimeError,
            backup_models=["backup-model"],
        )
        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["b1"]
        assert primary.stream_calls == 1  # NOT retried
        assert backup.gen_stream_called

    def test_stream_transport_error_no_fallback_still_retries(
        self, monkeypatch
    ):
        """Retry logic runs even when no fallback is configured — a
        retryable transport blip should not require a backup to recover.
        """
        monkeypatch.setattr(
            "application.llm.base.settings",
            MagicMock(FALLBACK_LLM_PROVIDER=None),
        )
        primary = FakeLLM(
            stream_chunks=["ok1"],
            backup_models=[],
        )
        primary.fail_schedule = [0, None]
        primary.error_schedule = [httpx.RemoteProtocolError, RuntimeError]

        chunks = list(primary.gen_stream(**CALL_ARGS))

        assert chunks == ["ok1"]
        assert primary.stream_calls == 2

    def test_retry_that_reaches_finish_then_trailing_frame_fails_skips_fallback(
        self, patch_model_utils
    ):
        """The retry may deliver the entire answer, set
        ``_stream_reached_finish``, and then die on a trailing frame
        (usage-only chunk, [DONE]). Without a re-check of the flag in
        the retry's except, we'd fall through to fallback and the user
        would receive the whole answer twice. This test pins the guard.

        Setup: primary attempt 1 fails immediately with a retryable
        transport error → retry runs, streams two chunks AND sets
        ``_stream_reached_finish=True``, then raises on the last frame.
        Expected: the two retry chunks are yielded, the fallback is
        NOT engaged, and the trailing-frame exception is re-raised
        (which the streaming handler treats as non-fatal via its own
        ``_stream_reached_finish`` guard).
        """
        backup = FakeLLM(stream_chunks=["should-not-appear"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )

        # A primary whose retry attempt yields chunks AND flips the
        # finish flag before raising on the trailing frame. Subclassing
        # keeps the fixture stubs untouched for the other tests.
        class FinishThenFailPrimary(FakeLLM):
            def _raw_gen_stream(
                self, baseself, model, messages, stream, tools=None, **kwargs
            ):
                self.stream_calls = getattr(self, "stream_calls", 0) + 1
                if self.stream_calls == 1:
                    # Immediate transport failure to trigger the retry.
                    raise httpx.RemoteProtocolError("initial reset")
                # Retry attempt: yield the full stream, then die on a
                # trailing frame after the finish signal was delivered.
                for chunk in ("a", "b"):
                    yield chunk
                self._stream_reached_finish = True
                raise httpx.RemoteProtocolError("trailing-frame drop")

        primary = FinishThenFailPrimary(
            stream_chunks=[],
            backup_models=["backup-model"],
        )

        # The trailing-frame RemoteProtocolError propagates because the
        # guard re-raises. The handler layer swallows it via its own
        # ``_stream_reached_finish`` check; at the base-LLM layer it's
        # the correct behaviour.
        chunks = []
        with pytest.raises(httpx.RemoteProtocolError, match="trailing-frame"):
            for chunk in primary.gen_stream(**CALL_ARGS):
                chunks.append(chunk)

        assert chunks == ["a", "b"]
        assert primary.stream_calls == 2
        assert not backup.gen_stream_called

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


# Tests — responding-provider tracking (cross-provider fallback handler fix)


class _Google(FakeLLM):
    provider_name = "google"


class _OpenAI(FakeLLM):
    provider_name = "openai"


@pytest.mark.integration
class TestRespondingProviderTracking:
    """The handler that parses a response must follow the model that
    actually produced it. ``BaseLLM`` exposes ``_responding_provider`` so
    the handler layer can re-route ``parse_response`` after a fallback to a
    different-provider model (Google primary -> OpenAI backup), instead of
    silently dropping the backup's tool calls."""

    def test_defaults_to_own_provider_before_any_call(self):
        assert _Google()._responding_provider == "google"

    def test_stream_success_keeps_primary_provider(self):
        primary = _Google(stream_chunks=["a", "b"])
        list(primary.gen_stream(**CALL_ARGS))
        assert primary._responding_provider == "google"

    def test_stream_fallback_records_backup_provider(self, patch_model_utils):
        backup = _OpenAI(stream_chunks=["x"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = _Google(
            stream_chunks=["a"], fail_at=0, backup_models=["backup-model"]
        )
        list(primary.gen_stream(**CALL_ARGS))
        assert primary._responding_provider == "openai"

    def test_gen_success_keeps_primary_provider(self):
        primary = _Google(responses=["ok"])
        primary.gen(**CALL_ARGS)
        assert primary._responding_provider == "google"

    def test_gen_fallback_records_backup_provider(self, patch_model_utils):
        backup = _OpenAI(responses=["backup ok"])
        patch_model_utils(
            get_provider=lambda m, **_kwargs: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = _Google(fail_at=0, backup_models=["backup-model"])
        primary.gen(**CALL_ARGS)
        assert primary._responding_provider == "openai"


# Tests — fallback payload size gate


@pytest.mark.integration
class TestFallbackPayloadSizeGate:
    """A payload that cannot fit the fallback's context window must skip the
    fallback attempt (it would be a guaranteed second rejection) and
    propagate the primary's error instead."""

    def _primary_with_backup(self, patch_model_utils, backup):
        patch_model_utils(
            get_provider=lambda mid, **_kw: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        return FakeLLM(fail_at=0, backup_models=["backup-model"])

    BIG_ARGS = dict(
        model="test-model",
        messages=[{"role": "user", "content": "word " * 300}],
    )

    def test_gen_skips_fallback_when_payload_cannot_fit(
        self, monkeypatch, patch_model_utils
    ):
        backup = FakeLLM(responses=["backup ok"])
        primary = self._primary_with_backup(patch_model_utils, backup)
        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit",
            lambda mid, user_id=None: 10,
        )
        with pytest.raises(RuntimeError, match="primary model unavailable"):
            primary.gen(**self.BIG_ARGS)
        assert backup.gen_called is False

    def test_stream_skips_fallback_when_payload_cannot_fit(
        self, monkeypatch, patch_model_utils
    ):
        backup = FakeLLM(stream_chunks=["backup chunk"])
        primary = self._primary_with_backup(patch_model_utils, backup)
        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit",
            lambda mid, user_id=None: 10,
        )
        with pytest.raises(RuntimeError, match="mid-stream failure"):
            list(primary.gen_stream(**self.BIG_ARGS))
        assert backup.gen_stream_called is False

    def test_fallback_proceeds_when_payload_fits(
        self, monkeypatch, patch_model_utils
    ):
        backup = FakeLLM(responses=["backup ok"])
        primary = self._primary_with_backup(patch_model_utils, backup)
        monkeypatch.setattr(
            "application.core.model_utils.get_token_limit",
            lambda mid, user_id=None: 100000,
        )
        assert primary.gen(**self.BIG_ARGS) == "backup ok"
        assert backup.gen_called is True

    def test_estimation_failure_never_blocks_fallback(
        self, monkeypatch, patch_model_utils
    ):
        backup = FakeLLM(responses=["backup ok"])
        primary = self._primary_with_backup(patch_model_utils, backup)

        def boom(*a, **kw):
            raise ValueError("estimator broken")

        monkeypatch.setattr("application.usage._count_prompt_tokens", boom)
        assert primary.gen(**self.BIG_ARGS) == "backup ok"
        assert backup.gen_called is True


# Tests — no fallback restream after the primary delivered its finish signal


@pytest.mark.integration
class TestNoRestreamAfterFinish:
    """A trailing-frame failure (between the finish chunk and stream end)
    must NOT restream the already-delivered answer from the fallback."""

    class FinishThenFailLLM(FakeLLM):
        def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kwargs):
            self.gen_stream_called = True
            yield "the full answer"
            # Provider marked the stream finished (finish_reason arrived)...
            self._stream_reached_finish = True
            # ...then the trailing usage/[DONE] frame dies.
            raise RuntimeError("connection reset in trailing frame")

    def test_trailing_frame_failure_skips_fallback(self, patch_model_utils):
        backup = FakeLLM(stream_chunks=["fallback chunk"])
        patch_model_utils(
            get_provider=lambda mid, **_kw: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = self.FinishThenFailLLM(backup_models=["backup-model"])

        received = []
        with pytest.raises(RuntimeError, match="trailing frame"):
            for chunk in primary.gen_stream(**CALL_ARGS):
                received.append(chunk)

        assert received == ["the full answer"]
        assert backup.gen_stream_called is False

    def test_pre_finish_failure_still_falls_back(self, patch_model_utils):
        backup = FakeLLM(stream_chunks=["fallback chunk"])
        patch_model_utils(
            get_provider=lambda mid, **_kw: "openai",
            get_api_key=lambda p: "k",
            create_llm=lambda type, **kw: backup,
        )
        primary = FakeLLM(fail_at=0, backup_models=["backup-model"])
        out = list(primary.gen_stream(**CALL_ARGS))
        assert out == ["fallback chunk"]
        assert backup.gen_stream_called is True


# Tests — fallback message reshaping (parts arrays prepared for the primary)
#
# ``prepare_messages_with_attachments`` runs against the *primary* model, so
# by the time a fallback engages the messages can carry ``file`` parts (whose
# Files-API ids only the primary's endpoint+credential can resolve) and
# ``image_url`` parts a non-vision fallback 4xxes on. These tests pin the
# handoff contract: the fallback must receive content it can accept.


def _parts_messages():
    return [
        {"role": "system", "content": "You are helpful."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "summarize the attached report"},
                {"type": "file", "file": {"file_id": "assistant-abc123"}},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAAA"},
                },
            ],
        },
    ]


ATTACHMENTS = [
    {"id": "att-1", "filename": "report.pdf", "content": "EXTRACTED REPORT TEXT"}
]


class VisionFakeLLM(FakeLLM):
    def get_supported_attachment_types(self):
        return ["image/png", "image/jpeg"]


class SharedEndpointPdfFakeLLM(FakeLLM):
    def get_supported_attachment_types(self):
        return ["application/pdf", "image/png"]

    def _endpoint_scope(self):
        return "scope-shared"


@pytest.mark.integration
class TestFallbackMessageReshaping:

    def _run_stream(self, primary, messages, attachments):
        return list(
            primary.gen_stream(
                model="test-model",
                messages=messages,
                _usage_attachments=attachments,
            )
        )

    def test_stream_fallback_gets_flattened_string_content(self):
        fallback = FakeLLM(stream_chunks=["fb"])
        primary = FakeLLM(fail_at=0)
        primary._fallback_llm = fallback
        original = _parts_messages()
        snapshot = copy.deepcopy(original)

        chunks = self._run_stream(primary, original, ATTACHMENTS)

        assert chunks == ["fb"]
        received = fallback.last_messages_received
        assert received[0] == {"role": "system", "content": "You are helpful."}
        user_content = received[1]["content"]
        assert isinstance(user_content, str)
        assert "summarize the attached report" in user_content
        assert "EXTRACTED REPORT TEXT" in user_content
        assert "Image attachment omitted" in user_content
        # The primary-scoped Files-API id must never reach another endpoint.
        assert "assistant-abc123" not in user_content
        # The primary's own message array is not mutated.
        assert original == snapshot

    def test_stream_vision_fallback_keeps_image_parts(self):
        fallback = VisionFakeLLM(stream_chunks=["fb"])
        primary = FakeLLM(fail_at=0)
        primary._fallback_llm = fallback

        self._run_stream(primary, _parts_messages(), ATTACHMENTS)

        user_content = fallback.last_messages_received[1]["content"]
        assert isinstance(user_content, list)
        types = [part["type"] for part in user_content]
        assert "image_url" in types
        assert "file" not in types
        joined = " ".join(
            part.get("text", "") for part in user_content if part["type"] == "text"
        )
        assert "EXTRACTED REPORT TEXT" in joined

    def test_stream_same_endpoint_pdf_fallback_keeps_file_parts(self):
        fallback = SharedEndpointPdfFakeLLM(stream_chunks=["fb"])
        primary = SharedEndpointPdfFakeLLM(fail_at=0)
        primary._fallback_llm = fallback

        self._run_stream(primary, _parts_messages(), ATTACHMENTS)

        user_content = fallback.last_messages_received[1]["content"]
        assert isinstance(user_content, list)
        assert {"type": "file", "file": {"file_id": "assistant-abc123"}} in user_content

    def test_stream_file_part_without_extracted_content_becomes_note(self):
        fallback = FakeLLM(stream_chunks=["fb"])
        primary = FakeLLM(fail_at=0)
        primary._fallback_llm = fallback

        self._run_stream(primary, _parts_messages(), attachments=None)

        user_content = fallback.last_messages_received[1]["content"]
        assert isinstance(user_content, str)
        assert "could not be included" in user_content
        assert "assistant-abc123" not in user_content

    def test_stream_string_messages_pass_through_unchanged(self):
        fallback = FakeLLM(stream_chunks=["fb"])
        primary = FakeLLM(fail_at=0)
        primary._fallback_llm = fallback
        messages = [{"role": "user", "content": "plain text"}]

        self._run_stream(primary, messages, ATTACHMENTS)

        assert fallback.last_messages_received == messages

    def test_gen_fallback_gets_flattened_string_content(self):
        fallback = FakeLLM(responses=["fb answer"])
        primary = FakeLLM(fail_at=0)
        primary._fallback_llm = fallback

        result = primary.gen(
            model="test-model",
            messages=_parts_messages(),
            _usage_attachments=ATTACHMENTS,
        )

        assert result == "fb answer"
        user_content = fallback.last_messages_received[1]["content"]
        assert isinstance(user_content, str)
        assert "EXTRACTED REPORT TEXT" in user_content
        assert "assistant-abc123" not in user_content


# Tests — cross-provider structured-output adaptation
#
# Structured output is provider-specific: OpenAI-wire classes take
# ``response_format``, Google takes ``response_schema``. Forwarding the
# primary's kwarg verbatim either loses enforcement silently (Google swallows
# ``response_format`` in ``**kwargs``) or raises TypeError inside the OpenAI
# SDK (``response_schema`` is not a Chat-Completions param) — which turned the
# fallback into no fallback at all for every structured node.


SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "score": {"type": "integer"},
    },
    "required": ["answer"],
}


class _OpenAIWireFake(FakeLLM):
    """OpenAI-wire double: real declaration + real preparer, fake transport."""

    provider_name = "openai"
    structured_output_kwarg = "response_format"
    prepare_structured_output_format = OpenAILLM.prepare_structured_output_format

    def _supports_structured_output(self):
        return True


class _GoogleFake(FakeLLM):
    """Google double: real declaration + real preparer, fake transport."""

    provider_name = "google"
    structured_output_kwarg = "response_schema"
    prepare_structured_output_format = GoogleLLM.prepare_structured_output_format

    def _supports_structured_output(self):
        return True


class _AnthropicFake(FakeLLM):
    """Provider with no structured-output kwarg at all."""

    provider_name = "anthropic"


def _openai_envelope(schema=SCHEMA, strict=True):
    """An OpenAI ``response_format`` built the way a provider would."""
    return OpenAILLM.prepare_structured_output_format(
        _OpenAIWireFake(), schema, strict=strict
    )


def _google_schema(schema=SCHEMA):
    """The Google ``response_schema`` conversion of ``schema``."""
    return GoogleLLM.prepare_structured_output_format(_GoogleFake(), schema)


@pytest.mark.unit
class TestStructuredOutputDeclarations:
    """One source of truth: the kwarg name lives on the LLM class."""

    def test_openai_declares_response_format(self):
        assert OpenAILLM.structured_output_kwarg == "response_format"

    def test_openai_subclasses_inherit_the_declaration(self):
        assert GroqLLM.structured_output_kwarg == "response_format"

    def test_google_declares_response_schema(self):
        assert GoogleLLM.structured_output_kwarg == "response_schema"

    def test_anthropic_declares_nothing(self):
        assert AnthropicLLM.structured_output_kwarg is None

    def test_base_declares_nothing(self):
        assert BaseLLM.structured_output_kwarg is None

    def test_openai_prepare_records_source(self):
        llm = _OpenAIWireFake()
        llm.prepare_structured_output_format(SCHEMA, strict=False)
        assert llm._structured_output_source == (SCHEMA, False)

    def test_google_prepare_records_source(self):
        llm = _GoogleFake()
        llm.prepare_structured_output_format(SCHEMA)
        assert llm._structured_output_source == (SCHEMA, True)

    def test_empty_schema_clears_recorded_source(self):
        llm = _OpenAIWireFake()
        llm.prepare_structured_output_format(SCHEMA)
        llm.prepare_structured_output_format(None)
        assert llm._structured_output_source is None

    def test_base_records_nothing_by_default(self):
        assert FakeLLM()._structured_output_source is None


@pytest.mark.unit
class TestAdaptStructuredOutputKwargs:
    """Unit-level contract of the adapter itself."""

    def test_no_structured_kwargs_returns_equal_copy(self):
        primary = _OpenAIWireFake()
        kwargs = {"model": "m", "messages": [], "temperature": 0.2}

        adapted = primary._adapt_structured_output_kwargs(_GoogleFake(), kwargs)

        assert adapted == kwargs
        assert adapted is not kwargs

    def test_does_not_mutate_the_callers_kwargs(self):
        primary = _OpenAIWireFake()
        primary.prepare_structured_output_format(SCHEMA)
        kwargs = {"model": "m", "response_format": _openai_envelope()}
        snapshot = copy.deepcopy(kwargs)

        primary._adapt_structured_output_kwargs(_GoogleFake(), kwargs)

        assert kwargs == snapshot

    def test_recovers_schema_from_envelope_when_no_source_recorded(self):
        """A hand-built ``response_format`` (research_agent) never went through
        ``prepare_structured_output_format``, so nothing was recorded — the raw
        schema is still readable out of the OpenAI envelope."""
        primary = _OpenAIWireFake()
        assert primary._structured_output_source is None

        adapted = primary._adapt_structured_output_kwargs(
            _GoogleFake(model_id="gemini-2.5-flash"),
            {"model": "m", "response_format": _openai_envelope()},
        )

        assert "response_format" not in adapted
        assert adapted["response_schema"]["type"] == "OBJECT"
        assert set(adapted["response_schema"]["properties"]) == {"answer", "score"}
        assert adapted["model"] == "m"

    def test_google_schema_without_source_is_dropped(self, caplog):
        """Google's conversion is lossy/type-mapped — not reversible."""
        primary = _GoogleFake()
        assert primary._structured_output_source is None

        with caplog.at_level(logging.WARNING, logger="application.llm.base"):
            adapted = primary._adapt_structured_output_kwargs(
                _OpenAIWireFake(model_id="gpt-4o-mini"),
                {"model": "m", "response_schema": _google_schema()},
            )

        assert "response_schema" not in adapted
        assert "response_format" not in adapted
        assert "gpt-4o-mini" in caplog.text

    def test_fallback_without_structured_support_drops_and_warns(self, caplog):
        primary = _OpenAIWireFake()
        primary.prepare_structured_output_format(SCHEMA)
        fallback = _GoogleFake(model_id="gemini-2.5-flash")
        fallback._supports_structured_output = lambda: False

        with caplog.at_level(logging.WARNING, logger="application.llm.base"):
            adapted = primary._adapt_structured_output_kwargs(
                fallback, {"model": "m", "response_format": _openai_envelope()}
            )

        assert "response_format" not in adapted
        assert "response_schema" not in adapted
        assert "cannot enforce structured output" in caplog.text

    def test_non_callable_support_flag_is_honored(self):
        """Test doubles sometimes set the capability as a plain bool."""
        primary = _OpenAIWireFake()
        primary.prepare_structured_output_format(SCHEMA)
        fallback = _GoogleFake(model_id="gemini-2.5-flash")
        fallback._supports_structured_output = False

        adapted = primary._adapt_structured_output_kwargs(
            fallback, {"response_format": _openai_envelope()}
        )

        assert adapted == {}

    def test_preparer_returning_none_drops_the_kwarg(self, caplog):
        class _NullPreparer(_GoogleFake):
            def prepare_structured_output_format(self, json_schema, strict=True):
                return None

        primary = _OpenAIWireFake()
        primary.prepare_structured_output_format(SCHEMA)

        with caplog.at_level(logging.WARNING, logger="application.llm.base"):
            adapted = primary._adapt_structured_output_kwargs(
                _NullPreparer(model_id="gemini-2.5-flash"),
                {"response_format": _openai_envelope()},
            )

        assert adapted == {}
        assert "cannot enforce structured output" in caplog.text

    def test_preparer_raising_never_breaks_the_fallback(self, caplog):
        class _ExplodingPreparer(_GoogleFake):
            def prepare_structured_output_format(self, json_schema, strict=True):
                raise ValueError("boom")

        primary = _OpenAIWireFake()
        primary.prepare_structured_output_format(SCHEMA)

        with caplog.at_level(logging.WARNING, logger="application.llm.base"):
            adapted = primary._adapt_structured_output_kwargs(
                _ExplodingPreparer(model_id="gemini-2.5-flash"),
                {"response_format": _openai_envelope()},
            )

        assert adapted == {}
        assert "Failed to prepare structured output" in caplog.text

    def test_strict_flag_survives_the_translation(self):
        primary = _GoogleFake()
        primary.prepare_structured_output_format(SCHEMA)
        primary._structured_output_source = (SCHEMA, False)

        adapted = primary._adapt_structured_output_kwargs(
            _OpenAIWireFake(model_id="gpt-4o-mini"),
            {"response_schema": _google_schema()},
        )

        assert adapted["response_format"]["json_schema"]["strict"] is False
        # strict=False leaves the schema untouched (no additionalProperties).
        assert "additionalProperties" not in (
            adapted["response_format"]["json_schema"]["schema"]
        )


@pytest.mark.integration
class TestCrossProviderStructuredOutputFallback:
    """End-to-end through ``gen`` / ``gen_stream``: the backup must receive
    the schema in *its own* provider's kwarg."""

    def test_gen_openai_primary_google_fallback_gets_response_schema(self):
        primary = _OpenAIWireFake(fail_at=0)
        fallback = _GoogleFake(responses=["fb"], model_id="gemini-2.5-flash")
        primary._fallback_llm = fallback
        response_format = primary.prepare_structured_output_format(SCHEMA)

        result = primary.gen(**CALL_ARGS, response_format=response_format)

        assert result == "fb"
        assert fallback.last_kwargs_received["response_schema"] == _google_schema()
        assert "response_format" not in fallback.last_kwargs_received

    def test_stream_openai_primary_google_fallback_gets_response_schema(self):
        primary = _OpenAIWireFake(stream_chunks=["x"], fail_at=0)
        fallback = _GoogleFake(stream_chunks=["fb"], model_id="gemini-2.5-flash")
        primary._fallback_llm = fallback
        response_format = primary.prepare_structured_output_format(SCHEMA)

        chunks = list(primary.gen_stream(**CALL_ARGS, response_format=response_format))

        assert chunks == ["fb"]
        assert fallback.last_kwargs_received["response_schema"] == _google_schema()
        assert "response_format" not in fallback.last_kwargs_received

    def test_gen_google_primary_openai_fallback_gets_response_format(self):
        primary = _GoogleFake(fail_at=0)
        fallback = _OpenAIWireFake(responses=["fb"], model_id="gpt-4o-mini")
        primary._fallback_llm = fallback
        response_schema = primary.prepare_structured_output_format(SCHEMA)

        result = primary.gen(**CALL_ARGS, response_schema=response_schema)

        assert result == "fb"
        received = fallback.last_kwargs_received
        assert "response_schema" not in received
        assert received["response_format"]["type"] == "json_schema"
        assert set(received["response_format"]["json_schema"]["schema"]["properties"]) == {
            "answer",
            "score",
        }

    def test_stream_google_primary_openai_fallback_gets_response_format(self):
        primary = _GoogleFake(stream_chunks=["x"], fail_at=0)
        fallback = _OpenAIWireFake(stream_chunks=["fb"], model_id="gpt-4o-mini")
        primary._fallback_llm = fallback
        response_schema = primary.prepare_structured_output_format(SCHEMA)

        chunks = list(primary.gen_stream(**CALL_ARGS, response_schema=response_schema))

        assert chunks == ["fb"]
        received = fallback.last_kwargs_received
        assert "response_schema" not in received
        assert received["response_format"]["type"] == "json_schema"

    def test_same_wire_family_passes_response_format_verbatim(self):
        """OpenAI -> openai_compatible: no re-preparation, byte-identical."""
        primary = _OpenAIWireFake(fail_at=0)
        fallback = _OpenAIWireFake(responses=["fb"], model_id="qwen3-4b")
        primary._fallback_llm = fallback
        response_format = primary.prepare_structured_output_format(SCHEMA)

        primary.gen(**CALL_ARGS, response_format=response_format)

        assert fallback.last_kwargs_received["response_format"] is response_format
        assert "response_schema" not in fallback.last_kwargs_received

    def test_same_wire_family_passes_response_schema_verbatim(self):
        primary = _GoogleFake(fail_at=0)
        fallback = _GoogleFake(responses=["fb"], model_id="gemini-2.5-pro")
        primary._fallback_llm = fallback
        response_schema = primary.prepare_structured_output_format(SCHEMA)

        primary.gen(**CALL_ARGS, response_schema=response_schema)

        assert fallback.last_kwargs_received["response_schema"] is response_schema
        assert "response_format" not in fallback.last_kwargs_received

    def test_json_object_mode_kept_within_the_openai_family(self):
        primary = _OpenAIWireFake(fail_at=0)
        fallback = _OpenAIWireFake(responses=["fb"], model_id="qwen3-4b")
        primary._fallback_llm = fallback

        primary.gen(**CALL_ARGS, response_format={"type": "json_object"})

        assert fallback.last_kwargs_received["response_format"] == {
            "type": "json_object"
        }

    def test_json_object_mode_dropped_for_google_fallback(self):
        """Google has no json_object equivalent wired — drop, don't crash."""
        primary = _OpenAIWireFake(fail_at=0)
        fallback = _GoogleFake(responses=["fb"], model_id="gemini-2.5-flash")
        primary._fallback_llm = fallback

        result = primary.gen(**CALL_ARGS, response_format={"type": "json_object"})

        assert result == "fb"
        assert "response_format" not in fallback.last_kwargs_received
        assert "response_schema" not in fallback.last_kwargs_received

    def test_json_object_mode_dropped_for_google_fallback_streaming(self):
        primary = _OpenAIWireFake(stream_chunks=["x"], fail_at=0)
        fallback = _GoogleFake(stream_chunks=["fb"], model_id="gemini-2.5-flash")
        primary._fallback_llm = fallback

        chunks = list(
            primary.gen_stream(**CALL_ARGS, response_format={"type": "json_object"})
        )

        assert chunks == ["fb"]
        assert "response_format" not in fallback.last_kwargs_received
        assert "response_schema" not in fallback.last_kwargs_received

    def test_anthropic_fallback_gets_neither_kwarg(self):
        """Anthropic has no structured-output kwarg: unstructured, not broken."""
        primary = _OpenAIWireFake(fail_at=0)
        fallback = _AnthropicFake(responses=["fb"], model_id="claude-sonnet-4")
        primary._fallback_llm = fallback
        response_format = primary.prepare_structured_output_format(SCHEMA)

        result = primary.gen(**CALL_ARGS, response_format=response_format)

        assert result == "fb"
        assert fallback.last_kwargs_received == {}

    def test_anthropic_fallback_gets_neither_kwarg_streaming(self):
        primary = _GoogleFake(stream_chunks=["x"], fail_at=0)
        fallback = _AnthropicFake(stream_chunks=["fb"], model_id="claude-sonnet-4")
        primary._fallback_llm = fallback
        response_schema = primary.prepare_structured_output_format(SCHEMA)

        chunks = list(primary.gen_stream(**CALL_ARGS, response_schema=response_schema))

        assert chunks == ["fb"]
        assert fallback.last_kwargs_received == {}

    def test_unrelated_gen_kwargs_are_forwarded_untouched(self):
        primary = _OpenAIWireFake(fail_at=0)
        fallback = _GoogleFake(responses=["fb"], model_id="gemini-2.5-flash")
        primary._fallback_llm = fallback
        response_format = primary.prepare_structured_output_format(SCHEMA)

        primary.gen(
            **CALL_ARGS, response_format=response_format, temperature=0.3
        )

        assert fallback.last_kwargs_received["temperature"] == 0.3


# The OpenAI SDK's ``chat.completions.create`` has an explicit keyword
# signature: a forwarded ``response_schema`` raises TypeError before the
# request is even built, so the Google -> OpenAI hop died with "Fallback LLM
# also failed". These tests drive the *real* ``OpenAILLM`` raw methods against
# a client double with the same strictness.


class _StrictChatCompletions:
    """Chat-Completions double that rejects kwargs the real SDK rejects."""

    _ACCEPTED = {
        "model",
        "messages",
        "stream",
        "stream_options",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "temperature",
        "top_p",
        "max_completion_tokens",
        "reasoning_effort",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stop",
        "n",
        "user",
    }

    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        unexpected = sorted(set(kwargs) - self._ACCEPTED)
        if unexpected:
            raise TypeError(
                f"Completions.create() got an unexpected keyword argument "
                f"'{unexpected[0]}'"
            )
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return [
                _stream_line(content="fb"),
                _stream_line(finish_reason="stop"),
            ]
        message = types.SimpleNamespace(content="fb answer", tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)], usage=None
        )


def _stream_line(content=None, finish_reason=None):
    delta = types.SimpleNamespace(
        content=content, reasoning_content=None, tool_calls=None
    )
    choice = types.SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice], usage=None)


def _strict_openai_llm():
    llm = OpenAILLM(api_key="sk-test", user_api_key=None, model_id="gpt-4o-mini")
    llm.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_StrictChatCompletions())
    )
    return llm


@pytest.mark.integration
class TestRealOpenAIFallbackRejectsForeignKwargs:

    def test_gen_google_primary_real_openai_fallback_does_not_typeerror(self):
        primary = _GoogleFake(fail_at=0)
        fallback = _strict_openai_llm()
        primary._fallback_llm = fallback
        response_schema = primary.prepare_structured_output_format(SCHEMA)

        result = primary.gen(**CALL_ARGS, response_schema=response_schema)

        assert result == "fb answer"
        sent = fallback.client.chat.completions.last_kwargs
        assert "response_schema" not in sent
        assert sent["response_format"]["type"] == "json_schema"

    def test_stream_google_primary_real_openai_fallback_does_not_typeerror(self):
        primary = _GoogleFake(stream_chunks=["x"], fail_at=0)
        fallback = _strict_openai_llm()
        primary._fallback_llm = fallback
        response_schema = primary.prepare_structured_output_format(SCHEMA)

        chunks = list(primary.gen_stream(**CALL_ARGS, response_schema=response_schema))

        assert chunks == ["fb"]
        sent = fallback.client.chat.completions.last_kwargs
        assert "response_schema" not in sent
        assert sent["response_format"]["type"] == "json_schema"
