"""The monitor spec: validating what ``monitor_create`` was given, and the values derived from it.

A spec is the model's request after validation, stored as ``monitor_spec``:

``{"source": {...}, "check": {...} | None, "condition": str | None,
"interval_seconds": int | None, "max_wakes": int, "on_match": str}``

Limits come from settings and are applied here: an interval below the
minimum, a lifetime past the maximum and too many wakes are raised or
lowered to the limit, and the change is reported back (``notes``) so the
model can tell the user. Anything malformed raises :class:`SpecError` with
a message written for the model.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import regex

from docsgpt.agents.scheduler_utils import ScheduleValidationError, parse_delay
from docsgpt.core.settings import settings

SOURCE_TYPES = ("webpage", "tool", "ingest", "webhook", "approval")
POLLED_SOURCES = ("webpage", "tool")
CHECK_TYPES = ("changed", "new_items", "regex", "threshold", "status")
SIGNATURE_SCHEMES = (
    "none", "standard_webhooks", "github", "hmac_sha256", "stripe", "slack", "header_token", "bearer"
)
WEBHOOK_METHODS = ("POST", "GET")

#: Schemes a GET call can satisfy: a GET has no body to sign, so only a static token header.
GET_SIGNATURE_SCHEMES = ("none", "header_token", "bearer")

#: Schemes whose secret the sender creates (Stripe, Slack): the owner pastes it in; DocsGPT mints none.
SENDER_SECRET_SCHEMES = ("stripe", "slack")

#: A header name a ``header_token`` link may read.
_HEADER_NAME = regex.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")

#: Headers a token can't live in: they carry other meanings, or a proxy rewrites them.
_RESERVED_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie", "host", "content-type", "content-length",
    "content-encoding", "transfer-encoding", "connection", "upgrade", "user-agent", "accept", "accept-encoding",
    "idempotency-key", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded",
    "via", "te", "trailer", "expect", "origin", "referer",
})

#: Threshold operators, and the words a model may use for them.
OPERATORS = ("<", "<=", ">", ">=", "==", "!=")
_OPERATOR_ALIASES = {
    "lt": "<", "below": "<", "under": "<", "less_than": "<",
    "le": "<=", "lte": "<=", "at_most": "<=",
    "gt": ">", "above": ">", "over": ">", "greater_than": ">",
    "ge": ">=", "gte": ">=", "at_least": ">=",
    "eq": "==", "=": "==", "equals": "==",
    "ne": "!=", "not_equals": "!=", "<>": "!=",
}

DEFAULT_APPROVAL_OPTIONS = ("approve", "reject")

#: Placeholders a tool source's string arguments may hold, replaced on every check.
PLACEHOLDERS = ("{{now}}", "{{last_checked_at}}", "{{last_changed_at}}", "{{last_checked_date}}")

_MAX_DESCRIPTION = 200
_MAX_ON_MATCH = 2000
_MAX_CONDITION = 1000
_MAX_PATTERN = 500
_MAX_ARGS_BYTES = 8192
_MAX_QUESTION = 1000
_MAX_DETAILS = 4000


class SpecError(ValueError):
    """The request can't make a monitor; the message tells the model what to fix."""


@dataclass
class MonitorRequest:
    """A validated ``monitor_create`` request.

    Attributes:
        description: What is watched, shown in every notification.
        source: The normalized source.
        check: The normalized deterministic check, or None.
        condition: The natural-language condition for the judge, or None.
        interval_seconds: Seconds between checks (polled sources only).
        expires_at: When the monitor ends.
        max_wakes: Wakes before it finishes.
        on_match: What the woken agent should do.
        notes: Limits applied to the request, for the model to relay.
    """

    description: str
    source: Dict[str, Any]
    check: Optional[Dict[str, Any]]
    condition: Optional[str]
    interval_seconds: Optional[int]
    expires_at: datetime
    max_wakes: int
    on_match: str
    notes: List[str] = field(default_factory=list)

    @property
    def polled(self) -> bool:
        return self.source["type"] in POLLED_SOURCES

    def spec(self) -> Dict[str, Any]:
        """The ``monitor_spec`` stored for this request."""
        return {
            "source": self.source,
            "check": self.check,
            "condition": self.condition,
            "interval_seconds": self.interval_seconds,
            "max_wakes": self.max_wakes,
            "on_match": self.on_match,
        }


def _text(value: Any, name: str, *, limit: int, required: bool = False) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise SpecError(f"`{name}` is required.")
        return None
    if not isinstance(value, str):
        raise SpecError(f"`{name}` must be a string.")
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise SpecError(f"`{name}` is too long (at most {limit} characters).")
    return cleaned


def _duration(value: Any, name: str) -> Optional[int]:
    """Seconds for ``15m`` / ``2h`` / ``7d`` (or a bare number of seconds)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SpecError(f"`{name}` must look like '15m', '2h' or '7d'.")
    if isinstance(value, (int, float)):
        if value <= 0:
            raise SpecError(f"`{name}` must be positive.")
        return int(value)
    if isinstance(value, str) and value.strip().lower().endswith("w"):
        try:
            weeks = int(value.strip()[:-1])
        except ValueError:
            raise SpecError(f"`{name}` must look like '15m', '2h' or '7d'.") from None
        if weeks <= 0:
            raise SpecError(f"`{name}` must be positive.")
        return weeks * 7 * 86400
    try:
        return int(parse_delay(str(value)).total_seconds())
    except ScheduleValidationError:
        raise SpecError(f"`{name}` must look like '15m', '2h' or '7d'.") from None


def human_duration(seconds: int) -> str:
    """``900`` -> ``15m``, ``86400`` -> ``1d``: the shortest exact unit."""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0 and seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def normalize_operator(value: Any) -> str:
    """A threshold operator in symbol form; raises :class:`SpecError` for an unknown one."""
    if not isinstance(value, str):
        raise SpecError("`check.op` must be one of <, <=, >, >=, ==, !=.")
    op = value.strip().lower()
    op = _OPERATOR_ALIASES.get(op, op)
    if op not in OPERATORS:
        raise SpecError("`check.op` must be one of <, <=, >, >=, ==, !=.")
    return op


def compile_pattern(pattern: str):
    """Compile a check pattern with the ``regex`` module (its matching takes a timeout)."""
    try:
        return regex.compile(pattern)
    except regex.error as exc:
        raise SpecError(f"`check.pattern` is not a valid regular expression: {exc}") from None


def _source(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise SpecError("`source` must be an object with a `type`.")
    kind = raw.get("type")
    if kind not in SOURCE_TYPES:
        raise SpecError(f"`source.type` must be one of: {', '.join(SOURCE_TYPES)}.")
    if kind == "webpage":
        url = _text(raw.get("url"), "source.url", limit=2048, required=True)
        if not url.lower().startswith(("http://", "https://")):
            raise SpecError("`source.url` must be a full http(s) URL.")
        out: Dict[str, Any] = {"type": "webpage", "url": url}
        selector = _text(raw.get("css_selector"), "source.css_selector", limit=300)
        if selector:
            import soupsieve

            try:
                soupsieve.compile(selector)
            except Exception as exc:
                raise SpecError(f"`source.css_selector` is not a valid CSS selector: {exc}") from None
            out["css_selector"] = selector
        return out
    if kind == "tool":
        tool = _text(raw.get("tool"), "source.tool", limit=200, required=True)
        action = _text(raw.get("action"), "source.action", limit=200)
        args = raw.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise SpecError("`source.args` must be an object with the call's arguments.")
        if len(json.dumps(args, default=str)) > _MAX_ARGS_BYTES:
            raise SpecError(f"`source.args` is too large (at most {_MAX_ARGS_BYTES} bytes).")
        out = {"type": "tool", "tool": tool, "args": args}
        if action:
            out["action"] = action
        return out
    if kind == "ingest":
        source_id = _text(raw.get("source_id"), "source.source_id", limit=100, required=True)
        return {"type": "ingest", "source_id": source_id}
    if kind == "webhook":
        scheme = raw.get("signature") or "none"
        if scheme not in SIGNATURE_SCHEMES:
            raise SpecError(f"`source.signature` must be one of: {', '.join(SIGNATURE_SCHEMES)}.")
        out = {"type": "webhook", "signature": scheme}
        header = raw.get("signature_header")
        if header not in (None, ""):
            if scheme != "header_token":
                raise SpecError("`source.signature_header` applies only to signature \"header_token\".")
            if not isinstance(header, str) or not _HEADER_NAME.match(header.strip()):
                raise SpecError("`source.signature_header` must be a header name like X-Gitlab-Token.")
            if header.strip().lower() in _RESERVED_HEADERS or header.strip().lower().startswith("webhook-"):
                raise SpecError(f"`source.signature_header` can't be {header.strip()}: pick a header of its own.")
            out["signature_header"] = header.strip()
        methods = _methods(raw.get("methods"))
        if "GET" in methods:
            if scheme not in GET_SIGNATURE_SCHEMES:
                raise SpecError(
                    f"`source.signature` {scheme!r} signs a request body, and a GET call has none: use GET only "
                    f"with {', '.join(GET_SIGNATURE_SCHEMES)}."
                )
            out["methods"] = methods
        if raw.get("expose_secret") not in (None, False):
            # Only the owner shows a secret to the assistant (Settings > Monitors); a model's request is ignored.
            out["expose_secret_ignored"] = True
        return out
    question = _text(raw.get("question"), "source.question", limit=_MAX_QUESTION, required=True)
    details = _text(raw.get("details") or raw.get("context"), "source.details", limit=_MAX_DETAILS)
    options_raw = raw.get("options") or list(DEFAULT_APPROVAL_OPTIONS)
    if not isinstance(options_raw, list) or not all(isinstance(o, str) and o.strip() for o in options_raw):
        raise SpecError("`source.options` must be a list of short option labels.")
    options: List[str] = []
    for option in options_raw:
        label = option.strip()[:40]
        if label.lower() not in (o.lower() for o in options):
            options.append(label)
    if not 2 <= len(options) <= 6:
        raise SpecError("`source.options` needs 2 to 6 distinct options.")
    allow_comment = raw.get("allow_comment")
    out = {
        "type": "approval",
        "question": question,
        "options": options,
        "allow_comment": True if allow_comment is None else bool(allow_comment),
    }
    if details:
        out["details"] = details
    return out


def _methods(raw: Any) -> List[str]:
    """A webhook's HTTP methods, POST first; POST alone when none are given."""
    if raw in (None, "", []):
        return ["POST"]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(m, str) for m in raw):
        raise SpecError('`source.methods` must be a list like ["POST"] or ["POST", "GET"].')
    wanted = {m.strip().upper() for m in raw}
    unknown = wanted - set(WEBHOOK_METHODS)
    if unknown:
        raise SpecError(f"`source.methods` takes only {', '.join(WEBHOOK_METHODS)}, not {', '.join(sorted(unknown))}.")
    return [m for m in WEBHOOK_METHODS if m in wanted or m == "POST"]


def _check(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise SpecError("`check` must be an object with a `type`.")
    kind = raw.get("type")
    if kind not in CHECK_TYPES:
        raise SpecError(f"`check.type` must be one of: {', '.join(CHECK_TYPES)}.")
    if kind == "changed":
        return {"type": "changed"}
    if kind == "new_items":
        items_path = raw.get("items_path") or ""
        if not isinstance(items_path, str):
            raise SpecError("`check.items_path` must be a path like 'items' or 'data.results'.")
        id_field = _text(raw.get("id_field"), "check.id_field", limit=200, required=True)
        return {"type": "new_items", "items_path": items_path.strip(), "id_field": id_field}
    if kind == "regex":
        pattern = _text(raw.get("pattern"), "check.pattern", limit=_MAX_PATTERN, required=True)
        compile_pattern(pattern)
        when = raw.get("when") or "match"
        if when not in ("match", "no_match"):
            raise SpecError("`check.when` must be 'match' or 'no_match'.")
        return {"type": "regex", "pattern": pattern, "when": when}
    if kind == "threshold":
        op = normalize_operator(raw.get("op"))
        value = raw.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise SpecError("`check.value` must be a number.")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise SpecError("`check.value` must be a number.") from None
        value_path = raw.get("value_path") or ""
        if not isinstance(value_path, str):
            raise SpecError("`check.value_path` must be a path like 'price' or 'data.price'.")
        return {"type": "threshold", "value_path": value_path.strip(), "op": op, "value": number}
    value_path = _text(raw.get("value_path"), "check.value_path", limit=200, required=True)
    terminal = raw.get("terminal")
    if not isinstance(terminal, list) or not terminal:
        raise SpecError("`check.terminal` must list every terminal status (success AND failure states).")
    states = []
    for item in terminal[:20]:
        if not isinstance(item, (str, int, float)) or isinstance(item, bool):
            raise SpecError("`check.terminal` must be a list of status values.")
        label = str(item).strip().lower()
        if label and label not in states:
            states.append(label)
    if not states:
        raise SpecError("`check.terminal` must list every terminal status.")
    return {"type": "status", "value_path": value_path, "terminal": states}


def parse_request(arguments: Dict[str, Any], *, now: Optional[datetime] = None) -> MonitorRequest:
    """Validate ``monitor_create`` arguments into a :class:`MonitorRequest`.

    Args:
        arguments: What the model sent.
        now: The current time (for tests).

    Returns:
        The request, with limits applied and noted.

    Raises:
        SpecError: A field is missing or malformed.
    """
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []
    description = _text(arguments.get("description"), "description", limit=_MAX_DESCRIPTION, required=True)
    source = _source(arguments.get("source"))
    on_match = _text(arguments.get("on_match"), "on_match", limit=_MAX_ON_MATCH)
    condition = _text(arguments.get("condition"), "condition", limit=_MAX_CONDITION)
    kind = source["type"]
    raw_check = arguments.get("check")
    # The decision, or the ingest ending, is the event: a check there could change nothing, so it is
    # dropped with a note rather than refused (a refusal costs a round trip and teaches nothing).
    if kind == "approval":
        check = None
        if raw_check not in (None, {}) or condition:
            notes.append("check and condition ignored: any decision on an approval link wakes you; act on it in "
                         "on_match")
        condition = None
        on_match = on_match or "Tell the user the decision and continue the task it was for."
    elif kind == "ingest":
        check = None
        if raw_check not in (None, {}):
            notes.append("check ignored: the ingest finishing or failing is the event")
    else:
        check = _check(raw_check)
    if source.pop("expose_secret_ignored", False):
        notes.append(
            "expose_secret ignored: you never get a link's raw secret from monitor_create. Use its reference "
            "{{link_secret:REF}}; only the owner can choose to show a secret to you, in Settings > Monitors"
        )
    if not on_match:
        raise SpecError("`on_match` is required: say what to do when the monitor fires.")

    interval: Optional[int] = None
    if kind in POLLED_SOURCES:
        interval = _duration(arguments.get("interval"), "interval") or int(settings.MONITOR_DEFAULT_INTERVAL_SECONDS)
        minimum = int(settings.MONITOR_MIN_INTERVAL_SECONDS)
        if interval < minimum:
            notes.append(f"interval raised to {human_duration(minimum)}, the shortest allowed")
            interval = minimum
    elif arguments.get("interval"):
        notes.append(f"interval ignored: a {kind} monitor is not polled")

    max_ttl = int(settings.MONITOR_MAX_TTL_DAYS) * 86400
    default_ttl = int(settings.MONITOR_DEFAULT_TTL_DAYS) * 86400
    if "GET" in (source.get("methods") or []):
        # Anything that opens a GET link fires it, so it lives a short while unless asked otherwise.
        default_ttl = int(settings.TRIGGER_GET_DEFAULT_TTL_HOURS) * 3600
    ttl = _duration(arguments.get("expires_in"), "expires_in") or default_ttl
    if ttl > max_ttl:
        longer = (
            "to keep the link longer, the user asks for a new one before it expires"
            if kind in ("webhook", "approval")
            else "to keep watching longer, create a new monitor before it expires"
        )
        notes.append(f"lifetime lowered to {human_duration(max_ttl)}, the longest allowed; {longer}")
        ttl = max_ttl
    if interval is not None and interval > ttl:
        raise SpecError("`interval` is longer than the monitor's lifetime (`expires_in`).")

    max_wakes_raw = arguments.get("max_wakes")
    if max_wakes_raw in (None, ""):
        max_wakes = int(settings.MONITOR_DEFAULT_MAX_WAKES)
    else:
        try:
            max_wakes = int(max_wakes_raw)
        except (TypeError, ValueError):
            raise SpecError("`max_wakes` must be a whole number.") from None
        if max_wakes < 1:
            raise SpecError("`max_wakes` must be at least 1.")
    if kind == "approval":
        max_wakes = 1
    elif max_wakes > int(settings.MONITOR_MAX_WAKES):
        notes.append(f"max_wakes lowered to {settings.MONITOR_MAX_WAKES}, the most allowed")
        max_wakes = int(settings.MONITOR_MAX_WAKES)

    return MonitorRequest(
        description=description,
        source=source,
        check=check,
        condition=condition,
        interval_seconds=interval,
        expires_at=now + timedelta(seconds=ttl),
        max_wakes=max_wakes,
        on_match=on_match,
        notes=notes,
    )


# ----------------------------------------------------------------------
# Derived values
# ----------------------------------------------------------------------


def canonical_args_hash(tool_id: str, action: str, args: Dict[str, Any]) -> str:
    """The hash a tool source's approval is bound to: tool row, action and the arguments *template*.

    Placeholders are hashed as written, so the per-check substitution never
    changes it; any other change to the arguments does.
    """
    canonical = json.dumps(
        {"tool_id": str(tool_id), "action": str(action), "args": args or {}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(value: Optional[datetime]) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else ""


def parse_iso(value: Any) -> Optional[datetime]:
    """A tz-aware datetime from a datetime or an ISO 8601 string; None for anything else."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def substitute(args: Any, *, now: datetime, last_checked_at: Any = None, last_changed_at: Any = None) -> Any:
    """Replace the placeholders in a tool source's string arguments.

    ``{{now}}``, ``{{last_checked_at}}`` and ``{{last_changed_at}}`` become
    ISO 8601 UTC times; ``{{last_checked_date}}`` becomes ``YYYY/MM/DD``
    (Gmail-style ``after:`` queries). A monitor that never checked uses now.

    Args:
        args: The arguments template (nested dicts and lists are walked).
        now: The current time.
        last_checked_at: The previous check's time.
        last_changed_at: The previous change's time.

    Returns:
        A copy with the placeholders replaced.
    """
    checked = parse_iso(last_checked_at) or now
    changed = parse_iso(last_changed_at) or checked
    values = {
        "{{now}}": _iso(now),
        "{{last_checked_at}}": _iso(checked),
        "{{last_changed_at}}": _iso(changed),
        "{{last_checked_date}}": checked.astimezone(timezone.utc).strftime("%Y/%m/%d"),
    }

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            for key, replacement in values.items():
                value = value.replace(key, replacement)
            return value
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(args)


def next_tick(now: datetime, interval_seconds: int, end_at: Optional[datetime]) -> datetime:
    """When a polled monitor checks next: one interval on, jittered, never on a :00 or :30 mark.

    Jitter is up to 10% of the interval (at most a minute), so monitors
    created together drift apart; a time landing in minute 0 or 30 of the
    hour moves past it. The expiry caps it, so the last pass expires the
    monitor on time.

    Args:
        now: The current time.
        interval_seconds: The monitor's interval.
        end_at: Its expiry.

    Returns:
        The next ``next_run_at``.
    """
    jitter = random.uniform(0, min(60.0, interval_seconds * 0.1))
    candidate = now + timedelta(seconds=interval_seconds + jitter)
    if candidate.minute in (0, 30):
        candidate += timedelta(seconds=60 - candidate.second + random.uniform(1, 30))
    if end_at is not None and candidate > end_at:
        return end_at
    return candidate


#: Bytes of JSON ``monitor_state`` may take.
STATE_LIMIT_BYTES = 16384


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def bounded_state(state: Dict[str, Any], *, limit: int = STATE_LIMIT_BYTES) -> Dict[str, Any]:
    """Keep ``monitor_state`` under ``limit`` bytes of JSON by trimming its largest parts first.

    The state is ``{"hash", "excerpt", "check": {..., "seen": [...]}, "recent_wakes": [...]}``:
    the excerpt is cut first, then the oldest seen item ids, then the
    wake history, so what a check needs to stay correct (hash, holds,
    epoch, key, value) is kept to the end.

    Args:
        state: The state to store.
        limit: Most bytes of JSON.

    Returns:
        A copy that fits.
    """
    out = dict(state)
    check = dict(out.get("check") or {})
    if check:
        out["check"] = check
    if _json_size(out) <= limit:
        return out
    steps = (
        ("excerpt", 1000),
        ("seen", 500),
        ("seen", 200),
        ("recent_wakes", 10),
        ("excerpt", 0),
        ("seen", 50),
        ("seen", 0),
    )
    for key, floor in steps:
        holder = check if key == "seen" else out
        value = holder.get(key)
        if isinstance(value, str) and len(value) > floor:
            holder[key] = value[:floor]
        elif isinstance(value, list) and len(value) > floor:
            holder[key] = value[-floor:] if floor else []
        if _json_size(out) <= limit:
            return out
    kept_check = {k: v for k, v in check.items() if k in ("holds", "epoch", "key") and _json_size(v) < 512}
    return {"hash": out.get("hash"), "check": kept_check}


def split_tool_name(name: str) -> Tuple[str, Optional[str]]:
    """``remote_device.run_command`` -> (``remote_device``, ``run_command``); a bare name has no action."""
    if "." in name:
        tool, _, action = name.partition(".")
        return tool.strip(), action.strip() or None
    return name.strip(), None
