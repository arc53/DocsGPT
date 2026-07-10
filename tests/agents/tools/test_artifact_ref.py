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


# ---------------------------------------------------------------------------
# Stable per-parent ref_seq: a ref no longer re-points after an earlier delete
# ---------------------------------------------------------------------------
class _SeqRepo:
    """Fake repo backing resolve_id_by_ref_seq (stable) with the legacy positional fallback."""

    def __init__(self, *, seq_map=None, pos_map=None, conv=None, run=None):
        self.seq_map = seq_map or {}
        self.pos_map = pos_map or {}
        self.conv = conv
        self.run = run
        self.seq_calls = []
        self.pos_calls = []

    def _in_scope(self, conversation_id, workflow_run_id) -> bool:
        if self.conv is not None and conversation_id != self.conv:
            return False
        if self.run is not None and workflow_run_id != self.run:
            return False
        return True

    def resolve_id_by_ref_seq(self, seq, *, conversation_id=None, workflow_run_id=None):
        self.seq_calls.append((seq, conversation_id, workflow_run_id))
        if not self._in_scope(conversation_id, workflow_run_id):
            return None
        return self.seq_map.get(seq)

    def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
        self.pos_calls.append((n, conversation_id, workflow_run_id))
        if not self._in_scope(conversation_id, workflow_run_id):
            return None
        return self.pos_map.get(n)


def test_ref_resolves_by_stable_seq_not_shifted_position():
    b, c = str(uuid.uuid4()), str(uuid.uuid4())
    # After deleting the earlier A(seq 1): ref_seq keeps B=2/C=3; positions shifted to B=1/C=2.
    repo = _SeqRepo(seq_map={2: b, 3: c}, pos_map={1: b, 2: c}, conv="conv-1")
    assert resolve_artifact_id(repo, "A2", conversation_id="conv-1") == b
    assert resolve_artifact_id(repo, "A3", conversation_id="conv-1") == c
    # The stable ref_seq hit; the (shifted) positional fallback was never consulted.
    assert repo.pos_calls == []


def test_ref_falls_back_to_position_for_legacy_rows():
    legacy = str(uuid.uuid4())
    # Legacy row has no ref_seq -> resolve_id_by_ref_seq misses -> positional fallback resolves it.
    repo = _SeqRepo(seq_map={}, pos_map={1: legacy}, conv="conv-1")
    assert resolve_artifact_id(repo, "A1", conversation_id="conv-1") == legacy
    assert repo.seq_calls == [(1, "conv-1", None)]
    assert repo.pos_calls == [(1, "conv-1", None)]


def test_ref_seq_does_not_cross_parents():
    b = str(uuid.uuid4())
    repo = _SeqRepo(seq_map={2: b}, pos_map={2: b}, conv="conv-1")
    assert resolve_artifact_id(repo, "A2", conversation_id="conv-OTHER") is None
