import json
import logging

logger = logging.getLogger(__name__)


class ToolActionParser:
    def __init__(self, llm_type, name_mapping=None):
        self.llm_type = llm_type
        self.name_mapping = name_mapping
        self.parsers = {
            "OpenAILLM": self._parse_openai_llm,
            "GoogleLLM": self._parse_google_llm,
        }

    def parse_args(self, call):
        parser = self.parsers.get(self.llm_type, self._parse_openai_llm)
        return parser(call)

    def _resolve_via_mapping(self, call_name):
        """Look up (tool_id, action_name) from the name mapping if available."""
        if self.name_mapping and call_name in self.name_mapping:
            return self.name_mapping[call_name]
        return None

    def _parse_openai_llm(self, call):
        try:
            call_args = json.loads(call.arguments)

            resolved = self._resolve_via_mapping(call.name)
            if resolved:
                return resolved[0], resolved[1], call_args

            # Fallback: legacy split on "_" for backward compatibility
            tool_parts = call.name.split("_")

            if len(tool_parts) < 2:
                logger.warning(
                    f"Invalid tool name format: {call.name}. "
                    "Could not resolve via mapping or legacy parsing."
                )
                return None, None, None

            tool_id = tool_parts[-1]
            action_name = "_".join(tool_parts[:-1])

            if not tool_id.isdigit():
                logger.warning(
                    f"Tool ID '{tool_id}' is not numerical. This might be a hallucinated tool call."
                )

        except (AttributeError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"Error parsing OpenAI LLM call: {e}")
            return None, None, None
        return tool_id, action_name, call_args

    def _parse_google_llm(self, call):
        try:
            call_args = call.arguments
            # Gemini's SDK natively returns ``args`` as a dict, but the
            # resume path (``gen_continuation``) stringifies it for the
            # assistant message. Coerce a JSON string back into a dict;
            # fall back to an empty dict on malformed input so downstream
            # ``call_args.items()`` doesn't crash the stream.
            if isinstance(call_args, str):
                try:
                    call_args = json.loads(call_args)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Google call.arguments was not valid JSON; "
                        "falling back to empty args for %s",
                        getattr(call, "name", "<unknown>"),
                    )
                    call_args = {}
            if not isinstance(call_args, dict):
                logger.warning(
                    "Google call.arguments has unexpected type %s; "
                    "falling back to empty args for %s",
                    type(call_args).__name__,
                    getattr(call, "name", "<unknown>"),
                )
                call_args = {}

            resolved = self._resolve_via_mapping(call.name)
            if resolved:
                return resolved[0], resolved[1], call_args

            # Fallback: legacy split on "_" for backward compatibility
            tool_parts = call.name.split("_")

            if len(tool_parts) < 2:
                logger.warning(
                    f"Invalid tool name format: {call.name}. "
                    "Could not resolve via mapping or legacy parsing."
                )
                return None, None, None

            tool_id = tool_parts[-1]
            action_name = "_".join(tool_parts[:-1])

            if not tool_id.isdigit():
                logger.warning(
                    f"Tool ID '{tool_id}' is not numerical. This might be a hallucinated tool call."
                )

        except (AttributeError, TypeError) as e:
            logger.error(f"Error parsing Google LLM call: {e}")
            return None, None, None
        return tool_id, action_name, call_args
