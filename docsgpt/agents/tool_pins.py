"""Fixed ("pinned") tool parameters.

Every parameter of a stored tool action carries ``filled_by_llm`` and
``value``. A parameter with ``filled_by_llm`` false is hidden from the model;
when it also has a value, that value is *pinned*: it is sent on every call and
the model can neither see nor override it. An empty string means "no value":
the parameter is left out of the call (optional OpenAPI parameters are stored
that way), while ``0`` and ``false`` are real values.

The run-time rules live in :func:`resolve_arguments`; the helpers below
validate and apply pin changes coming from the API.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping, Optional

#: The places an action keeps parameter schemas: ``parameters`` for ordinary
#: tools and MCP, the other three for ``api_tool`` requests.
PARAM_SECTIONS = ("query_params", "headers", "body", "parameters")

_NUMERIC = {"integer": int, "number": float}


def _properties(action: Mapping, section: str) -> dict:
    block = action.get(section)
    if not isinstance(block, dict):
        return {}
    properties = block.get("properties")
    return properties if isinstance(properties, dict) else {}


def iter_parameters(action: Mapping) -> Iterable[tuple[str, str, dict]]:
    """``(section, name, details)`` for every parameter schema of ``action``."""
    for section in PARAM_SECTIONS:
        for name, details in _properties(action, section).items():
            if isinstance(details, dict):
                yield section, name, details


def llm_fills(details: Mapping) -> bool:
    """Whether the model fills this parameter (the default when unset)."""
    return bool(details.get("filled_by_llm", True))


def has_value(details: Mapping) -> bool:
    """Whether a parameter carries a value: anything but a missing, None or empty string."""
    value = details.get("value")
    return value is not None and value != ""


def is_pinned(details: Mapping) -> bool:
    """Whether the parameter is hidden from the model and always sent with its value."""
    return not llm_fills(details) and has_value(details)


def pinned_names(action: Mapping) -> list[str]:
    """Names of the parameters of ``action`` that carry a pinned value."""
    return [name for _section, name, details in iter_parameters(action) if is_pinned(details)]


def resolve_arguments(
    action: Mapping,
    llm_arguments: Mapping[str, Any],
    connection_pins: Optional[Mapping[str, Any]] = None,
) -> dict[str, dict]:
    """The arguments a call runs with, per parameter section.

    Only parameters the action declares are passed. For each one:

    * a value the connection fixes (``connection_pins``, e.g. Telegram's
      default chat) always wins;
    * a parameter hidden from the model takes its stored value, or is left
      out when it has none; whatever the model sent for it is ignored, so a
      model that names the key anyway (a mistake, or a prompt injection)
      changes nothing;
    * any other parameter takes the model's value, falling back to its
      stored default.

    Args:
        action: The stored action (``parameters`` / ``query_params`` /
            ``headers`` / ``body`` schemas with ``filled_by_llm`` and ``value``).
        llm_arguments: The arguments the model sent.
        connection_pins: Parameter name to a value the connection fixes.

    Returns:
        Section name to ``{parameter: value}`` for every section in
        :data:`PARAM_SECTIONS` (empty dicts included).
    """
    connection_pins = connection_pins or {}
    resolved: dict[str, dict] = {section: {} for section in PARAM_SECTIONS}
    for section, name, details in iter_parameters(action):
        target = resolved[section]
        if name in connection_pins:
            target[name] = connection_pins[name]
        elif not llm_fills(details):
            if has_value(details):
                target[name] = details["value"]
        elif name in llm_arguments:
            target[name] = llm_arguments[name]
        elif has_value(details):
            target[name] = details["value"]
    return resolved


#: What the chat shows in place of a value the owner fixed.
FIXED_MASK = "(fixed)"


def sent_arguments(
    action: Mapping,
    llm_arguments: Mapping[str, Any],
    connection_pins: Optional[Mapping[str, Any]] = None,
) -> dict:
    """What a call sends, flattened for the chat (the approval card, a finished call).

    It follows :func:`resolve_arguments`, but a value the owner fixed shows
    as :data:`FIXED_MASK`: it may be a secret (an API key in a query), and
    the chat is shown to whoever runs the agent, over the API or a widget
    too. A value the connection sets (Telegram's default chat) is the
    account's own setting and shows as it is. Headers are left out.
    """
    connection_pins = connection_pins or {}
    shown: dict = {}
    for section, name, details in iter_parameters(action):
        if section == "headers":
            continue
        if name in connection_pins:
            shown[name] = connection_pins[name]
        elif not llm_fills(details):
            if has_value(details):
                shown[name] = FIXED_MASK
        elif name in llm_arguments:
            shown[name] = llm_arguments[name]
        elif has_value(details):
            shown[name] = details["value"]
    return shown


def coerce_value(details: Mapping, value: Any) -> Any:
    """Check a value for a pin against the parameter's declared type.

    Strings typed into a form are converted for ``integer``, ``number`` and
    ``boolean`` parameters.

    Raises:
        ValueError: The value does not fit the type, or is empty.
    """
    if value is None or value == "":
        raise ValueError("A fixed value cannot be empty")
    kind = details.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind in _NUMERIC:
        if isinstance(value, bool):
            raise ValueError(f"Expected a {kind}")
        try:
            number = _NUMERIC[kind](value)
        except (TypeError, ValueError):
            raise ValueError(f"Expected a {kind}") from None
        if kind == "integer" and isinstance(value, float) and not value.is_integer():
            raise ValueError("Expected an integer")
        return number
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError("Expected true or false")
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError("Expected a list")
        return value
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        return value
    if kind in (None, "string"):
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError("Expected text")
        return str(value) if kind == "string" else value
    return value


def set_pins(action: Mapping, pins: Mapping[str, Any]) -> dict:
    """Return ``action`` with ``pins`` applied.

    Args:
        action: A stored action.
        pins: Parameter name to the value to always use, or None to let the
            model decide again.

    Raises:
        ValueError: A parameter does not exist on the action, or a value does
            not fit its type.
    """
    updated = copy.deepcopy(dict(action))
    known = {name: details for _section, name, details in iter_parameters(updated)}
    for name, value in pins.items():
        details = known.get(name)
        if details is None:
            raise ValueError(f"Unknown parameter: {name}")
        if value is None:
            details["filled_by_llm"] = True
            details["value"] = ""
        else:
            details["value"] = coerce_value(details, value)
            details["filled_by_llm"] = False
    return updated


class PinChangeRefused(PermissionError):
    """Someone other than the tool's owner tried to change a fixed value."""


_ACTION_KEYS = ("active", "require_approval", "description")
_PARAM_KEYS = ("filled_by_llm", "value", "description")


def _pin_state(details: Mapping) -> tuple:
    return (llm_fills(details), details.get("value") if has_value(details) else None)


def merge_submitted_actions(stored: list, submitted: Any, *, may_change_pins: bool) -> list:
    """Validate a full list of actions sent by a client against the stored ones.

    The stored actions are the schema: a client can switch actions on and off,
    change approval and descriptions and (the owner only) fixed values, but
    cannot add actions or parameters, or change a parameter's type.

    Args:
        stored: The tool's stored actions.
        submitted: What the client sent (untrusted).
        may_change_pins: False for a team editor: any change to
            ``filled_by_llm`` or ``value`` is refused.

    Returns:
        The actions to store: every stored action, updated from the
        submission.

    Raises:
        ValueError: The submission is malformed or names an unknown action or
            parameter, or a fixed value does not fit its parameter.
        PinChangeRefused: ``may_change_pins`` is False and a fixed value changed.
    """
    if not isinstance(submitted, list):
        raise ValueError("actions must be a list")
    by_name = {a.get("name"): a for a in stored if isinstance(a, dict) and a.get("name")}
    seen: set = set()
    updates: dict[str, dict] = {}
    for entry in submitted:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError("Each action needs a name")
        name = entry["name"]
        if name not in by_name:
            raise ValueError(f"Unknown action: {name}")
        if name in seen:
            raise ValueError(f"Duplicate action: {name}")
        seen.add(name)
        updates[name] = entry

    merged = []
    for action in stored:
        if not isinstance(action, dict) or action.get("name") not in updates:
            merged.append(action)
            continue
        entry = updates[action["name"]]
        result = copy.deepcopy(action)
        for key in _ACTION_KEYS:
            if key in entry:
                value = entry[key]
                if key == "description" and not isinstance(value, str):
                    raise ValueError("description must be text")
                result[key] = bool(value) if key != "description" else value
        for section in PARAM_SECTIONS:
            sent = _properties(entry, section)
            if not sent:
                continue
            properties = _properties(result, section)
            for param, sent_details in sent.items():
                details = properties.get(param)
                if details is None or not isinstance(details, dict):
                    raise ValueError(f"Unknown parameter {param} on {action['name']}")
                if not isinstance(sent_details, dict):
                    raise ValueError(f"Parameter {param} must be an object")
                before = _pin_state(details)
                for key in _PARAM_KEYS:
                    if key in sent_details:
                        details[key] = sent_details[key]
                details["filled_by_llm"] = llm_fills(details)
                if _pin_state(details) == before:
                    continue
                if not may_change_pins:
                    raise PinChangeRefused("Only the tool's owner can change fixed values")
                if is_pinned(details):
                    details["value"] = coerce_value(details, details["value"])
        merged.append(result)
    return merged


def carry_pins_between(previous: Optional[list], fresh: list) -> list:
    """:func:`carry_pins` for whole action lists, matching actions by name."""
    old = {a.get("name"): a for a in previous or [] if isinstance(a, dict)}
    return [carry_pins(old.get(a.get("name")), a) if isinstance(a, dict) else a for a in fresh]


def carry_pins(previous: Optional[Mapping], fresh: Mapping) -> dict:
    """Copy fixed values from an action's old copy onto its re-discovered one.

    Parameters that still exist keep ``filled_by_llm`` and ``value``; removed
    ones are gone with the new schema.
    """
    result = copy.deepcopy(dict(fresh))
    if not previous:
        return result
    old = {(section, name): details for section, name, details in iter_parameters(previous)}
    for section, name, details in iter_parameters(result):
        before = old.get((section, name))
        if before is None:
            continue
        details["filled_by_llm"] = llm_fills(before)
        details["value"] = before.get("value", "")
    return result
