"""Tests for docsgpt/pricing.py and the per-million catalog fields."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from docsgpt import pricing
from docsgpt.core.model_settings import ModelCapabilities
from docsgpt.core.model_yaml import (
    BUILTIN_MODELS_DIR,
    ModelYAMLError,
    load_model_yamls,
)
from docsgpt.pricing import ModelRates, compute_cost_usd, cost_from_rates


def _registry(**models):
    entries = {k: SimpleNamespace(capabilities=v) for k, v in models.items()}
    return SimpleNamespace(models=entries)


@pytest.fixture
def priced_registry():
    caps = ModelCapabilities(
        input_cost_per_million=2.0,
        output_cost_per_million=10.0,
        cached_input_cost_per_million=0.2,
        cache_write_cost_per_million=2.5,
    )
    bare = ModelCapabilities()
    with patch(
        "docsgpt.core.model_registry.ModelRegistry.get_instance",
        return_value=_registry(priced=caps, bare=bare),
    ):
        yield


@pytest.mark.unit
class TestCostFromRates:
    def test_prompt_and_generated(self):
        rates = ModelRates(prompt=2.0, generated=10.0)
        assert cost_from_rates(rates, 1_000_000, 500_000) == pytest.approx(7.0)

    def test_cache_bins_use_their_rates(self):
        rates = ModelRates(prompt=2.0, generated=10.0, cached_input=0.2, cache_write=2.5)
        cost = cost_from_rates(rates, 1000, 0, cached_tokens=600, cache_write_tokens=100)
        assert cost == pytest.approx((300 * 2.0 + 600 * 0.2 + 100 * 2.5) / 1e6)

    def test_missing_cache_rates_bill_at_prompt_rate(self):
        rates = ModelRates(prompt=2.0, generated=10.0)
        assert cost_from_rates(rates, 1000, 0, cached_tokens=900) == pytest.approx(1000 * 2.0 / 1e6)

    def test_cache_bins_clamped_to_prompt_total(self):
        rates = ModelRates(prompt=2.0, generated=0.0, cached_input=0.0, cache_write=0.0)
        assert cost_from_rates(rates, 100, 0, cached_tokens=5000, cache_write_tokens=5000) == 0.0
        assert cost_from_rates(rates, 100, 0, cached_tokens=-5) == pytest.approx(100 * 2.0 / 1e6)

    def test_none_and_negative_counts(self):
        rates = ModelRates(prompt=2.0, generated=10.0)
        assert cost_from_rates(rates, None, -3, None, None) == 0.0


@pytest.mark.unit
class TestComputeCost:
    def test_priced_model(self, priced_registry):
        assert compute_cost_usd("priced", 1_000_000, 0) == pytest.approx(2.0)

    @pytest.mark.parametrize("model", ["bare", "unknown", None])
    def test_unpriced_model_is_free_without_fallback(self, priced_registry, model):
        with patch.object(pricing.settings, "QUOTA_UNPRICED_RATE_PER_MILLION", None):
            assert compute_cost_usd(model, 1_000_000, 1_000_000) == 0.0
            assert pricing.is_priced(model) is False

    def test_unpriced_model_uses_fallback(self, priced_registry):
        with patch.object(pricing.settings, "QUOTA_UNPRICED_RATE_PER_MILLION", [0.5, 1.5]):
            assert compute_cost_usd("bare", 1_000_000, 1_000_000) == pytest.approx(2.0)
            assert pricing.is_priced("bare") is True


@pytest.mark.unit
class TestCatalogFields:
    def _load(self, tmp_path, body):
        (tmp_path / "p.yaml").write_text(body)
        return load_model_yamls([tmp_path])[0].models[0].capabilities

    def test_per_million_fields(self, tmp_path):
        caps = self._load(
            tmp_path,
            "provider: openai\nmodels:\n  - id: m\n    input_cost_per_million: 3\n"
            "    output_cost_per_million: 15\n    cached_input_cost_per_million: 0.3\n",
        )
        assert (caps.input_cost_per_million, caps.output_cost_per_million) == (3, 15)
        assert caps.cached_input_cost_per_million == 0.3
        assert caps.cache_write_cost_per_million is None

    def test_per_token_alias_is_scaled(self, tmp_path):
        caps = self._load(
            tmp_path,
            "provider: openai\ndefaults:\n  input_cost_per_token: 0.000003\n"
            "models:\n  - id: m\n    output_cost_per_token: 0.000015\n",
        )
        assert caps.input_cost_per_million == pytest.approx(3.0)
        assert caps.output_cost_per_million == pytest.approx(15.0)

    def test_both_spellings_rejected(self, tmp_path):
        with pytest.raises(ModelYAMLError):
            self._load(
                tmp_path,
                "provider: openai\nmodels:\n  - id: m\n    input_cost_per_token: 0.1\n"
                "    input_cost_per_million: 1\n",
            )

    def test_negative_rate_rejected(self, tmp_path):
        with pytest.raises(ModelYAMLError):
            self._load(tmp_path, "provider: openai\nmodels:\n  - id: m\n    input_cost_per_million: -1\n")

    def test_hosted_builtin_models_are_priced(self):
        hosted = {"anthropic", "deepseek", "docsgpt", "google", "groq", "novita", "openai", "openrouter"}
        catalogs = [
            c for c in load_model_yamls([BUILTIN_MODELS_DIR]) if c.source_path.stem in hosted
        ]
        assert {c.source_path.stem for c in catalogs} == hosted
        for catalog in catalogs:
            for model in catalog.models:
                caps = model.capabilities
                assert caps.input_cost_per_million is not None, model.id
                assert caps.output_cost_per_million is not None, model.id

    def test_default_docsgpt_model_rates(self):
        (model,) = [
            m for c in load_model_yamls([BUILTIN_MODELS_DIR]) for m in c.models if m.id == "docsgpt-local"
        ]
        caps = model.capabilities
        assert (caps.input_cost_per_million, caps.output_cost_per_million) == (0.15, 0.5)
        assert caps.cached_input_cost_per_million == 0.03
        assert caps.cache_write_cost_per_million is None
