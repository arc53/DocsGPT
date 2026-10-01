"""The typed error for a turn that cannot fit the model's context window."""

from __future__ import annotations

from typing import Optional


class ContextOverflowError(ValueError):
    """A turn needs more context than the model has, and nothing can shrink it.

    Raised before any provider call (and before any compression call), so a
    hopeless request costs nothing. Routes can map it to an honest message,
    or to an OpenAI-shaped ``context_length_exceeded`` on ``/v1``. Subclasses
    ``ValueError`` so existing ``except ValueError`` handlers still catch it.

    Attributes:
        needed_tokens: Estimated tokens the turn needs.
        available_tokens: Tokens the model's window offers.
        stage: Where the overflow was found: ``"pre_compression"`` (setup,
            before history is compressed), ``"build"`` (message building) or
            ``"dispatch"`` (the pre-send gate).
    """

    def __init__(
        self,
        message: str,
        *,
        needed_tokens: int,
        available_tokens: int,
        stage: str,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.needed_tokens = int(needed_tokens)
        self.available_tokens = int(available_tokens)
        self.stage = stage
        self.detail = detail


# Phrases providers use when a request is longer than the model's window.
_CONTEXT_LENGTH_PHRASES = (
    "context_length_exceeded",
    "maximum context length",
    "context length exceeded",
    "context window",
    "prompt is too long",
    "input is too long",
    "too many input tokens",
    "reduce the length of the messages",
)


def is_context_length_error(error: BaseException) -> bool:
    """Whether ``error`` says the request did not fit the model's window.

    Covers :class:`ContextOverflowError` and the providers' own rejections
    (an error ``code`` of ``context_length_exceeded``, or the wording OpenAI,
    Anthropic, Google and OpenAI-compatible servers use).

    Args:
        error: Any exception from a model call.

    Returns:
        True for a context-length failure.
    """
    if isinstance(error, ContextOverflowError):
        return True
    code = getattr(error, "code", None)
    if isinstance(code, str) and code == "context_length_exceeded":
        return True
    text = str(error).lower()
    return any(phrase in text for phrase in _CONTEXT_LENGTH_PHRASES)
