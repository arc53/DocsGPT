import json
from abc import ABC, abstractmethod

from application.logging import build_stack_data


class LLMHandler(ABC):
    def __init__(self):
        self.llm_calls = []
        self.tool_calls = []

    @abstractmethod
    def handle_response(self, agent, resp, tools_dict, messages, **kwargs):
        pass


class OpenAILLMHandler(LLMHandler):
    def handle_response(self, agent, resp, tools_dict, messages, stream: bool = True):
        if not stream:
            while hasattr(resp, "finish_reason") and resp.finish_reason == "tool_calls":
                message = json.loads(resp.model_dump_json())["message"]
                keys_to_remove = {"audio", "function_call", "refusal"}
                filtered_data = {
                    k: v for k, v in message.items() if k not in keys_to_remove
                }
                messages.append(filtered_data)

                tool_calls = resp.message.tool_calls
                for call in tool_calls:
                    try:
                        self.tool_calls.append(call)
                        tool_response, call_id = agent._execute_tool_action(
                            tools_dict, call
                        )
                        function_call_dict = {
                            "function_call": {
                                "name": call.function.name,
                                "args": call.function.arguments,
                                "call_id": call_id,
                            }
                        }
                        function_response_dict = {
                            "function_response": {
                                "name": call.function.name,
                                "response": {"result": tool_response},
                                "call_id": call_id,
                            }
                        }

                        messages.append(
                            {"role": "assistant", "content": [function_call_dict]}
                        )
                        messages.append(
                            {"role": "tool", "content": [function_response_dict]}
                        )

                    except Exception as e:
                        messages.append(
                            {
                                "role": "tool",
                                "content": f"Error executing tool: {str(e)}",
                                "tool_call_id": call_id,
                            }
                        )
                resp = agent.llm.gen_stream(
                    model=agent.gpt_model, messages=messages, tools=agent.tools
                )
                self.llm_calls.append(build_stack_data(agent.llm))
            return resp

        else:
            while True:
                tool_calls = {}
                for chunk in resp:
                    if isinstance(chunk, str) and len(chunk) > 0:
                        return
                    elif hasattr(chunk, "delta"): 
                        chunk_delta = chunk.delta

                        if (
                            hasattr(chunk_delta, "tool_calls")
                            and chunk_delta.tool_calls is not None
                        ):
                            for tool_call in chunk_delta.tool_calls:
                                index = tool_call.index
                                if index not in tool_calls:
                                    tool_calls[index] = {
                                        "id": "",
                                        "function": {"name": "", "arguments": ""},
                                    }

                                current = tool_calls[index]
                                if tool_call.id:
                                    current["id"] = tool_call.id
                                if tool_call.function.name:
                                    current["function"][
                                        "name"
                                    ] = tool_call.function.name
                                if tool_call.function.arguments:
                                    current["function"][
                                        "arguments"
                                    ] += tool_call.function.arguments
                                tool_calls[index] = current

                        if (
                            hasattr(chunk, "finish_reason")
                            and chunk.finish_reason == "tool_calls"
                        ):
                            for index in sorted(tool_calls.keys()):
                                call = tool_calls[index]
                                try:
                                    self.tool_calls.append(call)
                                    tool_response, call_id = agent._execute_tool_action(
                                        tools_dict, call
                                    )
                                    if isinstance(call["function"]["arguments"], str):
                                        call["function"]["arguments"] = json.loads(call["function"]["arguments"])

                                    function_call_dict = {
                                        "function_call": {
                                            "name": call["function"]["name"],
                                            "args": call["function"]["arguments"],
                                            "call_id": call["id"],
                                        }
                                    }
                                    function_response_dict = {
                                        "function_response": {
                                            "name": call["function"]["name"],
                                            "response": {"result": tool_response},
                                            "call_id": call["id"],
                                        }
                                    }

                                    messages.append(
                                        {
                                            "role": "assistant",
                                            "content": [function_call_dict],
                                        }
                                    )
                                    messages.append(
                                        {
                                            "role": "tool",
                                            "content": [function_response_dict],
                                        }
                                    )

                                except Exception as e:
                                    messages.append(
                                        {
                                            "role": "assistant",
                                            "content": f"Error executing tool: {str(e)}",
                                        }
                                    )
                            tool_calls = {}

                        if (
                            hasattr(chunk, "finish_reason")
                            and chunk.finish_reason == "stop"
                        ):
                            return
                    elif isinstance(chunk, str) and len(chunk) == 0:
                            continue

                resp = agent.llm.gen_stream(
                    model=agent.gpt_model, messages=messages, tools=agent.tools
                )
                self.llm_calls.append(build_stack_data(agent.llm))


class GoogleLLMHandler(LLMHandler):
    def handle_response(self, agent, resp, tools_dict, messages, stream: bool = True):
        from google.genai import types

        while True:
            if not stream:
                response = agent.llm.gen(
                    model=agent.gpt_model, messages=messages, tools=agent.tools
                )
                self.llm_calls.append(build_stack_data(agent.llm))
                if response.candidates and response.candidates[0].content.parts:
                    tool_call_found = False
                    for part in response.candidates[0].content.parts:
                        if part.function_call:
                            tool_call_found = True
                            self.tool_calls.append(part.function_call)
                            tool_response, call_id = agent._execute_tool_action(
                                tools_dict, part.function_call
                            )
                            function_response_part = types.Part.from_function_response(
                                name=part.function_call.name,
                                response={"result": tool_response},
                            )

                            messages.append(
                                {"role": "model", "content": [part.to_json_dict()]}
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "content": [function_response_part.to_json_dict()],
                                }
                            )

                    if (
                        not tool_call_found
                        and response.candidates[0].content.parts
                        and response.candidates[0].content.parts[0].text
                    ):
                        return response.candidates[0].content.parts[0].text
                    elif not tool_call_found:
                        return response.candidates[0].content.parts

                else:
                    return response

            else:
                response = agent.llm.gen_stream(
                    model=agent.gpt_model, messages=messages, tools=agent.tools
                )
                self.llm_calls.append(build_stack_data(agent.llm))

                tool_call_found = False
                for result in response:
                    if hasattr(result, "function_call"):
                        tool_call_found = True
                        self.tool_calls.append(result.function_call)
                        tool_response, call_id = agent._execute_tool_action(
                            tools_dict, result.function_call
                        )
                        function_response_part = types.Part.from_function_response(
                            name=result.function_call.name,
                            response={"result": tool_response},
                        )

                        messages.append(
                            {"role": "model", "content": [result.to_json_dict()]}
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "content": [function_response_part.to_json_dict()],
                            }
                        )

                if not tool_call_found:
                    return response


def get_llm_handler(llm_type):
    handlers = {
        "openai": OpenAILLMHandler(),
        "google": GoogleLLMHandler(),
    }
    return handlers.get(llm_type, OpenAILLMHandler())
