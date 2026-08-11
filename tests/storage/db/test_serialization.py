"""Tests for the shared PG-native JSON coercion utility."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from application.storage.db.serialization import (
    PGNativeJSONEncoder,
    coerce_pg_native,
    decode_base64_bytes,
)


class TestCoercePgNative:
    def test_uuid(self):
        u = UUID("12345678-1234-5678-1234-567812345678")
        assert coerce_pg_native(u) == "12345678-1234-5678-1234-567812345678"

    def test_datetime_with_tz(self):
        ts = datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc)
        assert coerce_pg_native(ts) == "2026-05-02T12:14:32+00:00"

    def test_datetime_naive(self):
        ts = datetime(2026, 5, 2, 12, 14, 32)
        assert coerce_pg_native(ts) == "2026-05-02T12:14:32"

    def test_date(self):
        assert coerce_pg_native(date(2026, 5, 2)) == "2026-05-02"

    def test_decimal_preserves_precision(self):
        assert coerce_pg_native(Decimal("123.45000")) == "123.45000"

    def test_bytes_base64_roundtrip(self):
        b = b"\x00\x01\xff\x10gemini-binary"
        coerced = coerce_pg_native(b)
        assert isinstance(coerced, str)
        assert decode_base64_bytes(coerced) == b

    def test_dict_recurses_and_stringifies_keys(self):
        u = uuid4()
        got = coerce_pg_native({42: u, "n": [u, u]})
        assert got == {"42": str(u), "n": [str(u), str(u)]}

    def test_list_recurses(self):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        got = coerce_pg_native([1, ts, {"a": ts}])
        assert got == [1, "2026-01-01T00:00:00+00:00", {"a": "2026-01-01T00:00:00+00:00"}]

    def test_tuple_becomes_list(self):
        # Tuples have no JSON representation; the prior helper recursed
        # only into list — verify we now flatten tuples to lists too.
        u = uuid4()
        got = coerce_pg_native(("x", u))
        assert got == ["x", str(u)]
        assert isinstance(got, list)

    def test_passes_through_primitives(self):
        assert coerce_pg_native("hello") == "hello"
        assert coerce_pg_native(42) == 42
        assert coerce_pg_native(3.14) == 3.14
        assert coerce_pg_native(None) is None
        assert coerce_pg_native(True) is True

    def test_idempotent_for_already_safe_dict(self):
        d = {"a": 1, "b": [2, "x"], "c": None}
        assert coerce_pg_native(d) == d

    def test_pg_row_dict_real_shape(self):
        # Mirror the actual user_tools row dict shape that broke the
        # continuation save: timestamp + UUID + nested actions.
        row = {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "name": "mcp_tool",
            "status": True,
            "actions": [{"name": "search", "active": True}],
            "created_at": datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc),
        }
        coerced = coerce_pg_native(row)
        json.dumps(coerced)  # would raise on raw datetime/UUID
        assert coerced["id"] == "11111111-1111-1111-1111-111111111111"
        assert coerced["created_at"] == "2026-05-02T12:14:32+00:00"


class TestPGNativeJSONEncoder:
    def test_uuid(self):
        u = uuid4()
        assert json.loads(json.dumps(u, cls=PGNativeJSONEncoder)) == str(u)

    def test_datetime(self):
        ts = datetime(2026, 5, 2, 12, 14, 32, tzinfo=timezone.utc)
        assert json.loads(json.dumps(ts, cls=PGNativeJSONEncoder)) == ts.isoformat()

    def test_date(self):
        d = date(2026, 5, 2)
        assert json.loads(json.dumps(d, cls=PGNativeJSONEncoder)) == "2026-05-02"

    def test_decimal(self):
        assert json.loads(json.dumps(Decimal("99.99"), cls=PGNativeJSONEncoder)) == "99.99"

    def test_bytes(self):
        b = b"\x00\xff"
        encoded = json.loads(json.dumps(b, cls=PGNativeJSONEncoder))
        assert decode_base64_bytes(encoded) == b

    def test_nested_pg_row(self):
        row = {
            "id": UUID("22222222-2222-2222-2222-222222222222"),
            "amount": Decimal("42.00"),
            "scheduled_for": date(2026, 6, 1),
            "data": [{"created_at": datetime(2026, 5, 2, tzinfo=timezone.utc)}],
        }
        decoded = json.loads(json.dumps(row, cls=PGNativeJSONEncoder))
        assert decoded["id"] == "22222222-2222-2222-2222-222222222222"
        assert decoded["amount"] == "42.00"
        assert decoded["scheduled_for"] == "2026-06-01"
        assert decoded["data"][0]["created_at"] == "2026-05-02T00:00:00+00:00"

    def test_unsupported_type_still_raises(self):
        # Encoder must not silently swallow types it doesn't know how to
        # handle — raising is how callers learn about gaps.
        class Weird:
            pass

        with pytest.raises(TypeError):
            json.dumps(Weird(), cls=PGNativeJSONEncoder)


class TestDecodeBase64Bytes:
    def test_roundtrip(self):
        b = b"\x00\x10\x20\xff"
        from application.storage.db.serialization import _coerce_scalar
        encoded = _coerce_scalar(b)
        assert decode_base64_bytes(encoded) == b

    def test_passes_through_bytes_unchanged(self):
        assert decode_base64_bytes(b"raw") == b"raw"

    def test_passes_through_none(self):
        assert decode_base64_bytes(None) is None

    def test_invalid_base64_falls_back_to_input(self):
        assert decode_base64_bytes("not!valid!b64!") == "not!valid!b64!"
