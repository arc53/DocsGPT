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
