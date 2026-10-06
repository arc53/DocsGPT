"""Trigger and approval links: tokens, secrets and the URLs handed to the user.

A token is 32 random bytes (``secrets.token_urlsafe``), shown once in the
tool result; only its sha256 is stored, and a link is looked up by that
hash. Webhook secrets are random too and stored encrypted for the owner. The
model never sees a secret: the tool result carries :data:`SECRET_PLACEHOLDER`
and an example command that reads :data:`SECRET_ENV`, and the owner reveals the
secret in the chat (``GET /api/monitors/<id>/secret``).

URLs are absolute, built from ``PUBLIC_API_BASE_URL`` (else ``API_URL``);
approval pages from ``PUBLIC_APP_URL`` when the UI runs elsewhere. A base
that only this machine or network can reach (localhost, a private address,
a bare container hostname) is reported as such, so the model can tell the
user an outside service won't get through.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

from docsgpt.core.settings import settings

#: Random bytes in a link token (256 bits).
TOKEN_BYTES = 32

#: Accepted requests a webhook link takes over its lifetime.
WEBHOOK_MAX_HITS = 1000

_TOKEN_PREFIX = {"webhook": "trg_", "approval": "apv_"}

#: What the model is given in place of a signing secret.
SECRET_PLACEHOLDER = "hidden from you; the user reveals it on the link card in this chat"

#: The environment variable the example command reads the secret from.
SECRET_ENV = "DOCSGPT_WEBHOOK_SECRET"


def new_token(kind: str) -> str:
    """A fresh link token (``trg_…`` for a webhook, ``apv_…`` for an approval)."""
    return _TOKEN_PREFIX.get(kind, "") + secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    """The stored form of a token: its sha256, hex."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_secret(scheme: str) -> Optional[str]:
    """A signing secret for ``scheme``, or None when the link is unsigned.

    Standard Webhooks secrets are ``whsec_`` + base64 of 32 random bytes
    (the key is the decoded bytes, per the spec); GitHub and plain HMAC
    secrets are random URL-safe strings used as the key's UTF-8 bytes.
    """
    if scheme == "standard_webhooks":
        return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    if scheme in ("github", "hmac_sha256"):
        return secrets.token_urlsafe(32)
    return None


def seal_secret(secret: Optional[str], user_id: str) -> Optional[str]:
    """Encrypt a signing secret for storage."""
    if not secret:
        return None
    from docsgpt.security.encryption import encrypt_json

    return encrypt_json({"secret": secret}, user_id)


def open_secret(sealed: Optional[str], user_id: str) -> Optional[str]:
    """Decrypt a stored signing secret (None when there is none)."""
    if not sealed:
        return None
    from docsgpt.security.encryption import decrypt_json

    return decrypt_json(sealed, user_id).get("secret")


def api_base_url() -> str:
    """The public base URL of the API: ``PUBLIC_API_BASE_URL``, else ``API_URL``."""
    base = (settings.PUBLIC_API_BASE_URL or "").strip() or (settings.API_URL or "").strip()
    return base.rstrip("/")


def app_base_url() -> str:
    """The public base URL of the web UI: ``PUBLIC_APP_URL``, else the API's (it serves the UI)."""
    base = (getattr(settings, "PUBLIC_APP_URL", None) or "").strip()
    return base.rstrip("/") if base else api_base_url()


def trigger_url(token: str) -> str:
    return f"{api_base_url()}/api/triggers/{token}"


def approval_page_url(token: str) -> str:
    return f"{app_base_url()}/approve/{token}"


def approval_api_url(token: str) -> str:
    return f"{api_base_url()}/api/approvals/{token}"


def reachability(url: str) -> Tuple[bool, Optional[str]]:
    """Whether a link looks reachable from the internet, and why not.

    Args:
        url: The link.

    Returns:
        ``(public, note)``: ``note`` explains a link only this machine or network can open.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "the link's base URL is malformed; set PUBLIC_API_BASE_URL"
    host = (parts.hostname or "").lower()
    if not host:
        return False, "the instance has no public URL configured (PUBLIC_API_BASE_URL)"
    local_note = (
        "this link uses {where}, so only this machine or network can open it; an outside service "
        "or person can't reach it until the instance has a public URL (PUBLIC_API_BASE_URL)"
    )
    if host in ("localhost", "0.0.0.0") or host.endswith((".localhost", ".local", ".internal", ".lan")):
        return False, local_note.format(where=host)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            return False, local_note.format(where=f"the bare hostname {host!r}")
        return True, None
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        return False, local_note.format(where=f"the private address {host}")
    return True, None


#: A plain dotted path (``status``, ``deployment.state``) an example body can be built for.
_SIMPLE_PATH = re.compile(r"^[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*$")

#: Stands for the send time in an example body until it becomes ``printf``'s ``%s``.
_SENT_AT = "\x00sent_at\x00"


def example_body(check: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The JSON an example call sends: what the monitor's status check reads, plus a ``sent_at`` time.

    The time makes each call's body different, so a repeat of the example
    within ``TRIGGER_DEDUPE_WINDOW_SECONDS`` is not taken for a duplicate.

    Args:
        check: The monitor's check; a status check on a plain dotted path
            puts its first final state there.

    Returns:
        The body, with :data:`_SENT_AT` where the time goes.
    """
    body: Dict[str, Any] = {"status": "success", "detail": "example"}
    if check and check.get("type") == "status" and check.get("terminal"):
        path = str(check.get("value_path") or "")
        if _SIMPLE_PATH.match(path):
            body = {}
            node = body
            *parents, leaf = path.split(".")
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = str(check["terminal"][0])
    body.setdefault("sent_at", _SENT_AT)
    return body


def _quoted(value: str) -> str:
    """``value`` as one single-quoted shell word, whatever it contains."""
    return "'" + value.replace("'", "'\\''") + "'"


def _body_command(check: Optional[Dict[str, Any]]) -> str:
    """Shell that sets ``$body`` to the example JSON with the current UTC time, quoted safely."""
    template = json.dumps(example_body(check), separators=(",", ":"), ensure_ascii=False)
    template = template.replace("%", "%%").replace(json.dumps(_SENT_AT)[1:-1], "%s")
    return f"body=$(printf {_quoted(template)} \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\")"


def example_curl(url: str, scheme: str, check: Optional[Dict[str, Any]] = None) -> str:
    """A command that calls the link correctly for its signature scheme.

    A signed link's command reads the secret from ``$DOCSGPT_WEBHOOK_SECRET``,
    so the command can be shown to the model and kept in the chat. The body
    fits the monitor's status check (see :func:`example_body`).

    Args:
        url: The link.
        scheme: Its signature scheme.
        check: The monitor's check, to shape the example body.

    Returns:
        A one-line shell command.
    """
    body = _body_command(check)
    target = _quoted(url)
    if scheme in ("github", "hmac_sha256"):
        header = "X-Hub-Signature-256" if scheme == "github" else "X-Signature"
        return (
            f"{body}; "
            f"sig=$(printf '%s' \"$body\" | openssl dgst -sha256 -hmac \"${SECRET_ENV}\" | sed 's/^.* //'); "
            f"curl -X POST {target} -H 'Content-Type: application/json' -H \"{header}: sha256=$sig\" "
            "--data-raw \"$body\""
        )
    if scheme == "standard_webhooks":
        return (
            f"{body}; id=\"msg_$(date +%s)\"; ts=$(date +%s); "
            f"key=$(printf '%s' \"${{{SECRET_ENV}#whsec_}}\" | base64 -d | xxd -p | tr -d '\\n'); "
            "sig=$(printf '%s' \"$id.$ts.$body\" | openssl dgst -sha256 -mac HMAC -macopt hexkey:$key -binary "
            "| base64); "
            f"curl -X POST {target} -H 'Content-Type: application/json' -H \"webhook-id: $id\" "
            "-H \"webhook-timestamp: $ts\" -H \"webhook-signature: v1,$sig\" --data-raw \"$body\""
        )
    return f"{body}; curl -X POST {target} -H 'Content-Type: application/json' --data-raw \"$body\""


def signing_instructions(scheme: str) -> Optional[str]:
    """What the sender must configure for ``scheme``, in a sentence."""
    return {
        "github": (
            "In the repository's Settings > Webhooks > Add webhook: Payload URL = the url, Content type = "
            "application/json, Secret = the secret from the link card, then pick the events. GitHub signs each "
            "delivery with X-Hub-Signature-256."
        ),
        "hmac_sha256": (
            "Sign the raw request body with HMAC-SHA256 using the secret and send it as "
            "X-Signature: sha256=<hex digest>."
        ),
        "standard_webhooks": (
            "Send webhook-id, webhook-timestamp and webhook-signature headers per the Standard Webhooks spec "
            "(any Standard Webhooks or Svix library signs with this whsec_ secret). Deliveries older than "
            "5 minutes are refused."
        ),
    }.get(scheme)


def link_state(link: Dict[str, Any]) -> str:
    """Whether a link still works: ``live``, ``revoked``, ``expired`` or ``used_up`` (its calls, or its decision)."""
    if link.get("revoked_at"):
        return "revoked"
    expires = link.get("expires_at")
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            expires = None
    if isinstance(expires, datetime):
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return "expired"
    if link.get("decision") or int(link.get("hit_count") or 0) >= int(link.get("max_hits") or 0) > 0:
        return "used_up"
    return "live"


def link_view(link: Dict[str, Any]) -> Dict[str, Any]:
    """The safe parts of a link row for lists and the UI (never the token hash or secret)."""
    return {
        "id": link.get("id"),
        "kind": link.get("kind"),
        "state": link_state(link),
        "signature": link.get("signature_scheme"),
        "expires_at": link.get("expires_at"),
        "hit_count": link.get("hit_count"),
        "max_hits": link.get("max_hits"),
        "last_hit_at": link.get("last_hit_at"),
        "revoked": bool(link.get("revoked_at")),
        "decided": bool(link.get("decision")),
    }
