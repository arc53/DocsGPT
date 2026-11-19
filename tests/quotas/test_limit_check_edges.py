"""Where the per-call limit check applies inside a run, and where it deliberately doesn't.

The guardrail judge guards the run's own output: refused at the limit, it would let the answer that crossed it out
unjudged (fail-open) or block a paid answer with the guardrail's message (fail-closed). So its call is counted to the
run but never refused. A provider fallback, and the stream's same-model retry, are new model calls: each is checked
again, so a primary that recorded usage and then failed can't let them run past the limit.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docsgpt.guardrails.base import ScanContext
from docsgpt.guardrails.checks.judge import PolicyCheck
from docsgpt.guardrails.types import Stage
from docsgpt.llm.base import BaseLLM
from docsgpt.quotas.payer import billed_to, current_run_billing
from docsgpt.quotas.run_limits import RunLimitReached


class _Limits:
    """Limits whose check refuses from the ``refuse_from``-th call on (1-based), counting every check."""

    def __init__(self, refuse_from: int = 1):
        self.refuse_from = refuse_from
        self.checks = 0
        self.reached = None

    def check_call(self) -> None:
        self.checks += 1
        if self.checks >= self.refuse_from:
            raise RunLimitReached(MagicMock(name="exceeded"))


@pytest.mark.unit
class TestTheJudgeAtTheLimit:
    def test_the_judge_is_counted_to_the_run_but_not_refused(self):
        seen = {}

        def _gen(**_kw):
            billing = current_run_billing()
            seen["billing"] = billing
            # As every model call does: the run's limits, before the call.
            if billing.limits is not None:
                billing.limits.check_call()
            return '{"violation": false, "confidence": 0.1, "reason": "fine"}'

        llm = MagicMock(model_id="judge")
        llm.gen.side_effect = _gen
        check = PolicyCheck({"policy": "Never talk about the weather."})
        limits = _Limits()

        with billed_to("lena", "req-1", kind="published", team_id="team-1", limits=limits):
            outcome = check.scan("an answer", Stage.OUTPUT, ScanContext(llm_factory=lambda _model: llm))
            after = current_run_billing()

        assert outcome.evaluated is True
        assert outcome.triggered is False and outcome.detail == "fine"
        billing = seen["billing"]
        assert (billing.payer, billing.kind, billing.team_id, billing.request_id) == (
            "lena", "published", "team-1", "req-1"
        )
        assert limits.checks == 0
        # The run's limits are back once the judge is done.
        assert after.limits is limits


class _FailingLLM(BaseLLM):
    """A primary whose call fails, with a fallback that answers."""

    provider_name = "primary"

    def __init__(self, fallback=None):
        super().__init__()
        self.model_id = "primary-model"
        self._fallback = fallback

    @property
    def fallback_llm(self):
        return self._fallback

    def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kwargs):
        raise RuntimeError("primary failed")

    def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kwargs):
        raise RuntimeError("primary failed")
        yield  # pragma: no cover


class _Fallback(_FailingLLM):
    provider_name = "fallback"

    def __init__(self):
        super().__init__()
        self.model_id = "fallback-model"
        self.calls = 0

    def _raw_gen(self, baseself, model, messages, stream=False, tools=None, **kwargs):
        self.calls += 1
        return "fallback answer"

    def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kwargs):
        self.calls += 1
        yield "fallback answer"


@pytest.mark.unit
class TestTheFallbackIsChecked:
    def _run(self, method, limits, monkeypatch):
        fallback = _Fallback()
        primary = _FailingLLM(fallback)
        monkeypatch.setattr(primary, "_fallback_request", lambda fb, kwargs, error: dict(kwargs))
        with billed_to("lena", kind="chat", limits=limits):
            if method == "_raw_gen":
                result = primary._execute_with_fallback(method, [], model="primary-model", messages=[])
            else:
                result = list(primary._execute_with_fallback(method, [], model="primary-model", messages=[]))
        return fallback, result

    @pytest.mark.parametrize("method", ["_raw_gen", "_raw_gen_stream"])
    def test_a_fallback_past_the_limit_is_refused(self, method, monkeypatch):
        limits = _Limits(refuse_from=2)

        with pytest.raises(RunLimitReached):
            self._run(method, limits, monkeypatch)

        assert limits.checks == 2

    @pytest.mark.parametrize("method", ["_raw_gen", "_raw_gen_stream"])
    def test_a_fallback_within_the_limit_answers(self, method, monkeypatch):
        limits = _Limits(refuse_from=99)

        fallback, result = self._run(method, limits, monkeypatch)

        assert fallback.calls == 1
        assert limits.checks == 2
        assert "fallback answer" in (result if isinstance(result, str) else "".join(map(str, result)))


class _DroppedStream(_FailingLLM):
    """A primary whose stream drops before any output, so the stream retries it once."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def _raw_gen_stream(self, baseself, model, messages, stream=True, tools=None, **kwargs):
        import httpx

        self.calls += 1
        raise httpx.RemoteProtocolError("peer closed the stream")
        yield  # pragma: no cover


@pytest.mark.unit
class TestTheStreamRetryIsChecked:
    def test_a_retry_past_the_limit_is_refused(self):
        primary = _DroppedStream()
        limits = _Limits(refuse_from=2)

        with billed_to("lena", kind="chat", limits=limits), pytest.raises(RunLimitReached):
            list(primary._execute_with_fallback("_raw_gen_stream", [], model="primary-model", messages=[]))

        assert primary.calls == 1


@pytest.mark.unit
class TestARunCrossingAPeriodReset:
    def test_it_counts_from_the_new_period_once_the_old_one_ended(self, monkeypatch):
        from contextlib import nullcontext
        from datetime import datetime, timedelta, timezone

        from docsgpt.quotas import run_limits
        from docsgpt.quotas.resolver import ResolvedLimit, ResolvedLimits

        from docsgpt.core.settings import settings
        from docsgpt.quotas.windows import window_bounds

        # The run started in the previous period, which has since ended.
        old_reset, _ = window_bounds(settings.QUOTA_PERIOD, datetime.now(timezone.utc))
        old_start = old_reset - timedelta(days=40)
        starts = []

        class _Usage:
            def __init__(self, _conn):
                pass

            def usage_totals_for_buckets(self, user_id, start, buckets):
                starts.append(start)
                # The old period's spend is over the limit; the new one's is not.
                used = 150 if start < old_reset else 10
                return {bucket: (used, 0.0) for bucket in buckets}

        monkeypatch.setattr(run_limits, "TokenUsageRepository", _Usage)
        monkeypatch.setattr(run_limits, "db_readonly", lambda: nullcontext(None))
        limits = run_limits.RunLimits(
            "lena",
            limits={"all": ResolvedLimits(tokens=ResolvedLimit(100, "user"), cost=ResolvedLimit())},
            window_start=old_start,
            resets_at=old_reset,
        )

        limits.check_call()

        assert starts and starts[-1] >= old_reset
