"""Hosted content-moderation check (OpenAI Moderation API).

Kept separate from the injection check on purpose: content-safety classifiers
have no prompt-injection coverage, so presenting them as one control would sell
protection that isn't there.
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from application.core.settings import settings
from application.guardrails.base import GuardrailCheck, ScanContext
from application.guardrails.types import CheckOutcome, Stage

_ENDPOINT = "https://api.openai.com/v1/moderations"

CATEGORIES = [
    "harassment",
    "harassment/threatening",
    "hate",
    "hate/threatening",
    "illicit",
    "illicit/violent",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
    "sexual",
    "sexual/minors",
    "violence",
    "violence/graphic",
]


class ModerationCheck(GuardrailCheck):
    name = "moderation"
    label = "Content safety (OpenAI)"
    description = (
        "Classifies content against OpenAI's moderation categories. Free to call, "
        "needs OPENAI_API_KEY. Detects harmful content only — not prompt injection."
    )
    supported_stages = {Stage.INPUT, Stage.OUTPUT, Stage.RETRIEVAL, Stage.TOOL_RESULT}
    supports_redaction = False
    latency_hint_ms = 300
    remote = True

    @classmethod
    def is_available(cls) -> bool:
        return bool(settings.OPENAI_API_KEY)

    @classmethod
    def validate_settings(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        categories = config.get("categories") or CATEGORIES
        if not isinstance(categories, list) or not categories:
            raise ValueError("categories must be a non-empty list")
        unknown = [c for c in categories if c not in CATEGORIES]
        if unknown:
            raise ValueError(f"unknown categories: {', '.join(map(str, unknown))}")
        model = str(config.get("model", "omni-moderation-latest")).strip()
        if not model:
            raise ValueError("model must not be empty")
        return {"categories": list(dict.fromkeys(categories)), "model": model}

    def scan(self, text: str, stage: Stage, context: ScanContext) -> CheckOutcome:
        if not text.strip():
            return CheckOutcome.clean()
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            return CheckOutcome.not_evaluated("OPENAI_API_KEY is not configured")
        try:
            response = requests.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": self.settings.get("model", "omni-moderation-latest"),
                    "input": text[:32000],
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return CheckOutcome.not_evaluated(f"moderation request failed: {type(exc).__name__}")
        except ValueError:
            return CheckOutcome.not_evaluated("moderation returned a non-JSON body")

        results = payload.get("results") or []
        if not results:
            return CheckOutcome.not_evaluated("moderation returned no results")
        flags = results[0].get("categories") or {}
        scores = results[0].get("category_scores") or {}
        watched = self.settings.get("categories") or CATEGORIES
        hit: List[str] = [c for c in watched if flags.get(c)]
        if not hit:
            return CheckOutcome.clean()
        top = max((float(scores.get(c, 0.0)) for c in hit), default=1.0)
        return CheckOutcome.hit(
            categories=hit, score=round(top, 4), detail=f"flagged: {', '.join(hit)}"
        )
