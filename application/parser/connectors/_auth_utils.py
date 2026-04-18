"""Shared helpers for connector auth modules.

These helpers exist so that sensitive values (session tokens, bearer
credentials) never end up interpolated into exception messages or log
lines. Exception messages frequently flow into ``stack_logs`` (Postgres)
and Sentry via ``exc_info=True``, so the raw value must never be the
thing we format.
"""

from __future__ import annotations

import hashlib


def session_token_fingerprint(session_token: str) -> str:
    """Return a short, irreversible fingerprint for a session token.

    The returned string is safe to embed in exception messages and log
    lines: it is a prefix of a SHA-256 digest, clearly tagged so an
    operator reading the log knows it is a hash and not the token
    itself. It is stable for a given input, which lets operators
    correlate "which token failed" across log lines without exposing
    the credential.

    Args:
        session_token: The raw session token. Accepts ``None`` or the
            empty string for defensive callers; both yield a distinct
            sentinel rather than raising.

    Returns:
        A string of the form ``"sha256:<6 hex chars>"``, or
        ``"sha256:<empty>"`` when the input is falsy.
    """
    if not session_token:
        return "sha256:<empty>"
    digest = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:6]}"
