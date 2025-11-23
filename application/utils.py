import hashlib
import os
import re
import uuid

import tiktoken
from flask import jsonify, make_response
from werkzeug.utils import secure_filename

from application.core.model_utils import get_token_limit

from application.core.settings import settings


_encoding = None


def get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def get_gpt_model() -> str:
    """Get GPT model based on provider"""
    model_map = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-2",
        "groq": "llama3-8b-8192",
        "novita": "deepseek/deepseek-r1",
    }
    return settings.LLM_NAME or model_map.get(settings.LLM_PROVIDER, "")


def safe_filename(filename):
    """Create safe filename, preserving extension. Handles non-Latin characters."""
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


def calculate_doc_token_budget(
    model_id: str = "gpt-4o", history_token_limit: int = 2000
) -> int:
    total_context = get_token_limit(model_id)
    reserved = sum(settings.RESERVED_TOKENS.values())
    doc_budget = total_context - history_token_limit - reserved
    return max(doc_budget, 1000)


def get_missing_fields(data, required_fields):
    """Check for missing required fields. Returns list of missing field names."""
    return [field for field in required_fields if field not in data]


def check_required_fields(data, required_fields):
    """Validate required fields. Returns Flask 400 response if validation fails, None otherwise."""
    missing_fields = get_missing_fields(data, required_fields)
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


def get_field_validation_errors(data, required_fields):
    """Check for missing and empty fields. Returns dict with 'missing_fields' and 'empty_fields', or None."""
    missing_fields = []
    empty_fields = []

    for field in required_fields:
        if field not in data:
            missing_fields.append(field)
        elif not data[field]:
            empty_fields.append(field)
    if missing_fields or empty_fields:
        return {"missing_fields": missing_fields, "empty_fields": empty_fields}
    return None


def validate_required_fields(data, required_fields):
    """Validate required fields (must exist and be non-empty). Returns Flask 400 response if validation fails, None otherwise."""
    errors_dict = get_field_validation_errors(data, required_fields)
    if errors_dict:
        errors = []
        if errors_dict["missing_fields"]:
            errors.append(
                f"Missing required fields: {', '.join(errors_dict['missing_fields'])}"
            )
        if errors_dict["empty_fields"]:
            errors.append(
                f"Empty values in required fields: {', '.join(errors_dict['empty_fields'])}"
            )
        return make_response(
            jsonify({"success": False, "message": " | ".join(errors)}), 400
        )
    return None


def get_hash(data):
    return hashlib.md5(data.encode(), usedforsecurity=False).hexdigest()


def limit_chat_history(history, max_token_limit=None, model_id="docsgpt-local"):
    """Limit chat history to fit within token limit."""
    model_token_limit = get_token_limit(model_id)
    max_token_limit = (
        max_token_limit
        if max_token_limit and max_token_limit < model_token_limit
        else model_token_limit
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
    """Validate function name matches allowed pattern (alphanumeric, underscore, hyphen)."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", function_name):
        return False
    return True


def generate_image_url(image_path):
    if isinstance(image_path, str) and (
        image_path.startswith("http://") or image_path.startswith("https://")
    ):
        return image_path
    strategy = getattr(settings, "URL_STRATEGY", "backend")
    if strategy == "s3":
        bucket_name = getattr(settings, "S3_BUCKET_NAME", "docsgpt-test-bucket")
        region_name = getattr(settings, "SAGEMAKER_REGION", "eu-central-1")
        return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{image_path}"
    else:
        base_url = getattr(settings, "API_URL", "http://localhost:7091")
        return f"{base_url}/api/images/{image_path}"


def calculate_compression_threshold(
    model_id: str, threshold_percentage: float = 0.8
) -> int:
    """
    Calculate token threshold for triggering compression.

    Args:
        model_id: Model identifier
        threshold_percentage: Percentage of context window (default 80%)

    Returns:
        Token count threshold
    """
    total_context = get_token_limit(model_id)
    threshold = int(total_context * threshold_percentage)
    return threshold


def clean_text_for_tts(text: str) -> str:
    """
    clean text for Text-to-Speech processing.
    """
    # Handle code blocks and links

    text = re.sub(r"```mermaid[\s\S]*?```", " flowchart, ", text)  ## ```mermaid...```
    text = re.sub(r"```[\s\S]*?```", " code block, ", text)  ## ```code```
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  ## [text](url)
    text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", "", text)  ## ![alt](url)

    # Remove markdown formatting

    text = re.sub(r"`([^`]+)`", r"\1", text)  ## `code`
    text = re.sub(r"\{([^}]*)\}", r" \1 ", text)  ## {text}
    text = re.sub(r"[{}]", " ", text)  ## unmatched {}
    text = re.sub(r"\[([^\]]+)\]", r" \1 ", text)  ## [text]
    text = re.sub(r"[\[\]]", " ", text)  ## unmatched []
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)  ## **bold** __bold__
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)  ## *italic* _italic_
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  ## # headers
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)  ## > blockquotes
    text = re.sub(r"^[\s]*[-\*\+]\s+", "", text, flags=re.MULTILINE)  ## - * + lists
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)  ## 1. numbered lists
    text = re.sub(
        r"^[\*\-_]{3,}\s*$", "", text, flags=re.MULTILINE
    )  ## --- *** ___ rules
    text = re.sub(r"<[^>]*>", "", text)  ## <html> tags

    # Remove non-ASCII (emojis, special Unicode)

    text = re.sub(r"[^\x20-\x7E\n\r\t]", "", text)

    # Replace special sequences

    text = re.sub(r"-->", ", ", text)  ## -->
    text = re.sub(r"<--", ", ", text)  ## <--
    text = re.sub(r"=>", ", ", text)  ## =>
    text = re.sub(r"::", " ", text)  ## ::

    # Normalize whitespace

    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    return text
