"""The PAT rule table: route classification and enforcement at the Flask chokepoint."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from docsgpt.api.pat import rules
from docsgpt.api.pat.tokens import SCOPES, expand_scopes

AGENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
AGENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SOURCE_A = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SOURCE_B = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _claims(scopes, resource_filter=None):
    return {
        "sub": "alice",
        "auth_method": "pat",
        "pat_id": "t1",
        "pat_name": "ci",
        "scopes": sorted(expand_scopes(scopes)),
        "resource_filter": resource_filter or {},
    }


def _call(client, method, path, claims, **kwargs):
    """Send a request as a PAT; returns the response, short-circuiting the view."""
    with patch("docsgpt.app.handle_auth", return_value=claims):
        return client.open(path, method=method, **kwargs)


def _denied(response):
    """The rule table refused (as opposed to the view answering 4xx itself)."""
    if response.status_code != 403:
        return None
    return (json.loads(response.data) or {}).get("error")


@pytest.mark.unit
class TestClassification:
    def test_every_route_is_classified(self, flask_app):
        unclassified = []
        for url_rule in flask_app.url_map.iter_rules():
            for method in sorted(url_rule.methods - {"HEAD", "OPTIONS"}):
                if (url_rule.rule, method) in rules.RULES:
                    continue
                if rules.is_denied(url_rule.rule, method):
                    continue
                unclassified.append(f"{method} {url_rule.rule}")
        assert not unclassified, (
            "New routes must be given a scope in docsgpt/api/pat/rules.py RULES, "
            f"or listed in DENIED: {unclassified}"
        )

    def test_no_stale_rules(self, flask_app):
        registered = {
            (r.rule, m) for r in flask_app.url_map.iter_rules() for m in r.methods
        }
        assert not [key for key in rules.RULES if key not in registered]
        known_rules = {r.rule for r in flask_app.url_map.iter_rules()}
        assert not [rule for rule in rules.DENIED if rule not in known_rules]

    def test_a_route_is_never_both_allowed_and_denied(self):
        assert not [key for key in rules.RULES if rules.is_denied(*key)]

    def test_rules_only_name_real_scopes(self):
        for key, rule in rules.RULES.items():
            for scope in rule.scopes:
                assert scope in SCOPES, (key, scope)

    @pytest.mark.parametrize(
        "rule,method",
        [
            ("/api/user/tokens", "POST"),
            ("/api/user/tokens", "GET"),
            ("/api/user/tokens/<string:token_id>", "DELETE"),
            ("/api/admin/users", "GET"),
            ("/api/admin/tokens/<string:token_id>", "DELETE"),
            ("/api/generate_token", "GET"),
            ("/api/devices/pairings", "POST"),
            ("/api/connectors/auth", "GET"),
            ("/api/mcp_server/callback", "GET"),
        ],
    )
    def test_sensitive_routes_are_never_token_reachable(self, rule, method):
        assert (rule, method) not in rules.RULES
        assert rules.is_denied(rule, method)


@pytest.mark.unit
class TestScopeEnforcement:
    def test_unlisted_route_is_refused(self, client):
        response = _call(client, "GET", "/api/user/tokens", _claims(list(SCOPES)))
        assert _denied(response) == "not_available_to_tokens"

    def test_admin_routes_are_refused_even_with_every_scope(self, client):
        response = _call(client, "GET", "/api/admin/users", _claims(list(SCOPES)))
        assert _denied(response) == "not_available_to_tokens"

    def test_unknown_path_and_wrong_method_keep_their_own_status(self, client):
        claims = _claims(list(SCOPES))
        assert _call(client, "GET", "/api/no_such_route", claims).status_code == 404
        assert _call(client, "DELETE", "/api/get_agents", claims).status_code == 405

    def test_missing_scope_is_refused_and_names_the_scope(self, client):
        response = _call(client, "GET", "/api/get_agents", _claims(["sources:read"]))
        assert _denied(response) == "insufficient_scope"
        assert json.loads(response.data)["required_scope"] == "agents:read"

    def test_read_scope_cannot_write(self, client):
        response = _call(
            client, "DELETE", f"/api/delete_agent?id={AGENT_A}", _claims(["agents:read"])
        )
        assert _denied(response) == "insufficient_scope"

    def test_write_scope_can_read(self, client):
        response = _call(client, "GET", "/api/get_agents", _claims(["agents:write"]))
        assert _denied(response) is None

    def test_agent_key_regeneration_needs_its_own_scope(self, client):
        response = _call(
            client, "POST", f"/api/regenerate_agent_key/{AGENT_A}", _claims(["agents:write"])
        )
        assert _denied(response) == "insufficient_scope"

    def test_any_token_can_identify_itself(self, client):
        response = _call(client, "GET", "/api/user/me", _claims(["prompts:read"]))
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body["auth_method"] == "pat"
        assert body["token"]["scopes"] == ["prompts:read"]
        assert body["roles"] == ["user"]

    def test_token_never_carries_admin(self, client):
        with patch("docsgpt.app.resolve_roles", return_value=["admin", "user"]) as resolver:
            response = _call(client, "GET", "/api/user/me", _claims(["agents:read"]))
        resolver.assert_not_called()
        assert json.loads(response.data)["roles"] == ["user"]

    def test_session_callers_bypass_the_table(self, client):
        with patch("docsgpt.app.handle_auth", return_value={"sub": "alice"}), patch(
            "docsgpt.app.resolve_roles", return_value=["user"]
        ), patch("docsgpt.app.authorize_pat") as authorize:
            client.get("/api/user/me")
        authorize.assert_not_called()

    def test_invalid_token_is_401(self, client):
        with patch(
            "docsgpt.app.handle_auth",
            return_value={"error": "invalid_token", "message": "Authentication error: invalid token"},
        ):
            assert client.get("/api/get_agents").status_code == 401


@pytest.mark.unit
class TestResourceRestrictions:
    def _restricted(self, scopes, **families):
        return _claims(scopes, resource_filter=families)

    def test_allowed_id_passes_and_other_id_is_refused(self, client):
        claims = self._restricted(["agents:read"], agents=[AGENT_A])
        assert _denied(_call(client, "GET", f"/api/get_agent?id={AGENT_A}", claims)) is None
        assert (
            _denied(_call(client, "GET", f"/api/get_agent?id={AGENT_B}", claims))
            == "resource_not_allowed"
        )

    def test_id_comparison_ignores_case(self, client):
        claims = self._restricted(["agents:read"], agents=[AGENT_A])
        assert _denied(_call(client, "GET", f"/api/get_agent?id={AGENT_A.upper()}", claims)) is None

    def test_view_arg_ids(self, client):
        claims = self._restricted(["agents:write"], agents=[AGENT_A])
        ok = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json={"name": "x"})
        bad = _call(client, "PUT", f"/api/update_agent/{AGENT_B}", claims, json={"name": "x"})
        assert _denied(ok) is None
        assert _denied(bad) == "resource_not_allowed"

    def test_json_body_ids_including_lists(self, client):
        claims = self._restricted(["agents:write"], agents=[AGENT_A])
        ok = _call(client, "POST", "/api/agents/folders/bulk_move", claims, json={"agent_ids": [AGENT_A]})
        bad = _call(
            client, "POST", "/api/agents/folders/bulk_move", claims, json={"agent_ids": [AGENT_A, AGENT_B]}
        )
        assert _denied(ok) is None
        assert _denied(bad) == "resource_not_allowed"

    def test_missing_id_is_refused_for_a_restricted_token(self, client):
        claims = self._restricted(["agents:read"], agents=[AGENT_A])
        assert _denied(_call(client, "GET", "/api/get_agent", claims)) == "resource_not_allowed"

    def test_restricted_token_cannot_create(self, client):
        claims = self._restricted(["agents:write"], agents=[AGENT_A])
        response = _call(client, "POST", "/api/create_agent", claims, json={"name": "new"})
        assert _denied(response) == "resource_not_allowed"

    def test_unrestricted_family_is_untouched(self, client):
        claims = self._restricted(["agents:write", "prompts:write"], agents=[AGENT_A])
        response = _call(client, "POST", "/api/create_prompt", claims, json={})
        assert _denied(response) is None

    def test_cross_family_references_are_checked(self, client):
        claims = self._restricted(["agents:write", "sources:read"], sources=[SOURCE_A])
        ok = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json={"source": SOURCE_A})
        bad = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json={"sources": [SOURCE_A, SOURCE_B]})
        form = _call(
            client, "PUT", f"/api/update_agent/{AGENT_A}", claims,
            data={"sources": json.dumps([SOURCE_B])},
        )
        assert _denied(ok) is None
        assert _denied(bad) == "resource_not_allowed"
        assert _denied(form) == "resource_not_allowed"

    def test_routes_hanging_off_a_restricted_family_are_blocked(self, client):
        claims = self._restricted(["agents:read", "schedules:read", "analytics:read"], agents=[AGENT_A])
        assert _denied(_call(client, "GET", "/api/schedules/s1", claims)) == "resource_not_allowed"
        assert _denied(_call(client, "POST", "/api/get_token_analytics", claims, json={})) == "resource_not_allowed"
        assert _denied(_call(client, "GET", f"/api/agents/{AGENT_A}/schedules", claims)) is None
        assert _denied(_call(client, "GET", f"/api/agents/{AGENT_B}/schedules", claims)) == "resource_not_allowed"

    @pytest.mark.parametrize("family", ["agents", "sources", "prompts", "tools", "workflows"])
    def test_message_tail_is_closed_to_any_restricted_token(self, client, family):
        claims = _claims(["chat:run"], {family: [AGENT_A]})
        assert _denied(_call(client, "GET", "/api/messages/m1/tail", claims)) == "resource_not_allowed"
        assert _denied(_call(client, "GET", "/api/messages/m1/tail", _claims(["chat:run"]))) is None

    def test_sql_paged_listing_is_closed_to_restricted_tokens(self, client):
        claims = self._restricted(["sources:read"], sources=[SOURCE_A])
        assert _denied(_call(client, "GET", "/api/sources/paginated", claims)) == "resource_not_allowed"


WORKFLOW_A = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
TOOL_A = "ffffffff-ffff-ffff-ffff-ffffffffffff"


@pytest.mark.unit
class TestRelationshipsBeyondIds:
    """Rows whose content or parent the table cannot see are closed to restricted tokens."""

    @pytest.mark.parametrize("family", ["sources", "tools", "prompts"])
    def test_workflow_writes_are_closed_to_tokens_restricted_on_what_a_graph_can_name(self, client, family):
        claims = _claims(["workflows:write"], {family: [SOURCE_A]})
        assert _denied(_call(client, "POST", "/api/workflows", claims, json={})) == "resource_not_allowed"
        assert (
            _denied(_call(client, "PUT", f"/api/workflows/{WORKFLOW_A}", claims, json={}))
            == "resource_not_allowed"
        )
        assert _denied(_call(client, "GET", f"/api/workflows/{WORKFLOW_A}", claims)) is None

    def test_workflow_restricted_token_can_still_edit_its_workflows(self, client):
        claims = _claims(["workflows:write"], {"workflows": [WORKFLOW_A]})
        assert _denied(_call(client, "PUT", f"/api/workflows/{WORKFLOW_A}", claims, json={})) is None

    @pytest.mark.parametrize("family", ["sources", "tools", "prompts"])
    def test_agent_cannot_be_pointed_at_a_workflow_by_a_token_restricted_on_its_contents(self, client, family):
        claims = _claims(["agents:write"], {family: [SOURCE_A]})
        for body in ({"workflow": WORKFLOW_A}, {"workflow": {"id": WORKFLOW_A}}):
            response = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json=body)
            assert _denied(response) == "resource_not_allowed"
        form = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, data={"workflow": WORKFLOW_A})
        assert _denied(form) == "resource_not_allowed"
        assert _denied(_call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json={"name": "x"})) is None

    def test_workflow_allowlist_lets_the_agent_use_those_workflows_only(self, client):
        claims = _claims(["agents:write"], {"sources": [SOURCE_A], "workflows": [WORKFLOW_A]})
        ok = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json={"workflow": WORKFLOW_A})
        bad = _call(client, "PUT", f"/api/update_agent/{AGENT_A}", claims, json={"workflow": SOURCE_B})
        assert _denied(ok) is None
        assert _denied(bad) == "resource_not_allowed"

    @pytest.mark.parametrize("family", ["sources", "prompts", "tools", "workflows"])
    def test_schedules_are_closed_to_tokens_restricted_on_anything_but_agents(self, client, family):
        claims = _claims(["schedules:write"], {family: [SOURCE_A]})
        for method, path in (
            ("GET", f"/api/agents/{AGENT_A}/schedules"),
            ("POST", f"/api/agents/{AGENT_A}/schedules"),
            ("GET", "/api/schedules/s1"),
            ("POST", "/api/schedules/s1/run"),
            ("GET", "/api/schedules/s1/runs"),
        ):
            assert _denied(_call(client, method, path, claims, json={})) == "resource_not_allowed", path

    @pytest.mark.parametrize("family", ["agents", "sources", "prompts", "tools", "workflows"])
    def test_conversations_and_analytics_are_closed_to_every_restricted_token(self, client, family):
        claims = _claims(["conversations:write", "analytics:read"], {family: [SOURCE_A]})
        for method, path in (
            ("GET", "/api/get_conversations"),
            ("GET", "/api/get_single_conversation?id=c1"),
            ("GET", "/api/search_conversations?q=x"),
            ("POST", "/api/delete_conversation"),
            ("POST", "/api/feedback"),
            ("POST", "/api/get_message_analytics"),
            ("POST", "/api/get_user_logs"),
        ):
            assert _denied(_call(client, method, path, claims, json={})) == "resource_not_allowed", path


@pytest.mark.unit
class TestAgentKeyVisibility:
    def _request(self, flask_app, claims):
        from flask import request

        ctx = flask_app.test_request_context("/")
        ctx.push()
        request.decoded_token = claims
        return ctx, request

    def test_sessions_and_tokens_with_the_keys_scope_see_the_key(self, flask_app):
        for claims in ({"sub": "alice"}, _claims(["agents:write", "agents:keys"])):
            ctx, request = self._request(flask_app, claims)
            try:
                assert rules.may_see_agent_keys(request) is True
            finally:
                ctx.pop()

    def test_token_without_the_keys_scope_does_not(self, flask_app):
        ctx, request = self._request(flask_app, _claims(["agents:write"]))
        try:
            assert rules.may_see_agent_keys(request) is False
        finally:
            ctx.pop()

    def test_mask(self):
        assert rules.mask_agent_key("12345678-aaaa-bbbb-cccc-1234567890ab") == "1234...90ab"
        assert rules.mask_agent_key("") == "" and rules.mask_agent_key(None) == ""


@pytest.mark.unit
class TestChatRestrictions:
    def _chat(self, client, claims, body):
        return _denied(_call(client, "POST", "/api/answer", claims, json=body))

    def test_unrestricted_token_can_chat_any_way(self, client):
        claims = _claims(["chat:run"])
        assert self._chat(client, claims, {"question": "hi", "api_key": "k"}) is None
        assert self._chat(client, claims, {"question": "hi", "agent_id": AGENT_B}) is None

    def test_agent_restricted_token_must_name_an_allowed_agent(self, client):
        claims = _claims(["chat:run"], {"agents": [AGENT_A]})
        assert self._chat(client, claims, {"question": "hi", "agent_id": AGENT_A}) is None
        assert self._chat(client, claims, {"question": "hi", "agent_id": AGENT_B}) == "resource_not_allowed"
        assert self._chat(client, claims, {"question": "hi"}) == "resource_not_allowed"
        assert self._chat(client, claims, {"question": "hi", "api_key": "k"}) == "resource_not_allowed"

    def test_restricted_token_cannot_run_an_inline_workflow(self, client):
        claims = _claims(["chat:run"], {"agents": [AGENT_A]})
        body = {"question": "hi", "agent_id": AGENT_A, "workflow": {"nodes": []}}
        assert self._chat(client, claims, body) == "resource_not_allowed"

    def test_source_restricted_token_cannot_reach_other_sources_through_an_agent(self, client):
        claims = _claims(["chat:run"], {"sources": [SOURCE_A]})
        assert self._chat(client, claims, {"question": "hi", "active_docs": SOURCE_A}) is None
        assert self._chat(client, claims, {"question": "hi", "active_docs": [SOURCE_A, SOURCE_B]}) == "resource_not_allowed"
        assert self._chat(client, claims, {"question": "hi", "agent_id": AGENT_A}) == "resource_not_allowed"

    @pytest.mark.parametrize("extra", [{}, {"agents": [AGENT_A]}])
    def test_tools_restricted_token_cannot_chat_at_all(self, client, extra):
        claims = _claims(["chat:run"], {"tools": [TOOL_A], **extra})
        assert self._chat(client, claims, {"question": "hi"}) == "resource_not_allowed"
        assert self._chat(client, claims, {"question": "hi", "agent_id": AGENT_A}) == "resource_not_allowed"

    @pytest.mark.parametrize("family", ["prompts", "workflows"])
    def test_agentless_chat_needs_an_agent_restriction_unless_only_sources_are_restricted(self, client, family):
        claims = _claims(["chat:run"], {family: [SOURCE_A]})
        assert self._chat(client, claims, {"question": "hi"}) == "resource_not_allowed"
        assert self._chat(client, claims, {"question": "hi", "agent_id": AGENT_A}) == "resource_not_allowed"

    def test_conversation_must_belong_to_the_agent_being_run(self, client):
        claims = _claims(["chat:run"], {"agents": [AGENT_A]})
        body = {"question": "hi", "agent_id": AGENT_A, "conversation_id": "c1"}
        with patch.object(rules, "_conversation_agent_id", return_value=(True, AGENT_A.upper())) as lookup:
            assert self._chat(client, claims, body) is None
        lookup.assert_called_once_with("c1", "alice")
        for result in ((True, AGENT_B), (True, ""), (False, "")):
            with patch.object(rules, "_conversation_agent_id", return_value=result):
                assert self._chat(client, claims, body) == "resource_not_allowed", result

    def test_conversation_resume_with_tool_actions_is_held_to_the_same_rule(self, client):
        claims = _claims(["chat:run"], {"agents": [AGENT_A]})
        body = {"agent_id": AGENT_A, "conversation_id": "c1", "tool_actions": [{"call_id": "x"}]}
        with patch.object(rules, "_conversation_agent_id", return_value=(True, AGENT_B)):
            assert self._chat(client, claims, body) == "resource_not_allowed"

    def test_agentless_token_cannot_continue_an_agent_conversation(self, client):
        claims = _claims(["chat:run"], {"sources": [SOURCE_A]})
        body = {"question": "hi", "active_docs": SOURCE_A, "conversation_id": "c1"}
        with patch.object(rules, "_conversation_agent_id", return_value=(True, AGENT_B)):
            assert self._chat(client, claims, body) == "resource_not_allowed"
        with patch.object(rules, "_conversation_agent_id", return_value=(True, "")):
            assert self._chat(client, claims, body) is None

    def test_unrestricted_token_never_pays_for_the_conversation_lookup(self, client):
        with patch.object(rules, "_conversation_agent_id") as lookup:
            self._chat(client, _claims(["chat:run"]), {"question": "hi", "conversation_id": "c1"})
        lookup.assert_not_called()

    def test_conversation_lookup_fails_closed(self):
        with patch("docsgpt.storage.db.session.db_readonly", side_effect=RuntimeError("db down")):
            assert rules._conversation_agent_id("c1", "alice") == (False, "")
        assert rules._conversation_agent_id("c1", None) == (False, "")

    def test_retrieval_test_honours_the_source_allowlist(self, client):
        claims = _claims(["chat:run"], {"sources": [SOURCE_A]})
        ok = _call(client, "POST", f"/api/sources/{SOURCE_A}/search", claims, json={"query": "q"})
        bad = _call(client, "POST", f"/api/sources/{SOURCE_B}/search", claims, json={"query": "q"})
        assert _denied(ok) is None
        assert _denied(bad) == "resource_not_allowed"


@pytest.mark.unit
class TestListingFilter:
    def test_unrestricted_and_session_callers_see_everything(self, flask_app):
        from flask import request

        items = [{"id": AGENT_A}, {"id": AGENT_B}]
        with flask_app.test_request_context("/"):
            request.decoded_token = {"sub": "alice"}
            assert rules.filter_listing(request, "agents", items) == items
            request.decoded_token = _claims(["agents:read"])
            assert rules.filter_listing(request, "agents", items) == items

    def test_restricted_token_sees_only_its_rows_plus_builtin_presets(self, flask_app):
        from flask import request

        items = [{"id": AGENT_A}, {"id": AGENT_B}, {"id": "default"}]
        with flask_app.test_request_context("/"):
            request.decoded_token = _claims(["prompts:read"], {"prompts": [AGENT_A]})
            assert rules.filter_listing(request, "prompts", items) == [{"id": AGENT_A}, {"id": "default"}]
            assert rules.allowed_ids(request, "agents") is None
            assert rules.allowed_ids(request, "prompts") == {AGENT_A}
