"""Tests for /api/agent_starters (docsgpt/api/answer/routes/starters.py).

The route resolves an agent by its API key, as ``/stream`` does, and returns
only the agent's starters: the questions the chat widget lists when the
embedding site passes none of its own. Uses real repositories on ``pg_conn``.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.storage.db.repositories.agents import AgentsRepository

STARTERS = ["Which contracts renew this quarter?", "Run due diligence on a new vendor"]


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.routes.starters.db_readonly", _yield):
        yield


def _post(flask_app, conn, body):
    from docsgpt.api.answer.routes.starters import AgentStartersResource

    with _patch_db(conn), flask_app.app_context(), flask_app.test_request_context(json=body):
        return AgentStartersResource().post()


class TestAgentStartersResource:
    def test_known_key_returns_starters(self, pg_conn, flask_app):
        AgentsRepository(pg_conn).create("u", "a", "published", key="starters-key", starters=STARTERS)

        result = _post(flask_app, pg_conn, {"api_key": "starters-key"})

        assert result.status_code == 200
        assert result.json == {"starters": STARTERS}

    def test_agent_without_starters_returns_empty_list(self, pg_conn, flask_app):
        AgentsRepository(pg_conn).create("u", "a", "published", key="no-starters-key")

        result = _post(flask_app, pg_conn, {"api_key": "no-starters-key"})

        assert result.status_code == 200
        assert result.json == {"starters": []}

    def test_returns_nothing_else_about_the_agent(self, pg_conn, flask_app):
        AgentsRepository(pg_conn).create(
            "u", "Secret name", "published", key="only-starters-key", description="private", starters=STARTERS,
        )

        result = _post(flask_app, pg_conn, {"api_key": "only-starters-key"})

        assert set(result.json) == {"starters"}

    def test_unknown_key_returns_401(self, pg_conn, flask_app):
        result = _post(flask_app, pg_conn, {"api_key": "does-not-exist"})

        assert result.status_code == 401
        assert result.json == {"success": False, "message": "Invalid API key."}

    @pytest.mark.parametrize("body", [{}, {"api_key": ""}, {"api_key": "   "}, {"api_key": 42}, ["starters-key"]])
    def test_missing_key_returns_400(self, pg_conn, flask_app, body):
        result = _post(flask_app, pg_conn, body)

        assert result.status_code == 400
        assert result.json == {"success": False, "message": "api_key is required"}
