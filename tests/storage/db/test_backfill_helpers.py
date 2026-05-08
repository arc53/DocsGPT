"""Unit tests for pure helpers in ``scripts/db/backfill.py``.

These helpers are side-effect-free so they run without a live Postgres.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the backfill module importable (scripts/ isn't on sys.path by default).
sys.path.insert(
    0, str(Path(__file__).resolve().parents[3])
)

from scripts.db.backfill import (  # noqa: E402
    SYSTEM_USER_ID,
    _is_uuid_str,
    _normalize_mongo_jsonb,
    _normalize_system_user,
    _resolve_tool_id,
)


def _decode(value):
    """``_normalize_mongo_jsonb`` returns a JSON string ready for
    ``CAST(:x AS jsonb)`` (or ``None``). Decode for assertion convenience."""
    if value is None:
        return None
    return json.loads(value)


class TestNormalizeMongoJsonb:
    def test_none_passes_through(self):
        assert _normalize_mongo_jsonb(None) is None

    def test_dict_passes_through(self):
        value = {"provider": "google_drive", "folder_id": "abc"}
        assert _decode(_normalize_mongo_jsonb(value)) == value

    def test_list_passes_through(self):
        value = [{"url": "x"}, {"url": "y"}]
        assert _decode(_normalize_mongo_jsonb(value)) == value

    def test_https_url_wraps_as_crawler(self):
        out = _decode(_normalize_mongo_jsonb("https://docs.docsgpt.cloud/"))
        assert out == {
            "provider": "crawler",
            "url": "https://docs.docsgpt.cloud/",
        }

    def test_http_url_wraps_as_crawler(self):
        out = _decode(_normalize_mongo_jsonb("http://example.com/path"))
        assert out == {"provider": "crawler", "url": "http://example.com/path"}

    def test_non_url_string_wraps_as_raw(self):
        # Non-JSON, non-URL string falls into the lossless ``{"raw": ...}``
        # bucket so the original bytes can be recovered downstream.
        out = _decode(_normalize_mongo_jsonb("some plain string"))
        assert out == {"raw": "some plain string"}

    def test_empty_string_returns_none(self):
        # Empty / whitespace-only strings are coerced to NULL so the PG
        # column accepts them without inserting a useless ``""`` blob.
        assert _normalize_mongo_jsonb("") is None

    def test_json_string_round_trips(self):
        out = _decode(_normalize_mongo_jsonb('{"provider": "github"}'))
        assert out == {"provider": "github"}


class TestNormalizeSystemUser:
    def test_none_becomes_sentinel(self):
        assert _normalize_system_user(None) == SYSTEM_USER_ID

    def test_empty_string_becomes_sentinel(self):
        assert _normalize_system_user("") == SYSTEM_USER_ID

    def test_legacy_system_string_becomes_sentinel(self):
        assert _normalize_system_user("system") == SYSTEM_USER_ID

    def test_real_user_passed_through(self):
        assert _normalize_system_user("user-abc-123") == "user-abc-123"

    def test_sentinel_passed_through(self):
        assert _normalize_system_user(SYSTEM_USER_ID) == SYSTEM_USER_ID

    def test_non_string_coerced(self):
        assert _normalize_system_user(42) == "42"


class TestIsUuidStr:
    """``_is_uuid_str`` gates raw ``CAST(:x AS uuid)`` inside backfill
    batches. A weak shape check that accepts non-hex or wrong-segmented
    input would crash the whole batch in Postgres, so this helper must
    be strict."""

    def test_canonical_uuid_accepted(self):
        assert _is_uuid_str("123e4567-e89b-12d3-a456-426614174000") is True

    def test_uppercase_hex_accepted(self):
        assert _is_uuid_str("123E4567-E89B-12D3-A456-426614174000") is True

    def test_too_short_rejected(self):
        assert _is_uuid_str("123e4567-e89b-12d3-a456-4266141740") is False

    def test_too_long_rejected(self):
        assert _is_uuid_str("123e4567-e89b-12d3-a456-4266141740000") is False

    def test_non_hex_char_rejected(self):
        # Correct length and hyphen count, but 'z' is not hex — old dash-only
        # check would accept this and poison the CAST batch.
        assert _is_uuid_str("z23e4567-e89b-12d3-a456-426614174000") is False

    def test_wrong_hyphen_positions_rejected(self):
        # 36 chars, 4 hyphens, but segments are 12-4-4-4-8 instead of 8-4-4-4-12.
        assert _is_uuid_str("123e4567e89b1-2d3-a456-42661-4174000") is False

    def test_object_id_rejected(self):
        assert _is_uuid_str("507f1f77bcf86cd799439011") is False

    def test_non_string_rejected(self):
        assert _is_uuid_str(None) is False
        assert _is_uuid_str(42) is False


class TestResolveToolId:
    """``_resolve_tool_id`` must not pass through malformed UUID-shaped
    strings — they'll reach ``CAST(:tool_id AS uuid)`` inside the memory /
    todo / pending_tool_state backfill batches and raise."""

    def test_pg_uuid_passes_through(self):
        uuid_in = "123e4567-e89b-12d3-a456-426614174000"
        assert _resolve_tool_id(uuid_in, {}) == uuid_in

    def test_mongo_objectid_resolves_via_map(self):
        mapping = {"507f1f77bcf86cd799439011": "123e4567-e89b-12d3-a456-426614174000"}
        assert _resolve_tool_id("507f1f77bcf86cd799439011", mapping) == (
            "123e4567-e89b-12d3-a456-426614174000"
        )

    def test_unmapped_objectid_returns_none(self):
        assert _resolve_tool_id("507f1f77bcf86cd799439011", {}) is None

    def test_malformed_uuid_shape_rejected(self):
        # 36 chars with dashes, but non-hex content — would crash CAST.
        assert _resolve_tool_id("zzzz4567-e89b-12d3-a456-426614174000", {}) is None

    def test_none_input_returns_none(self):
        assert _resolve_tool_id(None, {}) is None


def test_sentinel_constant():
    assert SYSTEM_USER_ID == "__system__"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
