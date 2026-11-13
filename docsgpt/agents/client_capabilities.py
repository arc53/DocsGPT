"""What a chat client says it can render: the request's ``capabilities``.

A client lists what it can draw, and the server maps each value to the
internal tools a turn may use. Nothing is enforced: a client that sends
nothing gets every turn as before any of these existed, and an unknown value
is ignored, so an older server takes a newer client's list as it is.

* ``forms``: the client draws clarifying-question forms and resumes the turn
  with the answer, so a chat turn gets ``ask_user`` (as question cards).

A new value (``mermaid``, say) is added to :data:`KNOWN_CAPABILITIES` here
and read where the turn's tools are chosen.
"""

from __future__ import annotations

from typing import Any, FrozenSet

#: The client draws clarifying questions as forms (``ask_user``).
FORMS = "forms"

#: Every value the server reads; the rest are dropped.
KNOWN_CAPABILITIES: FrozenSet[str] = frozenset({FORMS})

#: Entries of the list read; a longer list is read only this far.
MAX_CAPABILITIES = 16


def parse_capabilities(value: Any) -> FrozenSet[str]:
    """The known capabilities in a request's ``capabilities`` value.

    Args:
        value: The request's field: a list of strings. Anything else (a
            single string, an object, a number) lists nothing.

    Returns:
        The known values, matched exactly; empty when none are.
    """
    if not isinstance(value, (list, tuple)):
        return frozenset()
    return frozenset(
        item for item in value[:MAX_CAPABILITIES] if isinstance(item, str) and item in KNOWN_CAPABILITIES
    )
