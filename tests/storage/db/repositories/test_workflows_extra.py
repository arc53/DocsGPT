"""Extra tests for WorkflowsRepository."""


class TestWorkflowsDeleteByLegacy:
    def test_delete_by_legacy_id_returns_true(self, pg_conn):
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        repo = WorkflowsRepository(pg_conn)
        repo.create(
            "u", "w", legacy_mongo_id="leg-wf",
        )
        got = repo.delete_by_legacy_id("leg-wf", "u")
        assert got is True

    def test_delete_by_legacy_id_no_match(self, pg_conn):
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        got = WorkflowsRepository(pg_conn).delete_by_legacy_id(
            "no-match", "u",
        )
        assert got is False

    def test_delete_by_legacy_id_wrong_user(self, pg_conn):
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )
        repo = WorkflowsRepository(pg_conn)
        repo.create(
            "owner", "w", legacy_mongo_id="leg-wrong",
        )
        got = repo.delete_by_legacy_id("leg-wrong", "other-user")
        assert got is False
