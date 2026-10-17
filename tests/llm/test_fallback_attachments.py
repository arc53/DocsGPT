"""A fallback keeps the turn's documents, or is not tried at all."""

import pytest

from docsgpt.agents.context_overflow import ContextOverflowError, is_context_length_error
from tests.llm.test_fallback import FakeLLM, VisionFakeLLM  # noqa: F401 (autouse fixtures below)
from tests.llm.test_fallback import _patch_decorators  # noqa: F401

pytestmark = pytest.mark.unit


class ContextLengthError(Exception):
    """A provider's context-length rejection."""

    code = "context_length_exceeded"


class _FailingLLM(FakeLLM):
    def __init__(self, error, **kwargs):
        super().__init__(fail_at=0, **kwargs)
        self._error = error

    def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.gen_stream_called = True
        raise self._error
        yield  # pragma: no cover

    def _raw_gen(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.gen_called = True
        raise self._error


def _limits(monkeypatch, limits):
    monkeypatch.setattr(
        "docsgpt.core.model_utils.get_token_limit",
        lambda model_id, user_id=None: limits.get(model_id, 100_000),
    )


def _pair(error=None, fallback=None, primary_model="primary", fallback_model="backup"):
    primary = _FailingLLM(error or RuntimeError("primary model unavailable"), model_id=primary_model)
    backup = fallback or FakeLLM(stream_chunks=["fb"], responses=["fb"])
    backup.model_id = fallback_model
    primary._fallback_llm = backup
    return primary, backup


class TestContextLengthErrors:
    @pytest.mark.parametrize(
        "error",
        [
            ContextLengthError("too long"),
            RuntimeError("Error code: 400 - This model's maximum context length is 128000 tokens"),
            RuntimeError("prompt is too long: 250000 tokens > 200000 maximum"),
            RuntimeError("The input exceeds the context window of this model"),
            ContextOverflowError("x", needed_tokens=2, available_tokens=1, stage="dispatch"),
        ],
    )
    def test_recognised(self, error):
        assert is_context_length_error(error)

    @pytest.mark.parametrize(
        "error",
        [RuntimeError("rate limit"), ValueError("bad request"), RuntimeError("Unknown parameter: context")],
    )
    def test_other_errors_are_not(self, error):
        assert not is_context_length_error(error)

    def test_not_retried_on_a_smaller_window(self, monkeypatch):
        _limits(monkeypatch, {"primary": 200_000, "backup": 128_000})
        primary, backup = _pair(ContextLengthError("too long"))

        with pytest.raises(ContextLengthError):
            list(primary.gen_stream(model="primary", messages=[{"role": "user", "content": "hi"}]))
        assert backup.gen_stream_called is False

    def test_not_retried_on_an_equal_window(self, monkeypatch):
        _limits(monkeypatch, {"primary": 200_000, "backup": 200_000})
        primary, backup = _pair(ContextLengthError("too long"))

        with pytest.raises(ContextLengthError):
            primary.gen(model="primary", messages=[{"role": "user", "content": "hi"}])
        assert backup.gen_called is False

    def test_retried_on_a_larger_window(self, monkeypatch):
        _limits(monkeypatch, {"primary": 128_000, "backup": 1_000_000})
        primary, backup = _pair(ContextLengthError("too long"))

        assert list(primary.gen_stream(model="primary", messages=[{"role": "user", "content": "hi"}])) == ["fb"]


def _file_messages(*file_ids):
    return [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": [{"type": "text", "text": "compare them"}]
            + [{"type": "file", "file": {"file_id": fid}} for fid in file_ids],
        },
    ]


class TestSwapsMatchAttachmentIds:
    def test_each_file_part_gets_its_own_attachments_text(self, monkeypatch):
        _limits(monkeypatch, {})
        primary, backup = _pair()
        # The provider sent only the PDF as a file part; the docx went in as text.
        primary._file_part_attachments = {"file-pdf": "att-pdf"}
        attachments = [
            {"id": "att-docx", "filename": "a.docx", "content": "DOCX TEXT"},
            {"id": "att-pdf", "filename": "b.pdf", "content": "PDF TEXT"},
        ]

        list(primary.gen_stream(model="primary", messages=_file_messages("file-pdf"), _usage_attachments=attachments))

        sent = backup.last_messages_received[1]["content"]
        assert "PDF TEXT" in sent
        assert "DOCX TEXT" not in sent

    def test_a_file_part_with_no_text_fails_openly(self, monkeypatch):
        _limits(monkeypatch, {})
        primary, backup = _pair()

        with pytest.raises(RuntimeError, match="primary model unavailable"):
            list(primary.gen_stream(model="primary", messages=_file_messages("file-unknown")))
        assert backup.gen_stream_called is False


class TestFitIsCheckedAfterTheSwap:
    def test_swapped_text_that_cannot_fit_skips_the_fallback(self, monkeypatch):
        _limits(monkeypatch, {"primary": 1_000_000, "backup": 2_000})
        primary, backup = _pair()
        primary._file_part_attachments = {"file-pdf": "att-pdf"}
        attachments = [{"id": "att-pdf", "filename": "b.pdf", "content": "word " * 20_000}]

        with pytest.raises(RuntimeError, match="primary model unavailable"):
            list(
                primary.gen_stream(
                    model="primary", messages=_file_messages("file-pdf"), _usage_attachments=attachments
                )
            )
        assert backup.gen_stream_called is False


class _Dispatch:
    """Stands in for the agent's attachment dispatch."""

    def __init__(self, replanned=None, usage=0):
        self.replanned = replanned
        self.usage = usage
        self.asked = []

    def usage_tokens(self, messages):
        return self.usage

    def for_fallback(self, fallback, messages):
        self.asked.append(fallback)
        return self.replanned


class _Replanned:
    def __init__(self, messages, dispatch):
        self.messages = messages
        self.dispatch = dispatch


class TestReplannedAttachments:
    def test_the_fallback_gets_the_replanned_messages(self, monkeypatch):
        _limits(monkeypatch, {})
        replanned = [{"role": "user", "content": "[F1 a.pdf inline] compare them"}]
        follow_up = _Dispatch(usage=0)
        dispatch = _Dispatch(_Replanned(replanned, follow_up))
        primary, backup = _pair()

        list(
            primary.gen_stream(
                model="primary", messages=_file_messages("file-pdf"), _attachment_dispatch=dispatch
            )
        )

        assert dispatch.asked == [backup]
        assert backup.last_messages_received == replanned
        assert backup.last_kwargs_received["_attachment_dispatch"] is follow_up

    def test_replanned_native_parts_count_toward_the_fit(self, monkeypatch):
        _limits(monkeypatch, {"primary": 1_000_000, "backup": 5_000})
        replanned = [{"role": "user", "content": "short"}]
        dispatch = _Dispatch(_Replanned(replanned, _Dispatch(usage=50_000)))
        primary, backup = _pair()

        with pytest.raises(RuntimeError, match="primary model unavailable"):
            list(primary.gen_stream(model="primary", messages=_file_messages(), _attachment_dispatch=dispatch))
        assert backup.gen_stream_called is False
