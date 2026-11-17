"""Notices addressed to a team principal are rerouted to a person, never lost.

A team's items are owned by its principal, whose event stream nobody reads. A notice to it goes to the person who
started the work; with nobody, a failure goes to the team's admins and owner, and anything else is dropped. Nothing
is ever written to ``user:__team__…:stream``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from docsgpt.core.settings import settings
from docsgpt.events import publisher
from docsgpt.notifications import notify
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import PRINCIPAL_PREFIX, principal_id


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _yield)
    return pg_conn


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


class _Redis:
    """Records every stream write."""

    def __init__(self):
        self.streams: list[str] = []

    def xadd(self, key, fields, maxlen=None, approximate=None):
        self.streams.append(key)
        return f"{len(self.streams)}-0"


@pytest.fixture
def redis(monkeypatch):
    fake = _Redis()
    monkeypatch.setattr(settings, "ENABLE_SSE_PUSH", True)
    monkeypatch.setattr(publisher, "get_redis_instance", lambda: fake)
    monkeypatch.setattr(publisher.Topic, "publish", lambda self, message: 1)
    monkeypatch.setattr(publisher, "_notify_monitors", lambda *a: None)
    monkeypatch.setattr(publisher, "_track_activity", lambda *a: None)
    return fake


def _users(streams):
    return sorted(key.split(":")[1] for key in streams)


class TestPublishUserEvent:
    def test_a_principals_event_goes_to_the_actor(self, db, redis):
        _, principal = _team(db)

        publisher.publish_user_event(principal, "source.ingest.completed", {"source_id": "s"}, actor_id="eddie")

        assert _users(redis.streams) == ["eddie"]

    def test_a_failure_with_no_actor_goes_to_the_admins_and_owner(self, db, redis):
        _, principal = _team(db)

        publisher.publish_user_event(principal, "source.ingest.failed", {"source_id": "s"})

        assert _users(redis.streams) == ["adam", "alice"]

    def test_anything_else_with_no_actor_is_dropped(self, db, redis):
        _, principal = _team(db)

        assert publisher.publish_user_event(principal, "source.ingest.progress", {"source_id": "s"}) is None
        assert redis.streams == []

    @pytest.mark.parametrize("actor", [None, "eddie"])
    @pytest.mark.parametrize("event_type", ["source.ingest.failed", "source.ingest.completed", "schedule.run"])
    def test_nothing_is_ever_written_to_a_principals_stream(self, db, redis, event_type, actor):
        _, principal = _team(db)

        publisher.publish_user_event(principal, event_type, {"source_id": "s"}, actor_id=actor)

        assert not any(key.startswith(f"user:{PRINCIPAL_PREFIX}") for key in redis.streams)

    def test_a_database_failure_drops_the_notice_rather_than_writing_to_the_team(self, redis, monkeypatch):
        @contextmanager
        def _down():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _down)

        publisher.publish_user_event(principal_id(uuid.uuid4()), "source.ingest.failed", {"source_id": "s"})

        assert redis.streams == []

    def test_a_person_is_unchanged_and_costs_no_lookup(self, redis, monkeypatch):
        def _no_db():
            raise AssertionError("a person's event must not read the database")

        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _no_db)

        publisher.publish_user_event("lena", "source.ingest.completed", {"source_id": "s"})

        assert redis.streams == ["user:lena:stream"]

    def test_ingest_monitors_hear_the_team_event_once(self, db, redis, monkeypatch):
        heard = []
        monkeypatch.setattr(publisher, "_notify_monitors", lambda user_id, *a: heard.append(user_id))
        _, principal = _team(db)

        publisher.publish_user_event(principal, "source.ingest.failed", {"source_id": "s"}, actor_id="eddie")

        assert heard == [principal]


class TestNotifyUser:
    @pytest.fixture
    def sent(self, monkeypatch):
        delivered = []
        monkeypatch.setattr(notify, "_notify", lambda **kwargs: delivered.append(kwargs) or notify.STORED)
        return delivered

    def test_a_principal_with_an_actor_notifies_the_actor(self, db, sent):
        _, principal = _team(db)

        notify.notify_user(user_id=principal, conversation_id=None, kind="schedule", title="t", body="b", url="/",
                           actor_id="eddie")

        assert [n["user_id"] for n in sent] == ["eddie"]

    def test_a_failure_kind_with_no_actor_reaches_the_admins(self, db, sent):
        _, principal = _team(db)

        notify.notify_user(user_id=principal, conversation_id=None, kind="schedule_failed", title="t", body="b",
                           url="/")

        assert sorted(n["user_id"] for n in sent) == ["adam", "alice"]

    def test_anything_else_with_no_actor_is_dropped(self, db, sent):
        _, principal = _team(db)

        notify.notify_user(user_id=principal, conversation_id="c", kind="job", title="t", body="b", url="/c/c")

        assert sent == []

    def test_a_person_is_notified_as_before(self, sent):
        notify.notify_user(user_id="lena", conversation_id=None, kind="job", title="t", body="b", url="/")
        assert [n["user_id"] for n in sent] == ["lena"]


class TestDocsGapsDigest:
    def test_the_digest_for_a_team_agent_reaches_the_teams_admins(self, db, monkeypatch):
        from docsgpt.analytics import tasks
        from docsgpt.storage.db.repositories.conversation_labels import ConversationLabelsRepository

        _, principal = _team(db)
        agent = {"id": str(uuid.uuid4()), "user_id": principal, "name": "Team bot"}
        monkeypatch.setattr(tasks, "enabled", lambda: True)
        monkeypatch.setattr(tasks, "db_readonly", db_readonly_of(db))
        monkeypatch.setattr(ConversationLabelsRepository, "digest_agents", lambda self: [agent])
        monkeypatch.setattr(ConversationLabelsRepository, "docs_gaps",
                            lambda self, *a: {"expected": 3.0, "topics": {"install": 2.0}})
        delivered = []
        monkeypatch.setattr(notify, "_notify", lambda **kwargs: delivered.append(kwargs) or notify.STORED)

        assert tasks.gap_digest() == {"sent": 1}

        assert sorted(n["user_id"] for n in delivered) == ["adam", "alice"]
        assert {n["kind"] for n in delivered} == {"docs_gaps"}


def db_readonly_of(conn):
    @contextmanager
    def _yield():
        yield conn

    return _yield


class TestIngestMonitorsMatchBySource:
    """A member's ingest monitor on a team source fires on the team's event, once, and only while they're a member."""

    @pytest.fixture
    def queued(self, monkeypatch):
        from docsgpt.monitors import tick

        calls = []
        monkeypatch.setattr(settings, "MONITORS_ENABLED", True)
        monkeypatch.setattr(tick, "_queue_event", lambda monitor_id, event: calls.append(monitor_id))
        return calls

    def _setup(self, db, monkeypatch):
        from docsgpt.monitors import tick
        from docsgpt.storage.db.repositories.monitors import MonitorsRepository
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        monkeypatch.setattr(tick, "db_readonly", db_readonly_of(db))
        monkeypatch.setattr(tick, "db_session", db_readonly_of(db))
        found = {}
        monkeypatch.setattr(MonitorsRepository, "find_ingest_monitors",
                            lambda self, user_id, source_id: found.setdefault("by_owner", []).append(user_id) or [])
        _, principal = _team(db)
        source = SourcesRepository(db).create("Team docs", user_id=principal)
        return principal, str(source["id"]), found

    def test_the_teams_event_wakes_members_monitors_on_the_source(self, db, monkeypatch, queued):
        from docsgpt.monitors import tick
        from docsgpt.storage.db.repositories.monitors import MonitorsRepository

        principal, source_id, _ = self._setup(db, monkeypatch)
        monitors = [{"id": "m-eddie", "user_id": "eddie"}, {"id": "m-out", "user_id": "outsider"}]
        monkeypatch.setattr(MonitorsRepository, "find_ingest_monitors_by_source",
                            lambda self, sid: monitors if sid == source_id else [], raising=False)

        tick.on_ingest_event(principal, "source.ingest.completed", {"source_id": source_id})

        # A non-member's monitor (they left the team) no longer fires.
        assert queued == ["m-eddie"]

    def test_a_persons_copy_of_a_team_event_wakes_nothing(self, db, monkeypatch, queued):
        from docsgpt.monitors import tick
        from docsgpt.storage.db.repositories.monitors import MonitorsRepository

        principal, source_id, found = self._setup(db, monkeypatch)
        monkeypatch.setattr(MonitorsRepository, "find_ingest_monitors_by_source",
                            lambda self, sid: [{"id": "m-eddie", "user_id": "eddie"}], raising=False)

        tick.on_ingest_event("eddie", "source.ingest.completed", {"source_id": source_id})

        assert queued == [] and "by_owner" not in found


class TestSourceEventsWakeIngestMonitors:
    """The worker's source events wake ingest monitors once, under the source's owner, whoever else hears them."""

    @pytest.fixture
    def heard(self, db, redis, monkeypatch):
        from docsgpt import worker
        from docsgpt.monitors import tick

        calls = []
        # The redis fixture silences the hook; put the real one back and record what reaches the monitors.
        monkeypatch.setattr(publisher, "_notify_monitors", _REAL_NOTIFY_MONITORS)
        monkeypatch.setattr(worker, "_notify_monitors", _REAL_NOTIFY_MONITORS)
        monkeypatch.setattr(tick, "on_ingest_event", lambda user_id, event_type, payload: calls.append(user_id))
        monkeypatch.setattr(worker, "db_readonly", db_readonly_of(db))
        return calls

    @pytest.mark.parametrize(
        "event_type,actor",
        [
            ("source.ingest.completed", "eddie"),
            ("source.ingest.completed", None),
            ("source.ingest.failed", None),
            ("source.ingest.failed", "eddie"),
        ],
    )
    def test_a_team_sources_event_reaches_the_monitors_under_the_principal(self, db, heard, event_type, actor):
        from docsgpt.worker import _publish_source_event

        _, principal = _team(db)

        _publish_source_event(principal, actor, event_type, {"source_id": "s"}, scope={"kind": "source", "id": "s"})

        assert heard.count(principal) == 1

    def test_a_persons_source_wakes_its_owners_monitors_once(self, heard):
        from docsgpt.worker import _publish_source_event

        _publish_source_event("lena", "eddie", "source.ingest.completed", {"source_id": "s"})

        assert heard.count("lena") == 1


_REAL_NOTIFY_MONITORS = publisher._notify_monitors
