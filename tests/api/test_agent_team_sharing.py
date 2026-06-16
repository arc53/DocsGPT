"""Endpoint tests for agent team-sharing paths.

Covers the GET /api/get_agent read/fallback + name-resolution paths and the
PUT /api/update_agent team-editor save-gate.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _cm(value):
    yield value


def _patches(sub, repo, team_access, *, prompt_name="Resolved Prompt", source_details=None):
    if source_details is None:
        source_details = []
    return [
        patch("application.app.handle_auth", return_value={"sub": sub}),
        patch("application.app.resolve_roles", return_value=["user"]),
        patch("application.api.user.agents.routes.db_readonly", lambda: _cm(Mock())),
        patch("application.api.user.agents.routes.AgentsRepository", return_value=repo),
        patch("application.api.user.agents.routes.team_access_for", return_value=team_access),
        # Resolve names by id (owner-agnostic) — patched so the test never
        # touches the DB; the route is what we're asserting wires them in.
        patch(
            "application.api.user.agents.routes.resolve_prompt_name",
            return_value=prompt_name,
        ),
        patch(
            "application.api.user.agents.routes.resolve_source_details",
            return_value=source_details,
        ),
    ]


def _run(patches, client, agent_id):
    for p in patches:
        p.start()
    try:
        return client.get(f"/api/get_agent?id={agent_id}")
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.mark.unit
class TestGetAgentTeamFallback:
    def test_owner_sees_own_agent(self, client):
        aid = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = {"id": aid, "name": "Mine", "status": "published"}
        resp = _run(_patches("alice", repo, None), client, aid)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ownership"] == "user"
        assert data["team_access"] is None
        repo.get_by_id.assert_not_called()

    def test_team_member_sees_shared_agent(self, client):
        aid = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = None  # not the owner
        repo.get_by_id.return_value = {
            "id": aid,
            "name": "Shared",
            "status": "published",
            # Owner secrets that must NOT leak to a team grantee.
            "shared_token": "secret-public-token",
            "key": "agentkey1234567890",
        }
        resp = _run(_patches("bob", repo, "viewer"), client, aid)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ownership"] == "team"
        assert data["team_access"] == "viewer"
        # Owner's public share token / API key are blanked for grantees.
        assert data["shared_token"] == ""
        assert data.get("key", "") == ""
        # get_by_id only reached AFTER the team grant check.
        repo.get_by_id.assert_called_once_with(aid)

    def test_no_access_returns_404(self, client):
        aid = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = None
        resp = _run(_patches("stranger", repo, None), client, aid)
        assert resp.status_code == 404
        repo.get_by_id.assert_not_called()


@pytest.mark.unit
class TestGetAgentResolvesNames:
    """GET /api/get_agent embeds owner-agnostic prompt/source names so a team
    grantee sees the owner's prompt name + source names rather than a blank
    prompt / "External KB" (the client can't resolve the owner's resources)."""

    def test_team_member_payload_has_resolved_names(self, client):
        aid = str(uuid.uuid4())
        src = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = None  # not the owner
        repo.get_by_id.return_value = {
            "id": aid,
            "name": "Shared",
            "status": "published",
            "prompt_id": str(uuid.uuid4()),
            "source_id": src,
        }
        details = [{"id": src, "name": "Owner KB"}]
        resp = _run(
            _patches(
                "bob", repo, "editor",
                prompt_name="Owner Prompt", source_details=details,
            ),
            client,
            aid,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ownership"] == "team"
        assert data["prompt_name"] == "Owner Prompt"
        assert data["source_details"] == details

    def test_owner_payload_also_has_resolved_names(self, client):
        aid = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = {
            "id": aid,
            "name": "Mine",
            "status": "published",
            "prompt_id": "default",
        }
        resp = _run(
            _patches("alice", repo, None, prompt_name="Default", source_details=[]),
            client,
            aid,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["ownership"] == "user"
        assert data["prompt_name"] == "Default"
        assert data["source_details"] == []


def _update_patches(sub, repo, team_access, can_access_mock):
    return [
        patch("application.app.handle_auth", return_value={"sub": sub}),
        patch("application.app.resolve_roles", return_value=["user"]),
        patch("application.api.user.agents.routes.db_session", lambda: _cm(Mock())),
        patch("application.api.user.agents.routes.AgentsRepository", return_value=repo),
        patch("application.api.user.agents.routes.team_access_for", return_value=team_access),
        patch("application.api.user.agents.routes.can_access", can_access_mock),
    ]


def _run_update(patches, client, agent_id, body):
    for p in patches:
        p.start()
    try:
        return client.put(f"/api/update_agent/{agent_id}", json=body)
    finally:
        for p in reversed(patches):
            p.stop()


def _shared_agent_row(aid, owner_src, owner_prompt):
    return {
        "id": aid,
        "name": "Shared",
        "description": "desc",
        "status": "draft",
        "source_id": owner_src,
        "extra_source_ids": [],
        "prompt_id": owner_prompt,
        "tools": [],
        "chunks": 2,
        "agent_type": "classic",
        "image": "",
    }


@pytest.mark.unit
class TestUpdateAgentEditorSaveGate:
    """PUT /api/update_agent: a team EDITOR may save an agent while keeping the
    owner's existing source/prompt (which aren't independently shared with
    them), but must not ATTACH a new source/prompt they can't access."""

    def test_editor_keeps_owner_source_and_prompt(self, client):
        aid, owner_src, owner_prompt = (
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        )
        repo = Mock()
        repo.get_any.return_value = None  # not the owner
        repo.get_by_id.return_value = _shared_agent_row(aid, owner_src, owner_prompt)
        repo.update_by_id.return_value = {"id": aid}
        # Editor holds NO independent grant on the source/prompt themselves.
        can_access = Mock(return_value=False)
        resp = _run_update(
            _update_patches("editor-bob", repo, "editor", can_access),
            client,
            aid,
            {
                "name": "Shared",
                "description": "desc",
                "source": owner_src,
                "prompt_id": owner_prompt,
            },
        )
        assert resp.status_code == 200
        # Unchanged refs are exempt — the access check is never consulted.
        can_access.assert_not_called()
        repo.update_by_id.assert_called_once()

    def test_editor_cannot_attach_new_unshared_source(self, client):
        aid, owner_src, owner_prompt = (
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        )
        new_src = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = None
        repo.get_by_id.return_value = _shared_agent_row(aid, owner_src, owner_prompt)
        repo.update_by_id.return_value = {"id": aid}
        can_access = Mock(return_value=False)
        resp = _run_update(
            _update_patches("editor-bob", repo, "editor", can_access),
            client,
            aid,
            {"name": "Shared", "description": "desc", "sources": [new_src]},
        )
        assert resp.status_code == 403
        assert "Source not accessible" in json.loads(resp.data)["message"]
        repo.update_by_id.assert_not_called()

    def test_editor_cannot_attach_new_unshared_prompt(self, client):
        aid, owner_src, owner_prompt = (
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        )
        new_prompt = str(uuid.uuid4())
        repo = Mock()
        repo.get_any.return_value = None
        repo.get_by_id.return_value = _shared_agent_row(aid, owner_src, owner_prompt)
        repo.update_by_id.return_value = {"id": aid}
        can_access = Mock(return_value=False)
        resp = _run_update(
            _update_patches("editor-bob", repo, "editor", can_access),
            client,
            aid,
            {
                "name": "Shared",
                "description": "desc",
                "source": owner_src,
                "prompt_id": new_prompt,
            },
        )
        assert resp.status_code == 403
        assert "Prompt not accessible" in json.loads(resp.data)["message"]
        repo.update_by_id.assert_not_called()
