from types import SimpleNamespace
from unittest.mock import Mock, patch

from bson import ObjectId
from flask import Flask, jsonify, make_response, request


def test_safe_db_operation_hides_exception_details():
    from application.api.user.utils import safe_db_operation

    app = Flask(__name__)

    def failing_operation():
        raise RuntimeError("database credentials leaked")

    with app.app_context():
        _, error = safe_db_operation(
            failing_operation,
            "Failed to create workflow",
        )

    assert error.status_code == 400
    assert error.json["message"] == "Failed to create workflow"
    assert "credentials" not in error.json["message"]


def test_agent_folders_hides_exception_details():
    from application.api.user.agents.folders import AgentFolders

    app = Flask(__name__)
    failing_collection = Mock()
    failing_collection.find.side_effect = RuntimeError("folder backend secret")

    with patch(
        "application.api.user.agents.folders.agent_folders_collection",
        failing_collection,
    ):
        with app.test_request_context("/api/agents/folders/", method="GET"):
            request.decoded_token = {"sub": "test_user"}
            response = AgentFolders().get()

    assert response.status_code == 400
    assert response.json["message"] == "Failed to fetch folders"
    assert "secret" not in response.json["message"]


def test_workflow_create_hides_structure_exception_details():
    from application.api.user.workflows.routes import WorkflowList

    app = Flask(__name__)
    insert_result = SimpleNamespace(inserted_id=ObjectId())

    with patch(
        "application.api.user.workflows.routes.safe_db_operation",
        return_value=(insert_result, None),
    ), patch(
        "application.api.user.workflows.routes.create_workflow_nodes",
        side_effect=RuntimeError("storage bucket credentials leaked"),
    ), patch(
        "application.api.user.workflows.routes.workflow_nodes_collection"
    ) as mock_nodes, patch(
        "application.api.user.workflows.routes.workflow_edges_collection"
    ) as mock_edges, patch(
        "application.api.user.workflows.routes.workflows_collection"
    ) as mock_workflows:
        with app.test_request_context(
            "/api/workflows",
            method="POST",
            json={
                "name": "Workflow",
                "nodes": [
                    {"id": "start", "type": "start"},
                    {"id": "end", "type": "end"},
                ],
                "edges": [{"id": "edge-1", "source": "start", "target": "end"}],
            },
        ):
            request.decoded_token = {"sub": "test_user"}
            response = WorkflowList().post()

    assert response.status_code == 400
    assert response.json["message"] == "Failed to create workflow structure"
    assert "credentials" not in response.json["message"]
    mock_nodes.delete_many.assert_called_once_with(
        {"workflow_id": str(insert_result.inserted_id)}
    )
    mock_edges.delete_many.assert_called_once_with(
        {"workflow_id": str(insert_result.inserted_id)}
    )
    mock_workflows.delete_one.assert_called_once_with(
        {"_id": insert_result.inserted_id}
    )


def test_update_agent_reuses_sanitized_image_upload_error():
    from application.api.user.agents.routes import UpdateAgent

    app = Flask(__name__)
    agent_id = str(ObjectId())

    with app.test_request_context(
        f"/api/agents/update_agent/{agent_id}",
        method="PUT",
        json={},
    ):
        request.decoded_token = {"sub": "test_user"}
        sanitized_error = make_response(
            jsonify({"success": False, "message": "Image upload failed"}),
            400,
        )

        with patch(
            "application.api.user.agents.routes.agents_collection.find_one",
            return_value={"_id": ObjectId(agent_id), "user": "test_user"},
        ), patch(
            "application.api.user.agents.routes.handle_image_upload",
            return_value=(None, sanitized_error),
        ):
            response = UpdateAgent().put(agent_id)

    assert response.status_code == 400
    assert response.json["message"] == "Image upload failed"
