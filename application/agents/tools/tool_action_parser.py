import json
import logging

logger = logging.getLogger(__name__)


class ToolActionParser:
    def __init__(self, llm_type):
        self.llm_type = llm_type
        self.parsers = {
            "OpenAILLM": self._parse_openai_llm,
            "GoogleLLM": self._parse_google_llm,
        }

    def parse_args(self, call):
        parser = self.parsers.get(self.llm_type, self._parse_openai_llm)
        return parser(call)

    def _parse_openai_llm(self, call):
        try:
            call_args = json.loads(call.arguments)
            tool_parts = call.name.split("_")
            
            # If the tool name doesn't contain an underscore, it's likely a hallucinated tool
            if len(tool_parts) < 2:
                logger.warning(f"Invalid tool name format: {call.name}. Expected format: action_name_tool_id")
                return None, None, None
                
            tool_id = tool_parts[-1]
            action_name = "_".join(tool_parts[:-1])
            
            # Validate that tool_id looks like a numerical ID
            if not tool_id.isdigit():
                logger.warning(f"Tool ID '{tool_id}' is not numerical. This might be a hallucinated tool call.")
                
        except (AttributeError, TypeError) as e:
            logger.error(f"Error parsing OpenAI LLM call: {e}")
            return None, None, None
        return tool_id, action_name, call_args

    def _parse_google_llm(self, call):
        try:
            call_args = call.arguments
            tool_parts = call.name.split("_")
            
            # If the tool name doesn't contain an underscore, it's likely a hallucinated tool
            if len(tool_parts) < 2:
                logger.warning(f"Invalid tool name format: {call.name}. Expected format: action_name_tool_id")
                return None, None, None
                
            tool_id = tool_parts[-1]
            action_name = "_".join(tool_parts[:-1])
            
            # Validate that tool_id looks like a numerical ID
            if not tool_id.isdigit():
                logger.warning(f"Tool ID '{tool_id}' is not numerical. This might be a hallucinated tool call.")
                
        except (AttributeError, TypeError) as e:
            logger.error(f"Error parsing Google LLM call: {e}")
            return None, None, None
        return tool_id, action_name, call_args
