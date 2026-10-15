"""Where decision-model passes run: ``onnx`` runs the model in this process; ``http`` and ``vllm`` call a server."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Outcome:
    """One answered request, before it becomes a ``Decision``."""

    answers: dict[str, dict]
    ms: float
    queue_ms: float
    truncated: bool
    input_tokens: int
