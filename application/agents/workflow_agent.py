import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from application.agents.base import BaseAgent
from application.agents.workflows.schemas import (
    ExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowRun,
)
from application.agents.workflows.workflow_engine import WorkflowEngine
from application.logging import log_activity, LogContext
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


class WorkflowAgent(BaseAgent):
    """A specialized agent that executes predefined workflows."""

    def __init__(
        self,
        *args,
        workflow_id: Optional[str] = None,
        workflow: Optional[Dict[str, Any]] = None,
        workflow_owner: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.workflow_id = workflow_id
        self.workflow_owner = workflow_owner
        self._workflow_data = workflow
        self._engine: Optional[WorkflowEngine] = None

    @log_activity()
    def gen(
        self, query: str, log_context: LogContext = None
    ) -> Generator[Dict[str, str], None, None]:
        yield from self._gen_inner(query, log_context)

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict[str, str], None, None]:
        graph = self._load_workflow_graph()
        if not graph:
            yield {"type": "error", "error": "Failed to load workflow configuration."}
            return
        self._engine = WorkflowEngine(graph, self)
        yield from self._engine.execute({}, query)
        self._save_workflow_run(query)

    def _load_workflow_graph(self) -> Optional[WorkflowGraph]:
        if self._workflow_data:
            return self._parse_embedded_workflow()
        if self.workflow_id:
            return self._load_from_database()
        return None

    def _parse_embedded_workflow(self) -> Optional[WorkflowGraph]:
        try:
            nodes_data = self._workflow_data.get("nodes", [])
            edges_data = self._workflow_data.get("edges", [])

            workflow = Workflow(
                name=self._workflow_data.get("name", "Embedded Workflow"),
                description=self._workflow_data.get("description"),
            )

            nodes = []
            for n in nodes_data:
                node_config = n.get("data", {})
                nodes.append(
                    WorkflowNode(
                        id=n["id"],
                        workflow_id=self.workflow_id or "embedded",
                        type=n["type"],
                        title=n.get("title", "Node"),
                        description=n.get("description"),
                        position=n.get("position", {"x": 0, "y": 0}),
                        config=node_config,
                    )
                )
            edges = []
            for e in edges_data:
                edges.append(
                    WorkflowEdge(
                        id=e["id"],
                        workflow_id=self.workflow_id or "embedded",
                        source=e.get("source") or e.get("source_id"),
                        target=e.get("target") or e.get("target_id"),
                        sourceHandle=e.get("sourceHandle") or e.get("source_handle"),
                        targetHandle=e.get("targetHandle") or e.get("target_handle"),
                    )
                )
            return WorkflowGraph(workflow=workflow, nodes=nodes, edges=edges)
        except Exception as e:
            logger.error(f"Invalid embedded workflow: {e}")
            return None

    def _load_from_database(self) -> Optional[WorkflowGraph]:
        try:
            if not self.workflow_id:
                logger.error("Missing workflow ID for load")
                return None
            owner_id = self.workflow_owner
            if not owner_id and isinstance(self.decoded_token, dict):
                owner_id = self.decoded_token.get("sub")
            if not owner_id:
                logger.error(
                    f"Workflow owner not available for workflow load: {self.workflow_id}"
                )
                return None

            with db_readonly() as conn:
                wf_repo = WorkflowsRepository(conn)
                if looks_like_uuid(self.workflow_id):
                    workflow_row = wf_repo.get(self.workflow_id, owner_id)
                else:
                    workflow_row = wf_repo.get_by_legacy_id(self.workflow_id, owner_id)
                if workflow_row is None:
                    logger.error(
                        f"Workflow {self.workflow_id} not found or inaccessible "
                        f"for user {owner_id}"
                    )
                    return None
                pg_workflow_id = str(workflow_row["id"])
                graph_version = workflow_row.get("current_graph_version", 1)
                try:
                    graph_version = int(graph_version)
                    if graph_version <= 0:
                        graph_version = 1
                except (ValueError, TypeError):
                    graph_version = 1

                node_rows = WorkflowNodesRepository(conn).find_by_version(
                    pg_workflow_id, graph_version,
                )
                edge_rows = WorkflowEdgesRepository(conn).find_by_version(
                    pg_workflow_id, graph_version,
                )

            workflow = Workflow(
                name=workflow_row.get("name"),
                description=workflow_row.get("description"),
            )
            nodes = [
                WorkflowNode(
                    id=n["node_id"],
                    workflow_id=pg_workflow_id,
                    type=n["node_type"],
                    title=n.get("title") or "Node",
                    description=n.get("description"),
                    position=n.get("position") or {"x": 0, "y": 0},
                    config=n.get("config") or {},
                )
                for n in node_rows
            ]
            edges = [
                WorkflowEdge(
                    id=e["edge_id"],
                    workflow_id=pg_workflow_id,
                    source=e.get("source_id"),
                    target=e.get("target_id"),
                    sourceHandle=e.get("source_handle"),
                    targetHandle=e.get("target_handle"),
                )
                for e in edge_rows
            ]

            return WorkflowGraph(workflow=workflow, nodes=nodes, edges=edges)
        except Exception as e:
            logger.error(f"Failed to load workflow from database: {e}")
            return None

    def _save_workflow_run(self, query: str) -> None:
        if not self._engine:
            return
        owner_id = self.workflow_owner
        if not owner_id and isinstance(self.decoded_token, dict):
            owner_id = self.decoded_token.get("sub")
        try:
            run = WorkflowRun(
                workflow_id=self.workflow_id or "unknown",
                user=owner_id,
                status=self._determine_run_status(),
                inputs={"query": query},
                outputs=self._serialize_state(self._engine.state),
                steps=self._engine.get_execution_summary(),
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

            if not self.workflow_id or not owner_id:
                return
            with db_session() as conn:
                wf_repo = WorkflowsRepository(conn)
                if looks_like_uuid(self.workflow_id):
                    workflow_row = wf_repo.get(self.workflow_id, owner_id)
                else:
                    workflow_row = wf_repo.get_by_legacy_id(
                        self.workflow_id, owner_id,
                    )
                if workflow_row is None:
                    return
                WorkflowRunsRepository(conn).create(
                    str(workflow_row["id"]),
                    owner_id,
                    run.status.value,
                    inputs=run.inputs,
                    result=run.outputs,
                    steps=[step.model_dump(mode="json") for step in run.steps],
                    started_at=run.created_at,
                    ended_at=run.completed_at,
                )
        except Exception as e:
            logger.error(f"Failed to save workflow run: {e}")

    def _determine_run_status(self) -> ExecutionStatus:
        if not self._engine or not self._engine.execution_log:
            return ExecutionStatus.COMPLETED
        for log in self._engine.execution_log:
            if log.get("status") == ExecutionStatus.FAILED.value:
                return ExecutionStatus.FAILED
        return ExecutionStatus.COMPLETED

    def _serialize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        serialized: Dict[str, Any] = {}
        for key, value in state.items():
            serialized[key] = self._serialize_state_value(value)
        return serialized

    def _serialize_state_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(dict_key): self._serialize_state_value(dict_value)
                for dict_key, dict_value in value.items()
            }
        if isinstance(value, list):
            return [self._serialize_state_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._serialize_state_value(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        return str(value)
