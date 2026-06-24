"""Unit tests for the virtual short artifact-ref helpers (make_ref / parse_ref / resolve_artifact_id).

No DB: ``resolve_artifact_id`` is exercised against a tiny fake repo that records the
parent scope it was asked for, proving a ref resolves only within the caller's parent.
"""

from __future__ import annotations

import uuid

from application.agents.tools.artifact_ref import make_ref, parse_ref, resolve_artifact_id


class _FakeRepo:
    """Records the position lookup and returns a canned id only for the scoped parent."""

    def __init__(self, *, mapping=None, conv=None, run=None):
        self.mapping = mapping or {}
        self.conv = conv
        self.run = run
        self.calls = []

    def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
        self.calls.append((n, conversation_id, workflow_run_id))
        if self.conv is not None and conversation_id != self.conv:
            return None
        if self.run is not None and workflow_run_id != self.run:
            return None
        return self.mapping.get(n)


# ---------------------------------------------------------------------------
# make_ref / parse_ref
# ---------------------------------------------------------------------------
def test_make_ref_formats_position():
    assert make_ref(1) == "A1"
    assert make_ref(2) == "A2"
    assert make_ref(42) == "A42"


def test_parse_ref_round_trips_make_ref():
    for n in (1, 2, 9, 10, 137):
        assert parse_ref(make_ref(n)) == n


def test_parse_ref_is_case_insensitive_and_trims():
    assert parse_ref("a1") == 1
    assert parse_ref("A3") == 3
    assert parse_ref("  A7  ") == 7


def test_parse_ref_rejects_non_refs():
    assert parse_ref("A0") is None  # 1-based; position 0 is not a ref
    assert parse_ref("A") is None
    assert parse_ref("AA1") is None
    assert parse_ref("1") is None
    assert parse_ref("B1") is None
    assert parse_ref(str(uuid.uuid4())) is None  # a uuid is not a ref
    assert parse_ref(None) is None
    assert parse_ref(7) is None


# ---------------------------------------------------------------------------
# resolve_artifact_id
# ---------------------------------------------------------------------------
def test_resolve_ref_uses_parent_scoped_position():
    target = str(uuid.uuid4())
    repo = _FakeRepo(mapping={1: target}, conv="conv-1")
    out = resolve_artifact_id(repo, "A1", conversation_id="conv-1")
    assert out == target
    assert repo.calls == [(1, "conv-1", None)]


def test_resolve_ref_does_not_cross_parents():
    target = str(uuid.uuid4())
    # The repo only yields the id for conv-1; asking under conv-OTHER yields nothing.
    repo = _FakeRepo(mapping={1: target}, conv="conv-1")
    assert resolve_artifact_id(repo, "A1", conversation_id="conv-OTHER") is None


def test_resolve_out_of_range_ref_returns_none():
    repo = _FakeRepo(mapping={1: str(uuid.uuid4())}, conv="conv-1")
    assert resolve_artifact_id(repo, "A9", conversation_id="conv-1") is None


def test_resolve_uuid_passthrough_without_touching_repo():
    raw = str(uuid.uuid4())
    repo = _FakeRepo(conv="conv-1")
    assert resolve_artifact_id(repo, raw, conversation_id="conv-1") == raw
    # A uuid never triggers a position lookup.
    assert repo.calls == []


def test_resolve_garbage_returns_none():
    repo = _FakeRepo(conv="conv-1")
    assert resolve_artifact_id(repo, "not-a-ref-or-uuid", conversation_id="conv-1") is None
    assert resolve_artifact_id(repo, "", conversation_id="conv-1") is None


def test_resolve_ref_under_workflow_run_parent():
    target = str(uuid.uuid4())
    repo = _FakeRepo(mapping={2: target}, run="run-9")
    assert resolve_artifact_id(repo, "A2", workflow_run_id="run-9") == target
    assert repo.calls == [(2, None, "run-9")]
