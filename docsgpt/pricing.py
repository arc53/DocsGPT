"""USD cost of LLM calls, from the per-model rates in the model catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from docsgpt.core.settings import settings


@dataclass(frozen=True)
class ModelRates:
    """USD-per-1M rates for one model; ``None`` cache rates bill at the prompt rate."""

    prompt: float
    generated: float
    cached_input: Optional[float] = None
    cache_write: Optional[float] = None


def _unpriced_rates() -> Optional[ModelRates]:
    """Return the operator's fallback rates for undeclared models, if configured."""
    fallback = settings.QUOTA_UNPRICED_RATE_PER_MILLION
    if not fallback:
        return None
    return ModelRates(prompt=float(fallback[0]), generated=float(fallback[1]))


def resolve_model_rates(model: Optional[str]) -> Optional[ModelRates]:
    """Return the rates for a registry model id.

    Args:
        model: Canonical registry id (catalog id, or the UUID of a BYOM record).

    Returns:
        The declared rates, the ``QUOTA_UNPRICED_RATE_PER_MILLION`` fallback when the
        model declares none, or ``None`` when there is no fallback either.
    """
    # Imported lazily: the registry pulls in the provider plugins, whose LLM
    # classes import ``docsgpt.usage`` and, through it, this module.
    from docsgpt.core.model_registry import ModelRegistry

    entry = ModelRegistry.get_instance().models.get(str(model)) if model else None
    if entry is None:
        return _unpriced_rates()
    caps = entry.capabilities
    if caps.input_cost_per_million is None or caps.output_cost_per_million is None:
        return _unpriced_rates()
    cached = caps.cached_input_cost_per_million
    written = caps.cache_write_cost_per_million
    return ModelRates(
        prompt=float(caps.input_cost_per_million),
        generated=float(caps.output_cost_per_million),
        cached_input=float(cached) if cached is not None else None,
        cache_write=float(written) if written is not None else None,
    )


def is_priced(model: Optional[str]) -> bool:
    """Return whether calls to ``model`` are recorded with a cost."""
    return resolve_model_rates(model) is not None


def cost_from_rates(
    rates: ModelRates,
    prompt_tokens: int,
    generated_tokens: int,
    cached_tokens: Optional[int] = 0,
    cache_write_tokens: Optional[int] = 0,
) -> float:
    """Return the USD cost of one call at ``rates``.

    ``prompt_tokens`` is the provider's billing total; ``cached_tokens`` and
    ``cache_write_tokens`` are the parts of it read from or written to the prompt
    cache. The sub-bins are clamped to the prompt total, so a malformed report can
    never price a call below "everything cached".
    """
    prompt_total = max(int(prompt_tokens or 0), 0)
    cached = min(max(int(cached_tokens or 0), 0), prompt_total)
    written = min(max(int(cache_write_tokens or 0), 0), prompt_total - cached)
    regular = prompt_total - cached - written
    cached_rate = rates.cached_input if rates.cached_input is not None else rates.prompt
    write_rate = rates.cache_write if rates.cache_write is not None else rates.prompt
    return (
        regular * rates.prompt
        + cached * cached_rate
        + written * write_rate
        + max(int(generated_tokens or 0), 0) * rates.generated
    ) / 1_000_000.0


def compute_cost_usd(
    model: Optional[str],
    prompt_tokens: int,
    generated_tokens: int,
    cached_tokens: Optional[int] = 0,
    cache_write_tokens: Optional[int] = 0,
) -> float:
    """Return the USD cost of one call to ``model``; ``0.0`` when it has no rates."""
    rates = resolve_model_rates(model)
    if rates is None:
        return 0.0
    return cost_from_rates(rates, prompt_tokens, generated_tokens, cached_tokens, cache_write_tokens)
