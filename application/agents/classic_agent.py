import uuid
from typing import Dict, Generator

from application.agents.base import BaseAgent
from application.logging import build_stack_data, log_activity, LogContext

from application.retriever.base import BaseRetriever


class ClassicAgent(BaseAgent):
    def __init__(
        self,
        endpoint,
        llm_name,
        gpt_model,
        api_key,
        user_api_key=None,
        prompt="",
        chat_history=None,
    ):
        super().__init__(endpoint, llm_name, gpt_model, api_key, user_api_key)
        self.prompt = prompt
        self.chat_history = chat_history if chat_history is not None else []

    @log_activity()
    def gen(
        self, query: str, retriever: BaseRetriever, log_context: LogContext = None
    ) -> Generator[Dict, None, None]:
        yield from self._gen_inner(query, retriever, log_context)

    def _gen_inner(
        self, query: str, retriever: BaseRetriever, log_context: LogContext
    ) -> Generator[Dict, None, None]:
        retrieved_data = self._retriever_search(retriever, query, log_context)

        docs_together = "\n".join([doc["text"] for doc in retrieved_data])
        p_chat_combine = self.prompt.replace("{summaries}", docs_together)
        messages_combine = [{"role": "system", "content": p_chat_combine}]

        if len(self.chat_history) > 0:
            for i in self.chat_history:
                if "prompt" in i and "response" in i:
                    messages_combine.append({"role": "user", "content": i["prompt"]})
                    messages_combine.append(
                        {"role": "assistant", "content": i["response"]}
                    )
                if "tool_calls" in i:
                    for tool_call in i["tool_calls"]:
                        call_id = tool_call.get("call_id")
                        if call_id is None or call_id == "None":
                            call_id = str(uuid.uuid4())

                        function_call_dict = {
                            "function_call": {
                                "name": tool_call.get("action_name"),
                                "args": tool_call.get("arguments"),
                                "call_id": call_id,
                            }
                        }
                        function_response_dict = {
                            "function_response": {
                                "name": tool_call.get("action_name"),
                                "response": {"result": tool_call.get("result")},
                                "call_id": call_id,
                            }
                        }

                        messages_combine.append(
                            {"role": "assistant", "content": [function_call_dict]}
                        )
                        messages_combine.append(
                            {"role": "tool", "content": [function_response_dict]}
                        )
        messages_combine.append({"role": "user", "content": query})

        tools_dict = self._get_user_tools()
        self._prepare_tools(tools_dict)

        resp = self._llm_gen(messages_combine, log_context)

        if isinstance(resp, str):
            yield {"answer": resp}
            return
        if (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            yield {"answer": resp.message.content}
            return

        resp = self._llm_handler(resp, tools_dict, messages_combine, log_context)

        if isinstance(resp, str):
            yield {"answer": resp}
        elif (
            hasattr(resp, "message")
            and hasattr(resp.message, "content")
            and resp.message.content is not None
        ):
            yield {"answer": resp.message.content}
        else:
            completion = self.llm.gen_stream(
                model=self.gpt_model, messages=messages_combine, tools=self.tools
            )
            for line in completion:
                if isinstance(line, str):
                    yield {"answer": line}

        yield {"sources": retrieved_data}
        yield {"tool_calls": self.tool_calls.copy()}

    def _retriever_search(self, retriever, query, log_context):
        retrieved_data = retriever.search(query)
        if log_context:
            data = build_stack_data(retriever, exclude_attributes=["llm"])
            log_context.stacks.append({"component": "retriever", "data": data})
        return retrieved_data

    def _llm_gen(self, messages_combine, log_context):
        resp = self.llm.gen_stream(
            model=self.gpt_model, messages=messages_combine, tools=self.tools
        )
        if log_context:
            data = build_stack_data(self.llm)
            log_context.stacks.append({"component": "llm", "data": data})
        return resp

    def _llm_handler(self, resp, tools_dict, messages_combine, log_context):
        resp = self.llm_handler.handle_response(
            self, resp, tools_dict, messages_combine
        )
        if log_context:
            data = build_stack_data(self.llm_handler)
            log_context.stacks.append({"component": "llm_handler", "data": data})
        return resp
