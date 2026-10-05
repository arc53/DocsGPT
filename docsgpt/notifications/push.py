"""Web Push: validate browser subscriptions and deliver notifications to them.

Push is on when ``WEBPUSH_VAPID_PRIVATE_KEY`` is set (the public key is
derived from it when unset, and must match it when set). Deliveries run in a
Celery worker (:func:`docsgpt.notifications.tasks.send_web_push`), never on a
request path.

**Endpoints are an allowlist.** A subscription's endpoint is a URL the server
will POST to, chosen by the browser, so a malicious client could otherwise
point it anywhere (SSRF). Only https URLs on known push services
(:data:`DEFAULT_ALLOWED_HOSTS`) and ``WEBPUSH_EXTRA_ALLOWED_HOSTS`` are
accepted, on the default port, checked when the subscription is saved and
again before every send. Redirects are never followed.

A subscription the push service reports gone (404, 410) is deleted; other
failures are counted, and one that keeps failing is dropped after
:data:`MAX_CONSECUTIVE_FAILURES`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

import requests

from docsgpt.core.settings import settings
from docsgpt.notifications.kinds import FALLBACK_TITLE, push_text

logger = logging.getLogger(__name__)

#: Push services browsers use: exact hosts, and suffixes (leading dot) that match subdomains.
DEFAULT_ALLOWED_HOSTS: Tuple[str, ...] = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, Opera, Samsung Internet, Brave
    "android.googleapis.com",  # legacy GCM endpoints
    "updates.push.services.mozilla.com",  # Firefox (autopush)
    ".push.services.mozilla.com",
    "web.push.apple.com",  # Safari 16+ and iOS home-screen apps
    ".push.apple.com",
    ".notify.windows.com",  # Edge on Windows (WNS)
)

#: Subscriptions one user keeps; registering more drops the least recently saved.
MAX_SUBSCRIPTIONS_PER_USER = 10

#: Failed deliveries in a row after which a subscription is dropped.
MAX_CONSECUTIVE_FAILURES = 20

#: Seconds a push service keeps an undelivered notification (a device that is off).
PUSH_TTL_SECONDS = 24 * 60 * 60

#: Seconds one delivery may take.
SEND_TIMEOUT_SECONDS = 10

#: Bounds on the payload's text; Web Push carries at most 4 KB once encrypted.
TITLE_MAX_CHARS = 120
BODY_MAX_CHARS = 400
URL_MAX_CHARS = 512

#: Longest endpoint URL accepted.
ENDPOINT_MAX_CHARS = 1024


class InvalidSubscription(ValueError):
    """A subscription the server will not save; the message says why."""


@dataclass(frozen=True)
class VapidConfig:
    """The key pair pushes are signed with."""

    private_key: str
    public_key: str
    subject: str


def _b64url_decode(value: str) -> bytes:
    text = (value or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _subject() -> str:
    configured = (settings.WEBPUSH_VAPID_SUBJECT or "").strip()
    if configured:
        return configured
    for candidate in (getattr(settings, "PUBLIC_API_BASE_URL", None), getattr(settings, "API_URL", None)):
        if candidate and str(candidate).startswith("https://"):
            return str(candidate).rstrip("/")
    return "mailto:webpush@docsgpt.invalid"


@lru_cache(maxsize=4)
def _load_vapid(private_key: str, public_key: Optional[str], subject: str) -> Optional[VapidConfig]:
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    try:
        vapid = Vapid.from_raw(private_key.strip().encode())
        derived = _b64url_encode(
            vapid.public_key.public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )
    except Exception:
        logger.error("WEBPUSH_VAPID_PRIVATE_KEY is not a raw base64url P-256 key; Web Push is off")
        return None
    if public_key:
        try:
            given = _b64url_encode(_b64url_decode(public_key))
        except (binascii.Error, ValueError):
            given = ""
        if given != derived:
            logger.error("WEBPUSH_VAPID_PUBLIC_KEY does not belong to WEBPUSH_VAPID_PRIVATE_KEY; Web Push is off")
            return None
    return VapidConfig(private_key=private_key.strip(), public_key=derived, subject=subject)


def vapid_config() -> Optional[VapidConfig]:
    """The VAPID configuration, or None when Web Push is off (no key, or a bad one)."""
    private_key = settings.WEBPUSH_VAPID_PRIVATE_KEY
    if not private_key:
        return None
    return _load_vapid(private_key, settings.WEBPUSH_VAPID_PUBLIC_KEY, _subject())


def push_enabled() -> bool:
    """Whether Web Push is configured."""
    return vapid_config() is not None


def _allowed_hosts() -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(exact, suffixes)`` of the accepted hosts; extra hosts may use ``*.example.com``."""
    exact: List[str] = []
    suffixes: List[str] = []
    entries: Iterable[str] = list(DEFAULT_ALLOWED_HOSTS) + list(settings.WEBPUSH_EXTRA_ALLOWED_HOSTS or [])
    for raw in entries:
        host = str(raw or "").strip().lower().rstrip(".")
        if not host:
            continue
        if host.startswith("*."):
            host = host[1:]
        (suffixes if host.startswith(".") else exact).append(host)
    return tuple(exact), tuple(suffixes)


def endpoint_allowed(endpoint: str) -> bool:
    """Whether the server may POST to ``endpoint``: https, no credentials, default port, an allowed host."""
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > ENDPOINT_MAX_CHARS:
        return False
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or not parts.hostname:
        return False
    if port not in (None, 443):
        return False
    host = parts.hostname.lower().rstrip(".")
    exact, suffixes = _allowed_hosts()
    return host in exact or any(host.endswith(suffix) and len(host) > len(suffix) for suffix in suffixes)


def parse_subscription(data: Any) -> Dict[str, str]:
    """Validate a browser ``PushSubscription`` JSON.

    Args:
        data: ``{endpoint, keys: {p256dh, auth}, expirationTime?}``.

    Returns:
        ``{endpoint, p256dh, auth}``.

    Raises:
        InvalidSubscription: The endpoint is not an allowed push service, or a key is malformed.
    """
    if not isinstance(data, dict):
        raise InvalidSubscription("expected a PushSubscription object")
    endpoint = data.get("endpoint")
    if not endpoint_allowed(endpoint):
        raise InvalidSubscription("endpoint must be an https URL of a known push service")
    keys = data.get("keys")
    if not isinstance(keys, dict):
        raise InvalidSubscription("keys are required")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    try:
        raw_p256dh = _b64url_decode(p256dh) if isinstance(p256dh, str) else b""
        raw_auth = _b64url_decode(auth) if isinstance(auth, str) else b""
    except (binascii.Error, ValueError):
        raise InvalidSubscription("keys must be base64url") from None
    if len(raw_p256dh) != 65 or raw_p256dh[0] != 0x04:
        raise InvalidSubscription("keys.p256dh must be an uncompressed P-256 public key")
    if len(raw_auth) != 16:
        raise InvalidSubscription("keys.auth must be 16 bytes")
    return {"endpoint": endpoint, "p256dh": _b64url_encode(raw_p256dh), "auth": _b64url_encode(raw_auth)}


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_payload(
    *, kind: str, title: str, body: str, url: str, conversation_id: Optional[str]
) -> Dict[str, Any]:
    """The JSON the service worker turns into a notification, bounded to fit Web Push.

    A known kind leads with its heading (:func:`docsgpt.notifications.kinds.push_text`).
    """
    safe_url = url if isinstance(url, str) and url.startswith("/") and not url.startswith("//") else "/"
    shown_title, shown_body = push_text(kind, title, body)
    return {
        "kind": kind,
        "title": _clip(shown_title, TITLE_MAX_CHARS) or FALLBACK_TITLE,
        "body": _clip(shown_body, BODY_MAX_CHARS),
        "url": safe_url[:URL_MAX_CHARS],
        "conversation_id": conversation_id,
        # One notification per conversation: a newer one replaces it on the device.
        "tag": f"docsgpt:{conversation_id}" if conversation_id else f"docsgpt:{kind}",
    }


def _topic(payload: Dict[str, Any]) -> str:
    """The ``Topic`` header: an undelivered push with the same topic is replaced, not queued."""
    return _b64url_encode(hashlib.sha256(str(payload.get("tag")).encode()).digest())[:32]


class _NoRedirectSession(requests.Session):
    """A session that never follows a redirect: a push service has no reason to send one."""

    def request(self, method, url, *args, **kwargs):  # noqa: D401 - requests' signature
        kwargs["allow_redirects"] = False
        return super().request(method, url, *args, **kwargs)


def _send_one(subscription: Dict[str, Any], data: str, config: VapidConfig, topic: str) -> int:
    """POST one encrypted notification; returns the push service's status code."""
    from py_vapid import Vapid
    from pywebpush import webpush, WebPushException

    try:
        response = webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
            },
            data=data,
            vapid_private_key=Vapid.from_raw(config.private_key.encode()),
            vapid_claims={"sub": config.subject},
            ttl=PUSH_TTL_SECONDS,
            timeout=SEND_TIMEOUT_SECONDS,
            headers={"Urgency": "normal", "Topic": topic},
            requests_session=_NoRedirectSession(),
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None:
            raise
        return int(status)
    return int(response.status_code)


def deliver(user_id: str, payload: Dict[str, Any]) -> Dict[str, int]:
    """Send ``payload`` to every Web Push subscription of the user.

    Args:
        user_id: The user.
        payload: From :func:`build_payload`.

    Returns:
        Counts: ``sent``, ``pruned`` (gone or failing for good), ``failed``,
        ``skipped`` (endpoint no longer allowed).
    """
    from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository
    from docsgpt.storage.db.session import db_readonly, db_session

    counts = {"sent": 0, "pruned": 0, "failed": 0, "skipped": 0}
    config = vapid_config()
    if config is None or not user_id:
        return counts
    with db_readonly() as conn:
        subscriptions = PushSubscriptionsRepository(conn).list_for_user(str(user_id))
    data = json.dumps(payload, ensure_ascii=False)
    topic = _topic(payload)
    for subscription in subscriptions[:MAX_SUBSCRIPTIONS_PER_USER]:
        sub_id = str(subscription["id"])
        if not endpoint_allowed(subscription.get("endpoint")):
            counts["skipped"] += 1
            continue
        try:
            status = _send_one(subscription, data, config, topic)
        except Exception as exc:
            logger.info("web push to subscription %s failed: %s", sub_id, type(exc).__name__)
            status = None
        with db_session() as conn:
            repo = PushSubscriptionsRepository(conn)
            if status is not None and 200 <= status < 300:
                repo.record_success(sub_id)
                counts["sent"] += 1
            elif status in (404, 410):
                repo.delete(sub_id)
                counts["pruned"] += 1
            else:
                failures = repo.record_failure(sub_id)
                counts["failed"] += 1
                if status is not None:
                    logger.info("web push to subscription %s answered %s", sub_id, status)
                if failures is not None and failures >= MAX_CONSECUTIVE_FAILURES:
                    repo.delete(sub_id)
                    counts["pruned"] += 1
    return counts
