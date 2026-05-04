"""Idempotency-Key behavior on the agent webhook listener route."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.agents.webhooks.db_session", _yield
    ), patch(
        "application.api.user.agents.webhooks.db_readonly", _yield
    ):
        yield


def _seed_agent(pg_conn, user="u", token="tk", **kw):
    from application.storage.db.repositories.agents import AgentsRepository
    return AgentsRepository(pg_conn).create(
        user, "a", "published", incoming_webhook_token=token, **kw,
    )


def _apply_async_mock():
    """Mock for ``process_agent_webhook.apply_async``; ``task.id`` mirrors the predetermined id."""
    def _side_effect(*args, **kwargs):
        return MagicMock(id=kwargs.get("task_id") or "auto-task-id")
    return MagicMock(side_effect=_side_effect)


class TestWebhookIdempotency:
    def test_no_header_enqueues_normally(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-noh", token="tk-noh")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-noh", method="POST",
            json={"event": "x"},
        ):
            listener = AgentWebhookListener()
            response = listener.post(
                webhook_token="tk-noh",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert response.status_code == 200
        assert apply_mock.call_count == 1

    def test_header_first_post_records_row(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-first", token="tk-first")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-first", method="POST",
            json={"event": "x"},
            headers={"Idempotency-Key": "key-abc"},
        ):
            listener = AgentWebhookListener()
            response = listener.post(
                webhook_token="tk-first",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert response.status_code == 200
        assert apply_mock.call_count == 1
        predetermined_id = apply_mock.call_args.kwargs["task_id"]
        assert response.json["task_id"] == predetermined_id

        # Stored under the *scoped* form ``"{agent_id}:{key}"`` so two
        # agents sharing the same raw header don't collapse on PK.
        scoped_key = f"{agent['id']}:key-abc"
        row = pg_conn.execute(
            text("SELECT task_id, agent_id FROM webhook_dedup WHERE idempotency_key = :k"),
            {"k": scoped_key},
        ).fetchone()
        assert row is not None
        assert row[0] == predetermined_id
        assert str(row[1]) == str(agent["id"])

    def test_header_forwards_idempotency_key_to_delay(self, app, pg_conn):
        """The Celery task body needs the key so ``with_idempotency`` can
        record terminal status and ``_derive_source_id`` can pick it up.
        """
        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-fwd", token="tk-fwd")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-fwd", method="POST",
            json={"event": "x"},
            headers={"Idempotency-Key": "key-fwd"},
        ):
            listener = AgentWebhookListener()
            listener.post(
                webhook_token="tk-fwd",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        # Worker sees the agent-scoped form so its dedup row is also
        # agent-distinct.
        scoped_key = f"{agent['id']}:key-fwd"
        assert (
            apply_mock.call_args.kwargs["kwargs"]["idempotency_key"]
            == scoped_key
        )

    def test_same_header_second_post_returns_cached(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-rep", token="tk-rep")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ):
            with app.test_request_context(
                "/api/webhooks/agents/tk-rep", method="POST",
                json={"event": "x"},
                headers={"Idempotency-Key": "key-rep"},
            ):
                listener = AgentWebhookListener()
                first = listener.post(
                    webhook_token="tk-rep",
                    agent=agent,
                    agent_id_str=str(agent["id"]),
                )
            with app.test_request_context(
                "/api/webhooks/agents/tk-rep", method="POST",
                json={"event": "x"},
                headers={"Idempotency-Key": "key-rep"},
            ):
                listener = AgentWebhookListener()
                second = listener.post(
                    webhook_token="tk-rep",
                    agent=agent,
                    agent_id_str=str(agent["id"]),
                )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json == second.json
        assert apply_mock.call_count == 1

    def test_concurrent_same_key_only_one_apply_async(self, app, pg_engine):
        """Race test (M3): N parallel webhook POSTs with same key → only ONE apply_async.

        Uses ``pg_engine`` so each thread checks out its own DB connection
        (sharing a single Connection serializes at the driver level).
        """
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager

        from application.api.user.agents.webhooks import AgentWebhookListener
        from application.storage.db.repositories.agents import AgentsRepository

        with pg_engine.begin() as conn:
            agent = AgentsRepository(conn).create(
                "u-race", "a", "published", incoming_webhook_token="tk-race",
            )

        apply_mock = _apply_async_mock()

        @contextmanager
        def _engine_session():
            with pg_engine.begin() as conn:
                yield conn

        @contextmanager
        def _engine_readonly():
            with pg_engine.connect() as conn:
                yield conn

        def fire(idx):
            # Patches sit outside the thread pool (see below); only the
            # per-thread Flask request context is set up inside.
            with app.test_request_context(
                "/api/webhooks/agents/tk-race", method="POST",
                json={"event": idx},
                headers={"Idempotency-Key": "wh-race"},
            ):
                listener = AgentWebhookListener()
                return listener.post(
                    webhook_token="tk-race",
                    agent=agent,
                    agent_id_str=str(agent["id"]),
                )

        # ``unittest.mock.patch`` is not thread-safe; set up
        # module-attribute patches once before fanning out so every
        # thread sees the mock instead of racing on save/restore.
        with patch(
            "application.api.user.agents.webhooks.db_session",
            _engine_session,
        ), patch(
            "application.api.user.agents.webhooks.db_readonly",
            _engine_readonly,
        ), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), ThreadPoolExecutor(max_workers=8) as ex:
            responses = list(ex.map(fire, range(8)))
        assert all(r.status_code == 200 for r in responses)
        assert apply_mock.call_count == 1
        ids = {r.json["task_id"] for r in responses}
        assert len(ids) == 1
        assert "deduplicated" not in ids

    def test_same_key_different_agent_does_not_collide(self, app, pg_conn):
        """Idempotency keys are now scoped by ``agent_id`` — two agents
        sending the same raw header each get their own dedup row, both
        requests enqueue work, and the responses carry distinct
        ``task_id``s. (Pre-fix, the second agent's request was silently
        deduplicated against the first agent's row.)
        """
        from sqlalchemy import text as sql_text

        from application.api.user.agents.webhooks import AgentWebhookListener

        agent_a = _seed_agent(pg_conn, user="u-a", token="tk-a")
        agent_b = _seed_agent(pg_conn, user="u-b", token="tk-b")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ):
            with app.test_request_context(
                "/api/webhooks/agents/tk-a", method="POST",
                json={"event": "x"},
                headers={"Idempotency-Key": "global-key"},
            ):
                listener = AgentWebhookListener()
                first = listener.post(
                    webhook_token="tk-a",
                    agent=agent_a,
                    agent_id_str=str(agent_a["id"]),
                )
            with app.test_request_context(
                "/api/webhooks/agents/tk-b", method="POST",
                json={"event": "x"},
                headers={"Idempotency-Key": "global-key"},
            ):
                listener = AgentWebhookListener()
                second = listener.post(
                    webhook_token="tk-b",
                    agent=agent_b,
                    agent_id_str=str(agent_b["id"]),
                )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json["task_id"] != second.json["task_id"]
        assert apply_mock.call_count == 2

        # And there are two ``webhook_dedup`` rows: one per agent scope.
        rows = pg_conn.execute(
            sql_text(
                "SELECT idempotency_key, agent_id FROM webhook_dedup "
                "WHERE idempotency_key LIKE :pat ORDER BY idempotency_key"
            ),
            {"pat": "%:global-key"},
        ).fetchall()
        assert len(rows) == 2
        scopes = {str(r[1]) for r in rows}
        assert scopes == {str(agent_a["id"]), str(agent_b["id"])}

    def test_empty_header_treated_as_absent(self, app, pg_conn):
        from sqlalchemy import text

        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-empty", token="tk-empty")
        apply_mock = _apply_async_mock()

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-empty", method="POST",
            json={"event": "x"},
            headers={"Idempotency-Key": ""},
        ):
            listener = AgentWebhookListener()
            response = listener.post(
                webhook_token="tk-empty",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert response.status_code == 200
        assert apply_mock.call_count == 1
        count = pg_conn.execute(
            text("SELECT count(*) FROM webhook_dedup")
        ).scalar()
        assert count == 0

    def test_oversized_header_rejected_with_400(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-big", token="tk-big")
        oversized = "x" * 257

        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
        ) as mock_apply, app.test_request_context(
            "/api/webhooks/agents/tk-big", method="POST",
            json={"event": "x"},
            headers={"Idempotency-Key": oversized},
        ):
            listener = AgentWebhookListener()
            response = listener.post(
                webhook_token="tk-big",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert response.status_code == 400
        assert mock_apply.call_count == 0

    def test_stale_dedup_row_does_not_block_new_work(self, app, pg_conn):
        """Regression for the TTL fail-shut bug: a >24h-old dedup row
        must not silently drop a new request. Pre-fix, the second POST
        returned ``task_id="deduplicated"`` and never enqueued.
        """
        from sqlalchemy import text

        from application.api.user.agents.webhooks import AgentWebhookListener

        agent = _seed_agent(pg_conn, user="u-stale", token="tk-stale")
        apply_mock = _apply_async_mock()

        # First POST creates a dedup row.
        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-stale", method="POST",
            json={"event": "x"},
            headers={"Idempotency-Key": "stale-key"},
        ):
            listener = AgentWebhookListener()
            first = listener.post(
                webhook_token="tk-stale",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert first.status_code == 200
        first_task_id = first.json["task_id"]
        assert first_task_id != "deduplicated"

        # Backdate the row so it looks 25h old.
        scoped_key = f"{agent['id']}:stale-key"
        pg_conn.execute(
            text(
                "UPDATE webhook_dedup SET created_at = "
                "clock_timestamp() - make_interval(hours => 25) "
                "WHERE idempotency_key = :k"
            ),
            {"k": scoped_key},
        )

        # Second POST with the same key must enqueue again, not silently dedup.
        with _patch_db(pg_conn), patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            apply_mock,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-stale", method="POST",
            json={"event": "x2"},
            headers={"Idempotency-Key": "stale-key"},
        ):
            listener = AgentWebhookListener()
            second = listener.post(
                webhook_token="tk-stale",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert second.status_code == 200
        assert second.json["task_id"] != "deduplicated"
        assert second.json["task_id"] != first_task_id
        assert apply_mock.call_count == 2
