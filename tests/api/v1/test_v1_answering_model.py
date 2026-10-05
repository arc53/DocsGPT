"""``/v1`` names the model that answered, in ``docsgpt`` frames and ``docsgpt.model``.

The standard ``model`` field keeps echoing the agent, so OpenAI clients see
no change; the answering model (and any fallback) is a DocsGPT extension.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from docsgpt.api.v1.routes import _non_stream_response, _stream_response
from docsgpt.api.v1.translator import translate_response

pytestmark = pytest.mark.unit

PRIMARY = {"model": "gpt-6.1-sol", "provider": "azure_openai", "fallback": False}
FALLBACK = {"model": "kimi-k3", "provider": "openai_compatible", "fallback": True, "reason": "InternalServerError/500"}


def _agent():
    return SimpleNamespace(llm=SimpleNamespace(answered_by=[], token_usage={}, _last_finish_reason="stop"))


def _processor():
    processor = MagicMock()
    processor.conversation_id = None
    processor.agent_config = {}
    return processor


def _frames(agent, script):
    """Run ``_stream_response`` over a scripted internal stream.

    ``script`` holds internal events, and dicts with an ``answered`` key that
    stand for a model call starting to answer (the LLM records it).
    """

    def _complete_stream(**_kwargs):
        for step in script:
            if "answered" in step:
                agent.llm.answered_by.append(step["answered"])
                continue
            yield f"data: {json.dumps(step)}\n\n"

    helper = MagicMock()
    helper.complete_stream.side_effect = _complete_stream
    raw = list(_stream_response(helper, "q", agent, _processor(), "my-agent", None, True, "hidden"))
    frames = []
    for chunk in raw:
        body = chunk[len("data: "):].strip()
        frames.append("[DONE]" if body == "[DONE]" else json.loads(body))
    return frames


def _model_frames(frames):
    return [f["docsgpt"] for f in frames if isinstance(f, dict) and (f.get("docsgpt") or {}).get("type") == "model"]


def _content(frame):
    if not isinstance(frame, dict) or not frame.get("choices"):
        return None
    return frame["choices"][0]["delta"].get("content")


class TestStreamFrames:
    def test_the_primary_answering_is_named_once_before_its_text(self):
        frames = _frames(
            _agent(),
            [
                {"answered": PRIMARY},
                {"type": "answer", "answer": "Hel"},
                {"type": "answer", "answer": "lo"},
                {"type": "end"},
            ],
        )

        assert _model_frames(frames) == [{"type": "model", **PRIMARY}]
        model_at = next(i for i, f in enumerate(frames) if _model_frames([f]))
        first_text = next(i for i, f in enumerate(frames) if _content(f))
        assert model_at < first_text
        assert all(f["model"] == "my-agent" for f in frames if isinstance(f, dict))

    def test_a_fallback_mid_stream_is_named_when_it_takes_over(self):
        frames = _frames(
            _agent(),
            [
                {"answered": PRIMARY},
                {"type": "answer", "answer": "Partial"},
                {"answered": FALLBACK},
                {"type": "answer", "answer": "Whole answer"},
                {"type": "end"},
            ],
        )

        assert _model_frames(frames) == [{"type": "model", **PRIMARY}, {"type": "model", **FALLBACK}]
        order = [
            ("model", f["docsgpt"]["model"]) if _model_frames([f]) else ("text", _content(f))
            for f in frames
            if _model_frames([f]) or _content(f)
        ]
        assert order == [
            ("model", "gpt-6.1-sol"),
            ("text", "Partial"),
            ("model", "kimi-k3"),
            ("text", "Whole answer"),
        ]

    def test_a_fallback_before_the_first_chunk_is_the_only_model_named(self):
        frames = _frames(_agent(), [{"answered": FALLBACK}, {"type": "answer", "answer": "Hi"}, {"type": "end"}])

        assert _model_frames(frames) == [{"type": "model", **FALLBACK}]

    def test_tool_rounds_answered_by_different_models_report_each_change(self):
        frames = _frames(
            _agent(),
            [
                {"answered": FALLBACK},
                {"type": "tool_call", "data": {"status": "completed", "call_id": "c1", "tool_name": "attachments"}},
                {"answered": PRIMARY},
                {"type": "tool_call", "data": {"status": "completed", "call_id": "c2", "tool_name": "attachments"}},
                {"answered": FALLBACK},
                {"type": "answer", "answer": "Done"},
                {"type": "end"},
            ],
        )

        assert [f["model"] for f in _model_frames(frames)] == ["kimi-k3", "gpt-6.1-sol", "kimi-k3"]

    def test_no_frame_when_no_model_answered(self):
        frames = _frames(_agent(), [{"type": "error", "error": "boom"}, {"type": "end"}])

        assert _model_frames(frames) == []


class TestNonStream:
    def _response(self, answered_by):
        agent = _agent()
        agent.llm.answered_by = answered_by
        helper = MagicMock()
        helper.complete_stream.return_value = iter([])
        helper.process_response_stream.return_value = {
            "error": None,
            "conversation_id": "conv-1",
            "answer": "hello",
            "sources": [],
            "tool_calls": [],
            "thought": "",
            "extra": {},
        }
        with Flask(__name__).test_request_context():
            response = _non_stream_response(helper, "q", agent, _processor(), "my-agent", None, True, "hidden")
            return response.get_json()

    def test_the_answering_model_is_in_docsgpt_model(self):
        body = self._response([dict(PRIMARY)])

        assert body["model"] == "my-agent"
        assert body["docsgpt"]["model"] == "gpt-6.1-sol"
        assert body["docsgpt"]["provider"] == "azure_openai"
        assert body["docsgpt"]["fallback"] is False
        assert "reason" not in body["docsgpt"]

    def test_a_fallback_answer_says_so_and_why(self):
        body = self._response([dict(PRIMARY), dict(FALLBACK)])

        assert body["docsgpt"]["model"] == "kimi-k3"
        assert body["docsgpt"]["fallback"] is True
        assert body["docsgpt"]["reason"] == "InternalServerError/500"
        assert [m["model"] for m in body["docsgpt"]["models"]] == ["gpt-6.1-sol", "kimi-k3"]

    def test_nothing_is_added_when_no_model_answered(self):
        body = self._response([])

        assert "model" not in body["docsgpt"]


def test_translate_response_without_a_model_is_unchanged():
    body = translate_response("conv-1", "hi", None, None, "", "my-agent")

    assert body["docsgpt"] == {"conversation_id": "conv-1"}
