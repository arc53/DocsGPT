import sys
import logging
from datetime import datetime

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.utils import num_tokens_from_object_or_list, num_tokens_from_string

logger = logging.getLogger(__name__)

mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]
usage_collection = db["token_usage"]


def _serialize_for_token_count(value):
    """Normalize payloads into token-countable primitives."""
    if isinstance(value, str):
        # Avoid counting large binary payloads in data URLs as text tokens.
        if value.startswith("data:") and ";base64," in value:
            return ""
        return value

    if value is None:
        return ""

    if isinstance(value, list):
        return [_serialize_for_token_count(item) for item in value]

    if isinstance(value, dict):
        serialized = {}
        for key, raw in value.items():
            key_lower = str(key).lower()

            # Skip raw binary-like fields; keep textual tool-call fields.
            if key_lower in {"data", "base64", "image_data"} and isinstance(raw, str):
                continue
            if key_lower == "url" and isinstance(raw, str) and ";base64," in raw:
                continue

            serialized[key] = _serialize_for_token_count(raw)
        return serialized

    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return _serialize_for_token_count(value.model_dump())
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return _serialize_for_token_count(value.to_dict())
    if hasattr(value, "__dict__"):
        return _serialize_for_token_count(vars(value))

    return str(value)


def _count_tokens(value):
    serialized = _serialize_for_token_count(value)
    if isinstance(serialized, str):
        return num_tokens_from_string(serialized)
    return num_tokens_from_object_or_list(serialized)


def _count_prompt_tokens(messages, tools=None, usage_attachments=None, **kwargs):
    prompt_tokens = 0

    for message in messages or []:
        if not isinstance(message, dict):
            prompt_tokens += _count_tokens(message)
            continue

        prompt_tokens += _count_tokens(message.get("content"))

        # Include tool-related message fields for providers that use OpenAI-native format.
        prompt_tokens += _count_tokens(message.get("tool_calls"))
        prompt_tokens += _count_tokens(message.get("tool_call_id"))
        prompt_tokens += _count_tokens(message.get("function_call"))
        prompt_tokens += _count_tokens(message.get("function_response"))

    # Count tool schema payload passed to the model.
    prompt_tokens += _count_tokens(tools)

    # Count structured-output/schema payloads when provided.
    prompt_tokens += _count_tokens(kwargs.get("response_format"))
    prompt_tokens += _count_tokens(kwargs.get("response_schema"))

    # Optional usage-only attachment context (not forwarded to provider).
    prompt_tokens += _count_tokens(usage_attachments)

    return prompt_tokens


def update_token_usage(decoded_token, user_api_key, token_usage, agent_id=None):
    if "pytest" in sys.modules:
        return
    user_id = decoded_token.get("sub") if isinstance(decoded_token, dict) else None
    normalized_agent_id = str(agent_id) if agent_id else None

    if not user_id and not user_api_key and not normalized_agent_id:
        logger.warning(
            "Skipping token usage insert: missing user_id, api_key, and agent_id"
        )
        return

    usage_data = {
        "user_id": user_id,
        "api_key": user_api_key,
        "prompt_tokens": token_usage["prompt_tokens"],
        "generated_tokens": token_usage["generated_tokens"],
        "timestamp": datetime.now(),
    }
    if normalized_agent_id:
        usage_data["agent_id"] = normalized_agent_id
    usage_collection.insert_one(usage_data)


def gen_token_usage(func):
    def wrapper(self, model, messages, stream, tools, **kwargs):
        usage_attachments = kwargs.pop("_usage_attachments", None)
        call_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        call_usage["prompt_tokens"] += _count_prompt_tokens(
            messages,
            tools=tools,
            usage_attachments=usage_attachments,
            **kwargs,
        )
        result = func(self, model, messages, stream, tools, **kwargs)
        call_usage["generated_tokens"] += _count_tokens(result)
        self.token_usage["prompt_tokens"] += call_usage["prompt_tokens"]
        self.token_usage["generated_tokens"] += call_usage["generated_tokens"]
        update_token_usage(
            self.decoded_token,
            self.user_api_key,
            call_usage,
            getattr(self, "agent_id", None),
        )
        return result

    return wrapper


def stream_token_usage(func):
    def wrapper(self, model, messages, stream, tools, **kwargs):
        usage_attachments = kwargs.pop("_usage_attachments", None)
        call_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        call_usage["prompt_tokens"] += _count_prompt_tokens(
            messages,
            tools=tools,
            usage_attachments=usage_attachments,
            **kwargs,
        )
        batch = []
        result = func(self, model, messages, stream, tools, **kwargs)
        for r in result:
            batch.append(r)
            yield r
        for line in batch:
            call_usage["generated_tokens"] += _count_tokens(line)
        self.token_usage["prompt_tokens"] += call_usage["prompt_tokens"]
        self.token_usage["generated_tokens"] += call_usage["generated_tokens"]
        update_token_usage(
            self.decoded_token,
            self.user_api_key,
            call_usage,
            getattr(self, "agent_id", None),
        )

    return wrapper
