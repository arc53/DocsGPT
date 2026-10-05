"""The arrival order of an answer's parts, recorded while streaming and saved with the turn."""

from unittest.mock import MagicMock

import pytest

from docsgpt.api.answer.segments import AnswerSegments, utf16_length


@pytest.mark.unit
class TestAnswerSegments:
    def test_records_interleaved_order_with_lengths(self):
        metadata: dict = {}
        segments = AnswerSegments(metadata)

        segments.thought("Plan: ")
        segments.thought("read the wiki.")
        segments.answer("Step 1 done. ")
        segments.tool_call({"call_id": "a", "status": "pending"})
        segments.tool_call({"call_id": "a", "status": "completed"})
        segments.answer("Now step 2:")
        segments.tool_call({"call_id": "b"})
        segments.answer("All done.")

        assert metadata["segments"] == [
            {"kind": "thought", "length": 20},
            {"kind": "text", "length": 13},
            {"kind": "tool", "call_id": "a"},
            {"kind": "text", "length": 11},
            {"kind": "tool", "call_id": "b"},
            {"kind": "text", "length": 9},
        ]

    def test_lengths_are_utf16_units(self):
        assert utf16_length("✅ ok") == 4
        assert utf16_length("😀") == 2
        metadata: dict = {}
        AnswerSegments(metadata).answer("😀 hi")
        assert metadata["segments"] == [{"kind": "text", "length": 5}]

    def test_a_lone_surrogate_counts_as_one_unit(self):
        # JSON can decode "\ud800" into a str; the browser counts it as one unit.
        assert utf16_length("a\ud800b") == 3
        metadata: dict = {}
        AnswerSegments(metadata).answer("\udfff")
        assert metadata["segments"] == [{"kind": "text", "length": 1}]

    def test_ignores_empty_chunks_and_calls_without_id(self):
        metadata: dict = {}
        segments = AnswerSegments(metadata)
        segments.answer("")
        segments.tool_call({"status": "pending"})
        segments.tool_call(None)
        # Nothing recorded leaves the metadata as it was, so an empty turn writes no key.
        assert "segments" not in metadata

    def test_reset_forgets_the_order(self):
        metadata: dict = {}
        segments = AnswerSegments(metadata)
        segments.answer("blocked text")
        segments.tool_call({"call_id": "a"})
        segments.reset()
        segments.tool_call({"call_id": "a"})
        assert metadata["segments"] == [{"kind": "tool", "call_id": "a"}]


@pytest.mark.unit
class TestCompleteStreamSavesSegments:
    def test_finalized_metadata_carries_the_order(self, mock_mongo_db, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            agent = MagicMock()
            agent.gen.return_value = iter(
                [
                    {"thought": "Think."},
                    {"answer": "Now step 2:"},
                    {"type": "tool_call", "data": {"call_id": "c1", "status": "pending"}},
                    {"type": "tool_call", "data": {"call_id": "c1", "status": "completed"}},
                    {"answer": "Done."},
                ]
            )
            agent.tool_calls = []
            resource.conversation_service = MagicMock()
            resource.conversation_service.save_user_question.return_value = {
                "conversation_id": "conv1",
                "message_id": "msg1",
                "request_id": "req1",
            }

            list(
                resource.complete_stream(
                    question="Q",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_persist=True,
                    model_id="gpt-4",
                )
            )

            finalize = resource.conversation_service.finalize_message
            assert finalize.called
            metadata = finalize.call_args.kwargs["metadata"]
            assert metadata["segments"] == [
                {"kind": "thought", "length": 6},
                {"kind": "text", "length": 11},
                {"kind": "tool", "call_id": "c1"},
                {"kind": "text", "length": 5},
            ]
