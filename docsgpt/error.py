from flask import jsonify
from werkzeug.http import HTTP_STATUS_CODES


def response_error(code_status, message=None):
    payload = {'error': HTTP_STATUS_CODES.get(code_status, "something went wrong")}
    if message:
        payload['message'] = message
    response = jsonify(payload)
    response.status_code = code_status
    return response


def bad_request(status_code=400, message=''):
    return response_error(code_status=status_code, message=message)


CONTEXT_WINDOW_MESSAGE = (
    "This request is too large for the selected model's context window. "
    "Try again with fewer or smaller attachments, start a new conversation, "
    "or choose a model with a larger context window."
)
RATE_LIMITED_MESSAGE = (
    "The AI service is receiving too much text right now. Please wait a "
    "moment and try again."
)

_CONTEXT_WINDOW_MARKERS = (
    "context_length_exceeded",
    "context window",
    "maximum context length",
    "prompt is too long",
    "input is too long",
    "too many input tokens",
    "exceeds the maximum number of tokens",
    # llama.cpp: "request (N tokens) exceeds the available context size"
    "context size",
    "exceed_context_size",
)


def user_facing_error(error) -> "tuple[str, str] | None":
    """Classify a failure the user can act on, with the copy to show them.

    Generic copy ("please try again later") after a request that can never
    succeed as sent sends the user round the same failure again; these
    classes say what to change instead.

    Args:
        error: The exception, or its message.

    Returns:
        ``(code, message)`` for a recognised failure, otherwise None.
    """
    text = str(error).lower()
    # A token-rate 429 can also say the request "exceeds the maximum number of
    # tokens" (per minute), so it is checked first: waiting fixes it, trimming
    # attachments does not.
    if "429" in text and ("tokens_per_minute" in text or "tokens per min" in text):
        return "rate_limited", RATE_LIMITED_MESSAGE
    if any(marker in text for marker in _CONTEXT_WINDOW_MARKERS):
        return "context_window_exceeded", CONTEXT_WINDOW_MESSAGE
    return None


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
