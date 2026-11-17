"""Move and the team's outside policy: what a lock keeps in, who brings outside access in, and team shares.

* A locked team keeps its items in: moving them out is refused for everyone, its Owner included, and a
  policy change racing a move waits for it (or the move waits and sees the lock).
* Bringing an agent with outside access into a team takes the role the target team's policy names: an
  Editor may under ``editors``; nobody may into a locked team.
* Moving a team's item out drops its shares with other teams; the plan lists them first.
* An agent moving into a team keeps the items another team shares with that team, and the plan says where
  they come from; what isn't shared with the target team is still taken off.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.workspaces.move import MoveError, apply_move, parse_move_request
from tests.workspaces.move_support import (
    agent, apply, body, keyed, owner_of, plan, prompt, source, team, tool, workflow,
)


def _policy(conn, team_id, policy):
    conn.execute(
        text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id}
    )


def _refused(conn, mover, request_body) -> MoveError:
    with pytest.raises(MoveError) as err:
        apply(conn, mover, request_body)
    return err.value


def _dev(conn):
    """Team "Dev" (dora owner, eddie editor, rita viewer): the team Ops shares with."""
    return team(conn, owner="dora", name="Dev", members=(("eddie", "team_editor"), ("rita", "team_viewer")))


class TestMoveOutOfALockedTeam:
    @pytest.mark.parametrize("mover", ["alice", "adam"])
    def test_nobody_moves_an_item_out_the_owner_included(self, pg_conn, mover):
        tid, principal = team(pg_conn)
        src = source(pg_conn, principal)
        _policy(pg_conn, tid, "locked")
        with pytest.raises(MoveError) as err:
            plan(pg_conn, mover, body("personal", [("source", src)]))
        assert (err.value.status, err.value.code) == (403, "team_locked")
        assert owner_of(pg_conn, "source", src) == principal

    def test_unlocking_lets_it_move_again(self, pg_conn):
        tid, principal = team(pg_conn)
        src = source(pg_conn, principal)
        _policy(pg_conn, tid, "locked")
        _policy(pg_conn, tid, "admins")
        apply(pg_conn, "alice", body("personal", [("source", src)]))
        assert owner_of(pg_conn, "source", src) == "alice"


class TestDroppedShares:
    def test_the_plan_lists_the_shares_a_move_out_drops_and_the_move_drops_them(self, pg_conn):
        tid, principal = team(pg_conn)
        dev, _ = _dev(pg_conn)
        qa, _ = team(pg_conn, owner="quinn", name="QA", members=())
        src = source(pg_conn, principal, "Handbook")
        ag = agent(pg_conn, principal, "Helper", source_id=src)
        shares = TeamItemSharesRepository(pg_conn)
        shares.share(tid, dev, "source", src, "adam")
        shares.share(tid, qa, "agent", ag, "adam")
        stays = source(pg_conn, principal, "Stays")
        shares.share(tid, dev, "source", stays, "adam")

        out = plan(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert sorted(out["dropped_shares"], key=lambda s: (s["team_name"], s["type"])) == [
            {"type": "source", "id": src, "name": "Handbook", "team_id": dev, "team_name": "Dev"},
            {"type": "agent", "id": ag, "name": "Helper", "team_id": qa, "team_name": "QA"},
        ]

        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert shares.get(dev, "source", src) is None
        assert shares.get(qa, "agent", ag) is None
        assert shares.get(dev, "source", stays) is not None

    def test_a_move_in_drops_nothing(self, pg_conn):
        tid, _ = team(pg_conn)
        src = source(pg_conn, "eddie")
        assert plan(pg_conn, "eddie", body(tid, [("source", src)]))["dropped_shares"] == []


class TestOutsideAccessIntoATeamFollowsItsPolicy:
    def test_an_editor_brings_a_keyed_agent_into_an_editors_team(self, pg_conn):
        tid, principal = team(pg_conn)
        _policy(pg_conn, tid, "editors")
        ag = agent(pg_conn, "eddie", "Public", key="k-public", status="published")
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert out["needs_admin"] == [] and out["team_locked_agents"] == []
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        row = pg_conn.execute(
            text("SELECT user_id, key, access_payer_id FROM agents WHERE id = CAST(:i AS uuid)"), {"i": ag}
        ).fetchone()
        assert tuple(row) == (principal, "k-public", "eddie")

    def test_under_admins_an_editor_still_needs_an_admin(self, pg_conn):
        tid, _ = team(pg_conn)
        ag = agent(pg_conn, "eddie", "Public", key="k-public", status="published")
        err = _refused(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert (err.status, err.code) == (403, "move_needs_admin")

    @pytest.mark.parametrize("mover", ["adam", "alice", "eddie"])
    def test_nobody_brings_outside_access_into_a_locked_team(self, pg_conn, mover):
        tid, _ = team(pg_conn)
        _policy(pg_conn, tid, "locked")
        ag = agent(pg_conn, mover, "Public", shared=True, shared_token=f"tok-{mover}")
        out = plan(pg_conn, mover, body(tid, [("agent", ag)]))
        assert out["team_locked_agents"] == [{"id": ag, "name": "Public"}]
        assert out["needs_admin"] == []
        err = _refused(pg_conn, mover, body(tid, [("agent", ag)]))
        assert (err.status, err.code) == (403, "team_locked")
        assert err.extra["agents"] == [{"id": ag, "name": "Public"}]
        assert owner_of(pg_conn, "agent", ag) == mover

    def test_an_agent_without_outside_access_moves_into_a_locked_team(self, pg_conn):
        tid, principal = team(pg_conn)
        _policy(pg_conn, tid, "locked")
        ag = agent(pg_conn, "eddie", "Quiet")
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert owner_of(pg_conn, "agent", ag) == principal


class TestItemsSharedIntoTheTargetTeam:
    def _world(self, conn):
        ops, ops_p = team(conn)
        dev, dev_p = _dev(conn)
        items = {"source": source(conn, ops_p, "Ops docs"), "tool": tool(conn, ops_p),
                 "prompt": prompt(conn, ops_p, "Ops brief")}
        shares = TeamItemSharesRepository(conn)
        for kind, item_id in items.items():
            shares.share(ops, dev, kind, item_id, "adam")
        return ops, dev, dev_p, items

    def test_a_personal_agent_keeps_the_shared_items_when_it_moves_into_the_receiving_team(self, pg_conn):
        ops, dev, dev_p, items = self._world(pg_conn)
        own_src = source(pg_conn, "eddie", "Mine")
        unshared = source(pg_conn, team(pg_conn, owner="olga", name="Far", members=(("eddie", "team_editor"),))[1])
        ag = agent(pg_conn, "eddie", "Helper", source_id=items["source"], extra_source_ids=[own_src, unshared],
                   tools=[items["tool"]], prompt_id=items["prompt"])

        out = plan(pg_conn, "eddie", body(dev, [("agent", ag)]))
        shared_from = {"team_id": ops, "name": "Ops"}
        assert sorted(out["shared_refs"], key=lambda r: r["type"]) == [
            {"type": "prompt", "id": items["prompt"], "name": "Ops brief", "shared_from": shared_from},
            {"type": "source", "id": items["source"], "name": "Ops docs", "shared_from": shared_from},
            {"type": "tool", "id": items["tool"], "name": "read_webpage", "shared_from": shared_from},
        ]
        cannot = keyed(out["cannot_move"])
        assert set(cannot) == {("source", unshared)}
        assert cannot[("source", unshared)]["effect"] == "removed_from_holder"

        apply(pg_conn, "eddie", body(dev, [("agent", ag)]))
        row = pg_conn.execute(
            text("SELECT user_id, source_id::text, extra_source_ids::text[], tools, prompt_id::text FROM agents "
                 "WHERE id = CAST(:i AS uuid)"), {"i": ag},
        ).fetchone()
        assert row[0] == dev_p
        assert row[1] == items["source"]
        assert row[2] == [own_src]
        assert row[3] == [items["tool"]]
        assert row[4] == items["prompt"]
        assert owner_of(pg_conn, "source", items["source"]) != dev_p

    def test_a_workflow_node_keeps_them_too(self, pg_conn):
        ops, dev, dev_p, items = self._world(pg_conn)
        wid = workflow(pg_conn, "eddie", nodes=[{"config": {"sources": [items["source"]], "tools": [items["tool"]]}}])
        ag = agent(pg_conn, "eddie", "Flow", agent_type="workflow", workflow_id=wid)
        out = plan(pg_conn, "eddie", body(dev, [("agent", ag)]))
        assert {(r["type"], r["id"]) for r in out["shared_refs"]} == {
            ("source", items["source"]), ("tool", items["tool"]),
        }
        apply(pg_conn, "eddie", body(dev, [("agent", ag)]))
        config = pg_conn.execute(
            text("SELECT config FROM workflow_nodes WHERE workflow_id = CAST(:w AS uuid)"), {"w": wid}
        ).scalar()
        assert config["config"]["sources"] == [items["source"]]
        assert config["config"]["tools"] == [items["tool"]]

    def test_a_share_paused_by_a_lock_still_keeps_the_ref(self, pg_conn):
        ops, dev, dev_p, items = self._world(pg_conn)
        ag = agent(pg_conn, "eddie", "Helper", source_id=items["source"])
        _policy(pg_conn, ops, "locked")
        assert [r["id"] for r in plan(pg_conn, "eddie", body(dev, [("agent", ag)]))["shared_refs"]] == [
            items["source"]
        ]
        apply(pg_conn, "eddie", body(dev, [("agent", ag)]))
        assert pg_conn.execute(
            text("SELECT source_id::text FROM agents WHERE id = CAST(:i AS uuid)"), {"i": ag}
        ).scalar() == items["source"]

    def test_into_another_team_the_shared_item_is_taken_off(self, pg_conn):
        ops, dev, dev_p, items = self._world(pg_conn)
        other, _ = team(pg_conn, owner="olga", name="Other", members=(("eddie", "team_editor"),))
        ag = agent(pg_conn, "eddie", "Helper", source_id=items["source"])
        out = plan(pg_conn, "eddie", body(other, [("agent", ag)]))
        assert out["shared_refs"] == []
        assert ("source", items["source"]) in keyed(out["cannot_move"])
        apply(pg_conn, "eddie", body(other, [("agent", ag)]))
        assert pg_conn.execute(
            text("SELECT source_id FROM agents WHERE id = CAST(:i AS uuid)"), {"i": ag}
        ).scalar() is None

    def test_a_share_row_naming_another_owning_team_keeps_nothing(self, pg_conn):
        ops, dev, dev_p, items = self._world(pg_conn)
        far, _ = team(pg_conn, owner="olga", name="Far", members=())
        pg_conn.execute(
            text("UPDATE team_item_shares SET owner_team_id = CAST(:far AS uuid) WHERE resource_id = CAST(:i AS uuid)"),
            {"far": far, "i": items["source"]},
        )
        ag = agent(pg_conn, "eddie", "Helper", source_id=items["source"])
        assert plan(pg_conn, "eddie", body(dev, [("agent", ag)]))["shared_refs"] == []


def _waiting_on_a_lock(engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()"
        )).scalar())


@pytest.mark.fresh_db
class TestAPolicyChangeRacingAMove:
    def test_a_move_out_waits_for_a_lock_being_set_and_is_refused(self, pg_engine):
        with pg_engine.begin() as conn:
            tid, principal = team(conn)
            src = source(conn, principal)
            request = body("personal", [("source", src)])
            fingerprint = plan(conn, "adam", request)["fingerprint"]
        out: dict = {}

        def move() -> None:
            try:
                with pg_engine.begin() as conn:
                    apply_move(conn, "adam", parse_move_request({**request, "fingerprint": fingerprint}))
            except Exception as err:  # noqa: BLE001 - the test reads what the move raised
                out["error"] = err

        with pg_engine.begin() as conn:
            conn.execute(text("SELECT outside_policy FROM teams WHERE id = CAST(:t AS uuid) FOR UPDATE"), {"t": tid})
            _policy(conn, tid, "locked")
            thread = threading.Thread(target=move)
            thread.start()
            deadline = time.monotonic() + 10
            while thread.is_alive() and not _waiting_on_a_lock(pg_engine) and time.monotonic() < deadline:
                time.sleep(0.02)
        thread.join(10)
        assert not thread.is_alive()
        assert isinstance(out.get("error"), MoveError), out
        assert out["error"].code == "team_locked"
        with pg_engine.connect() as conn:
            assert owner_of(conn, "source", src) == principal
