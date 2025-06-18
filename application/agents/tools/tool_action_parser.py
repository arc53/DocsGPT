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
            tool_id = call.name.split("_")[-1]
            action_name = call.name.rsplit("_", 1)[0]
        except (AttributeError, TypeError) as e:
            logger.error(f"Error parsing OpenAI LLM call: {e}")
            return None, None, None
        return tool_id, action_name, call_args

    def _parse_google_llm(self, call):
        try:
            call_args = call.arguments
            tool_id = call.name.split("_")[-1]
            action_name = call.name.rsplit("_", 1)[0]
        except (AttributeError, TypeError) as e:
            logger.error(f"Error parsing Google LLM call: {e}")
            return None, None, None
        return tool_id, action_name, call_args
