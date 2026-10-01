"""/v1: file parts become attachment rows the turn and its history refer to."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from tests.api.v1.test_routes_extended import _build_app, _patch_v1_db

pytestmark = pytest.mark.unit

PDF = base64.b64encode(b"%PDF-1.4 fictional filing").decode()
BODY = {
    "messages": [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "assess the attached filing"},
                {"type": "file", "file": {"filename": "PRILOGA_1.PDF", "file_data": f"data:application/pdf;base64,{PDF}"}},
            ],
        },
    ]
}


def _processor():
    processor = MagicMock()
    processor.decoded_token = {"sub": "u-test"}
    processor.conversation_id = None
    processor.agent_config = {"user_api_key": None}
    processor.agent_id = None
    processor.model_id = "m"
    processor.model_user_id = None
    processor.request_id = "r1"
    processor.build_agent.return_value = MagicMock()
    return processor


def _helper(stream_lines, result=None):
    helper = MagicMock()
    helper.check_usage.return_value = None
    helper.complete_stream.side_effect = lambda **kw: iter(stream_lines)
    helper.process_response_stream.return_value = result or {
        "error": None,
        "conversation_id": "c1",
        "answer": "ok",
        "sources": [],
        "tool_calls": [],
        "thought": "",
        "extra": {},
    }
    return helper


def _post(pg_conn, body, processor, helper, ingest=None):
    app = _build_app()
    created = {}

    def _make_processor(data, token, **kwargs):
        created["data"] = data
        return processor

    with _patch_v1_db(pg_conn), patch(
        "docsgpt.api.v1.routes.StreamProcessor", side_effect=_make_processor
    ), patch("docsgpt.api.v1.routes._V1AnswerHelper", return_value=helper), patch(
        "docsgpt.api.v1.routes.ingest_inline_files",
        side_effect=ingest or (lambda files, user: {f.content_hash: f"att-{i}" for i, f in enumerate(files)}),
    ) as ingested:
        with app.test_client() as client:
            response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer x"}, json=body)
            raw = response.get_data(as_text=True)
    return response, raw, created.get("data"), ingested


class TestFilePartsBecomeAttachments:
    def test_the_processor_gets_attachment_ids_instead_of_the_parts(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        response, _, data, ingested = _post(pg_conn, BODY, processor, helper)

        assert response.status_code == 200
        files, user = ingested.call_args.args
        assert [f.filename for f in files] == ["PRILOGA_1.pdf"]
        assert user == "u-test"
        assert data["attachments"] == ["att-0"]
        assert "multimodal_content" not in data
        assert "inline_files" not in data

    def test_the_turn_is_persisted_with_its_attachment_ids(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        _post(pg_conn, BODY, processor, helper)

        assert helper.complete_stream.call_args.kwargs["attachment_ids"] == ["att-0"]

    def test_a_streamed_turn_is_persisted_with_its_attachment_ids(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        _post(pg_conn, {**BODY, "stream": True}, processor, helper)

        assert helper.complete_stream.call_args.kwargs["attachment_ids"] == ["att-0"]

    def test_files_that_could_not_be_stored_stay_in_the_request(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        _, _, data, _ = _post(pg_conn, BODY, processor, helper, ingest=lambda files, user: {})

        assert any(p.get("type") == "file" for p in data["multimodal_content"])
        assert not data.get("attachments")
