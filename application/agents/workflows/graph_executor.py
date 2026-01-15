import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Generator, List, Optional, Union

from application.agents.workflows.schemas import (
    ExecutionStatus,
    NodeExecutionLog,
    NodeType,
    WorkflowDefinition,
    WorkflowNode,
)

if TYPE_CHECKING:
    from application.agents.base import BaseAgent

logger = logging.getLogger(__name__)

StateValue = Union[str, int, float, bool, None]
WorkflowState = Dict[str, StateValue]


class GraphExecutor:
    MAX_EXECUTION_STEPS = 50

    def __init__(self, workflow: WorkflowDefinition, agent: "BaseAgent"):
        self.workflow = workflow
        self.agent = agent
        self.state: WorkflowState = {}
        self.execution_log: List[Dict[str, Union[str, datetime, Dict, None]]] = []

    def execute(
        self, initial_inputs: WorkflowState, query: str
    ) -> Generator[Dict[str, str], None, None]:
        self._initialize_state(initial_inputs, query)

        start_node = self.workflow.get_start_node()
        if not start_node:
            yield {"answer": "Error: No start node found in workflow."}
            return

        current_node_id: Optional[str] = start_node.id
        steps = 0

        while current_node_id and steps < self.MAX_EXECUTION_STEPS:
            node = self.workflow.get_node_by_id(current_node_id)
            if not node:
                yield {"answer": f"Error: Node {current_node_id} not found."}
                break

            log_entry = self._create_log_entry(node)
            try:
                yield from self._execute_node(node)
                log_entry["status"] = ExecutionStatus.COMPLETED.value
            except Exception as e:
                logger.error(f"Error executing node {node.id}: {e}")
                log_entry["status"] = ExecutionStatus.FAILED.value
                log_entry["error"] = str(e)
                self.execution_log.append(log_entry)
                break

            log_entry["end_time"] = datetime.utcnow()
            self.execution_log.append(log_entry)

            if node.type == NodeType.END:
                break

            current_node_id = self._get_next_node_id(current_node_id)
            steps += 1

        if steps >= self.MAX_EXECUTION_STEPS:
            logger.warning(
                f"Workflow {self.workflow.id} reached max steps limit ({self.MAX_EXECUTION_STEPS})"
            )

    def _initialize_state(self, initial_inputs: WorkflowState, query: str) -> None:
        self.state.update(initial_inputs)
        self.state["query"] = query
        self.state["chat_history"] = str(self.agent.chat_history)

    def _create_log_entry(
        self, node: WorkflowNode
    ) -> Dict[str, Union[str, datetime, Dict, None]]:
        return {
            "node_id": node.id,
            "node_type": node.type.value,
            "start_time": datetime.utcnow(),
            "end_time": None,
            "status": ExecutionStatus.RUNNING.value,
            "error": None,
            "state_snapshot": dict(self.state),
        }

    def _get_next_node_id(self, current_node_id: str) -> Optional[str]:
        edges = self.workflow.get_outgoing_edges(current_node_id)
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
        prompt_template = str(node.data.get("prompt_template", ""))
        formatted_prompt = self._format_template(prompt_template)

        system_prompt = str(
            node.data.get("system_prompt", "You are a helpful assistant.")
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": formatted_prompt},
        ]

        full_response = ""
        response_gen = self.agent._llm_gen(messages)

        for chunk in response_gen:
            chunk_text = self._extract_chunk_text(chunk)
            if chunk_text:
                full_response += chunk_text
                if node.data.get("stream_to_user", True):
                    yield {"answer": chunk_text}

        output_var = node.data.get("output_variable")
        if output_var and isinstance(output_var, str):
            self.state[output_var] = full_response

    def _execute_state_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        updates = node.data.get("updates", {})

        if not updates:
            var_name = node.data.get("variable")
            var_value = node.data.get("value")
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
        output_template = str(node.data.get("output_template", ""))
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

    def _extract_chunk_text(self, chunk: object) -> str:
        if isinstance(chunk, str):
            return chunk
        if hasattr(chunk, "message") and hasattr(chunk.message, "content"):
            content = chunk.message.content
            return str(content) if content else ""
        if hasattr(chunk, "content"):
            content = chunk.content
            return str(content) if content else ""
        return ""

    def get_execution_summary(self) -> List[NodeExecutionLog]:
        return [
            NodeExecutionLog(
                node_id=log["node_id"],
                node_type=log["node_type"],
                status=ExecutionStatus(log["status"]),
                started_at=log["start_time"],
                completed_at=log.get("end_time"),
                error=log.get("error"),
                state_snapshot=log.get("state_snapshot", {}),
            )
            for log in self.execution_log
        ]
