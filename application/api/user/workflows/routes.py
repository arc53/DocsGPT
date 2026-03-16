"""Workflow management routes."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from flask import current_app, request
from flask_restx import Namespace, Resource

from application.api.user.base import (
    workflow_edges_collection,
    workflow_nodes_collection,
    workflows_collection,
)
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.model_utils import get_model_capabilities
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


def validate_json_schema_payload(
    json_schema: Any,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Validate and normalize optional JSON schema payload for structured output."""
    if json_schema is None:
        return None, None
    try:
        return normalize_json_schema_payload(json_schema), None
    except JsonSchemaValidationError as exc:
        return None, str(exc)


def normalize_agent_node_json_schemas(nodes: List[Dict]) -> List[Dict]:
    """Normalize agent-node JSON schema payloads before persistence."""
    normalized_nodes: List[Dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            normalized_nodes.append(node)
            continue

        normalized_node = dict(node)
        if normalized_node.get("type") != "agent":
            normalized_nodes.append(normalized_node)
            continue

        raw_config = normalized_node.get("data")
        if not isinstance(raw_config, dict) or "json_schema" not in raw_config:
            normalized_nodes.append(normalized_node)
            continue

        normalized_config = dict(raw_config)
        try:
            normalized_config["json_schema"] = normalize_json_schema_payload(
                raw_config.get("json_schema")
            )
        except JsonSchemaValidationError:
            # Validation runs before normalization; keep original on unexpected shape.
            normalized_config["json_schema"] = raw_config.get("json_schema")
        normalized_node["data"] = normalized_config
        normalized_nodes.append(normalized_node)

    return normalized_nodes


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
    node_map = {n.get("id"): n for n in nodes}
    end_ids = {n.get("id") for n in end_nodes}

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

    condition_nodes = [n for n in nodes if n.get("type") == "condition"]
    for cnode in condition_nodes:
        cnode_id = cnode.get("id")
        cnode_title = cnode.get("title", cnode_id)
        outgoing = [e for e in edges if e.get("source") == cnode_id]
        if len(outgoing) < 2:
            errors.append(
                f"Condition node '{cnode_title}' must have at least 2 outgoing edges"
            )
        node_data = cnode.get("data", {}) or {}
        cases = node_data.get("cases", [])
        if not isinstance(cases, list):
            cases = []
        if not cases or not any(
            isinstance(c, dict) and str(c.get("expression", "")).strip() for c in cases
        ):
            errors.append(
                f"Condition node '{cnode_title}' must have at least one case with an expression"
            )

        case_handles: Set[str] = set()
        duplicate_case_handles: Set[str] = set()
        for case in cases:
            if not isinstance(case, dict):
                continue
            raw_handle = case.get("sourceHandle", "")
            handle = raw_handle.strip() if isinstance(raw_handle, str) else ""
            if not handle:
                errors.append(
                    f"Condition node '{cnode_title}' has a case without a branch handle"
                )
                continue
            if handle in case_handles:
                duplicate_case_handles.add(handle)
            case_handles.add(handle)

        for handle in duplicate_case_handles:
            errors.append(
                f"Condition node '{cnode_title}' has duplicate case handle '{handle}'"
            )

        outgoing_by_handle: Dict[str, List[Dict]] = {}
        for out_edge in outgoing:
            raw_handle = out_edge.get("sourceHandle", "")
            handle = raw_handle.strip() if isinstance(raw_handle, str) else ""
            outgoing_by_handle.setdefault(handle, []).append(out_edge)

        for handle, handle_edges in outgoing_by_handle.items():
            if not handle:
                errors.append(
                    f"Condition node '{cnode_title}' has an outgoing edge without sourceHandle"
                )
                continue
            if handle != "else" and handle not in case_handles:
                errors.append(
                    f"Condition node '{cnode_title}' has a connection from unknown branch '{handle}'"
                )
            if len(handle_edges) > 1:
                errors.append(
                    f"Condition node '{cnode_title}' has multiple outgoing edges from branch '{handle}'"
                )

        if "else" not in outgoing_by_handle:
            errors.append(f"Condition node '{cnode_title}' must have an 'else' branch")

        for case in cases:
            if not isinstance(case, dict):
                continue
            raw_handle = case.get("sourceHandle", "")
            handle = raw_handle.strip() if isinstance(raw_handle, str) else ""
            if not handle:
                continue

            raw_expression = case.get("expression", "")
            has_expression = isinstance(raw_expression, str) and bool(
                raw_expression.strip()
            )
            has_outgoing = bool(outgoing_by_handle.get(handle))
            if has_expression and not has_outgoing:
                errors.append(
                    f"Condition node '{cnode_title}' case '{handle}' has an expression but no outgoing edge"
                )
            if not has_expression and has_outgoing:
                errors.append(
                    f"Condition node '{cnode_title}' case '{handle}' has an outgoing edge but no expression"
                )

        for handle, handle_edges in outgoing_by_handle.items():
            if not handle:
                continue
            for out_edge in handle_edges:
                target = out_edge.get("target")
                if target and not _can_reach_end(target, edges, node_map, end_ids):
                    errors.append(
                        f"Branch '{handle}' of condition '{cnode_title}' "
                        f"must eventually reach an end node"
                    )

    agent_nodes = [n for n in nodes if n.get("type") == "agent"]
    for agent_node in agent_nodes:
        agent_title = agent_node.get("title", agent_node.get("id", "unknown"))
        raw_config = agent_node.get("data", {}) or {}
        if not isinstance(raw_config, dict):
            errors.append(f"Agent node '{agent_title}' has invalid configuration")
            continue
        normalized_schema, schema_error = validate_json_schema_payload(
            raw_config.get("json_schema")
        )
        has_json_schema = normalized_schema is not None

        model_id = raw_config.get("model_id")
        if has_json_schema and isinstance(model_id, str) and model_id.strip():
            capabilities = get_model_capabilities(model_id.strip())
            if capabilities and not capabilities.get("supports_structured_output", False):
                errors.append(
                    f"Agent node '{agent_title}' selected model does not support structured output"
                )
        if schema_error:
            errors.append(f"Agent node '{agent_title}' JSON schema {schema_error}")

    for node in nodes:
        if not node.get("id"):
            errors.append("All nodes must have an id")
        if not node.get("type"):
            errors.append(f"Node {node.get('id', 'unknown')} must have a type")

    return errors


def _can_reach_end(
    node_id: str, edges: List[Dict], node_map: Dict, end_ids: set, visited: set = None
) -> bool:
    if visited is None:
        visited = set()
    if node_id in end_ids:
        return True
    if node_id in visited or node_id not in node_map:
        return False
    visited.add(node_id)
    outgoing = [e.get("target") for e in edges if e.get("source") == node_id]
    return any(_can_reach_end(t, edges, node_map, end_ids, visited) for t in outgoing if t)


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
        nodes_data = normalize_agent_node_json_schemas(nodes_data)

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
        nodes_data = normalize_agent_node_json_schemas(nodes_data)

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
