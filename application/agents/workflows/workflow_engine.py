import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, TYPE_CHECKING

from application.agents.workflows.node_agent import WorkflowNodeAgentFactory
from application.agents.workflows.schemas import (
    AgentNodeConfig,
    ExecutionStatus,
    NodeExecutionLog,
    NodeType,
    WorkflowGraph,
    WorkflowNode,
)

if TYPE_CHECKING:
    from application.agents.base import BaseAgent
logger = logging.getLogger(__name__)

StateValue = Any
WorkflowState = Dict[str, StateValue]


class WorkflowEngine:
    MAX_EXECUTION_STEPS = 50

    def __init__(self, graph: WorkflowGraph, agent: "BaseAgent"):
        self.graph = graph
        self.agent = agent
        self.state: WorkflowState = {}
        self.execution_log: List[Dict[str, Any]] = []

    def execute(
        self, initial_inputs: WorkflowState, query: str
    ) -> Generator[Dict[str, str], None, None]:
        self._initialize_state(initial_inputs, query)

        start_node = self.graph.get_start_node()
        if not start_node:
            yield {"type": "error", "error": "No start node found in workflow."}
            return
        current_node_id: Optional[str] = start_node.id
        steps = 0

        while current_node_id and steps < self.MAX_EXECUTION_STEPS:
            node = self.graph.get_node_by_id(current_node_id)
            if not node:
                yield {"type": "error", "error": f"Node {current_node_id} not found."}
                break
            log_entry = self._create_log_entry(node)

            yield {
                "type": "workflow_step",
                "node_id": node.id,
                "node_type": node.type.value,
                "node_title": node.title,
                "status": "running",
            }

            try:
                yield from self._execute_node(node)
                log_entry["status"] = ExecutionStatus.COMPLETED.value
                log_entry["completed_at"] = datetime.now(timezone.utc)

                output_key = f"node_{node.id}_output"
                node_output = self.state.get(output_key)

                yield {
                    "type": "workflow_step",
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "node_title": node.title,
                    "status": "completed",
                    "state_snapshot": dict(self.state),
                    "output": node_output,
                }
            except Exception as e:
                logger.error(f"Error executing node {node.id}: {e}", exc_info=True)
                log_entry["status"] = ExecutionStatus.FAILED.value
                log_entry["error"] = str(e)
                log_entry["completed_at"] = datetime.now(timezone.utc)
                log_entry["state_snapshot"] = dict(self.state)
                self.execution_log.append(log_entry)

                yield {
                    "type": "workflow_step",
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "node_title": node.title,
                    "status": "failed",
                    "state_snapshot": dict(self.state),
                    "error": str(e),
                }
                yield {"type": "error", "error": str(e)}
                break
            log_entry["state_snapshot"] = dict(self.state)
            self.execution_log.append(log_entry)

            if node.type == NodeType.END:
                break
            current_node_id = self._get_next_node_id(current_node_id)
            steps += 1
        if steps >= self.MAX_EXECUTION_STEPS:
            logger.warning(
                f"Workflow reached max steps limit ({self.MAX_EXECUTION_STEPS})"
            )

    def _initialize_state(self, initial_inputs: WorkflowState, query: str) -> None:
        self.state.update(initial_inputs)
        self.state["query"] = query
        self.state["chat_history"] = str(self.agent.chat_history)

    def _create_log_entry(self, node: WorkflowNode) -> Dict[str, Any]:
        return {
            "node_id": node.id,
            "node_type": node.type.value,
            "started_at": datetime.now(timezone.utc),
            "completed_at": None,
            "status": ExecutionStatus.RUNNING.value,
            "error": None,
            "state_snapshot": {},
        }

    def _get_next_node_id(self, current_node_id: str) -> Optional[str]:
        edges = self.graph.get_outgoing_edges(current_node_id)
        if edges:
            return edges[0].target_id
        return None

    def _execute_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        logger.info(f"Executing node {node.id} ({node.type.value})")

        node_handlers = {
            NodeType.START: self._execute_start_node,
            NodeType.NOTE: self._execute_note_node,
            NodeType.AGENT: self._execute_agent_node,
            NodeType.STATE: self._execute_state_node,
            NodeType.END: self._execute_end_node,
        }

        handler = node_handlers.get(node.type)
        if handler:
            yield from handler(node)

    def _execute_start_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        yield from ()

    def _execute_note_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        yield from ()

    def _execute_agent_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        from application.core.model_utils import get_api_key_for_provider

        node_config = AgentNodeConfig(**node.config)

        if node_config.prompt_template:
            formatted_prompt = self._format_template(node_config.prompt_template)
        else:
            formatted_prompt = self.state.get("query", "")
        node_llm_name = node_config.llm_name or self.agent.llm_name
        node_api_key = get_api_key_for_provider(node_llm_name) or self.agent.api_key

        node_agent = WorkflowNodeAgentFactory.create(
            agent_type=node_config.agent_type,
            endpoint=self.agent.endpoint,
            llm_name=node_llm_name,
            model_id=node_config.model_id or self.agent.model_id,
            api_key=node_api_key,
            tool_ids=node_config.tools,
            prompt=node_config.system_prompt,
            chat_history=self.agent.chat_history,
            decoded_token=self.agent.decoded_token,
            json_schema=node_config.json_schema,
        )

        full_response = ""
        first_chunk = True
        for event in node_agent.gen(formatted_prompt):
            if "answer" in event:
                full_response += event["answer"]
                if node_config.stream_to_user:
                    if first_chunk and hasattr(self, "_has_streamed"):
                        yield {"answer": "\n\n"}
                        first_chunk = False
                    yield event

        if node_config.stream_to_user:
            self._has_streamed = True

        output_key = node_config.output_variable or f"node_{node.id}_output"
        self.state[output_key] = full_response

    def _execute_state_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        config = node.config
        operations = config.get("operations", [])

        if operations:
            for op in operations:
                key = op.get("key")
                operation = op.get("operation", "set")
                value = op.get("value")

                if not key:
                    continue
                if operation == "set":
                    formatted_value = (
                        self._format_template(str(value))
                        if isinstance(value, str)
                        else value
                    )
                    self.state[key] = formatted_value
                elif operation == "increment":
                    current = self.state.get(key, 0)
                    try:
                        self.state[key] = int(current) + int(value or 1)
                    except (ValueError, TypeError):
                        self.state[key] = 1
                elif operation == "append":
                    if key not in self.state:
                        self.state[key] = []
                    if isinstance(self.state[key], list):
                        self.state[key].append(value)
        else:
            updates = config.get("updates", {})
            if not updates:
                var_name = config.get("variable")
                var_value = config.get("value")
                if var_name and isinstance(var_name, str):
                    updates = {var_name: var_value or ""}
            if isinstance(updates, dict):
                for key, value in updates.items():
                    if isinstance(value, str):
                        self.state[key] = self._format_template(value)
                    else:
                        self.state[key] = value
        yield from ()

    def _execute_end_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        config = node.config
        output_template = str(config.get("output_template", ""))
        if output_template:
            formatted_output = self._format_template(output_template)
            yield {"answer": formatted_output}

    def _format_template(self, template: str) -> str:
        formatted = template
        for key, value in self.state.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in formatted and value is not None:
                formatted = formatted.replace(placeholder, str(value))
        return formatted

    def get_execution_summary(self) -> List[NodeExecutionLog]:
        return [
            NodeExecutionLog(
                node_id=log["node_id"],
                node_type=log["node_type"],
                status=ExecutionStatus(log["status"]),
                started_at=log["started_at"],
                completed_at=log.get("completed_at"),
                error=log.get("error"),
                state_snapshot=log.get("state_snapshot", {}),
            )
            for log in self.execution_log
        ]
