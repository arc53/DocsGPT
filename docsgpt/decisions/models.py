"""The registered decision models, their pinned constants and which one a runtime uses.

Identity needs no download: ``model_version()`` comes from these constants, so a feature can look up scores it
stored earlier without loading anything. The constants are checked against each repository's ``arcd_serving.json``
in the tests; on load, the files' own hashes win (see ``backends.onnx``). The heads and temperatures are here too,
because the vLLM protocol applies them on this side of the wire and downloads only the tokenizer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
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
        serving: The ``heads`` and ``temperature`` (without its ``fit_sets`` notes) of ``arcd_serving.json``.
    """

    id: str
    revision: str
    layers: int
    prompt_hash: str
    calibration: str
    max_state_tokens: int
    onnx_dtype: str
    min_free_mb: int
    serving: dict = field(default_factory=dict, compare=False, repr=False)


#: Label tokens of each head; both models read the same ones.
_LABELS = {
    "noul": [9834, 902],
    "score:4": [15, 16, 17, 18],
    "score:3": [20, 21, 22],
    "choice": [362, 425, 356, 422, 468, 434, 479, 472, 358, 619, 730, 444, 386, 451, 506, 393],
}


def _heads(noul: float, score4: list[float], score3: list[float]) -> dict:
    return {
        "noul": {"tokens": _LABELS["noul"], "bias": noul},
        "score:4": {"tokens": _LABELS["score:4"], "bias": score4},
        "score:3": {"tokens": _LABELS["score:3"], "bias": score3},
        "choice": {"tokens": _LABELS["choice"], "bias": [0.0] * len(_LABELS["choice"])},
    }


V02 = ModelSpec(
    id="arc53/arc-decide-0.4b-v0.2",
    revision="cb32fe9190a78aed4291fd8e8f087628dc5053df",
    layers=16,
    prompt_hash="78cfb276f93a",
    calibration="c3bc72ff6907",
    max_state_tokens=2048,
    onnx_dtype="int8",
    min_free_mb=1200,  # peaks at 978 MiB over every call shape
    serving={
        "heads": _heads(
            0.0012515024282038212,
            [0.0031790027860552073, -0.005675514228641987, 0.0009620477794669569, 0.0025524271186441183],
            [0.00550613459199667, 0.0031515166629105806, -0.014491165988147259],
        ),
        "temperature": {
            "noul": 1.0000000000000004, "score": 0.9958365752606795, "choice": 1.4125375446227555,
            "by_question": {
                "frustrated": 0.3831186849557289, "asks_human": 0.7356422544596417, "injection": 1.0000000000000004,
                "relevant": 0.926118728128794, "goal_met": 0.5843414133735179, "answer": 1.995262314968881,
                "supported": 0.9623506263980889, "tag": 0.926118728128794, "needs_retrieval": 1.0391223038351698,
                "needs_clarification": 0.9623506263980889, "tool_needed": 1.0391223038351698,
                "right_tool": 0.9623506263980889, "tool_succeeded": 1.0391223038351698,
                "result_used": 0.926118728128794, "induced_by_untrusted": 1.0391223038351698,
                "sentiment": 0.6072021956909888, "severity": 1.0000000000000004, "grade": 1.0000000000000004,
                "complexity": 0.9623506263980889, "reaction": 0.7644222742526006,
                "answer_status": 0.7644222742526006, "unanswered_reason": 0.7079457843841382,
                "request_type": 0.6556418494179792, "intent": 1.4125375446227555, "topic": 0.9623506263980889,
            },
        },
    },
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
    serving={
        "heads": _heads(
            0.0023702443577349186,
            [0.0011492845369502902, -0.003303258214145899, 0.0005224453052505851, 0.0006493947003036737],
            [0.0025686242152005434, 0.002364307176321745, -0.00862978771328926],
        ),
        "temperature": {
            "noul": 1.0391223038351698, "score": 1.023003591673832, "choice": 1.4125375446227555,
            "by_question": {
                "relevant": 1.0000000000000004, "injection": 1.2115276586285892, "supported": 0.926118728128794,
                "goal_met": 0.5623413251903493, "tag": 1.0000000000000004, "frustrated": 0.3831186849557289,
                "asks_human": 0.7356422544596417, "needs_retrieval": 1.0797751623277103,
                "needs_clarification": 1.0000000000000004, "answer": 1.995262314968881,
                "tool_needed": 1.1220184543019638, "right_tool": 0.9623506263980889,
                "tool_succeeded": 1.0000000000000004, "result_used": 0.7644222742526006,
                "induced_by_untrusted": 1.0391223038351698, "grade": 1.0000000000000004,
                "severity": 1.0797751623277103, "complexity": 1.0391223038351698, "sentiment": 0.6072021956909888,
                "answer_status": 0.7644222742526006, "unanswered_reason": 0.7356422544596417,
                "request_type": 0.6556418494179792, "intent": 1.4125375446227555, "topic": 1.0391223038351698,
                "reaction": 0.7943282347242819,
            },
        },
    },
)

REGISTRY: dict[str, ModelSpec] = {spec.id: spec for spec in (V02, V01)}

#: The model each runtime uses when ``DECISION_MODEL`` is unset. ``torch`` is ``docsgpt decide-server`` on a GPU;
#: ``remote`` is a ``decide`` server that does not report its model (``arcd serve``); one that does is taken at its
#: word.
DEFAULT_FOR_RUNTIME = {"onnx": V02.id, "torch": V02.id, "vllm": V01.id, "remote": V01.id}


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
