"""A member's personal shares to a team pause while they are out of it and return when they are re-added.

A grant made to a team (team-wide, or to one member of that team) gives access
only while the item's owner is still a member of that team. Leaving, or being
removed, deletes the owner's ``team_members`` rows and nothing else: the grants
stay, the team's grants list marks them ``paused_reason: "owner_left"``, and
re-adding the owner makes them work again. Every path that honours a grant is
checked here: reads, runs, "Shared with you" lists, sponsors and live folders.
Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.api.user.resource_access import (
    REASON_CANNOT_EDIT_HOLDER,
    REASON_OWNER_LOST_ACCESS,
    AccessDenied,
    active_sponsor,
    can_sponsor_ref,
    can_use_ref,
    ref_access,
    require,
    resolve,
    sponsor_key,
    sponsor_state,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository

ADMIN, LENA, BOB, CAROL = "ml-admin", "ml-lena", "ml-bob", "ml-carol"
KINDS = ("agent", "source", "prompt", "tool")


def _people(conn, *users):
    repo = UsersRepository(conn)
    for user in users:
        repo.upsert(user, email=f"{user}@x.io")


def _team(conn, name="Ops", members=((LENA, "team_editor"), (BOB, "team_viewer"), (CAROL, "team_viewer"))):
    _people(conn, ADMIN, *(u for u, _ in members))
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:8]}", ADMIN)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, ADMIN, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid


def _item(conn, kind, owner=LENA, name="Thing"):
    if kind == "agent":
        row = AgentsRepository(conn).create(owner, name, "published", key=f"k-{uuid.uuid4().hex[:8]}")
    elif kind == "source":
        row = SourcesRepository(conn).create(name, user_id=owner)
    elif kind == "prompt":
        row = PromptsRepository(conn).create(owner, name, "Be brief.")
    else:
        row = UserToolsRepository(conn).create(owner, "api_tool")
    return str(row["id"])


def _share(conn, tid, kind, rid, level="viewer", owner=LENA, target=None):
    TeamResourceGrantsRepository(conn).grant(tid, kind, rid, owner, owner, access_level=level, target_user_id=target)


def _leave(conn, tid, user=LENA, actor=None):
    """Remove ``user`` the way the members route does (an admin's removal, or leaving with ``actor=user``)."""
    TeamMembersRepository(conn).change_membership(tid, user, None, actor=actor or ADMIN)


def _rejoin(conn, tid, user=LENA, role="editor"):
    TeamMembersRepository(conn).change_membership(tid, user, role, actor=ADMIN)


@pytest.fixture
def team(pg_conn):
    return _team(pg_conn)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    @pytest.mark.parametrize("kind", KINDS)
    def test_a_team_wide_grant_pauses_and_returns(self, pg_conn, team, kind):
        rid = _item(pg_conn, kind)
        _share(pg_conn, team, kind, rid)
        assert resolve(pg_conn, kind, rid, BOB) is not None
        _leave(pg_conn, team)
        assert resolve(pg_conn, kind, rid, BOB) is None
        with pytest.raises(AccessDenied) as denied:
            require(pg_conn, kind, rid, BOB, "use")
        assert denied.value.status == 404
        _rejoin(pg_conn, team)
        ra = resolve(pg_conn, kind, rid, BOB)
        assert ra is not None and ra.access == "viewer"

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_grant_to_one_member_pauses_too(self, pg_conn, team, kind):
        rid = _item(pg_conn, kind)
        _share(pg_conn, team, kind, rid, target=BOB)
        assert resolve(pg_conn, kind, rid, BOB) is not None
        _leave(pg_conn, team, actor=LENA)
        assert resolve(pg_conn, kind, rid, BOB) is None
        _rejoin(pg_conn, team)
        assert resolve(pg_conn, kind, rid, BOB) is not None

    def test_an_editor_grant_stops_writes(self, pg_conn, team):
        rid = _item(pg_conn, "prompt")
        _share(pg_conn, team, "prompt", rid, level="editor")
        assert require(pg_conn, "prompt", rid, BOB, "edit").owner_id == LENA
        _leave(pg_conn, team)
        with pytest.raises(AccessDenied):
            require(pg_conn, "prompt", rid, BOB, "edit")

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_scope_lookups_agree(self, pg_conn, team, kind):
        rid = _item(pg_conn, kind)
        _share(pg_conn, team, kind, rid, level="editor")
        scope = TeamScopeRepository(pg_conn)
        _leave(pg_conn, team)
        assert scope.visible_resource_ids(BOB, kind) == set()
        assert scope.visible_with_access(BOB, kind) == {}
        assert scope.effective_access(BOB, kind, rid) is None
        _rejoin(pg_conn, team)
        assert scope.visible_resource_ids(BOB, kind) == {rid}
        assert scope.visible_with_access(BOB, kind) == {rid: "editor"}
        assert scope.effective_access(BOB, kind, rid) == "editor"

    def test_the_owner_keeps_their_own_item(self, pg_conn, team):
        rid = _item(pg_conn, "agent")
        _share(pg_conn, team, "agent", rid)
        _leave(pg_conn, team)
        assert resolve(pg_conn, "agent", rid, LENA).access == "owner"

    def test_only_the_team_they_left_pauses(self, pg_conn, team):
        other = _team(pg_conn, name="Sales")
        rid = _item(pg_conn, "source")
        _share(pg_conn, team, "source", rid)
        _share(pg_conn, other, "source", rid)
        _leave(pg_conn, team)
        assert resolve(pg_conn, "source", rid, BOB) is not None  # Bob is in Sales too
        TeamMembersRepository(pg_conn).change_membership(other, BOB, None, actor=ADMIN)
        assert resolve(pg_conn, "source", rid, BOB) is None

    def test_a_membership_through_the_identity_provider_still_counts(self, pg_conn, team):
        rid = _item(pg_conn, "agent")
        _share(pg_conn, team, "agent", rid)
        TeamMembersRepository(pg_conn).add_member(team, LENA, role="team_viewer", source="oidc_group")
        TeamMembersRepository(pg_conn).remove_member(team, LENA, source="manual")
        assert resolve(pg_conn, "agent", rid, BOB) is not None
        TeamMembersRepository(pg_conn).remove_member(team, LENA, source="oidc_group")
        assert resolve(pg_conn, "agent", rid, BOB) is None

    def test_a_deactivated_owner_is_still_a_member(self, pg_conn, team):
        """Deactivation keeps the membership rows, so it doesn't pause team shares."""
        rid = _item(pg_conn, "agent")
        _share(pg_conn, team, "agent", rid)
        pg_conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": LENA})
        assert resolve(pg_conn, "agent", rid, BOB) is not None

    def test_the_teams_owner_is_in_it_without_a_membership_row(self, pg_conn):
        """Being in the team reads as the team role does: the owner counts even with no row."""
        _people(pg_conn, LENA, BOB)
        tid = str(TeamsRepository(pg_conn).create("Own", f"own-{uuid.uuid4().hex[:8]}", LENA)["id"])
        TeamMembersRepository(pg_conn).add_member(tid, BOB)
        rid = _item(pg_conn, "agent")
        _share(pg_conn, tid, "agent", rid)
        assert resolve(pg_conn, "agent", rid, BOB) is not None

    def test_a_grant_on_a_missing_item_gives_nothing(self, pg_conn, team):
        ghost = str(uuid.uuid4())
        _share(pg_conn, team, "agent", ghost)
        assert TeamScopeRepository(pg_conn).visible_resource_ids(BOB, "agent") == set()

    def test_nothing_is_deleted(self, pg_conn, team):
        rid = _item(pg_conn, "agent")
        _share(pg_conn, team, "agent", rid)
        _share(pg_conn, team, "agent", rid, target=BOB)
        _leave(pg_conn, team)
        assert len(TeamResourceGrantsRepository(pg_conn).list_for_team(team)) == 2


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@contextmanager
def _patch_stream_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.services.stream_processor.db_readonly", _yield), patch(
        "docsgpt.api.answer.services.stream_processor.db_session", _yield
    ):
        yield


class TestRuns:
    def test_chatting_with_a_shared_agent_stops_and_returns(self, pg_conn, team):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        agent = AgentsRepository(pg_conn).create(LENA, "Helper", "published", key="ml-agent-key")
        _share(pg_conn, team, "agent", str(agent["id"]))
        with _patch_stream_db(pg_conn):
            key, _, _ = StreamProcessor({}, {"sub": BOB})._get_agent_key(str(agent["id"]), BOB)
        assert key == "ml-agent-key"
        _leave(pg_conn, team)
        with _patch_stream_db(pg_conn), pytest.raises(Exception, match="Unauthorized"):
            StreamProcessor({}, {"sub": BOB})._get_agent_key(str(agent["id"]), BOB)
        _rejoin(pg_conn, team)
        with _patch_stream_db(pg_conn):
            key, _, _ = StreamProcessor({}, {"sub": BOB})._get_agent_key(str(agent["id"]), BOB)
        assert key == "ml-agent-key"

    @pytest.mark.parametrize("kind", ["source", "prompt", "tool"])
    def test_a_shared_item_stops_running_in_someone_elses_agent(self, pg_conn, team, kind):
        rid = _item(pg_conn, kind)
        _share(pg_conn, team, kind, rid)
        holder = AgentsRepository(pg_conn).create(BOB, "Bob's", "published")
        assert can_use_ref(pg_conn, kind, rid, BOB)
        assert ref_access(pg_conn, "agent", holder, kind, rid).principal == BOB
        _leave(pg_conn, team)
        assert not can_use_ref(pg_conn, kind, rid, BOB)
        stopped = ref_access(pg_conn, "agent", holder, kind, rid)
        assert stopped.principal is None and stopped.reason == REASON_OWNER_LOST_ACCESS
        _rejoin(pg_conn, team)
        assert ref_access(pg_conn, "agent", holder, kind, rid).principal == BOB

    def test_a_live_folder_stops_feeding_a_shared_source(self, pg_conn, team):
        from docsgpt.api.user.folder_knowledge import folder_source_ids

        source = _item(pg_conn, "source")
        own = _item(pg_conn, "source", owner=BOB, name="own")
        _share(pg_conn, team, "source", source)
        folder = str(FoldersRepository(pg_conn).create(BOB, "Carriers", resource_type="source")["id"])
        FolderItemsRepository(pg_conn).file(BOB, "source", source, folder)
        FolderItemsRepository(pg_conn).file(BOB, "source", own, folder)
        holder = AgentsRepository(pg_conn).create(BOB, "Bob's", "published", knowledge_folder_ids=[folder])
        assert set(folder_source_ids(pg_conn, [folder], "agent", holder)) == {source, own}
        _leave(pg_conn, team)
        assert folder_source_ids(pg_conn, [folder], "agent", holder) == [own]
        _rejoin(pg_conn, team)
        assert set(folder_source_ids(pg_conn, [folder], "agent", holder)) == {source, own}


# ---------------------------------------------------------------------------
# Sponsors
# ---------------------------------------------------------------------------


class TestSponsors:
    def test_a_sponsor_on_a_shared_agent_stops_when_its_owner_leaves(self, pg_conn, team):
        """Bob edits Lena's agent through her team grant and sponsors his own prompt on it."""
        agent_id = _item(pg_conn, "agent")
        _share(pg_conn, team, "agent", agent_id, level="editor")
        prompt = _item(pg_conn, "prompt", owner=BOB)
        AgentsRepository(pg_conn).update(
            agent_id, LENA, {"resource_sponsors": {sponsor_key("prompt", prompt): BOB}}
        )
        holder = AgentsRepository(pg_conn).get_any(agent_id, LENA)
        assert active_sponsor(pg_conn, "agent", holder, "prompt", prompt) == BOB
        _leave(pg_conn, team)
        assert active_sponsor(pg_conn, "agent", holder, "prompt", prompt) is None
        assert sponsor_state(pg_conn, "agent", holder, "prompt", prompt) == (BOB, REASON_CANNOT_EDIT_HOLDER)
        _rejoin(pg_conn, team)
        assert active_sponsor(pg_conn, "agent", holder, "prompt", prompt) == BOB

    def test_an_editor_grant_no_longer_lets_someone_sponsor(self, pg_conn, team):
        source = _item(pg_conn, "source")
        _share(pg_conn, team, "source", source, level="editor")
        assert can_sponsor_ref(pg_conn, "source", source, BOB)
        _leave(pg_conn, team)
        assert not can_sponsor_ref(pg_conn, "source", source, BOB)


# ---------------------------------------------------------------------------
# "Shared with you" lists
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, *modules):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for module in modules:
            for name in ("db_session", "db_readonly"):
                stack.enter_context(patch(f"{module}.{name}", _yield))
        yield


def _get(app, conn, resource_cls, path, module, user=BOB):
    with _patch_db(conn, module), app.test_request_context(path):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource_cls().get()


def _ids(kind, resp):
    body = resp.json
    rows = {"tool": lambda b: b["tools"], "source": lambda b: b["paginated"]}.get(kind, lambda b: b)(body)
    return {str(r["id"]) for r in rows}


def _list_route(kind):
    if kind == "agent":
        from docsgpt.api.user.agents.routes import GetAgents

        return GetAgents, "/api/get_agents", "docsgpt.api.user.agents.routes"
    if kind == "prompt":
        from docsgpt.api.user.prompts.routes import GetPrompts

        return GetPrompts, "/api/get_prompts", "docsgpt.api.user.prompts.routes"
    if kind == "tool":
        from docsgpt.api.user.tools.routes import GetTools

        return GetTools, "/api/get_tools", "docsgpt.api.user.tools.routes"
    from docsgpt.api.user.sources.routes import PaginatedSources

    return PaginatedSources, "/api/sources/paginated?rows=50", "docsgpt.api.user.sources.routes"


class TestSharedWithYou:
    @pytest.mark.parametrize("kind", KINDS)
    def test_the_personal_list_drops_and_regains_the_item(self, app, pg_conn, team, kind):
        rid = _item(pg_conn, kind)
        _share(pg_conn, team, kind, rid)
        cls, path, module = _list_route(kind)
        assert rid in _ids(kind, _get(app, pg_conn, cls, path, module))
        _leave(pg_conn, team)
        assert rid not in _ids(kind, _get(app, pg_conn, cls, path, module))
        _rejoin(pg_conn, team)
        assert rid in _ids(kind, _get(app, pg_conn, cls, path, module))

    def test_a_personal_folder_stops_counting_the_item(self, pg_conn, team):
        from docsgpt.api.user.folders.service import visible_item_counts

        rid = _item(pg_conn, "agent")
        _share(pg_conn, team, "agent", rid)
        folder = str(FoldersRepository(pg_conn).create(BOB, "Mine")["id"])
        FolderItemsRepository(pg_conn).file(BOB, "agent", rid, folder)
        assert visible_item_counts(pg_conn, BOB, "agent") == {folder: 1}
        _leave(pg_conn, team)
        assert visible_item_counts(pg_conn, BOB, "agent") == {}

    def test_a_tool_is_not_said_to_come_through_the_paused_team(self, pg_conn, team):
        from docsgpt.api.user.tools.routes import _shared_via

        rid = _item(pg_conn, "tool")
        _share(pg_conn, team, "tool", rid)
        assert _shared_via(pg_conn, BOB, [rid]) == {rid: "Ops"}
        _leave(pg_conn, team)
        assert _shared_via(pg_conn, BOB, [rid]) == {}


# ---------------------------------------------------------------------------
# The team's grants list
# ---------------------------------------------------------------------------


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
            "docsgpt.api.user.team_authz.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        stack.enter_context(patch("docsgpt.api.user.teams.routes.publish_user_event"))
        yield pg_conn


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _grants_by_owner(client, tid, user=ADMIN):
    with _as(user):
        resp = client.get(f"/api/teams/{tid}/grants")
    assert resp.status_code == 200
    return {(g["owner_id"], g.get("target_user_id")): g for g in json.loads(resp.data)["grants"]}


class TestGrantsList:
    def test_a_leavers_grants_stay_listed_as_paused(self, client, db):
        tid = _team(db)
        lenas = _item(db, "agent")
        bobs = _item(db, "prompt", owner=BOB)
        _share(db, tid, "agent", lenas)
        _share(db, tid, "agent", lenas, target=CAROL)
        _share(db, tid, "prompt", bobs, owner=BOB)
        before = _grants_by_owner(client, tid)
        assert {g["paused_reason"] for g in before.values()} == {None}
        with _as(LENA):
            assert client.delete(f"/api/teams/{tid}/members/{LENA}").status_code == 200
        after = _grants_by_owner(client, tid)
        assert after[(LENA, None)]["paused_reason"] == "owner_left"
        assert after[(LENA, CAROL)]["paused_reason"] == "owner_left"
        assert after[(BOB, None)]["paused_reason"] is None
        _rejoin(db, tid)
        assert {g["paused_reason"] for g in _grants_by_owner(client, tid).values()} == {None}

    def test_an_admins_removal_reads_the_same(self, client, db):
        tid = _team(db)
        _share(db, tid, "source", _item(db, "source"))
        with _as(ADMIN):
            assert client.delete(f"/api/teams/{tid}/members/{LENA}").status_code == 200
        assert _grants_by_owner(client, tid)[(LENA, None)]["paused_reason"] == "owner_left"
        # A viewer sees the whole-team grant, paused, and has no access to it.
        row = _grants_by_owner(client, tid, user=BOB)[(LENA, None)]
        assert row["paused_reason"] == "owner_left"
        assert row["caller"] is None
