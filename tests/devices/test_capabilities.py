"""Parsing ``X-Device-Capabilities``."""

from __future__ import annotations

import pytest

from docsgpt.devices import capabilities


@pytest.mark.parametrize(
    "header,expected",
    [
        ("cancel,outbox", "cancel,outbox"),
        (" OUTBOX , cancel ,cancel", "cancel,outbox"),
        (None, ""),
        ("", ""),
        ("bad token!,ok", "ok"),
        (",".join(f"c{n}" for n in range(40)), ",".join(sorted(f"c{n}" for n in range(40))[:16])),
    ],
)
def test_parse(header, expected):
    assert capabilities.parse(header) == expected


def test_from_headers_is_case_insensitive():
    assert capabilities.from_headers({"x-device-capabilities": "outbox"}) == "outbox"

    class _Plain:
        def items(self):
            return [("X-DEVICE-CAPABILITIES", "cancel")]

    assert capabilities.from_headers(_Plain()) == "cancel"


def test_has():
    assert capabilities.has("cancel,outbox", capabilities.CANCEL)
    assert not capabilities.has("outbox", capabilities.CANCEL)
    assert not capabilities.has(None, capabilities.OUTBOX)
