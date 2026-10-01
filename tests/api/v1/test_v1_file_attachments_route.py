"""/v1: file parts become attachment rows the turn and its history refer to."""

import base64
import threading
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


class _FakeIngest:
    """``start_inline_files``' result: ``wait`` runs the test's ingest function."""

    def __init__(self, files, user, ingest, pending=False):
        self.files, self.user, self._ingest = files, user, ingest
        self.skipped = {}
        self.converted = {}
        self.pending = [object()] if pending else []
        self.waited = False

    def wait(self):
        self.waited = True
        self.pending = []
        self.converted = self._ingest(self.files, self.user, skipped=self.skipped)
        return self.converted


def _default_ingest(files, user, **_):
    return {f.content_hash: f"att-{i}" for i, f in enumerate(files)}


def _post(pg_conn, body, processor, helper, ingest=None, pending=False, consume=True):
    app = _build_app()
    created = {}
    started = []

    def _make_processor(data, token, **kwargs):
        created["data"] = data
        return processor

    def _start(files, user):
        started.append(_FakeIngest(files, user, ingest or _default_ingest, pending=pending))
        return started[-1]

    with _patch_v1_db(pg_conn), patch(
        "docsgpt.api.v1.routes.StreamProcessor", side_effect=_make_processor
    ), patch("docsgpt.api.v1.routes._V1AnswerHelper", return_value=helper), patch(
        "docsgpt.api.v1.routes.start_inline_files", side_effect=_start
    ) as ingested:
        with app.test_client() as client:
            response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer x"}, json=body)
            if not consume:
                return response, started, created, processor
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

        _, _, data, _ = _post(pg_conn, BODY, processor, helper, ingest=lambda files, user, **_: {})

        assert any(p.get("type") == "file" for p in data["multimodal_content"])
        assert not data.get("attachments")

    def test_files_that_could_not_be_stored_are_named_for_the_manifest(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        def _ingest(files, user, skipped=None):
            skipped.update({f.content_hash: "unsupported" for f in files})
            return {}

        _, _, data, _ = _post(pg_conn, BODY, processor, helper, ingest=_ingest)

        assert data["skipped_files"] == [
            {"filename": "PRILOGA_1.pdf", "mime_type": "application/pdf", "reason": "unsupported"}
        ]

    def test_a_failed_conversion_still_names_the_files(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        def _ingest(files, user, skipped=None):
            raise RuntimeError("storage down")

        response, _, data, _ = _post(pg_conn, BODY, processor, helper, ingest=_ingest)

        assert response.status_code == 200
        assert [s["reason"] for s in data["skipped_files"]] == ["not_stored"]


class TestParsesWaitInsideTheStream:
    """A streamed request starts its SSE stream before waiting on a parse (CF cuts at 100 s)."""

    def test_the_stream_starts_before_the_parse_is_awaited(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])
        app = _build_app()
        created, started = {}, []

        def _make_processor(data, token, **kwargs):
            created["data"] = data
            return processor

        release = threading.Event()

        def _slow_ingest(files, user, **kwargs):
            assert release.wait(5), "the parse was awaited before the stream started"
            return _default_ingest(files, user, **kwargs)

        def _start(files, user):
            started.append(_FakeIngest(files, user, _slow_ingest, pending=True))
            return started[-1]

        with _patch_v1_db(pg_conn), patch(
            "docsgpt.api.v1.routes.StreamProcessor", side_effect=_make_processor
        ), patch("docsgpt.api.v1.routes._V1AnswerHelper", return_value=helper), patch(
            "docsgpt.api.v1.routes.start_inline_files", side_effect=_start
        ):
            with app.test_client() as client:
                response = client.post(
                    "/v1/chat/completions", headers={"Authorization": "Bearer x"}, json={**BODY, "stream": True}
                )
                # The response is out while the parse is still running.
                assert response.status_code == 200
                assert response.mimetype == "text/event-stream"
                processor.build_agent.assert_not_called()
                release.set()
                raw = response.get_data(as_text=True)

        assert started[0].waited
        processor.build_agent.assert_called_once()
        assert created["data"]["attachments"] == ["att-0"]
        assert helper.complete_stream.call_args.kwargs["attachment_ids"] == ["att-0"]
        assert "[DONE]" in raw or "finish_reason" in raw

    def test_an_error_after_the_parse_ends_the_stream_with_an_error_frame(self, pg_conn):
        from docsgpt.agents.context_overflow import ContextOverflowError

        processor, helper = _processor(), _helper(['data: {"type": "end"}'])
        processor.build_agent.side_effect = ContextOverflowError(
            "raw", needed_tokens=300_000, available_tokens=200_000, stage="pre_compression"
        )

        response, raw, _, _ = _post(pg_conn, {**BODY, "stream": True}, processor, helper, pending=True)

        assert response.status_code == 200
        assert '"code": "context_length_exceeded"' in raw
        assert raw.rstrip().endswith("data: [DONE]")

    def test_a_non_streaming_request_waits_before_answering(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        response, _, data, ingested = _post(pg_conn, BODY, processor, helper, pending=True)

        assert response.status_code == 200
        assert data["attachments"] == ["att-0"]

    def test_a_stream_without_a_pending_parse_is_unchanged(self, pg_conn):
        processor, helper = _processor(), _helper(['data: {"type": "end"}'])

        response, raw, data, _ = _post(pg_conn, {**BODY, "stream": True}, processor, helper)

        assert response.status_code == 200
        assert data["attachments"] == ["att-0"]
