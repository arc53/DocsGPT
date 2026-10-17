"""Deterministic checks: does this content pass the monitor's check, and is that new?

Pure functions over :class:`Content` and the check's stored state, so the
tick pipeline can run them with no I/O and no LLM.

Two modes:

* ``poll`` (webpage and tool sources) is edge-triggered: a check *fires*
  when it starts to hold (``threshold``: the price drops below 90), or
  holds with something new (``regex``: a new match; ``status``: a new
  terminal status; ``new_items``: unseen ids). A check that keeps holding
  over unchanged facts does not fire again. Each new start of holding opens
  a new ``epoch``, so a price that recovers and drops again wakes again.
* ``event`` (a webhook delivery) judges each delivery on its own: it fires
  whenever the delivery passes.

The baseline (the first check) records state and never fires.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import regex

from docsgpt.monitors.spec import compile_pattern

#: Item ids remembered for ``new_items``.
SEEN_LIMIT = 1000

#: Regex matching gives up after this many seconds (a pathological pattern can't stall a worker).
REGEX_TIMEOUT_SECONDS = 1.0

#: Matches reported for a ``regex`` check.
MAX_MATCHES = 20

#: New items reported in a wake.
MAX_REPORTED_ITEMS = 20

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")


class CheckError(ValueError):
    """The content doesn't fit the check (the path is missing, the value isn't a number)."""


@dataclass
class Content:
    """What a source produced, normalized.

    Attributes:
        text: Text the hash, regex and judge see.
        data: Parsed JSON when the source returned JSON (paths resolve in it).
    """

    text: str
    data: Any = None

    @property
    def digest(self) -> str:
        """sha256 of the normalized text: equal content, equal hash."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass
class Evaluation:
    """The outcome of a check on one piece of content.

    Attributes:
        holds: The check passes for this content.
        fire: Without a condition, this is a wake.
        key: Identifies what fired, for deduplication.
        summary: One line for the wake ("price is 88.0 (< 90.0)").
        detail: Data for the wake's payload (value, matches, new items).
        state: The check's state to store.
    """

    holds: bool
    fire: bool
    key: str
    summary: str
    detail: Dict[str, Any] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)


def _short_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


_MISSING = object()


def resolve_path(data: Any, path: str) -> Any:
    """Read ``a.b[0].c`` (or ``$.a.b``) out of parsed JSON; :data:`_MISSING` when absent.

    Args:
        data: Parsed JSON.
        path: Dotted keys with optional ``[index]``; empty means the root.

    Returns:
        The value, or the module's missing sentinel.
    """
    path = (path or "").strip()
    if path.startswith("$"):
        path = path[1:].lstrip(".")
    if not path:
        return data
    current = data
    for part in re.findall(r"[^.\[\]]+|\[-?\d+\]", path):
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(current, list) or not -len(current) <= index < len(current):
                return _MISSING
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def to_number(value: Any) -> Optional[float]:
    """A number from a JSON value or text such as ``"$52,140.10"``; None when there is none."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER.search(value)
        if match:
            try:
                return float(match.group(0).replace(",", ""))
            except ValueError:
                return None
    return None


def _compare(left: float, op: str, right: float) -> bool:
    return {
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
        "==": left == right,
        "!=": left != right,
    }[op]


def _clip(value: Any, limit: int = 500) -> Any:
    """Bound a value reported in a payload."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return text[:limit] + "…"


def evaluate(
    check: Optional[Dict[str, Any]],
    content: Content,
    state: Optional[Dict[str, Any]],
    *,
    mode: str = "poll",
    baseline: bool = False,
) -> Evaluation:
    """Run ``check`` on ``content`` against the stored state.

    Args:
        check: The monitor's check, or None (any change passes).
        content: The normalized content.
        state: The check state from the last run (``holds``, ``epoch``, ``key``, ``seen``, ``value``).
        mode: ``poll`` (edge-triggered) or ``event`` (each delivery on its own).
        baseline: The first check: record state, never fire.

    Returns:
        The evaluation.

    Raises:
        CheckError: The content doesn't fit the check.
    """
    previous = dict(state or {})
    kind = (check or {}).get("type") or "changed"
    holds, key, summary, detail = _run(kind, check or {}, content, previous)

    new_state: Dict[str, Any] = {
        "holds": holds,
        "key": key,
        "epoch": int(previous.get("epoch") or 0),
    }
    if kind == "new_items":
        new_state["seen"] = detail.pop("_seen")
    if "value" in detail:
        new_state["value"] = detail["value"]

    if mode == "event":
        fire = holds
    else:
        started = holds and not previous.get("holds")
        if started:
            new_state["epoch"] += 1
        fire = holds and (started or key != previous.get("key") or kind in ("changed", "new_items"))
    if baseline:
        fire = False
    return Evaluation(holds=holds, fire=fire, key=f"{new_state['epoch']}:{key}", summary=summary, detail=detail,
                      state=new_state)


def _run(kind: str, check: Dict[str, Any], content: Content, previous: Dict[str, Any]):
    """``(holds, key, summary, detail)`` for one check type."""
    if kind == "changed":
        return True, content.digest[:16], "the content changed", {}
    if kind == "new_items":
        items = resolve_path(content.data, check.get("items_path") or "")
        if items is _MISSING or not isinstance(items, list):
            raise CheckError(f"`{check.get('items_path') or '(root)'}` is not a list in the content.")
        seen: List[str] = [str(i) for i in previous.get("seen") or []]
        seen_set = set(seen)
        new_items, new_ids = [], []
        for item in items:
            item_id = resolve_path(item, check.get("id_field") or "")
            if item_id is _MISSING or item_id is None:
                continue
            item_id = str(item_id)[:200]
            if item_id in seen_set:
                continue
            seen_set.add(item_id)
            new_ids.append(item_id)
            new_items.append(item)
        seen = (seen + new_ids)[-SEEN_LIMIT:]
        detail = {
            "new_items": [_clip(i) for i in new_items[:MAX_REPORTED_ITEMS]],
            "new_count": len(new_items),
            "_seen": seen,
        }
        summary = f"{len(new_items)} new item(s)" if new_items else "no new items"
        return bool(new_items), _short_hash(sorted(new_ids)), summary, detail
    if kind == "regex":
        pattern = compile_pattern(check["pattern"])
        try:
            found = []
            for match in pattern.finditer(content.text, timeout=REGEX_TIMEOUT_SECONDS):
                text = match.group(0)
                if text not in found:
                    found.append(text[:200])
                if len(found) >= MAX_MATCHES:
                    break
        except TimeoutError:
            raise CheckError("the pattern took too long to match; use a simpler `check.pattern`") from None
        except regex.error as exc:
            raise CheckError(f"the pattern failed: {exc}") from None
        if check.get("when") == "no_match":
            holds = not found
            return holds, "absent" if holds else "present", (
                "the pattern no longer matches" if holds else "the pattern still matches"
            ), {"matches": found}
        return bool(found), _short_hash(sorted(found)), (
            f"the pattern matched: {', '.join(found[:3])}" if found else "the pattern did not match"
        ), {"matches": found}
    if kind == "threshold":
        path = check.get("value_path") or ""
        if content.data is not None and path:
            raw = resolve_path(content.data, path)
            if raw is _MISSING:
                raise CheckError(f"`{path}` is not in the content.")
        elif content.data is not None and isinstance(content.data, (int, float, str)):
            raw = content.data
        else:
            raw = content.text
        value = to_number(raw)
        if value is None:
            raise CheckError(f"no number found at `{path or 'the content'}`.")
        holds = _compare(value, check["op"], float(check["value"]))
        label = path or "value"
        return holds, "", f"{label} is {_fmt(value)} ({check['op']} {_fmt(check['value'])}: {holds})", {
            "value": value
        }
    # status
    path = check["value_path"]
    raw = resolve_path(content.data, path) if content.data is not None else _MISSING
    if raw is _MISSING:
        raise CheckError(f"`{path}` is not in the content.")
    status = str(raw).strip().lower()[:200] if raw is not None else ""
    holds = status in (check.get("terminal") or [])
    return holds, status, f"{path} is {status or '(empty)'}" + (" (terminal)" if holds else ""), {
        "value": status
    }


def _fmt(number: Any) -> str:
    value = float(number)
    return str(int(value)) if value.is_integer() else f"{value:g}"
