"""Canonical signed-payload tests.

The string here MUST match the DocsGPT-cli signer byte-for-byte (see
``internal/host/identity.go`` ``CanonicalPayload`` and the Go test
``TestCanonicalPayloadExactString``). If you change the format, change both
repos together.
"""

from __future__ import annotations

from application.api.devices.auth import _canonical_payload


def test_canonical_payload_empty_body():
    # sha256("") = e3b0c442...b855
    got = _canonical_payload("GET", "/api/devices/poll", "1700000000", b"")
    assert got == (
        "GET /api/devices/poll 1700000000 "
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_canonical_payload_none_body_equals_empty():
    # The verifier passes request.get_data(); guard against a None slipping in.
    assert _canonical_payload("GET", "/x", "1", None) == _canonical_payload(
        "GET", "/x", "1", b""
    )


def test_canonical_payload_with_body_matches_cli():
    # sha256("hello") = 2cf24dba...9824 — identical to the Go test constant.
    got = _canonical_payload("POST", "/api/devices/x", "1700000000", b"hello")
    assert got == (
        "POST /api/devices/x 1700000000 "
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_canonical_payload_body_changes_hash():
    a = _canonical_payload("POST", "/x", "1", b'{"decision":"accept"}')
    b = _canonical_payload("POST", "/x", "1", b'{"decision":"deny"}')
    assert a != b
