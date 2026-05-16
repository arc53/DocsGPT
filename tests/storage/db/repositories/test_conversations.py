"""Tests for ConversationsRepository against a real Postgres instance."""

from __future__ import annotations

from datetime import datetime, timezone


from application.storage.db.repositories.conversations import (
    ConversationsRepository,
    MessageUpdateOutcome,
)


def _repo(conn) -> ConversationsRepository:
    return ConversationsRepository(conn)


# ------------------------------------------------------------------
# Conversation CRUD
# ------------------------------------------------------------------


class TestCreate:
    def test_creates_conversation(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "My Chat")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "My Chat"
        assert doc["id"] is not None
        assert doc["_id"] == doc["id"]

    def test_create_with_agent(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        agent_repo = AgentsRepository(pg_conn)
        agent = agent_repo.create("user-1", "a", "active")
        repo = _repo(pg_conn)
        doc = repo.create(
            "user-1", "Chat",
            agent_id=agent["id"],
            api_key="ak-123",
            is_shared_usage=True,
            shared_token="tok-abc",
        )
        assert str(doc["agent_id"]) == agent["id"]
        assert doc["api_key"] == "ak-123"
        assert doc["is_shared_usage"] is True
        assert doc["shared_token"] == "tok-abc"


class TestGet:
    def test_get_owned(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "c")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "u") is None

    def test_get_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "c")
        assert repo.get(created["id"], "user-other") is None


class TestListForUser:
    def test_lists_own_conversations(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "c1")
        repo.create("alice", "c2")
        repo.create("bob", "c3")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)

    def test_excludes_api_key_without_agent(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "normal")
        repo.create("alice", "api-only", api_key="key-1")
        results = repo.list_for_user("alice")
        assert len(results) == 1
        assert results[0]["name"] == "normal"


class TestRename:
    def test_renames(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        assert repo.rename(created["id"], "user-1", "new") is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"

    def test_rename_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        assert repo.rename(created["id"], "user-other", "new") is False


class TestDelete:
    def test_deletes(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "c")
        assert repo.delete(created["id"], "user-1") is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "c")
        assert repo.delete(created["id"], "user-other") is False

    def test_delete_cascades_messages(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "hi", "response": "hello"})
        repo.delete(conv["id"], "user-1")
        assert repo.get_messages(conv["id"]) == []

    def test_delete_all_for_user(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("user-1", "c1")
        repo.create("user-1", "c2")
        repo.create("user-2", "c3")
        count = repo.delete_all_for_user("user-1")
        assert count == 2
        assert repo.list_for_user("user-1") == []
        assert len(repo.list_for_user("user-2")) == 1


# ------------------------------------------------------------------
# Messages
# ------------------------------------------------------------------


class TestAppendMessage:
    def test_append_first_message(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        msg = repo.append_message(conv["id"], {
            "prompt": "hello",
            "response": "hi there",
            "model_id": "gpt-4",
        })
        assert msg["position"] == 0
        assert msg["prompt"] == "hello"
        assert msg["response"] == "hi there"
        assert msg["model_id"] == "gpt-4"

    def test_append_increments_position(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        m0 = repo.append_message(conv["id"], {"prompt": "q1", "response": "a1"})
        m1 = repo.append_message(conv["id"], {"prompt": "q2", "response": "a2"})
        assert m0["position"] == 0
        assert m1["position"] == 1

    def test_append_with_sources_and_tools(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        msg = repo.append_message(conv["id"], {
            "prompt": "q",
            "response": "a",
            "sources": [{"title": "doc1"}],
            "tool_calls": [{"name": "search", "args": {}}],
            "metadata": {"search_query": "rewritten"},
        })
        assert msg["sources"] == [{"title": "doc1"}]
        assert msg["tool_calls"] == [{"name": "search", "args": {}}]
        assert msg["metadata"] == {"search_query": "rewritten"}

    def test_append_preserves_explicit_timestamp(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        ts = datetime.now(timezone.utc)
        msg = repo.append_message(conv["id"], {
            "prompt": "q",
            "response": "a",
            "timestamp": ts,
        })
        # ``row_to_dict`` coerces datetimes to ISO strings at the SELECT
        # boundary; round-trip via ``fromisoformat`` to compare values.
        assert datetime.fromisoformat(msg["timestamp"]) == ts


class TestGetMessages:
    def test_returns_ordered_messages(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q1", "response": "a1"})
        repo.append_message(conv["id"], {"prompt": "q2", "response": "a2"})
        msgs = repo.get_messages(conv["id"])
        assert len(msgs) == 2
        assert msgs[0]["position"] == 0
        assert msgs[1]["position"] == 1

    def test_get_message_at(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q1", "response": "a1"})
        repo.append_message(conv["id"], {"prompt": "q2", "response": "a2"})
        msg = repo.get_message_at(conv["id"], 1)
        assert msg["prompt"] == "q2"

    def test_get_message_at_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        assert repo.get_message_at(conv["id"], 99) is None


class TestUpdateMessageAt:
    def test_updates_response(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "old"})
        assert repo.update_message_at(conv["id"], 0, {"response": "new"}) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert msg["response"] == "new"

    def test_update_disallowed_field(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        assert repo.update_message_at(conv["id"], 0, {"id": "bad"}) is False

    def test_updates_explicit_timestamp(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "old"})
        ts = datetime.now(timezone.utc)
        assert repo.update_message_at(
            conv["id"], 0, {"response": "new", "timestamp": ts},
        ) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert msg["response"] == "new"
        assert datetime.fromisoformat(msg["timestamp"]) == ts


class TestTruncateAfter:
    def test_truncates_messages(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        for i in range(5):
            repo.append_message(conv["id"], {"prompt": f"q{i}", "response": f"a{i}"})
        deleted = repo.truncate_after(conv["id"], 2)
        assert deleted == 2
        msgs = repo.get_messages(conv["id"])
        assert len(msgs) == 3
        assert [m["position"] for m in msgs] == [0, 1, 2]


class TestSetFeedback:
    def test_set_feedback(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        assert repo.set_feedback(conv["id"], 0, {"text": "thumbs_up"}) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert msg["feedback"] == {"text": "thumbs_up"}

    def test_unset_feedback(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        repo.set_feedback(conv["id"], 0, {"text": "thumbs_up"})
        assert repo.set_feedback(conv["id"], 0, None) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert msg["feedback"] is None

    def test_set_feedback_nonexistent_position(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        assert repo.set_feedback(conv["id"], 99, {"text": "x"}) is False


class TestMessageCount:
    def test_counts_messages(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        assert repo.message_count(conv["id"]) == 0
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        assert repo.message_count(conv["id"]) == 1


class TestCompressionMetadata:
    def test_set_compression_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        meta = {"is_compressed": True, "last_compression_at": "2026-01-01T00:00:00Z"}
        assert repo.update_compression_metadata(conv["id"], "user-1", meta) is True
        fetched = repo.get(conv["id"], "user-1")
        assert fetched["compression_metadata"]["is_compressed"] is True

    def test_set_compression_flags_preserves_points(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.update_compression_metadata(conv["id"], "user-1", {
            "is_compressed": False,
            "compression_points": [{"summary": "earlier"}],
        })
        assert repo.set_compression_flags(
            conv["id"], is_compressed=True, last_compression_at="2026-01-02",
        ) is True
        fetched = repo.get(conv["id"], "user-1")
        assert fetched["compression_metadata"]["is_compressed"] is True
        assert fetched["compression_metadata"]["last_compression_at"] == "2026-01-02"
        assert fetched["compression_metadata"]["compression_points"] == [
            {"summary": "earlier"}
        ]

    def test_append_compression_point_slices_to_max(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        for i in range(5):
            assert repo.append_compression_point(
                conv["id"], {"summary": f"p{i}"}, max_points=3,
            ) is True
        fetched = repo.get(conv["id"], "user-1")
        points = fetched["compression_metadata"]["compression_points"]
        assert [p["summary"] for p in points] == ["p2", "p3", "p4"]


class TestResolveAgentRef:
    """The repo must translate Mongo ObjectId-shaped ``agent_id`` values
    to Postgres UUIDs on ``create`` so that dual-write from the
    ObjectId-era conversation service doesn't silently lose rows."""

    def test_create_translates_objectid_agent_id(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        agent_repo = AgentsRepository(pg_conn)
        legacy_oid = "507f1f77bcf86cd799439099"
        agent = agent_repo.create(
            "user-1", "a", "active", legacy_mongo_id=legacy_oid,
        )
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "chat", agent_id=legacy_oid)
        assert str(conv["agent_id"]) == agent["id"]

    def test_create_passes_through_uuid_agent_id(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        agent_repo = AgentsRepository(pg_conn)
        agent = agent_repo.create("user-1", "a", "active")
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "chat", agent_id=agent["id"])
        assert str(conv["agent_id"]) == agent["id"]

    def test_create_drops_unknown_objectid_agent_id(self, pg_conn):
        # Unknown legacy id resolves to None — the conversation row still
        # inserts (dual_write stays quiet) but without an agent FK.
        repo = _repo(pg_conn)
        conv = repo.create(
            "user-1", "chat", agent_id="507f1f77bcf86cd7994390aa",
        )
        assert conv["agent_id"] is None


class TestResolveAttachmentRefs:
    """``append_message`` and ``update_message_at`` must translate Mongo
    ObjectId attachment ids to PG UUIDs via ``attachments.legacy_mongo_id``.
    Without this, the ``uuid[]`` cast raises and dual_write drops the
    whole message."""

    def _create_attachment(self, pg_conn, legacy: str) -> str:
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )

        att = AttachmentsRepository(pg_conn).create(
            "user-1", "a.txt", "/tmp/a.txt", legacy_mongo_id=legacy,
        )
        return att["id"]

    def test_append_translates_objectid_attachments(self, pg_conn):
        att_uuid = self._create_attachment(
            pg_conn, "507f1f77bcf86cd799439011",
        )
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        msg = repo.append_message(conv["id"], {
            "prompt": "q", "response": "a",
            "attachments": ["507f1f77bcf86cd799439011"],
        })
        assert [str(a) for a in msg["attachments"]] == [att_uuid]

    def test_append_passes_through_uuid_attachments(self, pg_conn):
        att_uuid = self._create_attachment(
            pg_conn, "507f1f77bcf86cd799439022",
        )
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        msg = repo.append_message(conv["id"], {
            "prompt": "q", "response": "a",
            "attachments": [att_uuid],
        })
        assert [str(a) for a in msg["attachments"]] == [att_uuid]

    def test_append_drops_unknown_objectid_attachments(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        # Unknown legacy id is silently dropped; message still inserts.
        msg = repo.append_message(conv["id"], {
            "prompt": "q", "response": "a",
            "attachments": ["507f1f77bcf86cd7994390bb"],
        })
        assert list(msg["attachments"] or []) == []

    def test_update_translates_objectid_attachments(self, pg_conn):
        att_uuid = self._create_attachment(
            pg_conn, "507f1f77bcf86cd799439033",
        )
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        assert repo.update_message_at(
            conv["id"], 0,
            {"attachments": ["507f1f77bcf86cd799439033"]},
        ) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert [str(a) for a in msg["attachments"]] == [att_uuid]


class TestUpdateMessageFeedback:
    """``feedback`` / ``feedback_timestamp`` must be in the update whitelist
    so continuation-flow re-appends don't silently strip them."""

    def test_update_sets_feedback(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        assert repo.update_message_at(
            conv["id"], 0, {"feedback": {"text": "thumbs_up"}},
        ) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert msg["feedback"] == {"text": "thumbs_up"}

    def test_update_clears_feedback(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        repo.set_feedback(conv["id"], 0, {"text": "thumbs_up"})
        assert repo.update_message_at(
            conv["id"], 0, {"feedback": None},
        ) is True
        msg = repo.get_message_at(conv["id"], 0)
        assert msg["feedback"] is None


class TestReserveAndFinalizeMessage:
    """Pre-persist (WAL) + finalisation primitives used by save_user_question /
    finalize_message in the answer-streaming path."""

    def test_reserve_message_inserts_pending_row(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"],
            prompt="q1",
            placeholder_response="placeholder",
            request_id="req-1",
        )
        assert msg["position"] == 0
        assert msg["status"] == "pending"
        assert msg["request_id"] == "req-1"
        assert msg["prompt"] == "q1"
        assert msg["response"] == "placeholder"

    def test_reserve_message_allocates_next_position(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        repo.append_message(conv["id"], {"prompt": "q0", "response": "a0"})
        msg = repo.reserve_message(
            conv["id"], prompt="q1", placeholder_response="ph",
        )
        assert msg["position"] == 1

    def test_update_message_by_id_updates_response_and_status(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        outcome = repo.update_message_by_id(
            msg["id"], {"response": "real answer", "status": "complete"},
        )
        assert outcome is MessageUpdateOutcome.UPDATED
        refreshed = repo.get_message_at(conv["id"], 0)
        assert refreshed["response"] == "real answer"
        assert refreshed["status"] == "complete"

    def test_update_message_by_id_writes_metadata_error(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        repo.update_message_by_id(
            msg["id"],
            {"status": "failed", "metadata": {"error": "RuntimeError: boom"}},
        )
        refreshed = repo.get_message_at(conv["id"], 0)
        assert refreshed["status"] == "failed"
        assert refreshed["metadata"]["error"] == "RuntimeError: boom"

    def test_update_message_by_id_rejects_non_uuid(self, pg_conn):
        repo = _repo(pg_conn)
        assert (
            repo.update_message_by_id("not-a-uuid", {"status": "complete"})
            is MessageUpdateOutcome.INVALID
        )

    def test_update_message_by_id_distinguishes_already_complete(self, pg_conn):
        """When the row is already ``complete``, a subsequent
        ``only_if_non_terminal=True`` finalize must report
        ``ALREADY_COMPLETE`` — not ``UPDATED`` and not the generic
        not-found case. The SSE abort handler relies on this to
        journal ``end`` instead of a spurious ``error`` when the
        normal-path finalize wins the race against a client
        disconnect.
        """
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        first = repo.update_message_by_id(
            msg["id"], {"response": "ok", "status": "complete"},
            only_if_non_terminal=True,
        )
        assert first is MessageUpdateOutcome.UPDATED
        second = repo.update_message_by_id(
            msg["id"], {"response": "ok again", "status": "complete"},
            only_if_non_terminal=True,
        )
        assert second is MessageUpdateOutcome.ALREADY_COMPLETE
        # The second attempt must NOT have overwritten anything.
        refreshed = repo.get_message_at(conv["id"], 0)
        assert refreshed["response"] == "ok"

    def test_update_message_by_id_distinguishes_already_failed(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        assert repo.update_message_by_id(
            msg["id"], {"response": "boom", "status": "failed"},
            only_if_non_terminal=True,
        ) is MessageUpdateOutcome.UPDATED
        assert repo.update_message_by_id(
            msg["id"], {"response": "late", "status": "complete"},
            only_if_non_terminal=True,
        ) is MessageUpdateOutcome.ALREADY_FAILED

    def test_update_message_by_id_unknown_uuid_is_not_found(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.update_message_by_id(
            "00000000-0000-0000-0000-000000000000",
            {"status": "complete"},
            only_if_non_terminal=True,
        ) is MessageUpdateOutcome.NOT_FOUND

    def test_update_message_status_only(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        assert repo.update_message_status(msg["id"], "streaming") is True
        refreshed = repo.get_message_at(conv["id"], 0)
        assert refreshed["status"] == "streaming"

    def test_confirm_executed_tool_calls_flips_status(self, pg_conn):
        from sqlalchemy import text as sql_text
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        # Insert two rows: one 'executed' (should flip), one 'proposed' (no-op).
        pg_conn.execute(
            sql_text(
                "INSERT INTO tool_call_attempts "
                "(call_id, message_id, tool_name, action_name, arguments, status) "
                "VALUES (:cid, CAST(:mid AS uuid), 't', 'a', '{}'::jsonb, :status)"
            ),
            [
                {"cid": "c-exec", "mid": msg["id"], "status": "executed"},
                {"cid": "c-prop", "mid": msg["id"], "status": "proposed"},
            ],
        )
        flipped = repo.confirm_executed_tool_calls(msg["id"])
        assert flipped == 1
        rows = pg_conn.execute(
            sql_text(
                "SELECT call_id, status FROM tool_call_attempts "
                "WHERE message_id = CAST(:mid AS uuid) ORDER BY call_id"
            ),
            {"mid": msg["id"]},
        ).fetchall()
        as_dict = {r[0]: r[1] for r in rows}
        assert as_dict == {"c-exec": "confirmed", "c-prop": "proposed"}

    def test_confirm_executed_tool_calls_no_rows_is_zero(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-r", "c")
        msg = repo.reserve_message(
            conv["id"], prompt="q", placeholder_response="ph",
        )
        # No tool_call_attempts inserted — no-op
        assert repo.confirm_executed_tool_calls(msg["id"]) == 0


class TestConcurrentAppend:
    """Two threads appending to the same conversation must not race on
    ``position``. The migration plan explicitly calls this out as the
    single trickiest invariant, so we exercise it directly with two
    parallel connections."""

    def test_concurrent_appends_get_distinct_positions(self, pg_engine, pg_conn):
        import threading

        # Arrange — one conversation, created inside the outer test txn so
        # it disappears on teardown even if the workers somehow commit.
        # We commit it explicitly so the workers' separate sessions see it.
        repo_setup = _repo(pg_conn)
        conv = repo_setup.create("user-concurrent", "c")
        pg_conn.commit()

        try:
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    with pg_engine.begin() as worker_conn:
                        ConversationsRepository(worker_conn).append_message(
                            conv["id"], {"prompt": "q", "response": "a"},
                        )
                except BaseException as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"worker threads errored: {errors}"

            # Assert — the parent row-lock in append_message must have
            # serialised the two inserts so they land at positions {0, 1}.
            with pg_engine.connect() as verify_conn:
                msgs = ConversationsRepository(verify_conn).get_messages(conv["id"])
            positions = sorted(m["position"] for m in msgs)
            assert positions == [0, 1], (
                f"concurrent appends raced; got positions {positions}"
            )
        finally:
            # Clean up — the conversation was committed, so the transaction
            # rollback won't drop it.
            with pg_engine.begin() as cleanup_conn:
                ConversationsRepository(cleanup_conn).delete(
                    conv["id"], "user-concurrent"
                )
                ConversationsRepository(cleanup_conn).delete(
                    conv["id"], "user-concurrent"
                )


class TestSharedWith:
    def test_add_shared_user_by_uuid(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("owner", "c")
        assert repo.add_shared_user(conv["id"], "bob") is True
        fetched = repo.get(conv["id"], "bob")
        assert fetched is not None
        assert "bob" in fetched["shared_with"]

    def test_add_shared_user_is_idempotent(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("owner", "c")
        assert repo.add_shared_user(conv["id"], "bob") is True
        # Second call is a no-op (mirrors Mongo $addToSet semantics).
        assert repo.add_shared_user(conv["id"], "bob") is False
        fetched = repo.get(conv["id"], "bob")
        assert fetched["shared_with"].count("bob") == 1

    def test_add_shared_user_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create(
            "owner", "c", legacy_mongo_id="507f1f77bcf86cd799439abc"
        )
        assert repo.add_shared_user("507f1f77bcf86cd799439abc", "bob") is True
        fetched = repo.get(conv["id"], "bob")
        assert "bob" in fetched["shared_with"]

    def test_add_shared_user_empty_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("owner", "c")
        assert repo.add_shared_user(conv["id"], "") is False

    def test_remove_shared_user(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("owner", "c")
        repo.add_shared_user(conv["id"], "bob")
        repo.add_shared_user(conv["id"], "carol")
        assert repo.remove_shared_user(conv["id"], "bob") is True
        fetched = repo.get(conv["id"], "carol")
        assert fetched["shared_with"] == ["carol"]

    def test_remove_missing_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("owner", "c")
        assert repo.remove_shared_user(conv["id"], "bob") is False

    def test_remove_shared_user_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create(
            "owner", "c", legacy_mongo_id="507f1f77bcf86cd799439def"
        )
        repo.add_shared_user("507f1f77bcf86cd799439def", "bob")
        assert repo.remove_shared_user("507f1f77bcf86cd799439def", "bob") is True
        fetched = repo.get(conv["id"], "owner")
        assert fetched["shared_with"] == []


class TestUuidShapeGate:
    """Regression: a non-UUID conversation id (e.g. a legacy Mongo
    ObjectId still embedded in old client-side state) must never reach
    ``CAST(:id AS uuid)``. The cast raises ``InvalidTextRepresentation``
    on the server and **aborts the enclosing Postgres transaction**,
    making every subsequent query on the same connection fail. These
    tests pin the conservative behaviour: return False/None/0 for
    non-UUID input and leave the transaction usable."""

    @staticmethod
    def _assert_txn_alive(conn) -> None:
        """Subsequent trivial query must succeed — proves the txn wasn't
        poisoned. This is the load-bearing assertion; "returns False"
        alone is insufficient since the old code did exactly that while
        leaving the txn dead."""
        from sqlalchemy import text as _text

        assert conn.execute(_text("SELECT 1")).scalar() == 1

    def test_rename_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.rename("507f1f77bcf86cd799439011", "user-1", "new") is False
        self._assert_txn_alive(pg_conn)

    def test_rename_uuid_path_still_works(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        assert repo.rename(created["id"], "user-1", "new") is True

    def test_delete_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.delete("507f1f77bcf86cd799439011", "user-1") is False
        self._assert_txn_alive(pg_conn)

    def test_delete_uuid_path_still_works(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "c")
        assert repo.delete(created["id"], "user-1") is True

    def test_set_feedback_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.set_feedback(
            "507f1f77bcf86cd799439011", 0, {"text": "x"},
        ) is False
        self._assert_txn_alive(pg_conn)

    def test_truncate_after_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.truncate_after("507f1f77bcf86cd799439011", 0) == 0
        self._assert_txn_alive(pg_conn)

    def test_set_shared_token_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.set_shared_token(
            "507f1f77bcf86cd799439011", "user-1", "tok",
        ) is False
        self._assert_txn_alive(pg_conn)

    def test_update_compression_metadata_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.update_compression_metadata(
            "507f1f77bcf86cd799439011", "user-1", {"is_compressed": True},
        ) is False
        self._assert_txn_alive(pg_conn)

    def test_set_compression_flags_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.set_compression_flags(
            "507f1f77bcf86cd799439011",
            is_compressed=True,
            last_compression_at="2026-01-01",
        ) is False
        self._assert_txn_alive(pg_conn)

    def test_append_compression_point_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.append_compression_point(
            "507f1f77bcf86cd799439011", {"summary": "x"}, max_points=3,
        ) is False
        self._assert_txn_alive(pg_conn)

    def test_get_message_at_rejects_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get_message_at("507f1f77bcf86cd799439011", 0) is None
        self._assert_txn_alive(pg_conn)

    def test_rename_rejects_garbage(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.rename("not-an-id", "user-1", "new") is False
        self._assert_txn_alive(pg_conn)

    def test_get_message_at_uuid_path_still_works(self, pg_conn):
        repo = _repo(pg_conn)
        conv = repo.create("user-1", "c")
        repo.append_message(conv["id"], {"prompt": "q", "response": "a"})
        msg = repo.get_message_at(conv["id"], 0)
        assert msg is not None
        assert msg["prompt"] == "q"
