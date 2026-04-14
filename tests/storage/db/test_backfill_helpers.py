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
    _normalize_mongo_jsonb,
    _normalize_system_user,
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


def test_sentinel_constant():
    assert SYSTEM_USER_ID == "__system__"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
