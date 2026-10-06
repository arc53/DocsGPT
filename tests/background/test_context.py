"""Which turns may hand calls off, and which conversations a finished job may resume."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text

from docsgpt.background.context import BackgroundContext, auto_resume_allowed, bind_turn
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def _agent(conn, owner):
    return str(conn.execute(
        text("INSERT INTO agents (user_id, name, status) VALUES (:u, 'a', 'draft') RETURNING id"), {"u": owner}
    ).scalar())


class TestAutoResumeAllowed:
    def test_policy(self, pg_conn):
        repo = ConversationsRepository(pg_conn)
        own = str(repo.create("u1", "c")["id"])
        api = str(repo.create("u1", "c", api_key="key")["id"])
        shared = str(repo.create("u1", "c", is_shared_usage=True)["id"])
        own_agent = str(repo.create("u1", "c", agent_id=_agent(pg_conn, "u1"))["id"])
        other_agent = str(repo.create("u1", "c", agent_id=_agent(pg_conn, "u2"))["id"])
        assert auto_resume_allowed(pg_conn, own, "u1") is True
        assert auto_resume_allowed(pg_conn, own, "u1", api_route=True) is False
        assert auto_resume_allowed(pg_conn, own, "someone-else") is False
        assert auto_resume_allowed(pg_conn, api, "u1") is False
        assert auto_resume_allowed(pg_conn, shared, "u1") is False
        assert auto_resume_allowed(pg_conn, own_agent, "u1") is True
        assert auto_resume_allowed(pg_conn, other_agent, "u1") is False

    def test_feature_switch(self, pg_conn, monkeypatch):
        monkeypatch.setattr("docsgpt.background.context.settings.AUTO_RESUME_ENABLED", False)
        own = str(ConversationsRepository(pg_conn).create("u1", "c")["id"])
        assert auto_resume_allowed(pg_conn, own, "u1") is False


class TestBindTurn:
    def _executor(self, **kw):
        return SimpleNamespace(headless=False, workflow_run_id=None, background=None, **kw)

    def test_binds_a_persisted_interactive_turn(self):
        executor = self._executor()
        context = bind_turn(executor, conversation_id="c", message_id="m", decoded_token={"sub": "u"}, agent_id="a")
        assert isinstance(context, BackgroundContext)
        assert executor.background is context
        assert context.origin_message_id == "m"

    def test_skips_what_cannot_hand_off(self, monkeypatch):
        assert bind_turn(self._executor(), conversation_id=None, message_id="m", decoded_token={"sub": "u"}) is None
        assert bind_turn(self._executor(), conversation_id="c", message_id=None, decoded_token={"sub": "u"}) is None
        assert bind_turn(self._executor(), conversation_id="c", message_id="m", decoded_token=None) is None
        headless = SimpleNamespace(headless=True, workflow_run_id=None)
        assert bind_turn(headless, conversation_id="c", message_id="m", decoded_token={"sub": "u"}) is None
        node = SimpleNamespace(headless=False, workflow_run_id="w")
        assert bind_turn(node, conversation_id="c", message_id="m", decoded_token={"sub": "u"}) is None
        monkeypatch.setattr("docsgpt.background.context.settings.BACKGROUND_JOBS_ENABLED", False)
        assert bind_turn(self._executor(), conversation_id="c", message_id="m", decoded_token={"sub": "u"}) is None
