"""A scripted LLM for drafter tests: answers in the OpenAI response shape the handler parses."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def tool_call(name: str, arguments: Any, call_id: str = "call_1") -> SimpleNamespace:
    """One OpenAI-shaped tool call."""
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return SimpleNamespace(id=call_id, index=0, function=SimpleNamespace(name=name, arguments=args))


def calls(*tool_calls: SimpleNamespace, content: str | None = None) -> SimpleNamespace:
    """A response choice that calls tools."""
    return SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=list(tool_calls)),
        finish_reason="tool_calls",
    )


def text(content: str) -> str:
    """A plain-text answer (what ``gen`` returns without tool calls)."""
    return content


class FakeLLM:
    """Hands back ``script`` one answer per ``gen`` call and records each call."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.model_id = "fake-model"
        self._drafter_provider = "openai"

    def gen(self, model: str, messages: list, tools: Any = None, **kwargs: Any) -> Any:
        self.calls.append({"model": model, "messages": [dict(m) for m in messages], "tools": tools})
        if not self.script:
            raise AssertionError("the fake LLM ran out of answers")
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def factory(self, user_id: str, model_id: str, request_id: str) -> "FakeLLM":
        """Stands in for ``build_llm``."""
        self.built_for = (user_id, model_id, request_id)
        return self


PROPOSAL = {
    "message": "Drafted a shipping help agent.",
    "fields": {
        "name": "Shipping help",
        "description": "Answers shipping questions.",
        "agent_type": "classic",
        "starters": ["Where is my parcel?"],
    },
    "reasons": [{"field": "name", "summary": "Shipping help", "detail": "Says what it does."}],
    "notes": [],
}

QUESTIONS = {
    "message": "Two questions before I draft:",
    "questions": [
        {"text": "Where should refund requests go?", "options": ["Email support", "Collect details and stop"]},
        {"text": "Which knowledge?", "options": ["Help Center", "Policies"], "multi": True},
    ],
}
