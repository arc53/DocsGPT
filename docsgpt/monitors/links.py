"""Trigger and approval links: tokens, secrets and the URLs handed to the user.

A token is 32 random bytes (``secrets.token_urlsafe``), shown once in the
tool result; only its sha256 is stored, and a link is looked up by that
hash. Webhook secrets are random too and stored encrypted for the owner. The
model never sees a secret unless the link was created with
``expose_secret``: the tool result carries the reference
``{{link_secret:REF}}`` (:mod:`docsgpt.monitors.secret_refs` fills the value
into tool calls the user approves) and an example command that reads
:data:`SECRET_ENV`, and the owner reveals the secret in the chat or on the
Monitors page (``GET /api/monitors/<id>/secret``).

URLs are absolute, built from ``PUBLIC_API_BASE_URL`` (else ``API_URL``);
approval pages from ``PUBLIC_APP_URL`` when the UI runs elsewhere. A base
that only this machine or network can reach (localhost, a private address,
a bare container hostname) is reported as such, so the model can tell the
user an outside service won't get through.
"""

from __future__ import annotations

import base64
import binascii
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
    if scheme in ("github", "hmac_sha256", "header_token", "bearer"):
        return secrets.token_urlsafe(32)
    # Stripe and Slack create their own signing secret; the owner pastes it in (PUT /api/monitors/<id>/secret).
    return None


#: Schemes whose secret the sender creates, so a new link has none until the owner sets it.
SENDER_SECRET_SCHEMES = ("stripe", "slack")

#: Shortest secret the owner may set.
MIN_SECRET_CHARS = 16

#: Longest secret the owner may set.
MAX_SECRET_CHARS = 512


def check_owner_secret(scheme: str, secret: Any) -> str:
    """Validate a signing secret the owner pastes in, for the link's scheme.

    Args:
        scheme: The link's signature scheme.
        secret: What was pasted.

    Returns:
        The secret, trimmed.

    Raises:
        ValueError: It can't be this scheme's secret (the message says why).
    """
    if not isinstance(secret, str):
        raise ValueError("the secret must be text")
    value = secret.strip()
    if not MIN_SECRET_CHARS <= len(value) <= MAX_SECRET_CHARS or any(ch.isspace() for ch in value):
        raise ValueError(
            f"a signing secret is {MIN_SECRET_CHARS} to {MAX_SECRET_CHARS} characters with no spaces"
        )
    if not value.isprintable():
        raise ValueError("the secret has characters a signing secret never has")
    if scheme == "stripe" and not value.startswith("whsec_"):
        raise ValueError("a Stripe endpoint signing secret starts with whsec_")
    if scheme == "standard_webhooks":
        raw = value[len("whsec_"):] if value.startswith("whsec_") else value
        try:
            base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("a Standard Webhooks secret is whsec_ followed by base64") from None
    return value


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


def example_get(
    url: str, check: Optional[Dict[str, Any]] = None, scheme: str = "none", header_name: Optional[str] = None
) -> str:
    """A GET call to a link that takes GET: the example body's fields as query parameters.

    Args:
        url: The link.
        check: The monitor's check, to shape the parameters.
        scheme: The link's signature scheme (a static-token one adds its header).
        header_name: The header a ``header_token`` link reads.

    Returns:
        A one-line shell command.
    """
    from urllib.parse import urlencode

    params: Dict[str, str] = {}

    def flatten(node: Dict[str, Any], prefix: str) -> None:
        for key, value in node.items():
            if value == _SENT_AT:
                continue
            if isinstance(value, dict):
                flatten(value, f"{prefix}{key}.")
            else:
                params[f"{prefix}{key}"] = str(value)

    # Dotted keys nest again on arrival, so a check's value_path reads them as from a JSON body.
    flatten(example_body(check), "")
    query = urlencode(params)
    token_header = _token_header(scheme, header_name)
    header = f' -H "{token_header}"' if token_header else ""
    return f"curl{header} {_quoted(url + ('?' + query if query else ''))}"


def _token_header(scheme: str, header_name: Optional[str]) -> Optional[str]:
    """The header line (with ``$DOCSGPT_WEBHOOK_SECRET``) a static-token scheme sends, or None."""
    if scheme == "header_token":
        return f"{header_name or 'X-Webhook-Token'}: ${SECRET_ENV}"
    if scheme == "bearer":
        return f"Authorization: Bearer ${SECRET_ENV}"
    return None


def example_curl(
    url: str, scheme: str, check: Optional[Dict[str, Any]] = None, header_name: Optional[str] = None
) -> str:
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
    token_header = _token_header(scheme, header_name)
    if token_header:
        return (
            f"{body}; curl -X POST {target} -H 'Content-Type: application/json' -H \"{token_header}\" "
            "--data-raw \"$body\""
        )
    if scheme == "stripe":
        return (
            f"{body}; ts=$(date +%s); "
            f"sig=$(printf '%s' \"$ts.$body\" | openssl dgst -sha256 -hmac \"${SECRET_ENV}\" | sed 's/^.* //'); "
            f"curl -X POST {target} -H 'Content-Type: application/json' -H \"Stripe-Signature: t=$ts,v1=$sig\" "
            "--data-raw \"$body\""
        )
    if scheme == "slack":
        return (
            f"{body}; ts=$(date +%s); "
            f"sig=$(printf '%s' \"v0:$ts:$body\" | openssl dgst -sha256 -hmac \"${SECRET_ENV}\" | sed 's/^.* //'); "
            f"curl -X POST {target} -H 'Content-Type: application/json' -H \"X-Slack-Request-Timestamp: $ts\" "
            "-H \"X-Slack-Signature: v0=$sig\" --data-raw \"$body\""
        )
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


def signing_instructions(scheme: str, header_name: Optional[str] = None) -> Optional[str]:
    """What the sender must configure for ``scheme``, in a sentence."""
    return {
        "stripe": (
            "In Stripe's Dashboard (Developers > Webhooks > Add endpoint): Endpoint URL = the url, then pick the "
            "events. Stripe creates the endpoint's signing secret (whsec_...); the user copies it from the "
            "endpoint's page and pastes it with Set signing secret on the link card. Calls are refused until "
            "then. Stripe signs each delivery with Stripe-Signature."
        ),
        "slack": (
            "In the Slack app's settings: copy the Signing Secret from Basic Information and paste it with Set "
            "signing secret on the link card first, then put the url in Event Subscriptions > Request URL (Slack "
            "verifies it at once). Slack signs each request with X-Slack-Signature."
        ),
        "header_token": (
            f"Send the secret as the {header_name or 'X-Webhook-Token'} header on every call (GitLab: Settings > "
            "Webhooks > Secret token, with X-Gitlab-Token as the header)."
        ),
        "bearer": "Send the secret as Authorization: Bearer <secret> on every call.",
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
    ref = link.get("ref")
    return {
        "id": link.get("id"),
        "kind": link.get("kind"),
        "state": link_state(link),
        "signature": link.get("signature_scheme"),
        "secret_ref": "{{link_secret:" + str(ref) + "}}" if ref else None,
        "signature_header": link.get("signature_header"),
        "has_secret": bool(link.get("secret_encrypted")),
        "methods": ["POST", "GET"] if link.get("allow_get") else ["POST"] if link.get("kind") == "webhook" else None,
        "expires_at": link.get("expires_at"),
        "hit_count": link.get("hit_count"),
        "max_hits": link.get("max_hits"),
        "last_hit_at": link.get("last_hit_at"),
        "revoked": bool(link.get("revoked_at")),
        "decided": bool(link.get("decision")),
    }
