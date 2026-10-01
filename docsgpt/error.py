import re
from dataclasses import dataclass, field
from typing import Any, Dict

from flask import jsonify
from werkzeug.http import HTTP_STATUS_CODES

# Shown for a failed turn when nothing more specific can be said.
GENERIC_ERROR_MESSAGE = "Please try again later. We apologize for any inconvenience."

CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
SERVER_ERROR = "server_error"

# Longest error text kept for operators (turn logs); longer text is cut.
MAX_ERROR_TEXT_CHARS = 2_000
# A run this long of base64 characters is a payload, not a message.
_BASE64_RUN = re.compile(r"(?:base64,)?[A-Za-z0-9+/=_-]{200,}")


def response_error(code_status, message=None):
    payload = {'error': HTTP_STATUS_CODES.get(code_status, "something went wrong")}
    if message:
        payload['message'] = message
    response = jsonify(payload)
    response.status_code = code_status
    return response


def bad_request(status_code=400, message=''):
    return response_error(code_status=status_code, message=message)


def sanitize_api_error(error) -> str:
    """
    Convert technical API errors to user-friendly messages.
    Works with both Exception objects and error message strings.
    """
    error_str = str(error).lower()
    if "503" in error_str or "unavailable" in error_str or "high demand" in error_str:
        return "The AI service is temporarily unavailable due to high demand. Please try again in a moment."
    if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
        return "Rate limit exceeded. Please wait a moment before trying again."
    if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
        return "Authentication error. Please check your API configuration."
    if "timeout" in error_str or "timed out" in error_str:
        return "The request timed out. Please try again."
    if "connection" in error_str or "network" in error_str:
        return "Network error. Please check your connection and try again."
    original = str(error)
    if len(original) > 200 or "{" in original or "traceback" in error_str:
        return "An error occurred while processing your request. Please try again later."
    return original


@dataclass(frozen=True)
class UserFacingError:
    """What a failed turn tells the user, and stores.

    Attributes:
        code: Machine-readable reason, ``context_length_exceeded`` or
            ``server_error``.
        message: Curated text; never the raw exception.
        params: The values ``message`` is built from (``needed_tokens``,
            ``available_tokens``), so a client can word it in the user's
            language. Empty when the message has none.
    """

    code: str
    message: str
    params: Dict[str, Any] = field(default_factory=dict)


def user_facing_error(error: BaseException, *, surface: str = "chat") -> UserFacingError:
    """The curated error a failed turn reports for ``error``.

    Only a turn that did not fit the model's window says more than the
    generic message: how big it was, when that is known, and what to do. The
    exception's own text is never used, since provider errors can echo the
    request (a rejected file part comes back as its base64 payload).

    Args:
        error: What failed the turn.
        surface: ``chat`` for the web UI and widgets, ``v1`` for the
            OpenAI-compatible API (no UI actions to point at).

    Returns:
        The code and message.
    """
    from docsgpt.agents.context_overflow import ContextOverflowError, is_context_length_error

    if not is_context_length_error(error):
        return UserFacingError(SERVER_ERROR, GENERIC_ERROR_MESSAGE)
    params: Dict[str, Any] = {}
    if isinstance(error, ContextOverflowError) and error.needed_tokens and error.available_tokens:
        params = {"needed_tokens": error.needed_tokens, "available_tokens": error.available_tokens}
        size = (
            f"This message and its attached files need about {error.needed_tokens:,} tokens, "
            f"more than the model can take ({error.available_tokens:,} tokens)."
        )
    else:
        size = "This message and its attached files are too large for the model's context window."
    if surface == "v1":
        advice = "Send fewer or smaller files, or add large documents to the agent's sources instead."
    else:
        advice = "Send fewer or smaller files, or use Add to Knowledge to search them instead of sending them whole."
    return UserFacingError(CONTEXT_LENGTH_EXCEEDED, f"{size} {advice}", params)


def bounded_error_text(error: BaseException) -> str:
    """``Type: message`` for operator logs, without payloads and bounded in size.

    Args:
        error: The exception.

    Returns:
        The text, base64 runs replaced by ``[payload]`` and cut to
        ``MAX_ERROR_TEXT_CHARS``.
    """
    text = _BASE64_RUN.sub("[payload]", f"{type(error).__name__}: {error}")
    if len(text) > MAX_ERROR_TEXT_CHARS:
        text = text[: MAX_ERROR_TEXT_CHARS - 1] + "…"
    return text
