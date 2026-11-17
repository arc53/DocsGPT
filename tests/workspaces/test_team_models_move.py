"""Move and custom models: a model never moves; its references follow to the matching model on the other side.

Moving in, a personal model an agent or a workflow node names is swapped for the target team's model with the
same endpoint (base URL and upstream model id); moving out, a team's model for the mover's own match. Without
a match, or for a model the old owner doesn't hold (someone else's, another team's), the reference is listed
(``cannot_move`` reason ``custom_model``) and removed. The plan lists each swap (``model_remaps``) and its
fingerprint covers them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.workspaces.move import MoveError, apply_move, parse_move_request
from docsgpt.workspaces.principal import principal_id
from tests.workspaces.move_support import agent, apply, body, keyed, other_team, plan, team, workflow

BASE = "https://models.example.com/v1"


def _model(conn, owner, name="My model", *, base_url=BASE, upstream="gpt-x", created_by=None) -> str:
    if created_by is None and owner.startswith("__team__"):
        created_by = "alice"
    return str(UserCustomModelsRepository(conn).create(
        owner, upstream, name, base_url, "sk-test", created_by=created_by,
    )["id"])


def _agent_row(conn, agent_id) -> dict:
    return dict(conn.execute(
        text("SELECT default_model_id, models, user_id FROM agents WHERE id = CAST(:i AS uuid)"), {"i": agent_id}
    ).mappings().fetchone())


def _node_model(conn, wid):
    cfg = conn.execute(
        text("SELECT config FROM workflow_nodes WHERE workflow_id = CAST(:w AS uuid)"), {"w": wid}
    ).scalar()
    inner = cfg.get("config") if isinstance(cfg.get("config"), dict) else cfg
    return inner.get("model_id")


class TestMoveIn:
    def test_a_personal_model_is_swapped_for_the_teams_match(self, pg_conn):
        tid, principal = team(pg_conn)
        mine = _model(pg_conn, "eddie")
        # The match tolerates a different case and a trailing slash on the base URL; the name may differ.
        theirs = _model(pg_conn, principal, "Team model", base_url="https://Models.example.com/v1/")
        ag = agent(pg_conn, "eddie", default_model_id=mine, models=[mine, "gpt-4o"])

        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert ("model", mine) not in keyed(out["cannot_move"])
        assert out["model_remaps"] == [
            {"from_id": mine, "from_name": "My model", "to_id": theirs, "to_name": "Team model"}
        ]

        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        row = _agent_row(pg_conn, ag)
        assert row["default_model_id"] == theirs
        assert row["models"] == [theirs, "gpt-4o"]
        # The person's model stays theirs, untouched.
        assert UserCustomModelsRepository(pg_conn).get(mine, "eddie") is not None

    def test_without_a_match_it_cant_move_and_is_removed(self, pg_conn):
        tid, principal = team(pg_conn)
        mine = _model(pg_conn, "eddie")
        _model(pg_conn, principal, "Other upstream", upstream="gpt-y")
        _model(pg_conn, principal, "Other endpoint", base_url="https://elsewhere.example.com/v1")
        ag = agent(pg_conn, "eddie", default_model_id=mine, models=[mine, "gpt-4o"])

        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("model", mine)]
        assert (entry["reason"], entry["effect"], entry["name"]) == ("custom_model", "removed_from_holder", "My model")
        assert out["model_remaps"] == []

        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        row = _agent_row(pg_conn, ag)
        assert row["default_model_id"] is None
        assert row["models"] == ["gpt-4o"]

    def test_another_teams_model_is_never_the_match(self, pg_conn):
        tid, _ = team(pg_conn)
        other = other_team(pg_conn)
        mine = _model(pg_conn, "eddie")
        _model(pg_conn, principal_id(other), "Their model", created_by="olga")
        ag = agent(pg_conn, "eddie", default_model_id=mine)

        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert keyed(out["cannot_move"])[("model", mine)]["reason"] == "custom_model"
        assert out["model_remaps"] == []

    def test_someone_elses_model_is_removed_even_with_a_match(self, pg_conn):
        tid, principal = team(pg_conn)
        veras = _model(pg_conn, "vera", "Vera's model")
        _model(pg_conn, principal, "Team model")
        ag = agent(pg_conn, "eddie", default_model_id=veras)

        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("model", veras)]
        assert (entry["reason"], entry["name"]) == ("custom_model", None)
        assert out["model_remaps"] == []
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert _agent_row(pg_conn, ag)["default_model_id"] is None

    def test_a_workflow_node_model_is_swapped(self, pg_conn):
        tid, principal = team(pg_conn)
        mine = _model(pg_conn, "eddie")
        theirs = _model(pg_conn, principal, "Team model")
        wid = workflow(pg_conn, "eddie", nodes=[{"config": {"model_id": mine}}])
        ag = agent(pg_conn, "eddie", agent_type="workflow", workflow_id=wid)

        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert [r["to_id"] for r in out["model_remaps"]] == [theirs]
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert _node_model(pg_conn, wid) == theirs

    def test_a_workflow_node_model_without_a_match_is_removed(self, pg_conn):
        tid, _ = team(pg_conn)
        mine = _model(pg_conn, "eddie")
        wid = workflow(pg_conn, "eddie", nodes=[{"config": {"model_id": mine}}])
        ag = agent(pg_conn, "eddie", agent_type="workflow", workflow_id=wid)
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert not _node_model(pg_conn, wid)

    def test_a_teams_model_already_named_stays(self, pg_conn):
        tid, principal = team(pg_conn)
        theirs = _model(pg_conn, principal, "Team model")
        ag = agent(pg_conn, "eddie", default_model_id=theirs)
        out = plan(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert ("model", theirs) not in keyed(out["cannot_move"]) and out["model_remaps"] == []
        apply(pg_conn, "eddie", body(tid, [("agent", ag)]))
        assert _agent_row(pg_conn, ag)["default_model_id"] == theirs


class TestMoveOut:
    def test_a_teams_model_is_swapped_for_the_movers_match(self, pg_conn):
        tid, principal = team(pg_conn)
        theirs = _model(pg_conn, principal, "Team model")
        mine = _model(pg_conn, "adam", "Adam's model", base_url=BASE + "/")
        ag = agent(pg_conn, principal, default_model_id=theirs, models=[theirs])

        out = plan(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert out["model_remaps"] == [
            {"from_id": theirs, "from_name": "Team model", "to_id": mine, "to_name": "Adam's model"}
        ]
        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        row = _agent_row(pg_conn, ag)
        assert (row["user_id"], row["default_model_id"], row["models"]) == ("adam", mine, [mine])
        # The team's model stays the team's.
        assert UserCustomModelsRepository(pg_conn).get(theirs, principal) is not None

    def test_without_a_match_it_is_listed_and_removed(self, pg_conn):
        tid, principal = team(pg_conn)
        theirs = _model(pg_conn, principal, "Team model")
        # Someone else's match doesn't count: only the mover's own.
        _model(pg_conn, "alice", "Alice's model")
        ag = agent(pg_conn, principal, default_model_id=theirs, models=[theirs, "gpt-4o"])

        out = plan(pg_conn, "adam", body("personal", [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("model", theirs)]
        assert (entry["reason"], entry["effect"], entry["name"]) == (
            "custom_model", "removed_from_holder", "Team model"
        )
        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        row = _agent_row(pg_conn, ag)
        assert (row["default_model_id"], row["models"]) == (None, ["gpt-4o"])

    def test_another_teams_model_is_removed(self, pg_conn):
        tid, principal = team(pg_conn)
        other = other_team(pg_conn)
        foreign = _model(pg_conn, principal_id(other), "Their model", created_by="olga")
        _model(pg_conn, "adam", "Adam's model")
        ag = agent(pg_conn, principal, default_model_id=foreign)

        out = plan(pg_conn, "adam", body("personal", [("agent", ag)]))
        entry = keyed(out["cannot_move"])[("model", foreign)]
        assert (entry["reason"], entry["name"]) == ("custom_model", None)
        assert out["model_remaps"] == []
        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert _agent_row(pg_conn, ag)["default_model_id"] is None

    def test_a_workflow_node_model_is_swapped(self, pg_conn):
        tid, principal = team(pg_conn)
        theirs = _model(pg_conn, principal, "Team model")
        mine = _model(pg_conn, "adam", "Adam's model")
        wid = workflow(pg_conn, principal, nodes=[{"config": {"model_id": theirs}}])
        ag = agent(pg_conn, principal, agent_type="workflow", workflow_id=wid)
        apply(pg_conn, "adam", body("personal", [("agent", ag)]))
        assert _node_model(pg_conn, wid) == mine


class TestFingerprint:
    def test_it_changes_with_the_remaps(self, pg_conn):
        tid, principal = team(pg_conn)
        mine = _model(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", default_model_id=mine)
        request = body(tid, [("agent", ag)])

        without = plan(pg_conn, "eddie", request)["fingerprint"]
        theirs = _model(pg_conn, principal, "Team model")
        with_match = plan(pg_conn, "eddie", request)["fingerprint"]
        assert with_match != without
        pg_conn.execute(
            text("UPDATE user_custom_models SET display_name = 'Renamed' WHERE id = CAST(:i AS uuid)"), {"i": theirs}
        )
        assert plan(pg_conn, "eddie", request)["fingerprint"] != with_match

    def test_a_plan_agreed_before_the_match_appeared_is_refused(self, pg_conn):
        tid, principal = team(pg_conn)
        mine = _model(pg_conn, "eddie")
        ag = agent(pg_conn, "eddie", default_model_id=mine)
        request = body(tid, [("agent", ag)])
        stale = plan(pg_conn, "eddie", request)["fingerprint"]
        _model(pg_conn, principal, "Team model")
        with pytest.raises(MoveError) as err:
            apply_move(pg_conn, "eddie", parse_move_request({**request, "fingerprint": stale}))
        assert err.value.code == "move_plan_changed"
