"""The data-plane routes must leave an audit trail.

Identity events were audited from the start; source/agent/conversation
mutations were not, so "who deleted that source" had no answer. These pin the
hooks at the route layer — the repositories are mocked, what is asserted is
that the audit row is written with the acting user and the resource id.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _authed(module: str, **patches):
    """Authenticate as ``u1`` and patch names inside ``module``."""
    recorded: list[tuple] = []

    def _record(_conn, event, *, actor, target=None, **metadata):
        recorded.append((event, actor, target, metadata))

    @contextmanager
    def _conn():
        yield MagicMock()

    with ExitStack() as stack:
        stack.enter_context(
            patch("docsgpt.app.handle_auth", return_value={"sub": "u1"})
        )
        stack.enter_context(patch("docsgpt.app.resolve_roles", return_value=["user"]))
        stack.enter_context(patch(f"{module}.db_session", _conn))
        stack.enter_context(patch(f"{module}.db_readonly", _conn))
        stack.enter_context(patch(f"{module}.record_event", _record))
        for name, value in patches.items():
            stack.enter_context(patch(f"{module}.{name}", value))
        yield recorded


_SOURCES = "docsgpt.api.user.sources.routes"
_AGENTS = "docsgpt.api.user.agents.routes"
_CONVERSATIONS = "docsgpt.api.user.conversations.routes"


@pytest.mark.unit
class TestSourceAudit:
    def test_delete_records_source_deleted(self, client):
        repo = Mock()
        repo.get_any.return_value = {"id": "src-1", "name": "Handbook"}
        storage = Mock()
        storage.file_exists.return_value = False
        with _authed(
            _SOURCES,
            SourcesRepository=Mock(return_value=repo),
            StorageCreator=Mock(get_storage=Mock(return_value=storage)),
        ) as recorded:
            resp = client.get("/api/delete_old?source_id=src-1")
        assert resp.status_code == 200
        assert recorded[0][:3] == ("source.deleted", "u1", None)
        assert recorded[0][3]["source_id"] == "src-1"
        assert recorded[0][3]["name"] == "Handbook"

    def test_nothing_recorded_when_the_source_is_missing(self, client):
        repo = Mock()
        repo.get_any.return_value = None
        with _authed(_SOURCES, SourcesRepository=Mock(return_value=repo)) as recorded:
            resp = client.get("/api/delete_old?source_id=nope")
        assert resp.status_code == 404
        assert recorded == []


_UPLOAD = "docsgpt.api.user.sources.upload"


@pytest.mark.unit
class TestRemoteSourceAudit:
    """``source.deleted`` is recorded for remote sources, so creation must be.

    A trail showing a source deleted that was apparently never created is
    worse than no trail, and the docs state ``source.created`` is recorded.
    """

    @contextmanager
    def _remote_env(self):
        recorded: list[tuple] = []

        def _record(_conn, event, *, actor, target=None, **metadata):
            recorded.append((event, actor, target, metadata))

        @contextmanager
        def _conn():
            yield MagicMock()

        task = Mock(id="task-9")
        with ExitStack() as stack:
            stack.enter_context(
                patch("docsgpt.app.handle_auth", return_value={"sub": "u1"})
            )
            stack.enter_context(
                patch("docsgpt.app.resolve_roles", return_value=["user"])
            )
            stack.enter_context(patch(f"{_UPLOAD}.db_session", _conn))
            stack.enter_context(patch(f"{_UPLOAD}.record_event", _record))
            stack.enter_context(
                patch(
                    f"{_UPLOAD}.ingest_remote",
                    Mock(apply_async=Mock(return_value=task)),
                )
            )
            yield recorded

    def test_url_source_records_source_created(self, client):
        # The route reads ``request.form``; ``data`` is a JSON string.
        with self._remote_env() as recorded:
            resp = client.post(
                "/api/remote",
                data={
                    "user": "u1",
                    "source": "url",
                    "name": "Handbook",
                    "data": json.dumps({"url": "https://example.com"}),
                },
            )
        assert resp.status_code == 200
        assert [row[0] for row in recorded] == ["source.created"]
        event, actor, target, metadata = recorded[0]
        assert (actor, target) == ("u1", None)
        assert metadata["name"] == "Handbook"
        assert metadata["type"] == "url"
        assert metadata["source_id"] == json.loads(resp.data)["source_id"]

    def test_github_source_records_source_created(self, client):
        with self._remote_env() as recorded:
            resp = client.post(
                "/api/remote",
                data={
                    "user": "u1",
                    "source": "github",
                    "name": "Repo",
                    "data": json.dumps({"repo_url": "https://github.com/a/b"}),
                },
            )
        assert resp.status_code == 200
        assert recorded[0][3]["type"] == "github"


@pytest.mark.unit
class TestAgentAudit:
    def test_delete_records_agent_deleted(self, client):
        repo = Mock()
        repo.get_any.return_value = {
            "id": "agent-1",
            "name": "Support bot",
            "agent_type": "classic",
        }
        with _authed(
            _AGENTS,
            AgentsRepository=Mock(return_value=repo),
            WorkflowsRepository=Mock(),
            UsersRepository=Mock(),
        ) as recorded:
            resp = client.delete("/api/delete_agent?id=agent-1")
        assert resp.status_code == 200
        assert recorded[0][:3] == ("agent.deleted", "u1", None)
        assert recorded[0][3]["agent_id"] == "agent-1"
        assert recorded[0][3]["name"] == "Support bot"

    def test_missing_agent_records_nothing(self, client):
        repo = Mock()
        repo.get_any.return_value = None
        with _authed(_AGENTS, AgentsRepository=Mock(return_value=repo)) as recorded:
            assert client.delete("/api/delete_agent?id=x").status_code == 404
        assert recorded == []


@pytest.mark.unit
class TestConversationAudit:
    def test_delete_records_conversation_deleted(self, client):
        repo = Mock()
        repo.get_any.return_value = {"id": "conv-1"}
        with _authed(
            _CONVERSATIONS, ConversationsRepository=Mock(return_value=repo)
        ) as recorded:
            resp = client.post("/api/delete_conversation?id=conv-1")
        assert resp.status_code == 200
        assert recorded[0][:3] == ("conversation.deleted", "u1", None)
        assert recorded[0][3]["conversation_id"] == "conv-1"

    def test_delete_all_records_the_count(self, client):
        repo = Mock()
        repo.delete_all_for_user.return_value = 7
        with _authed(
            _CONVERSATIONS, ConversationsRepository=Mock(return_value=repo)
        ) as recorded:
            resp = client.get("/api/delete_all_conversations")
        assert resp.status_code == 200
        assert recorded[0][0] == "conversation.deleted_all"
        assert recorded[0][3]["deleted"] == 7

    def test_unknown_conversation_records_nothing(self, client):
        repo = Mock()
        repo.get_any.return_value = None
        with _authed(
            _CONVERSATIONS, ConversationsRepository=Mock(return_value=repo)
        ) as recorded:
            assert client.post("/api/delete_conversation?id=x").status_code == 200
        assert recorded == []
