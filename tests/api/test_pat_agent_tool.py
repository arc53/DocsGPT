"""An API tool made from a new token: POST /api/user/tokens/<id>/tool."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from docsgpt.agents.tool_executor import api_tool_action_with_secrets
from docsgpt.api.pat.agent_tool import CATALOG, build_actions
from tests.api.test_pat_routes import AGENT_A, _create, _policy, _session, client, db  # noqa: F401

BASE = "https://docs.example.com"


def _make_tool(client, token: str, token_id: str, sub: str = "alice", base_url: str = BASE):
    with _session(sub=sub):
        return client.post(
            f"/api/user/tokens/{token_id}/tool", json={"token": token, "base_url": base_url}
        )


def _new_token(client, **body):
    created = json.loads(_create(client, **body).data)
    return created["token"], created["personal_access_token"]["id"]


class TestBuildActions:
    def test_scopes_pick_the_actions(self):
        actions = build_actions(BASE, "dgpt_pat_x", ["analytics:read"], {})
        assert sorted(actions) == ["get_feedback_counts", "get_logs", "get_message_counts", "get_trace"]
        assert actions["get_logs"]["url"] == f"{BASE}/api/get_user_logs"
        assert actions["get_logs"]["headers"]["properties"]["Authorization"]["value"] == "Bearer dgpt_pat_x"

    def test_a_restricted_token_gets_only_what_it_may_call(self):
        actions = build_actions(BASE, "t", ["agents:read", "analytics:read"], {"agents": [AGENT_A]})
        assert sorted(actions) == ["list_agents"]

    def test_every_catalog_entry_is_a_pat_route(self):
        from docsgpt.api.pat.rules import RULES

        for _name, method, path, *_rest in CATALOG:
            assert (path, method) in RULES

    def test_every_action_is_read_only(self):
        for _name, method, path, *_rest in CATALOG:
            from docsgpt.api.pat.rules import RULES

            assert all(scope.endswith(":read") for scope in RULES[(path, method)].scopes)


class TestCreateTool:
    def test_creates_an_api_tool_with_the_token_sealed(self, client, db):
        token, token_id = _new_token(client, name="analyst", scopes=["analytics:read", "conversations:read"])

        response = _make_tool(client, token, token_id)
        assert response.status_code == 201
        body = json.loads(response.data)
        assert "get_conversation" in body["actions"] and "get_logs" in body["actions"]
        assert "list_agents" not in body["actions"]

        row = db.execute(
            text("SELECT * FROM user_tools WHERE id = CAST(:id AS uuid)"), {"id": body["id"]}
        ).mappings().one()
        assert row["user_id"] == "alice"
        assert row["name"] == "api_tool"
        assert row["custom_name"] == "DocsGPT API (analyst)"
        stored = json.dumps(row["config"])
        assert token not in stored
        header = row["config"]["actions"]["get_logs"]["headers"]["properties"]["Authorization"]
        assert header["value"] == "" and header["has_value"] is True
        action = api_tool_action_with_secrets(dict(row), "get_logs", "alice")
        assert action["headers"]["properties"]["Authorization"]["value"] == f"Bearer {token}"

    def test_a_token_with_nothing_an_agent_reads_is_refused(self, client, db):
        token, token_id = _new_token(client, scopes=["chat:run"])
        response = _make_tool(client, token, token_id)
        assert response.status_code == 400

    def test_the_secret_must_match_the_token(self, client, db):
        token, token_id = _new_token(client, scopes=["analytics:read"])
        other, _ = _new_token(client, name="other", scopes=["analytics:read"])
        assert _make_tool(client, other, token_id).status_code == 404
        assert _make_tool(client, token + "x", token_id).status_code == 404

    def test_another_users_token_is_not_found(self, client, db):
        token, token_id = _new_token(client, scopes=["analytics:read"])
        assert _make_tool(client, token, token_id, sub="bob").status_code == 404

    @pytest.mark.parametrize("base_url", ["", "docs.example.com", "ftp://docs.example.com", None])
    def test_base_url_must_be_http(self, client, db, base_url):
        token, token_id = _new_token(client, scopes=["analytics:read"])
        assert _make_tool(client, token, token_id, base_url=base_url).status_code == 400

    def test_requires_a_session(self, client, db):
        response = client.post(f"/api/user/tokens/{AGENT_A}/tool", json={"token": "t", "base_url": BASE})
        assert response.status_code == 401
