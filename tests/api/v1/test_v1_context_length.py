"""/v1: a request that does not fit the model gets OpenAI's context_length_exceeded."""

import json

import pytest

from docsgpt.agents.context_overflow import ContextOverflowError
from tests.api.v1.test_v1_file_attachments_route import BODY, _helper, _post, _processor

pytestmark = pytest.mark.unit


def _overflow():
    return ContextOverflowError(
        "raw detail", needed_tokens=300_000, available_tokens=200_000, stage="pre_compression"
    )


class TestContextLengthExceeded:
    def _assert_error(self, payload):
        error = payload["error"]
        assert error["type"] == "invalid_request_error"
        assert error["code"] == "context_length_exceeded"
        assert error["param"] == "messages"
        assert "300,000" in error["message"]
        assert "raw detail" not in error["message"]

    def test_before_the_stream_it_is_a_400(self, pg_conn):
        processor = _processor()
        processor.build_agent.side_effect = _overflow()

        response, _, _, _ = _post(pg_conn, {**BODY, "stream": True}, processor, _helper([]))

        assert response.status_code == 400
        self._assert_error(response.get_json())

    def test_non_streaming_overflow_inside_the_run_is_a_400(self, pg_conn):
        result = {
            "error": "too big",
            "error_code": "context_length_exceeded",
            "conversation_id": None,
            "answer": None,
            "sources": None,
            "tool_calls": None,
            "thought": None,
        }
        error_event = {"type": "error", "error": "This message ... 300,000 tokens", "code": "context_length_exceeded"}
        helper = _helper([f"data: {json.dumps(error_event)}"], result=result)
        helper.process_response_stream.side_effect = None

        response, _, _, _ = _post(pg_conn, BODY, _processor(), helper)

        assert response.status_code == 400
        error = response.get_json()["error"]
        assert error["code"] == "context_length_exceeded"
        assert error["type"] == "invalid_request_error"

    def test_mid_stream_it_is_an_error_frame_then_done(self, pg_conn):
        event = {
            "type": "error",
            "error": "This message and its attached files need about 300,000 tokens.",
            "code": "context_length_exceeded",
        }
        helper = _helper([f"data: {json.dumps(event)}\n\n"])

        response, raw, _, _ = _post(pg_conn, {**BODY, "stream": True}, _processor(), helper)

        frames = [line[len("data: "):] for line in raw.splitlines() if line.startswith("data: ")]
        assert frames[-1] == "[DONE]"
        error = json.loads(frames[-2])["error"]
        assert error["code"] == "context_length_exceeded"
        assert error["type"] == "invalid_request_error"
        assert error["param"] == "messages"
