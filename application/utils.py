import hashlib
import os
import re
import uuid

import tiktoken
from flask import jsonify, make_response
from werkzeug.utils import secure_filename

from application.core.settings import settings


_encoding = None


def get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def get_gpt_model() -> str:
    """Get the appropriate GPT model based on provider"""
    model_map = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-2",
        "groq": "llama3-8b-8192",
        "novita": "deepseek/deepseek-r1",
    }
    return settings.LLM_NAME or model_map.get(settings.LLM_PROVIDER, "")


def safe_filename(filename):
    """
    Creates a safe filename that preserves the original extension.
    Uses secure_filename, but ensures a proper filename is returned even with non-Latin characters.

    Args:
        filename (str): The original filename

    Returns:
        str: A safe filename that can be used for storage
    """
    if not filename:
        return str(uuid.uuid4())
    _, extension = os.path.splitext(filename)

    safe_name = secure_filename(filename)

    # If secure_filename returns just the extension or an empty string

    if not safe_name or safe_name == extension.lstrip("."):
        return f"{str(uuid.uuid4())}{extension}"
    return safe_name


def num_tokens_from_string(string: str) -> int:
    encoding = get_encoding()
    if isinstance(string, str):
        num_tokens = len(encoding.encode(string))
        return num_tokens
    else:
        return 0


def num_tokens_from_object_or_list(thing):
    if isinstance(thing, list):
        return sum([num_tokens_from_object_or_list(x) for x in thing])
    elif isinstance(thing, dict):
        return sum([num_tokens_from_object_or_list(x) for x in thing.values()])
    elif isinstance(thing, str):
        return num_tokens_from_string(thing)
    else:
        return 0


def count_tokens_docs(docs):
    docs_content = ""
    for doc in docs:
        docs_content += doc.page_content
    tokens = num_tokens_from_string(docs_content)
    return tokens


def check_required_fields(data, required_fields):
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return make_response(
            jsonify(
                {
                    "success": False,
                    "message": f"Missing required fields: {', '.join(missing_fields)}",
                }
            ),
            400,
        )
    return None


def validate_required_fields(data, required_fields):
    missing_fields = []
    empty_fields = []

    for field in required_fields:
        if field not in data:
            missing_fields.append(field)
        elif not data[field]:
            empty_fields.append(field)
    errors = []
    if missing_fields:
        errors.append(f"Missing required fields: {', '.join(missing_fields)}")
    if empty_fields:
        errors.append(f"Empty values in required fields: {', '.join(empty_fields)}")
    if errors:
        return make_response(
            jsonify({"success": False, "message": " | ".join(errors)}), 400
        )
    return None


def get_hash(data):
    return hashlib.md5(data.encode(), usedforsecurity=False).hexdigest()


def limit_chat_history(history, max_token_limit=None, gpt_model="docsgpt"):
    """
    Limits chat history based on token count.
    Returns a list of messages that fit within the token limit.
    """
    from application.core.settings import settings

    max_token_limit = (
        max_token_limit
        if max_token_limit
        and max_token_limit
        < settings.LLM_TOKEN_LIMITS.get(gpt_model, settings.DEFAULT_MAX_HISTORY)
        else settings.LLM_TOKEN_LIMITS.get(gpt_model, settings.DEFAULT_MAX_HISTORY)
    )

    if not history:
        return []
    trimmed_history = []
    tokens_current_history = 0

    for message in reversed(history):
        tokens_batch = 0
        if "prompt" in message and "response" in message:
            tokens_batch += num_tokens_from_string(message["prompt"])
            tokens_batch += num_tokens_from_string(message["response"])
        if "tool_calls" in message:
            for tool_call in message["tool_calls"]:
                tool_call_string = f"Tool: {tool_call.get('tool_name')} | Action: {tool_call.get('action_name')} | Args: {tool_call.get('arguments')} | Response: {tool_call.get('result')}"
                tokens_batch += num_tokens_from_string(tool_call_string)
        if tokens_current_history + tokens_batch < max_token_limit:
            tokens_current_history += tokens_batch
            trimmed_history.insert(0, message)
        else:
            break
    return trimmed_history


def validate_function_name(function_name):
    """Validates if a function name matches the allowed pattern."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", function_name):
        return False
    return True


def generate_image_url(image_path):
    strategy = getattr(settings, "URL_STRATEGY", "backend")
    if strategy == "s3":
        bucket_name = getattr(settings, "S3_BUCKET_NAME", "docsgpt-test-bucket")
        region_name = getattr(settings, "SAGEMAKER_REGION", "eu-central-1")
        return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{image_path}"
    else:
        base_url = getattr(settings, "API_URL", "http://localhost:7091")
        return f"{base_url}/api/images/{image_path}"
