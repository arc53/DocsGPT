"""Migration round-trip + persistence tests for 0029_agent_guardrails."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0028 = "0028_user_logs_agent_lookup_idx"
_0029 = "0029_agent_guardrails"


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "application" / "alembic.ini"


def _run_alembic(url: str, *args: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _alembic_heads(url: str) -> list[str]:
    out = subprocess.check_output(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), "heads"],
        timeout=60,
        env={**os.environ, "POSTGRES_URI": url},
        text=True,
    )
    return [line for line in out.splitlines() if line.strip()]


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
        ).scalar()
    )


class TestMigration0029RoundTrip:
    def test_single_head(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        heads = _alembic_heads(url)
        assert len(heads) == 1, f"expected one alembic head, got {heads}"
        assert _0029 in heads[0]

    def test_upgrade_creates_column_and_table(self, pg_engine):
        with pg_engine.connect() as conn:
            assert _column_exists(conn, "agents", "config")
            assert _table_exists(conn, "guardrail_events")

    def test_existing_agents_default_to_empty_config(self, pg_engine):
        """The server default must backfill, so old agents parse as disabled."""
        from application.guardrails.config import AgentConfig

        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agents (user_id, name, status) "
                    "VALUES ('u-29', 'legacy', 'published')"
                )
            )
            stored = conn.execute(
                text("SELECT config FROM agents WHERE user_id = 'u-29'")
            ).scalar()
        assert stored == {}
        assert AgentConfig.parse(stored).guardrails.enabled is False

    def test_downgrade_then_upgrade_is_clean(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0028)
        with pg_engine.connect() as conn:
            assert not _column_exists(conn, "agents", "config")
            assert not _table_exists(conn, "guardrail_events")
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert _column_exists(conn, "agents", "config")
            assert _table_exists(conn, "guardrail_events")

    def test_events_survive_message_deletion(self, pg_engine):
        """ON DELETE SET NULL: the compliance trail outlives the conversation."""
        with pg_engine.begin() as conn:
            conv_id = conn.execute(
                text(
                    "INSERT INTO conversations (user_id, name) "
                    "VALUES ('u-29b', 'c') RETURNING id"
                )
            ).scalar()
            msg_id = conn.execute(
                text(
                    "INSERT INTO conversation_messages "
                    "(conversation_id, position, prompt, response, user_id) "
                    "VALUES (:c, 0, 'q', 'a', 'u-29b') RETURNING id"
                ),
                {"c": conv_id},
            ).scalar()
            conn.execute(
                text(
                    "INSERT INTO guardrail_events "
                    "(user_id, message_id, stage, check_name, detector_type, "
                    " action, outcome) "
                    "VALUES ('u-29b', :m, 'output', 'pii', 'PII', 'redact', "
                    "'triggered')"
                ),
                {"m": msg_id},
            )
            conn.execute(
                text("DELETE FROM conversation_messages WHERE id = :m"),
                {"m": msg_id},
            )
            row = conn.execute(
                text(
                    "SELECT message_id, check_name FROM guardrail_events "
                    "WHERE user_id = 'u-29b'"
                )
            ).fetchone()
        assert row is not None, "the audit row must survive"
        assert row[0] is None
        assert row[1] == "pii"


class TestAgentConfigPersistence:
    def test_config_round_trips_through_the_repository(self, pg_engine):
        from application.storage.db.repositories.agents import AgentsRepository

        config = {
            "guardrails": {
                "enabled": True,
                "mode": "scan_all",
                "fail_open": False,
                "timeout_ms": 1500,
                "block_message": "Nope.",
                "controls": [
                    {
                        "check": "pii",
                        "stage": "input",
                        "action": "redact",
                        "enabled": True,
                        "settings": {"entities": ["EMAIL"]},
                    }
                ],
            }
        }
        with pg_engine.begin() as conn:
            repo = AgentsRepository(conn)
            created = repo.create("u-cfg", "a", "published", config=config)
            assert created["config"] == config, "JSONB must not double-encode"

            repo.update(str(created["id"]), "u-cfg", {"config": {"guardrails": {}}})
            reread = repo.get(str(created["id"]), "u-cfg")
        assert reread["config"] == {"guardrails": {}}

    def test_config_survives_a_parse_round_trip(self, pg_engine):
        from application.guardrails.config import AgentConfig
        from application.storage.db.repositories.agents import AgentsRepository

        raw = AgentConfig.model_validate(
            {
                "guardrails": {
                    "enabled": True,
                    "controls": [{"check": "secrets", "stage": "output",
                                  "action": "redact"}],
                }
            }
        ).model_dump(mode="json")
        with pg_engine.begin() as conn:
            repo = AgentsRepository(conn)
            created = repo.create("u-cfg2", "a", "published", config=raw)
            reread = repo.get(str(created["id"]), "u-cfg2")
        parsed = AgentConfig.parse(reread["config"]).guardrails
        assert parsed.enabled is True
        assert parsed.controls[0].check == "secrets"


class TestGuardrailEventsRepository:
    def test_record_and_read_back(self, pg_engine):
        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )
        from application.storage.db.repositories.agents import AgentsRepository

        with pg_engine.begin() as conn:
            agent = AgentsRepository(conn).create("u-ev", "a", "published")
            agent_id = str(agent["id"])
            repo = GuardrailEventsRepository(conn)
            written = repo.record_many(
                [
                    {
                        "user_id": "u-ev",
                        "agent_id": agent_id,
                        "stage": "input",
                        "check_name": "denylist",
                        "detector_type": "DENYLIST",
                        "action": "block",
                        "outcome": "triggered",
                        "category": "BANNED_TERM",
                        "match_count": 2,
                        "detail": "2 banned term match(es)",
                    },
                    {
                        "user_id": "u-ev",
                        "agent_id": agent_id,
                        "stage": "output",
                        "check_name": "policy",
                        "detector_type": "POLICY",
                        "action": "flag",
                        "outcome": "not_evaluated",
                        "detail": "timeout",
                    },
                ]
            )
            assert written == 2
            events = repo.list_for_agent(agent_id, "u-ev")
            summary = repo.summary_for_user("u-ev")

        assert len(events) == 2
        assert summary["totals"]["blocked"] == 1
        assert summary["totals"]["not_evaluated"] == 1
        assert summary["totals"]["flagged"] == 0

    def test_empty_batch_is_a_noop(self, pg_engine):
        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        with pg_engine.begin() as conn:
            assert GuardrailEventsRepository(conn).record_many([]) == 0

    def test_events_are_scoped_to_the_requesting_user(self, pg_engine):
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        with pg_engine.begin() as conn:
            agent = AgentsRepository(conn).create("owner", "a", "published")
            agent_id = str(agent["id"])
            repo = GuardrailEventsRepository(conn)
            repo.record_many(
                [
                    {"user_id": "owner", "agent_id": agent_id, "stage": "input",
                     "check_name": "pii", "detector_type": "PII",
                     "action": "flag", "outcome": "triggered"},
                    {"user_id": "someone-else", "agent_id": agent_id,
                     "stage": "input", "check_name": "secrets",
                     "detector_type": "SECRETS", "action": "flag",
                     "outcome": "triggered"},
                ]
            )
            mine = repo.list_for_agent(agent_id, "owner")
        assert len(mine) == 1
        assert mine[0]["check_name"] == "pii"

    def test_listing_never_exposes_the_key_or_scanned_text(self, pg_engine):
        """``api_key`` is the agent's raw key and ``matched_value`` is raw PII."""
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        with pg_engine.begin() as conn:
            agent = AgentsRepository(conn).create("u-leak", "a", "published")
            agent_id = str(agent["id"])
            repo = GuardrailEventsRepository(conn)
            repo.record_many(
                [{"user_id": "u-leak", "agent_id": agent_id,
                  "api_key": "super-secret-agent-key", "stage": "output",
                  "check_name": "pii", "detector_type": "PII",
                  "action": "redact", "outcome": "triggered",
                  "matched_value": "ada@example.com"}]
            )
            rows = repo.list_for_agent(agent_id, "u-leak")
        assert rows
        assert "api_key" not in rows[0]
        assert "matched_value" not in rows[0]
        assert "super-secret-agent-key" not in str(rows[0])
        assert "ada@example.com" not in str(rows[0])

    def test_purge_respects_the_window(self, pg_engine):
        from application.storage.db.repositories.guardrail_events import (
            GuardrailEventsRepository,
        )

        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO guardrail_events "
                    "(user_id, stage, check_name, detector_type, action, "
                    " outcome, created_at) "
                    "VALUES ('u-purge', 'input', 'pii', 'PII', 'flag', "
                    "'triggered', NOW() - INTERVAL '90 days')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO guardrail_events "
                    "(user_id, stage, check_name, detector_type, action, "
                    " outcome) "
                    "VALUES ('u-purge', 'input', 'pii', 'PII', 'flag', "
                    "'triggered')"
                )
            )
            deleted = GuardrailEventsRepository(conn).purge_older_than(30)
            remaining = conn.execute(
                text(
                    "SELECT COUNT(*) FROM guardrail_events "
                    "WHERE user_id = 'u-purge'"
                )
            ).scalar()
        assert deleted == 1
        assert remaining == 1
