"""Pre-execution trust verification for MCP tool calls.

Provides an opt-in, pluggable hook that runs before DocsGPT invokes a remote
MCP server action. Operators can:

* leave verification disabled (default — existing behaviour),
* enable a built-in URI/host allowlist via settings, and/or
* register a custom :class:`TrustVerifier` at process start.

See https://github.com/arc53/DocsGPT/issues/2501.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Protocol, runtime_checkable
from urllib.parse import urlparse

from application.core.settings import settings

logger = logging.getLogger(__name__)


class TrustVerdict(str, Enum):
    """Outcome of a trust verification check."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    WARNED = "warned"


@dataclass(frozen=True)
class TrustResult:
    """Result returned by a :class:`TrustVerifier`.

    Attributes:
        verdict: Whether the call may proceed.
        reason: Human-readable explanation (logged / raised to the user).
        details: Optional structured metadata for custom backends.
    """

    verdict: TrustVerdict
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrustContext:
    """Context passed to verifiers before an MCP tool call executes.

    Attributes:
        server_uri: MCP server URL (or empty for stdio-style configs).
        tool_name: DocsGPT tool type name (typically ``mcp_tool``).
        action_name: Remote MCP action about to run, when known.
        arguments: Call arguments (may be empty/redacted by callers).
        user_id: Authenticated user id when available.
        transport_type: MCP transport (``http``, ``sse``, …).
        auth_type: Configured auth mode (``none``, ``bearer``, ``oauth``, …).
    """

    server_uri: str
    tool_name: str = "mcp_tool"
    action_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    transport_type: Optional[str] = None
    auth_type: Optional[str] = None


@runtime_checkable
class TrustVerifier(Protocol):
    """Pluggable trust verification backend.

    Implementations may be sync or async; the framework awaits coroutines
    automatically. Raise only for infrastructure failures — return a
    :class:`TrustResult` for policy decisions.
    """

    def verify(self, context: TrustContext) -> Any:
        """Evaluate trust for the given MCP call context.

        Args:
            context: Call metadata including the server URI.

        Returns:
            A :class:`TrustResult`, or an awaitable resolving to one.
        """
        ...


_verifier_lock = threading.RLock()
_custom_verifier: Optional[TrustVerifier] = None


def set_trust_verifier(verifier: Optional[TrustVerifier]) -> None:
    """Register (or clear) a process-wide custom trust verifier.

    Args:
        verifier: Custom backend, or ``None`` to clear and fall back to the
            settings-driven allowlist (when enabled).
    """
    global _custom_verifier
    with _verifier_lock:
        _custom_verifier = verifier
        if verifier is None:
            logger.info("MCP trust verifier cleared")
        else:
            logger.info(
                "MCP trust verifier registered: %s",
                type(verifier).__name__,
            )


def get_trust_verifier() -> Optional[TrustVerifier]:
    """Return the active verifier, or ``None`` when verification is off.

    Preference order:
        1. Custom verifier set via :func:`set_trust_verifier`
        2. Built-in allowlist verifier when ``MCP_TRUST_VERIFICATION_ENABLED``
        3. ``None`` (skip verification — fail open / legacy behaviour)
    """
    with _verifier_lock:
        if _custom_verifier is not None:
            return _custom_verifier
    if getattr(settings, "MCP_TRUST_VERIFICATION_ENABLED", False):
        return AllowlistTrustVerifier.from_settings()
    return None


class AllowlistTrustVerifier:
    """Allowlist / denylist trust policy for MCP server URIs.

    Matching is case-insensitive against:

    * the full URI (scheme + netloc + path, trailing slash stripped),
    * the netloc (``host:port``), and
    * the bare hostname.

    An empty allowlist with verification enabled does **not** block every
    server (that would brick default installs); denylist entries still apply.
    When the allowlist is non-empty, only matching servers are allowed.
    """

    def __init__(
        self,
        allowed: Optional[list[str]] = None,
        blocked: Optional[list[str]] = None,
    ):
        self.allowed = {_normalize_entry(e) for e in (allowed or []) if e}
        self.blocked = {_normalize_entry(e) for e in (blocked or []) if e}

    @classmethod
    def from_settings(cls) -> "AllowlistTrustVerifier":
        """Build a verifier from ``MCP_TRUST_ALLOWED_SERVERS`` / blocked env."""
        return cls(
            allowed=_split_csv(getattr(settings, "MCP_TRUST_ALLOWED_SERVERS", None)),
            blocked=_split_csv(getattr(settings, "MCP_TRUST_BLOCKED_SERVERS", None)),
        )

    def verify(self, context: TrustContext) -> TrustResult:
        """Apply allowlist / denylist rules to ``context.server_uri``."""
        uri = (context.server_uri or "").strip()
        if not uri:
            return TrustResult(
                verdict=TrustVerdict.BLOCKED,
                reason="MCP server URI is empty",
            )

        candidates = _uri_match_candidates(uri)

        if self.blocked and candidates & self.blocked:
            return TrustResult(
                verdict=TrustVerdict.BLOCKED,
                reason=f"MCP server URI is on the blocklist: {uri}",
                details={"matched": sorted(candidates & self.blocked)},
            )

        if self.allowed:
            if candidates & self.allowed:
                return TrustResult(
                    verdict=TrustVerdict.ALLOWED,
                    reason="MCP server URI is on the allowlist",
                    details={"matched": sorted(candidates & self.allowed)},
                )
            return TrustResult(
                verdict=TrustVerdict.BLOCKED,
                reason=f"MCP server URI is not on the allowlist: {uri}",
                details={"candidates": sorted(candidates)},
            )

        # Enabled with no allowlist: allow but warn so operators notice.
        return TrustResult(
            verdict=TrustVerdict.WARNED,
            reason=(
                "MCP trust verification is enabled but no allowlist is configured; "
                "allowing call. Set MCP_TRUST_ALLOWED_SERVERS or register a custom verifier."
            ),
        )


class MCPTrustBlockedError(Exception):
    """Raised when pre-execution trust verification blocks an MCP call."""

    def __init__(self, result: TrustResult, server_uri: str = ""):
        self.result = result
        self.server_uri = server_uri
        message = result.reason or "MCP trust verification blocked this call"
        if server_uri:
            message = f"{message} (server={server_uri})"
        super().__init__(message)


def verify_mcp_trust(context: TrustContext) -> TrustResult:
    """Run the active trust verifier for ``context``.

    Returns:
        :class:`TrustResult`. When no verifier is configured, returns
        ``ALLOWED`` without side effects.

    Notes:
        Verifier exceptions are fail-open by default
        (``MCP_TRUST_FAIL_OPEN=True``) so a broken custom backend does not
        take down every MCP call; set fail-open to false for fail-closed.
    """
    verifier = get_trust_verifier()
    if verifier is None:
        return TrustResult(
            verdict=TrustVerdict.ALLOWED,
            reason="MCP trust verification disabled",
        )

    try:
        raw = verifier.verify(context)
        if inspect.isawaitable(raw):
            result = _run_awaitable(raw)
        else:
            result = raw
    except Exception as exc:
        fail_open = bool(getattr(settings, "MCP_TRUST_FAIL_OPEN", True))
        logger.exception(
            "MCP trust verifier raised (fail_open=%s) for server=%s",
            fail_open,
            context.server_uri,
        )
        if fail_open:
            return TrustResult(
                verdict=TrustVerdict.WARNED,
                reason=f"trust verifier error (fail-open): {exc}",
                details={"error": type(exc).__name__},
            )
        return TrustResult(
            verdict=TrustVerdict.BLOCKED,
            reason=f"trust verifier error (fail-closed): {exc}",
            details={"error": type(exc).__name__},
        )

    if not isinstance(result, TrustResult):
        logger.error(
            "MCP trust verifier returned %s, expected TrustResult; blocking",
            type(result).__name__,
        )
        return TrustResult(
            verdict=TrustVerdict.BLOCKED,
            reason="trust verifier returned an invalid result type",
        )
    return result


def enforce_mcp_trust(context: TrustContext) -> TrustResult:
    """Verify trust and enforce block / warn policy.

    Args:
        context: MCP call context.

    Returns:
        The :class:`TrustResult` when the call may proceed.

    Raises:
        MCPTrustBlockedError: When the verdict is ``BLOCKED``, or ``WARNED``
            and ``MCP_TRUST_ON_WARN`` is ``block``.
    """
    result = verify_mcp_trust(context)

    if result.verdict == TrustVerdict.ALLOWED:
        return result

    if result.verdict == TrustVerdict.WARNED:
        logger.warning(
            "MCP trust warning server=%s action=%s reason=%s",
            context.server_uri,
            context.action_name,
            result.reason,
        )
        on_warn = (getattr(settings, "MCP_TRUST_ON_WARN", "proceed") or "proceed").strip().lower()
        if on_warn == "block":
            raise MCPTrustBlockedError(result, server_uri=context.server_uri)
        return result

    # BLOCKED
    logger.warning(
        "MCP trust blocked server=%s action=%s reason=%s",
        context.server_uri,
        context.action_name,
        result.reason,
    )
    raise MCPTrustBlockedError(result, server_uri=context.server_uri)


def _run_awaitable(awaitable: Any) -> Any:
    """Run an async verifier result from a sync call path."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    # Already inside an event loop (e.g. ASGI worker path that somehow
    # calls sync MCPTool): spin a short-lived loop on a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, awaitable).result()


def _split_csv(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _normalize_entry(entry: str) -> str:
    return entry.strip().rstrip("/").lower()


def _uri_match_candidates(uri: str) -> set[str]:
    """Return normalized forms of ``uri`` used for allowlist matching."""
    normalized = _normalize_entry(uri)
    candidates = {normalized}
    try:
        parsed = urlparse(uri if "://" in uri else f"//{uri}", scheme="")
        netloc = (parsed.netloc or parsed.path.split("/")[0] or "").lower()
        if netloc:
            candidates.add(netloc)
            host = netloc.split("@")[-1]
            # strip port
            if host.startswith("["):
                # IPv6 literal
                end = host.find("]")
                hostname = host[: end + 1] if end != -1 else host
            else:
                hostname = host.rsplit(":", 1)[0]
            if hostname:
                candidates.add(hostname.lower())
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}".rstrip("/")
            candidates.add(origin)
    except Exception:
        logger.debug("Failed to parse MCP server URI for trust matching: %s", uri)
    return candidates
