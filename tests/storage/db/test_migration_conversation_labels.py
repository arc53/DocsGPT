"""Migration round-trip test for 0057_conversation_labels."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


pytestmark = pytest.mark.integration

_PREVIOUS = "0056_conversation_passthrough"
_INDEXES = (
    "conversation_labels_target_uidx", "conversation_labels_agent_time_idx", "conversation_labels_user_time_idx",
    "conversation_labels_message_idx", "conversation_labels_reply_idx", "conversation_labels_resolution_idx",
)


def _run_alembic(url: str, *args: str) -> None:
    ini = Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(ini), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _conversation(conn) -> tuple[str, str, str]:
    cid = conn.execute(text("INSERT INTO conversations (user_id) VALUES ('u') RETURNING CAST(id AS text)")).scalar()
    first, second = (
        conn.execute(
            text(
                "INSERT INTO conversation_messages (conversation_id, user_id, position, prompt, response) "
                "VALUES (CAST(:cid AS uuid), 'u', :pos, 'q', 'a') RETURNING CAST(id AS text)"
            ),
            {"cid": cid, "pos": pos},
        ).scalar()
        for pos in (0, 1)
    )
    return cid, first, second


def _label(conn, cid, message_id=None, label="answer_status", reply=None) -> None:
    conn.execute(
        text(
            "INSERT INTO conversation_labels (conversation_id, message_id, reply_message_id, user_id, level, label, "
            "probabilities, schema_hash, model_version, occurred_at) VALUES (CAST(:cid AS uuid), "
            "CAST(:mid AS uuid), CAST(:reply AS uuid), 'u', 'turn', :label, '{}'::jsonb, 'h', 'v', now())"
        ),
        {"cid": cid, "mid": message_id, "reply": reply, "label": label},
    )


def _count(conn, cid) -> int:
    return conn.execute(
        text("SELECT COUNT(*) FROM conversation_labels WHERE conversation_id = CAST(:cid AS uuid)"), {"cid": cid}
    ).scalar()


def _index_names(conn) -> set[str]:
    rows = conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")).fetchall()
    return {row[0] for row in rows}


class TestMigration0057RoundTrip:
    def test_head_creates_the_table_and_its_indexes(self, pg_engine):
        with pg_engine.connect() as conn:
            names = _index_names(conn)
        assert set(_INDEXES) <= names
        assert "conversation_messages_ts_idx" in names

    def test_rows_record_what_they_were_built_from(self, pg_engine):
        with pg_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'conversation_labels' "
                    "AND column_name IN ('source_updated_at', 'source_hash')"
                )
            ).fetchall()
        assert {row[0]: (row[1], row[2]) for row in rows} == {
            "source_updated_at": ("timestamp with time zone", "YES"),
            "source_hash": ("text", "YES"),
        }

    def test_pending_marks_the_resolutions_still_pending_and_only_they_are_indexed(self, pg_engine):
        # The sweep looks every few minutes for resolutions still pending past their window; settled ones, nearly
        # all of them, stay out of its index.
        with pg_engine.begin() as conn:
            cid, first, _ = _conversation(conn)
            rows = (("resolution", None, {"resolved": 0.4, "pending": 0.6}), ("experience", None, {"pending": 2}),
                    ("topic_effective", first, {"pending": 0.9}))
            for label, message_id, probabilities in rows:
                conn.execute(
                    text(
                        "INSERT INTO conversation_labels (conversation_id, message_id, user_id, level, label, "
                        "probabilities, schema_hash, model_version, occurred_at) VALUES (CAST(:cid AS uuid), "
                        "CAST(:mid AS uuid), 'u', 'conversation', :label, CAST(:p AS jsonb), 'h', 'v', now())"
                    ),
                    {"cid": cid, "mid": message_id, "label": label, "p": json.dumps(probabilities)},
                )

            def pending():
                return {row[0]: row[1] for row in conn.execute(text(
                    "SELECT label, pending FROM conversation_labels WHERE conversation_id = CAST(:cid AS uuid)"
                ), {"cid": cid})}

            assert pending() == {"resolution": True, "experience": False, "topic_effective": False}
            conn.execute(text("UPDATE conversation_labels SET probabilities = '{\"resolved\": 1, \"pending\": 0}'"
                              " WHERE label = 'resolution'"))
            assert pending()["resolution"] is False
            definition = conn.execute(text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'conversation_labels_resolution_idx'")).scalar()
        assert definition.endswith("WHERE pending")

    def test_one_row_per_conversation_message_and_label(self, pg_engine):
        with pg_engine.begin() as conn:
            cid, first, _ = _conversation(conn)
            _label(conn, cid, first)
            _label(conn, cid, None, label="goal_met")
            _label(conn, cid, first, label="request_type")
        for message_id, label in ((first, "answer_status"), (None, "goal_met")):
            with pytest.raises(IntegrityError, match="conversation_labels_target_uidx"):
                with pg_engine.begin() as conn:
                    _label(conn, cid, message_id, label=label)

    def test_labels_go_with_their_message_reply_and_conversation(self, pg_engine):
        with pg_engine.begin() as conn:
            cid, first, second = _conversation(conn)
            _label(conn, cid, first)
            _label(conn, cid, first, label="reaction", reply=second)
            _label(conn, cid, None, label="goal_met")
            assert _count(conn, cid) == 3
            conn.execute(text("DELETE FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": second})
            assert _count(conn, cid) == 2  # the reaction read the deleted reply
            conn.execute(text("DELETE FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": first})
            assert _count(conn, cid) == 1
            conn.execute(text("DELETE FROM conversations WHERE id = CAST(:id AS uuid)"), {"id": cid})
            assert _count(conn, cid) == 0

    def test_downgrade_drops_then_upgrade_restores(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        with pg_engine.begin() as conn:
            cid, first, _ = _conversation(conn)
            _label(conn, cid, first)
        _run_alembic(url, "downgrade", _PREVIOUS)
        with pg_engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('public.conversation_labels')")).scalar() is None
            assert "conversation_messages_ts_idx" not in _index_names(conn)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert set(_INDEXES) | {"conversation_messages_ts_idx"} <= _index_names(conn)
