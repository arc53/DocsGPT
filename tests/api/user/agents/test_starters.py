"""Agent starters: the questions a new chat with an agent offers.

The owner or an editor writes them (create, draft and update, JSON or the
multipart form's JSON string); everyone who can open a chat with the agent
reads them, from the single-agent GET and from every agent list. They travel
in the export file. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import json

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.agents.starters import (
    MAX_STARTER_LENGTH,
    StartersError,
    normalize_starters,
    stored_starters,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from tests.api.user.agents.test_roles_access import (
    EDITOR,
    OWNER,
    STRANGER,
    VIEWER,
    _agent,
    _call,
    _json,
    _patch_db,
    _status,
)

STARTERS = ["Run due diligence on a new vendor", "Which contracts renew this quarter?"]


@pytest.fixture
def app():
    return Flask(__name__)


def _form_call(app, conn, resource_cls, method, path, user, form, *, args=()):
    """Call a route with a multipart body, as the agent form sends it."""
    with _patch_db(conn), app.test_request_context(
        path, method=method.upper(), data=form, content_type="multipart/form-data"
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method.lower())(*args)


def _starters(conn, agent_id) -> list:
    return AgentsRepository(conn).get_by_id(str(agent_id))["starters"]


def _create(app, conn, user, **body):
    from docsgpt.api.user.agents.routes import CreateAgent

    payload = {"name": "Bot", "description": "d", "agent_type": "classic", "status": "draft", **body}
    return _call(app, conn, CreateAgent, "post", "/api/create_agent", user, json=payload)


def _update(app, conn, user, agent_id, body):
    from docsgpt.api.user.agents.routes import UpdateAgent

    return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user,
                 json=body, args=(str(agent_id),))


def _get(app, conn, user, agent_id):
    from docsgpt.api.user.agents.routes import GetAgent

    return _call(app, conn, GetAgent, "get", f"/api/get_agent?id={agent_id}", user)


# ---------------------------------------------------------------------------
# normalize_starters
# ---------------------------------------------------------------------------


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, []),
            ("", []),
            ([], []),
            (["  Hi?  ", "", "   ", "Next"], ["Hi?", "Next"]),
            (["Hi?", "hi?", " HI? ", "Other"], ["Hi?", "Other"]),
            ('["a", "b"]', ["a", "b"]),
            (["a", "b", "c", "d", "A", ""], ["a", "b", "c", "d"]),
            (["x" * MAX_STARTER_LENGTH], ["x" * MAX_STARTER_LENGTH]),
            ([" " + "x" * MAX_STARTER_LENGTH + " "], ["x" * MAX_STARTER_LENGTH]),
            (["\tHi?\r\n", "Two\nlines\tand a tab"], ["Hi?", "Two\nlines\tand a tab"]),
        ],
    )
    def test_cleans(self, raw, expected):
        assert normalize_starters(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ("not json", "must be a list"),
            ('{"a": 1}', "must be a list"),
            ({"a": 1}, "must be a list"),
            (7, "must be a list"),
            (["ok", 3], "must be text"),
            (["ok", None], "must be text"),
            (["x" * (MAX_STARTER_LENGTH + 1)], "at most 200 characters"),
            (["a", "b", "c", "d", "e"], "at most 4 starters"),
            (["\x00hi"], "control characters"),
            (["hi\x00"], "control characters"),
            (["ok", "a\x07b"], "control characters"),
            (["a\x1bb"], "control characters"),
            (["a\x7fb"], "control characters"),
            (["a\ud800b"], "unpaired surrogate"),
            ('["\\udfff"]', "unpaired surrogate"),
        ],
    )
    def test_rejects(self, raw, message):
        with pytest.raises(StartersError, match=message):
            normalize_starters(raw)

    def test_stored_starters_tolerates_odd_rows(self):
        assert stored_starters({}) == []
        assert stored_starters({"starters": None}) == []
        assert stored_starters({"starters": {"a": 1}}) == []
        assert stored_starters({"starters": ["a", 1, "b"]}) == ["a", "b"]


# ---------------------------------------------------------------------------
# create / update / get
# ---------------------------------------------------------------------------


class TestCreate:
    def test_json_list_round_trips_through_get(self, app, pg_conn):
        response = _create(app, pg_conn, "s-create", starters=[" A? ", "a?", "", "B?"])
        assert _status(response) == 201, _json(response)
        agent_id = _json(response)["id"]
        assert _starters(pg_conn, agent_id) == ["A?", "B?"]
        assert _json(_get(app, pg_conn, "s-create", agent_id))["starters"] == ["A?", "B?"]

    def test_multipart_json_string(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import CreateAgent

        form = {"name": "Bot", "description": "d", "status": "draft", "starters": json.dumps(STARTERS)}
        response = _form_call(app, pg_conn, CreateAgent, "post", "/api/create_agent", "s-create-form", form)
        assert _status(response) == 201, _json(response)
        assert _starters(pg_conn, _json(response)["id"]) == STARTERS

    def test_published_agent_keeps_them(self, app, pg_conn):
        response = _create(
            app, pg_conn, "s-create-pub", status="published", chunks="2", retriever="classic",
            prompt_id="default", starters=STARTERS,
        )
        assert _status(response) == 201, _json(response)
        assert _starters(pg_conn, _json(response)["id"]) == STARTERS

    def test_workflow_draft_keeps_them(self, app, pg_conn):
        response = _create(app, pg_conn, "s-create-wf", agent_type="workflow", starters=STARTERS)
        assert _status(response) == 201, _json(response)
        assert _starters(pg_conn, _json(response)["id"]) == STARTERS

    def test_none_sent_is_empty(self, app, pg_conn):
        response = _create(app, pg_conn, "s-create-none")
        assert _status(response) == 201
        assert _starters(pg_conn, _json(response)["id"]) == []
        assert _json(_get(app, pg_conn, "s-create-none", _json(response)["id"]))["starters"] == []

    @pytest.mark.parametrize(
        ("starters", "message"),
        [
            (["a", "b", "c", "d", "e"], "An agent can have at most 4 starters"),
            (["x" * 201], "A starter can be at most 200 characters"),
            (["ok", 5], "Each starter must be text"),
            ("not json", "Starters must be a list of questions"),
            ({"a": "b"}, "Starters must be a list of questions"),
        ],
    )
    def test_rejects_with_a_clear_message(self, app, pg_conn, starters, message):
        user = "s-create-bad"
        response = _create(app, pg_conn, user, starters=starters)
        assert _status(response) == 400
        assert _json(response)["message"] == message
        assert AgentsRepository(pg_conn).list_for_user(user) == []


class TestUpdate:
    def test_owner_sets_cleans_and_clears(self, app, pg_conn):
        agent = AgentsRepository(pg_conn).create("s-upd", "a", "draft", description="d")
        response = _update(app, pg_conn, "s-upd", agent["id"], {"starters": [" One ", "one", "Two"]})
        assert _status(response) == 200, _json(response)
        assert _starters(pg_conn, agent["id"]) == ["One", "Two"]
        assert _status(_update(app, pg_conn, "s-upd", agent["id"], {"starters": []})) == 200
        assert _starters(pg_conn, agent["id"]) == []

    def test_a_save_without_starters_keeps_them(self, app, pg_conn):
        agent = AgentsRepository(pg_conn).create("s-upd-keep", "a", "draft", description="d", starters=STARTERS)
        assert _status(_update(app, pg_conn, "s-upd-keep", agent["id"], {"name": "Renamed"})) == 200
        assert _starters(pg_conn, agent["id"]) == STARTERS

    def test_multipart_json_string(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent

        agent = AgentsRepository(pg_conn).create("s-upd-form", "a", "draft", description="d")
        form = {"name": "a", "description": "d", "status": "draft", "starters": json.dumps(STARTERS)}
        response = _form_call(app, pg_conn, UpdateAgent, "put", f"/api/update_agent/{agent['id']}",
                              "s-upd-form", form, args=(str(agent["id"]),))
        assert _status(response) == 200, _json(response)
        assert _starters(pg_conn, agent["id"]) == STARTERS

    def test_multipart_bad_json_is_400(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent

        agent = AgentsRepository(pg_conn).create("s-upd-badform", "a", "draft", description="d", starters=STARTERS)
        response = _form_call(app, pg_conn, UpdateAgent, "put", f"/api/update_agent/{agent['id']}",
                              "s-upd-badform", {"starters": "[oops"}, args=(str(agent["id"]),))
        assert _status(response) == 400
        assert _starters(pg_conn, agent["id"]) == STARTERS

    @pytest.mark.parametrize(
        ("starters", "message"),
        [
            (["a", "b", "c", "d", "e"], "An agent can have at most 4 starters"),
            (["x" * 201], "A starter can be at most 200 characters"),
            ([["nested"]], "Each starter must be text"),
            ("a question", "Starters must be a list of questions"),
            (["\u0000hi"], "A starter can't contain control characters"),
        ],
    )
    def test_rejects_and_keeps_the_stored_ones(self, app, pg_conn, starters, message):
        agent = AgentsRepository(pg_conn).create("s-upd-bad", "a", "draft", description="d", starters=STARTERS)
        response = _update(app, pg_conn, "s-upd-bad", agent["id"], {"starters": starters})
        assert _status(response) == 400
        assert _json(response)["message"] == message
        assert _starters(pg_conn, agent["id"]) == STARTERS

    def test_a_starters_change_moves_the_stale_write_token(self, app, pg_conn):
        agent = AgentsRepository(pg_conn).create("s-upd-stale", "a", "draft", description="d")
        stale = "2020-01-01T00:00:00+00:00"
        pg_conn.execute(
            text("UPDATE agents SET updated_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": stale, "id": str(agent["id"])},
        )
        body = {"starters": STARTERS, "expected_updated_at": stale}
        assert _status(_update(app, pg_conn, "s-upd-stale", agent["id"], body)) == 200
        # The builder's copy from before the save is now stale.
        response = _update(app, pg_conn, "s-upd-stale", agent["id"], {"starters": [], "expected_updated_at": stale})
        assert _status(response) == 409
        assert _starters(pg_conn, agent["id"]) == STARTERS


class TestAccess:
    def test_editor_changes_them(self, app, pg_conn):
        agent_id = _agent(pg_conn)
        assert _status(_update(app, pg_conn, EDITOR, agent_id, {"starters": STARTERS})) == 200
        assert _starters(pg_conn, agent_id) == STARTERS

    def test_viewer_and_stranger_cannot(self, app, pg_conn):
        agent_id = _agent(pg_conn, starters=STARTERS)
        assert _status(_update(app, pg_conn, VIEWER, agent_id, {"starters": []})) == 403
        assert _status(_update(app, pg_conn, STRANGER, agent_id, {"starters": []})) == 404
        assert _starters(pg_conn, agent_id) == STARTERS

    @pytest.mark.parametrize("user", [OWNER, EDITOR, VIEWER])
    def test_everyone_who_sees_the_agent_reads_them(self, app, pg_conn, user):
        agent_id = _agent(pg_conn, starters=STARTERS, config={"guardrails": {"enabled": True}})
        data = _json(_get(app, pg_conn, user, agent_id))
        assert data["starters"] == STARTERS
        if user == VIEWER:
            # Unlike the guardrail config, which a chat-only caller doesn't get.
            assert data["config"] == {}


# ---------------------------------------------------------------------------
# list payloads (the chat sets its agent from these)
# ---------------------------------------------------------------------------


class TestLists:
    def test_get_agents_owned_and_team(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgents

        shared_id = _agent(pg_conn, starters=STARTERS)
        own = AgentsRepository(pg_conn).create(EDITOR, "Mine", "draft")
        rows = {r["id"]: r for r in _json(_call(app, pg_conn, GetAgents, "get", "/api/get_agents", EDITOR))}
        assert rows[shared_id]["starters"] == STARTERS
        assert rows[str(own["id"])]["starters"] == []

    def test_pinned_agents(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import PinAgent, PinnedAgents

        agent_id = _agent(pg_conn, starters=STARTERS)
        bare_id = _agent(pg_conn, key="bare1234abcd")
        for aid in (agent_id, bare_id):
            assert _status(_call(app, pg_conn, PinAgent, "post", f"/api/pin_agent?id={aid}", VIEWER)) == 200
        rows = {r["id"]: r for r in _json(_call(app, pg_conn, PinnedAgents, "get", "/api/pinned_agents", VIEWER))}
        assert rows[agent_id]["starters"] == STARTERS
        assert rows[bare_id]["starters"] == []

    def test_shared_link_payload_and_shared_with_me_list(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import SharedAgent, SharedAgents

        agent_id = _agent(pg_conn, share=False, starters=STARTERS)
        AgentsRepository(pg_conn).update(agent_id, OWNER, {"shared": True, "shared_token": "tok-starters"})
        data = _json(_call(app, pg_conn, SharedAgent, "get", "/api/shared_agent?token=tok-starters", STRANGER))
        assert data["starters"] == STARTERS
        rows = _json(_call(app, pg_conn, SharedAgents, "get", "/api/shared_agents", STRANGER))
        assert rows[0]["starters"] == STARTERS

    def test_shared_link_payload_without_starters_is_empty(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import SharedAgent

        agent_id = _agent(pg_conn, share=False)
        AgentsRepository(pg_conn).update(agent_id, OWNER, {"shared": True, "shared_token": "tok-bare"})
        data = _json(_call(app, pg_conn, SharedAgent, "get", "/api/shared_agent?token=tok-bare", None))
        assert data["starters"] == []

    def test_folder_listing(self, app, pg_conn):
        from docsgpt.api.user.agents.folders import AgentFolder
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder = AgentFoldersRepository(pg_conn).create(OWNER, "F")
        agent_id = _agent(pg_conn, share=False, starters=STARTERS, folder_id=str(folder["id"]))
        data = _json(_call(app, pg_conn, AgentFolder, "get", f"/api/agents/folders/{folder['id']}", OWNER,
                           args=(str(folder["id"]),)))
        assert {a["id"]: a for a in data["agents"]}[agent_id]["starters"] == STARTERS

    def test_templates_list_and_adopt(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import AdoptAgent, GetTemplateAgents

        template = AgentsRepository(pg_conn).create("__system__", "Tpl", "template", description="d",
                                                    starters=STARTERS)
        rows = _json(_call(app, pg_conn, GetTemplateAgents, "get", "/api/template_agents", "s-adopter"))
        assert {r["id"]: r for r in rows}[str(template["id"])]["starters"] == STARTERS
        response = _call(app, pg_conn, AdoptAgent, "post", f"/api/adopt_agent?id={template['id']}", "s-adopter")
        assert _status(response) == 200, _json(response)
        assert AgentsRepository(pg_conn).list_for_user("s-adopter")[0]["starters"] == STARTERS


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------


class TestPortability:
    def test_export_and_import_round_trip(self, pg_conn):
        from docsgpt.api.user.agents.portability import (
            agent_to_yaml,
            apply_import,
            parse_agent_yaml,
            serialize_agent,
        )

        user = "s-port"
        agent = AgentsRepository(pg_conn).create(user, "Bot", "draft", description="d", starters=STARTERS)
        export = serialize_agent(pg_conn, AgentsRepository(pg_conn).get(str(agent["id"]), user), user)
        assert export["spec"]["starters"] == STARTERS
        doc = parse_agent_yaml(agent_to_yaml(export))
        doc["metadata"] = {}
        result = apply_import(pg_conn, f"{user}-importer", doc)
        assert result["action"] == "created"
        assert _starters(pg_conn, result["agent_id"]) == STARTERS

    def test_import_without_the_key_gets_none_and_clears_on_update(self, pg_conn):
        from docsgpt.api.user.agents.portability import (
            API_VERSION,
            apply_import,
            ensure_agent_slug,
            parse_agent_yaml,
        )

        user = "s-port-missing"
        created = apply_import(pg_conn, user, parse_agent_yaml(
            f"apiVersion: {API_VERSION}\nkind: Agent\nmetadata: {{}}\nspec:\n  name: Fresh\n"
        ))
        assert _starters(pg_conn, created["agent_id"]) == []

        agent = AgentsRepository(pg_conn).create(user, "Bot", "draft", description="d", starters=STARTERS)
        slug = ensure_agent_slug(pg_conn, agent, user)
        doc = parse_agent_yaml(
            f"apiVersion: {API_VERSION}\nkind: Agent\nmetadata:\n  slug: {slug}\nspec:\n  name: Bot\n"
        )
        assert apply_import(pg_conn, user, doc)["action"] == "updated"
        assert _starters(pg_conn, agent["id"]) == []

    def test_import_cleans_and_rejects_like_the_routes(self, pg_conn):
        from docsgpt.api.user.agents.portability import API_VERSION, AgentImportError, parse_agent_yaml

        head = f"apiVersion: {API_VERSION}\nkind: Agent\nspec:\n  name: Bot\n  starters:\n"
        doc = parse_agent_yaml(head + "    - ' Hi? '\n    - hi?\n    - ''\n")
        assert doc["spec"]["starters"] == ["Hi?"]
        with pytest.raises(AgentImportError, match="at most 4 starters"):
            parse_agent_yaml(head + "".join(f"    - q{i}\n" for i in range(5)))
        with pytest.raises(AgentImportError, match="must be text"):
            parse_agent_yaml(head + "    - 7\n")
        with pytest.raises(AgentImportError, match="control characters"):
            parse_agent_yaml(head + '    - "\\0hi"\n')

    def test_export_route_writes_them(self, app, pg_conn):
        from docsgpt.api.user.agents.portability import ExportAgent

        agent = AgentsRepository(pg_conn).create("s-port-route", "Bot", "draft", description="d", starters=STARTERS)
        response = _call(app, pg_conn, ExportAgent, "get", f"/api/export_agent?id={agent['id']}", "s-port-route")
        assert _status(response) == 200
        body = response.get_data(as_text=True)
        assert "starters:" in body and STARTERS[0] in body
