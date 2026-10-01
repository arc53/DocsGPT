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


class TestRegenerateExcludesTheReplacedTurns:
    """A retry or an edit at ``index`` replaces that turn and drops the later ones."""

    def _conversation(self):
        history = _history(4, 100)
        for position, entry in enumerate(history):
            entry["position"] = position
            entry["attachments"] = [f"e{position}"]
        return {"queries": history}

    def _rows(self, ids):
        return [_att(f"{i}.txt", 100, i) for i in ids]

    def test_files_of_the_replaced_and_later_turns_are_not_earlier(self):
        sp = _processor({"conversation_id": "c1", "question": "again", "index": 2})
        sp.attachments = []
        with patch.object(type(sp), "_fetch_attachment_rows", side_effect=self._rows) as fetch:
            _run(sp, self._conversation())
        fetch.assert_called_once_with(["e0", "e1"])
        assert [a["id"] for a in sp.earlier_attachments] == ["e0", "e1"]

    def test_regenerating_the_first_turn_has_no_earlier_files(self):
        sp = _processor({"conversation_id": "c1", "question": "again", "index": 0})
        sp.attachments = []
        with patch.object(type(sp), "_fetch_attachment_rows", side_effect=self._rows) as fetch:
            _run(sp, self._conversation())
        fetch.assert_not_called()
        assert sp.earlier_attachments == []

    def test_a_new_turn_sees_every_earlier_file(self):
        sp = _processor({"conversation_id": "c1", "question": "next"})
        sp.attachments = []
        with patch.object(type(sp), "_fetch_attachment_rows", side_effect=self._rows):
            _run(sp, self._conversation())
        assert [a["id"] for a in sp.earlier_attachments] == ["e0", "e1", "e2", "e3"]


class TestV1RequestFiles:
    """What /v1 tells the processor about the files a stateless client re-sent."""

    def test_files_from_earlier_messages_join_the_earlier_attachments(self):
        sp = _processor({"question": "next", "earlier_attachments": ["r1", "r2"]})
        sp.trace_source = "v1"
        sp.conversation_id = None
        sp.attachments = []
        with patch.object(type(sp), "_fetch_attachment_rows", side_effect=lambda ids: [_att(f"{i}.txt", 100, i) for i in ids]):
            sp._load_conversation_history()
        assert [a["id"] for a in sp.earlier_attachments] == ["r1", "r2"]

    def test_they_are_merged_with_the_conversations_own_files_once(self):
        sp = _processor({"conversation_id": "c1", "question": "next", "earlier_attachments": ["e0", "r9"]})
        sp.trace_source = "v1"
        sp.attachments = []
        history = _history(2, 100)
        history[0]["attachments"] = ["e0"]
        with patch.object(type(sp), "_fetch_attachment_rows", side_effect=lambda ids: [_att(f"{i}.txt", 100, i) for i in ids]):
            _run(sp, {"queries": history})
        assert [a["id"] for a in sp.earlier_attachments] == ["e0", "r9"]

    def test_only_v1_requests_carry_them(self):
        sp = _processor({"question": "next", "earlier_attachments": ["r1"], "skipped_files": [{"filename": "x"}]})
        sp.conversation_id = None
        sp.attachments = []
        with patch.object(type(sp), "_fetch_attachment_rows") as fetch:
            sp._load_conversation_history()
        fetch.assert_not_called()
        assert sp.earlier_attachments == []
        assert sp._request_skipped_files() == []

    def test_skipped_files_are_read_from_a_v1_request(self):
        skipped = [{"filename": "clip.mp4", "mime_type": "video/mp4", "reason": "unsupported"}, "junk"]
        sp = _processor({"question": "q", "skipped_files": skipped})
        sp.trace_source = "v1"
        assert sp._request_skipped_files() == skipped[:1]


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
        # What one message may take: the window less the answer's and history's share.
        assert 0 < info.value.available_tokens < WINDOW

    def test_new_conversation_is_checked_too(self):
        oversized = [{"type": "text", "text": "clause " * (WINDOW + 5_000)}]
        sp = _processor({"question": "assess", "multimodal_content": oversized})
        sp.conversation_id = None
        sp.attachments = []
        with patch(f"{SP}.multimodal_reaches_model", return_value=True):
            with pytest.raises(ContextOverflowError):
                sp._load_conversation_history()

    def test_plain_text_question_too_big_is_refused_not_truncated(self):
        # Maintainer decision: oversized pasted text is an honest overflow,
        # never a silent middle cut, and it fails before any compression call.
        sp = _processor({"conversation_id": "c1", "question": "word " * (WINDOW + 5_000)})
        sp.attachments = []
        sp.conversation_service.get_conversation.return_value = {"queries": _history(10, 9_000)}
        with patch.object(sp.compression_orchestrator, "compress_if_needed") as compress:
            with pytest.raises(ContextOverflowError) as info:
                sp._load_conversation_history()

        compress.assert_not_called()
        assert info.value.needed_tokens > WINDOW + 5_000
        assert info.value.stage == "pre_compression"

    def test_a_question_over_the_message_budget_is_refused(self):
        # Under the window, but over what message building lets the turn's
        # own message take: it would have been cut, so it is refused.
        sp = _processor({"question": "word " * int(WINDOW * 0.8)})
        sp.conversation_id = None
        sp.attachments = []
        with pytest.raises(ContextOverflowError) as info:
            sp._load_conversation_history()
        assert info.value.available_tokens < WINDOW

    def test_history_does_not_count_toward_cannot_fit(self):
        sp = _processor({"conversation_id": "c1", "question": "word " * 20_000})
        sp.attachments = []
        perform = _run(sp, {"queries": _history(10, 9_000)})
        assert perform.called, "history is compressed, the turn is not refused"
