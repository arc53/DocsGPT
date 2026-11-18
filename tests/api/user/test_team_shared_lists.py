"""A team's items shared with another team, as the receiving team's lists, pickers and detail reads show them.

Ops owns an agent, a source, a tool and a prompt and shares them with Dev. In Dev's workspace each is listed
beside Dev's own items, as ``origin: team_shared`` with ``shared_from`` naming Ops, the receiver's fixed actions
and Dev as its ``workspace``, whatever the member's role in Dev: nothing to edit, file or publish. A share that
isn't live lists nothing: revoked, Ops locked (unlocking brings it back), or a row naming a team that doesn't own
the item. No Personal list shows it, neither an Ops member's nor a Dev member's. A Dev member pins the agent in
Dev only. Detail reads (the agent, a prompt, where a source lives, the shared-link page) place it in Dev, and
never show Ops' filing of it.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.outside import RECEIVER_ACTIONS
from tests.workspaces.move_support import agent, file, folder, prompt, source, team, tool

KINDS = ("agent", "source", "tool", "prompt")
_MAKERS = {"agent": agent, "source": source, "tool": tool, "prompt": prompt}

_MODULES = (
    "docsgpt.api.user.agents.routes",
    "docsgpt.api.user.agents.sharing",
    "docsgpt.api.user.prompts.routes",
    "docsgpt.api.user.tools.routes",
    "docsgpt.api.user.sources.routes",
    "docsgpt.workspaces.context",
)


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def world(pg_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer), Dev (dora owner, dan editor, rita viewer),
    QA (quinn owner, rita viewer); one item of each kind owned by Ops."""
    ops, ops_p = team(pg_conn)
    dev, dev_p = team(pg_conn, owner="dora", name="Dev", members=(("dan", "team_editor"), ("rita", "team_viewer")))
    qa, qa_p = team(pg_conn, owner="quinn", name="QA", members=(("rita", "team_viewer"),))
    items = {kind: _MAKERS[kind](pg_conn, ops_p) for kind in KINDS}
    return {"ops": ops, "ops_p": ops_p, "dev": dev, "dev_p": dev_p, "qa": qa, "qa_p": qa_p, "items": items}


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for module in _MODULES:
            for name in ("db_session", "db_readonly"):
                if hasattr(__import__(module, fromlist=[name]), name):
                    stack.enter_context(patch(f"{module}.{name}", _yield))
        yield


def _call(app, conn, resource_cls, path, user, *, team_id=None, method="get", args=()):
    headers = {WORKSPACE_HEADER: team_id} if team_id else {}
    with _patch_db(conn), app.test_request_context(path, method=method.upper(), headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)(*args)


def _share(conn, w, kind, into="dev", owner_team=None):
    TeamItemSharesRepository(conn).share(owner_team or w["ops"], w[into], kind, w["items"][kind], "adam")


def _revoke(conn, w, kind, into="dev"):
    TeamItemSharesRepository(conn).revoke(w[into], kind, w["items"][kind])


def _policy(conn, team_id, policy):
    conn.execute(
        text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id}
    )


def _list_route(kind, picker=False):
    if kind == "agent":
        from docsgpt.api.user.agents.routes import GetAgents

        return GetAgents, "/api/get_agents"
    if kind == "prompt":
        from docsgpt.api.user.prompts.routes import GetPrompts

        return GetPrompts, "/api/get_prompts"
    if kind == "tool":
        from docsgpt.api.user.tools.routes import GetTools

        return GetTools, "/api/get_tools"
    if picker:
        from docsgpt.api.user.sources.routes import CombinedJson

        return CombinedJson, "/api/sources"
    from docsgpt.api.user.sources.routes import PaginatedSources

    return PaginatedSources, "/api/sources/paginated?rows=50"


def _rows(app, conn, kind, user, team_id=None, picker=False) -> dict:
    cls, path = _list_route(kind, picker)
    resp = _call(app, conn, cls, path, user, team_id=team_id)
    assert resp.status_code == 200, resp.json
    body = resp.json
    rows = {"tool": lambda b: b["tools"], "source": lambda b: b if picker else b["paginated"]}.get(
        kind, lambda b: b
    )(body)
    return {str(r["id"]): r for r in rows}


class TestTheReceivingTeamsLists:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("who", ["rita", "dan", "dora"])
    def test_listed_with_the_receivers_actions_and_where_it_comes_from(self, app, pg_conn, world, kind, who):
        rid = world["items"][kind]
        assert rid not in _rows(app, pg_conn, kind, who, world["dev"])
        _share(pg_conn, world, kind)
        row = _rows(app, pg_conn, kind, who, world["dev"])[rid]
        assert row["origin"] == "team_shared"
        assert row["shared_from"] == {"team_id": world["ops"], "name": "Ops"}
        assert row["workspace"] == {"kind": "team", "team_id": world["dev"]}
        assert row["team_role"] is None and row["access"] == "viewer"
        assert row["allowed_actions"] == sorted(RECEIVER_ACTIONS[kind])

    def test_the_sources_picker_lists_it_too(self, app, pg_conn, world):
        rid = world["items"]["source"]
        _share(pg_conn, world, "source")
        row = _rows(app, pg_conn, "source", "dan", world["dev"], picker=True)[rid]
        assert row["origin"] == "team_shared" and row["workspace"]["team_id"] == world["dev"]
        assert row["allowed_actions"] == ["use"]

    @pytest.mark.parametrize("kind", KINDS)
    def test_gone_after_revoke(self, app, pg_conn, world, kind):
        rid = world["items"][kind]
        _share(pg_conn, world, kind)
        assert rid in _rows(app, pg_conn, kind, "rita", world["dev"])
        _revoke(pg_conn, world, kind)
        assert rid not in _rows(app, pg_conn, kind, "rita", world["dev"])

    @pytest.mark.parametrize("kind", KINDS)
    def test_gone_while_the_owning_team_is_locked(self, app, pg_conn, world, kind):
        rid = world["items"][kind]
        _share(pg_conn, world, kind)
        _policy(pg_conn, world["ops"], "locked")
        assert rid not in _rows(app, pg_conn, kind, "rita", world["dev"])
        _policy(pg_conn, world["ops"], "admins")
        assert rid in _rows(app, pg_conn, kind, "rita", world["dev"])

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_row_naming_a_team_that_does_not_own_the_item_lists_nothing(self, app, pg_conn, world, kind):
        # A forced or stale row: QA never owned this item.
        _share(pg_conn, world, kind, owner_team=world["qa"])
        assert world["items"][kind] not in _rows(app, pg_conn, kind, "rita", world["dev"])

    @pytest.mark.parametrize("kind", KINDS)
    def test_only_the_receiving_team_lists_it(self, app, pg_conn, world, kind):
        # Rita is in QA too; the share is into Dev only.
        _share(pg_conn, world, kind)
        assert world["items"][kind] not in _rows(app, pg_conn, kind, "rita", world["qa"])

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("who", ["alice", "vera", "rita", "dora"])
    def test_never_in_a_personal_list(self, app, pg_conn, world, kind, who):
        _share(pg_conn, world, kind)
        assert world["items"][kind] not in _rows(app, pg_conn, kind, who)

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_owning_team_lists_it_as_its_own(self, app, pg_conn, world, kind):
        _share(pg_conn, world, kind)
        row = _rows(app, pg_conn, kind, "eddie", world["ops"])[world["items"][kind]]
        assert row["origin"] == "team" and row["workspace"]["team_id"] == world["ops"]
        assert "shared_from" not in row


class TestNoEditFields:
    def test_an_agent_row_carries_no_config_or_key(self, app, pg_conn, world):
        rid = world["items"]["agent"]
        pg_conn.execute(
            text("UPDATE agents SET key = 'secret-key-1234', config = CAST(:c AS jsonb) WHERE id = CAST(:i AS uuid)"),
            {"i": rid, "c": '{"banned_terms": ["x"]}'},
        )
        _share(pg_conn, world, "agent")
        for who in ("rita", "dora"):
            row = _rows(app, pg_conn, "agent", who, world["dev"])[rid]
            assert row["config"] == {} and "key" not in row and row["shared_token"] == ""
            assert row["folder_id"] is None
            assert row["ownership"] == "team" and row["team_access"] == "viewer"

    def test_a_source_row_shows_only_its_kind_of_config(self, app, pg_conn, world):
        rid = world["items"]["source"]
        _share(pg_conn, world, "source")
        row = _rows(app, pg_conn, "source", "dora", world["dev"])[rid]
        assert set(row["config"]) == {"kind"}
        assert "delete" not in row["allowed_actions"] and "edit" not in row["allowed_actions"]

    def test_a_tool_row_hides_its_secrets(self, app, pg_conn, world):
        rid = world["items"]["tool"]
        pg_conn.execute(
            text("UPDATE user_tools SET config = CAST(:c AS jsonb) WHERE id = CAST(:i AS uuid)"),
            {"i": rid, "c": '{"encrypted_credentials": "blob"}'},
        )
        _share(pg_conn, world, "tool")
        row = _rows(app, pg_conn, "tool", "dora", world["dev"])[rid]
        assert "encrypted_credentials" not in row["config"]
        assert row["owner_label"] == "Ops"

    def test_the_owning_teams_filing_does_not_show(self, app, pg_conn, world):
        rid = world["items"]["prompt"]
        ops_folder = folder(pg_conn, world["ops_p"], "Ops only")
        file(pg_conn, world["ops_p"], "prompt", rid, ops_folder)
        _share(pg_conn, world, "prompt")
        row = _rows(app, pg_conn, "prompt", "rita", world["dev"])[rid]
        assert row["folder_id"] is None and row["folder_path"] == []

    def test_a_shared_source_counts_as_shared_and_hides_who_else_uses_it(self, app, pg_conn, world):
        rid = world["items"]["source"]
        source(pg_conn, world["dev_p"], name="Dev's own")
        # Ops' own agent on the source: Dev may not delete the source, so it learns no count of it.
        agent(pg_conn, world["ops_p"], name="Ops reader", source_id=rid)
        _share(pg_conn, world, "source")
        from docsgpt.api.user.sources.routes import PaginatedSources

        resp = _call(app, pg_conn, PaginatedSources, "/api/sources/paginated?rows=50", "dora", team_id=world["dev"])
        assert resp.json["origin_counts"] == {"own": 1, "shared": 1}
        row = next(r for r in resp.json["paginated"] if r["id"] == rid)
        assert row["used_by"] == {"agents": [], "others": 0}
        resp = _call(
            app, pg_conn, PaginatedSources, "/api/sources/paginated?rows=50&origin=shared", "dora",
            team_id=world["dev"],
        )
        assert [r["id"] for r in resp.json["paginated"]] == [rid]


class TestDetailReads:
    def test_get_agent_lives_in_the_receiving_team(self, app, pg_conn, world):
        from docsgpt.api.user.agents.routes import GetAgent

        rid = world["items"]["agent"]
        ops_folder = folder(pg_conn, world["ops_p"], "Ops only")
        file(pg_conn, world["ops_p"], "agent", rid, ops_folder)
        _share(pg_conn, world, "agent")
        resp = _call(app, pg_conn, GetAgent, f"/api/get_agent?id={rid}", "rita", team_id=world["dev"])
        assert resp.status_code == 200
        data = resp.json
        assert data["workspace"] == {"kind": "team", "team_id": world["dev"]}
        assert data["origin"] == "team_shared" and data["shared_from"]["name"] == "Ops"
        assert data["folder_id"] is None
        assert data["config"] == {} and "key" not in data
        assert data["resource_sponsors"] == [] and "outside_access" not in data
        _revoke(pg_conn, world, "agent")
        resp = _call(app, pg_conn, GetAgent, f"/api/get_agent?id={rid}", "rita", team_id=world["dev"])
        assert resp[1] == 404

    def test_get_agent_prefers_the_workspace_it_is_asked_from(self, app, pg_conn, world):
        from docsgpt.api.user.agents.routes import GetAgent

        rid = world["items"]["agent"]
        _share(pg_conn, world, "agent")
        _share(pg_conn, world, "agent", into="qa")
        for team_id in (world["dev"], world["qa"]):
            resp = _call(app, pg_conn, GetAgent, f"/api/get_agent?id={rid}", "rita", team_id=team_id)
            assert resp.json["workspace"]["team_id"] == team_id

    def test_a_prompt_read_lives_in_the_receiving_team_without_ops_filing(self, app, pg_conn, world):
        from docsgpt.api.user.prompts.routes import GetSinglePrompt

        rid = world["items"]["prompt"]
        ops_folder = folder(pg_conn, world["ops_p"], "Ops only")
        file(pg_conn, world["ops_p"], "prompt", rid, ops_folder)
        _share(pg_conn, world, "prompt")
        resp = _call(app, pg_conn, GetSinglePrompt, f"/api/get_single_prompt?id={rid}", "rita", team_id=world["dev"])
        assert resp.status_code == 200
        assert resp.json["workspace"]["team_id"] == world["dev"] and resp.json["origin"] == "team_shared"
        assert resp.json["folder_id"] is None and resp.json["folder_path"] == []

    def test_where_a_shared_source_lives(self, app, pg_conn, world):
        from docsgpt.api.user.sources.routes import SourceWorkspace

        rid = world["items"]["source"]
        path = f"/api/sources/{rid}/workspace"
        assert _call(app, pg_conn, SourceWorkspace, path, "rita", args=(rid,)).status_code == 404
        _share(pg_conn, world, "source")
        resp = _call(app, pg_conn, SourceWorkspace, path, "rita", args=(rid,))
        assert resp.json["workspace"] == {"kind": "team", "team_id": world["dev"]}
        _share(pg_conn, world, "source", into="qa")
        resp = _call(app, pg_conn, SourceWorkspace, path, "rita", team_id=world["qa"], args=(rid,))
        assert resp.json["workspace"] == {"kind": "team", "team_id": world["qa"]}
        # An Ops member still goes to Ops.
        resp = _call(app, pg_conn, SourceWorkspace, path, "vera", args=(rid,))
        assert resp.json["workspace"] == {"kind": "team", "team_id": world["ops"]}

    def test_the_shared_link_page_follows_the_receiving_team(self, app, pg_conn, world):
        from docsgpt.api.user.agents.sharing import SharedAgent

        rid = world["items"]["agent"]
        pg_conn.execute(
            text("UPDATE agents SET shared = true, shared_token = 'tok-ops' WHERE id = CAST(:i AS uuid)"), {"i": rid}
        )
        _share(pg_conn, world, "agent")
        _share(pg_conn, world, "agent", into="qa")
        resp = _call(app, pg_conn, SharedAgent, "/api/shared_agent?token=tok-ops", "dan")
        assert resp.json["workspace"] == {"kind": "team", "team_id": world["dev"]}
        assert resp.json["origin"] == "team_shared" and resp.json["allowed_actions"] == ["pin", "use"]
        resp = _call(app, pg_conn, SharedAgent, "/api/shared_agent?token=tok-ops", "rita", team_id=world["qa"])
        assert resp.json["workspace"] == {"kind": "team", "team_id": world["qa"]}


class TestPins:
    def _pin(self, app, conn, world, user):
        from docsgpt.api.user.agents.routes import PinAgent

        rid = world["items"]["agent"]
        return _call(app, conn, PinAgent, f"/api/pin_agent?id={rid}", user, method="post")

    def _pinned(self, app, conn, user, team_id=None) -> dict:
        from docsgpt.api.user.agents.routes import PinnedAgents

        resp = _call(app, conn, PinnedAgents, "/api/pinned_agents", user, team_id=team_id)
        assert resp.status_code == 200
        return {r["id"]: r for r in resp.json}

    def test_a_receiver_pins_it_in_the_receiving_team_only(self, app, pg_conn, world):
        rid = world["items"]["agent"]
        assert self._pin(app, pg_conn, world, "rita").status_code == 404
        _share(pg_conn, world, "agent")
        assert self._pin(app, pg_conn, world, "rita").json["action"] == "pinned"
        row = self._pinned(app, pg_conn, "rita", world["dev"])[rid]
        assert row["workspace"] == {"kind": "team", "team_id": world["dev"]} and row["origin"] == "team_shared"
        assert row["key"] == ""
        assert rid not in self._pinned(app, pg_conn, "rita")
        assert rid not in self._pinned(app, pg_conn, "rita", world["qa"])

    def test_the_pin_hides_after_revoke_and_while_locked(self, app, pg_conn, world):
        rid = world["items"]["agent"]
        _share(pg_conn, world, "agent")
        self._pin(app, pg_conn, world, "rita")
        _policy(pg_conn, world["ops"], "locked")
        assert rid not in self._pinned(app, pg_conn, "rita", world["dev"])
        _policy(pg_conn, world["ops"], "admins")
        assert rid in self._pinned(app, pg_conn, "rita", world["dev"])
        _revoke(pg_conn, world, "agent")
        assert rid not in self._pinned(app, pg_conn, "rita", world["dev"])

    def test_a_member_of_both_teams_sees_the_pin_in_each(self, app, pg_conn, world):
        rid = world["items"]["agent"]
        TeamMembersRepository(pg_conn).add_member(world["dev"], "eddie", role="team_viewer")
        _share(pg_conn, world, "agent")
        self._pin(app, pg_conn, world, "eddie")
        assert self._pinned(app, pg_conn, "eddie", world["ops"])[rid]["origin"] == "team"
        assert self._pinned(app, pg_conn, "eddie", world["dev"])[rid]["origin"] == "team_shared"
        assert rid not in self._pinned(app, pg_conn, "eddie")


class TestTheSourcesQuery:
    def test_received_ids_bring_in_only_a_teams_rows(self, pg_conn, world):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        mine = source(pg_conn, "bob", name="Bob's")
        rid = world["items"]["source"]
        repo = SourcesRepository(pg_conn)
        # Only another team's source comes in this way: a person's never does, whatever id is passed.
        listed = {str(r["id"]) for r in repo.list_for_user(world["dev_p"], received_ids=[rid, mine])}
        assert listed == {rid}
        facets = {str(r["id"]) for r in repo.list_facets_for_user(world["dev_p"], received_ids=[rid, mine])}
        assert facets == {rid}


class TestReceivedQueryCount:
    """Listing what other teams share reads each owning team's policy with the shares, not once per item."""

    @staticmethod
    def _statements(conn, team_id, kind):
        from sqlalchemy import event

        from docsgpt.api.user.received_shares import received_into
        from docsgpt.workspaces.context import Workspace

        statements: list[str] = []

        def _count(_conn, _cursor, statement, *args):
            statements.append(statement)

        workspace = Workspace("team", team_id, f"__team__{team_id}", "viewer", "admins")
        event.listen(conn, "before_cursor_execute", _count)
        try:
            received = received_into(conn, workspace, kind)
        finally:
            event.remove(conn, "before_cursor_execute", _count)
        return received, statements

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_same_queries_for_one_item_or_many(self, pg_conn, world, kind):
        _share(pg_conn, world, kind)
        one, few = self._statements(pg_conn, world["dev"], kind)
        for i in range(5):
            TeamItemSharesRepository(pg_conn).share(
                world["ops"], world["dev"], kind, _MAKERS[kind](pg_conn, world["ops_p"], f"more {i}"), "adam"
            )
        many, more = self._statements(pg_conn, world["dev"], kind)
        assert len(one) == 1 and len(many) == 6
        assert len(more) == len(few) == 2
        assert not any("outside_policy FROM teams" in s for s in more)

    def test_a_locked_owning_team_still_lists_nothing(self, pg_conn, world):
        for kind in KINDS:
            _share(pg_conn, world, kind)
        _policy(pg_conn, world["ops"], "locked")
        assert all(self._statements(pg_conn, world["dev"], kind)[0] == {} for kind in KINDS)
