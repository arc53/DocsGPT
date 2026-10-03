"""Images a tool returned reach the model with that tool's result.

The handler puts the images a call queued on its tool message as references;
each provider renders them when it sends the request: inside the tool result
(Anthropic, the Responses API, Gemini 3), in a user message after the run of
tool results (Chat Completions, earlier Gemini), or as a note for a model
that reads no images.
"""

import base64
import io
import types
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, Mock

import pytest
from PIL import Image

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.core.model_settings import ModelCapabilities
from docsgpt.llm import tool_images
from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall
from docsgpt.llm.handlers.openai import OpenAILLMHandler

pytestmark = pytest.mark.unit


def _png(size=(40, 30), mode="RGB", fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, fmt)
    return out.getvalue()


PNG_B64 = base64.b64encode(_png()).decode()
SHOT = {"label": "A1 chart.png", "mime_type": "image/png", "data": PNG_B64}


def _conversation(*images):
    tool = {"role": "tool", "tool_call_id": "c1", "content": "Image A1 chart.png is shown with this result."}
    if images:
        tool["images"] = list(images)
    return [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "view_image", "arguments": "{}"}},
        ]},
        tool,
    ]


class TestNormalize:
    def test_a_small_png_is_sent_as_stored(self):
        raw = _png()
        assert tool_images.normalize_image(raw) == ("image/png", raw)

    def test_a_large_image_is_scaled_down_the_same_way_every_time(self):
        raw = _png(size=(4000, 1000))
        first = tool_images.normalize_image(raw)
        assert first == tool_images.normalize_image(raw)
        assert first[0] == "image/jpeg"
        assert Image.open(io.BytesIO(first[1])).size == (tool_images.MAX_SIDE, 500)

    def test_other_formats_are_converted(self):
        mime_type, data = tool_images.normalize_image(_png(fmt="GIF"))
        assert mime_type == "image/jpeg"
        assert Image.open(io.BytesIO(data)).format == "JPEG"

    def test_transparency_is_kept_as_png(self):
        mime_type, data = tool_images.normalize_image(_png(size=(3000, 10), mode="RGBA"))
        assert mime_type == "image/png"
        assert Image.open(io.BytesIO(data)).mode == "RGBA"

    def test_a_file_that_is_no_image_is_refused(self):
        with pytest.raises(ValueError):
            tool_images.normalize_image(b"%PDF-1.4 not an image")

    def test_a_truncated_image_is_refused_not_sent(self):
        out = io.BytesIO()
        Image.new("RGB", (64, 64), "blue").save(out, "JPEG")
        with pytest.raises(ValueError):
            tool_images.normalize_image(out.getvalue()[:-40])


class TestToolResult:
    def test_images_come_out_ready_to_send(self):
        text, shown = tool_images.tool_result(_conversation(SHOT)[-1], vision=True)
        assert text.startswith("Image A1")
        assert shown == [("A1 chart.png", "image/png", PNG_B64)]

    def test_a_model_without_vision_gets_a_note(self):
        text, shown = tool_images.tool_result(_conversation(SHOT)[-1], vision=False)
        assert shown == []
        assert "does not read images (A1 chart.png)" in text

    def test_an_image_that_cannot_be_loaded_is_named(self, monkeypatch):
        monkeypatch.setattr(tool_images, "_stored", Mock(side_effect=FileNotFoundError))
        message = _conversation({"label": "A2 gone.png", "path": "inputs/u/gone.png"})[-1]
        text, shown = tool_images.tool_result(message, vision=True)
        assert shown == []
        assert "could not be loaded: A2 gone.png" in text

    def test_a_stored_image_is_read_once(self, monkeypatch):
        tool_images._stored.cache_clear()
        storage = Mock()
        storage.get_file = Mock(side_effect=lambda path: io.BytesIO(_png()))
        monkeypatch.setattr(
            "docsgpt.storage.storage_creator.StorageCreator.get_storage", Mock(return_value=storage)
        )
        ref = {"label": "F1 x.png", "path": "inputs/u/cached.png"}
        assert tool_images.load_image(ref) == tool_images.load_image(ref)
        storage.get_file.assert_called_once_with("inputs/u/cached.png")
        tool_images._stored.cache_clear()


class TestReplay:
    def test_an_earlier_turns_result_says_its_images_are_gone(self):
        text = tool_images.replayed_result({"result": "Image A1 chart.png is shown with this result.",
                                            "images": ["A1 chart.png"]})
        assert "not kept in the history: A1 chart.png" in text

    def test_a_result_without_images_is_unchanged(self):
        assert tool_images.replayed_result({"result": {"a": 1}}) == '{"a": 1}'


class TestClientResults:
    @pytest.mark.parametrize(
        "part",
        [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}},
            {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG_B64}},
        ],
    )
    def test_inline_images_are_split_out(self, part):
        result, refs = tool_images.split_content([{"type": "text", "text": "done"}, part], "screenshot")
        assert result == "done"
        assert refs[0]["label"] == "screenshot image 1"
        assert refs[0]["data"] == PNG_B64

    def test_a_remote_image_stays_text(self):
        part = {"type": "image_url", "image_url": {"url": "https://x.test/a.png"}}
        result, refs = tool_images.split_content([part])
        assert result == [part] and refs == []

    def test_a_plain_result_is_untouched(self):
        assert tool_images.split_content({"ok": True}) == ({"ok": True}, [])


def _openai(monkeypatch, flavor="chat_completions", attachments=("image/png",)):
    from tests.llm.test_openai_responses import _make_llm

    caps = ModelCapabilities(api_flavor=flavor, supported_attachment_types=list(attachments))
    return _make_llm(monkeypatch, caps)


class TestOpenAI:
    def test_chat_completions_shows_them_in_a_user_message_after_the_results(self, monkeypatch):
        llm = _openai(monkeypatch)
        messages = [*_conversation(SHOT), {"role": "assistant", "content": "It is red."}]
        cleaned = llm._clean_messages_openai(messages)

        assert [m["role"] for m in cleaned] == ["system", "user", "assistant", "tool", "user", "assistant"]
        assert cleaned[3]["content"].startswith("Image A1") and "images" not in cleaned[3]
        note, image = cleaned[4]["content"]
        assert "A1 chart.png" in note["text"] and "untrusted" in note["text"]
        assert image["image_url"]["url"] == f"data:image/png;base64,{PNG_B64}"

    def test_one_user_message_follows_a_parallel_batch(self, monkeypatch):
        llm = _openai(monkeypatch)
        messages = _conversation(SHOT)
        messages[2]["tool_calls"].append(
            {"id": "c2", "type": "function", "function": {"name": "view_image", "arguments": "{}"}}
        )
        messages.append({"role": "tool", "tool_call_id": "c2", "content": "two", "images": [dict(SHOT, label="B")]})
        cleaned = llm._clean_messages_openai(messages)
        assert [m["role"] for m in cleaned] == ["system", "user", "assistant", "tool", "tool", "user"]
        assert len(cleaned[-1]["content"]) == 3

    def test_responses_puts_them_inside_the_function_call_output(self, monkeypatch):
        llm = _openai(monkeypatch, flavor="responses")
        items = llm._to_responses_input(llm._clean_messages_openai(_conversation(SHOT)))

        output = items[-1]
        assert output["type"] == "function_call_output"
        assert output["output"][0] == {"type": "input_text", "text": "Image A1 chart.png is shown with this result."}
        assert output["output"][1] == {
            "type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}", "detail": "auto",
        }
        assert not any(item.get("role") == "user" and item is not items[1] for item in items[2:])

    def test_a_model_without_vision_gets_text_only(self, monkeypatch):
        llm = _openai(monkeypatch, attachments=())
        cleaned = llm._clean_messages_openai(_conversation(SHOT))
        assert cleaned[-1]["role"] == "tool"
        assert "does not read images" in cleaned[-1]["content"]


class TestPlacementOverride:
    """A model's ``tool_result_images`` overrides where its wire API puts them."""

    def test_follow_up_on_the_responses_api(self, monkeypatch):
        llm = _openai(monkeypatch, flavor="responses")
        llm.capabilities.tool_result_images = "follow_up"
        items = llm._to_responses_input(llm._clean_messages_openai(_conversation(SHOT)))

        output, follow_up = items[-2:]
        assert output["type"] == "function_call_output" and isinstance(output["output"], str)
        assert follow_up["role"] == "user"
        assert follow_up["content"][1] == {
            "type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}", "detail": "auto",
        }

    def test_native_on_chat_completions(self, monkeypatch):
        llm = _openai(monkeypatch)
        llm.capabilities.tool_result_images = "native"
        cleaned = llm._clean_messages_openai(_conversation(SHOT))

        assert cleaned[-1]["role"] == "tool"
        text, image = cleaned[-1]["content"]
        assert text["type"] == "text" and image["image_url"]["url"].endswith(PNG_B64)

    def test_follow_up_on_gemini_3(self):
        from docsgpt.llm.google_ai import GoogleLLM

        llm = GoogleLLM.__new__(GoogleLLM)
        llm.capabilities = ModelCapabilities(supported_attachment_types=["image/png"], tool_result_images="follow_up")
        contents, _ = llm._clean_messages_google(_conversation(SHOT), "gemini-3.5-flash")
        response, note, image = contents[-1].parts
        assert response.function_response.parts is None
        assert "A1 chart.png" in note.text and image.inline_data.data == base64.b64decode(PNG_B64)

    def test_an_unknown_value_is_refused_in_a_model_yaml(self):
        from docsgpt.core.model_yaml import _CapabilityFields

        assert _CapabilityFields(tool_result_images="follow_up").tool_result_images == "follow_up"
        with pytest.raises(ValueError):
            _CapabilityFields(tool_result_images="inline")


class TestAnthropic:
    def test_they_go_inside_the_tool_result_with_no_text_after_it(self):
        from docsgpt.llm.anthropic import AnthropicLLM

        mapped, _system = AnthropicLLM._clean_messages_anthropic(_conversation(SHOT))
        last = mapped[-1]
        assert last["role"] == "user" and [b["type"] for b in last["content"]] == ["tool_result"]
        text, image = last["content"][0]["content"]
        assert text == {"type": "text", "text": "Image A1 chart.png is shown with this result."}
        assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG_B64}}


class TestGoogle:
    def _llm(self):
        from docsgpt.llm.google_ai import GoogleLLM

        llm = GoogleLLM.__new__(GoogleLLM)
        llm.capabilities = None
        llm.model_id = "gemini-3.5-flash"
        return llm

    def test_gemini_3_takes_them_inside_the_function_response(self):
        llm = self._llm()
        contents, _ = llm._clean_messages_google(_conversation(SHOT), "gemini-3.5-flash")

        responses = contents[-1]
        assert responses.role == "user"
        response = responses.parts[0].function_response
        assert response.name == "view_image"
        assert response.response == {"result": "Image A1 chart.png is shown with this result."}
        blob = response.parts[0].inline_data
        assert (blob.mime_type, blob.data) == ("image/png", base64.b64decode(PNG_B64))

    def test_a_batch_answers_in_one_turn(self):
        llm = self._llm()
        messages = _conversation()
        messages[2]["tool_calls"].append(
            {"id": "c2", "type": "function", "function": {"name": "read_webpage", "arguments": "{}"}}
        )
        messages.append({"role": "tool", "tool_call_id": "c2", "content": "page"})
        contents, _ = llm._clean_messages_google(messages, "gemini-3.5-flash")
        assert [p.function_response.name for p in contents[-1].parts] == ["view_image", "read_webpage"]

    def test_earlier_models_get_them_after_the_responses_in_the_same_turn(self):
        llm = self._llm()
        contents, _ = llm._clean_messages_google([*_conversation(SHOT), {"role": "user", "content": "next"}],
                                                 "gemini-2.5-flash")
        turn = contents[-1]
        assert turn.role == "user" and contents[-2].role == "model"
        response, note, image, question = turn.parts
        assert response.function_response.parts is None
        assert "A1 chart.png" in note.text
        assert image.inline_data.data == base64.b64decode(PNG_B64)
        assert question.text == "next"


class _Handler(LLMHandler):
    def parse_response(self, response: Any) -> LLMResponse:
        return LLMResponse(content=str(response), tool_calls=[], finish_reason="stop", raw_response=response)

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response: Any) -> Generator:
        yield from response


def _run(gen):
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


class TestHandler:
    def _agent(self, queued_by_call):
        executor = Mock()
        executor.pending_native_parts = []
        executor.check_pause = Mock(return_value=None)

        def _execute(tools_dict, call):
            executor.pending_native_parts = list(queued_by_call.get(call.id, []))
            yield {"type": "tool_call", "data": {}}
            return f"result {call.id}", call.id

        agent = Mock()
        agent.tool_executor = executor
        agent._check_context_limit = Mock(return_value=False)
        agent._execute_tool_action = Mock(side_effect=_execute)
        agent.llm.__class__.__name__ = "OpenAILLM"
        return agent

    def test_each_calls_images_go_on_its_own_tool_message(self):
        agent = self._agent({"c2": [SHOT]})
        calls = [ToolCall(id="c1", name="a", arguments={}), ToolCall(id="c2", name="b", arguments={})]
        messages, pending = _run(_Handler().handle_tool_calls(agent, calls, {}, [{"role": "user", "content": "q"}]))

        assert pending is None
        assert [m["role"] for m in messages] == ["user", "assistant", "tool", "tool"]
        assert "images" not in messages[2]
        assert messages[3]["images"] == [SHOT]
        assert agent.tool_executor.pending_native_parts == []

    def test_research_steps_keep_them_on_the_tool_message(self):
        from docsgpt.agents.research_agent import ResearchAgent

        agent = ResearchAgent.__new__(ResearchAgent)
        agent.llm = Mock()
        agent.llm.__class__.__name__ = "OpenAILLM"
        agent.llm_handler = _Handler()
        executor = Mock()
        executor.pending_native_parts = []
        executor.check_pause = Mock(return_value=None)

        def _execute(tools_dict, call, llm_class):
            executor.pending_native_parts = [SHOT]
            yield {"type": "tool_call", "data": {}}
            return "shown", call.id

        executor.execute = Mock(side_effect=_execute)
        messages, _ = agent._execute_step_tools_with_refinement(
            [ToolCall(id="c1", name="view_image", arguments={})], {}, [{"role": "user", "content": "q"}],
            executor, False,
        )
        assert messages[-1]["role"] == "tool" and messages[-1]["images"] == [SHOT]


class TestExecutor:
    def _execute(self, monkeypatch, executor, parts, result="ok"):
        fake = Mock()
        fake.execute_action = Mock(return_value=result)
        fake.drain_native_parts = Mock(return_value=list(parts))
        fake.get_artifact_id = None
        fake.get_artifacts = None
        tools_dict = {"t1": {"name": "view_image", "actions": [{"name": "view_image", "active": True,
                                                              "parameters": {"type": "object", "properties": {}}}]}}
        executor.prepare_tools_for_llm(tools_dict)
        monkeypatch.setattr(executor, "_get_or_load_tool", lambda *a, **k: fake)
        monkeypatch.setattr("docsgpt.agents.tool_executor._record_proposed", lambda *a, **k: False)
        monkeypatch.setattr("docsgpt.agents.tool_executor._mark_executed", lambda *a, **k: None)
        call = types.SimpleNamespace(id="c1", name="view_image", arguments={}, thought_signature=None)
        return _run(executor.execute(tools_dict, call, "OpenAILLM"))

    def test_queued_images_are_taken_and_named_on_the_call(self, monkeypatch):
        executor = ToolExecutor(user="u")
        self._execute(monkeypatch, executor, [SHOT])
        assert executor.pending_native_parts == [SHOT]
        assert executor.tool_calls[-1]["images"] == ["A1 chart.png"]
        assert executor.get_truncated_tool_calls()[-1]["images"] == ["A1 chart.png"]

    def test_images_past_the_turns_limit_are_dropped_with_a_note(self, monkeypatch):
        monkeypatch.setattr("docsgpt.core.settings.settings.ATTACHMENT_MAX_NATIVE_PARTS", 1)
        executor = ToolExecutor(user="u")
        result, _ = self._execute(monkeypatch, executor, [SHOT, dict(SHOT, label="two")])
        assert executor.pending_native_parts == [SHOT]
        assert "1 image(s) not shown" in result
        executor.pending_native_parts = []
        result, _ = self._execute(monkeypatch, executor, [SHOT], result={"status": "ok"})
        assert executor.pending_native_parts == []
        assert "images_not_shown" in result


class TestContinuation:
    def test_a_client_results_images_go_on_its_tool_message(self):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent.__new__(ClassicAgent)
        agent.llm = MagicMock()
        agent.llm_handler = OpenAILLMHandler()
        agent.tool_executor = MagicMock()
        agent._prepare_tools = Mock()
        agent._guard_tool_result_text = lambda text: text
        agent.retrieved_docs = []
        agent._get_truncated_tool_calls = Mock(return_value=[])
        agent._emit_responses_metadata = Mock(return_value=iter([]))
        sent = {}

        def _gen(messages, **kwargs):
            sent["messages"] = list(messages)
            return iter([])

        agent._llm_gen = _gen
        agent._handle_response = Mock(return_value=iter([]))
        pending = [{"call_id": "c1", "name": "screenshot", "arguments": {}}]
        result = [{"type": "text", "text": "taken"},
                  {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}}]
        list(agent._gen_continuation_inner([{"role": "user", "content": "q"}], {}, pending,
                                           [{"call_id": "c1", "result": result}]))

        tool = sent["messages"][-1]
        assert tool["role"] == "tool" and tool["content"] == "taken"
        assert tool["images"][0]["label"] == "screenshot image 1"
        assert PNG_B64 not in tool["content"]


class TestTokenCounting:
    def test_images_are_counted_per_image_not_by_their_bytes(self):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter
        from docsgpt.usage import _count_prompt_tokens

        message = _conversation(SHOT, SHOT)[-1]
        assert TokenCounter.count_message_tokens([message]) < 2 * tool_images.IMAGE_TOKENS + 50
        assert TokenCounter.count_message_tokens([message]) >= 2 * tool_images.IMAGE_TOKENS
        assert 2 * tool_images.IMAGE_TOKENS <= _count_prompt_tokens([message]) < 2 * tool_images.IMAGE_TOKENS + 50
