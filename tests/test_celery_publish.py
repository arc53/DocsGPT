import types
from unittest.mock import MagicMock

import celery
import pytest
from kombu.transport import redis as kombu_redis

from docsgpt.celery_publish import Celery


def closed_channel_error() -> AttributeError:
    """The error kombu's Redis channel raises once a reconnect has closed it (celery/kombu#2804)."""
    try:
        kombu_redis.Channel._connparams(types.SimpleNamespace(connection=None))
    except AttributeError as exc:
        return exc
    raise AssertionError("kombu no longer fails this way; the retry in docsgpt.celery_publish can go")


@pytest.fixture
def app():
    return Celery("publish-test", broker="memory://", set_as_current=False)


@pytest.fixture
def base_send(monkeypatch):
    """Celery's own send_task, replaced by a mock the test scripts."""
    send = MagicMock(name="celery.Celery.send_task")
    monkeypatch.setattr(celery.Celery, "send_task", send)
    return send


@pytest.mark.unit
def test_a_publish_on_a_channel_kombu_closed_is_sent_again(app, base_send, caplog):
    result = object()
    base_send.side_effect = [closed_channel_error(), result]

    assert app.send_task("docsgpt.some.task", ["a"], {"b": 1}, queue="ingest") is result

    assert base_send.call_count == 2
    first, second = base_send.call_args_list
    assert first == second  # the same message
    assert first.kwargs["task_id"]  # under one id: whatever recorded the first attempt matches the second
    assert first.kwargs["queue"] == "ingest"
    assert "docsgpt.some.task" in caplog.text


@pytest.mark.unit
def test_the_callers_task_id_is_kept(app, base_send):
    base_send.side_effect = [closed_channel_error(), object()]

    app.send_task("docsgpt.some.task", task_id="given-id")

    assert [call.kwargs["task_id"] for call in base_send.call_args_list] == ["given-id", "given-id"]


@pytest.mark.unit
def test_a_publish_that_fails_twice_raises(app, base_send):
    base_send.side_effect = [closed_channel_error(), closed_channel_error()]

    with pytest.raises(AttributeError, match="'client'"):
        app.send_task("docsgpt.some.task")

    assert base_send.call_count == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [AttributeError("'Task' object has no attribute 'nope'"), ConnectionError("broker down"), ValueError("bad args")],
    ids=lambda exc: type(exc).__name__,
)
def test_other_errors_are_not_retried(app, base_send, error):
    base_send.side_effect = error

    with pytest.raises(type(error)):
        app.send_task("docsgpt.some.task")

    assert base_send.call_count == 1


@pytest.mark.unit
def test_a_task_is_published_through_the_retry(app, base_send):
    @app.task(name="docsgpt.some.task")
    def some_task():
        return None

    result = object()
    base_send.side_effect = [closed_channel_error(), result]

    assert some_task.apply_async() is result
    assert base_send.call_count == 2


@pytest.mark.unit
def test_the_app_is_built_with_the_retry():
    from docsgpt import celery_init

    assert celery_init.Celery is Celery
    assert isinstance(celery_init.celery, Celery)
