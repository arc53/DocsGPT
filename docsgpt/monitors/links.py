"""Trigger and approval links: tokens, secrets and the URLs handed to the user.

A token is 32 random bytes (``secrets.token_urlsafe``), shown once in the
tool result; only its sha256 is stored, and a link is looked up by that
hash. Webhook secrets are random too and stored encrypted for the owner.

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
import secrets
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

from docsgpt.core.settings import settings

#: Random bytes in a link token (256 bits).
TOKEN_BYTES = 32

#: Accepted requests a webhook link takes over its lifetime.
WEBHOOK_MAX_HITS = 1000

_TOKEN_PREFIX = {"webhook": "trg_", "approval": "apv_"}


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


_EXAMPLE_BODY = {"status": "success", "detail": "example"}


def example_curl(url: str, scheme: str, secret: Optional[str]) -> str:
    """A command that calls the link correctly for its signature scheme."""
    body = json.dumps(_EXAMPLE_BODY, separators=(",", ":"))
    if scheme in ("github", "hmac_sha256") and secret:
        header = "X-Hub-Signature-256" if scheme == "github" else "X-Signature"
        return (
            f"body='{body}'; "
            f"sig=$(printf '%s' \"$body\" | openssl dgst -sha256 -hmac '{secret}' | sed 's/^.* //'); "
            f"curl -X POST '{url}' -H 'Content-Type: application/json' -H \"{header}: sha256=$sig\" "
            "--data-raw \"$body\""
        )
    if scheme == "standard_webhooks":
        return (
            f"# Sign with a Standard Webhooks library (e.g. `pip install standardwebhooks`) using the secret:\n"
            f"# Webhook(secret).sign(msg_id, timestamp, body) -> send webhook-id, webhook-timestamp, "
            f"webhook-signature headers\n"
            f"curl -X POST '{url}' -H 'Content-Type: application/json' -H 'webhook-id: msg_1' "
            f"-H \"webhook-timestamp: $(date +%s)\" -H 'webhook-signature: v1,<signature>' --data-raw '{body}'"
        )
    return f"curl -X POST '{url}' -H 'Content-Type: application/json' --data-raw '{body}'"


def signing_instructions(scheme: str) -> Optional[str]:
    """What the sender must configure for ``scheme``, in a sentence."""
    return {
        "github": (
            "In the repository's Settings > Webhooks > Add webhook: Payload URL = the url, Content type = "
            "application/json, Secret = the secret, then pick the events. GitHub signs each delivery with "
            "X-Hub-Signature-256."
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


def link_view(link: Dict[str, object]) -> Dict[str, object]:
    """The safe parts of a link row for lists and the UI (never the token hash or secret)."""
    return {
        "id": link.get("id"),
        "kind": link.get("kind"),
        "signature": link.get("signature_scheme"),
        "expires_at": link.get("expires_at"),
        "hit_count": link.get("hit_count"),
        "max_hits": link.get("max_hits"),
        "last_hit_at": link.get("last_hit_at"),
        "revoked": bool(link.get("revoked_at")),
        "decided": bool(link.get("decision")),
    }
