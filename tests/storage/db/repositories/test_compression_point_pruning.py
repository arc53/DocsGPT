"""Compression points must not outlive the messages they summarize."""

from __future__ import annotations

from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def _conversation(conn, turns: int) -> tuple[ConversationsRepository, str]:
    repo = ConversationsRepository(conn)
    conv_id = str(repo.create("u", "points")["id"])
    for i in range(turns):
        repo.append_message(conv_id, {"prompt": f"q{i}", "response": f"a{i}"})
    return repo, conv_id


def _point(query_index: int, summary: str, turn_index: int | None = None) -> dict:
    point = {"query_index": query_index, "compressed_summary": summary, "compressed_token_count": 3}
    if turn_index is not None:
        point["turn_index"] = turn_index
    return point


def _points(repo, conv_id: str) -> list:
    return (repo.get_any(conv_id, "u").get("compression_metadata") or {}).get("compression_points") or []


def _metadata(repo, conv_id: str) -> dict:
    return repo.get_any(conv_id, "u").get("compression_metadata") or {}


def _store(repo, conv_id: str, *points: dict) -> None:
    repo.set_compression_flags(conv_id, is_compressed=True, last_compression_at=None)
    for point in points:
        repo.append_compression_point(conv_id, point, max_points=5)


class TestTruncatePrunesPoints:
    def test_edit_drops_points_past_the_cut_and_keeps_earlier_ones(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 5)
        _store(repo, conv_id, _point(1, "s1"), _point(3, "s3"))

        # The user edits the turn at position 2.
        repo.truncate_after(conv_id, keep_up_to=1)

        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["s1"]
        assert _metadata(repo, conv_id)["is_compressed"] is True

    def test_mid_turn_point_goes_with_the_turn_whose_tool_work_it_holds(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 3)
        # Made while turn 2 ran: covers rows 0-1 and turn 2's tool work.
        _store(repo, conv_id, _point(0, "pre"), _point(1, "mid", turn_index=2))

        repo.truncate_after(conv_id, keep_up_to=1)

        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["pre"]

    def test_last_point_removed_clears_the_compressed_flag(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 2)
        _store(repo, conv_id, _point(-1, "first turn", turn_index=0))

        repo.truncate_after(conv_id, keep_up_to=-1)

        assert _points(repo, conv_id) == []
        assert _metadata(repo, conv_id)["is_compressed"] is False

    def test_retry_of_the_next_turn_keeps_a_point_that_covers_only_earlier_rows(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 4)
        _store(repo, conv_id, _point(2, "s2"))

        repo.truncate_after(conv_id, keep_up_to=2)

        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["s2"]

    def test_no_metadata_is_left_alone(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 2)

        assert repo.truncate_after(conv_id, keep_up_to=0) == 1
        assert repo.prune_compression_points(conv_id, keep_up_to=0) == 0
        assert _metadata(repo, conv_id) == {}


class TestSearchSkipsStoredSummaryRows:
    def test_summary_rows_do_not_match(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        repo.append_message(
            conv_id,
            {
                "prompt": "[Context Compression Summary]",
                "response": "zebra crossing summary",
                "metadata": {"compression_summary": True},
            },
        )
        legacy_id = str(repo.create("u", "legacy")["id"])
        repo.append_message(
            legacy_id,
            {"prompt": "[Context Compression Summary]", "response": "zebra legacy summary"},
        )

        assert repo.search_for_user("u", "zebra") == []
        assert repo.search_for_user("u", "Context Compression") == []

    def test_real_messages_still_match(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        repo.append_message(conv_id, {"prompt": "where is the zebra", "response": "a zebra answer"})

        assert [str(c["id"]) for c in repo.search_for_user("u", "zebra")] == [conv_id]


class TestMidTurnPointNeedsItsTurn:
    def test_point_is_stored_while_its_turn_row_exists(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        row = repo.reserve_message(conv_id, prompt="q1", placeholder_response="", status="streaming")
        point = {**_point(0, "mid", turn_index=1), "turn_message_id": str(row["id"])}

        assert repo.append_compression_point(conv_id, point, max_points=3) is True
        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["mid"]

    def test_point_of_a_replaced_turn_is_not_stored(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        row = repo.reserve_message(conv_id, prompt="q1", placeholder_response="", status="streaming")
        # The user edits the turn while its stream is still compressing.
        repo.truncate_after(conv_id, keep_up_to=0)
        point = {**_point(0, "late", turn_index=1), "turn_message_id": str(row["id"])}

        assert repo.append_compression_point(conv_id, point, max_points=3) is False
        assert _points(repo, conv_id) == []

    def test_point_of_a_turn_rewritten_in_place_is_not_stored(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        row = repo.reserve_message(conv_id, prompt="q1", placeholder_response="", status="streaming")
        # A retry without a reservation rewrites the row and keeps its id.
        repo.update_message_at(conv_id, 1, {"prompt": "q1 again", "response": "a", "status": "complete"})
        point = {**_point(0, "late", turn_index=1), "turn_message_id": str(row["id"])}

        assert repo.append_compression_point(conv_id, point, max_points=3) is False

    def test_deleting_an_unanswered_turn_drops_its_point(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 2)
        row = repo.reserve_message(conv_id, prompt="wake", placeholder_response="", status="streaming")
        _store(
            repo, conv_id,
            _point(0, "pre"),
            {**_point(1, "mid", turn_index=2), "turn_message_id": str(row["id"])},
        )

        assert repo.delete_in_flight_message(str(row["id"])) is True
        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["pre"]


class TestPruningCountsRowsNotPositions:
    def test_a_deleted_middle_row_does_not_keep_a_replaced_turns_point(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        gone = repo.reserve_message(conv_id, prompt="wake", placeholder_response="", status="streaming")
        repo.append_message(conv_id, {"prompt": "q2", "response": "a2"})
        repo.append_message(conv_id, {"prompt": "q3", "response": "a3"})
        # Positions are now 0, 2, 3; points count rows: q3 is row 2.
        assert repo.delete_in_flight_message(str(gone["id"])) is True
        _store(repo, conv_id, _point(0, "pre"), _point(1, "mid", turn_index=2))

        # The user edits q3 (position 3).
        repo.truncate_after(conv_id, keep_up_to=2)

        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["pre"]

    def test_a_replaced_turns_point_goes_by_its_row_id(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        row = repo.reserve_message(conv_id, prompt="q1", placeholder_response="", status="streaming")
        _store(
            repo, conv_id,
            # Indexes that the cut would keep: only the row id says it is gone.
            {**_point(-1, "mid", turn_index=0), "turn_message_id": str(row["id"])},
        )

        repo.truncate_after(conv_id, keep_up_to=0)

        assert _points(repo, conv_id) == []


class TestDeletingAnUnansweredRow:
    def test_a_point_reaching_the_deleted_row_goes_and_an_earlier_one_stays(self, pg_conn):
        repo, conv_id = _conversation(pg_conn, 1)
        row = repo.reserve_message(conv_id, prompt="wake", placeholder_response="", status="streaming")
        repo.append_message(conv_id, {"prompt": "q2", "response": "a2"})
        # Made while row 1 was still open: it covers rows 0-2.
        _store(repo, conv_id, _point(0, "early"), _point(2, "late"))

        assert repo.delete_in_flight_message(str(row["id"])) is True

        # Row q2 is now at index 1, and the next message lands at index 2.
        assert [p["compressed_summary"] for p in _points(repo, conv_id)] == ["early"]
