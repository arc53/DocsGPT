"""A scripted LLM for drafter tests: answers in the OpenAI response shape the handler parses."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def tool_call(name: str, arguments: Any, call_id: str = "call_1") -> SimpleNamespace:
    """One OpenAI-shaped tool call."""
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return SimpleNamespace(id=call_id, index=0, function=SimpleNamespace(name=name, arguments=args))


def calls(*tool_calls: SimpleNamespace, content: str | None = None, reasoning: str | None = None) -> SimpleNamespace:
    """A response choice that calls tools (with the ``reasoning_content`` a thinking model sends, if given).

    The calls are numbered as a stream numbers them; one index is one call.
    """
    tool_calls = tuple(SimpleNamespace(**{**vars(call), "index": i}) for i, call in enumerate(tool_calls))
    message = SimpleNamespace(content=content, tool_calls=list(tool_calls))
    if reasoning is not None:
        message.reasoning_content = reasoning
    return SimpleNamespace(message=message, finish_reason="tool_calls" if tool_calls else "stop")


def text(content: str) -> str:
    """A plain-text answer (an answer without tool calls, streamed as text)."""
    return content


class FakeLLM:
    """Streams back ``script`` one answer per ``gen_stream`` call and records each call.

    The stream runs through ``timed_stream`` as ``BaseLLM.gen_stream`` does,
    so a Stop or deadline the drafter binds with ``interruptible`` ends it
    the same way. An answer is an exception (raised before any chunk), text
    (streamed in two pieces), a response choice (one chunk), or a list of
    chunks streamed as given.
    """

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.model_id = "fake-model"
        self._drafter_provider = "openai"
        self.closed = 0

    def gen(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the drafter streams its model calls")

    def gen_stream(self, model: str, messages: list, tools: Any = None, **kwargs: Any) -> Any:
        from docsgpt.llm.deadlines import timed_stream

        self.calls.append({"model": model, "messages": [dict(m) for m in messages], "tools": tools})
        if not self.script:
            raise AssertionError("the fake LLM ran out of answers")
        answer = self.script.pop(0)
        return timed_stream(lambda: self._closing(self.chunks(answer)), first_token=60, stall=60)

    def chunks(self, answer: Any) -> Any:
        """The chunks of one scripted answer."""
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, list):
            yield from answer
        elif isinstance(answer, str) and len(answer) > 1:
            yield answer[: len(answer) // 2]
            yield answer[len(answer) // 2:]
        else:
            yield answer

    def _closing(self, chunks: Any) -> Any:
        try:
            yield from chunks
        finally:
            self.closed += 1

    def factory(self, user_id: str, model_id: str, request_id: str) -> "FakeLLM":
        """Stands in for ``build_llm``."""
        self.built_for = (user_id, model_id, request_id)
        return self


#: The task model a test hands ``run_draft``: one that calls tools.
MODEL = {"id": "m", "display_name": "M", "supports_tools": True}

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
