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
