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
        import google.generativeai as genai

        while (
            hasattr(resp.candidates[0].content.parts[0], "function_call")
            and resp.candidates[0].content.parts[0].function_call
        ):
            responses = {}
            for part in resp.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    function_call_part = part
                    messages.append(
                        genai.protos.Part(
                            function_call=genai.protos.FunctionCall(
                                name=function_call_part.function_call.name,
                                args=function_call_part.function_call.args,
                            )
                        )
                    )
                    tool_response, call_id = agent._execute_tool_action(
                        tools_dict, function_call_part.function_call
                    )
                    responses[function_call_part.function_call.name] = tool_response
            response_parts = [
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=tool_name, response={"result": response}
                    )
                )
                for tool_name, response in responses.items()
            ]
            if response_parts:
                messages.append(response_parts)
            resp = agent.llm.gen(
                model=agent.gpt_model, messages=messages, tools=agent.tools
            )

        return resp.text


def get_llm_handler(llm_type):
    handlers = {
        "openai": OpenAILLMHandler(),
        "google": GoogleLLMHandler(),
    }
    return handlers.get(llm_type, OpenAILLMHandler())
