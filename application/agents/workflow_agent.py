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
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.logging import log_activity, LogContext

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
            from bson.objectid import ObjectId

            if not self.workflow_id or not ObjectId.is_valid(self.workflow_id):
                logger.error(f"Invalid workflow ID: {self.workflow_id}")
                return None
            owner_id = self.workflow_owner
            if not owner_id and isinstance(self.decoded_token, dict):
                owner_id = self.decoded_token.get("sub")
            if not owner_id:
                logger.error(
                    f"Workflow owner not available for workflow load: {self.workflow_id}"
                )
                return None

            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]

            workflows_coll = db["workflows"]
            workflow_nodes_coll = db["workflow_nodes"]
            workflow_edges_coll = db["workflow_edges"]

            workflow_doc = workflows_coll.find_one(
                {"_id": ObjectId(self.workflow_id), "user": owner_id}
            )
            if not workflow_doc:
                logger.error(
                    f"Workflow {self.workflow_id} not found or inaccessible for user {owner_id}"
                )
                return None
            workflow = Workflow(**workflow_doc)
            graph_version = workflow_doc.get("current_graph_version", 1)
            try:
                graph_version = int(graph_version)
                if graph_version <= 0:
                    graph_version = 1
            except (ValueError, TypeError):
                graph_version = 1

            nodes_docs = list(
                workflow_nodes_coll.find(
                    {"workflow_id": self.workflow_id, "graph_version": graph_version}
                )
            )
            if not nodes_docs and graph_version == 1:
                nodes_docs = list(
                    workflow_nodes_coll.find(
                        {
                            "workflow_id": self.workflow_id,
                            "graph_version": {"$exists": False},
                        }
                    )
                )
            nodes = [WorkflowNode(**doc) for doc in nodes_docs]

            edges_docs = list(
                workflow_edges_coll.find(
                    {"workflow_id": self.workflow_id, "graph_version": graph_version}
                )
            )
            if not edges_docs and graph_version == 1:
                edges_docs = list(
                    workflow_edges_coll.find(
                        {
                            "workflow_id": self.workflow_id,
                            "graph_version": {"$exists": False},
                        }
                    )
                )
            edges = [WorkflowEdge(**doc) for doc in edges_docs]

            return WorkflowGraph(workflow=workflow, nodes=nodes, edges=edges)
        except Exception as e:
            logger.error(f"Failed to load workflow from database: {e}")
            return None

    def _save_workflow_run(self, query: str) -> None:
        if not self._engine:
            return
        try:
            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            workflow_runs_coll = db["workflow_runs"]

            run = WorkflowRun(
                workflow_id=self.workflow_id or "unknown",
                status=self._determine_run_status(),
                inputs={"query": query},
                outputs=self._serialize_state(self._engine.state),
                steps=self._engine.get_execution_summary(),
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

            workflow_runs_coll.insert_one(run.to_mongo_doc())
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
            if isinstance(value, (str, int, float, bool, type(None))):
                serialized[key] = value
            else:
                serialized[key] = str(value)
        return serialized
