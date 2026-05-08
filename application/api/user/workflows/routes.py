"""Workflow management routes."""

from typing import Any, Dict, List, Optional, Set

from flask import current_app, request
from flask_restx import Namespace, Resource

from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.session import db_readonly, db_session
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.model_utils import get_model_capabilities
from application.api.user.utils import (
    error_response,
    get_user_id,
    require_auth,
    require_fields,
    success_response,
)

workflows_ns = Namespace("workflows", path="/api")


def _workflow_error_response(message: str, err: Exception):
    current_app.logger.error(f"{message}: {err}", exc_info=True)
    return error_response(message)


def _resolve_workflow(repo: WorkflowsRepository, workflow_id: str, user_id: str):
    """Resolve a workflow by UUID or legacy Mongo id, scoped to user."""
    if not workflow_id:
        return None
    if looks_like_uuid(workflow_id):
        row = repo.get(workflow_id, user_id)
        if row is not None:
            return row
    return repo.get_by_legacy_id(workflow_id, user_id)


def _write_graph(
    conn,
    pg_workflow_id: str,
    graph_version: int,
    nodes_data: List[Dict],
    edges_data: List[Dict],
) -> List[Dict]:
    """Bulk-create nodes + edges for one graph version. Uses ON CONFLICT upsert.

    Edges arrive with source/target as user-provided node-id strings. We
    insert nodes first, capture their ``node_id → UUID`` map, then
    translate edges before insertion. Edges referencing missing nodes are
    dropped with a warning.
    """
    nodes_repo = WorkflowNodesRepository(conn)
    edges_repo = WorkflowEdgesRepository(conn)

    if nodes_data:
        created_nodes = nodes_repo.bulk_create(
            pg_workflow_id, graph_version,
            [
                {
                    "node_id": n["id"],
                    "node_type": n["type"],
                    "title": n.get("title", ""),
                    "description": n.get("description", ""),
                    "position": n.get("position", {"x": 0, "y": 0}),
                    "config": n.get("data", {}),
                }
                for n in nodes_data
            ],
        )
        node_uuid_by_str = {n["node_id"]: n["id"] for n in created_nodes}
    else:
        created_nodes = []
        node_uuid_by_str = {}

    if edges_data:
        translated_edges: List[Dict] = []
        for e in edges_data:
            src = e.get("source")
            tgt = e.get("target")
            from_uuid = node_uuid_by_str.get(src)
            to_uuid = node_uuid_by_str.get(tgt)
            if not from_uuid or not to_uuid:
                current_app.logger.warning(
                    "Workflow graph write: dropping edge %s; node refs unresolved "
                    "(source=%s, target=%s)",
                    e.get("id"), src, tgt,
                )
                continue
            translated_edges.append({
                "edge_id": e["id"],
                "from_node_id": from_uuid,
                "to_node_id": to_uuid,
                "source_handle": e.get("sourceHandle"),
                "target_handle": e.get("targetHandle"),
            })
        if translated_edges:
            edges_repo.bulk_create(
                pg_workflow_id, graph_version, translated_edges,
            )

    return created_nodes


def serialize_workflow(w: Dict) -> Dict:
    """Serialize workflow row to API response format."""
    created_at = w.get("created_at")
    updated_at = w.get("updated_at")
    return {
        "id": str(w["id"]),
        "name": w.get("name"),
        "description": w.get("description"),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


def serialize_node(n: Dict) -> Dict:
    """Serialize workflow node row to API response format."""
    return {
        "id": n["node_id"],
        "type": n["node_type"],
        "title": n.get("title"),
        "description": n.get("description"),
        "position": n.get("position"),
        "data": n.get("config", {}) or {},
    }


def serialize_edge(e: Dict) -> Dict:
    """Serialize workflow edge row to API response format."""
    return {
        "id": e["edge_id"],
        "source": e.get("source_id"),
        "target": e.get("target_id"),
        "sourceHandle": e.get("source_handle"),
        "targetHandle": e.get("target_handle"),
    }


def get_workflow_graph_version(workflow: Dict) -> int:
    """Get current graph version with fallback."""
    raw_version = workflow.get("current_graph_version", 1)
    try:
        version = int(raw_version)
        return version if version > 0 else 1
    except (ValueError, TypeError):
        return 1


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


def validate_workflow_structure(
    nodes: List[Dict], edges: List[Dict], user_id: str | None = None
) -> List[str]:
    """Validate workflow graph structure.

    ``user_id`` is required so per-user BYOM custom-model UUIDs resolve
    when checking each agent node's structured-output capability.
    """
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
            capabilities = get_model_capabilities(model_id.strip(), user_id=user_id)
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


@workflows_ns.route("/workflows")
class WorkflowList(Resource):

    @require_auth
    @require_fields(["name"])
    def post(self):
        """Create a new workflow with nodes and edges."""
        user_id = get_user_id()
        data = request.get_json()

        name = data.get("name", "").strip()
        description = data.get("description", "")
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edges", [])

        validation_errors = validate_workflow_structure(
            nodes_data, edges_data, user_id=user_id
        )
        if validation_errors:
            return error_response(
                "Workflow validation failed", errors=validation_errors
            )
        nodes_data = normalize_agent_node_json_schemas(nodes_data)

        try:
            with db_session() as conn:
                repo = WorkflowsRepository(conn)
                workflow = repo.create(user_id, name, description=description)
                pg_workflow_id = str(workflow["id"])
                _write_graph(conn, pg_workflow_id, 1, nodes_data, edges_data)
        except Exception as err:
            return _workflow_error_response("Failed to create workflow", err)

        return success_response({"id": pg_workflow_id}, 201)


@workflows_ns.route("/workflows/<string:workflow_id>")
class WorkflowDetail(Resource):

    @require_auth
    def get(self, workflow_id: str):
        """Get workflow details with nodes and edges."""
        user_id = get_user_id()
        try:
            with db_readonly() as conn:
                repo = WorkflowsRepository(conn)
                workflow = _resolve_workflow(repo, workflow_id, user_id)
                if workflow is None:
                    return error_response("Workflow not found", 404)
                pg_workflow_id = str(workflow["id"])
                graph_version = get_workflow_graph_version(workflow)
                nodes = WorkflowNodesRepository(conn).find_by_version(
                    pg_workflow_id, graph_version,
                )
                edges = WorkflowEdgesRepository(conn).find_by_version(
                    pg_workflow_id, graph_version,
                )
        except Exception as err:
            return _workflow_error_response("Failed to fetch workflow", err)

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
        data = request.get_json()
        name = data.get("name", "").strip()
        description = data.get("description", "")
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edges", [])

        validation_errors = validate_workflow_structure(
            nodes_data, edges_data, user_id=user_id
        )
        if validation_errors:
            return error_response(
                "Workflow validation failed", errors=validation_errors
            )
        nodes_data = normalize_agent_node_json_schemas(nodes_data)

        try:
            with db_session() as conn:
                repo = WorkflowsRepository(conn)
                workflow = _resolve_workflow(repo, workflow_id, user_id)
                if workflow is None:
                    return error_response("Workflow not found", 404)
                pg_workflow_id = str(workflow["id"])
                current_graph_version = get_workflow_graph_version(workflow)
                next_graph_version = current_graph_version + 1

                _write_graph(
                    conn, pg_workflow_id, next_graph_version,
                    nodes_data, edges_data,
                )
                repo.update(
                    pg_workflow_id, user_id,
                    {
                        "name": name,
                        "description": description,
                        "current_graph_version": next_graph_version,
                    },
                )
                WorkflowNodesRepository(conn).delete_other_versions(
                    pg_workflow_id, next_graph_version,
                )
                WorkflowEdgesRepository(conn).delete_other_versions(
                    pg_workflow_id, next_graph_version,
                )
        except Exception as err:
            return _workflow_error_response("Failed to update workflow", err)

        return success_response()

    @require_auth
    def delete(self, workflow_id: str):
        """Delete workflow and its graph."""
        user_id = get_user_id()
        try:
            with db_session() as conn:
                repo = WorkflowsRepository(conn)
                workflow = _resolve_workflow(repo, workflow_id, user_id)
                if workflow is None:
                    return error_response("Workflow not found", 404)
                # ON DELETE CASCADE on workflow_nodes/edges cleans children.
                repo.delete(str(workflow["id"]), user_id)
        except Exception as err:
            return _workflow_error_response("Failed to delete workflow", err)

        return success_response()
