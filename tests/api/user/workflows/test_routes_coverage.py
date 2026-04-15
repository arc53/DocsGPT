"""Targeted coverage tests for uncovered lines in application/api/user/workflows/routes.py.

Covers:
- _dual_write_workflow_create inner _do callback (lines 73-80)
- _dual_write_workflow_update inner _do callback (lines 102-115)
- _dual_write_workflow_delete inner _do callback (lines 130-132)
- _resolve_pg_workflow (lines 139-144)
- _write_graph (lines 162-207)
- create_workflow_nodes with empty nodes (line 513)
- WorkflowDetail.put invalid-id branch (line 638)
- WorkflowDetail.put update_one failure cleanup (lines 690-696)
- WorkflowDetail.put old-versions cleanup exception branch (lines 705-706)
"""

from unittest.mock import MagicMock, Mock, call, patch

import pytest
from bson import ObjectId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_dual_write_callback(fn, captured):
    """Execute the callback that was passed to dual_write with a mock repo."""
    repo = captured[0]
    fn(repo)


# ---------------------------------------------------------------------------
# _resolve_pg_workflow
# ---------------------------------------------------------------------------


class TestResolvePgWorkflow:
    @pytest.mark.unit
    def test_returns_workflow_dict_when_found(self):
        from application.api.user.workflows.routes import _resolve_pg_workflow

        import uuid
        wf_uuid = uuid.uuid4()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (wf_uuid,)

        result = _resolve_pg_workflow(mock_conn, "507f1f77bcf86cd799439011")

        assert result is not None
        assert result["id"] == str(wf_uuid)

    @pytest.mark.unit
    def test_returns_none_when_not_found(self):
        from application.api.user.workflows.routes import _resolve_pg_workflow

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        result = _resolve_pg_workflow(mock_conn, "507f1f77bcf86cd799439011")

        assert result is None


# ---------------------------------------------------------------------------
# _write_graph
# ---------------------------------------------------------------------------


class TestWriteGraph:
    @pytest.mark.unit
    def test_empty_nodes_and_edges(self):
        from application.api.user.workflows.routes import _write_graph

        from flask import Flask
        app = Flask(__name__)
        mock_conn = MagicMock()

        with app.app_context():
            with patch("application.api.user.workflows.routes.WorkflowNodesRepository"), \
                 patch("application.api.user.workflows.routes.WorkflowEdgesRepository"):
                _write_graph(mock_conn, "pg-wf-id", 1, [], [])
        # No crash, no inserts
        # nodes_repo.bulk_create should NOT be called
        # (nothing to assert beyond no exception)

    @pytest.mark.unit
    def test_nodes_without_edges(self):
        from application.api.user.workflows.routes import _write_graph

        from flask import Flask
        app = Flask(__name__)
        mock_conn = MagicMock()

        nodes_data = [
            {"id": "n1", "type": "start", "title": "Start", "data": {}, "position": {"x": 0, "y": 0}},
        ]

        mock_nodes_repo = MagicMock()
        mock_nodes_repo.bulk_create.return_value = [{"node_id": "n1", "id": "uuid-n1"}]
        mock_edges_repo = MagicMock()

        with app.app_context():
            with patch("application.api.user.workflows.routes.WorkflowNodesRepository", return_value=mock_nodes_repo), \
                 patch("application.api.user.workflows.routes.WorkflowEdgesRepository", return_value=mock_edges_repo):
                _write_graph(mock_conn, "pg-wf-id", 1, nodes_data, [])

        mock_nodes_repo.bulk_create.assert_called_once()
        mock_edges_repo.bulk_create.assert_not_called()

    @pytest.mark.unit
    def test_nodes_with_resolved_edges(self):
        from application.api.user.workflows.routes import _write_graph

        from flask import Flask
        app = Flask(__name__)
        mock_conn = MagicMock()

        nodes_data = [
            {"id": "n1", "type": "start", "data": {}, "position": {"x": 0, "y": 0}},
            {"id": "n2", "type": "end", "data": {}, "position": {"x": 100, "y": 0}},
        ]
        edges_data = [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": None, "targetHandle": None},
        ]

        mock_nodes_repo = MagicMock()
        mock_nodes_repo.bulk_create.return_value = [
            {"node_id": "n1", "id": "uuid-n1"},
            {"node_id": "n2", "id": "uuid-n2"},
        ]
        mock_edges_repo = MagicMock()

        with app.app_context():
            with patch("application.api.user.workflows.routes.WorkflowNodesRepository", return_value=mock_nodes_repo), \
                 patch("application.api.user.workflows.routes.WorkflowEdgesRepository", return_value=mock_edges_repo):
                _write_graph(mock_conn, "pg-wf-id", 1, nodes_data, edges_data)

        mock_edges_repo.bulk_create.assert_called_once()

    @pytest.mark.unit
    def test_edge_with_unresolvable_nodes_is_dropped(self):
        """Edges whose source/target don't exist in node map are silently dropped."""
        from application.api.user.workflows.routes import _write_graph

        from flask import Flask
        app = Flask(__name__)
        mock_conn = MagicMock()

        nodes_data = [
            {"id": "n1", "type": "start", "data": {}, "position": {"x": 0, "y": 0}},
        ]
        edges_data = [
            {"id": "e1", "source": "n1", "target": "ghost-node"},
        ]

        mock_nodes_repo = MagicMock()
        mock_nodes_repo.bulk_create.return_value = [{"node_id": "n1", "id": "uuid-n1"}]
        mock_edges_repo = MagicMock()

        with app.app_context():
            with patch("application.api.user.workflows.routes.WorkflowNodesRepository", return_value=mock_nodes_repo), \
                 patch("application.api.user.workflows.routes.WorkflowEdgesRepository", return_value=mock_edges_repo):
                _write_graph(mock_conn, "pg-wf-id", 1, nodes_data, edges_data)

        # Edge was dropped — bulk_create should not be called
        mock_edges_repo.bulk_create.assert_not_called()


# ---------------------------------------------------------------------------
# _dual_write_workflow_create inner callback
# ---------------------------------------------------------------------------


class TestDualWriteWorkflowCreateCallback:
    @pytest.mark.unit
    def test_callback_creates_workflow_and_graph(self):
        """The _do closure passed to dual_write creates workflow + writes graph."""
        from application.api.user.workflows.routes import _dual_write_workflow_create
        import uuid

        captured_fn = []

        def fake_dual_write(repo_cls, fn):
            captured_fn.append(fn)

        with patch("application.api.user.workflows.routes.dual_write", side_effect=fake_dual_write), \
             patch("application.api.user.workflows.routes._write_graph") as mock_write_graph:
            _dual_write_workflow_create(
                mongo_workflow_id="mongo123",
                user_id="user1",
                name="My WF",
                description="desc",
                nodes_data=[],
                edges_data=[],
                graph_version=1,
            )

            assert len(captured_fn) == 1

            # Call the captured _do with a mock repo while patches are still active
            mock_repo = MagicMock()
            pg_wf_id = str(uuid.uuid4())
            mock_repo.create.return_value = {"id": pg_wf_id}
            mock_repo._conn = MagicMock()

            captured_fn[0](mock_repo)

        mock_repo.create.assert_called_once_with(
            "user1", "My WF",
            description="desc",
            legacy_mongo_id="mongo123",
        )
        mock_write_graph.assert_called_once()


# ---------------------------------------------------------------------------
# _dual_write_workflow_update inner callback
# ---------------------------------------------------------------------------


class TestDualWriteWorkflowUpdateCallback:
    @pytest.mark.unit
    def test_callback_when_pg_workflow_not_found(self):
        """If PG workflow not found, _do returns early without error."""
        from application.api.user.workflows.routes import _dual_write_workflow_update

        captured_fn = []

        def fake_dual_write(repo_cls, fn):
            captured_fn.append(fn)

        with patch("application.api.user.workflows.routes.dual_write", side_effect=fake_dual_write), \
             patch("application.api.user.workflows.routes._resolve_pg_workflow", return_value=None):
            _dual_write_workflow_update(
                mongo_workflow_id="mongo123",
                user_id="user1",
                name="WF",
                description="",
                nodes_data=[],
                edges_data=[],
                next_graph_version=2,
            )

            mock_repo = MagicMock()
            mock_repo._conn = MagicMock()
            captured_fn[0](mock_repo)  # Should not raise

        mock_repo.update.assert_not_called()

    @pytest.mark.unit
    def test_callback_updates_workflow_and_cleans_old_versions(self):
        """Full update path: write graph, update workflow, delete other versions."""
        from application.api.user.workflows.routes import _dual_write_workflow_update
        import uuid

        pg_id = str(uuid.uuid4())
        captured_fn = []

        def fake_dual_write(repo_cls, fn):
            captured_fn.append(fn)

        mock_nodes_repo = MagicMock()
        mock_edges_repo = MagicMock()

        with patch("application.api.user.workflows.routes.dual_write", side_effect=fake_dual_write), \
             patch("application.api.user.workflows.routes._resolve_pg_workflow", return_value={"id": pg_id}), \
             patch("application.api.user.workflows.routes._write_graph") as mock_write_graph, \
             patch("application.api.user.workflows.routes.WorkflowNodesRepository", return_value=mock_nodes_repo), \
             patch("application.api.user.workflows.routes.WorkflowEdgesRepository", return_value=mock_edges_repo):
            _dual_write_workflow_update(
                mongo_workflow_id="mongo123",
                user_id="user1",
                name="New Name",
                description="new desc",
                nodes_data=[],
                edges_data=[],
                next_graph_version=2,
            )

            mock_repo = MagicMock()
            mock_repo._conn = MagicMock()
            captured_fn[0](mock_repo)

        mock_write_graph.assert_called_once_with(mock_repo._conn, pg_id, 2, [], [])
        mock_repo.update.assert_called_once_with(
            pg_id, "user1",
            {
                "name": "New Name",
                "description": "new desc",
                "current_graph_version": 2,
            },
        )
        mock_nodes_repo.delete_other_versions.assert_called_once_with(pg_id, 2)
        mock_edges_repo.delete_other_versions.assert_called_once_with(pg_id, 2)


# ---------------------------------------------------------------------------
# _dual_write_workflow_delete inner callback
# ---------------------------------------------------------------------------


class TestDualWriteWorkflowDeleteCallback:
    @pytest.mark.unit
    def test_callback_deletes_when_found(self):
        import uuid
        from application.api.user.workflows.routes import _dual_write_workflow_delete

        pg_id = str(uuid.uuid4())
        captured_fn = []

        def fake_dual_write(repo_cls, fn):
            captured_fn.append(fn)

        with patch("application.api.user.workflows.routes.dual_write", side_effect=fake_dual_write), \
             patch("application.api.user.workflows.routes._resolve_pg_workflow", return_value={"id": pg_id}):
            _dual_write_workflow_delete("mongo123", "user1")

            mock_repo = MagicMock()
            mock_repo._conn = MagicMock()
            captured_fn[0](mock_repo)

        mock_repo.delete.assert_called_once_with(pg_id, "user1")

    @pytest.mark.unit
    def test_callback_skips_when_not_found(self):
        from application.api.user.workflows.routes import _dual_write_workflow_delete

        captured_fn = []

        def fake_dual_write(repo_cls, fn):
            captured_fn.append(fn)

        with patch("application.api.user.workflows.routes.dual_write", side_effect=fake_dual_write), \
             patch("application.api.user.workflows.routes._resolve_pg_workflow", return_value=None):
            _dual_write_workflow_delete("mongo123", "user1")

            mock_repo = MagicMock()
            mock_repo._conn = MagicMock()
            captured_fn[0](mock_repo)

        mock_repo.delete.assert_not_called()


# ---------------------------------------------------------------------------
# create_workflow_nodes: empty nodes path (line 513)
# ---------------------------------------------------------------------------


class TestCreateWorkflowNodes:
    @pytest.mark.unit
    def test_empty_nodes_returns_empty_list(self):
        from application.api.user.workflows.routes import create_workflow_nodes

        result = create_workflow_nodes("wf1", [], 1)
        assert result == []


# ---------------------------------------------------------------------------
# WorkflowDetail.put: remaining uncovered branches
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    from flask import Flask
    return Flask(__name__)


@pytest.mark.unit
class TestWorkflowDetailPutCoverageBranches:

    def test_put_invalid_object_id_returns_400(self, app):
        """Line 638: invalid ObjectId triggers early return."""
        from application.api.user.workflows.routes import WorkflowDetail

        with app.test_request_context(
            "/api/workflows/not-an-objectid",
            method="PUT",
            json={"name": "X", "nodes": [], "edges": []},
        ):
            from flask import request
            request.decoded_token = {"sub": "user1"}
            response = WorkflowDetail().put("not-an-objectid")

        assert response.status_code == 400

    def test_put_cleanup_runs_when_update_one_fails(self, app):
        """Lines 690-696: cleanup nodes+edges when update_one raises."""
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf = Mock()
        mock_wf.find_one.return_value = {"_id": wf_id, "name": "WF", "user": "user1", "current_graph_version": 1}
        mock_wf.update_one.side_effect = Exception("update failed")
        mock_nodes = Mock()
        mock_nodes.insert_many.return_value = Mock(inserted_ids=[ObjectId(), ObjectId()])
        mock_edges = Mock()
        mock_edges.insert_many.return_value = Mock(inserted_ids=[])

        with patch("application.api.user.workflows.routes.workflows_collection", mock_wf), \
             patch("application.api.user.workflows.routes.workflow_nodes_collection", mock_nodes), \
             patch("application.api.user.workflows.routes.workflow_edges_collection", mock_edges):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={
                    "name": "Updated",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [{"id": "e1", "source": "start", "target": "end"}],
                },
            ):
                from flask import request
                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        # Should return error and have cleaned up new graph version
        assert response.status_code == 400
        # The cleanup delete_many calls for graph_version=2
        cleanup_calls = [c for c in mock_nodes.delete_many.call_args_list]
        assert len(cleanup_calls) >= 1

    def test_put_old_version_cleanup_exception_is_swallowed(self, app):
        """Lines 705-706: exception during old-version cleanup is logged but not raised."""
        from application.api.user.workflows.routes import WorkflowDetail

        wf_id = ObjectId()
        mock_wf = Mock()
        mock_wf.find_one.return_value = {"_id": wf_id, "name": "WF", "user": "user1", "current_graph_version": 1}
        mock_wf.update_one.return_value = Mock()
        mock_nodes = Mock()
        mock_nodes.insert_many.return_value = Mock(inserted_ids=[ObjectId(), ObjectId()])
        # Make the old-version cleanup delete_many raise (no prior delete_many in success path)
        mock_nodes.delete_many.side_effect = Exception("cleanup error")
        mock_edges = Mock()
        mock_edges.insert_many.return_value = Mock(inserted_ids=[])

        with patch("application.api.user.workflows.routes.workflows_collection", mock_wf), \
             patch("application.api.user.workflows.routes.workflow_nodes_collection", mock_nodes), \
             patch("application.api.user.workflows.routes.workflow_edges_collection", mock_edges):
            with app.test_request_context(
                f"/api/workflows/{wf_id}",
                method="PUT",
                json={
                    "name": "Updated",
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [{"id": "e1", "source": "start", "target": "end"}],
                },
            ):
                from flask import request
                request.decoded_token = {"sub": "user1"}
                response = WorkflowDetail().put(str(wf_id))

        # Exception in cleanup must not propagate - should still succeed
        assert response.status_code == 200
