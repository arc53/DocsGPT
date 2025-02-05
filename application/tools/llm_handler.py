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

        while True:
            response = agent.llm.gen(
                model=agent.gpt_model, messages=messages, tools=agent.tools
            )
            if response.candidates and response.candidates[0].content.parts:
                tool_call_found = False
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        tool_call_found = True
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


def get_llm_handler(llm_type):
    handlers = {
        "openai": OpenAILLMHandler(),
        "google": GoogleLLMHandler(),
    }
    return handlers.get(llm_type, OpenAILLMHandler())
