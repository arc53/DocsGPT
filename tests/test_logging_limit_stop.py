"""The operator activity log names a run stopped by a limit apart from a run out of time."""

import time

import pytest

from docsgpt.logging import LogContext, _emit_activity_finished
from docsgpt.quotas.agent_limits import AgentLimitExceeded
from docsgpt.quotas.run_limits import RunLimitReached


def _finished(caplog, error):
    context = LogContext("chat", "activity", "u", None, "q")
    with caplog.at_level("INFO"):
        _emit_activity_finished(context=context, parent_activity_id=None, started_at=time.monotonic(), error=error)
    return next(r for r in caplog.records if r.msg == "activity_finished")


@pytest.mark.unit
def test_a_limit_stop_is_labelled_as_a_limit_not_a_time_limit(caplog):
    exceeded = AgentLimitExceeded(agent_id="a1", dimension="tokens", usage=10, limit=10)

    event = _finished(caplog, RunLimitReached(exceeded))

    assert event.status == "error"
    assert event.error_class == "LimitReached"


@pytest.mark.unit
def test_a_time_limit_keeps_its_label(caplog):
    from celery.exceptions import SoftTimeLimitExceeded

    assert _finished(caplog, SoftTimeLimitExceeded()).error_class == "TimeLimit"
