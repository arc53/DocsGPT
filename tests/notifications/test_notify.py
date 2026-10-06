"""notify_user: watching, a tab open, no tab with push, no tab without push, and the unread mark."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.events.keys import connection_leases_key
from docsgpt.notifications import notify, presence
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository

P256DH = "BIzyXn-qzOUEO1_AJqEJdxVQ4LBymTq3lFS7btztj_VA-UWISfaIbQpPNPssV2rq5CDmYvbBa4xZYzzmgSeWyNM"


@pytest.fixture()
def db(pg_engine, monkeypatch):
    monkeypatch.setattr("docsgpt.storage.db.engine._engine", pg_engine)
    return pg_engine


@pytest.fixture()
def conversation_id(db):
    with db.begin() as conn:
        return str(ConversationsRepository(conn).create("u1", "chat")["id"])


@pytest.fixture()
def published(monkeypatch):
    events = []

    def fake_publish(user_id, event_type, payload, *, scope=None):
        events.append({"user_id": user_id, "type": event_type, "payload": payload, "scope": scope})
        return "1-0"

    monkeypatch.setattr(notify, "publish_user_event", fake_publish)
    monkeypatch.setattr(settings, "ENABLE_SSE_PUSH", True)
    monkeypatch.setattr(settings, "SSE_MAX_CONCURRENT_PER_USER", 8)
    return events


@pytest.fixture()
def pushes(monkeypatch):
    queued = []
    from docsgpt.notifications import tasks

    monkeypatch.setattr(tasks.send_web_push, "delay", lambda user_id, payload: queued.append((user_id, payload)))
    return queued


@pytest.fixture()
def push_on(monkeypatch):
    monkeypatch.setattr("docsgpt.notifications.push.push_enabled", lambda: True)


def _subscribe(db, user_id="u1"):
    with db.begin() as conn:
        PushSubscriptionsRepository(conn).upsert(
            user_id=user_id, endpoint="https://fcm.googleapis.com/x", p256dh=P256DH, auth="a" * 22
        )


def _unread(db, conversation_id):
    with db.connect() as conn:
        return conn.execute(
            text("SELECT unread_at FROM conversations WHERE id = CAST(:id AS uuid)"), {"id": conversation_id}
        ).scalar()


def _call(conversation_id, **overrides):
    fields = {
        "user_id": "u1",
        "conversation_id": conversation_id,
        "kind": "job",
        "title": "run_code finished",
        "body": "The answer is 42.",
        "url": f"/c/{conversation_id}",
    }
    fields.update(overrides)
    return notify._notify(**fields)


class TestDecisions:
    def test_watching_sends_nothing_and_leaves_no_mark(
        self, db, conversation_id, fake_redis, published, pushes, push_on
    ):
        _subscribe(db)
        presence.report("u1", "t1", conversation_id, True)
        assert _call(conversation_id) == notify.WATCHING
        assert published == [] and pushes == []
        assert _unread(db, conversation_id) is None

    def test_a_tab_elsewhere_gets_a_toast_and_the_mark(
        self, db, conversation_id, fake_redis, published, pushes, push_on
    ):
        _subscribe(db)
        presence.report("u1", "t1", None, True)
        assert _call(conversation_id, kind="monitor", title="BTC below $50k") == notify.TOAST
        assert pushes == []
        [event] = published
        assert event["type"] == "notification.created"
        assert event["payload"] == {
            "kind": "monitor",
            "title": "BTC below $50k",
            "body": "The answer is 42.",
            "url": f"/c/{conversation_id}",
            "conversation_id": conversation_id,
        }
        assert event["scope"] == {"kind": "conversation", "id": conversation_id}
        assert _unread(db, conversation_id) is not None

    def test_a_hidden_tab_with_its_stream_open_gets_a_toast(
        self, db, conversation_id, fake_redis, published, pushes, push_on
    ):
        import time

        _subscribe(db)
        presence.report("u1", "t1", conversation_id, False)
        fake_redis.zadd(connection_leases_key("u1"), {"lease": time.time()})
        assert _call(conversation_id) == notify.TOAST
        assert pushes == []

    def test_no_tab_with_a_subscription_gets_a_push(
        self, db, conversation_id, fake_redis, published, pushes, push_on
    ):
        _subscribe(db)
        # The tab said it was hidden, then its stream closed: it is gone.
        presence.report("u1", "t1", conversation_id, False)
        assert _call(conversation_id, kind="approval", title="Deploy approved") == notify.PUSH
        assert published == []
        [(user_id, payload)] = pushes
        assert user_id == "u1"
        # A known kind leads with its heading; the caller's title moves into the body.
        assert payload["title"] == "Approval received"
        assert payload["body"].startswith("Deploy approved")
        assert payload["url"] == f"/c/{conversation_id}"
        assert payload["kind"] == "approval"
        assert _unread(db, conversation_id) is not None

    def test_no_tab_and_no_subscription_leaves_only_the_mark(
        self, db, conversation_id, fake_redis, published, pushes, push_on
    ):
        assert _call(conversation_id) == notify.STORED
        assert published == [] and pushes == []
        assert _unread(db, conversation_id) is not None

    def test_no_tab_with_push_off_leaves_only_the_mark(self, db, conversation_id, fake_redis, published, pushes):
        _subscribe(db)
        assert _call(conversation_id) == notify.STORED
        assert pushes == []

    def test_redis_down_counts_as_away(self, db, conversation_id, fake_redis, published, pushes, push_on):
        _subscribe(db)
        presence.report("u1", "t1", conversation_id, True)
        fake_redis.fail = True
        assert _call(conversation_id) == notify.PUSH
        assert _unread(db, conversation_id) is not None

    def test_a_toast_that_could_not_be_published_falls_back_to_push(
        self, db, conversation_id, fake_redis, pushes, push_on, monkeypatch
    ):
        monkeypatch.setattr(notify, "publish_user_event", lambda *a, **k: None)
        monkeypatch.setattr(settings, "ENABLE_SSE_PUSH", True)
        _subscribe(db)
        presence.report("u1", "t1", None, True)
        assert _call(conversation_id) == notify.PUSH

    def test_sse_off_goes_straight_to_push(self, db, conversation_id, fake_redis, published, pushes, push_on, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_SSE_PUSH", False)
        _subscribe(db)
        presence.report("u1", "t1", None, True)
        assert _call(conversation_id) == notify.PUSH
        assert published == []

    def test_another_users_subscription_is_not_used(self, db, conversation_id, fake_redis, published, pushes, push_on):
        _subscribe(db, user_id="u2")
        assert _call(conversation_id) == notify.STORED

    def test_without_a_conversation(self, db, fake_redis, published, pushes, push_on):
        presence.report("u1", "t1", None, True)
        assert _call(None, url="/") == notify.TOAST
        assert published[0]["scope"] == {"kind": "user"}
        assert published[0]["payload"]["conversation_id"] is None


class TestNeverRaises:
    def test_no_user(self):
        assert notify._notify(user_id="", conversation_id=None, kind="job", title="t", body="b", url="/") is None

    def test_any_failure_is_logged(self, monkeypatch):
        monkeypatch.setattr(notify, "_notify", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        notify.notify_user(user_id="u1", conversation_id="c", kind="job", title="t", body="b", url="/c/c")

    def test_mark_and_queue_failures_are_swallowed(self, fake_redis, published, push_on, monkeypatch):
        monkeypatch.setattr("docsgpt.storage.db.session.db_session", lambda: (_ for _ in ()).throw(RuntimeError("db")))
        monkeypatch.setattr(
            "docsgpt.storage.db.session.db_readonly", lambda: (_ for _ in ()).throw(RuntimeError("db"))
        )
        cid = "11111111-1111-1111-1111-111111111111"
        assert notify._notify(user_id="u1", conversation_id=cid, kind="job", title="t", body="b", url="/") == (
            notify.STORED
        )

    def test_a_broker_failure_is_not_a_push(self, db, conversation_id, fake_redis, published, push_on, monkeypatch):
        from docsgpt.notifications import tasks

        monkeypatch.setattr(tasks.send_web_push, "delay", lambda *a: (_ for _ in ()).throw(ConnectionError("broker")))
        _subscribe(db)
        assert _call(conversation_id) == notify.STORED


class TestContinuationCallsIt:
    def test_kind_is_the_first_wake_source_and_url_the_conversation(self, monkeypatch):
        from docsgpt.background import continuation

        calls = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: calls.append(kw))
        continuation._notify(
            {"user_id": "u1", "id": "c1"},
            [{"source": "trigger", "title": "Webhook hit"}, {"source": "job", "title": "x"}],
            "answer",
        )
        assert calls == [
            {
                "user_id": "u1",
                "conversation_id": "c1",
                "kind": "trigger",
                "title": "Webhook hit (+1 more)",
                "body": "answer",
                "url": "/c/c1",
            }
        ]

    def test_a_job_is_titled_by_its_conversation_never_by_the_tool(self, monkeypatch):
        from docsgpt.background import continuation

        calls = []
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: calls.append(kw))
        job_id = "5f0c2a8e-1b7d-4e6a-9c3f-2d8b7a6e5f41"
        wake = {"source": "job", "title": f"code_executor.run_code finished (job {job_id})"}
        continuation._notify({"user_id": "u1", "id": "c1", "name": "Weekly report"}, [wake], "42")
        assert calls[0]["title"] == "Weekly report"
        assert calls[0]["kind"] == "job"
        continuation._notify({"user_id": "u1", "id": "c1", "name": ""}, [wake], "42")
        # No name and no job to read: the kind's heading says it all.
        assert calls[1]["title"] == ""
