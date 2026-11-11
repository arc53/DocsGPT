"""Tests for docsgpt/api/user/task_owners.py."""

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.store[key] = value.encode() if isinstance(value, str) else value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.store.get(key)


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def fake_redis():
    redis = _FakeRedis()
    with patch("docsgpt.api.user.task_owners.get_redis_instance", return_value=redis):
        yield redis


INGEST = "docsgpt.api.user.tasks.ingest"


class TestRecordOnPublish:
    def test_records_session_user(self, app, fake_redis):
        from docsgpt.api.user.task_owners import record_on_publish
        from docsgpt.celeryconfig import result_expires

        with app.test_request_context("/api/upload"):
            request.decoded_token = {"sub": "alice"}
            record_on_publish(sender=INGEST, headers={"id": "t-1"})
        assert fake_redis.store["task_owner:t-1"] == b"alice"
        assert fake_redis.ttls["task_owner:t-1"] == result_expires

    def test_sessionless_request_records_capability(self, app, fake_redis):
        from docsgpt.api.user.task_owners import record_on_publish

        with app.test_request_context("/api/webhooks/agents/tok"):
            request.decoded_token = None
            record_on_publish(sender=INGEST, headers={"id": "t-2"})
        assert fake_redis.store["task_owner:t-2"] == b""

    def test_outside_request_records_nothing(self, fake_redis):
        from docsgpt.api.user.task_owners import record_on_publish

        record_on_publish(sender=INGEST, headers={"id": "t-3"})
        assert fake_redis.store == {}

    def test_skips_query_embedding(self, app, fake_redis):
        from docsgpt.api.user.task_owners import record_on_publish

        with app.test_request_context("/stream"):
            request.decoded_token = {"sub": "alice"}
            record_on_publish(
                sender="docsgpt.vectorstore.embeddings_tasks.embed_texts", headers={"id": "t-4"}
            )
        assert fake_redis.store == {}

    def test_redis_absent_is_silent(self, app):
        from docsgpt.api.user.task_owners import record_on_publish

        with patch("docsgpt.api.user.task_owners.get_redis_instance", return_value=None), \
                app.test_request_context("/api/upload"):
            request.decoded_token = {"sub": "alice"}
            record_on_publish(sender=INGEST, headers={"id": "t-5"})

    def test_redis_error_is_silent(self, app):
        from docsgpt.api.user.task_owners import record_on_publish

        broken = MagicMock()
        broken.set.side_effect = ConnectionError("down")
        with patch("docsgpt.api.user.task_owners.get_redis_instance", return_value=broken), \
                app.test_request_context("/api/upload"):
            request.decoded_token = {"sub": "alice"}
            record_on_publish(sender=INGEST, headers={"id": "t-6"})

    def test_connected_to_before_task_publish(self, app, fake_redis):
        from celery.signals import before_task_publish

        import docsgpt.celery_init  # noqa: F401 -- wires the signal

        with app.test_request_context("/api/upload"):
            request.decoded_token = {"sub": "alice"}
            before_task_publish.send(sender=INGEST, headers={"id": "t-7"}, body=((), {}, {}))
        assert fake_redis.store["task_owner:t-7"] == b"alice"


class TestGetTaskOwner:
    def test_unknown_task_is_none(self, fake_redis):
        from docsgpt.api.user.task_owners import get_task_owner

        assert get_task_owner("nope") is None

    def test_returns_recorded_owner(self, fake_redis):
        from docsgpt.api.user.task_owners import get_task_owner

        fake_redis.store["task_owner:t-1"] = b"alice"
        fake_redis.store["task_owner:t-2"] = b""
        assert get_task_owner("t-1") == "alice"
        assert get_task_owner("t-2") == ""

    def test_redis_absent_raises(self):
        from docsgpt.api.user.task_owners import TaskOwnersUnavailable, get_task_owner

        with patch("docsgpt.api.user.task_owners.get_redis_instance", return_value=None):
            with pytest.raises(TaskOwnersUnavailable):
                get_task_owner("t-1")

    def test_redis_error_raises(self):
        from docsgpt.api.user.task_owners import TaskOwnersUnavailable, get_task_owner

        broken = MagicMock()
        broken.get.side_effect = ConnectionError("down")
        with patch("docsgpt.api.user.task_owners.get_redis_instance", return_value=broken):
            with pytest.raises(TaskOwnersUnavailable):
                get_task_owner("t-1")
