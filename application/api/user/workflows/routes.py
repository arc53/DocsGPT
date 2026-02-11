"""Workflow management routes."""

from datetime import datetime, timezone
from typing import Dict, List

from flask import current_app, request
from flask_restx import Namespace, Resource

from application.api.user.base import (
    workflow_edges_collection,
    workflow_nodes_collection,
    workflows_collection,
)
from application.api.user.utils import (
    check_resource_ownership,
    error_response,
    get_user_id,
    require_auth,
    require_fields,
    safe_db_operation,
    success_response,
    validate_object_id,
)

workflows_ns = Namespace("workflows", path="/api")


def serialize_workflow(w: Dict) -> Dict:
    """Serialize workflow document to API response format."""
    return {
        "id": str(w["_id"]),
        "name": w.get("name"),
        "description": w.get("description"),
        "created_at": w["created_at"].isoformat() if w.get("created_at") else None,
        "updated_at": w["updated_at"].isoformat() if w.get("updated_at") else None,
    }


def serialize_node(n: Dict) -> Dict:
    """Serialize workflow node document to API response format."""
    return {
        "id": n["id"],
        "type": n["type"],
        "title": n.get("title"),
        "description": n.get("description"),
        "position": n.get("position"),
        "data": n.get("config", {}),
    }


def serialize_edge(e: Dict) -> Dict:
    """Serialize workflow edge document to API response format."""
    return {
        "id": e["id"],
        "source": e.get("source_id"),
        "target": e.get("target_id"),
        "sourceHandle": e.get("source_handle"),
        "targetHandle": e.get("target_handle"),
    }


def get_workflow_graph_version(workflow: Dict) -> int:
    """Get current graph version with legacy fallback."""
    raw_version = workflow.get("current_graph_version", 1)
    try:
        version = int(raw_version)
        return version if version > 0 else 1
    except (ValueError, TypeError):
        return 1


def fetch_graph_documents(collection, workflow_id: str, graph_version: int) -> List[Dict]:
    """Fetch graph docs for active version, with fallback for legacy unversioned data."""
    docs = list(
        collection.find({"workflow_id": workflow_id, "graph_version": graph_version})
    )
    if docs:
        return docs
    if graph_version == 1:
        return list(
            collection.find(
                {"workflow_id": workflow_id, "graph_version": {"$exists": False}}
            )
        )
    return docs


def validate_workflow_structure(nodes: List[Dict], edges: List[Dict]) -> List[str]:
    """Validate workflow graph structure."""
    errors = []

    if not nodes:
        errors.append("Workflow must have at least one node")
        return errors

    start_nodes = [n for n in nodes if n.get("type") == "start"]
    if len(start_nodes) != 1:
        errors.append("Workflow must have exactly one start node")

    end_nodes = [n for n in nodes if n.get("type") == "end"]
    if not end_nodes:
        errors.append("Workflow must have at least one end node")

    node_ids = {n.get("id") for n in nodes}
    for edge in edges:
        source_id = edge.get("source")
        target_id = edge.get("target")
        if source_id not in node_ids:
            errors.append(f"Edge references non-existent source: {source_id}")
        if target_id not in node_ids:
            errors.append(f"Edge references non-existent target: {target_id}")

    if start_nodes:
        start_id = start_nodes[0].get("id")
        if not any(e.get("source") == start_id for e in edges):
            errors.append("Start node must have at least one outgoing edge")

    for node in nodes:
        if not node.get("id"):
            errors.append("All nodes must have an id")
        if not node.get("type"):
            errors.append(f"Node {node.get('id', 'unknown')} must have a type")

    return errors


def create_workflow_nodes(
    workflow_id: str, nodes_data: List[Dict], graph_version: int
) -> None:
    """Insert workflow nodes into database."""
    if nodes_data:
        workflow_nodes_collection.insert_many(
            [
                {
                    "id": n["id"],
                    "workflow_id": workflow_id,
                    "graph_version": graph_version,
                    "type": n["type"],
                    "title": n.get("title", ""),
                    "description": n.get("description", ""),
                    "position": n.get("position", {"x": 0, "y": 0}),
                    "config": n.get("data", {}),
                }
                for n in nodes_data
            ]
        )


def create_workflow_edges(
    workflow_id: str, edges_data: List[Dict], graph_version: int
) -> None:
    """Insert workflow edges into database."""
    if edges_data:
        workflow_edges_collection.insert_many(
            [
                {
                    "id": e["id"],
                    "workflow_id": workflow_id,
                    "graph_version": graph_version,
                    "source_id": e.get("source"),
                    "target_id": e.get("target"),
                    "source_handle": e.get("sourceHandle"),
                    "target_handle": e.get("targetHandle"),
                }
                for e in edges_data
            ]
        )


@workflows_ns.route("/workflows")
class WorkflowList(Resource):

    @require_auth
    @require_fields(["name"])
    def post(self):
        """Create a new workflow with nodes and edges."""
        user_id = get_user_id()
        data = request.get_json()

        name = data.get("name", "").strip()
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edges", [])

        validation_errors = validate_workflow_structure(nodes_data, edges_data)
        if validation_errors:
            return error_response(
                "Workflow validation failed", errors=validation_errors
            )

        now = datetime.now(timezone.utc)
        workflow_doc = {
            "name": name,
            "description": data.get("description", ""),
            "user": user_id,
            "created_at": now,
            "updated_at": now,
            "current_graph_version": 1,
        }

        result, error = safe_db_operation(
            lambda: workflows_collection.insert_one(workflow_doc),
            "Failed to create workflow",
        )
        if error:
            return error

        workflow_id = str(result.inserted_id)

        try:
            create_workflow_nodes(workflow_id, nodes_data, 1)
            create_workflow_edges(workflow_id, edges_data, 1)
        except Exception as e:
            workflow_nodes_collection.delete_many({"workflow_id": workflow_id})
            workflow_edges_collection.delete_many({"workflow_id": workflow_id})
            workflows_collection.delete_one({"_id": result.inserted_id})
            return error_response(f"Failed to create workflow structure: {str(e)}")

        return success_response({"id": workflow_id}, 201)


@workflows_ns.route("/workflows/<string:workflow_id>")
class WorkflowDetail(Resource):

    @require_auth
    def get(self, workflow_id: str):
        """Get workflow details with nodes and edges."""
        user_id = get_user_id()
        obj_id, error = validate_object_id(workflow_id, "Workflow")
        if error:
            return error

        workflow, error = check_resource_ownership(
            workflows_collection, obj_id, user_id, "Workflow"
        )
        if error:
            return error

        graph_version = get_workflow_graph_version(workflow)
        nodes = fetch_graph_documents(
            workflow_nodes_collection, workflow_id, graph_version
        )
        edges = fetch_graph_documents(
            workflow_edges_collection, workflow_id, graph_version
        )

        return success_response(
            {
                "workflow": serialize_workflow(workflow),
                "nodes": [serialize_node(n) for n in nodes],
                "edges": [serialize_edge(e) for e in edges],
            }
        )

    @require_auth
    @require_fields(["name"])
    def put(self, workflow_id: str):
        """Update workflow and replace nodes/edges."""
        user_id = get_user_id()
        obj_id, error = validate_object_id(workflow_id, "Workflow")
        if error:
            return error

        workflow, error = check_resource_ownership(
            workflows_collection, obj_id, user_id, "Workflow"
        )
        if error:
            return error

        data = request.get_json()
        name = data.get("name", "").strip()
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edges", [])

        validation_errors = validate_workflow_structure(nodes_data, edges_data)
        if validation_errors:
            return error_response(
                "Workflow validation failed", errors=validation_errors
            )

        current_graph_version = get_workflow_graph_version(workflow)
        next_graph_version = current_graph_version + 1
        try:
            create_workflow_nodes(workflow_id, nodes_data, next_graph_version)
            create_workflow_edges(workflow_id, edges_data, next_graph_version)
        except Exception as e:
            workflow_nodes_collection.delete_many(
                {"workflow_id": workflow_id, "graph_version": next_graph_version}
            )
            workflow_edges_collection.delete_many(
                {"workflow_id": workflow_id, "graph_version": next_graph_version}
            )
            return error_response(f"Failed to update workflow structure: {str(e)}")

        now = datetime.now(timezone.utc)
        _, error = safe_db_operation(
            lambda: workflows_collection.update_one(
                {"_id": obj_id},
                {
                    "$set": {
                        "name": name,
                        "description": data.get("description", ""),
                        "updated_at": now,
                        "current_graph_version": next_graph_version,
                    }
                },
            ),
            "Failed to update workflow",
        )
        if error:
            workflow_nodes_collection.delete_many(
                {"workflow_id": workflow_id, "graph_version": next_graph_version}
            )
            workflow_edges_collection.delete_many(
                {"workflow_id": workflow_id, "graph_version": next_graph_version}
            )
            return error

        try:
            workflow_nodes_collection.delete_many(
                {"workflow_id": workflow_id, "graph_version": {"$ne": next_graph_version}}
            )
            workflow_edges_collection.delete_many(
                {"workflow_id": workflow_id, "graph_version": {"$ne": next_graph_version}}
            )
        except Exception as cleanup_err:
            current_app.logger.warning(
                f"Failed to clean old workflow graph versions for {workflow_id}: {cleanup_err}"
            )

        return success_response()

    @require_auth
    def delete(self, workflow_id: str):
        """Delete workflow and its graph."""
        user_id = get_user_id()
        obj_id, error = validate_object_id(workflow_id, "Workflow")
        if error:
            return error

        workflow, error = check_resource_ownership(
            workflows_collection, obj_id, user_id, "Workflow"
        )
        if error:
            return error

        try:
            workflow_nodes_collection.delete_many({"workflow_id": workflow_id})
            workflow_edges_collection.delete_many({"workflow_id": workflow_id})
            workflows_collection.delete_one({"_id": workflow["_id"], "user": user_id})
        except Exception as e:
            return error_response(f"Failed to delete workflow: {str(e)}")

        return success_response()
