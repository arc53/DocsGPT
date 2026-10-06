"""Secret references: a webhook link's signing secret used in a tool call without the model ever seeing it.

``monitor_create`` gives the model ``{{link_secret:REF}}`` (``REF`` is the
link's stable short id) instead of the secret. The model writes that
reference into a tool call that configures the sender (a ``remote_device``
command that registers the hook, an MCP or API action that creates it).
The executor fills in the real value only when the call runs, and only when:

* the tool is one that acts on a device or service (:data:`SUBSTITUTING_TOOLS`)
  and the action is not one that sends a message (:func:`sends_messages`);
* the turn is interactive (not headless, not an API-key or public-link
  caller), so the user is there to approve it;
* the user approved this very call: a call carrying a reference always
  asks for approval (:func:`plan`), whatever the tool's usual mode;
* the reference names one of the user's own live signed links;
* the reference is not in a URL (a value under a URL-like key, or a string
  that is a URL), where it would end up in logs and history.

Anything else is refused with a message for the model, and the tool does not
run. Everything recorded about the call (the journal, the conversation, logs,
traces, the job's arguments, the device audit row) keeps the reference, and
any echo of a substituted value in what the tool returns is put back to the
reference before it reaches the model or storage (:func:`redact`). Each
substitution is an audit event (``monitor.secret_substituted``) without the
value.
"""

from __future__ import annotations

import contextvars
import copy
import logging
import re
import secrets as _secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: Characters of a link's reference id: no 0/O, 1/I/L, so it reads and types back unambiguously.
REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: Length of a reference id.
REF_LENGTH = 6

#: ``{{link_secret:REF}}``, spaces and case tolerated.
REF_PATTERN = re.compile(r"\{\{\s*link_secret\s*:\s*([A-Za-z0-9]{4,16})\s*\}\}")

#: Tools that may receive a substituted secret: ones that act on a device or service.
SUBSTITUTING_TOOLS = frozenset({"remote_device", "mcp_tool", "api_tool"})

#: Action names that send a message somewhere (a reference there would publish the secret).
_MESSAGE_ACTION = re.compile(
    r"(?:^|[_\-.\s])(send|sends|message|messages|mail|email|emails|reply|chat|chats|comment|comments|notify|"
    r"notification|notifications|publish|sms|tweet|dm|forward|post_message|postmessage|broadcast)(?:$|[_\-.\s])",
    re.IGNORECASE,
)

#: Argument keys whose value is a URL (never substituted into).
_URL_KEY = re.compile(r"(?:^|_)(url|uri|href|link|links|endpoint)$", re.IGNORECASE)

#: A URL inside a longer string (a shell command) that carries a reference.
_REF_IN_URL = re.compile(r"(?:https?|wss?|ftp)://[^\s\"'<>`]*\{\{\s*link_secret", re.IGNORECASE)

_active: contextvars.ContextVar[Optional["Substitution"]] = contextvars.ContextVar(
    "docsgpt_secret_substitution", default=None
)


class SecretRefError(ValueError):
    """A call's secret reference can't be filled in; the message is written for the model."""


def reference(ref: str) -> str:
    """``{{link_secret:REF}}`` for a link's reference id."""
    return "{{link_secret:" + str(ref) + "}}"


def new_ref() -> str:
    """A fresh reference id (6 characters from :data:`REF_ALPHABET`)."""
    return "".join(_secrets.choice(REF_ALPHABET) for _ in range(REF_LENGTH))


def find_refs(value: Any) -> List[str]:
    """Every reference id in ``value`` (strings in nested dicts and lists), upper-cased, in order, once each."""
    found: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for match in REF_PATTERN.finditer(node):
                ref = match.group(1).upper()
                if ref not in found:
                    found.append(ref)
        elif isinstance(node, dict):
            for key, child in node.items():
                walk(key)
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(value)
    return found


def sends_messages(action_name: Optional[str]) -> bool:
    """Whether an action name reads like one that sends a message (``send_email``, ``post_message``)."""
    return bool(action_name) and bool(_MESSAGE_ACTION.search(str(action_name)))


def _refusal_text(refs: Iterable[str], why: str) -> str:
    names = ", ".join(reference(ref) for ref in refs)
    return (
        f"This call contains {names}, a link secret reference, and {why} Nothing ran. A reference is filled in "
        "only when the user approves a call that configures a device or service (a remote_device command, an "
        "MCP or API action that sets up the sender); it never goes into messages, URLs or fetched pages. The "
        "user can also reveal the secret on the link card and enter it themselves."
    )


@dataclass
class Plan:
    """What the executor does with a call that carries references.

    Attributes:
        refs: The reference ids in the call.
        refusal: Why it can't run (the message for the model), or None when
            it runs once the user approves it.
    """

    refs: List[str]
    refusal: Optional[str] = None


def _caller_refusal(executor: Any) -> Optional[str]:
    if getattr(executor, "headless", False):
        return "this run has nobody to approve it (a scheduled or background run)."
    if getattr(executor, "external_caller", False) or getattr(executor, "public_link_caller", False):
        return "only the owner, in their own chat, can approve one."
    if not getattr(executor, "user", None):
        return "there is no signed-in user to approve it."
    return None


def plan(executor: Any, tool_data: Dict[str, Any], action_name: str, arguments: Any) -> Optional[Plan]:
    """Decide what happens to a call that carries secret references (None when it carries none).

    Args:
        executor: The turn's ``ToolExecutor``.
        tool_data: The tool row being called.
        action_name: The action.
        arguments: The model's arguments.

    Returns:
        None for a call without references; else a :class:`Plan` whose
        ``refusal`` is set when the call can't take a secret at all.
    """
    refs = find_refs(arguments)
    if not refs:
        return None
    tool_name = str(tool_data.get("name") or "")
    if tool_name not in SUBSTITUTING_TOOLS or tool_data.get("client_side"):
        return Plan(refs, _refusal_text(refs, f"{tool_name or 'this tool'} never receives secrets."))
    if sends_messages(action_name):
        return Plan(refs, _refusal_text(refs, "this action sends a message, which would publish the secret."))
    refused = _caller_refusal(executor)
    if refused:
        return Plan(refs, _refusal_text(refs, refused))
    try:
        _check_placement(arguments)
    except SecretRefError as exc:
        return Plan(refs, _refusal_text(refs, str(exc)))
    return Plan(refs)


def _is_url(value: str) -> bool:
    stripped = value.strip()
    if not stripped.lower().startswith(("http://", "https://", "ws://", "wss://", "ftp://")):
        return False
    try:
        return bool(urlsplit(stripped).netloc)
    except ValueError:
        return True


def _check_placement(arguments: Any, key: Optional[str] = None) -> None:
    """Raise when a reference sits in a URL: under a URL-like key, or inside a string that is a URL."""
    if isinstance(arguments, str):
        if REF_PATTERN.search(arguments) and (
            (key and _URL_KEY.search(key)) or _is_url(arguments) or _REF_IN_URL.search(arguments)
        ):
            raise SecretRefError("a secret never goes into a URL, where it would land in logs and history.")
        return
    if isinstance(arguments, dict):
        for child_key, child in arguments.items():
            _check_placement(child, str(child_key))
    elif isinstance(arguments, (list, tuple)):
        for child in arguments:
            _check_placement(child, key)


@dataclass
class Substitution:
    """The values filled into one call, and how to put the references back.

    Attributes:
        kwargs: The tool's keyword arguments with the secrets filled in.
        values: ``{secret: reference}`` for redaction.
        links: ``[(ref, link_id)]`` substituted, for the audit trail.
    """

    kwargs: Dict[str, Any]
    values: Dict[str, str] = field(default_factory=dict)
    links: List[Tuple[str, str]] = field(default_factory=list)

    def redact(self, value: Any) -> Any:
        """``value`` with every substituted secret put back to its reference."""
        return redact(value, self.values)


def _lookup(user_id: str, refs: Iterable[str], *, live_only: bool) -> Dict[str, Dict[str, Any]]:
    """The user's signed links by reference id, with their secrets opened."""
    from docsgpt.monitors import links
    from docsgpt.storage.db.repositories.trigger_links import TriggerLinksRepository
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        rows = TriggerLinksRepository(conn).find_by_refs(user_id, list(refs))
    found: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if live_only and links.link_state(row) != "live":
            continue
        secret = links.open_secret(row.get("secret_encrypted"), user_id) if row.get("secret_encrypted") else None
        if secret:
            found[str(row["ref"]).upper()] = {"secret": secret, "link_id": str(row["id"])}
    return found


def substitute(
    executor: Any,
    tool_data: Dict[str, Any],
    action_name: str,
    kwargs: Dict[str, Any],
    *,
    call_id: str,
    refs: List[str],
) -> Substitution:
    """Fill the referenced secrets into an approved call's arguments.

    Args:
        executor: The turn's ``ToolExecutor`` (``approved_call_ids``, ``user``).
        tool_data: The tool row being called.
        action_name: The action.
        kwargs: The tool's keyword arguments (copied, never changed).
        call_id: The call's id.
        refs: The reference ids in the call.

    Returns:
        The substitution.

    Raises:
        SecretRefError: The call may not take the secrets (the message is for the model).
    """
    decided = plan(executor, tool_data, action_name, kwargs)
    if decided is not None and decided.refusal:
        raise SecretRefError(decided.refusal)
    approved = getattr(executor, "approved_call_ids", None) or set()
    # An approval fills secrets in once: a later call that reuses the id (some providers number calls
    # call_0, call_1 per response) is not covered by it.
    consumed = getattr(executor, "secret_approvals_used", None)
    if call_id not in approved or (isinstance(consumed, set) and call_id in consumed):
        raise SecretRefError(
            _refusal_text(refs, "the user did not approve this call, so the secret was not filled in.")
        )
    if isinstance(consumed, set):
        consumed.add(call_id)
    user_id = str(getattr(executor, "user", "") or "")
    found = _lookup(user_id, refs, live_only=True)
    missing = [ref for ref in refs if ref not in found]
    if missing:
        raise SecretRefError(
            _refusal_text(
                missing,
                "it does not name a live signed link of this user (it may have expired, been cancelled, or still "
                "be waiting for the sender's secret).",
            )
        )
    values = {entry["secret"]: reference(ref) for ref, entry in found.items()}

    def fill(node: Any) -> Any:
        if isinstance(node, str):
            return REF_PATTERN.sub(lambda m: found[m.group(1).upper()]["secret"], node)
        if isinstance(node, dict):
            return {key: fill(child) for key, child in node.items()}
        if isinstance(node, list):
            return [fill(child) for child in node]
        if isinstance(node, tuple):
            return tuple(fill(child) for child in node)
        return node

    filled = fill(copy.deepcopy(kwargs))
    substitution = Substitution(
        kwargs=filled, values=values, links=[(ref, found[ref]["link_id"]) for ref in refs]
    )
    _audit(executor, tool_data, action_name, call_id, substitution)
    return substitution


def _audit(executor: Any, tool_data: Dict[str, Any], action_name: str, call_id: str, done: Substitution) -> None:
    """One ``monitor.secret_substituted`` audit event per link filled in (never the value)."""
    from docsgpt.api.audit import record_event
    from docsgpt.storage.db.session import db_session

    user_id = str(getattr(executor, "user", "") or "")
    try:
        with db_session() as conn:
            for ref, link_id in done.links:
                record_event(
                    conn,
                    "monitor.secret_substituted",
                    actor=user_id,
                    link_id=link_id,
                    ref=ref,
                    tool=tool_data.get("name"),
                    action=action_name,
                    call_id=call_id,
                    conversation_id=getattr(executor, "conversation_id", None),
                )
    except Exception:
        logger.exception("recording a secret substitution failed (call %s)", call_id)


def redact(value: Any, values: Mapping[str, str]) -> Any:
    """``value`` (a string, or strings nested in dicts, lists and tuples) with each secret replaced by its reference.

    Args:
        value: Anything a tool returns.
        values: ``{secret: reference}``.

    Returns:
        A copy with every occurrence put back; other values pass through.
    """
    if not values:
        return value
    ordered = sorted(values.items(), key=lambda item: len(item[0]), reverse=True)

    def scrub(node: Any) -> Any:
        if isinstance(node, str):
            for secret, ref in ordered:
                if secret and secret in node:
                    node = node.replace(secret, ref)
            return node
        if isinstance(node, dict):
            return {scrub(key): scrub(child) for key, child in node.items()}
        if isinstance(node, list):
            return [scrub(child) for child in node]
        if isinstance(node, tuple):
            return tuple(scrub(child) for child in node)
        return node

    return scrub(value)


class RedactionUnavailable(RuntimeError):
    """The secrets to redact could not all be looked up, so the value must not be kept as it is."""


def redact_for_user(value: Any, user_id: str, refs: Iterable[str]) -> Any:
    """Redact the secrets of the user's links named by ``refs`` (live or not) out of ``value``.

    For work that finishes after its call (a device job's output): the
    secrets are looked up again rather than carried anywhere.

    Raises:
        RedactionUnavailable: A secret could not be looked up (the database
            failed, or the link is gone). The caller must withhold the value:
            it may hold the secret.
    """
    refs = [str(ref).upper() for ref in refs or []]
    if not refs:
        return value
    if not user_id:
        raise RedactionUnavailable("no owner to look the secrets up for")
    try:
        found = _lookup(user_id, refs, live_only=False)
    except Exception as exc:
        logger.exception("looking up link secrets to redact failed")
        raise RedactionUnavailable("the link secrets could not be looked up") from exc
    if any(ref not in found for ref in refs):
        raise RedactionUnavailable("a link whose secret was used is gone")
    return redact(value, {entry["secret"]: reference(ref) for ref, entry in found.items()})


def exposed_values(user_id: str) -> Dict[str, str]:
    """``{secret: reference}`` for the user's live links whose owner chose to show the secret to the assistant.

    A model that was shown such a secret may write the raw value into a tool
    call or repeat it; the executor and the stream put the reference back
    wherever they store it, and treat a raw value in a call as its reference.

    Args:
        user_id: The conversation's owner.

    Returns:
        The mapping (empty when the user exposed nothing, or the lookup failed).
    """
    if not user_id:
        return {}
    from docsgpt.monitors import links
    from docsgpt.storage.db.repositories.trigger_links import TriggerLinksRepository
    from docsgpt.storage.db.session import db_readonly

    try:
        with db_readonly() as conn:
            rows = TriggerLinksRepository(conn).list_exposed(str(user_id))
        values: Dict[str, str] = {}
        for row in rows:
            secret = links.open_secret(row.get("secret_encrypted"), str(user_id))
            if secret:
                values[secret] = reference(str(row["ref"]))
        return values
    except Exception:
        logger.exception("looking up exposed link secrets failed")
        return {}


class active:
    """Make a call's substitution visible to the tool running it (``with active(substitution): ...``).

    A tool that records its own copy of the arguments (the device audit log)
    redacts it with :func:`redact_active`; one that hands its work to a
    poller passes :func:`active_refs` along.
    """

    def __init__(self, substitution: Optional[Substitution]) -> None:
        self._substitution = substitution
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> "active":
        if self._substitution is not None:
            self._token = _active.set(self._substitution)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._token is not None:
            _active.reset(self._token)


def redact_active(value: Any) -> Any:
    """``value`` with the running call's substituted secrets put back to their references."""
    current = _active.get()
    return current.redact(value) if current is not None else value


def active_refs() -> List[str]:
    """The reference ids substituted into the running call (empty outside one)."""
    current = _active.get()
    return [ref for ref, _link in current.links] if current is not None else []
