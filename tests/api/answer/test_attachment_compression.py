"""Pre-turn compression accounts for the turn's attachments, and fit comes first.

Two production failures shaped these tests:

* a turn attaching a large set was planned against the full history, so the
  history never compressed and the request overflowed;
* a /v1 turn whose own message could not fit the window even with no history
  first ran a ~193k-token compression call on the history, then failed
  anyway, on every retry.
"""

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.agents.context_overflow import ContextOverflowError
from docsgpt.api.answer.services.compression import CompressionOrchestrator
from docsgpt.api.answer.services.compression.types import CompressionResult

pytestmark = pytest.mark.unit

WINDOW = 100_000
SP = "docsgpt.api.answer.services.stream_processor"


def _att(name, tokens, att_id):
    return {
        "id": att_id,
        "filename": name,
        "mime_type": "text/plain",
        "content": "x" * 10,
        "token_count": tokens,
        "metadata": {"extraction": {"status": "ok"}, "content_hash": f"h-{att_id}"},
    }


def _history(turns, tokens_per_side):
    word = "word " * tokens_per_side
    return [{"prompt": word, "response": word, "attachments": []} for _ in range(turns)]


def _processor(data):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    sp = StreamProcessor(request_data=data, decoded_token={"sub": "u"})
    sp.model_id = "m"
    sp.model_user_id = "u"
    sp._get_prompt_content = MagicMock(return_value="You are helpful.")
    sp.conversation_service = MagicMock()
    sp.compression_orchestrator = CompressionOrchestrator(sp.conversation_service)
    return sp


@pytest.fixture(autouse=True)
def _model():
    with patch(f"{SP}.get_token_limit", return_value=WINDOW), patch(
        "docsgpt.api.answer.services.compression.threshold_checker.get_token_limit", return_value=WINDOW
    ), patch(
        f"{SP}.get_model_capabilities",
        return_value={"supported_attachment_types": [], "supports_tools": True, "context_window": WINDOW},
    ), patch(f"{SP}.settings.ENABLE_CONVERSATION_COMPRESSION", True):
        yield


def _run(sp, conversation):
    sp.conversation_service.get_conversation.return_value = conversation
    performed = CompressionResult.success_with_compression("short summary", [], MagicMock())
    with patch.object(
        sp.compression_orchestrator, "_perform_compression", return_value=performed
    ) as perform:
        sp._load_conversation_history()
    return perform


class TestThresholdCountsPlannedAttachments:
    def test_big_attach_turn_compresses_history(self):
        sp = _processor({"conversation_id": "c1", "question": "summarise", "attachments": ["a1", "a2"]})
        sp.attachments = [_att("a.txt", 20_000, "a1"), _att("b.txt", 20_000, "a2")]
        # 44k of history: under the 80% threshold alone, over it with the files.
        perform = _run(sp, {"queries": _history(4, 5_500)})

        perform.assert_called_once()
        assert sp.compressed_summary == "short summary"

    def test_no_compression_when_everything_fits(self):
        sp = _processor({"conversation_id": "c1", "question": "summarise", "attachments": ["a1"]})
        sp.attachments = [_att("a.txt", 2_000, "a1")]
        perform = _run(sp, {"queries": _history(2, 2_000)})

        perform.assert_not_called()
        assert len(sp.history) == 2

    def test_files_from_earlier_turns_are_not_counted_as_inline(self):
        sp = _processor({"conversation_id": "c1", "question": "and now?"})
        sp.attachments = []
        history = _history(4, 5_000)
        history[0]["attachments"] = ["e1", "e2"]
        with patch.object(
            type(sp),
            "_fetch_attachment_rows",
            return_value=[_att("old1.txt", 30_000, "e1"), _att("old2.txt", 30_000, "e2")],
        ):
            perform = _run(sp, {"queries": history})

        perform.assert_not_called()
        assert [a["id"] for a in sp.earlier_attachments] == ["e1", "e2"]


class TestFitBeforeCompression:
    def test_a_turn_that_cannot_fit_fails_before_any_compression_call(self):
        oversized = [{"type": "text", "text": "clause " * (WINDOW + 5_000)}]
        sp = _processor({"conversation_id": "c1", "question": "assess", "multimodal_content": oversized})
        sp.attachments = []
        conversation = {"queries": _history(10, 9_000)}

        with patch.object(sp.compression_orchestrator, "compress_if_needed") as compress, patch(
            f"{SP}.multimodal_reaches_model", return_value=True
        ):
            sp.conversation_service.get_conversation.return_value = conversation
            with pytest.raises(ContextOverflowError) as info:
                sp._load_conversation_history()

        compress.assert_not_called()
        assert info.value.needed_tokens > WINDOW
        assert info.value.available_tokens == WINDOW

    def test_new_conversation_is_checked_too(self):
        oversized = [{"type": "text", "text": "clause " * (WINDOW + 5_000)}]
        sp = _processor({"question": "assess", "multimodal_content": oversized})
        sp.conversation_id = None
        sp.attachments = []
        with patch(f"{SP}.multimodal_reaches_model", return_value=True):
            with pytest.raises(ContextOverflowError):
                sp._load_conversation_history()

    def test_plain_text_question_is_not_refused(self):
        # A plain question is middle-truncated by message building, so it
        # always fits; only what cannot be shortened is checked here.
        sp = _processor({"question": "word " * (WINDOW + 5_000)})
        sp.conversation_id = None
        sp.attachments = []
        sp._load_conversation_history()
