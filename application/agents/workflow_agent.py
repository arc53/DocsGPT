import logging
from datetime import datetime
from typing import Dict, Generator, Optional, Union

from application.agents.base import BaseAgent
from application.agents.workflows.graph_executor import GraphExecutor
from application.agents.workflows.schemas import (
    ExecutionStatus,
    WorkflowDefinition,
    WorkflowRun,
)
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.logging import log_activity, LogContext

logger = logging.getLogger(__name__)

WorkflowData = Dict[str, Union[str, list, dict, None]]


class WorkflowAgent(BaseAgent):
    def __init__(
        self,
        *args,
        workflow_id: Optional[str] = None,
        workflow: Optional[WorkflowData] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.workflow_id = workflow_id
        self._workflow_data = workflow
        self._executor: Optional[GraphExecutor] = None

    @log_activity()
    def gen(
        self, query: str, log_context: LogContext = None
    ) -> Generator[Dict[str, str], None, None]:
        yield from self._gen_inner(query, log_context)

    def _gen_inner(
        self, query: str, log_context: LogContext
    ) -> Generator[Dict[str, str], None, None]:
        if not self._workflow_data:
            yield {"answer": "Error: No workflow definition provided."}
            return

        workflow = self._parse_workflow_definition()
        if not workflow:
            yield {"answer": "Error: Failed to parse workflow definition."}
            return

        self._executor = GraphExecutor(workflow, self)
        yield from self._executor.execute({}, query)
        self._save_workflow_run(query)

    def _parse_workflow_definition(self) -> Optional[WorkflowDefinition]:
        if isinstance(self._workflow_data, WorkflowDefinition):
            return self._workflow_data

        if isinstance(self._workflow_data, dict):
            try:
                return WorkflowDefinition(**self._workflow_data)
            except Exception as e:
                logger.error(f"Invalid workflow definition: {e}")
                return None

        return None

    def _save_workflow_run(self, query: str) -> None:
        if not self._executor:
            return

        try:
            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            runs_collection = db["workflow_runs"]

            run = WorkflowRun(
                workflow_id=self.workflow_id or "unknown",
                status=self._determine_run_status(),
                inputs={"query": query},
                outputs=self._serialize_state(self._executor.state),
                steps=self._executor.get_execution_summary(),
                created_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )

            runs_collection.insert_one(run.to_mongo_doc())
        except Exception as e:
            logger.error(f"Failed to save workflow run: {e}")

    def _determine_run_status(self) -> ExecutionStatus:
        if not self._executor or not self._executor.execution_log:
            return ExecutionStatus.COMPLETED

        for log in self._executor.execution_log:
            if log.get("status") == ExecutionStatus.FAILED.value:
                return ExecutionStatus.FAILED

        return ExecutionStatus.COMPLETED

    def _serialize_state(
        self, state: Dict[str, Union[str, int, float, bool, None]]
    ) -> Dict[str, Union[str, int, float, bool, None]]:
        serialized: Dict[str, Union[str, int, float, bool, None]] = {}
        for key, value in state.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                serialized[key] = value
            else:
                serialized[key] = str(value)
        return serialized
