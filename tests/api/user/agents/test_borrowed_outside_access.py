"""Someone else's tool or source never goes out through a key, a link or a webhook.

An agent runs as its owner, so a tool or source the owner reaches only through
a team grant ("borrowed") reaches everyone who can run the agent. An API key
(and the widget on it), a public link and an incoming webhook reach people the
item's owner never shared with, so an agent that uses a borrowed item gets
none of them, and a borrowed item can't be added to an agent that has one.
Using it in one's own agent and chats stays allowed. Uses real repositories on
``pg_conn``.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.api.user.resource_access import (
    CODE_BORROWED_RESOURCE,
    borrowed_refs,
    set_settings,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

OWNER, LENDER, EDITOR = "bo-owner", "bo-lender", "bo-editor"

_DB_MODULES = (
    "docsgpt.api.user.agents.routes",
    "docsgpt.api.user.agents.sharing",
    "docsgpt.api.user.agents.webhooks",
    "docsgpt.api.user.workflows.routes",
    "docsgpt.api.user.sharing.routes",
    "docsgpt.api.user.folder_knowledge",
    "docsgpt.api.user.base",
)


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    import importlib

    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for mod_name in _DB_MODULES:
            mod = importlib.import_module(mod_name)
            for attr in ("db_session", "db_readonly"):
                if hasattr(mod, attr):
                    stack.enter_context(patch(f"{mod_name}.{attr}", _yield))
        yield


def _call(app, conn, resource_cls, method, path, user, *, json=None, args=(), query=None):
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    if query is not None:
        kwargs["query_string"] = query
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method.lower())(*args)


def _status(resp) -> int:
    return resp[1] if isinstance(resp, tuple) else resp.status_code


def _json(resp):
    return resp[0] if isinstance(resp, tuple) else resp.get_json()


def _lend(conn, resource_type, resource_id, to=OWNER):
    """LENDER shares their item with ``to`` as a viewer, through a team."""
    team = TeamsRepository(conn).create("Lenders", f"t-{uuid.uuid4().hex[:8]}", LENDER)
    for member in (LENDER, to):
        TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, resource_id, LENDER, LENDER, access_level="viewer", target_user_id=to,
    )


def _lent_tool(conn):
    tid = str(UserToolsRepository(conn).create(LENDER, "api_tool", custom_name="Lender CRM")["id"])
    _lend(conn, "tool", tid)
    return tid


def _lent_source(conn):
    sid = str(SourcesRepository(conn).create("Lender handbook", user_id=LENDER)["id"])
    _lend(conn, "source", sid)
    return sid


def _own_tool(conn, owner=OWNER):
    return str(UserToolsRepository(conn).create(owner, "api_tool", custom_name="Mine")["id"])


def _agent(conn, *, status="published", key=None, **extra):
    extra.setdefault("agent_type", "classic")
    extra.setdefault("chunks", 6)
    row = AgentsRepository(conn).create(OWNER, "Bot", status, description="d", key=key, **extra)
    return str(row["id"])


def _row(conn, agent_id):
    return AgentsRepository(conn).get_by_id(agent_id)


def _assert_borrowed_refusal(resp, *names):
    assert _status(resp) == 403, _json(resp)
    body = _json(resp)
    assert body["success"] is False
    for name in names:
        assert name in body["message"]
    return body


class TestBorrowedRefs:
    def test_lent_tool_and_source_are_borrowed(self, pg_conn):
        tool, source = _lent_tool(pg_conn), _lent_source(pg_conn)
        own = _own_tool(pg_conn)
        found = borrowed_refs(pg_conn, OWNER, [("tool", tool), ("source", source), ("tool", own)])
        assert set(found) == {("tool", tool), ("source", source)}

    def test_an_item_the_owner_cant_use_is_not_borrowed(self, pg_conn):
        # An editor's own tool on the owner's agent runs as its sponsor: the
        # sponsor flow, which confirms the agent's audience, owns that case.
        editors = _own_tool(pg_conn, owner=EDITOR)
        assert borrowed_refs(pg_conn, OWNER, [("tool", editors)]) == []

    def test_a_folder_feeds_its_borrowed_sources(self, pg_conn):
        source = _lent_source(pg_conn)
        folder = str(FoldersRepository(pg_conn).create(OWNER, "Mixed", resource_type="source")["id"])
        FolderItemsRepository(pg_conn).file(OWNER, "source", source, folder)
        assert borrowed_refs(pg_conn, OWNER, [], [folder]) == [("source", source)]


class TestPublicLink:
    def _share(self, app, conn, agent_id, user=OWNER):
        from docsgpt.api.user.agents.sharing import ShareAgent

        return _call(app, conn, ShareAgent, "put", "/api/share_agent", user, json={"id": agent_id, "shared": True})

    def test_refused_with_a_borrowed_tool(self, app, pg_conn):
        agent_id = _agent(pg_conn, tools=[_lent_tool(pg_conn)])
        body = _assert_borrowed_refusal(self._share(app, pg_conn, agent_id), "Lender CRM", LENDER)
        assert body["code"] == CODE_BORROWED_RESOURCE
        assert not _row(pg_conn, agent_id).get("shared")

    def test_allowed_with_own_items(self, app, pg_conn):
        agent_id = _agent(pg_conn, tools=[_own_tool(pg_conn)])
        assert _status(self._share(app, pg_conn, agent_id)) == 200
        assert _row(pg_conn, agent_id)["shared"] is True

    def test_an_existing_link_can_still_be_replaced(self, app, pg_conn):
        # Rotating a link the agent already has opens nothing new.
        agent_id = _agent(pg_conn, tools=[_lent_tool(pg_conn)], shared=True, shared_token=f"s-{uuid.uuid4().hex}")
        assert _status(self._share(app, pg_conn, agent_id)) == 200

    def test_refused_for_a_workflow_node_source(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import _write_graph

        from tests.api.user.test_resource_sponsors import _wf_body

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        body = _wf_body(source=_lent_source(pg_conn))
        _write_graph(pg_conn, str(wf["id"]), 1, body["nodes"], body["edges"])
        agent_id = _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        _assert_borrowed_refusal(self._share(app, pg_conn, agent_id), "Lender handbook")


class TestWebhook:
    def _webhook(self, app, conn, agent_id):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        return _call(app, conn, AgentWebhook, "get", "/api/agent_webhook", OWNER, query={"id": agent_id})

    def test_new_webhook_refused(self, app, pg_conn):
        agent_id = _agent(pg_conn, source_id=_lent_source(pg_conn))
        _assert_borrowed_refusal(self._webhook(app, pg_conn, agent_id), "Lender handbook")
        assert not _row(pg_conn, agent_id).get("incoming_webhook_token")

    def test_existing_webhook_is_still_returned(self, app, pg_conn):
        token = f"w-{uuid.uuid4().hex}"
        agent_id = _agent(pg_conn, source_id=_lent_source(pg_conn), incoming_webhook_token=token)
        resp = self._webhook(app, pg_conn, agent_id)
        assert _status(resp) == 200
        assert _json(resp)["webhook_url"].endswith(token)


class TestApiKey:
    def _regenerate(self, app, conn, agent_id):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey

        return _call(app, conn, RegenerateAgentKey, "post", f"/api/regenerate_agent_key/{agent_id}", OWNER,
                     args=(agent_id,))

    def _create(self, app, conn, body):
        from docsgpt.api.user.agents.routes import CreateAgent

        base = {"name": "Bot", "description": "d", "agent_type": "classic", "status": "published", "chunks": 6,
                "retriever": "classic", "prompt_id": "default"}
        return _call(app, conn, CreateAgent, "post", "/api/create_agent", OWNER, json={**base, **body})

    def _put(self, app, conn, agent_id, body):
        from docsgpt.api.user.agents.routes import UpdateAgent

        return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", OWNER, json=body,
                     args=(agent_id,))

    def test_publishing_with_a_borrowed_tool_mints_no_key(self, app, pg_conn):
        # Publishing keeps the agent usable in its owner's own chats; it only
        # gets no key for people outside.
        resp = self._create(app, pg_conn, {"tools": [_lent_tool(pg_conn)]})
        assert _status(resp) == 201, _json(resp)
        agent_id = _json(resp)["id"]
        assert _json(resp)["key"] == ""
        row = _row(pg_conn, agent_id)
        assert row["status"] == "published"
        assert not row.get("key")

    def test_publishing_with_own_items_mints_a_key(self, app, pg_conn):
        resp = self._create(app, pg_conn, {"tools": [_own_tool(pg_conn)]})
        assert _status(resp) == 201, _json(resp)
        assert _row(pg_conn, _json(resp)["id"]).get("key")

    def test_publishing_a_draft_with_a_borrowed_source_mints_no_key(self, app, pg_conn):
        agent_id = _agent(pg_conn, status="draft", source_id=_lent_source(pg_conn))
        resp = self._put(app, pg_conn, agent_id, {"status": "published"})
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, agent_id)
        assert row["status"] == "published"
        assert not row.get("key")
        assert "key" not in _json(resp)

    def test_first_key_refused_with_a_borrowed_tool(self, app, pg_conn):
        agent_id = _agent(pg_conn, tools=[_lent_tool(pg_conn)])
        _assert_borrowed_refusal(self._regenerate(app, pg_conn, agent_id), "Lender CRM")
        assert not _row(pg_conn, agent_id).get("key")

    def test_an_existing_key_can_still_be_rotated(self, app, pg_conn):
        agent_id = _agent(pg_conn, tools=[_lent_tool(pg_conn)], key=f"k-{uuid.uuid4().hex}")
        assert _status(self._regenerate(app, pg_conn, agent_id)) == 200


class TestAttach:
    def _put(self, app, conn, agent_id, body, user=OWNER):
        from docsgpt.api.user.agents.routes import UpdateAgent

        return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user, json=body,
                     args=(agent_id,))

    def test_borrowed_tool_refused_on_an_agent_with_a_key(self, app, pg_conn):
        agent_id = _agent(pg_conn, key=f"k-{uuid.uuid4().hex}")
        tool = _lent_tool(pg_conn)
        _assert_borrowed_refusal(self._put(app, pg_conn, agent_id, {"tools": [tool]}), "Lender CRM", LENDER)
        assert not _row(pg_conn, agent_id).get("tools")

    def test_borrowed_source_refused_on_an_agent_with_a_webhook(self, app, pg_conn):
        agent_id = _agent(pg_conn, status="draft", incoming_webhook_token=f"w-{uuid.uuid4().hex}")
        source = _lent_source(pg_conn)
        _assert_borrowed_refusal(self._put(app, pg_conn, agent_id, {"sources": [source]}), "Lender handbook")

    def test_borrowed_tool_allowed_on_an_agent_nobody_reaches_from_outside(self, app, pg_conn):
        agent_id = _agent(pg_conn, status="draft")
        tool = _lent_tool(pg_conn)
        assert _status(self._put(app, pg_conn, agent_id, {"tools": [tool]})) == 200
        assert [str(t) for t in _row(pg_conn, agent_id)["tools"]] == [tool]

    def test_an_agent_already_published_with_one_still_saves(self, app, pg_conn):
        tool = _lent_tool(pg_conn)
        agent_id = _agent(pg_conn, tools=[tool], key=f"k-{uuid.uuid4().hex}")
        resp = self._put(app, pg_conn, agent_id, {"name": "Renamed", "tools": [tool]})
        assert _status(resp) == 200, _json(resp)

    def test_folder_with_a_borrowed_source_refused_on_an_agent_with_a_key(self, app, pg_conn):
        source = _lent_source(pg_conn)
        folder = str(FoldersRepository(pg_conn).create(OWNER, "Mixed", resource_type="source")["id"])
        FolderItemsRepository(pg_conn).file(OWNER, "source", source, folder)
        agent_id = _agent(pg_conn, key=f"k-{uuid.uuid4().hex}")
        _assert_borrowed_refusal(self._put(app, pg_conn, agent_id, {"folders": [folder]}), "Lender handbook")

    def test_workflow_node_tool_refused_when_its_agent_has_a_key(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        from tests.api.user.test_resource_sponsors import _wf_body

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        wid = str(wf["id"])
        _agent(pg_conn, agent_type="workflow", workflow_id=wid, key=f"k-{uuid.uuid4().hex}")
        resp = _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", OWNER,
                     json=_wf_body(tool=_lent_tool(pg_conn)), args=(wid,))
        _assert_borrowed_refusal(resp, "Lender CRM")


class TestPromptableConversationShare:
    def _share(self, app, conn, source):
        from docsgpt.api.user.sharing.routes import ShareConversation

        conv = ConversationsRepository(conn).create(OWNER, "Billing")
        return _call(app, conn, ShareConversation, "post", "/api/share", OWNER,
                     json={"conversation_id": str(conv["id"]), "source": source},
                     query={"isPromptable": "true"})

    def test_refused_with_a_borrowed_source(self, app, pg_conn):
        _assert_borrowed_refusal(self._share(app, pg_conn, _lent_source(pg_conn)), "Lender handbook")

    def test_allowed_with_an_own_source(self, app, pg_conn):
        source = str(SourcesRepository(pg_conn).create("Mine", user_id=OWNER)["id"])
        assert _status(self._share(app, pg_conn, source)) == 201


class TestEditorsDontManageAccessDetailsByDefault:
    def _editor_agent(self, conn):
        agent_id = _agent(conn)
        team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", OWNER)
        TeamMembersRepository(conn).add_member(str(team["id"]), EDITOR)
        TeamResourceGrantsRepository(conn).grant(
            str(team["id"]), "agent", agent_id, OWNER, OWNER, access_level="editor", target_user_id=EDITOR,
        )
        return agent_id

    def _share(self, app, conn, agent_id):
        from docsgpt.api.user.agents.sharing import ShareAgent

        return _call(app, conn, ShareAgent, "put", "/api/share_agent", EDITOR, json={"id": agent_id, "shared": True})

    def test_editor_cannot_make_a_public_link_by_default(self, app, pg_conn):
        agent_id = self._editor_agent(pg_conn)
        assert _status(self._share(app, pg_conn, agent_id)) == 403

    def test_editor_can_once_the_owner_allows_it(self, app, pg_conn):
        agent_id = self._editor_agent(pg_conn)
        set_settings(pg_conn, "agent", agent_id, {"editors_can_manage_access_details": True}, OWNER)
        assert _status(self._share(app, pg_conn, agent_id)) == 200
