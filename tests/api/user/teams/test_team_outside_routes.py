"""A team's outside policy, its items shared with whole other teams, and what each side reads about them.

Ops (alice owner, adam admin, eddie editor, vera viewer) owns an agent, a source, a tool and a prompt. Dev
(dora owner, dan admin, rita viewer; adam, eddie and vera are Viewers there too) receives shares; QA (quinn
owner; adam and rita Viewers) is a third team. Who may take Ops' items outside follows Ops' policy: its Admins
and Owner, Editors too, or nobody once locked, and only the Owner unlocks. A share goes to the whole team at
Viewer level, from someone in both teams, and outlives whoever made it. Driven through the real app.py
chokepoint against real Postgres; only ``handle_auth`` / ``resolve_roles`` are patched, and the modules'
sessions are pointed at the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from tests.workspaces.move_support import agent, prompt, source, team, tool

KINDS = ("agent", "source", "tool", "prompt")
_MAKERS = {"agent": agent, "source": source, "tool": tool, "prompt": prompt}


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in (
            "docsgpt.api.user.teams.routes.db_readonly",
            "docsgpt.api.user.teams.routes.db_session",
            "docsgpt.api.user.teams.outside.db_readonly",
            "docsgpt.api.user.teams.outside.db_session",
            "docsgpt.api.user.teams.usage.db_readonly",
            "docsgpt.api.user.team_authz.db_readonly",
            "docsgpt.api.user.workspaces.routes.db_readonly",
            "docsgpt.quotas.service.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        stack.enter_context(patch("docsgpt.api.user.teams.routes.publish_user_event"))
        yield pg_conn


@pytest.fixture
def world(db):
    ops, ops_p = team(db)
    dev, dev_p = team(db, owner="dora", name="Dev", members=(
        ("dan", "team_admin"), ("rita", "team_viewer"), ("adam", "team_viewer"), ("eddie", "team_viewer"),
        ("vera", "team_viewer"),
    ))
    qa, qa_p = team(db, owner="quinn", name="QA", members=(("adam", "team_viewer"), ("rita", "team_viewer")))
    items = {kind: _MAKERS[kind](db, ops_p) for kind in KINDS}
    return {"ops": ops, "ops_p": ops_p, "dev": dev, "dev_p": dev_p, "qa": qa, "qa_p": qa_p, "items": items}


@contextmanager
def _as(sub, *roles):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles) or ["user"]
    ):
        yield


def _body(resp):
    return json.loads(resp.data)


def _policy(conn, team_id, policy):
    conn.execute(text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id})


def _stored_policy(conn, team_id):
    return conn.execute(text("SELECT outside_policy FROM teams WHERE id = CAST(:t AS uuid)"), {"t": team_id}).scalar()


def _events(conn, event):
    return conn.execute(
        text("SELECT metadata FROM auth_events WHERE event = :e ORDER BY id"), {"e": event}
    ).scalars().all()


def _set_policy(client, team_id, user, policy, *roles):
    with _as(user, *roles):
        return client.put(f"/api/teams/{team_id}/outside_policy", json={"policy": policy})


def _share(client, w, kind, user="adam", into="dev", **extra):
    with _as(user):
        return client.post(
            f"/api/teams/{w[into]}/grants",
            json={"resource_type": kind, "resource_id": w["items"][kind], **extra},
        )


def _unshare(client, w, kind, user, into="dev"):
    with _as(user):
        return client.delete(
            f"/api/teams/{w[into]}/grants?resource_type={kind}&resource_id={w['items'][kind]}"
        )


def _row(conn, w, kind, into="dev"):
    return TeamItemSharesRepository(conn).get(w[into], kind, w["items"][kind])


def _leave(conn, team_id, user):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user}
    )


class TestPolicy:
    def test_an_admin_changes_it_and_it_is_audited(self, client, db, world):
        resp = _set_policy(client, world["ops"], "adam", "editors")
        assert resp.status_code == 200, resp.data
        body = _body(resp)
        assert body["outside_policy"] == "editors" and body["changed"] is True
        assert body["can_set_outside_policy"] is True
        assert _stored_policy(db, world["ops"]) == "editors"
        (event,) = _events(db, "team.outside_policy_changed")
        assert event["before"] == "admins" and event["after"] == "editors" and event["team_id"] == world["ops"]

    def test_the_same_policy_again_changes_nothing(self, client, db, world):
        resp = _set_policy(client, world["ops"], "adam", "admins")
        assert resp.status_code == 200 and _body(resp)["changed"] is False
        assert _events(db, "team.outside_policy_changed") == []

    @pytest.mark.parametrize("user", ["eddie", "vera"])
    def test_below_admin_is_refused(self, client, db, world, user):
        resp = _set_policy(client, world["ops"], user, "editors")
        assert resp.status_code == 403
        assert _body(resp)["error"] == "workspace_role_required"
        assert _stored_policy(db, world["ops"]) == "admins"

    def test_only_the_owner_unlocks(self, client, db, world):
        assert _set_policy(client, world["ops"], "adam", "locked").status_code == 200
        for policy in ("admins", "editors"):
            resp = _set_policy(client, world["ops"], "adam", policy)
            assert resp.status_code == 403
            assert _body(resp)["error"] == "policy_owner_only"
        assert _stored_policy(db, world["ops"]) == "locked"
        resp = _set_policy(client, world["ops"], "alice", "admins")
        assert resp.status_code == 200 and _stored_policy(db, world["ops"]) == "admins"

    def test_an_admin_of_a_locked_team_reads_that_they_cannot_set_it(self, client, db, world):
        _policy(db, world["ops"], "locked")
        with _as("adam"):
            teams = {t["id"]: t for t in _body(client.get("/api/teams"))["teams"]}
        assert teams[world["ops"]]["outside_policy"] == "locked"
        assert teams[world["ops"]]["can_set_outside_policy"] is False
        with _as("alice"):
            teams = {t["id"]: t for t in _body(client.get("/api/teams"))["teams"]}
        assert teams[world["ops"]]["can_set_outside_policy"] is True

    def test_someone_outside_the_team_gets_404_instance_admin_too(self, client, db, world):
        assert _set_policy(client, world["ops"], "dora", "locked").status_code == 404
        assert _set_policy(client, world["ops"], "root", "locked", "admin").status_code == 404
        assert _stored_policy(db, world["ops"]) == "admins"

    @pytest.mark.parametrize("bad", ["nobody", "", None, 3])
    def test_an_unknown_policy_is_400(self, client, db, world, bad):
        resp = _set_policy(client, world["ops"], "alice", bad)
        assert resp.status_code == 400
        assert _stored_policy(db, world["ops"]) == "admins"

    def test_a_token_can_never_change_it(self):
        from docsgpt.api.pat.rules import DENIED, RULES

        path = "/api/teams/<string:team_id>/outside_policy"
        assert DENIED.get(path) == ("*",)
        assert (path, "PUT") not in RULES
        assert RULES[("/api/teams/<string:team_id>/outside", "GET")].scopes == ("teams:read",)


class TestPayloads:
    def test_team_rows_carry_the_policy_and_who_may_set_it(self, client, db, world):
        _policy(db, world["ops"], "editors")
        expected = {"alice": True, "adam": True, "eddie": False, "vera": False}
        for user, can in expected.items():
            with _as(user):
                teams = {t["id"]: t for t in _body(client.get("/api/teams"))["teams"]}
                one = _body(client.get(f"/api/teams/{world['ops']}"))["team"]
            assert teams[world["ops"]]["outside_policy"] == "editors"
            assert teams[world["ops"]]["can_set_outside_policy"] is can
            assert one["outside_policy"] == "editors" and one["can_set_outside_policy"] is can

    def test_workspace_rows_carry_them_too(self, client, db, world):
        _policy(db, world["ops"], "locked")
        with _as("adam"):
            rows = {w["id"]: w for w in _body(client.get("/api/workspaces"))["workspaces"]}
        assert rows[world["ops"]]["outside_policy"] == "locked"
        assert rows[world["ops"]]["can_set_outside_policy"] is False
        assert rows[world["dev"]]["outside_policy"] == "admins"
        assert rows[world["dev"]]["can_set_outside_policy"] is False  # a Viewer there
        assert "outside_policy" not in rows["personal"]


class TestShare:
    @pytest.mark.parametrize("kind", KINDS)
    def test_an_admin_in_both_teams_shares_each_kind(self, client, db, world, kind):
        resp = _share(client, world, kind)
        assert resp.status_code == 201, resp.data
        row = _row(db, world, kind)
        assert row["owner_team_id"] == world["ops"] and row["shared_by"] == "adam"
        (event,) = _events(db, "team.item_shared_with_team")
        assert event == {
            "team_id": world["ops"], "to_team_id": world["dev"], "resource_type": kind,
            "resource_id": world["items"][kind],
        }

    def test_the_receiving_team_is_told(self, client, db, world):
        with patch("docsgpt.api.user.teams.routes.publish_user_event") as publish:
            assert _share(client, world, "source").status_code == 201
        told = {call.args[0] for call in publish.call_args_list}
        assert told == {"dora", "dan", "rita", "eddie", "vera"}  # Dev, but not the sharer

    def test_sharing_again_keeps_the_first_share(self, client, db, world):
        assert _share(client, world, "prompt").status_code == 201
        TeamMembersRepository(db).add_member(world["dev"], "alice", role="team_viewer")
        resp = _share(client, world, "prompt", user="alice")
        assert resp.status_code == 200 and _body(resp)["share"]["created"] is False
        assert _row(db, world, "prompt")["shared_by"] == "adam"
        assert len(_events(db, "team.item_shared_with_team")) == 1

    def test_an_editor_only_under_editors_too(self, client, db, world):
        resp = _share(client, world, "source", user="eddie")
        assert resp.status_code == 403 and _body(resp)["error"] == "workspace_role_required"
        assert _row(db, world, "source") is None
        _policy(db, world["ops"], "editors")
        assert _share(client, world, "source", user="eddie").status_code == 201

    def test_a_viewer_never(self, client, db, world):
        _policy(db, world["ops"], "editors")
        assert _share(client, world, "tool", user="vera").status_code == 403
        assert _row(db, world, "tool") is None

    def test_locked_refuses_everyone_the_owner_too(self, client, db, world):
        _policy(db, world["ops"], "locked")
        TeamMembersRepository(db).add_member(world["dev"], "alice", role="team_viewer")
        for user in ("alice", "adam"):
            resp = _share(client, world, "agent", user=user)
            assert resp.status_code == 403 and _body(resp)["error"] == "team_locked"
        assert _row(db, world, "agent") is None

    def test_the_sharer_must_be_in_the_receiving_team(self, client, db, world):
        _leave(db, world["dev"], "adam")
        resp = _share(client, world, "source")
        assert resp.status_code == 403 and _body(resp)["error"] == "team_share_not_member"
        assert _row(db, world, "source") is None

    def test_not_with_its_own_team(self, client, db, world):
        resp = _share(client, world, "source", into="ops")
        assert resp.status_code == 400 and _body(resp)["error"] == "team_share_same_team"
        assert _row(db, world, "source", into="ops") is None

    def test_the_whole_team_only(self, client, db, world):
        resp = _share(client, world, "source", target_user_id="rita")
        assert resp.status_code == 400 and _body(resp)["error"] == "team_share_whole_team_only"
        assert _row(db, world, "source") is None

    def test_viewer_level_only(self, client, db, world):
        resp = _share(client, world, "source", access_level="editor")
        assert resp.status_code == 400 and _body(resp)["error"] == "team_share_viewer_only"
        assert _row(db, world, "source") is None

    def test_someone_who_cannot_see_it_gets_404(self, client, db, world):
        TeamMembersRepository(db).add_member(world["dev"], "zed", role="team_admin")
        assert _share(client, world, "source", user="zed").status_code == 404
        assert _row(db, world, "source") is None

    def test_the_receiving_team_cannot_share_it_on(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        TeamMembersRepository(db).add_member(world["qa"], "dan", role="team_viewer")
        resp = _share(client, world, "source", user="dan", into="qa")
        assert resp.status_code == 403
        assert _row(db, world, "source", into="qa") is None

    def test_an_agent_using_an_item_shared_into_its_team_cannot_be_shared_on(self, client, db, world):
        # QA shares its source with Ops; Ops' agent uses it; Ops can't pass the agent on to Dev.
        qa_source = source(db, world["qa_p"], name="QA notes")
        TeamItemSharesRepository(db).share(world["qa"], world["ops"], "source", qa_source, "quinn")
        AgentsRepository(db).update(world["items"]["agent"], world["ops_p"], {"source_id": qa_source})
        resp = _share(client, world, "agent")
        assert resp.status_code == 403, resp.data
        body = _body(resp)
        assert body["code"] == "borrowed_resource"
        assert [r["id"] for r in body["resources"]] == [qa_source]
        assert _row(db, world, "agent") is None


class TestRevoke:
    def test_an_owning_admin_revokes_while_locked(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        _policy(db, world["ops"], "locked")
        resp = _unshare(client, world, "source", "adam")
        assert resp.status_code == 200 and _body(resp)["success"] is True
        assert _row(db, world, "source") is None
        (event,) = _events(db, "team.item_unshared_from_team")
        assert event["side"] == "owner" and event["to_team_id"] == world["dev"] and event["team_id"] == world["ops"]

    def test_an_owning_editor_under_editors_too_only(self, client, db, world):
        assert _share(client, world, "tool").status_code == 201
        assert _unshare(client, world, "tool", "eddie").status_code == 403
        assert _row(db, world, "tool") is not None
        _policy(db, world["ops"], "editors")
        assert _unshare(client, world, "tool", "eddie").status_code == 200
        assert _row(db, world, "tool") is None

    @pytest.mark.parametrize("user", ["dan", "dora"])
    def test_a_receiving_admin_removes_it_from_their_team(self, client, db, world, user):
        assert _share(client, world, "prompt").status_code == 201
        resp = _unshare(client, world, "prompt", user)
        assert resp.status_code == 200 and _body(resp)["success"] is True
        assert _row(db, world, "prompt") is None
        (event,) = _events(db, "team.item_unshared_from_team")
        assert event["side"] == "receiver"

    def test_a_receiving_viewer_cannot(self, client, db, world):
        assert _share(client, world, "agent").status_code == 201
        assert _unshare(client, world, "agent", "rita").status_code == 403
        assert _row(db, world, "agent") is not None

    def test_the_sharer_after_leaving_the_owning_team_cannot(self, client, db, world):
        assert _share(client, world, "agent").status_code == 201
        _leave(db, world["ops"], "adam")
        assert _unshare(client, world, "agent", "adam").status_code == 403
        assert _row(db, world, "agent") is not None

    def test_someone_in_neither_team_gets_404(self, client, db, world):
        assert _share(client, world, "agent").status_code == 201
        assert _unshare(client, world, "agent", "quinn").status_code == 404
        assert _unshare(client, world, "agent", "root").status_code == 404
        assert _row(db, world, "agent") is not None

    def test_the_share_survives_the_sharer_being_removed(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        with _as("alice"):
            assert client.delete(f"/api/teams/{world['ops']}/members/adam").status_code == 200
        assert _row(db, world, "source") is not None


class TestOutsideList:
    def _get(self, client, w, user, team_key="ops"):
        with _as(user):
            return client.get(f"/api/teams/{w[team_key]}/outside")

    def test_every_member_reads_it_and_only_some_revoke(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        for user, can in (("vera", False), ("eddie", False), ("adam", True), ("alice", True)):
            resp = self._get(client, world, user)
            assert resp.status_code == 200, resp.data
            body = _body(resp)
            assert body["outside_policy"] == "admins"
            (row,) = body["shares"]
            assert row["resource_type"] == "source" and row["resource_id"] == world["items"]["source"]
            assert row["resource_name"] == "Docs"
            assert row["team_id"] == world["dev"] and row["name"] == "Dev"
            assert row["shared_by"] == {"user_id": "adam", "label": "adam@example.com"}
            assert row["can_revoke"] is can and row["paused_reason"] is None

    def test_a_locked_teams_shares_read_as_paused(self, client, db, world):
        assert _share(client, world, "tool").status_code == 201
        _policy(db, world["ops"], "locked")
        (row,) = _body(self._get(client, world, "adam"))["shares"]
        assert row["paused_reason"] == "team_locked" and row["can_revoke"] is True

    def test_used_by_count_counts_the_receiving_teams_agents(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        for name in ("A", "B"):
            agent(db, world["dev_p"], name=name, source_id=world["items"]["source"])
        agent(db, "rita", name="Rita's own", source_id=world["items"]["source"])
        (row,) = _body(self._get(client, world, "vera"))["shares"]
        assert row["used_by_count"] == 2

    def test_agents_with_outside_access_are_listed(self, client, db, world):
        AgentsRepository(db).update(world["items"]["agent"], world["ops_p"], {"key": "k-1", "access_payer_id": "adam"})
        body = _body(self._get(client, world, "vera"))
        (row,) = body["published"]
        assert row["agent_id"] == world["items"]["agent"] and row["name"] == "Helper"
        assert row["outside_access"]["api_key"] is True
        assert row["outside_access"]["paid_by"] is None  # a Viewer doesn't read who pays
        (row,) = _body(self._get(client, world, "adam"))["published"]
        assert row["outside_access"]["paid_by"]["user_id"] == "adam"

    def test_a_row_naming_an_item_the_team_does_not_own_is_left_out(self, client, db, world):
        # A forced or stale row: QA's source, said to be shared by Ops.
        qa_source = source(db, world["qa_p"], name="QA notes")
        TeamItemSharesRepository(db).share(world["ops"], world["dev"], "source", qa_source, "adam")
        assert _body(self._get(client, world, "adam"))["shares"] == []
        with _as("dan"):
            grants = _body(client.get(f"/api/teams/{world['dev']}/grants"))["grants"]
        assert [g for g in grants if g["origin"] == "team_shared"] == []

    @pytest.mark.parametrize("user", ["dora", "quinn"])
    def test_someone_outside_the_team_gets_404(self, client, db, world, user):
        assert _share(client, world, "source").status_code == 201
        assert self._get(client, world, user).status_code == 404


class TestReceivingTeamsGrantList:
    def _grants(self, client, w, user, team_key="dev"):
        with _as(user):
            return client.get(f"/api/teams/{w[team_key]}/grants")

    def test_incoming_shares_are_listed_with_where_they_come_from(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        for user, can in (("rita", False), ("dan", True)):
            body = _body(self._grants(client, world, user))
            (row,) = [g for g in body["grants"] if g["origin"] == "team_shared"]
            assert row["resource_type"] == "source" and row["resource_id"] == world["items"]["source"]
            assert row["resource_name"] == "Docs"
            assert row["shared_from"] == {"team_id": world["ops"], "name": "Ops"}
            assert row["access_level"] == "viewer" and row["target_user_id"] is None
            assert row["paused_reason"] is None and row["can_revoke"] is can
            assert row["caller"]["origin"] == "team_shared"

    def test_each_row_names_the_teams_agents_that_stop_with_it(self, client, db, world):
        assert _share(client, world, "tool").status_code == 201
        used = agent(db, world["dev_p"], name="Uses it", tools=[world["items"]["tool"]])
        agent(db, world["dev_p"], name="Does not")
        (row,) = [g for g in _body(self._grants(client, world, "dan"))["grants"] if g["origin"] == "team_shared"]
        assert row["used_by"] == [{"id": used, "name": "Uses it"}]

    def test_a_locked_owner_pauses_them(self, client, db, world):
        assert _share(client, world, "agent").status_code == 201
        _policy(db, world["ops"], "locked")
        (row,) = [g for g in _body(self._grants(client, world, "rita"))["grants"] if g["origin"] == "team_shared"]
        assert row["paused_reason"] == "team_locked" and row["caller"] is None

    def test_the_owning_teams_list_does_not_show_them(self, client, db, world):
        assert _share(client, world, "agent").status_code == 201
        grants = _body(self._grants(client, world, "alice", team_key="ops"))["grants"]
        assert [g for g in grants if g["origin"] == "team_shared"] == []


class TestShareDialog:
    def _dialog(self, client, w, kind, user):
        with _as(user):
            return client.get(f"/api/resource_shares?resource_type={kind}&resource_id={w['items'][kind]}")

    def test_the_owning_team_reads_its_shares_and_targets(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        body = _body(self._dialog(client, world, "source", "adam"))
        assert body["outside_policy"] == "admins"
        (share,) = body["outside_shares"]
        assert share["team_id"] == world["dev"] and share["name"] == "Dev"
        assert share["shared_by"]["user_id"] == "adam" and share["can_revoke"] is True
        assert share["used_by_count"] == 0
        assert body["share_targets"] == [{"team_id": world["qa"], "name": "QA"}]  # Dev has it already
        assert body["warning_kind"] == "source"

    def test_a_viewer_reads_the_shares_but_gets_no_targets(self, client, db, world):
        assert _share(client, world, "source").status_code == 201
        TeamMembersRepository(db).add_member(world["qa"], "vera", role="team_admin")
        body = _body(self._dialog(client, world, "source", "vera"))
        assert body["share_targets"] == []
        assert body["outside_shares"][0]["can_revoke"] is False

    def test_locked_offers_no_targets(self, client, db, world):
        _policy(db, world["ops"], "locked")
        body = _body(self._dialog(client, world, "source", "alice"))
        assert body["outside_policy"] == "locked" and body["share_targets"] == []

    @pytest.mark.parametrize("kind, warning", [("agent", "agent"), ("prompt", "prompt"), ("tool", "tool_stored")])
    def test_the_warning_follows_the_kind(self, client, db, world, kind, warning):
        assert _body(self._dialog(client, world, kind, "adam"))["warning_kind"] == warning

    def test_a_receiver_reads_where_it_comes_from_and_nothing_of_the_owning_team(self, client, db, world):
        AgentsRepository(db).update(world["items"]["agent"], world["ops_p"], {"key": "k-2", "access_payer_id": "adam"})
        assert _share(client, world, "agent").status_code == 201
        # Dev's share is the older one, so rita (in Dev and QA) reads the item in Dev.
        db.execute(text("UPDATE team_item_shares SET created_at = now() - interval '1 hour'"))
        assert _share(client, world, "agent", into="qa").status_code == 201
        resp = self._dialog(client, world, "agent", "rita")
        assert resp.status_code == 200, resp.data
        body = _body(resp)
        assert body["workspace"] == {"kind": "team", "team_id": world["dev"], "name": "Dev"}
        assert body["shared_from"] == {"team_id": world["ops"], "name": "Ops"}
        assert body["origin"] == "team_shared"
        # Nothing about Ops' size, its outside access or the other teams it shares with.
        for key in ("members_count", "outside_access", "outside_policy"):
            assert key not in body
        assert body["outside_shares"] == [] and body["share_targets"] == []


class TestPersonalAgentUsingTeamItems:
    """vera's own agent reads Ops' source: it goes only to people who reach that source."""

    def _agent(self, db, world):
        return agent(db, "vera", name="Vera's helper", source_id=world["items"]["source"])

    def _grant(self, client, team_id, agent_id, **extra):
        with _as("vera"):
            return client.post(
                f"/api/teams/{team_id}/grants", json={"resource_type": "agent", "resource_id": agent_id, **extra}
            )

    def _grant_rows(self, db, agent_id):
        return db.execute(
            text("SELECT team_id::text FROM team_resource_grants WHERE resource_id = CAST(:a AS uuid)"),
            {"a": agent_id},
        ).scalars().all()

    def test_a_team_that_does_not_reach_the_item_is_refused(self, client, db, world):
        agent_id = self._agent(db, world)
        resp = self._grant(client, world["dev"], agent_id)
        assert resp.status_code == 409, resp.data
        body = _body(resp)
        assert body["code"] == "uses_team_items"
        assert body["uses_team_items"][0]["team_id"] == world["ops"]
        assert self._grant_rows(db, agent_id) == []

    def test_the_owning_team_and_a_team_it_is_shared_with_are_not(self, client, db, world):
        agent_id = self._agent(db, world)
        assert self._grant(client, world["ops"], agent_id).status_code == 201
        assert _share(client, world, "source").status_code == 201
        assert self._grant(client, world["dev"], agent_id).status_code == 201
        assert sorted(self._grant_rows(db, agent_id)) == sorted([world["ops"], world["dev"]])

    def test_its_share_dialog_names_the_team_items(self, client, db, world):
        agent_id = self._agent(db, world)
        with _as("vera"):
            body = _body(client.get(f"/api/resource_shares?resource_type=agent&resource_id={agent_id}"))
        (row,) = body["uses_team_items"]
        assert row["team_id"] == world["ops"] and row["name"] == "Ops"
        assert [(i["type"], i["id"], i["name"]) for i in row["items"]] == [
            ("source", world["items"]["source"], "Docs")
        ]

    def test_an_agent_using_no_team_items_has_none(self, client, db, world):
        agent_id = agent(db, "vera", name="Plain")
        with _as("vera"):
            body = _body(client.get(f"/api/resource_shares?resource_type=agent&resource_id={agent_id}"))
        assert body["uses_team_items"] == []
        assert self._grant(client, world["dev"], agent_id).status_code == 201
