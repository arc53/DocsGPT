"""A one-time schedule replays its origin chat without stored summary rows."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.user import scheduler_worker


@pytest.mark.unit
def test_origin_history_leaves_out_compression_summary_rows():
    rows = [
        {"prompt": "q0", "response": "a0", "tool_calls": [], "metadata": {}},
        {"prompt": "[Context Compression Summary]", "response": "s", "tool_calls": [],
         "metadata": {"compression_summary": True}},
        {"prompt": "[Context Compression Summary]", "response": "legacy", "tool_calls": [], "metadata": {}},
        {"prompt": "q1", "response": "a1", "tool_calls": [], "metadata": {}},
    ]
    repo = MagicMock()
    repo.get_any.return_value = {"id": "c1"}
    repo.get_messages.return_value = rows
    engine = MagicMock()

    @contextmanager
    def _connect():
        yield MagicMock()

    engine.connect = _connect
    schedule = {"origin_conversation_id": "c1", "trigger_type": "once", "user_id": "u"}
    with patch.object(scheduler_worker, "get_engine", return_value=engine), patch.object(
        scheduler_worker, "ConversationsRepository", return_value=repo
    ):
        history = scheduler_worker._load_chat_history(schedule)

    assert history == [{"prompt": "q0", "response": "a0"}, {"prompt": "q1", "response": "a1"}]
