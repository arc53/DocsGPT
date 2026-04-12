import json
from unittest.mock import MagicMock

import pytest

from application.stt.live_session import (
    apply_live_stt_hypothesis,
    create_live_stt_session,
    delete_live_stt_session,
    finalize_live_stt_session,
    get_live_stt_session_key,
    get_live_stt_transcript_text,
    join_transcript_parts,
    load_live_stt_session,
    normalize_transcript_text,
    save_live_stt_session,
    strip_committed_prefix,
    LIVE_STT_SESSION_PREFIX,
    LIVE_STT_SESSION_TTL_SECONDS,
)


def test_strip_committed_prefix_removes_full_prefix_match():
    assert (
        strip_committed_prefix(
            "hello this is committed",
            "hello this is committed and this stays mutable",
        )
        == "and this stays mutable"
    )


def test_strip_committed_prefix_removes_committed_suffix_overlap():
    assert (
        strip_committed_prefix(
            "one two three four five",
            "four five six seven eight",
        )
        == "six seven eight"
    )


def test_apply_live_stt_hypothesis_keeps_initial_hypothesis_mutable():
    session_state = {
        "session_id": "session-1",
        "user": "test-user",
        "language": "ru",
        "committed_text": "",
        "mutable_text": "",
        "previous_hypothesis": "",
        "latest_hypothesis": "",
        "last_chunk_index": -1,
    }

    apply_live_stt_hypothesis(
        session_state,
        "hello this is a longer test phrase for transcript stabilization",
        0,
    )

    assert session_state["committed_text"] == ""
    assert (
        session_state["mutable_text"]
        == "hello this is a longer test phrase for transcript stabilization"
    )


def test_apply_live_stt_hypothesis_commits_stable_prefix_beyond_mutable_tail():
    session_state = {
        "session_id": "session-1",
        "user": "test-user",
        "language": "ru",
        "committed_text": "",
        "mutable_text": "",
        "previous_hypothesis": "",
        "latest_hypothesis": "",
        "last_chunk_index": -1,
    }

    first_hypothesis = (
        "hello this is a longer test phrase for transcript stabilization today now"
    )
    second_hypothesis = (
        "hello this is a longer test phrase for transcript stabilization today now again later"
    )

    apply_live_stt_hypothesis(session_state, first_hypothesis, 0)
    apply_live_stt_hypothesis(session_state, second_hypothesis, 1)

    assert session_state["committed_text"] == "hello this is a longer test"
    assert (
        session_state["mutable_text"]
        == "phrase for transcript stabilization today now again later"
    )
    assert (
        get_live_stt_transcript_text(session_state)
        == "hello this is a longer test phrase for transcript stabilization today now again later"
    )


def test_apply_live_stt_hypothesis_commits_more_aggressively_on_silence():
    session_state = {
        "session_id": "session-1",
        "user": "test-user",
        "language": "ru",
        "committed_text": "",
        "mutable_text": "",
        "previous_hypothesis": "",
        "latest_hypothesis": "",
        "last_chunk_index": -1,
    }

    hypothesis = "hello this is a longer test phrase for transcript stabilization today now"
    apply_live_stt_hypothesis(session_state, hypothesis, 0)
    apply_live_stt_hypothesis(session_state, hypothesis, 1, is_silence=True)

    assert (
        session_state["committed_text"]
        == "hello this is a longer test phrase for transcript stabilization"
    )
    assert session_state["mutable_text"] == "today now"


def test_finalize_live_stt_session_returns_committed_and_mutable_text():
    session_state = {
        "session_id": "session-1",
        "user": "test-user",
        "language": "ru",
        "committed_text": "hello this is",
        "mutable_text": "a live transcript",
        "previous_hypothesis": "a live transcript",
        "latest_hypothesis": "a live transcript",
        "last_chunk_index": 1,
    }

    assert finalize_live_stt_session(session_state) == "hello this is a live transcript"


def test_apply_live_stt_hypothesis_rejects_older_chunks():
    session_state = {
        "session_id": "session-1",
        "user": "test-user",
        "language": "ru",
        "committed_text": "",
        "mutable_text": "hello there",
        "previous_hypothesis": "hello there",
        "latest_hypothesis": "hello there",
        "last_chunk_index": 1,
    }

    try:
        apply_live_stt_hypothesis(session_state, "hello there again", 0)
    except ValueError as exc:
        assert "older" in str(exc)
    else:
        raise AssertionError("Expected older chunk to raise ValueError")


# ── normalize_transcript_text ───────────────────────────────────────────────


def test_normalize_transcript_text_strips_and_collapses_whitespace():
    assert normalize_transcript_text("  hello   world  ") == "hello world"


def test_normalize_transcript_text_empty():
    assert normalize_transcript_text("") == ""


def test_normalize_transcript_text_none():
    assert normalize_transcript_text(None) == ""


def test_normalize_transcript_text_tabs_and_newlines():
    assert normalize_transcript_text("hello\t\nworld") == "hello world"


# ── join_transcript_parts ───────────────────────────────────────────────────


def test_join_transcript_parts_multiple():
    assert join_transcript_parts("hello", "world") == "hello world"


def test_join_transcript_parts_empty_parts():
    assert join_transcript_parts("hello", "", "world") == "hello world"


def test_join_transcript_parts_all_empty():
    assert join_transcript_parts("", "", "") == ""


def test_join_transcript_parts_single():
    assert join_transcript_parts("hello") == "hello"


def test_join_transcript_parts_whitespace_only():
    assert join_transcript_parts("   ", "  hello  ") == "hello"


# ── create_live_stt_session ─────────────────────────────────────────────────


def test_create_live_stt_session_basic():
    session = create_live_stt_session("user1", language="en")
    assert session["user"] == "user1"
    assert session["language"] == "en"
    assert session["committed_text"] == ""
    assert session["mutable_text"] == ""
    assert session["previous_hypothesis"] == ""
    assert session["latest_hypothesis"] == ""
    assert session["last_chunk_index"] == -1
    assert "session_id" in session
    assert len(session["session_id"]) == 36  # UUID format


def test_create_live_stt_session_no_language():
    session = create_live_stt_session("user1")
    assert session["language"] is None


# ── get_live_stt_session_key ────────────────────────────────────────────────


def test_get_live_stt_session_key():
    key = get_live_stt_session_key("abc-123")
    assert key == f"{LIVE_STT_SESSION_PREFIX}abc-123"


# ── save_live_stt_session ──────────────────────────────────────────────────


def test_save_live_stt_session():
    mock_redis = MagicMock()
    session_state = {
        "session_id": "test-session-id",
        "user": "user1",
        "committed_text": "hello",
        "mutable_text": "world",
    }

    save_live_stt_session(mock_redis, session_state)

    expected_key = f"{LIVE_STT_SESSION_PREFIX}test-session-id"
    mock_redis.setex.assert_called_once_with(
        expected_key,
        LIVE_STT_SESSION_TTL_SECONDS,
        json.dumps(session_state),
    )


# ── load_live_stt_session ──────────────────────────────────────────────────


def test_load_live_stt_session_found():
    mock_redis = MagicMock()
    session_data = {"session_id": "test-id", "committed_text": "hello"}
    mock_redis.get.return_value = json.dumps(session_data).encode("utf-8")

    result = load_live_stt_session(mock_redis, "test-id")

    assert result == session_data


def test_load_live_stt_session_not_found():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    result = load_live_stt_session(mock_redis, "nonexistent")

    assert result is None


def test_load_live_stt_session_string_response():
    mock_redis = MagicMock()
    session_data = {"session_id": "test-id"}
    # Some redis clients return strings instead of bytes
    mock_redis.get.return_value = json.dumps(session_data)

    result = load_live_stt_session(mock_redis, "test-id")

    assert result == session_data


# ── delete_live_stt_session ─────────────────────────────────────────────────


def test_delete_live_stt_session():
    mock_redis = MagicMock()

    delete_live_stt_session(mock_redis, "test-id")

    expected_key = f"{LIVE_STT_SESSION_PREFIX}test-id"
    mock_redis.delete.assert_called_once_with(expected_key)


# ── strip_committed_prefix edge cases ──────────────────────────────────────


def test_strip_committed_prefix_empty_committed():
    result = strip_committed_prefix("", "hello world")
    assert result == "hello world"


def test_strip_committed_prefix_empty_hypothesis():
    result = strip_committed_prefix("hello", "")
    assert result == ""


def test_strip_committed_prefix_both_empty():
    result = strip_committed_prefix("", "")
    assert result == ""


def test_strip_committed_prefix_no_overlap():
    result = strip_committed_prefix(
        "completely different text",
        "no overlap here at all",
    )
    assert result == "no overlap here at all"


# ── apply_live_stt_hypothesis edge cases ───────────────────────────────────


def test_apply_live_stt_hypothesis_negative_chunk_index():
    session_state = create_live_stt_session("user1")

    with pytest.raises(ValueError, match="non-negative"):
        apply_live_stt_hypothesis(session_state, "hello", -1)


def test_apply_live_stt_hypothesis_same_chunk_index_is_noop():
    session_state = create_live_stt_session("user1")
    session_state["last_chunk_index"] = 5

    original_state = dict(session_state)
    result = apply_live_stt_hypothesis(session_state, "hello", 5)

    assert result["last_chunk_index"] == 5
    assert result["committed_text"] == original_state["committed_text"]


def test_apply_live_stt_hypothesis_silence_commits_all_previous():
    session_state = create_live_stt_session("user1")
    session_state["last_chunk_index"] = 0
    session_state["latest_hypothesis"] = "previous words here"

    apply_live_stt_hypothesis(session_state, "", 1, is_silence=True)

    # Silence with empty current hypothesis should commit previous
    assert "previous words here" in session_state["committed_text"]


# ── get_live_stt_transcript_text ────────────────────────────────────────────


def test_get_live_stt_transcript_text_both_parts():
    state = {"committed_text": "hello", "mutable_text": "world"}
    assert get_live_stt_transcript_text(state) == "hello world"


def test_get_live_stt_transcript_text_committed_only():
    state = {"committed_text": "hello", "mutable_text": ""}
    assert get_live_stt_transcript_text(state) == "hello"


def test_get_live_stt_transcript_text_mutable_only():
    state = {"committed_text": "", "mutable_text": "world"}
    assert get_live_stt_transcript_text(state) == "world"


def test_get_live_stt_transcript_text_empty():
    state = {"committed_text": "", "mutable_text": ""}
    assert get_live_stt_transcript_text(state) == ""


# ── finalize_live_stt_session edge cases ────────────────────────────────────


def test_finalize_live_stt_session_empty():
    state = {
        "committed_text": "",
        "latest_hypothesis": "",
    }
    assert finalize_live_stt_session(state) == ""


def test_finalize_live_stt_session_committed_only():
    state = {
        "committed_text": "all committed",
        "latest_hypothesis": "",
    }
    assert finalize_live_stt_session(state) == "all committed"
