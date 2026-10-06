"""Concurrent first use of the model registry right after a process starts.

``ModelRegistry`` is a per-process singleton that loads its catalog on first
use. Two requests that arrive together after a restart both reach that first
use. These tests hold every thread at a barrier, slow the catalog load down so
the threads overlap inside it, and check what each request then sees and which
key it would send to which endpoint.

The failure they pin down was seen in a benchmark: one request observed an
empty registry, so it had no default model, fell back to ``LLM_PROVIDER``
(``openai_compatible``) with the generic ``API_KEY`` (a DeepSeek key) and no
endpoint, and the OpenAI client sent that key to ``api.openai.com``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import pytest

from docsgpt.core import model_registry as registry_module
from docsgpt.core.model_registry import ModelRegistry
from docsgpt.core.model_settings import AvailableModel, ModelProvider
from docsgpt.core.model_yaml import BUILTIN_MODELS_DIR, load_model_yamls
from docsgpt.core.settings import settings

THREADS = 8
LOAD_DELAY_SECONDS = 0.2
DEEPSEEK_KEY = "sk-deepseek-benchmark-key"
DEEPSEEK_URL = "https://api.deepseek.com/v1"

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
def _isolated_registry(monkeypatch):
    """Start every test from an unloaded registry and no provider keys."""
    for name in _LLM_SETTINGS:
        monkeypatch.setattr(settings, name, None)
    for catalog in load_model_yamls([BUILTIN_MODELS_DIR]):
        if catalog.api_key_env:
            monkeypatch.delenv(catalog.api_key_env, raising=False)
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


def _slow_catalog_load(monkeypatch, loader) -> List[int]:
    """Make the catalog load take ``LOAD_DELAY_SECONDS`` and count the loads."""
    calls: List[int] = []

    def slow(settings_obj):
        calls.append(1)
        time.sleep(LOAD_DELAY_SECONDS)
        return loader(settings_obj)

    monkeypatch.setattr(registry_module, "load_catalog_models", slow)
    return calls


def _run_together(target) -> List[Dict[str, Any]]:
    """Run ``target`` on ``THREADS`` threads released together by a barrier."""
    barrier = threading.Barrier(THREADS)
    results: List[Dict[str, Any]] = []
    errors: List[BaseException] = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            outcome = target()
        except BaseException as exc:  # noqa: BLE001 - reported below
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert len(results) == THREADS
    return results


@pytest.mark.unit
class TestConcurrentFirstAccess:
    def test_no_request_sees_an_empty_or_partial_registry(self, monkeypatch):
        catalog = {
            f"model-{i}": AvailableModel(
                id=f"model-{i}", provider=ModelProvider.OPENAI, display_name=f"Model {i}"
            )
            for i in range(5)
        }
        monkeypatch.setattr(settings, "LLM_NAME", "model-3")
        calls = _slow_catalog_load(monkeypatch, lambda _settings: dict(catalog))

        def first_request():
            registry = ModelRegistry.get_instance()
            return {
                "registry": registry,
                "models": len(registry.models),
                "default": registry.default_model_id,
            }

        results = _run_together(first_request)

        observed = sorted((r["models"], r["default"]) for r in results)
        assert observed == [(5, "model-3")] * THREADS, observed
        assert len({id(r["registry"]) for r in results}) == 1
        assert len(calls) == 1, f"catalog loaded {len(calls)} times"

    def test_a_failed_load_is_not_published_and_the_next_call_retries(self, monkeypatch):
        attempts: List[int] = []

        def flaky(_settings):
            attempts.append(1)
            if len(attempts) == 1:
                raise ValueError("bad yaml")
            return {
                "m": AvailableModel(id="m", provider=ModelProvider.OPENAI, display_name="M"),
            }

        monkeypatch.setattr(registry_module, "load_catalog_models", flaky)

        with pytest.raises(ValueError, match="bad yaml"):
            ModelRegistry.get_instance()
        assert ModelRegistry._instance is None

        registry = ModelRegistry.get_instance()
        assert list(registry.models) == ["m"]
        assert registry.default_model_id == "m"

    def test_invalidate_user_during_first_load_does_not_fail(self, monkeypatch):
        started = threading.Event()
        release = threading.Event()

        def blocking(_settings):
            started.set()
            release.wait(5)
            return {}

        monkeypatch.setattr(registry_module, "load_catalog_models", blocking)
        monkeypatch.setattr(ModelRegistry, "_read_user_version", classmethod(lambda cls, user_id: None))
        loader = threading.Thread(target=ModelRegistry.get_instance)
        loader.start()
        try:
            assert started.wait(5)
            ModelRegistry.invalidate_user("user-1")
        finally:
            release.set()
            loader.join(5)
        assert ModelRegistry.get_instance().models == {}


@pytest.mark.unit
class TestConcurrentFirstRequestCredentials:
    """The benchmark configuration, resolved the way a chat request resolves it."""

    def _configure_benchmark(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_PROVIDER", "openai_compatible")
        monkeypatch.setattr(settings, "LLM_NAME", "deepseek-v4-flash")
        monkeypatch.setattr(settings, "API_KEY", DEEPSEEK_KEY)
        monkeypatch.setenv("DEEPSEEK_API_KEY", DEEPSEEK_KEY)

    def test_every_concurrent_first_request_sends_the_key_to_its_own_provider(self, monkeypatch):
        from docsgpt.core.model_utils import (
            get_api_key_for_provider,
            get_default_model_id,
            get_provider_from_model_id,
        )
        from docsgpt.llm.llm_creator import LLMCreator

        self._configure_benchmark(monkeypatch)
        _slow_catalog_load(monkeypatch, registry_module.load_catalog_models)

        def first_chat_request():
            # Mirrors StreamProcessor: default model, its provider, that
            # provider's key, then the LLM.
            registry = ModelRegistry.get_instance()
            seen_models = len(registry.models)
            model_id = get_default_model_id()
            provider = get_provider_from_model_id(model_id) if model_id else settings.LLM_PROVIDER
            api_key = get_api_key_for_provider(provider or settings.LLM_PROVIDER)
            try:
                llm = LLMCreator.create_llm(
                    provider or settings.LLM_PROVIDER,
                    api_key=api_key,
                    user_api_key=None,
                    decoded_token=None,
                    model_id=model_id,
                )
            except ValueError as exc:
                return {"models": seen_models, "model_id": model_id, "refused": str(exc)}
            return {
                "models": seen_models,
                "model_id": model_id,
                "key": llm.api_key,
                "url": llm._effective_base_url,
            }

        results = _run_together(first_chat_request)

        empty = [r for r in results if r["models"] == 0 or r["model_id"] is None]
        assert not empty, f"requests saw an empty registry: {empty}"
        mismatched = [r for r in results if r.get("key") == DEEPSEEK_KEY and r.get("url") != DEEPSEEK_URL]
        assert not mismatched, f"the DeepSeek key went to another endpoint: {mismatched}"
        assert all(
            (r.get("model_id"), r.get("key"), r.get("url")) == ("deepseek-v4-flash", DEEPSEEK_KEY, DEEPSEEK_URL)
            for r in results
        ), results
