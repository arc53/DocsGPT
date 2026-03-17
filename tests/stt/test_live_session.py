from application.stt.live_session import (
    apply_live_stt_hypothesis,
    finalize_live_stt_session,
    get_live_stt_transcript_text,
    strip_committed_prefix,
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
