"""Test doubles shared by the monitor tests."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Dict


class FakeRedis:
    """Just enough of redis-py for fixed-window counters and markers."""

    def __init__(self) -> None:
        self.values: Dict[str, int] = {}
        self.expiry: Dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        if key in self.expiry and self.expiry[key] <= time.time():
            self.values.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.values

    def incr(self, key: str) -> int:
        self._alive(key)
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int, nx: bool = False) -> bool:
        if nx and key in self.expiry:
            return False
        self.expiry[key] = time.time() + seconds
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and self._alive(key):
            return None
        self.values[key] = value
        if ex:
            self.expiry[key] = time.time() + ex
        return True

    def delete(self, key):
        self.values.pop(key, None)
        self.expiry.pop(key, None)

    def pipeline(self):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list = []

    def incr(self, key):
        self.ops.append(("incr", key))
        return self

    def expire(self, key, seconds, nx=False):
        self.ops.append(("expire", key, seconds, nx))
        return self

    def execute(self):
        out = []
        for op in self.ops:
            if op[0] == "incr":
                out.append(self.redis.incr(op[1]))
            else:
                out.append(self.redis.expire(op[1], op[2], nx=op[3]))
        return out



def executor_stub(*, call_id: str = "call-1", approved: bool = False, **extra) -> SimpleNamespace:
    """A chat turn's executor as the monitor tool sees it."""
    fields = dict(
        user="u1",
        agent_id=None,
        conversation_id=None,
        headless=False,
        external_caller=False,
        public_link_caller=False,
        workflow_run_id=None,
        background=None,
        current_call_id=call_id,
        approved_call_ids={call_id} if approved else set(),
    )
    fields.update(extra)
    return SimpleNamespace(**fields)
