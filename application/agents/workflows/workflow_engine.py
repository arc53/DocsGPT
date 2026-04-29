import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, TYPE_CHECKING

from application.agents.workflows.cel_evaluator import CelEvaluationError, evaluate_cel
from application.agents.workflows.node_agent import WorkflowNodeAgentFactory
from application.agents.workflows.schemas import (
    AgentNodeConfig,
    AgentType,
    ConditionNodeConfig,
    ExecutionStatus,
    NodeExecutionLog,
    NodeType,
    WorkflowGraph,
    WorkflowNode,
)
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.error import sanitize_api_error
from application.templates.namespaces import NamespaceManager
from application.templates.template_engine import TemplateEngine, TemplateRenderError

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency in some deployments.
    jsonschema = None

if TYPE_CHECKING:
    from application.agents.base import BaseAgent
logger = logging.getLogger(__name__)

StateValue = Any
WorkflowState = Dict[str, StateValue]
TEMPLATE_RESERVED_NAMESPACES = {"agent", "system", "source", "tools", "passthrough"}


class WorkflowEngine:
    MAX_EXECUTION_STEPS = 50

    def __init__(self, graph: WorkflowGraph, agent: "BaseAgent"):
        self.graph = graph
        self.agent = agent
        self.state: WorkflowState = {}
        self.execution_log: List[Dict[str, Any]] = []
        self._condition_result: Optional[str] = None
        self._template_engine = TemplateEngine()
        self._namespace_manager = NamespaceManager()

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

                user_friendly_error = sanitize_api_error(e)
                yield {
                    "type": "workflow_step",
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "node_title": node.title,
                    "status": "failed",
                    "state_snapshot": dict(self.state),
                    "error": user_friendly_error,
                }
                yield {"type": "error", "error": user_friendly_error}
                break
            log_entry["state_snapshot"] = dict(self.state)
            self.execution_log.append(log_entry)

            if node.type == NodeType.END:
                break
            current_node_id = self._get_next_node_id(current_node_id)
            if current_node_id is None and node.type != NodeType.END:
                logger.warning(
                    f"Branch ended at node '{node.title}' ({node.id}) without reaching an end node"
                )
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
        node = self.graph.get_node_by_id(current_node_id)
        edges = self.graph.get_outgoing_edges(current_node_id)
        if not edges:
            return None

        if node and node.type == NodeType.CONDITION and self._condition_result:
            target_handle = self._condition_result
            self._condition_result = None
            for edge in edges:
                if edge.source_handle == target_handle:
                    return edge.target_id
            return None

        return edges[0].target_id

    def _execute_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        logger.info(f"Executing node {node.id} ({node.type.value})")

        node_handlers = {
            NodeType.START: self._execute_start_node,
            NodeType.NOTE: self._execute_note_node,
            NodeType.AGENT: self._execute_agent_node,
            NodeType.STATE: self._execute_state_node,
            NodeType.CONDITION: self._execute_condition_node,
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
        from application.core.model_utils import (
            get_api_key_for_provider,
            get_model_capabilities,
            get_provider_from_model_id,
        )

        node_config = AgentNodeConfig(**node.config.get("config", node.config))

        if node_config.sources:
            self._retrieve_node_sources(node_config)

        if node_config.prompt_template:
            formatted_prompt = self._format_template(node_config.prompt_template)
        else:
            formatted_prompt = self.state.get("query", "")
        node_json_schema = self._normalize_node_json_schema(
            node_config.json_schema, node.title
        )
        node_model_id = node_config.model_id or self.agent.model_id
        # Inherit BYOM scope from parent agent so owner-stored BYOM
        # resolves on shared workflows.
        node_user_id = getattr(self.agent, "model_user_id", None) or (
            self.agent.decoded_token.get("sub")
            if isinstance(self.agent.decoded_token, dict)
            else None
        )
        node_llm_name = (
            node_config.llm_name
            or get_provider_from_model_id(
                node_model_id or "", user_id=node_user_id
            )
            or self.agent.llm_name
        )
        node_api_key = get_api_key_for_provider(node_llm_name) or self.agent.api_key

        if node_json_schema and node_model_id:
            model_capabilities = get_model_capabilities(
                node_model_id, user_id=node_user_id
            )
            if model_capabilities and not model_capabilities.get(
                "supports_structured_output", False
            ):
                raise ValueError(
                    f'Model "{node_model_id}" does not support structured output for node "{node.title}"'
                )

        factory_kwargs = {
            "agent_type": node_config.agent_type,
            "endpoint": self.agent.endpoint,
            "llm_name": node_llm_name,
            "model_id": node_model_id,
            "model_user_id": getattr(self.agent, "model_user_id", None),
            "api_key": node_api_key,
            "tool_ids": node_config.tools,
            "prompt": node_config.system_prompt,
            "chat_history": self.agent.chat_history,
            "decoded_token": self.agent.decoded_token,
            "json_schema": node_json_schema,
        }

        # Agentic/research agents need retriever_config for on-demand search
        if node_config.agent_type in (AgentType.AGENTIC, AgentType.RESEARCH):
            factory_kwargs["retriever_config"] = {
                "source": {"active_docs": node_config.sources} if node_config.sources else {},
                "retriever_name": node_config.retriever or "classic",
                "chunks": int(node_config.chunks) if node_config.chunks else 2,
                "model_id": node_model_id,
                "llm_name": node_llm_name,
                "api_key": node_api_key,
                "decoded_token": self.agent.decoded_token,
            }

        node_agent = WorkflowNodeAgentFactory.create(**factory_kwargs)

        full_response_parts: List[str] = []
        structured_response_parts: List[str] = []
        has_structured_response = False
        first_chunk = True
        for event in node_agent.gen(formatted_prompt):
            if "answer" in event:
                chunk = str(event["answer"])
                full_response_parts.append(chunk)
                if event.get("structured"):
                    has_structured_response = True
                    structured_response_parts.append(chunk)
                if node_config.stream_to_user:
                    if first_chunk and hasattr(self, "_has_streamed"):
                        yield {"answer": "\n\n"}
                        first_chunk = False
                    yield event

        if node_config.stream_to_user:
            self._has_streamed = True

        full_response = "".join(full_response_parts).strip()
        output_value: Any = full_response
        if has_structured_response:
            structured_response = "".join(structured_response_parts).strip()
            response_to_parse = structured_response or full_response
            parsed_success, parsed_structured = self._parse_structured_output(
                response_to_parse
            )
            output_value = parsed_structured if parsed_success else response_to_parse
            if node_json_schema:
                self._validate_structured_output(node_json_schema, output_value)
        elif node_json_schema:
            parsed_success, parsed_structured = self._parse_structured_output(
                full_response
            )
            if not parsed_success:
                raise ValueError(
                    "Structured output was expected but response was not valid JSON"
                )
            output_value = parsed_structured
            self._validate_structured_output(node_json_schema, output_value)

        default_output_key = f"node_{node.id}_output"
        self.state[default_output_key] = output_value

        if node_config.output_variable:
            self.state[node_config.output_variable] = output_value

    def _execute_state_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        config = node.config.get("config", node.config)
        for op in config.get("operations", []):
            expression = op.get("expression", "")
            target_variable = op.get("target_variable", "")
            if expression and target_variable:
                self.state[target_variable] = evaluate_cel(expression, self.state)
        yield from ()

    def _execute_condition_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        config = ConditionNodeConfig(**node.config.get("config", node.config))
        matched_handle = None

        for case in config.cases:
            if not case.expression.strip():
                continue
            try:
                if evaluate_cel(case.expression, self.state):
                    matched_handle = case.source_handle
                    break
            except CelEvaluationError:
                continue

        self._condition_result = matched_handle or "else"
        yield from ()

    def _execute_end_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        config = node.config.get("config", node.config)
        output_template = str(config.get("output_template", ""))
        if output_template:
            formatted_output = self._format_template(output_template)
            yield {"answer": formatted_output}

    def _parse_structured_output(self, raw_response: str) -> tuple[bool, Optional[Any]]:
        normalized_response = raw_response.strip()
        if not normalized_response:
            return False, None

        try:
            return True, json.loads(normalized_response)
        except json.JSONDecodeError:
            logger.warning(
                "Workflow agent returned structured output that was not valid JSON"
            )
            return False, None

    def _normalize_node_json_schema(
        self, schema: Optional[Dict[str, Any]], node_title: str
    ) -> Optional[Dict[str, Any]]:
        if schema is None:
            return None
        try:
            return normalize_json_schema_payload(schema)
        except JsonSchemaValidationError as exc:
            raise ValueError(
                f'Invalid JSON schema for node "{node_title}": {exc}'
            ) from exc

    def _validate_structured_output(self, schema: Dict[str, Any], output_value: Any) -> None:
        if jsonschema is None:
            logger.warning(
                "jsonschema package is not available, skipping structured output validation"
            )
            return

        try:
            normalized_schema = normalize_json_schema_payload(schema)
        except JsonSchemaValidationError as exc:
            raise ValueError(f"Invalid JSON schema: {exc}") from exc

        try:
            jsonschema.validate(instance=output_value, schema=normalized_schema)
        except jsonschema.exceptions.ValidationError as exc:
            raise ValueError(f"Structured output did not match schema: {exc.message}") from exc
        except jsonschema.exceptions.SchemaError as exc:
            raise ValueError(f"Invalid JSON schema: {exc.message}") from exc

    def _format_template(self, template: str) -> str:
        context = self._build_template_context()
        try:
            return self._template_engine.render(template, context)
        except TemplateRenderError as e:
            logger.warning(
                "Workflow template rendering failed, using raw template: %s", str(e)
            )
            return template

    def _build_template_context(self) -> Dict[str, Any]:
        docs, docs_together = self._get_source_template_data()
        passthrough_data = (
            self.state.get("passthrough")
            if isinstance(self.state.get("passthrough"), dict)
            else None
        )
        tools_data = (
            self.state.get("tools") if isinstance(self.state.get("tools"), dict) else None
        )

        context = self._namespace_manager.build_context(
            user_id=getattr(self.agent, "user", None),
            request_id=getattr(self.agent, "request_id", None),
            passthrough_data=passthrough_data,
            docs=docs,
            docs_together=docs_together,
            tools_data=tools_data,
        )

        agent_context: Dict[str, Any] = {}
        for key, value in self.state.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.strip()
            if not normalized_key:
                continue
            agent_context[normalized_key] = value

        context["agent"] = agent_context

        # Keep legacy top-level variables working while namespaced variables are adopted.
        for key, value in agent_context.items():
            if key in TEMPLATE_RESERVED_NAMESPACES:
                context[f"agent_{key}"] = value
                continue
            if key not in context:
                context[key] = value

        return context

    def _get_source_template_data(self) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        docs = getattr(self.agent, "retrieved_docs", None)
        if not isinstance(docs, list) or len(docs) == 0:
            return None, None

        docs_together_parts: List[str] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            text = doc.get("text")
            if not isinstance(text, str):
                continue

            filename = doc.get("filename") or doc.get("title") or doc.get("source")
            if isinstance(filename, str) and filename.strip():
                docs_together_parts.append(f"{filename}\n{text}")
            else:
                docs_together_parts.append(text)

        docs_together = "\n\n".join(docs_together_parts) if docs_together_parts else None
        return docs, docs_together

    def _retrieve_node_sources(self, node_config: AgentNodeConfig) -> None:
        """Retrieve documents from the node's sources for template resolution."""
        from application.retriever.retriever_creator import RetrieverCreator

        query = self.state.get("query", "")
        if not query:
            return

        try:
            retriever = RetrieverCreator.create_retriever(
                node_config.retriever or "classic",
                source={"active_docs": node_config.sources},
                chat_history=[],
                prompt="",
                chunks=int(node_config.chunks) if node_config.chunks else 2,
                decoded_token=self.agent.decoded_token,
            )
            docs = retriever.search(query)
            if docs:
                self.agent.retrieved_docs = docs
        except Exception:
            logger.exception("Failed to retrieve docs for workflow node")

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
