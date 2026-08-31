import base64
import hashlib
import hmac
import io
import logging
import os
import re
import uuid
from pathlib import PurePosixPath
from typing import List

import tiktoken
from flask import jsonify, make_response
from werkzeug.utils import secure_filename

from application.core.model_utils import get_token_limit

from application.core.settings import settings

logger = logging.getLogger(__name__)


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


def strip_null_bytes(value):
    """Recursively strip ``\\x00`` from string keys/values in ``value``.

    Postgres rejects NUL in both text and jsonb; one NUL-laden payload
    (e.g. a binary response mis-decoded to text) would otherwise raise
    ``DataError`` and lose the whole row. Shared by the message journal,
    conversation finalize, activity log, tool_call_attempts, and
    attachments write lanes.
    """
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {
            (k.replace("\x00", "") if isinstance(k, str) and "\x00" in k else k):
            strip_null_bytes(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [strip_null_bytes(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_null_bytes(item) for item in value)
    return value


def truncate_to_line_boundary(data: bytes) -> bytes:
    """Trim a head-truncated byte window back to its last line boundary.

    The trim is skipped when it would discard more than half the window — a
    file whose only newline sits near the start (or at byte 0) would otherwise
    collapse to a few bytes, which is far worse than a partial final line.
    Callers pass a window already read at their size cap, so the cut never
    grows the result.

    Args:
        data: The head window read from an oversized file.

    Returns:
        ``data`` up to and including its last newline, or ``data`` unchanged
        when no newline is far enough in to be worth cutting at.
    """
    cut = data.rfind(b"\n")
    if cut > len(data) // 2:
        return data[: cut + 1]
    return data


def num_tokens_from_string(string: str) -> int:
    encoding = get_encoding()
    if isinstance(string, str):
        # encode_ordinary: plain ``encode()`` raises ValueError on literal
        # special-token text like <|endoftext|>, which user documents
        # legitimately contain.
        num_tokens = len(encoding.encode_ordinary(string))
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
    model_id: str = "gpt-4o", user_id: str | None = None
) -> int:
    total_context = get_token_limit(model_id, user_id=user_id)
    reserved = sum(settings.RESERVED_TOKENS.values())
    doc_budget = total_context - reserved
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


def limit_chat_history(
    history, max_token_limit=None, model_id="docsgpt-local", user_id=None
):
    """Limit chat history to fit within token limit."""
    model_token_limit = get_token_limit(model_id, user_id=user_id)
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


# Extension -> (accepted Pillow formats, MIME type). JPEG entries also accept
# MPO because Pillow reports multi-picture JPEGs (e.g. iPhone portrait photos,
# Samsung motion photos) as MPO.
AGENT_IMAGE_FORMATS = {
    ".gif": (("GIF",), "image/gif"),
    ".jpeg": (("JPEG", "MPO"), "image/jpeg"),
    ".jpg": (("JPEG", "MPO"), "image/jpeg"),
    ".png": (("PNG",), "image/png"),
    ".webp": (("WEBP",), "image/webp"),
}


def is_external_image_url(image_path: object) -> bool:
    """Return whether an image value is an externally hosted HTTP(S) URL."""
    return isinstance(image_path, str) and image_path.startswith(("http://", "https://"))


def safe_user_storage_component(user_id: object) -> str:
    """Return a deterministic, traversal-safe directory component for a user ID."""
    raw_user_id = str(user_id or "")
    component = secure_filename(raw_user_id)[:80] or "user"
    digest = hashlib.sha256(raw_user_id.encode("utf-8")).hexdigest()[:16]
    return f"{component}-{digest}"


def get_agent_image_content_type(image_path: object) -> str | None:
    """Return an allow-listed raster MIME type for an internal image path."""
    if not isinstance(image_path, str):
        return None
    policy = AGENT_IMAGE_FORMATS.get(PurePosixPath(image_path).suffix.lower())
    return policy[1] if policy else None


def is_safe_agent_image_path(image_path: object, user_id: object) -> bool:
    """Validate that a path is an agent avatar under its owner's upload directory."""
    if not isinstance(image_path, str) or not image_path or not user_id:
        return False
    if is_external_image_url(image_path) or "\\" in image_path or "\x00" in image_path:
        return False

    candidate = PurePosixPath(image_path)
    upload_root = PurePosixPath(str(settings.UPLOAD_FOLDER).rstrip("/"))
    # An absolute UPLOAD_FOLDER yields absolute stored paths, so the two must
    # agree; mismatched anchors mean the path did not come from this root. The
    # exact parent match below is what actually contains the path.
    if candidate.is_absolute() != upload_root.is_absolute() or ".." in candidate.parts:
        return False
    if get_agent_image_content_type(image_path) is None:
        return False

    owner_components = {safe_user_storage_component(user_id)}
    raw_user_id = str(user_id)
    raw_owner = PurePosixPath(raw_user_id)
    if (
        len(raw_owner.parts) == 1
        and raw_user_id not in {"", ".", ".."}
        and "\\" not in raw_user_id
        and "\x00" not in raw_user_id
    ):
        # Compatibility for avatars written before user IDs were sanitized.
        owner_components.add(raw_user_id)

    for owner_component in owner_components:
        expected_parent = upload_root / owner_component / "attachments"
        if candidate.parent == expected_parent and candidate.name:
            return True
    return False


def generate_agent_image_capability(
    agent_id: object, image_path: object, user_id: object
) -> str:
    """Create an HMAC capability for one agent's current internal image."""
    secret = getattr(settings, "JWT_SECRET_KEY", "")
    if not isinstance(secret, str) or not secret:
        return ""
    try:
        canonical_agent_id = str(uuid.UUID(str(agent_id)))
    except (TypeError, ValueError, AttributeError):
        return ""
    if not isinstance(image_path, str) or not user_id:
        return ""
    payload = (
        f"docsgpt-agent-image-v1\0{canonical_agent_id}\0{user_id}\0{image_path}"
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_agent_image_capability(
    capability: object, agent_id: object, image_path: object, user_id: object
) -> bool:
    """Verify an agent image capability without timing-leaky string comparison."""
    if not isinstance(capability, str) or not re.fullmatch(r"[0-9a-f]{64}", capability):
        return False
    expected = generate_agent_image_capability(agent_id, image_path, user_id)
    return bool(expected) and hmac.compare_digest(capability, expected)


def generate_image_url(image_path, agent_id=None, user_id=None):
    """Return an external URL or an opaque capability URL for an agent image.

    Internal storage paths are never included in the returned URL. Invalid or
    unscoped paths fail closed so a poisoned database row cannot become a file
    read capability.
    """
    if isinstance(image_path, str) and (
        image_path.startswith("http://") or image_path.startswith("https://")
    ):
        return image_path
    if not is_safe_agent_image_path(image_path, user_id):
        return ""
    capability = generate_agent_image_capability(agent_id, image_path, user_id)
    if not capability:
        return ""
    canonical_agent_id = str(uuid.UUID(str(agent_id)))
    base_url = getattr(settings, "API_URL", "http://localhost:7091").rstrip("/")
    return f"{base_url}/api/images/{canonical_agent_id}/{capability}"


def calculate_compression_threshold(
    model_id: str,
    threshold_percentage: float = 0.8,
    user_id: str | None = None,
) -> int:
    """
    Calculate token threshold for triggering compression.

    Args:
        model_id: Model identifier
        threshold_percentage: Percentage of context window (default 80%)
        user_id: When set, BYOM custom-model records (UUID-keyed) resolve
            for context-window lookup.

    Returns:
        Token count threshold
    """
    total_context = get_token_limit(model_id, user_id=user_id)
    threshold = int(total_context * threshold_percentage)
    return threshold


def convert_pdf_to_images(
    file_path: str,
    storage=None,
    max_pages: int = 20,
    dpi: int = 150,
    image_format: str = "PNG",
) -> List[dict]:
    """
    Convert PDF pages to images for LLMs that support images but not PDFs.

    This enables "synthetic PDF support" by converting each PDF page to an image
    that can be sent to vision-capable LLMs like Claude.

    Args:
        file_path: Path to the PDF file (can be storage path)
        storage: Optional storage instance for retrieving files
        max_pages: Maximum number of pages to convert (default 20 to avoid context overflow)
        dpi: Resolution for rendering (default 150 for balance of quality/size)
        image_format: Output format (PNG recommended for quality)

    Returns:
        List of dicts with keys:
        - 'data': base64-encoded image data
        - 'mime_type': MIME type (e.g., 'image/png')
        - 'page': Page number (1-indexed)

    Raises:
        ImportError: If pdf2image is not installed
        FileNotFoundError: If file doesn't exist
        Exception: If conversion fails
    """
    try:
        from pdf2image import convert_from_path, convert_from_bytes
    except ImportError:
        raise ImportError(
            "pdf2image is required for PDF-to-image conversion. "
            "Install it with: pip install pdf2image\n"
            "Also ensure poppler-utils is installed on your system."
        )

    images_data = []
    mime_type = f"image/{image_format.lower()}"

    try:
        # Get PDF content either from storage or direct file path
        if storage and hasattr(storage, "get_file"):
            with storage.get_file(file_path) as pdf_file:
                pdf_bytes = pdf_file.read()
                pil_images = convert_from_bytes(
                    pdf_bytes,
                    dpi=dpi,
                    fmt=image_format.lower(),
                    first_page=1,
                    last_page=max_pages,
                )
        else:
            pil_images = convert_from_path(
                file_path,
                dpi=dpi,
                fmt=image_format.lower(),
                first_page=1,
                last_page=max_pages,
            )

        for page_num, pil_image in enumerate(pil_images, start=1):
            # Convert PIL image to base64
            buffer = io.BytesIO()
            pil_image.save(buffer, format=image_format)
            buffer.seek(0)
            base64_data = base64.b64encode(buffer.read()).decode("utf-8")

            images_data.append({
                "data": base64_data,
                "mime_type": mime_type,
                "page": page_num,
            })

        return images_data

    except FileNotFoundError:
        logger.error(f"PDF file not found: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}", exc_info=True)
        raise


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
