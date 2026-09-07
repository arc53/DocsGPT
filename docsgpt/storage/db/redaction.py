"""Secret redaction for reflected ``stack_logs`` data.

``stacks`` is built by reflecting every public attribute of runtime
objects (the ``llm`` component carries the deployment provider
``api_key`` and the caller's ``user_api_key``). The unified-logs endpoint
returns ``stacks`` to the client, so credentials must be scrubbed — at
write time for new rows, and at read time for rows written before
redaction existed.
"""

from __future__ import annotations

REDACTED = "[REDACTED]"

# Substrings marking a key as a credential. Compound token-count fields
# (``prompt_tokens`` / ``generated_tokens`` / ``token_budget`` / ...) are
# intentionally not matched: secret token forms are spelled out
# (``access_token`` etc.) and a bare ``token`` is handled separately.
_SECRET_SUBSTRINGS = (
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "refresh_token",
    "auth_token",
    "id_token",
    "session_token",
    "secret",
    "password",
    "passwd",
    "passphrase",
    "private_key",
    "credential",
    "authorization",
    "bearer",
)


def is_secret_key(key: str) -> bool:
    """True when ``key`` names a credential that must not be persisted/returned."""
    k = key.lower()
    if k == "token":
        return True
    return any(s in k for s in _SECRET_SUBSTRINGS)


def redact_secrets(obj):
    """Recursively replace secret-keyed values with ``[REDACTED]``.

    Walks dicts and lists; leaf scalars pass through unchanged. ``None``
    returns ``None`` so callers can redact an optional payload directly.
    """
    if isinstance(obj, dict):
        return {
            k: (
                REDACTED
                if isinstance(k, str) and is_secret_key(k)
                else redact_secrets(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_secrets(v) for v in obj]
    return obj
