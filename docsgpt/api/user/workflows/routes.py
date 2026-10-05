"""Workflow management routes."""

from typing import Any, Dict, List, Optional, Set, Tuple

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource
from sqlalchemy import text as sql_text

from docsgpt.agents.workflows.cel_evaluator import (
    CelEvaluationError,
    validate_cel_expression,
)
from docsgpt.api.user import resource_access
from docsgpt.api.user.resource_access import (
    AccessDenied,
    best_effort,
    cached_resolves,
    can_use_ref,
    named_ref_keys,
    parse_confirmations,
    plan_sponsors,
    resolve,
    resource_states,
    sponsor_audience,
    sponsor_details,
    sponsor_refusal,
)
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from docsgpt.core.model_utils import get_model_capabilities
from docsgpt.api.user.utils import (
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


def _workflow_access(conn, workflow_id: str, user_id: str, action: str):
    """Resolve a workflow the caller may ``action``, and the id to act as.

    The caller's own workflow is always theirs. Otherwise access comes from
    an agent of the workflow's owner that uses it: ``view`` to read it,
    ``edit`` to change it, ``delete`` to remove it (checked on that agent).

    Args:
        conn: Open database connection.
        workflow_id: Workflow UUID or legacy id.
        user_id: The caller.
        action: Agent action required (``view``, ``edit`` or ``delete``).

    Returns:
        ``(workflow, acting_user_id)``.

    Raises:
        AccessDenied: 404 when not visible, 403 when the role can't ``action``.
    """
    repo = WorkflowsRepository(conn)
    own = _resolve_workflow(repo, workflow_id, user_id)
    if own is not None:
        return own, user_id
    if not looks_like_uuid(str(workflow_id)):
        raise AccessDenied(404, "Workflow not found")
    workflow = repo.get_by_id(str(workflow_id))
    if workflow is None:
        raise AccessDenied(404, "Workflow not found")
    agent_ids = conn.execute(
        sql_text(
            "SELECT id FROM agents WHERE workflow_id = CAST(:wid AS uuid) AND user_id = :owner"
        ),
        {"wid": str(workflow["id"]), "owner": workflow["user_id"]},
    ).scalars().all()
    visible = False
    for agent_id in agent_ids:
        ra = resolve(conn, "agent", str(agent_id), user_id)
        if ra is None:
            continue
        visible = True
        if ra.can(action):
            return workflow, ra.owner_id
    if not visible:
        raise AccessDenied(404, "Workflow not found")
    raise AccessDenied(403, "Your access to this item doesn't allow that")


def _node_refs(nodes: List[Dict]) -> List[Tuple[str, str]]:
    """The ``(type, id)`` tools and sources a workflow's agent nodes reference.

    Args:
        nodes: Nodes as the builder sends them (config under ``data`` or
            ``data.config``, like the engine reads it).

    Returns:
        list: ``("tool", id)`` and ``("source", id)`` pairs.
    """
    refs: List[Tuple[str, str]] = []
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("type") != "agent":
            continue
        data = node.get("data") or {}
        cfg = data.get("config") if isinstance(data.get("config"), dict) else data
        for resource_type, key in (("tool", "tools"), ("source", "sources")):
            values = cfg.get(key) or []
            if isinstance(values, (str, int)):
                values = [values]
            refs.extend((resource_type, str(v)) for v in values if v)
    return refs


def _node_ref_details(nodes: List[Dict], visible: Optional[Set[str]] = None) -> Dict[str, List[Dict]]:
    """Names of the tools and sources the graph's agent nodes reference.

    Looked up by id whoever owns them, so an editor's node pickers can show
    (and remove) the owner's private tools and sources. Builtin tool ids
    always resolve; any other id only when its ``"<type>:<id>"`` key is in
    ``visible`` (see ``resource_access.named_ref_keys``), so a node naming
    someone else's resource never reveals its name.

    Args:
        nodes: Nodes in builder shape.
        visible: Keys whose names may be read; None allows every id.

    Returns:
        dict: ``tools`` as ``[{id, name, display_name}]`` and ``sources`` as
        ``[{id, name}]``, each id once.
    """
    from docsgpt.agents.default_tools import is_synthesized_tool_id
    from docsgpt.api.user.base import resolve_source_details, resolve_tool_details

    tool_ids: List[str] = []
    source_ids: List[str] = []
    for resource_type, resource_id in _node_refs(nodes):
        if (
            visible is not None
            and not (resource_type == "tool" and is_synthesized_tool_id(resource_id))
            and f"{resource_type}:{resource_id.lower()}" not in visible
        ):
            continue
        bucket = tool_ids if resource_type == "tool" else source_ids
        if resource_id not in bucket:
            bucket.append(resource_id)
    return {
        "tools": resolve_tool_details(tool_ids),
        "sources": resolve_source_details(source_ids),
    }


def _new_node_ref_denied(
    conn, previous_nodes: List[Dict], new_nodes: List[Dict], caller: str
) -> Optional[AccessDenied]:
    """403 for the first node tool/source ``caller`` newly adds but can't use.

    A workflow runs as its owner, so an editor saving the owner's graph must
    not reference the owner's private tools or sources: the caller's own
    access counts (``use_in_own`` for a tool, ``use`` for a source), not the
    owner's. The owner's own saves are checked the same way, so no graph
    names a resource its owner never could use. Refs already in the stored
    graph stay, like an agent's.

    Args:
        conn: Open database connection.
        previous_nodes: The stored graph's nodes, in builder shape (empty
            when creating the workflow).
        new_nodes: The nodes being saved.
        caller: The user saving, owner or editor.

    Returns:
        An :class:`AccessDenied` to return, or None when every new ref is fine.
    """
    from docsgpt.agents.default_tools import is_synthesized_tool_id

    existing = set(_node_refs(previous_nodes))
    for resource_type, resource_id in _node_refs(new_nodes):
        if (resource_type, resource_id) in existing:
            continue
        if resource_type == "tool" and is_synthesized_tool_id(resource_id):
            continue
        if resource_type == "source" and resource_id == "default":
            continue
        if not can_use_ref(conn, resource_type, resource_id, caller):
            return AccessDenied(403, f"{resource_type.capitalize()} not accessible")
    return None


def _denied(err: AccessDenied):
    """403/404 in this module's ``error`` shape, plus the shared ``message`` key."""
    return make_response(
        jsonify({"success": False, "error": err.message, "message": err.message}), err.status
    )


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
            if has_expression:
                try:
                    validate_cel_expression(raw_expression)
                except CelEvaluationError as exc:
                    errors.append(
                        f"Condition node '{cnode_title}' case '{handle}' "
                        f"has an invalid expression: {exc}"
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

    # Set State nodes were validated nowhere. A node whose CEL does not compile
    # saves and publishes clean, then aborts the run on first execution — the
    # user only finds out as a failed answer, with no pointer to the node.
    state_nodes = [n for n in nodes if n.get("type") == "state"]
    for snode in state_nodes:
        snode_title = snode.get("title", snode.get("id"))
        node_data = snode.get("data", {}) or {}
        # The builder writes state config under ``data.config`` but other
        # payloads keep it flat on ``data``; the engine reads
        # ``node.config.get("config", node.config)`` for exactly this reason,
        # so accept both rather than silently validating nothing.
        nested = node_data.get("config")
        source = nested if isinstance(nested, dict) else node_data
        operations = source.get("operations", [])
        if not isinstance(operations, list):
            continue
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                continue
            raw_expression = operation.get("expression", "")
            target_variable = operation.get("target_variable", "")
            has_expression = isinstance(raw_expression, str) and bool(
                raw_expression.strip()
            )
            has_target = isinstance(target_variable, str) and bool(
                target_variable.strip()
            )
            # The engine silently skips an operation missing either half
            # (workflow_engine._execute_state_node), so downstream nodes read a
            # variable that never gets set. Surface it at save time instead.
            if has_expression and not has_target:
                errors.append(
                    f"Set State node '{snode_title}' operation {index + 1} "
                    f"has an expression but no target variable"
                )
            if has_target and not has_expression:
                errors.append(
                    f"Set State node '{snode_title}' operation {index + 1} "
                    f"has a target variable but no expression"
                )
            if has_expression:
                try:
                    validate_cel_expression(raw_expression)
                except CelEvaluationError as exc:
                    errors.append(
                        f"Set State node '{snode_title}' operation {index + 1} "
                        f"has an invalid expression: {exc}"
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

    code_nodes = [n for n in nodes if n.get("type") == "code"]
    for code_node in code_nodes:
        code_title = code_node.get("title", code_node.get("id", "unknown"))
        raw_config = code_node.get("data", {}) or {}
        if not isinstance(raw_config, dict):
            errors.append(f"Code node '{code_title}' has invalid configuration")
            continue
        if not str(raw_config.get("code", "")).strip():
            errors.append(f"Code node '{code_title}' must have code to execute")
        _, schema_error = validate_json_schema_payload(raw_config.get("json_schema"))
        if schema_error:
            errors.append(f"Code node '{code_title}' JSON schema {schema_error}")

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
                denied = _new_node_ref_denied(conn, [], nodes_data, user_id)
                if denied is not None:
                    return _denied(denied)
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
                try:
                    workflow, _acting = _workflow_access(conn, workflow_id, user_id, "view")
                except AccessDenied as denied:
                    return _denied(denied)
                pg_workflow_id = str(workflow["id"])
                graph_version = get_workflow_graph_version(workflow)
                nodes = WorkflowNodesRepository(conn).find_by_version(
                    pg_workflow_id, graph_version,
                )
                edges = WorkflowEdgesRepository(conn).find_by_version(
                    pg_workflow_id, graph_version,
                )
                serialized_nodes = [serialize_node(n) for n in nodes]
                # Edit-page detail (sponsors, run state, names of node
                # resources) only for people who may edit the workflow.
                sponsored: list = []
                states: list = []
                audience = None
                visible: Optional[Set[str]] = None
                with cached_resolves():
                    if resource_access.holder_editable_by(conn, "workflow", workflow, user_id):
                        refs = _node_refs(serialized_nodes)
                        sponsored = sponsor_details(conn, "workflow", workflow, viewer=user_id)
                        # Run state never fails the read; node names follow
                        # the same rule as the state's names.
                        states = best_effort(
                            conn, "the workflow's resource states",
                            lambda: resource_states(conn, "workflow", workflow, refs, user_id), [],
                        )
                        audience = best_effort(
                            conn, "the workflow's audience",
                            lambda: sponsor_audience(conn, "workflow", workflow, states, sponsored), None,
                        )
                        visible = named_ref_keys(states)
            ref_details = (
                _node_ref_details(serialized_nodes, visible)
                if visible is not None
                else {"tools": [], "sources": []}
            )
        except Exception as err:
            return _workflow_error_response("Failed to fetch workflow", err)

        return success_response(
            {
                "workflow": serialize_workflow(workflow),
                "nodes": serialized_nodes,
                "edges": [serialize_edge(e) for e in edges],
                "resource_sponsors": sponsored,
                "resource_states": states,
                "ref_details": ref_details,
                **({"sponsor_audience": audience} if audience is not None else {}),
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

        try:
            with db_session() as conn:
                repo = WorkflowsRepository(conn)
                try:
                    workflow, acting = _workflow_access(conn, workflow_id, user_id, "edit")
                except AccessDenied as denied:
                    return _denied(denied)
                # Validated as the owner: the workflow runs with the owner's
                # models, so their BYOM ids are the ones that must resolve.
                validation_errors = validate_workflow_structure(
                    nodes_data, edges_data, user_id=acting
                )
                if validation_errors:
                    return error_response(
                        "Workflow validation failed", errors=validation_errors
                    )
                nodes_data = normalize_agent_node_json_schemas(nodes_data)
                pg_workflow_id = str(workflow["id"])
                current_graph_version = get_workflow_graph_version(workflow)
                previous_nodes = [
                    serialize_node(n)
                    for n in WorkflowNodesRepository(conn).find_by_version(
                        pg_workflow_id, current_graph_version,
                    )
                ]
                # Every newly referenced node tool or source must be one the
                # caller may use, the owner included.
                denied = _new_node_ref_denied(conn, previous_nodes, nodes_data, user_id)
                if denied is not None:
                    return _denied(denied)
                # A node tool/source the owner can't use runs as the editor
                # who attached it (its sponsor): only someone who owns or
                # edits it, and only once ``confirm_sponsor`` lists it.
                plan = plan_sponsors(
                    conn,
                    "workflow",
                    workflow,
                    acting,
                    user_id,
                    _node_refs(nodes_data),
                    previous_refs=_node_refs(previous_nodes),
                    confirmed=parse_confirmations(data.get("confirm_sponsor")),
                )
                refusal = sponsor_refusal(conn, "workflow", workflow, plan)
                if refusal is not None:
                    body, status = refusal
                    body.setdefault("error", body["message"])
                    return make_response(jsonify(body), status)
                next_graph_version = current_graph_version + 1

                _write_graph(
                    conn, pg_workflow_id, next_graph_version,
                    nodes_data, edges_data,
                )
                workflow_fields = {
                    "name": name,
                    "description": description,
                    "current_graph_version": next_graph_version,
                }
                if plan.sponsors != (workflow.get("resource_sponsors") or {}):
                    workflow_fields["resource_sponsors"] = plan.sponsors
                repo.update(pg_workflow_id, acting, workflow_fields)
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
                try:
                    workflow, acting = _workflow_access(conn, workflow_id, user_id, "delete")
                except AccessDenied as denied:
                    return _denied(denied)
                # ON DELETE CASCADE on workflow_nodes/edges cleans children.
                repo.delete(str(workflow["id"]), acting)
        except Exception as err:
            return _workflow_error_response("Failed to delete workflow", err)

        return success_response()
