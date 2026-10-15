"""The registered decision models, their pinned constants and which one a runtime uses.

Identity needs no download: ``model_version()`` comes from these constants, so a feature can look up scores it
stored earlier without loading anything. The constants are checked against each repository's ``arcd_serving.json``
in the tests; on load, the files' own hashes win (see ``backends.onnx``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelSpec:
    """One published decision model.

    Attributes:
        id: Hugging Face repository.
        revision: The pinned commit.
        layers: Decoder layers (informational).
        prompt_hash: The release client's ``PROMPT_HASH`` the model was trained with.
        calibration: First 12 hex of the sha256 of the heads and temperatures in ``arcd_serving.json``.
        max_state_tokens: Tokens of state kept; the rest is cut.
        onnx_dtype: Weight type of the ``onnx/`` export, for the runtime label.
        min_free_mb: Memory a load needs free, the ``DECISION_MIN_FREE_MB`` default.
    """

    id: str
    revision: str
    layers: int
    prompt_hash: str
    calibration: str
    max_state_tokens: int
    onnx_dtype: str
    min_free_mb: int


V02 = ModelSpec(
    id="arc53/arc-decide-0.4b-v0.2",
    revision="cb32fe9190a78aed4291fd8e8f087628dc5053df",
    layers=16,
    prompt_hash="78cfb276f93a",
    calibration="c3bc72ff6907",
    max_state_tokens=2048,
    onnx_dtype="int8",
    min_free_mb=1200,  # peaks at 978 MiB over every call shape
)
V01 = ModelSpec(
    id="arc53/arc-decide-0.6b-v0.1",
    revision="a03cd6bc45fa7b75e05489454e2084bd3516db17",
    layers=28,
    prompt_hash="78cfb276f93a",
    calibration="680b3c70a92c",
    max_state_tokens=2048,
    onnx_dtype="fp32",
    min_free_mb=3200,  # ~2.9 GB on an analytics turn
)

REGISTRY: dict[str, ModelSpec] = {spec.id: spec for spec in (V02, V01)}

#: The model each runtime uses when ``DECISION_MODEL`` is unset.
DEFAULT_FOR_RUNTIME = {"onnx": V02.id}


def lookup(model_id: str) -> Optional[ModelSpec]:
    """The registered model with this id (Hub ids are case-insensitive), or ``None``."""
    wanted = model_id.strip().lower()
    return next((spec for spec in REGISTRY.values() if spec.id.lower() == wanted), None)


def select(runtime: str = "onnx") -> Optional[ModelSpec]:
    """The model for a runtime: ``DECISION_MODEL`` when set, else the runtime's default.

    Returns:
        The spec, or ``None`` when ``DECISION_MODEL`` names an unregistered model.
    """
    from docsgpt.core.settings import settings

    return lookup(settings.DECISION_MODEL or DEFAULT_FOR_RUNTIME[runtime])


def calibration_hash(serving: dict) -> str:
    """The calibration identity of an ``arcd_serving.json``: its heads and temperatures, hashed."""
    payload = {"heads": serving["heads"], "temperature": serving["temperature"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def version(spec: ModelSpec, calibration: Optional[str] = None) -> str:
    """``<repo>/p<prompt_hash>/c<calibration>``, the key under which answers may be stored.

    The Hub commit and the runtime are left out: client-only commits happen, and the int8 and fp16 runs of a model
    agree within its parity tier, so neither should invalidate stored scores.
    """
    return f"{spec.id}/p{spec.prompt_hash}/c{calibration or spec.calibration}"
