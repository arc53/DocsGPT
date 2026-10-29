"""Retrying a workflow node on transient failures: the policy, and which errors it covers."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, ConfigDict

# What a node's ``retry.on`` may name.
TRANSIENT = "transient"
INVALID_OUTPUT = "invalid_output"
RETRY_REASONS = (TRANSIENT, INVALID_OUTPUT)

# Node types a retry policy applies to.
RETRYABLE_NODE_TYPES = frozenset({"agent", "code"})

DEFAULT_BACKOFF_SECONDS = (2.0, 10.0, 30.0)
# Most delay entries a policy keeps.
MAX_BACKOFF_ENTRIES = 10

# HTTP statuses worth another attempt: request timeout, conflict, too early, rate limit.
_RETRYABLE_4XX = frozenset({408, 409, 425, 429})

# Exception class names (anywhere in the MRO) that mean the request never got a
# full answer. Matched by name: the providers' SDKs split across httpx, httpx2,
# requests and their own types, and importing each to ``isinstance`` against
# would load every SDK.
_TRANSPORT_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ConnectionError",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "ServiceUnavailableError",
        "StreamStalledError",
        "Timeout",
        "TimeoutError",
        "WriteError",
        "WriteTimeout",
        "ChunkedEncodingError",
    }
)

# How deep to follow ``raise ... from`` when looking for the provider's error.
_MAX_CAUSE_DEPTH = 5


class InvalidNodeOutputError(ValueError):
    """A node's reply is not valid JSON or does not match its schema."""


class EmptyCompletionError(ValueError):
    """A node's model returned no text."""


class SandboxInfrastructureError(RuntimeError):
    """The sandbox, not the node's code, failed: the runtime was gone or unreachable."""


class RetryPolicy(BaseModel):
    """The retry policy a node runs with, after inheriting and clamping."""

    model_config = ConfigDict(frozen=True)
    max_attempts: int = 1
    backoff_seconds: tuple = DEFAULT_BACKOFF_SECONDS
    on: frozenset = frozenset(RETRY_REASONS)

    @property
    def enabled(self) -> bool:
        """Whether the node may run more than once."""
        return self.max_attempts > 1 and bool(self.on)

    def delay_before(self, attempt: int) -> float:
        """Seconds to wait before ``attempt`` (2 for the first retry)."""
        if not self.backoff_seconds:
            return 0.0
        index = min(max(attempt - 2, 0), len(self.backoff_seconds) - 1)
        return float(self.backoff_seconds[index])


def validate_retry_config(raw: Any, max_attempts: int, max_delay: float) -> Optional[str]:
    """Why a saved ``retry`` / ``retry_defaults`` value is invalid, or None.

    Args:
        raw: The value as sent; None means unset.
        max_attempts: The instance's cap on attempts.
        max_delay: The instance's cap on one delay, in seconds.

    Returns:
        A message naming the problem, or None when the value is valid.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return "must be an object"
    unknown = set(raw) - {"max_attempts", "backoff_seconds", "on"}
    if unknown:
        return f"has unknown settings: {', '.join(sorted(unknown))}"
    attempts = raw.get("max_attempts")
    if attempts is not None and (
        isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= max_attempts
    ):
        return f"max_attempts must be a whole number from 1 to {max_attempts}"
    backoff = raw.get("backoff_seconds")
    if backoff is not None:
        if not isinstance(backoff, list) or len(backoff) > MAX_BACKOFF_ENTRIES:
            return f"backoff_seconds must be a list of at most {MAX_BACKOFF_ENTRIES} delays"
        for value in backoff:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= max_delay:
                return f"backoff_seconds must hold delays from 0 to {max_delay:g} seconds"
    on = raw.get("on")
    if on is not None:
        if not isinstance(on, list) or any(value not in RETRY_REASONS for value in on):
            return f"on may only list {', '.join(RETRY_REASONS)}"
    return None


def resolve_retry_policy(
    node_retry: Any,
    defaults: Any,
    *,
    max_attempts: int,
    max_delay: float,
) -> RetryPolicy:
    """The policy a node runs with: its own ``retry`` over the workflow's defaults.

    Each field falls back separately. Values out of range are clamped and
    unknown reasons dropped, so a graph saved before a cap was lowered (or
    embedded without validation) still runs.

    Args:
        node_retry: The node's ``retry`` config, if any.
        defaults: The workflow's ``retry_defaults``, if any.
        max_attempts: The instance's cap on attempts.
        max_delay: The instance's cap on one delay, in seconds.

    Returns:
        The policy; one attempt when neither sets ``max_attempts``.
    """
    merged: Dict[str, Any] = {}
    for layer in (defaults, node_retry):
        if isinstance(layer, Mapping):
            merged.update({key: value for key, value in layer.items() if value is not None})

    attempts = merged.get("max_attempts", 1)
    if isinstance(attempts, bool) or not isinstance(attempts, (int, float)):
        attempts = 1
    attempts = max(1, min(int(attempts), max(1, int(max_attempts))))

    backoff = merged.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    if not isinstance(backoff, (list, tuple)):
        backoff = DEFAULT_BACKOFF_SECONDS
    delays = tuple(
        min(max(float(value), 0.0), float(max_delay))
        for value in list(backoff)[:MAX_BACKOFF_ENTRIES]
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )

    on = merged.get("on", RETRY_REASONS)
    reasons = (
        frozenset(value for value in on if value in RETRY_REASONS) if isinstance(on, (list, tuple)) else frozenset()
    )
    return RetryPolicy(max_attempts=attempts, backoff_seconds=delays, on=reasons)


def _causes(error: BaseException):
    """``error`` and what it was raised from, outermost first."""
    seen = 0
    current: Optional[BaseException] = error
    while current is not None and seen < _MAX_CAUSE_DEPTH:
        yield current
        current = current.__cause__
        seen += 1


def http_status(error: BaseException) -> Optional[int]:
    """The HTTP status a provider error carries, or None.

    Reads ``status_code`` (OpenAI, Anthropic), an integer ``code`` (Google
    GenAI), the attached response's status, or a boto ``ClientError``'s
    metadata, following ``raise ... from`` chains.
    """
    for current in _causes(error):
        status = getattr(current, "status_code", None)
        if status is None:
            code = getattr(current, "code", None)
            status = code if isinstance(code, int) and 100 <= code < 600 else None
        if status is None:
            response = getattr(current, "response", None)
            if isinstance(response, Mapping):
                status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            else:
                status = getattr(response, "status_code", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
    return None


def retry_after_seconds(error: BaseException) -> Optional[float]:
    """The delay a 429/503 response asked for in ``Retry-After``, or None."""
    for current in _causes(error):
        headers = getattr(getattr(current, "response", None), "headers", None)
        if headers is None:
            continue
        try:
            millis = headers.get("retry-after-ms")
            if millis is not None:
                return max(float(millis) / 1000.0, 0.0)
            value = headers.get("retry-after")
        except Exception:
            continue
        if value is None:
            continue
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)
    return None


def is_transport_error(error: BaseException) -> bool:
    """Whether the request failed in transit: a timeout, a refused or reset connection."""
    for current in _causes(error):
        if any(cls.__name__ in _TRANSPORT_ERROR_NAMES for cls in type(current).__mro__):
            return True
    return False


def _never_retried(error: BaseException) -> bool:
    """Errors another attempt cannot fix: the run is out of time or quota, or the request is too big."""
    from docsgpt.agents.context_overflow import is_context_length_error
    from docsgpt.core.run_budget import is_budget_exhausted
    from docsgpt.quotas.service import QuotaExceededError

    return any(
        is_budget_exhausted(current) or isinstance(current, QuotaExceededError) or is_context_length_error(current)
        for current in _causes(error)
    )


def classify_failure(error: BaseException, node_type: str) -> Optional[str]:
    """Which ``retry.on`` reason covers ``error``, or None when it must not be retried.

    Classifies the raw exception, before ``sanitize_api_error`` rewrites it.
    A status the provider sent decides first: 5xx, 408, 409, 425 and 429
    retry; any other 4xx (bad request, auth, not found) never does. Without
    a status, timeouts and dropped connections retry. Code nodes retry only
    on sandbox infrastructure errors.

    Args:
        error: What the node raised.
        node_type: The node's type value.

    Returns:
        ``transient``, ``invalid_output``, or None.
    """
    if _never_retried(error):
        return None
    if node_type == "code":
        return TRANSIENT if isinstance(error, SandboxInfrastructureError) else None
    if node_type != "agent":
        return None
    if isinstance(error, EmptyCompletionError):
        return TRANSIENT
    if isinstance(error, InvalidNodeOutputError):
        return INVALID_OUTPUT
    status = http_status(error)
    if status is not None:
        return TRANSIENT if status >= 500 or status in _RETRYABLE_4XX else None
    if is_transport_error(error):
        return TRANSIENT
    return None
