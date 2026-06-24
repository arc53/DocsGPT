"""Tests for ArtifactsRepository against a real Postgres instance."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from application.storage.db.repositories.artifacts import ArtifactsRepository


def _repo(conn) -> ArtifactsRepository:
    return ArtifactsRepository(conn)


def _conversation_id() -> str:
    return str(uuid.uuid4())


class TestCreateArtifact:
    def test_creates_identity_and_auto_v1(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        artifact = repo.create_artifact(
            "user-1",
            "presentation",
            conversation_id=conv,
            title="Q3 deck",
            metadata={"source": "chat"},
            mime_type="application/vnd.ms-powerpoint",
            filename="deck.pptx",
            storage_path="inputs/user-1/artifacts/x/v1/deck.pptx",
            size=1234,
            sha256="abc",
            spec={"slides": []},
        )
        assert artifact["user_id"] == "user-1"
        assert artifact["kind"] == "presentation"
        assert artifact["title"] == "Q3 deck"
        assert artifact["metadata"] == {"source": "chat"}
        assert artifact["current_version"] == 1
        assert artifact["id"] is not None
        assert artifact["_id"] == artifact["id"]

        v1 = repo.get_version(artifact["id"], 1)
        assert v1 is not None
        assert v1["version"] == 1
        assert v1["filename"] == "deck.pptx"
        assert v1["storage_path"] == "inputs/user-1/artifacts/x/v1/deck.pptx"
        assert v1["size"] == 1234
        assert v1["sha256"] == "abc"
        assert v1["spec"] == {"slides": []}

    def test_spec_only_version_allows_null_storage_path(self, pg_conn):
        repo = _repo(pg_conn)
        artifact = repo.create_artifact(
            "user-1",
            "document",
            workflow_run_id=_conversation_id(),
            spec={"body": "draft"},
        )
        v1 = repo.get_version(artifact["id"], 1)
        assert v1["storage_path"] is None
        assert v1["spec"] == {"body": "draft"}

    def test_produced_by_and_preview_round_trip(self, pg_conn):
        repo = _repo(pg_conn)
        artifact = repo.create_artifact(
            "user-1",
            "code",
            conversation_id=_conversation_id(),
            preview_text="head of output",
            produced_by={"tool_id": "code_executor", "session_id": "s1"},
        )
        v1 = repo.get_version(artifact["id"], 1)
        assert v1["preview_text"] == "head of output"
        assert v1["produced_by"] == {"tool_id": "code_executor", "session_id": "s1"}

    def test_missing_both_parents_rejected(self, pg_conn):
        repo = _repo(pg_conn)
        try:
            with pg_conn.begin_nested():
                repo.create_artifact("user-1", "document")
        except IntegrityError:
            pass
        else:
            pytest.fail("expected IntegrityError when no parent is present")


class TestGetArtifact:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        fetched = repo.get_artifact(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_missing_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get_artifact(str(uuid.uuid4())) is None

    def test_get_not_gated_on_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "owner", "document", conversation_id=_conversation_id()
        )
        # Parent-derived authz: the repository never filters reads by user_id.
        assert repo.get_artifact(created["id"])["user_id"] == "owner"


class TestGetArtifactInParent:
    def test_returns_when_parent_matches(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        created = repo.create_artifact("user-1", "document", conversation_id=conv)
        fetched = repo.get_artifact_in_parent(created["id"], conversation_id=conv)
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_returns_none_on_parent_mismatch(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        # Correct id but a different conversation -> denied (no cross-parent leak).
        assert repo.get_artifact_in_parent(created["id"], conversation_id=_conversation_id()) is None

    def test_requires_a_parent(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        with pytest.raises(ValueError):
            repo.get_artifact_in_parent(created["id"])


class TestAppendVersion:
    def test_increments_current_version(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        assert created["current_version"] == 1

        v2 = repo.append_version(created["id"], spec={"body": "edit"}, filename="d.md")
        assert v2["version"] == 2

        refreshed = repo.get_artifact(created["id"])
        assert refreshed["current_version"] == 2
        assert refreshed["updated_at"] >= created["updated_at"]

    def test_two_appends_yield_v2_then_v3(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        assert repo.append_version(created["id"])["version"] == 2
        assert repo.append_version(created["id"])["version"] == 3
        assert repo.get_artifact(created["id"])["current_version"] == 3

    def test_append_to_missing_artifact_raises(self, pg_conn):
        repo = _repo(pg_conn)
        with pytest.raises(ValueError):
            repo.append_version(str(uuid.uuid4()))

    def test_duplicate_version_raises(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        # Force a collision on (artifact_id, version) by re-inserting v1.
        try:
            with pg_conn.begin_nested():
                repo._insert_version(
                    artifact_id=created["id"],
                    version=1,
                    mime_type=None,
                    filename=None,
                    storage_path=None,
                    size=None,
                    sha256=None,
                    spec=None,
                    preview_text=None,
                    produced_by=None,
                )
        except IntegrityError:
            pass
        else:
            pytest.fail("expected IntegrityError on duplicate (artifact_id, version)")


class TestListArtifacts:
    def test_filters_by_conversation(self, pg_conn):
        repo = _repo(pg_conn)
        conv_a = _conversation_id()
        conv_b = _conversation_id()
        repo.create_artifact("user-1", "document", conversation_id=conv_a)
        repo.create_artifact("user-1", "document", conversation_id=conv_a)
        repo.create_artifact("user-1", "document", conversation_id=conv_b)

        assert len(repo.list_artifacts(conversation_id=conv_a)) == 2
        assert len(repo.list_artifacts(conversation_id=conv_b)) == 1

    def test_filters_by_workflow_run(self, pg_conn):
        repo = _repo(pg_conn)
        run = _conversation_id()
        repo.create_artifact("user-1", "document", workflow_run_id=run)
        repo.create_artifact("user-1", "document", conversation_id=_conversation_id())
        assert len(repo.list_artifacts(workflow_run_id=run)) == 1

    def test_filters_by_user(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        repo.create_artifact("alice", "document", conversation_id=conv)
        repo.create_artifact("bob", "document", conversation_id=conv)
        assert len(repo.list_artifacts(conversation_id=conv, user_id="alice")) == 1

    def test_requires_at_least_one_filter(self, pg_conn):
        repo = _repo(pg_conn)
        with pytest.raises(ValueError):
            repo.list_artifacts()


class TestQuotaAccounting:
    def test_count_for_user_counts_only_that_user(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        repo.create_artifact("alice", "document", conversation_id=conv)
        repo.create_artifact("alice", "document", conversation_id=conv)
        repo.create_artifact("bob", "document", conversation_id=conv)
        assert repo.count_for_user("alice") == 2
        assert repo.count_for_user("bob") == 1
        assert repo.count_for_user("nobody") == 0

    def test_total_bytes_sums_all_versions(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        a = repo.create_artifact("alice", "document", conversation_id=conv, size=100)
        repo.append_version(a["id"], size=250)  # +250 -> 350 for the same artifact
        repo.create_artifact("alice", "document", conversation_id=conv, size=50)
        repo.create_artifact("bob", "document", conversation_id=conv, size=999)
        assert repo.total_bytes_for_user("alice") == 400
        assert repo.total_bytes_for_user("bob") == 999

    def test_total_bytes_zero_for_unknown_user(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.total_bytes_for_user("nobody") == 0

    def test_total_bytes_treats_null_size_as_zero(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create_artifact("alice", "document", conversation_id=_conversation_id())
        assert repo.total_bytes_for_user("alice") == 0


class TestQuotaEnforcement:
    """Exercises the shared enforcement helper against a real repo + connection."""

    def _seed(self, pg_conn, *, count: int, size: int) -> None:
        repo = _repo(pg_conn)
        for _ in range(count):
            repo.create_artifact("alice", "document", conversation_id=_conversation_id(), size=size)

    def test_under_quota_passes(self, pg_conn, monkeypatch):
        from application.sandbox import artifacts_capture as ac

        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_COUNT_PER_USER", 10, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 10_000, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_BYTES", 10_000, raising=False)
        self._seed(pg_conn, count=2, size=100)
        # 2 existing + 1 new = 3 <= 10; 200 + 100 = 300 <= 10000. Must not raise.
        ac._enforce_user_quota(_repo(pg_conn), "alice", 100, new_artifact=True)

    def test_over_count_quota_raises(self, pg_conn, monkeypatch):
        from application.sandbox import artifacts_capture as ac

        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_COUNT_PER_USER", 2, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 10_000_000, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_BYTES", 10_000_000, raising=False)
        self._seed(pg_conn, count=2, size=10)
        with pytest.raises(ac.QuotaExceeded):
            ac._enforce_user_quota(_repo(pg_conn), "alice", 10, new_artifact=True)

    def test_count_quota_ignored_when_appending_version(self, pg_conn, monkeypatch):
        from application.sandbox import artifacts_capture as ac

        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_COUNT_PER_USER", 2, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 10_000_000, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_BYTES", 10_000_000, raising=False)
        self._seed(pg_conn, count=2, size=10)
        # Appending a version to an existing identity must not trip the count cap.
        ac._enforce_user_quota(_repo(pg_conn), "alice", 10, new_artifact=False)

    def test_over_total_bytes_quota_raises(self, pg_conn, monkeypatch):
        from application.sandbox import artifacts_capture as ac

        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_COUNT_PER_USER", 10_000, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 500, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_BYTES", 10_000, raising=False)
        self._seed(pg_conn, count=1, size=450)
        with pytest.raises(ac.QuotaExceeded):
            ac._enforce_user_quota(_repo(pg_conn), "alice", 100, new_artifact=True)  # 450 + 100 > 500

    def test_single_artifact_too_large_raises(self, pg_conn, monkeypatch):
        from application.sandbox import artifacts_capture as ac

        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_COUNT_PER_USER", 10_000, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 10_000_000, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_BYTES", 1000, raising=False)
        with pytest.raises(ac.QuotaExceeded):
            ac._enforce_user_quota(_repo(pg_conn), "alice", 1001, new_artifact=True)

    def test_zero_settings_disable_enforcement(self, pg_conn, monkeypatch):
        from application.sandbox import artifacts_capture as ac

        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_COUNT_PER_USER", 0, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 0, raising=False)
        monkeypatch.setattr(ac.settings, "ARTIFACT_MAX_BYTES", 0, raising=False)
        self._seed(pg_conn, count=5, size=10_000)
        ac._enforce_user_quota(_repo(pg_conn), "alice", 10_000_000, new_artifact=True)  # disabled -> no raise


class TestVirtualRefPositions:
    """Parent-scoped 1-based positions that back the short ``A{n}`` refs."""

    @staticmethod
    def _stamp(pg_conn, artifact_id: str, seconds: int) -> None:
        """Give an artifact a distinct created_at so ordering is deterministic in one txn.

        In production each persist is its own transaction (distinct ``now()``); the
        repo test seeds several rows in a single transaction where ``now()`` collides,
        so explicit timestamps make the created_at ordering testable.
        """
        pg_conn.execute(
            text(
                "UPDATE artifacts SET created_at = TIMESTAMPTZ '2026-01-01 00:00:00+00' "
                "+ (:s || ' seconds')::interval WHERE id = CAST(:id AS uuid)"
            ),
            {"s": seconds, "id": artifact_id},
        )

    def test_position_and_id_round_trip_in_order(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        a = repo.create_artifact("u", "document", conversation_id=conv)
        b = repo.create_artifact("u", "document", conversation_id=conv)
        c = repo.create_artifact("u", "document", conversation_id=conv)
        for idx, art in enumerate((a, b, c)):
            self._stamp(pg_conn, art["id"], idx)

        assert repo.position_in_parent(a["id"], conversation_id=conv) == 1
        assert repo.position_in_parent(b["id"], conversation_id=conv) == 2
        assert repo.position_in_parent(c["id"], conversation_id=conv) == 3

        assert repo.artifact_id_at_position(1, conversation_id=conv) == a["id"]
        assert repo.artifact_id_at_position(2, conversation_id=conv) == b["id"]
        assert repo.artifact_id_at_position(3, conversation_id=conv) == c["id"]

    def test_position_is_parent_scoped(self, pg_conn):
        repo = _repo(pg_conn)
        conv_a = _conversation_id()
        conv_b = _conversation_id()
        a1 = repo.create_artifact("u", "document", conversation_id=conv_a)
        a2 = repo.create_artifact("u", "document", conversation_id=conv_a)
        b1 = repo.create_artifact("u", "document", conversation_id=conv_b)
        for idx, art in enumerate((a1, a2, b1)):
            self._stamp(pg_conn, art["id"], idx)

        # Each parent numbers from 1 independently.
        assert repo.position_in_parent(a2["id"], conversation_id=conv_a) == 2
        assert repo.position_in_parent(b1["id"], conversation_id=conv_b) == 1
        # An artifact is invisible (position 0) under the wrong parent.
        assert repo.position_in_parent(a2["id"], conversation_id=conv_b) == 0

    def test_id_at_position_does_not_cross_parents(self, pg_conn):
        repo = _repo(pg_conn)
        conv_a = _conversation_id()
        conv_b = _conversation_id()
        a1 = repo.create_artifact("u", "document", conversation_id=conv_a)
        # conv_b has no artifacts, so its A1 resolves to nothing (no leak from conv_a).
        assert repo.artifact_id_at_position(1, conversation_id=conv_a) == a1["id"]
        assert repo.artifact_id_at_position(1, conversation_id=conv_b) is None

    def test_out_of_range_and_invalid_position_return_none(self, pg_conn):
        repo = _repo(pg_conn)
        conv = _conversation_id()
        repo.create_artifact("u", "document", conversation_id=conv)
        assert repo.artifact_id_at_position(2, conversation_id=conv) is None
        assert repo.artifact_id_at_position(0, conversation_id=conv) is None
        assert repo.artifact_id_at_position(-1, conversation_id=conv) is None

    def test_workflow_run_parent_supported(self, pg_conn):
        repo = _repo(pg_conn)
        run = _conversation_id()
        a = repo.create_artifact("u", "document", workflow_run_id=run)
        assert repo.position_in_parent(a["id"], workflow_run_id=run) == 1
        assert repo.artifact_id_at_position(1, workflow_run_id=run) == a["id"]

    def test_position_helpers_require_a_parent(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact("u", "document", conversation_id=_conversation_id())
        with pytest.raises(ValueError):
            repo.position_in_parent(created["id"])
        with pytest.raises(ValueError):
            repo.artifact_id_at_position(1)


class TestCascadeDelete:
    def test_deleting_artifact_removes_versions(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create_artifact(
            "user-1", "document", conversation_id=_conversation_id()
        )
        repo.append_version(created["id"])
        assert len(repo.list_versions(created["id"])) == 2

        pg_conn.execute(
            text("DELETE FROM artifacts WHERE id = CAST(:id AS uuid)"),
            {"id": created["id"]},
        )
        assert repo.get_artifact(created["id"]) is None
        assert repo.list_versions(created["id"]) == []
