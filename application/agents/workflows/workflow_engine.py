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
        self.state: WorkflowState = {}
        self.execution_log: List[Dict[str, Any]] = []
        self._condition_result: Optional[str] = None
        self._template_engine = TemplateEngine()
        self._namespace_manager = NamespaceManager()

    def execute(
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
        # Run-scope the node agent's tools so artifact_generator / code_executor
        # address artifacts by this workflow run: a short ref (A1) created by one
        # node resolves for edit_artifact in a later node within the same run.
        if getattr(node_agent, "tool_executor", None) is not None:
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
        manager.open(session_id)
        try:
            loaded = self._materialize_code_inputs(manager, session_id, config.inputs, user_id)
            # Stage prior state as DATA the node code reads with
            # ``json.load(open("state.json"))`` -- e.g. ``state["decision"]``. The
            # file lands at the workspace root, which is the kernel cwd, so a
            # relative open resolves it. State is never templated into the program.
            state_json = json.dumps(self._json_safe_state(), default=str).encode("utf-8")
            manager.put_file(session_id, "state.json", state_json)
            pre_signatures = snapshot_signatures(manager, session_id)
            result = manager.exec(session_id, code, timeout=timeout)
            artifacts = capture_artifacts(
                manager,
                session_id,
                pre_signatures,
                user_id=user_id,
                workflow_run_id=self.workflow_run_id,
                produced_by={"node_id": node.id, "node_type": NodeType.CODE.value},
            )
        finally:
            try:
                manager.close(session_id)
            except Exception:
                logger.exception("Code node failed to close sandbox session")

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
        from application.storage.db.repositories.artifacts import ArtifactsRepository
        from application.storage.db.session import db_readonly
        from application.storage.storage_creator import StorageCreator
        from application.utils import safe_filename

        loaded: List[str] = []
        raw_ids = self._resolve_input_artifact_ids(inputs)
        if not raw_ids:
            return loaded
        storage = StorageCreator.get_storage()
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
            filename = safe_filename(version.get("filename") or artifact_id)
            data = storage.get_file(version["storage_path"]).read()
            manager.put_file(session_id, f"inputs/{filename}", data)
            loaded.append(f"inputs/{filename}")
        return loaded

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
        return attachments

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
            result = async_result.get(timeout=timeout)
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
        """Project ``self.state`` to a JSON-safe dict (the code node reads it from state.json)."""
        projection: Dict[str, Any] = {}
        for key, value in self.state.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.strip()
            if not normalized_key:
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
            yield {"answer": formatted_output}

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
        # Fall back to the outermost {...} or [...] span.
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = text.find(open_ch)
            end = text.rfind(close_ch)
            if start != -1 and end > start:
                return text[start : end + 1]
        return None

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
                error=log.get("error"),
                state_snapshot=log.get("state_snapshot", {}),
            )
            for log in self.execution_log
        ]
