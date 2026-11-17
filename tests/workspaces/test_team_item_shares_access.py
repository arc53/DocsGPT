"""A team's item shared with a whole other team: what the receiving team gets, and when it gets nothing.

Ops owns an agent, a source, a tool and a prompt and shares them with Dev. Every Dev member, and Dev's own
principal (Dev's agents run as it), gets the receiver's fixed actions on them, whatever their role in Dev: an
agent to chat with and pin, a source, tool or prompt to use. Nothing more: no editing, filing, moving, exporting
or sharing it on. The share reaches nobody while Ops is locked, once the item is no longer Ops' (a forced or
stale row naming another owning team), or once the person left Dev; who made the share doesn't matter. An item
used through a share is someone else's, so it counts as borrowed (prompts aside, as everywhere). Dev's agents
may reference Ops' shared source, tool and prompt; anything else of Ops' stays a workspace mismatch.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from docsgpt.api.user.resource_access import (
    borrowed_refs,
    can_use_ref,
    resolve,
    team_item_reach,
    workspace_mismatches,
)
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.workspaces.outside import RECEIVER_ACTIONS
from docsgpt.workspaces.principal import principal_id
from tests.workspaces.move_support import agent, prompt, source, team, tool

KINDS = ("agent", "source", "tool", "prompt")
_MAKERS = {"agent": agent, "source": source, "tool": tool, "prompt": prompt}

#: What a receiver must never get on a shared item.
NEVER = {"share_outside", "edit", "move_folder", "export", "view", "delete", "move_out", "manage_access_details",
         "publish", "view_config", "edit_credentials", "duplicate", "view_logs", "manage_schedules"}


@pytest.fixture
def world(pg_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer), Dev (dora owner, dan editor, rita viewer),
    QA (quinn owner, rita viewer); one item of each kind owned by Ops."""
    ops, ops_p = team(pg_conn)
    dev, dev_p = team(pg_conn, owner="dora", name="Dev", members=(("dan", "team_editor"), ("rita", "team_viewer")))
    qa, qa_p = team(pg_conn, owner="quinn", name="QA", members=(("rita", "team_viewer"),))
    items = {kind: _MAKERS[kind](pg_conn, ops_p) for kind in KINDS}
    return {"ops": ops, "ops_p": ops_p, "dev": dev, "dev_p": dev_p, "qa": qa, "qa_p": qa_p, "items": items}


def _share(conn, w, kind, into="dev", owner_team=None, by="adam"):
    TeamItemSharesRepository(conn).share(owner_team or w["ops"], w[into], kind, w["items"][kind], by)


def _policy(conn, team_id, policy):
    conn.execute(
        text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id}
    )


def _leave(conn, team_id, user):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user}
    )


class TestWhatTheReceivingTeamGets:
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("who", ["rita", "dan", "dora", "dev_p"])
    def test_exactly_the_receivers_actions(self, pg_conn, world, kind, who):
        _share(pg_conn, world, kind)
        user = world.get(who, who)
        ra = resolve(pg_conn, kind, world["items"][kind], user)
        assert ra is not None
        assert ra.actions == RECEIVER_ACTIONS[kind]
        assert not NEVER & set(ra.actions)
        assert ra.access == "viewer" and ra.team_role is None
        assert ra.team_id == world["ops"] and ra.via_team_id == world["dev"]
        assert ra.is_team_item and ra.owner_id == world["ops_p"]

    def test_the_payload_lives_in_the_receiving_team(self, pg_conn, world):
        _share(pg_conn, world, "agent")
        payload = resolve(pg_conn, "agent", world["items"]["agent"], "rita").payload()
        assert payload["workspace"] == {"kind": "team", "team_id": world["dev"]}
        assert payload["origin"] == "team_shared"
        assert payload["shared_from"] == {"team_id": world["ops"], "name": "Ops"}
        assert payload["team_role"] is None and payload["access"] == "viewer"
        assert payload["allowed_actions"] == ["pin", "use"]

    @pytest.mark.parametrize("kind", ["source", "tool", "prompt"])
    @pytest.mark.parametrize("who", ["dev_p", "rita"])
    def test_the_receiving_side_may_use_it_and_it_is_borrowed(self, pg_conn, world, kind, who):
        user = world.get(who, who)
        rid = world["items"][kind]
        assert not can_use_ref(pg_conn, kind, rid, user)
        assert borrowed_refs(pg_conn, user, [(kind, rid)]) == []
        _share(pg_conn, world, kind)
        assert can_use_ref(pg_conn, kind, rid, user)
        # Prompts are never borrowed; a shared source or tool is someone else's.
        assert borrowed_refs(pg_conn, user, [(kind, rid)]) == ([] if kind == "prompt" else [(kind, rid)])

    def test_a_member_of_both_teams_keeps_their_role_in_the_owning_team(self, pg_conn, world):
        TeamMembersRepository(pg_conn).add_member(world["dev"], "eddie", role="team_viewer")
        _share(pg_conn, world, "agent")
        ra = resolve(pg_conn, "agent", world["items"]["agent"], "eddie")
        assert ra.team_role == "editor" and ra.via_team_id is None and ra.can("edit")

    def test_the_sharer_leaving_changes_nothing(self, pg_conn, world):
        _share(pg_conn, world, "source", by="adam")
        _leave(pg_conn, world["ops"], "adam")
        assert resolve(pg_conn, "source", world["items"]["source"], "rita").can("use")


class TestWhenItReachesNobody:
    @pytest.mark.parametrize("kind", KINDS)
    def test_no_share(self, pg_conn, world, kind):
        for user in ("rita", "dora", world["dev_p"]):
            assert resolve(pg_conn, kind, world["items"][kind], user) is None

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_owning_team_locked_pauses_it_and_unlocking_brings_it_back(self, pg_conn, world, kind):
        _share(pg_conn, world, kind)
        _policy(pg_conn, world["ops"], "locked")
        assert resolve(pg_conn, kind, world["items"][kind], "rita") is None
        assert resolve(pg_conn, kind, world["items"][kind], world["dev_p"]) is None
        _policy(pg_conn, world["ops"], "admins")
        assert resolve(pg_conn, kind, world["items"][kind], "rita") is not None

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_row_naming_another_owning_team(self, pg_conn, world, kind):
        # A forced or stale row: QA never owned this item.
        _share(pg_conn, world, kind, owner_team=world["qa"])
        assert resolve(pg_conn, kind, world["items"][kind], "dan") is None
        assert resolve(pg_conn, kind, world["items"][kind], world["dev_p"]) is None

    def test_a_receiver_who_left(self, pg_conn, world):
        _share(pg_conn, world, "tool")
        _leave(pg_conn, world["dev"], "dan")
        assert resolve(pg_conn, "tool", world["items"]["tool"], "dan") is None
        assert not can_use_ref(pg_conn, "tool", world["items"]["tool"], "dan")

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_third_team_and_its_members(self, pg_conn, world, kind):
        _share(pg_conn, world, kind)
        assert resolve(pg_conn, kind, world["items"][kind], world["qa_p"]) is None
        assert resolve(pg_conn, kind, world["items"][kind], "quinn") is None
        assert resolve(pg_conn, kind, world["items"][kind], "stranger") is None


class TestWhichReceivingTeam:
    def test_the_named_team_when_it_reaches_them_else_the_oldest_share(self, pg_conn, world):
        _share(pg_conn, world, "source", into="dev")
        _share(pg_conn, world, "source", into="qa")
        sid = world["items"]["source"]
        # One transaction stamps both rows alike: make QA's the newer.
        pg_conn.execute(
            text("UPDATE team_item_shares SET created_at = now() + interval '1 minute' WHERE team_id = CAST(:t AS uuid)"),
            {"t": world["qa"]},
        )
        assert team_item_reach(pg_conn, "rita", "source", sid) == world["dev"]
        assert team_item_reach(pg_conn, "rita", "source", sid, prefer_team=world["qa"]) == world["qa"]
        assert team_item_reach(pg_conn, "dora", "source", sid, prefer_team=world["qa"]) == world["dev"]
        assert team_item_reach(pg_conn, world["qa_p"], "source", sid) == world["qa"]
        assert team_item_reach(pg_conn, "alice", "source", sid) is None
        _policy(pg_conn, world["ops"], "locked")
        assert team_item_reach(pg_conn, "rita", "source", sid) is None


class TestReceivingTeamsHolders:
    def test_a_dev_agent_may_reference_ops_items_shared_into_dev(self, pg_conn, world):
        refs = [(kind, world["items"][kind]) for kind in ("source", "tool", "prompt")]
        assert workspace_mismatches(pg_conn, world["dev_p"], refs) == [(t, i.lower()) for t, i in refs]
        for kind in ("source", "tool", "prompt"):
            _share(pg_conn, world, kind)
        assert workspace_mismatches(pg_conn, world["dev_p"], refs) == []
        # QA has no share: the same refs stay foreign to it.
        assert len(workspace_mismatches(pg_conn, world["qa_p"], refs)) == 3

    def test_a_shared_agent_and_a_row_naming_another_team_stay_mismatches(self, pg_conn, world):
        _share(pg_conn, world, "agent")
        _share(pg_conn, world, "source", owner_team=world["qa"])
        refs = [("agent", world["items"]["agent"]), ("source", world["items"]["source"])]
        assert workspace_mismatches(pg_conn, world["dev_p"], refs) == [(t, i.lower()) for t, i in refs]

    def test_a_paused_share_still_saves(self, pg_conn, world):
        _share(pg_conn, world, "source")
        _policy(pg_conn, world["ops"], "locked")
        assert workspace_mismatches(pg_conn, world["dev_p"], [("source", world["items"]["source"])]) == []


def test_a_principal_never_reaches_another_teams_share(pg_conn, world):
    _share(pg_conn, world, "prompt")
    other = principal_id(uuid.uuid4())
    assert resolve(pg_conn, "prompt", world["items"]["prompt"], other) is None
