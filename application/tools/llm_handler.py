import json
from abc import ABC, abstractmethod


class LLMHandler(ABC):
    @abstractmethod
    def handle_response(self, agent, resp, tools_dict, messages, **kwargs):
        pass


class OpenAILLMHandler(LLMHandler):
    def handle_response(self, agent, resp, tools_dict, messages):
        while resp.finish_reason == "tool_calls":
            message = json.loads(resp.model_dump_json())["message"]
            keys_to_remove = {"audio", "function_call", "refusal"}
            filtered_data = {
                k: v for k, v in message.items() if k not in keys_to_remove
            }
            messages.append(filtered_data)

            tool_calls = resp.message.tool_calls
            for call in tool_calls:
                try:
                    tool_response, call_id = agent._execute_tool_action(
                        tools_dict, call
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "content": str(tool_response),
                            "tool_call_id": call_id,
                        }
                    )
                except Exception as e:
                    messages.append(
                        {
                            "role": "tool",
                            "content": f"Error executing tool: {str(e)}",
                            "tool_call_id": call_id,
                        }
                    )
            resp = agent.llm.gen(
                model=agent.gpt_model, messages=messages, tools=agent.tools
            )
        return resp


class GoogleLLMHandler(LLMHandler):
    def handle_response(self, agent, resp, tools_dict, messages):
        from google.genai import types

        while resp.content.parts[0].function_call:
            function_call_part = resp.candidates[0].content.parts[0]
            tool_response, call_id = agent._execute_tool_action(
                tools_dict, function_call_part.function_call
            )
            function_response_part = types.Part.from_function_response(
                name=function_call_part.function_call.name, response=tool_response
            )

            messages.append(function_call_part, function_response_part)
            resp = agent.llm.gen(
                model=agent.gpt_model, messages=messages, tools=agent.tools
            )

        return resp


def get_llm_handler(llm_type):
    handlers = {
        "openai": OpenAILLMHandler(),
        "google": GoogleLLMHandler(),
    }
    return handlers.get(llm_type, OpenAILLMHandler())
