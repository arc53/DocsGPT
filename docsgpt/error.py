import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from flask import jsonify
from werkzeug.http import HTTP_STATUS_CODES

# Shown for a failed turn when nothing more specific can be said.
GENERIC_ERROR_MESSAGE = "Please try again later. We apologize for any inconvenience."

CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
IMAGE_UNREADABLE = "image_unreadable"
SERVER_ERROR = "server_error"

# Longest error text kept for operators (turn logs); longer text is cut.
MAX_ERROR_TEXT_CHARS = 2_000
# A run this long of base64 characters is a payload, not a message.
_BASE64_RUN = re.compile(r"(?:base64,)?[A-Za-z0-9+/=_-]{200,}")
# Longest provider error text a model-call failure log line keeps.
MAX_PROVIDER_FAILURE_CHARS = 300
# Error class names the provider SDKs raise for a refused key (OpenAI, Anthropic, Groq…).
_AUTH_ERROR_NAMES = frozenset({"AuthenticationError", "PermissionDeniedError"})
# Lower-cased phrases of the errors an SDK raises for a key that is missing when it is built or called.
_MISSING_KEY_PHRASES = ("api_key client option must be set", "could not resolve authentication method")


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


# Error codes and wording providers use when an image part cannot be decoded.
_IMAGE_REJECTION_CODES = frozenset({"image_parse_error", "invalid_image", "invalid_image_format"})
_IMAGE_REJECTION_PHRASES = (
    "image_parse_error",
    "unsupported image",
    "invalid image",
    "could not process image",
    "unable to process input image",
    "image could not be decoded",
)


def is_image_rejection_error(error: BaseException) -> bool:
    """Whether a provider refused the request because an image part is unreadable.

    Args:
        error: Any exception from a model call.

    Returns:
        True when the provider said an image could not be read.
    """
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in _IMAGE_REJECTION_CODES:
        return True
    text = str(error).lower()
    return any(phrase in text for phrase in _IMAGE_REJECTION_PHRASES)


def _rejected_image_error(image_names: Sequence[str]) -> UserFacingError:
    """The curated error for a turn whose images a provider refused.

    Providers do not say which image they refused, so every image sent as
    an image this turn is named.
    """
    names = [str(n) for n in image_names if n]
    if len(names) == 1:
        subject = f"the attached image {names[0]}"
    elif names:
        subject = f"one of the attached images ({', '.join(names)})"
    else:
        subject = "an attached image"
    message = (
        f"The model could not read {subject}: it may be damaged or in a format the model does not accept. "
        "Remove or replace it, then send the message again."
    )
    return UserFacingError(IMAGE_UNREADABLE, message, {"files": names} if names else {})


def user_facing_error(
    error: BaseException, *, surface: str = "chat", image_names: Optional[Sequence[str]] = None
) -> UserFacingError:
    """The curated error a failed turn reports for ``error``.

    Only a turn that did not fit the model's window says more than the
    generic message: how big it was, when that is known, and what to do. The
    exception's own text is never used, since provider errors can echo the
    request (a rejected file part comes back as its base64 payload).

    Args:
        error: What failed the turn.
        surface: ``chat`` for the web UI and widgets, ``v1`` for the
            OpenAI-compatible API (no UI actions to point at).
        image_names: Files sent to the model as images this turn, named
            when the provider refuses an image.

    Returns:
        The code and message.
    """
    from docsgpt.agents.context_overflow import ContextOverflowError, is_context_length_error
    from docsgpt.core.run_budget import is_budget_exhausted

    if is_budget_exhausted(error):
        return UserFacingError("time_limit", "Stopped: time limit.")

    if not is_context_length_error(error) and is_image_rejection_error(error):
        return _rejected_image_error(image_names or ())
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


def http_status(error: BaseException) -> Optional[int]:
    """The HTTP status a provider SDK's error carries, or None.

    Args:
        error: The exception.

    Returns:
        ``status_code`` (openai, anthropic), the response's status, or google-genai's ``code``; None without one.
    """
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if status is None:
        # google-genai's APIError carries the HTTP status as ``code``.
        status = getattr(error, "code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def is_auth_failure(error: BaseException) -> bool:
    """Whether a model call failed because the provider refused, or never got, the model's key.

    A 401 or 403 from the provider, an SDK's authentication or permission
    error, or an SDK that can't find a key to send. Such a failure doesn't go
    away on retry: the user has to change the model or its key.

    Args:
        error: What the call (or building the model) raised.

    Returns:
        True for a key problem.
    """
    if http_status(error) in (401, 403) or type(error).__name__ in _AUTH_ERROR_NAMES:
        return True
    message = str(error).lower()
    return any(phrase in message for phrase in _MISSING_KEY_PHRASES)


def provider_failure_text(error: BaseException) -> str:
    """A failed model call, as an operator log line may quote it.

    A refused key is named by its type and HTTP status only: the provider's
    body can quote the key or the account. Other failures keep their message,
    payloads cut out and cut to :data:`MAX_PROVIDER_FAILURE_CHARS`.

    Args:
        error: What the model call raised.

    Returns:
        ``Type (HTTP 401)`` for a key problem, else ``Type: message``.
    """
    if is_auth_failure(error):
        status = http_status(error)
        return type(error).__name__ + (f" (HTTP {status})" if status is not None else "")
    text = bounded_error_text(error)
    if len(text) > MAX_PROVIDER_FAILURE_CHARS:
        text = text[: MAX_PROVIDER_FAILURE_CHARS - 1] + "…"
    return text
