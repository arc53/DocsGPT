"""Why a schedule or an agent's outside access is paused for its payer, derived on every read and never stored.

The reasons, strongest first: ``owner_inactive`` (an account it runs on is deactivated), ``payer_left`` (the payer
no longer holds the role on the team agent), ``no_payer`` (nobody can be billed) and ``payer_out_of_allowance``
(until the window resets). Nothing is written when a pause starts or ends.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.quotas import pause as pause_mod
from docsgpt.quotas.pause import PAUSE_REASONS, Pause, PayerChecks, outside_access_pause, schedule_pause
from docsgpt.quotas.service import QuotaService
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
NEXT_MONTH = datetime(2026, 12, 2, 12, tzinfo=timezone.utc)
RESETS_AT = datetime(2026, 12, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn(pg_conn, monkeypatch):
    @contextmanager
    def _readonly():
        yield pg_conn

    monkeypatch.setattr("docsgpt.quotas.service.db_readonly", _readonly)
    monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "month")
    return pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    repo.add_member(tid, "tomas", role="team_viewer")
    return tid, principal_id(tid)


def _team_agent(conn, principal, *, payer="adam", key=True, **fields):
    return AgentsRepository(conn).create(
        principal, "Team bot", "published", key=f"k-{uuid.uuid4().hex[:8]}" if key else None,
        access_payer_id=payer, created_by="adam", default_model_id="m", agent_type="classic", **fields,
    )


def _personal_agent(conn, owner="lena", key=True):
    return AgentsRepository(conn).create(
        owner, "Mine", "published", key=f"k-{uuid.uuid4().hex[:8]}" if key else None,
        default_model_id="m", agent_type="classic",
    )


def _schedule(agent, setter):
    return {"id": str(uuid.uuid4()), "user_id": setter, "agent_id": str(agent["id"]), "status": "active"}


def _deactivate(conn, user_id):
    UsersRepository(conn).upsert(user_id)
    conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": user_id})


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _out_of_allowance(conn, user_id):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, token_limit=100)
    TokenUsageRepository(conn).insert(user_id=user_id, api_key="k", prompt_tokens=150, timestamp=NOW - timedelta(days=1))


def test_the_reasons_strongest_first():
    assert PAUSE_REASONS == ("owner_inactive", "team_locked", "payer_left", "no_payer", "payer_out_of_allowance")


def _policy(conn, team_id, policy):
    conn.execute(
        text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": team_id}
    )


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


class TestSchedulePause:
    def test_a_schedule_that_can_run_is_not_paused(self, conn):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)

        assert schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW) is None

    def test_a_deactivated_setter(self, conn):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _deactivate(conn, "eddie")

        assert schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW) == Pause("owner_inactive", "eddie", None)

    def test_a_deactivated_owner_of_a_personal_agent(self, conn):
        agent = _personal_agent(conn)
        _deactivate(conn, "lena")

        assert schedule_pause(conn, _schedule(agent, "lena"), agent, now=NOW).reason == "owner_inactive"

    @pytest.mark.parametrize("role", [None, "team_viewer"])
    def test_a_setter_who_left_or_is_now_a_viewer(self, conn, role):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _set_role(conn, team, "eddie", role)

        # Whether they left or were demoted is read from the same role lookup, so the line can say which.
        assert schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW) == Pause(
            "payer_left", "eddie", None, left_team=role is None
        )

    def test_re_adding_the_setter_resumes_it(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        schedule = _schedule(agent, "eddie")
        _set_role(conn, team, "eddie", None)
        assert schedule_pause(conn, schedule, agent, now=NOW).reason == "payer_left"

        _set_role(conn, team, "eddie", "team_editor")

        assert schedule_pause(conn, schedule, agent, now=NOW) is None

    def test_the_team_owner_may_set_schedules(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _set_role(conn, team, "alice", None)

        assert schedule_pause(conn, _schedule(agent, "alice"), agent, now=NOW) is None

    def test_a_schedule_stored_under_a_principal_has_no_payer(self, conn):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)

        assert schedule_pause(conn, _schedule(agent, principal), agent, now=NOW) == Pause("no_payer", None, None)

    def test_a_setter_out_of_allowance_until_the_reset(self, conn):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _out_of_allowance(conn, "eddie")

        paused = schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW)

        assert paused == Pause("payer_out_of_allowance", "eddie", RESETS_AT)

    def test_a_new_window_clears_the_allowance_pause_with_no_write(self, conn):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _out_of_allowance(conn, "eddie")
        schedule = _schedule(agent, "eddie")
        before = conn.execute(text("SELECT count(*) FROM token_usage")).scalar()

        assert schedule_pause(conn, schedule, agent, now=NOW).reason == "payer_out_of_allowance"
        assert schedule_pause(conn, schedule, agent, now=NEXT_MONTH) is None
        assert conn.execute(text("SELECT count(*) FROM token_usage")).scalar() == before
        assert schedule["status"] == "active"

    def test_a_personal_agents_schedule_never_reports_payer_left(self, conn):
        agent = _personal_agent(conn)

        assert schedule_pause(conn, _schedule(agent, "editor-friend"), agent, now=NOW) is None

    def test_deactivation_comes_before_a_lost_role(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _set_role(conn, team, "eddie", None)
        _deactivate(conn, "eddie")
        _out_of_allowance(conn, "eddie")

        assert schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW).reason == "owner_inactive"

    def test_a_lost_role_comes_before_the_allowance(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _set_role(conn, team, "eddie", "team_viewer")
        _out_of_allowance(conn, "eddie")

        assert schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW).reason == "payer_left"

    def test_an_agentless_schedule_checks_the_direct_allowance(self, conn):
        QuotaPoliciesRepository(conn).upsert(scope="user", subject_id="eddie", bucket="direct", token_limit=100)
        TokenUsageRepository(conn).insert(user_id="eddie", prompt_tokens=150, timestamp=NOW - timedelta(days=1))

        paused = schedule_pause(conn, {"user_id": "eddie"}, {"user_id": "eddie"}, now=NOW)

        assert paused == Pause("payer_out_of_allowance", "eddie", RESETS_AT)


# ---------------------------------------------------------------------------
# Published access
# ---------------------------------------------------------------------------


class TestOutsideAccessPause:
    def test_a_team_agent_with_an_active_admin_payer_is_not_paused(self, conn):
        _, principal = _team(conn)

        assert outside_access_pause(conn, _team_agent(conn, principal), now=NOW) is None

    def test_a_deactivated_payer(self, conn):
        _, principal = _team(conn)
        _deactivate(conn, "adam")

        assert outside_access_pause(conn, _team_agent(conn, principal), now=NOW) == Pause("owner_inactive", "adam", None)

    def test_a_deactivated_owner_of_a_personal_agent(self, conn):
        _deactivate(conn, "lena")

        assert outside_access_pause(conn, _personal_agent(conn), now=NOW) == Pause("owner_inactive", "lena", None)

    @pytest.mark.parametrize("role", [None, "team_editor", "team_viewer"])
    def test_a_payer_who_left_or_is_now_below_admin(self, conn, role):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _set_role(conn, team, "adam", role)

        assert outside_access_pause(conn, agent, now=NOW) == Pause("payer_left", "adam", None, left_team=role is None)

    def test_re_promoting_the_payer_resumes_it(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _set_role(conn, team, "adam", "team_editor")
        assert outside_access_pause(conn, agent, now=NOW).reason == "payer_left"

        _set_role(conn, team, "adam", "team_admin")

        assert outside_access_pause(conn, agent, now=NOW) is None

    def test_a_team_agent_with_access_on_and_no_payer(self, conn):
        _, principal = _team(conn)

        assert outside_access_pause(conn, _team_agent(conn, principal, payer=None), now=NOW) == Pause(
            "no_payer", None, None
        )

    def test_nothing_is_paused_when_no_outside_access_is_on(self, conn):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal, payer=None, key=False)

        assert outside_access_pause(conn, agent, now=NOW) is None

    @pytest.mark.parametrize("access", ["public_link", "webhook"])
    def test_a_link_or_a_webhook_is_outside_access_too(self, conn, access):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal, payer=None, key=False)
        if access == "public_link":
            agent = {**agent, "shared": True, "shared_token": "tok"}
        else:
            agent = {**agent, "incoming_webhook_token": "hook"}

        assert outside_access_pause(conn, agent, now=NOW).reason == "no_payer"

    def test_a_row_that_does_not_say_what_is_on_is_checked_as_on(self, conn):
        _, principal = _team(conn)

        # A gate handed only the owner and payer must not let a payerless team agent through.
        assert outside_access_pause(conn, {"user_id": principal, "access_payer_id": None}, now=NOW).reason == (
            "no_payer"
        )

    def test_a_payer_out_of_allowance_until_the_reset(self, conn):
        _, principal = _team(conn)
        _out_of_allowance(conn, "adam")

        assert outside_access_pause(conn, _team_agent(conn, principal), now=NOW) == Pause(
            "payer_out_of_allowance", "adam", RESETS_AT
        )

    def test_a_new_window_clears_it(self, conn):
        _, principal = _team(conn)
        _out_of_allowance(conn, "adam")

        assert outside_access_pause(conn, _team_agent(conn, principal), now=NEXT_MONTH) is None

    def test_a_personal_agents_owner_out_of_allowance(self, conn):
        _out_of_allowance(conn, "lena")

        assert outside_access_pause(conn, _personal_agent(conn), now=NOW).reason == "payer_out_of_allowance"

    def test_a_personal_agent_never_reports_payer_left(self, conn):
        team, _ = _team(conn)
        _set_role(conn, team, "lena", None)

        assert outside_access_pause(conn, _personal_agent(conn), now=NOW) is None

    def test_deactivation_comes_first(self, conn):
        team, principal = _team(conn)
        _set_role(conn, team, "adam", None)
        _deactivate(conn, "adam")
        _out_of_allowance(conn, "adam")

        assert outside_access_pause(conn, _team_agent(conn, principal), now=NOW).reason == "owner_inactive"

    def test_a_lost_role_comes_before_the_allowance(self, conn):
        team, principal = _team(conn)
        _set_role(conn, team, "adam", "team_editor")
        _out_of_allowance(conn, "adam")

        assert outside_access_pause(conn, _team_agent(conn, principal), now=NOW).reason == "payer_left"

    def test_a_missing_agent_is_not_paused(self, conn):
        assert outside_access_pause(conn, None, now=NOW) is None


# ---------------------------------------------------------------------------
# The payload and the per-request cache
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_payload_shape():
    assert Pause("payer_out_of_allowance", "eddie", RESETS_AT).payload() == {
        "reason": "payer_out_of_allowance", "until": RESETS_AT.isoformat(),
    }
    assert Pause("payer_left", "eddie", None, left_team=True).payload() == {
        "reason": "payer_left", "until": None, "left_team": True,
    }
    assert Pause("payer_left", "eddie", None, left_team=False).payload() == {
        "reason": "payer_left", "until": None, "left_team": False,
    }


class TestPayerChecks:
    def test_a_list_checks_each_distinct_payer_once(self, conn, monkeypatch):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)
        checked = []
        original = QuotaService.check.__func__

        def _counting(cls, user_id, bucket="direct", now=None):
            checked.append((user_id, bucket))
            return original(cls, user_id, bucket, now)

        monkeypatch.setattr(QuotaService, "check", classmethod(_counting))
        roles = []
        original_role = pause_mod.team_role_for
        monkeypatch.setattr(pause_mod, "team_role_for", lambda *a: roles.append(a[1:]) or original_role(*a))
        checks = PayerChecks()

        for setter in ("eddie", "eddie", "alice", "eddie"):
            assert schedule_pause(conn, _schedule(agent, setter), agent, checks=checks, now=NOW) is None
        for _ in range(3):
            assert outside_access_pause(conn, agent, checks=checks, now=NOW) is None

        assert sorted(checked) == [("adam", "agent"), ("alice", "agent"), ("eddie", "agent")]
        assert len(roles) == len(set(roles)) == 3

    def test_without_a_cache_each_read_checks_again(self, conn, monkeypatch):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal)
        checked = []
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, uid, *a, **kw: checked.append(uid)))

        schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW)
        schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW)

        assert checked == ["eddie", "eddie"]

    def test_a_principal_is_never_handed_to_the_quota_service(self, conn, monkeypatch):
        _, principal = _team(conn)
        agent = _team_agent(conn, principal, payer=None)
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, *a, **kw: pytest.fail("checked")))

        assert schedule_pause(conn, _schedule(agent, principal), agent, now=NOW).reason == "no_payer"
        assert outside_access_pause(conn, agent, now=NOW).reason == "no_payer"


# ---------------------------------------------------------------------------
# The team's outside policy
# ---------------------------------------------------------------------------


class TestTeamLocked:
    def test_a_locked_teams_outside_access_pauses_for_its_payer(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _policy(conn, team, "locked")

        pause = outside_access_pause(conn, agent, now=NOW)

        assert pause == Pause("team_locked", "adam", None)
        assert pause.payload() == {"reason": "team_locked", "until": None}

    def test_unlocking_resumes_it_with_nothing_written(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _policy(conn, team, "locked")
        assert outside_access_pause(conn, agent, now=NOW).reason == "team_locked"

        _policy(conn, team, "admins")

        assert outside_access_pause(conn, AgentsRepository(conn).get_by_id(str(agent["id"])), now=NOW) is None

    def test_a_deactivated_account_comes_first(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _policy(conn, team, "locked")
        _deactivate(conn, "adam")

        assert outside_access_pause(conn, agent, now=NOW).reason == "owner_inactive"

    @pytest.mark.parametrize("change", ["left", "no_payer", "allowance"])
    def test_it_comes_before_the_payer_reasons(self, conn, change):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal, payer=None if change == "no_payer" else "adam")
        if change == "left":
            _set_role(conn, team, "adam", None)
        if change == "allowance":
            _out_of_allowance(conn, "adam")
        _policy(conn, team, "locked")

        assert outside_access_pause(conn, agent, now=NOW).reason == "team_locked"

    def test_nothing_on_nothing_paused(self, conn):
        team, principal = _team(conn)
        _policy(conn, team, "locked")

        assert outside_access_pause(conn, _team_agent(conn, principal, key=False), now=NOW) is None

    def test_a_schedule_is_not_outside_access(self, conn):
        team, principal = _team(conn)
        agent = _team_agent(conn, principal)
        _policy(conn, team, "locked")

        assert schedule_pause(conn, _schedule(agent, "eddie"), agent, now=NOW) is None


class TestEditorsToo:
    def test_an_editor_pays_under_editors_too(self, conn):
        team, principal = _team(conn)
        _policy(conn, team, "editors")

        assert outside_access_pause(conn, _team_agent(conn, principal, payer="eddie"), now=NOW) is None

    def test_narrowing_to_admins_pauses_the_editor_who_still_is_in_the_team(self, conn):
        team, principal = _team(conn)
        _policy(conn, team, "editors")
        agent = _team_agent(conn, principal, payer="eddie")
        _policy(conn, team, "admins")

        assert outside_access_pause(conn, agent, now=NOW) == Pause("payer_left", "eddie", None, left_team=False)

    def test_a_viewer_never_pays(self, conn):
        team, principal = _team(conn)
        _policy(conn, team, "editors")

        assert outside_access_pause(conn, _team_agent(conn, principal, payer="tomas"), now=NOW).reason == "payer_left"

    def test_one_list_reads_each_teams_policy_once(self, conn, monkeypatch):
        team, principal = _team(conn)
        agents = [_team_agent(conn, principal) for _ in range(3)]
        reads = []
        real = pause_mod._team_policy

        def _counting(conn_, team_id):
            reads.append(team_id)
            return real(conn_, team_id)

        monkeypatch.setattr(pause_mod, "_team_policy", _counting)
        checks = PayerChecks()
        for agent in agents:
            outside_access_pause(conn, agent, checks=checks, now=NOW)

        assert reads == [team]
