import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, TYPE_CHECKING

from application.agents.workflows.cel_evaluator import CelEvaluationError, evaluate_cel
from application.agents.workflows.node_agent import WorkflowNodeAgentFactory
from application.agents.workflows.schemas import (
    AgentNodeConfig,
    AgentType,
    CodeNodeConfig,
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
TEMPLATE_RESERVED_NAMESPACES = {"agent", "artifacts", "system", "source", "tools", "passthrough"}

# Run ids become a sandbox-session / kernel-workspace path component; the gateway
# only accepts [A-Za-z0-9_-]+, so any disallowed character is stripped before binding.
_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")

# State keys never staged into a code node's ``state.json``. ``chat_history`` is
# the caller's conversation and must not be reachable by owner-authored,
# egress-open sandbox code (see ``_json_safe_state``).
_CODE_STATE_EXCLUDED_KEYS = frozenset({"chat_history"})

# Sentinel id stamped on the synthetic text attachment that flags documents a
# node skipped past the per-node blocking-extract cap (callers/tests match on it).
_EXTRACT_TRUNCATION_ID = "workflow-extract-truncated"


class WorkflowEngine:
    MAX_EXECUTION_STEPS = 50

    def __init__(
        self,
        graph: WorkflowGraph,
        agent: "BaseAgent",
        workflow_run_id: Optional[str] = None,
    ):
        """Bind the engine to a graph + agent; mint a run id for run-scoped sandbox/artifacts."""
        self.graph = graph
        self.agent = agent
        # The run id scopes the code-node sandbox session and every produced
        # artifact's parent; mint one when the caller has not supplied a
        # pre-created ``workflow_runs`` id so the engine is self-contained.
        self.workflow_run_id: str = workflow_run_id or str(uuid.uuid4())
        # Per-node tool-call summary collected by the node executors and folded
        # into the step log; reset before each node runs.
        self._last_node_tool_calls: List[Dict[str, Any]] = []
        # False when no ``workflow_runs`` row backs ``workflow_run_id`` (unsaved /
        # embedded draft), so run-scoped artifacts must NOT be persisted as orphans.
        # Defaults True; WorkflowAgent flips it off on the draft path.
        self.run_persisted: bool = True
        self.state: WorkflowState = {}
        self.execution_log: List[Dict[str, Any]] = []
        self._condition_result: Optional[str] = None
        self._template_engine = TemplateEngine()
        self._namespace_manager = NamespaceManager()

    def execute(
        self, initial_inputs: WorkflowState, query: str
    ) -> Generator[Dict[str, str], None, None]:
        """Run the workflow graph, closing the run-scoped sandbox session once when the run ends."""
        try:
            yield from self._run_graph(initial_inputs, query)
        finally:
            # The sandbox session is keyed by the run id and shared by every code
            # node and agent-node tool in this run, so it is torn down exactly once
            # here rather than per node. peek_manager() never builds the manager, so
            # a run that never opened a session closes nothing.
            from application.sandbox.sandbox_creator import SandboxCreator

            mgr = SandboxCreator.peek_manager()
            if mgr is not None:
                try:
                    mgr.close(self._session_id())
                except Exception:
                    logger.exception("Workflow run failed to close its sandbox session")

    def _run_graph(
        self, initial_inputs: WorkflowState, query: str
    ) -> Generator[Dict[str, str], None, None]:
        self._initialize_state(initial_inputs, query)

        # Surface the run id up front so the client can list this run's
        # artifacts (GET /api/artifacts?workflow_run_id=) once it has been
        # persisted; the same id parents every artifact produced by code nodes.
        yield {"type": "workflow_run", "workflow_run_id": self.workflow_run_id}

        start_node = self.graph.get_start_node()
        if not start_node:
            yield {"type": "error", "error": "No start node found in workflow."}
            return
        current_node_id: Optional[str] = start_node.id
        steps = 0
        # Snapshots are stored as per-node DELTAS: full state copied into
        # every step grows the run row O(n^2) and repeats every upstream
        # output verbatim. Point-in-time state = merge of deltas up to a step.
        # The empty baseline attributes the pre-loop initialization (query,
        # input documents) to the first step so steps alone reconstruct state.
        pre_state: Dict[str, Any] = {}

        while current_node_id and steps < self.MAX_EXECUTION_STEPS:
            node = self.graph.get_node_by_id(current_node_id)
            if not node:
                yield {"type": "error", "error": f"Node {current_node_id} not found."}
                break
            log_entry = self._create_log_entry(node)
            self._last_node_tool_calls = []

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
                self._finalize_log_entry(log_entry, pre_state)

                output_key = f"node_{node.id}_output"
                node_output = self.state.get(output_key)

                yield {
                    "type": "workflow_step",
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "node_title": node.title,
                    "status": "completed",
                    "state_delta": log_entry["state_delta"],
                    "output": node_output,
                }
            except Exception as e:
                logger.error(f"Error executing node {node.id}: {e}", exc_info=True)
                log_entry["status"] = ExecutionStatus.FAILED.value
                log_entry["error"] = str(e)
                self._finalize_log_entry(log_entry, pre_state)
                self.execution_log.append(log_entry)

                user_friendly_error = sanitize_api_error(e)
                yield {
                    "type": "workflow_step",
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "node_title": node.title,
                    "status": "failed",
                    "state_delta": log_entry["state_delta"],
                    "error": user_friendly_error,
                }
                yield {"type": "error", "error": user_friendly_error}
                break
            self.execution_log.append(log_entry)
            pre_state = dict(self.state)

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
            "state_delta": {},
        }

    def _finalize_log_entry(self, log_entry: Dict[str, Any], pre_state: Dict[str, Any]) -> None:
        """Stamp completion time, duration, the node's state delta, and its tool-call summary."""
        completed_at = datetime.now(timezone.utc)
        log_entry["completed_at"] = completed_at
        log_entry["duration_ms"] = int((completed_at - log_entry["started_at"]).total_seconds() * 1000)
        log_entry["state_delta"] = self._state_delta(pre_state)
        if self._last_node_tool_calls:
            log_entry["tool_calls"] = list(self._last_node_tool_calls)

    def _state_delta(self, previous: Dict[str, Any]) -> Dict[str, Any]:
        """Keys this node added or changed. Deleted keys are not tracked; nothing deletes state today."""
        return {
            key: value
            for key, value in self.state.items()
            if key not in previous or previous[key] != value
        }

    @staticmethod
    def _summarize_tool_calls(node_agent: Any) -> List[Dict[str, Any]]:
        """Compact per-node tool-call summary for the run record (no arguments/results)."""
        executor = getattr(node_agent, "tool_executor", None)
        calls = getattr(executor, "tool_calls", None) or []
        return [
            {
                "tool_name": call.get("tool_name"),
                "action_name": call.get("action_name"),
                "status": call.get("status", "completed"),
            }
            for call in calls
        ]

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
            NodeType.CODE: self._execute_code_node,
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

        # Structured output gates on the model's registry capability flags;
        # fetch them only when a node json_schema needs the check.
        if node_json_schema and node_model_id:
            model_capabilities = get_model_capabilities(node_model_id, user_id=node_user_id)
            if model_capabilities and not model_capabilities.get(
                "supports_structured_output", False
            ):
                raise ValueError(
                    f'Model "{node_model_id}" does not support structured output for node "{node.title}"'
                )

        node_prompt = node_config.system_prompt
        doc_manifest = self._node_document_manifest(node_config)
        if doc_manifest:
            node_prompt = f"{node_prompt}\n\n{doc_manifest}" if node_prompt else doc_manifest

        factory_kwargs = {
            "agent_type": node_config.agent_type,
            "endpoint": self.agent.endpoint,
            "llm_name": node_llm_name,
            "model_id": node_model_id,
            "model_user_id": getattr(self.agent, "model_user_id", None),
            "api_key": node_api_key,
            "tool_ids": node_config.tools,
            "prompt": node_prompt,
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
        # Attribute this node's tool calls to the run's message and, crucially,
        # namespace their durability journal keys by it: node executors are built
        # without a message_id, so providers that reuse deterministic call ids
        # ("functions.create_artifact:0") would otherwise collide across runs on
        # the tool_call_attempts primary key and drop the later journal rows.
        node_executor = getattr(node_agent, "tool_executor", None)
        if node_executor is not None:
            node_executor.message_id = getattr(
                getattr(self.agent, "tool_executor", None), "message_id", None
            )
        # Run-scope the node agent's tools so artifact_generator / code_executor
        # address artifacts by this workflow run: a short ref (A1) created by one
        # node resolves for edit_artifact in a later node within the same run. Only
        # when a workflow_runs row backs the run -- otherwise an artifact parented
        # to this run id would be an orphan (403 on get/download); left unset, the
        # run-scoped tools persist under a conversation parent or cleanly error.
        if self.run_persisted and getattr(node_agent, "tool_executor", None) is not None:
            node_agent.tool_executor.workflow_run_id = self.workflow_run_id

        # Decide native-eligibility from the SAME supported-types list the provider
        # handler filters on at send time, so a mime is never sent native-but-empty
        # and then silently dropped. Read post-construction: BaseAgent consumes
        # ``self.attachments`` at gen time, so assigning here takes effect.
        node_attachments = self._materialize_node_attachments(
            node_config, node.title, self._agent_supported_attachment_types(node_agent)
        )
        if node_attachments:
            node_agent.attachments = node_attachments

        full_response_parts: List[str] = []
        structured_response_parts: List[str] = []
        has_structured_response = False
        first_chunk = True
        for event in node_agent.gen(formatted_prompt):
            # A tool that pauses for approval makes the LLM handler yield
            # ``tool_calls_pending`` and end. An ephemeral node agent has no resume path,
            # so silently continuing would leave the node with empty output (or a confusing
            # "Structured output was expected" when it has a json_schema). Fail visibly.
            if event.get("type") == "tool_calls_pending":
                raise ValueError(
                    f'Node "{node.title}" uses a tool that requires approval, which is not '
                    "supported inside a workflow. Disable require_approval for tools used in "
                    "workflow nodes."
                )
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

        self._last_node_tool_calls = self._summarize_tool_calls(node_agent)
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

    def _execute_code_node(
        self, node: WorkflowNode
    ) -> Generator[Dict[str, str], None, None]:
        """Run code in the run-scoped sandbox, persist produced files, and write an artifact reference."""
        from application.sandbox.artifacts_capture import capture_artifacts, snapshot_signatures
        from application.sandbox.sandbox_creator import SandboxCreator

        config = CodeNodeConfig(**node.config.get("config", node.config))
        code = config.code or ""
        if not code.strip():
            raise ValueError(f'Code node "{node.title}" has no code to execute.')
        # Code nodes are NEVER Jinja-rendered: state is untrusted (document-derived)
        # so interpolating it into the program would be code injection. Prior state is
        # passed as DATA via ``state.json`` (read below), never templated into code.

        user_id = self._resolve_user_id()
        if not user_id:
            raise ValueError(f'Code node "{node.title}" requires an authenticated user.')

        node_json_schema = self._normalize_node_json_schema(config.json_schema, node.title)
        session_id = self._session_id()
        timeout = self._resolve_code_timeout(config.timeout)

        manager = SandboxCreator.get_manager()
        # The session is keyed by the run id and shared by every code node and every
        # agent-node tool in this run, so it is NOT closed here: closing per node
        # would cold-drop later nodes' interpreter/filesystem state. The run session
        # is torn down once in ``execute``'s finally when the whole run ends.
        manager.open(session_id)
        loaded = self._materialize_code_inputs(manager, session_id, config.inputs, user_id)
        # Stage prior state as DATA the node code reads with
        # ``json.load(open("state.json"))`` -- e.g. ``state["decision"]``. The
        # file lands at the workspace root, which is the kernel cwd, so a
        # relative open resolves it. State is never templated into the program.
        state_json = json.dumps(self._json_safe_state(), default=str).encode("utf-8")
        manager.put_file(session_id, "state.json", state_json)
        pre_signatures = snapshot_signatures(manager, session_id)
        result = manager.exec(session_id, code, timeout=timeout)
        # Code nodes execute the sandbox directly (no tool_executor); record the
        # run as a synthetic tool call so the step log shows it like agent nodes.
        self._last_node_tool_calls = [
            {
                "tool_name": "code_executor",
                "action_name": "run_code",
                "status": "completed" if result.ok else "error",
            }
        ]
        if result.runtime_invalidated:
            # A hard timeout destroyed the workspace runtime, so there is
            # nothing reachable to capture and the timeout below stays primary.
            artifacts = []
        elif self.run_persisted:
            artifacts = capture_artifacts(
                manager,
                session_id,
                pre_signatures,
                user_id=user_id,
                workflow_run_id=self.workflow_run_id,
                produced_by={"node_id": node.id, "node_type": NodeType.CODE.value},
            )
        else:
            # No workflow_runs row backs this run (unsaved/embedded draft): an
            # artifact parented to this run id would be an unreachable orphan
            # (403 on get/download). Skip persistence; the sandbox still ran and
            # ``_build_code_output`` handles the empty-artifacts case.
            artifacts = []

        if not result.ok:
            error = (
                f"{result.error_name}: {result.error_value}"
                if result.error_name
                else (result.error_value or "execution error")
            )
            raise ValueError(f'Code node "{node.title}" failed: {error}')

        # The primary produced file becomes the node's pass-by-reference output;
        # it is JSON primitives only ({artifact_id, version, mime_type, filename})
        # so it survives the workflow_runs state-snapshot serialization. Bytes
        # never enter state. A structured decision (optional json_schema) is
        # parsed from stdout and validated through the existing jsonschema path.
        output_value: Any = self._build_code_output(node, result, artifacts, loaded, node_json_schema)

        default_output_key = f"node_{node.id}_output"
        self.state[default_output_key] = output_value
        if config.output_variable:
            self.state[config.output_variable] = output_value
        yield from ()

    def _build_code_output(
        self,
        node: WorkflowNode,
        result: Any,
        artifacts: List[Dict[str, Any]],
        inputs_loaded: List[str],
        node_json_schema: Optional[Dict[str, Any]],
    ) -> Any:
        """Shape a code node's pass-by-reference output (artifact ref and/or validated decision)."""
        if node_json_schema is not None:
            parsed_success, decision = self._parse_structured_output(result.stdout or "")
            if not parsed_success:
                raise ValueError(
                    f'Code node "{node.title}" must print JSON matching its schema, '
                    "but stdout was not valid JSON"
                )
            self._validate_structured_output(node_json_schema, decision)
            if artifacts:
                # Carry the produced artifact reference alongside the decision so
                # downstream nodes can branch on both.
                if isinstance(decision, dict) and "artifacts" not in decision:
                    decision = {**decision, "artifacts": artifacts}
            return decision
        if artifacts:
            return artifacts[0]
        return {"artifacts": [], "status": "ok"}

    def _materialize_code_inputs(
        self, manager: Any, session_id: str, inputs: List[str], user_id: str
    ) -> List[str]:
        """Stage referenced input artifacts (run-scoped, never cross-tenant) into the workspace."""
        from application.agents.tools.artifact_ref import resolve_artifact_id
        from application.core.settings import settings
        from application.sandbox.artifacts_capture import unique_input_path
        from application.storage.db.repositories.artifacts import ArtifactsRepository
        from application.storage.db.session import db_readonly
        from application.storage.storage_creator import StorageCreator
        from application.utils import safe_filename

        loaded: List[str] = []
        raw_ids = self._resolve_input_artifact_ids(inputs)
        if not raw_ids:
            return loaded
        max_bytes = int(getattr(settings, "SANDBOX_MAX_INPUT_BYTES", 0) or 0)
        storage = StorageCreator.get_storage()
        # Two inputs whose current versions share a filename would clobber each other at the
        # same ``inputs/{name}`` path; track used paths and disambiguate deterministically.
        used_paths: set = set()
        for raw in raw_ids:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                # A short ref (A1/A2/...) resolves to an id within this run only;
                # the resolved id is re-checked through the run-scoped gate so a ref
                # can never reach another tenant.
                artifact_id = resolve_artifact_id(repo, raw, workflow_run_id=self.workflow_run_id)
                artifact = (
                    repo.get_artifact_in_parent(artifact_id, workflow_run_id=self.workflow_run_id)
                    if artifact_id is not None
                    else None
                )
                if artifact is None:
                    raise ValueError(f"input artifact {raw} not found in this run.")
                version = repo.get_version(artifact_id, artifact["current_version"])
            if not version or not version.get("storage_path"):
                raise ValueError(f"input artifact {artifact_id} has no stored content.")
            declared_size = version.get("size")
            if max_bytes and isinstance(declared_size, (int, float)) and declared_size > max_bytes:
                raise ValueError(
                    f"input artifact {artifact_id} exceeds the {max_bytes}-byte sandbox input limit."
                )
            filename = safe_filename(version.get("filename") or artifact_id)
            file_obj = storage.get_file(version["storage_path"])
            try:
                data = file_obj.read(max_bytes + 1) if max_bytes else file_obj.read()
            finally:
                close = getattr(file_obj, "close", None)
                if callable(close):
                    close()
            if max_bytes and len(data) > max_bytes:
                raise ValueError(
                    f"input artifact {artifact_id} exceeds the {max_bytes}-byte sandbox input limit."
                )
            rel_path = unique_input_path(f"inputs/{filename}", used_paths)
            manager.put_file(session_id, rel_path, data)
            loaded.append(rel_path)
        return loaded

    def _node_document_manifest(self, node_config: AgentNodeConfig) -> str:
        """One-line-per-document manifest of the node's selected input documents.

        Appended to the node's system prompt so the model knows the concrete
        refs (``A1``) and filenames it can pass to document/code tools —
        without it, models guess placeholder names ("attached_file") or paste
        file contents inline. Scoped to THIS node's ``input_documents``
        selection, so it never widens per-node document access. Best-effort:
        a resolution failure drops the manifest, never the node.
        """
        from application.agents.tools.artifact_ref import make_ref, resolve_artifact_id
        from application.storage.db.repositories.artifacts import ArtifactsRepository
        from application.storage.db.session import db_readonly

        try:
            raw_ids = self._resolve_input_artifact_ids(node_config.input_documents)
            if not raw_ids:
                return ""
            lines: List[str] = []
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                for raw in raw_ids:
                    artifact_id = resolve_artifact_id(repo, raw, workflow_run_id=self.workflow_run_id)
                    artifact = (
                        repo.get_artifact_in_parent(artifact_id, workflow_run_id=self.workflow_run_id)
                        if artifact_id is not None
                        else None
                    )
                    if artifact is None:
                        continue
                    version = repo.get_version(artifact_id, artifact["current_version"]) or {}
                    ref_seq = (artifact.get("metadata") or {}).get("ref_seq")
                    # Legacy artifacts predate ref_seq; the full id works in every tool.
                    handle = make_ref(int(ref_seq)) if ref_seq else str(artifact_id)
                    filename = version.get("filename") or artifact.get("title") or str(artifact_id)
                    mime = version.get("mime_type") or "application/octet-stream"
                    lines.append(f"- {handle}: {filename} ({mime})")
        except Exception:
            logger.exception("Node document manifest failed; continuing without it")
            return ""
        if not lines:
            return ""
        return (
            "## Input documents for this node\n"
            "These files are staged for this node. Pass a ref (e.g. A1) or the "
            "filename to a document or code tool to read the file:\n" + "\n".join(lines)
        )

    def _materialize_node_attachments(
        self,
        node_config: AgentNodeConfig,
        node_title: str,
        supported_types: List[str],
    ) -> List[Dict[str, Any]]:
        """Resolve a node's selected documents to native/extracted attachment dicts for its LLM."""
        from application.agents.tools.artifact_ref import resolve_artifact_id
        from application.core.settings import settings
        from application.storage.db.repositories.artifacts import ArtifactsRepository
        from application.storage.db.session import db_readonly

        raw_ids = self._resolve_input_artifact_ids(node_config.input_documents)
        if not raw_ids:
            return []

        supported = set(supported_types)
        supports_images = any(t.startswith("image/") for t in supported)
        max_files = int(getattr(settings, "WORKFLOW_NODE_NATIVE_MAX_FILES", 5))
        extract_max = int(getattr(settings, "WORKFLOW_NODE_EXTRACT_MAX_FILES", 5))
        max_bytes = int(getattr(settings, "SANDBOX_MAX_INPUT_BYTES", 25 * 1024 * 1024))

        # One read-only connection for the whole batch; the resolved-version
        # rows are collected, then storage reads happen outside the DB context.
        resolved: List[tuple] = []
        with db_readonly() as conn:
            repo = ArtifactsRepository(conn)
            for raw in raw_ids:
                # A short ref (A1/...) resolves to an id within this run only; the
                # resolved id is re-checked through the run-scoped gate so a forged
                # or cross-run ref can never reach another tenant's bytes.
                artifact_id = resolve_artifact_id(repo, raw, workflow_run_id=self.workflow_run_id)
                artifact = (
                    repo.get_artifact_in_parent(artifact_id, workflow_run_id=self.workflow_run_id)
                    if artifact_id is not None
                    else None
                )
                if artifact is None:
                    raise ValueError(
                        f'Document "{raw}" for node "{node_title}" was not found in this run.'
                    )
                version = repo.get_version(artifact_id, artifact["current_version"])
                if not version or not version.get("storage_path"):
                    raise ValueError(f"input document {artifact_id} has no stored content.")
                resolved.append((str(artifact_id), artifact, version))

        attachments: List[Dict[str, Any]] = []
        native_count = 0
        extract_count = 0
        dropped_for_cap = 0
        for artifact_id, artifact, version in resolved:
            storage_path = version["storage_path"]
            mime_type = version.get("mime_type") or "application/octet-stream"
            filename = version.get("filename") or artifact.get("title") or artifact_id
            size = version.get("size")
            if isinstance(size, int) and size > max_bytes:
                logger.warning(
                    "Workflow node %s: document %s (%d bytes) exceeds the %d-byte cap; skipping",
                    node_title, artifact_id, size, max_bytes,
                )
                continue

            native_ok = self._is_native_mime(mime_type, supported, supports_images)
            policy = node_config.file_passing
            if policy == "native" and not native_ok:
                raise ValueError(
                    f'Model "{node_config.model_id or self.agent.model_id}" cannot read '
                    f'"{mime_type}" natively for node "{node_title}".'
                )
            go_native = policy == "native" or (policy == "auto" and native_ok)
            if go_native and native_count >= max_files:
                logger.warning(
                    "Workflow node %s: native file cap (%d) reached; extracting %s instead",
                    node_title, max_files, filename,
                )
                go_native = False

            if go_native:
                # No bytes copied: the provider reads them from storage via ``path``.
                attachments.append({"id": artifact_id, "mime_type": mime_type, "path": storage_path})
                native_count += 1
            else:
                # Inline-text mimes are read directly (cheap); other mimes route
                # through the parsing worker -- a blocking, ~120s per-document call.
                # Cap how many documents a single node sends down that path so a
                # node referencing many non-native documents (e.g. the ``*`` token)
                # can't serialize dozens of parses. Inline text is not capped.
                needs_parse = not self._is_inline_text_mime(mime_type)
                if needs_parse:
                    # Count (and gate on) the parse ATTEMPT, not the success: a
                    # timed-out/failed parse is the ~120s worst case we must bound,
                    # so it has to consume cap budget too. Otherwise a degraded
                    # parsing backend (every parse fails) never advances the count
                    # and the node keeps issuing blocking parses without limit.
                    if extract_count >= extract_max:
                        dropped_for_cap += 1
                        continue
                    extract_count += 1
                content = self._extract_attachment_text(
                    artifact_id, storage_path, mime_type, filename, max_bytes
                )
                if content is None:
                    logger.warning(
                        "Workflow node %s: could not extract text from %s; skipping",
                        node_title, filename,
                    )
                    continue
                # A non-native mime routes this through ``_append_unsupported_attachments``,
                # which inlines ``content`` as text in the system prompt.
                attachments.append(
                    {"id": artifact_id, "mime_type": "text/plain", "content": content}
                )
        if dropped_for_cap:
            logger.warning(
                "Workflow node %s: blocking-extract cap (%d) reached; %d document(s) omitted",
                node_title, extract_max, dropped_for_cap,
            )
            attachments.append(
                self._extract_truncation_note(node_title, extract_max, dropped_for_cap)
            )
        return attachments

    @staticmethod
    def _extract_truncation_note(node_title: str, cap: int, dropped: int) -> Dict[str, Any]:
        """Build a non-fatal text attachment flagging documents skipped past the per-node extract cap."""
        content = (
            f'[Notice] Only the first {cap} document(s) for node "{node_title}" were extracted '
            f"to text; {dropped} additional document(s) were omitted to bound execution time. "
            "Reference fewer documents, or use a model that reads them natively."
        )
        return {"id": _EXTRACT_TRUNCATION_ID, "mime_type": "text/plain", "content": content}

    @staticmethod
    def _agent_supported_attachment_types(node_agent: "BaseAgent") -> List[str]:
        """Return the provider's authoritative supported attachment mime types (handler's source)."""
        llm = getattr(node_agent, "llm", None)
        getter = getattr(llm, "get_supported_attachment_types", None)
        if not callable(getter):
            return []
        types = getter()
        return list(types) if isinstance(types, (list, tuple, set)) else []

    @staticmethod
    def _is_native_mime(mime_type: str, supported_types: set, supports_images: bool) -> bool:
        """A mime is native if the model accepts it, or it is a PDF a vision model renders to images."""
        if mime_type in supported_types:
            return True
        return mime_type == "application/pdf" and supports_images

    def _extract_attachment_text(
        self, artifact_id: str, storage_path: str, mime_type: str, filename: str, max_bytes: int
    ) -> Optional[str]:
        """Get an attachment's text: inline already-text formats, else parse via the parsing worker; None on failure."""
        from application.parser.document_reader import truncate_text_head_tail
        from application.storage.storage_creator import StorageCreator

        if self._is_inline_text_mime(mime_type):
            try:
                data = StorageCreator.get_storage().get_file(storage_path).read()
            except Exception:
                logger.exception("Workflow node: failed to read document bytes for extraction")
                return None
            # Defensive size gate: a NULL/missing version size skips the pre-read cap,
            # so re-check the actual bytes before inlining.
            if len(data) > max_bytes:
                logger.warning(
                    "Workflow node: document at %s (%d bytes) exceeds the %d-byte cap; skipping",
                    storage_path, len(data), max_bytes,
                )
                return None
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                return None
            # Bound the inlined text to a head+tail window so a large-but-under-cap
            # text file can't blow the context (the parse branch is already bounded).
            return truncate_text_head_tail(text)
        # Non-text mimes parse via the dedicated parsing queue (works on any backend,
        # no sandbox): the worker re-resolves the artifact run-scoped and reads its bytes.
        return self._parse_document_text(artifact_id)

    def _parse_document_text(self, artifact_id: str) -> Optional[str]:
        """Enqueue ``parse_document`` for this run and await the bounded markdown; None on failure."""
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        from application.api.user.tasks import parse_document
        from application.core.settings import settings

        user_id = self._resolve_user_id()
        if not user_id:
            return None
        options = {"output": "markdown", "include_tables": False, "persist": False}
        queue = getattr(settings, "DOCUMENT_PARSE_QUEUE", "parsing")
        timeout = float(getattr(settings, "DOCUMENT_PARSE_TIMEOUT", 120))
        try:
            async_result = parse_document.apply_async(
                args=[artifact_id, {"workflow_run_id": self.workflow_run_id}, user_id, options],
                queue=queue,
            )
            # A workflow can run inside a Celery worker (scheduled runs / webhooks).
            # In a prefork worker ``task_join_will_block()`` is process-wide, so the
            # default ``disable_sync_subtasks=True`` makes ``get()`` raise RuntimeError
            # ("Never call result.get() within a task!"). The dedicated parsing queue +
            # separate workers already avoid the real self-deadlock, so opt out
            # explicitly (mirrors application/agents/tools/read_document.py).
            result = async_result.get(timeout=timeout, disable_sync_subtasks=False)
        except (CeleryTimeoutError, TimeoutError):
            logger.warning("Workflow node: document parse timed out for %s", artifact_id)
            return None
        except Exception:
            logger.exception("Workflow node: document parse failed")
            return None
        if isinstance(result, dict) and result.get("status") == "ok":
            content = result.get("content")
            return content if isinstance(content, str) else None
        return None

    @staticmethod
    def _is_inline_text_mime(mime_type: str) -> bool:
        """Already-text formats are inlined directly (no Docling round-trip)."""
        if mime_type.startswith("text/"):
            return True
        return mime_type in ("application/json", "application/xml")

    def _resolve_input_artifact_ids(self, inputs: List[str]) -> List[str]:
        """Resolve node ``inputs`` (refs/ids, ``*`` token, or state vars holding a ref or a list of refs)."""
        resolved: List[str] = []
        for raw in inputs or []:
            # ``*`` / ``input_documents`` expands to every run input document.
            if isinstance(raw, str) and raw.strip() in ("*", "input_documents"):
                resolved.extend(self._input_document_ids())
                continue
            ref = self.state.get(raw) if isinstance(raw, str) else None
            if isinstance(ref, dict) and ref.get("artifact_id"):
                resolved.append(str(ref["artifact_id"]))
            elif isinstance(ref, list):
                # A state var holding a list of ref dicts (e.g. input_documents).
                for item in ref:
                    if isinstance(item, dict) and item.get("artifact_id"):
                        resolved.append(str(item["artifact_id"]))
            elif isinstance(raw, str) and raw.strip():
                resolved.append(raw.strip())
        # Dedup preserving order so ``["*", "A1"]`` / duplicate refs don't attach twice.
        return list(dict.fromkeys(resolved))

    def _input_document_ids(self) -> List[str]:
        """Return the artifact ids of every ref in ``state['input_documents']``."""
        docs = self.state.get("input_documents")
        if not isinstance(docs, list):
            return []
        return [str(d["artifact_id"]) for d in docs if isinstance(d, dict) and d.get("artifact_id")]

    def _session_id(self) -> str:
        """Sanitize the run id into the sandbox-gateway charset for the session key."""
        return _SESSION_ID_RE.sub("-", str(self.workflow_run_id)) or str(uuid.uuid4())

    def _json_safe_state(self) -> Dict[str, Any]:
        """Project ``self.state`` to a JSON-safe dict (the code node reads it from state.json).

        ``chat_history`` is excluded: it is the *caller's* full conversation, and a
        code node (authored by the workflow owner, who may differ from the runner
        in a shared agent) has no legitimate need for it. Since sandbox egress is
        open by design, staging it would let owner-authored code exfiltrate the
        runner's conversation. Node outputs and ``query`` are still exposed.
        """
        projection: Dict[str, Any] = {}
        for key, value in self.state.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.strip()
            if not normalized_key or normalized_key in _CODE_STATE_EXCLUDED_KEYS:
                continue
            projection[normalized_key] = value
        return projection

    def _resolve_user_id(self) -> Optional[str]:
        """Resolve the run's owner for artifact ownership/quota accounting."""
        user_id = getattr(self.agent, "user", None)
        if user_id:
            return user_id
        token = getattr(self.agent, "decoded_token", None)
        if isinstance(token, dict):
            return token.get("sub")
        return None

    def _resolve_code_timeout(self, requested: Optional[int]) -> float:
        """Return the stricter of the node's requested timeout and the sandbox cap."""
        from application.core.settings import settings

        cap = float(getattr(settings, "SANDBOX_EXEC_TIMEOUT", 60))
        if requested is None:
            return cap
        try:
            parsed = int(requested)
        except (TypeError, ValueError):
            return cap
        return float(min(parsed, cap)) if parsed > 0 else cap

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
            # A prior streaming node's text otherwise runs straight into the
            # end-node output ("...enterprise growth.Sales analysis complete");
            # insert the same paragraph break streamed nodes use between each
            # other so the segments stay readable.
            if getattr(self, "_has_streamed", False):
                yield {"answer": "\n\n"}
            yield {"answer": formatted_output}
            self._has_streamed = True

    def _parse_structured_output(self, raw_response: str) -> tuple[bool, Optional[Any]]:
        normalized_response = raw_response.strip()
        if not normalized_response:
            return False, None

        try:
            return True, json.loads(normalized_response)
        except json.JSONDecodeError:
            pass

        # Some models wrap structured output in a ```json ... ``` fence or add
        # prose around it; recover the JSON object/array before giving up so a
        # well-formed-but-fenced response still validates.
        candidate = self._strip_json_fence(normalized_response)
        if candidate is not None:
            try:
                return True, json.loads(candidate)
            except json.JSONDecodeError:
                pass

        logger.warning(
            "Workflow agent returned structured output that was not valid JSON"
        )
        return False, None

    @staticmethod
    def _strip_json_fence(text: str) -> Optional[str]:
        """Extract the JSON payload from a fenced/prose-wrapped response, or None."""
        fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fence:
            return fence.group(1).strip()
        # Fall back to the outermost {...} or [...] span, choosing whichever
        # bracket opens first. Fixing the order to "{" before "[" would slice a
        # top-level array (``[{...},{...}]``) from its first "{" to its last "}",
        # dropping the array framing (invalid JSON) or extracting an inner object
        # that parses as silently-wrong structured data.
        best: Optional[str] = None
        best_start = -1
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = text.find(open_ch)
            end = text.rfind(close_ch)
            if start != -1 and end > start and (best_start == -1 or start < best_start):
                best_start = start
                best = text[start : end + 1]
        return best

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
            artifacts_data=self._collect_artifact_refs(),
            artifact_parent={"workflow_run_id": self.workflow_run_id},
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

    def _collect_artifact_refs(self) -> Dict[str, Any]:
        """Collect state variables that hold artifact references, keyed by their state name."""
        refs: Dict[str, Any] = {}
        for key, value in self.state.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, dict) and value.get("artifact_id"):
                refs[key] = value
        return refs

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
                duration_ms=log.get("duration_ms"),
                error=log.get("error"),
                state_delta=log.get("state_delta", {}),
                tool_calls=log.get("tool_calls", []),
            )
            for log in self.execution_log
        ]
