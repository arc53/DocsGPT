"""The turn-start bound a compression during the turn may cover up to."""

import pytest

from docsgpt.api.answer.services.stream_processor import StreamProcessor


def _processor(covered: int) -> StreamProcessor:
    processor = StreamProcessor.__new__(StreamProcessor)
    processor.history_covered_index = covered
    return processor


def _rows(*statuses):
    return {"queries": [{"prompt": f"q{i}", "status": s} for i, s in enumerate(statuses)]}


@pytest.mark.unit
class TestHistoryBound:
    def test_every_settled_row_is_held(self):
        assert _processor(-1)._history_bound(_rows("complete", "failed", "complete")) == 2

    def test_stops_before_the_first_row_still_being_answered(self):
        assert _processor(-1)._history_bound(_rows("complete", "streaming", "complete")) == 0

    def test_a_row_inside_the_summary_does_not_stop_it(self):
        # Row 1 was folded into the saved summary while it was still open.
        assert _processor(2)._history_bound(_rows("complete", "pending", "complete", "complete")) == 3

    def test_an_empty_conversation(self):
        assert _processor(-1)._history_bound({"queries": []}) == -1


@pytest.mark.unit
def test_a_new_conversation_holds_no_saved_row():
    from unittest.mock import patch

    processor = StreamProcessor.__new__(StreamProcessor)
    processor.conversation_id = None
    processor.initial_user_id = None
    processor.history_bound = None
    processor.data = {"history": "[]"}
    processor.model_id = "m"
    processor.model_user_id = None
    with patch.object(StreamProcessor, "_with_request_earlier_attachments", return_value=[]), patch.object(
        StreamProcessor, "_ensure_turn_fits"
    ), patch.object(StreamProcessor, "_context_window_limit", return_value=None), patch.object(
        StreamProcessor, "_within_history_limit", side_effect=lambda history: history
    ):
        processor._load_conversation_history()

    assert processor.history_bound == -1
