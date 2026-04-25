"""Anonymous version-check client.

Fired on every Celery worker boot (see ``application/celery_init.py``
``worker_ready`` handler) and on a 7h periodic schedule (see the
``version-check`` entry in ``application/api/user/tasks.py``). Posts
the running version + anonymous instance UUID to
``gptcloud.arc53.com/api/check``, caches the response in Redis, and
surfaces any advisories to stdout + logs.

Design invariants — all enforced by a broad ``try/except`` at the top
of :func:`run_check`:

* Never blocks worker startup (fired from a daemon thread).
* Never raises to the caller (every failure is swallowed + logged at
  ``DEBUG``).
* Opt-out via ``VERSION_CHECK=0`` short-circuits before any Postgres
  write, Redis access, or outbound request.
* Redis coordinates multi-worker and multi-replica deployments — the
  first worker to acquire ``docsgpt:version_check:lock`` fetches, the
  rest read from the cached response on the next cycle.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import sys
from typing import Any, Dict, Optional

import requests

from application.cache import get_redis_instance
from application.core.settings import settings
from application.storage.db.repositories.app_metadata import AppMetadataRepository
from application.storage.db.session import db_session
from application.version import get_version

logger = logging.getLogger(__name__)

ENDPOINT_URL = "https://gptcloud.arc53.com/api/check"
CLIENT_NAME = "docsgpt-backend"
REQUEST_TIMEOUT_SECONDS = 5

CACHE_KEY = "docsgpt:version_check:response"
LOCK_KEY = "docsgpt:version_check:lock"
CACHE_TTL_SECONDS = 6 * 3600  # 6h default; shortened by response `next_check_after`.
LOCK_TTL_SECONDS = 60

NOTICE_KEY = "version_check_notice_shown"
INSTANCE_ID_KEY = "instance_id"

_HIGH_SEVERITIES = {"high", "critical"}

_ANSI_RESET = "\033[0m"
_ANSI_RED = "\033[31m"
_ANSI_YELLOW = "\033[33m"


def run_check() -> None:
    """Entry point for the worker-startup daemon thread.

    Safe to call unconditionally: the opt-out, Redis-outage, and
    Postgres-outage paths all return silently. No exception propagates.
    """
    try:
        _run_check_inner()
    except Exception as exc:  # noqa: BLE001 — belt-and-braces; nothing escapes.
        logger.debug("version check crashed: %s", exc, exc_info=True)


def _run_check_inner() -> None:
    if not settings.VERSION_CHECK:
        return

    instance_id = _resolve_instance_id_and_notice()
    if instance_id is None:
        # Postgres unavailable — per spec we skip the check entirely
        # rather than phone home with a synthetic/ephemeral UUID.
        return

    redis_client = get_redis_instance()

    cached = _read_cache(redis_client)
    if cached is not None:
        _render_advisories(cached)
        return

    # Cache miss. Try to win the lock; if another worker has it, skip.
    # ``redis_client is None`` here means Redis is unreachable — per the
    # spec we still proceed uncached (acceptable duplicate calls in
    # multi-worker Redis-less deploys).
    if redis_client is not None and not _acquire_lock(redis_client):
        return

    response = _fetch(instance_id)
    if response is None:
        if redis_client is not None:
            _release_lock(redis_client)
        return

    _write_cache(redis_client, response)
    _render_advisories(response)
    if redis_client is not None:
        _release_lock(redis_client)


def _resolve_instance_id_and_notice() -> Optional[str]:
    """Load (or create) the instance UUID and emit the first-run notice.

    The notice is printed at most once across the lifetime of the
    installation — tracked via the ``version_check_notice_shown`` row
    in ``app_metadata``. Both reads and the write happen inside one
    short transaction so two racing workers can't each emit the notice.
    """
    try:
        with db_session() as conn:
            repo = AppMetadataRepository(conn)
            instance_id = repo.get_or_create_instance_id()
            if repo.get(NOTICE_KEY) is None:
                _print_first_run_notice()
                repo.set(NOTICE_KEY, "1")
            return instance_id
    except Exception as exc:  # noqa: BLE001 — Postgres down, bad URI, etc.
        logger.debug("version check: Postgres unavailable (%s)", exc, exc_info=True)
        return None


def _print_first_run_notice() -> None:
    message = (
        "Anonymous version check enabled — sends version to "
        "gptcloud.arc53.com.\nDisable with VERSION_CHECK=0."
    )
    print(message, flush=True)
    logger.info("version check: first-run notice shown")


def _read_cache(redis_client) -> Optional[Dict[str, Any]]:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(CACHE_KEY)
    except Exception as exc:  # noqa: BLE001 — Redis transient errors.
        logger.debug("version check: cache GET failed (%s)", exc, exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError) as exc:
        logger.debug("version check: cache decode failed (%s)", exc, exc_info=True)
        return None


def _write_cache(redis_client, response: Dict[str, Any]) -> None:
    if redis_client is None:
        return
    ttl = _compute_ttl(response)
    try:
        redis_client.setex(CACHE_KEY, ttl, json.dumps(response))
    except Exception as exc:  # noqa: BLE001
        logger.debug("version check: cache SETEX failed (%s)", exc, exc_info=True)


def _compute_ttl(response: Dict[str, Any]) -> int:
    """Cap the cache at 6h but honor a shorter server-specified window."""
    next_after = response.get("next_check_after")
    if isinstance(next_after, (int, float)) and next_after > 0:
        return max(1, min(CACHE_TTL_SECONDS, int(next_after)))
    return CACHE_TTL_SECONDS


def _acquire_lock(redis_client) -> bool:
    try:
        owner = f"{socket.gethostname()}:{os.getpid()}"
        return bool(
            redis_client.set(LOCK_KEY, owner, nx=True, ex=LOCK_TTL_SECONDS)
        )
    except Exception as exc:  # noqa: BLE001
        # Treat a failing Redis the same as "no lock infra" — skip rather
        # than fire without coordination, because Redis outage is
        # usually transient and one missed cycle is harmless.
        logger.debug("version check: lock acquire failed (%s)", exc, exc_info=True)
        return False


def _release_lock(redis_client) -> None:
    try:
        redis_client.delete(LOCK_KEY)
    except Exception as exc:  # noqa: BLE001
        logger.debug("version check: lock release failed (%s)", exc, exc_info=True)


def _fetch(instance_id: str) -> Optional[Dict[str, Any]]:
    version = get_version()
    if version in ("", "unknown"):
        # The endpoint rejects payloads without a valid semver, and the
        # rejection is otherwise logged at DEBUG — invisible under the
        # usual ``-l INFO`` Celery worker start. Surface it loudly so a
        # misconfigured release (missing or unset ``__version__``) is
        # obvious instead of silently disabling the check.
        logger.warning(
            "version check: skipping — get_version() returned %r. "
            "Set __version__ in application/version.py to a valid "
            "version string.",
            version,
        )
        return None
    payload = {
        "version": version,
        "instance_id": instance_id,
        "python_version": platform.python_version(),
        "platform": sys.platform,
        "client": CLIENT_NAME,
    }
    try:
        resp = requests.post(
            ENDPOINT_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.debug("version check: request failed (%s)", exc, exc_info=True)
        return None
    if resp.status_code >= 400:
        logger.debug("version check: non-2xx response %s", resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError as exc:
        logger.debug("version check: response decode failed (%s)", exc, exc_info=True)
        return None


def _render_advisories(response: Dict[str, Any]) -> None:
    advisories = response.get("advisories") or []
    if not isinstance(advisories, list):
        return
    current_version = get_version()
    for advisory in advisories:
        if not isinstance(advisory, dict):
            continue
        severity = str(advisory.get("severity", "")).lower()
        advisory_id = advisory.get("id", "UNKNOWN")
        title = advisory.get("title", "")
        url = advisory.get("url", "")
        fixed_in = advisory.get("fixed_in")
        summary = advisory.get(
            "summary",
            f"Your DocsGPT version {current_version} is vulnerable.",
        )

        logger.warning(
            "security advisory %s (severity=%s) affects version %s: %s%s%s",
            advisory_id,
            severity or "unknown",
            current_version,
            title or summary,
            f" — fixed in {fixed_in}" if fixed_in else "",
            f" — {url}" if url else "",
        )

        if severity in _HIGH_SEVERITIES:
            _print_console_advisory(
                advisory_id=advisory_id,
                title=title,
                severity=severity,
                summary=summary,
                fixed_in=fixed_in,
                url=url,
            )


def _print_console_advisory(
    *,
    advisory_id: str,
    title: str,
    severity: str,
    summary: str,
    fixed_in: Optional[str],
    url: str,
) -> None:
    color = _ANSI_RED if severity == "critical" else _ANSI_YELLOW
    bar = "=" * 60
    upgrade_line = ""
    if fixed_in and url:
        upgrade_line = f"   Upgrade to {fixed_in}+ — {url}"
    elif fixed_in:
        upgrade_line = f"   Upgrade to {fixed_in}+"
    elif url:
        upgrade_line = f"   {url}"

    lines = [
        bar,
        f"\u26a0  SECURITY ADVISORY: {advisory_id}",
        f"   {summary}",
        f"   {title} (severity: {severity})" if title else f"   severity: {severity}",
    ]
    if upgrade_line:
        lines.append(upgrade_line)
    lines.append(bar)
    print(f"{color}{chr(10).join(lines)}{_ANSI_RESET}", flush=True)
