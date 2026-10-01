"""A fallback model gets the turn's files re-planned for its own window."""

import copy
from unittest.mock import Mock, patch

import pytest

from docsgpt.agents.attachment_budget import AttachmentPlan
from docsgpt.agents.attachment_dispatch import AttachmentDispatch
from docsgpt.agents.base import BaseAgent
from docsgpt.api.answer.services.compression.token_counter import TokenCounter
from docsgpt.llm.handlers.handler_creator import LLMHandlerCreator
from docsgpt.utils import num_tokens_from_string

pytestmark = pytest.mark.unit

WINDOWS = {"m": 200_000, "fb-small": 30_000, "fb-big": 200_000}


class _Agent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "ok"}


class _LLM:
    """A provider double: PDFs become file parts when it takes them."""

    def __init__(self, model_id, types=()):
        self.model_id = model_id
        self.model_user_id = None
        self._types = list(types)

    def get_supported_attachment_types(self):
        return list(self._types)

    def _supports_tools(self):
        return True

    def prepare_messages_with_attachments(self, messages, attachments=None):
        carrier = messages[-1]
        content = carrier["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for attachment in attachments or []:
            content.append({"type": "file", "file": {"file_id": f"file-{attachment['id']}"}})
        carrier["content"] = content
        return messages


def text_att(name, tokens, body_word="lorem"):
    body = f"{body_word} " * tokens
    return {
        "id": f"id-{name}",
        "filename": name,
        "mime_type": "text/plain",
        "content": body,
        "token_count": num_tokens_from_string(body),
        "metadata": {"extraction": {"status": "ok"}},
    }


def pdf_att(name, body):
    return {
        "id": f"id-{name}",
        "filename": name,
        "mime_type": "application/pdf",
        "content": body,
        "token_count": num_tokens_from_string(body),
        "path": f"inputs/{name}",
        "metadata": {"page_count": 2, "extraction": {"status": "ok"}},
    }


@pytest.fixture(autouse=True)
def _windows():
    with patch(
        "docsgpt.core.model_utils.get_token_limit",
        side_effect=lambda model_id, user_id=None: WINDOWS.get(model_id, 100_000),
    ):
        yield


def _merged_turn(attachments, primary=None):
    agent = _Agent(
        endpoint="stream",
        llm_name="openai",
        model_id="m",
        api_key="k",
        llm=primary or _LLM("m"),
        llm_handler=LLMHandlerCreator.create_handler("openai"),
        decoded_token={"sub": "u"},
        attachments=attachments,
        attachment_planning=True,
    )
    agent.tool_executor = Mock()
    messages = agent._build_messages("system prompt", "compare the files")
    messages = agent.llm_handler.prepare_messages(agent, messages, attachments)
    return agent, messages


def _turn_text(messages):
    content = messages[-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if p.get("type") == "text")


class TestReplanForTheFallback:
    def test_a_smaller_window_gets_a_plan_that_fits_it(self):
        files = [text_att(f"r{i}.txt", 12_000, body_word=f"w{i}") for i in range(3)]
        agent, messages = _merged_turn(files)
        assert [f.status.value for f in agent.attachment_plan.files] == ["inline"] * 3

        replanned = AttachmentDispatch(agent).for_fallback(_LLM("fb-small"), messages)

        assert replanned is not None
        assert TokenCounter.count_message_tokens(replanned.messages) < WINDOWS["fb-small"]
        text = _turn_text(replanned.messages)
        # The user's own words survive, and every file is still listed.
        assert "compare the files" in text
        for i in range(3):
            assert f"r{i}.txt" in text

    def test_the_primary_messages_are_left_alone(self):
        files = [text_att(f"r{i}.txt", 20_000) for i in range(3)]
        agent, messages = _merged_turn(files)
        snapshot = copy.deepcopy(messages)

        AttachmentDispatch(agent).for_fallback(_LLM("fb-small"), messages)

        assert messages == snapshot

    def test_a_pdf_sent_natively_reaches_a_text_only_fallback_as_its_text(self):
        pdf = pdf_att("PRILOGA_1.PDF", "PDF BODY " * 50)
        agent, messages = _merged_turn([pdf], primary=_LLM("m", types=["application/pdf"]))
        assert any(p.get("type") == "file" for p in messages[-1]["content"])

        replanned = AttachmentDispatch(agent).for_fallback(_LLM("fb-big"), messages)

        content = replanned.messages[-1]["content"]
        parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
        assert not any(p.get("type") == "file" for p in parts)
        assert "PDF BODY" in _turn_text(replanned.messages)

    def test_a_pdf_capable_fallback_keeps_it_native_and_counts_it(self):
        pdf = pdf_att("a.pdf", "PDF BODY " * 50)
        agent, messages = _merged_turn([pdf], primary=_LLM("m", types=["application/pdf"]))
        fallback = _LLM("fb-big", types=["application/pdf"])

        replanned = AttachmentDispatch(agent).for_fallback(fallback, messages)

        assert any(p.get("type") == "file" for p in replanned.messages[-1]["content"])
        assert replanned.dispatch.usage_tokens(replanned.messages) > 0

    def test_without_a_merged_plan_there_is_nothing_to_replan(self):
        agent = _Agent(
            endpoint="stream",
            llm_name="openai",
            model_id="m",
            api_key="k",
            llm=_LLM("m"),
            llm_handler=LLMHandlerCreator.create_handler("openai"),
            decoded_token={"sub": "u"},
        )
        assert AttachmentDispatch(agent).for_fallback(_LLM("fb-big"), [{"role": "user", "content": "q"}]) is None

    def test_a_rebuilt_message_list_is_not_replanned(self):
        agent, _ = _merged_turn([text_att("a.txt", 1_000)])
        other = [{"role": "user", "content": "q"}]
        assert AttachmentDispatch(agent).for_fallback(_LLM("fb-big"), other) is None


class TestTheAgentHandsItsDispatchToTheLLM:
    def test_llm_gen_passes_the_dispatch(self):
        llm = Mock()
        llm.get_supported_attachment_types = Mock(return_value=[])
        agent = _Agent(
            endpoint="stream",
            llm_name="openai",
            model_id="m",
            api_key="k",
            llm=llm,
            llm_handler=Mock(),
            decoded_token={"sub": "u"},
            attachments=[text_att("a.txt", 10)],
        )
        agent._llm_gen([{"role": "user", "content": "q"}])

        dispatch = llm.gen_stream.call_args.kwargs["_attachment_dispatch"]
        assert isinstance(dispatch, AttachmentDispatch)
        assert isinstance(agent.attachment_plan, (AttachmentPlan, type(None)))


class TestUsageOfNativeParts:
    def test_text_inlined_by_the_plan_adds_nothing(self):
        agent, messages = _merged_turn([text_att("a.txt", 2_000)])
        assert AttachmentDispatch(agent).usage_tokens(messages) == 0

    def test_a_native_pdf_counts_at_the_plans_size(self):
        pdf = pdf_att("a.pdf", "PDF BODY " * 500)
        agent, messages = _merged_turn([pdf], primary=_LLM("m", types=["application/pdf"]))

        tokens = AttachmentDispatch(agent).usage_tokens(messages)

        assert tokens == agent.attachment_plan.native_tokens > 0

    def test_nothing_before_the_plan_is_merged(self):
        pdf = pdf_att("a.pdf", "PDF BODY " * 500)
        agent = _Agent(
            endpoint="stream",
            llm_name="openai",
            model_id="m",
            api_key="k",
            llm=_LLM("m", types=["application/pdf"]),
            llm_handler=LLMHandlerCreator.create_handler("openai"),
            decoded_token={"sub": "u"},
            attachments=[pdf],
            attachment_planning=True,
        )
        messages = agent._build_messages("system prompt", "q")
        assert AttachmentDispatch(agent).usage_tokens(messages) == 0

    def test_an_unplanned_turn_counts_only_what_the_provider_sends_natively(self):
        image = {"id": "img", "mime_type": "image/png", "token_count": 0}
        text = text_att("a.txt", 3_000)
        agent = _Agent(
            endpoint="stream",
            llm_name="openai",
            model_id="m",
            api_key="k",
            llm=_LLM("m", types=["image/png"]),
            llm_handler=LLMHandlerCreator.create_handler("openai"),
            decoded_token={"sub": "u"},
            attachments=[image, text],
        )
        assert AttachmentDispatch(agent).usage_tokens([]) == 1500


class TestFallbackUsage:
    def test_the_fallback_row_counts_its_own_prompt_once(self, monkeypatch):
        from tests.test_usage import _install_fake_token_repo
        from tests.llm.test_fallback import FakeLLM

        _install_fake_token_repo(monkeypatch)
        files = [text_att(f"r{i}.txt", 12_000) for i in range(3)]
        agent, messages = _merged_turn(files)
        primary = FakeLLM(fail_at=0, model_id="m")
        fallback = FakeLLM(stream_chunks=["fb"], model_id="fb-small")
        primary._fallback_llm = fallback

        list(
            primary.gen_stream(
                model="m",
                messages=messages,
                _usage_attachments=files,
                _attachment_dispatch=AttachmentDispatch(agent),
            )
        )

        sent = fallback.last_messages_received
        from docsgpt.usage import _count_prompt_tokens

        assert fallback.token_usage["prompt_tokens"] == _count_prompt_tokens(sent)
