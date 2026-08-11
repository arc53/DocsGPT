import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

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
from application.core.settings import settings
from application.logging import LogContext, log_activity
from application.sandbox.artifacts_capture import QuotaExceeded
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

# Per-run cap on attachments staged as run-scoped artifacts; the remainder is
# dropped (the per-user artifact quota is only a best-effort soft cap).
_MAX_INPUT_DOCUMENTS = 25


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
        self._run_persisted = False
        # Set to a message when the input-document bridge fails fatally (quota), so
        # the run is finalized FAILED instead of running with missing documents.
        self._bridge_error: Optional[str] = None

    @log_activity()
    def gen(self, query: str, log_context: LogContext = None) -> Generator[Dict[str, str], None, None]:
        yield from self._gen_inner(query, log_context)

    def _gen_inner(self, query: str, log_context: LogContext) -> Generator[Dict[str, str], None, None]:
        graph = self._load_workflow_graph()
        if not graph:
            yield {"type": "error", "error": "Failed to load workflow configuration."}
            return
        self._engine = WorkflowEngine(graph, self)

        # Two distinct identities: the workflow *owner* (A) owns the workflow
        # definition and is used to resolve the workflow row; the *runner* (B,
        # the caller) owns the run and its artifacts. They are the same user
        # except for a shared agent, where B != A. Owning run artifacts by the
        # runner means quota is charged to the uploader and the caller can read
        # the outputs of the run they triggered (authz is run.user_id == caller).
        workflow_owner_id = self._resolve_owner_id()
        run_user_id = self._resolve_run_user_id(workflow_owner_id)
        pg_workflow_id = self._precreate_workflow_run(workflow_owner_id, run_user_id, query)
        self._run_persisted = pg_workflow_id is not None

        try:
            input_documents, dropped = self._bridge_attachments(run_user_id, persisted=self._run_persisted)
        except QuotaExceeded as exc:
            # The run's input documents exceed the uploader's artifact quota. Surface
            # a clean error and finalize the pre-created RUNNING row as FAILED rather
            # than executing nodes with silently-missing documents.
            self._bridge_error = str(exc)
            yield {
                "type": "error",
                "user_facing": True,
                "error": (
                    "This run's input documents exceed your artifact storage quota. "
                    "Delete some artifacts and try again."
                ),
            }
            self._finalize_workflow_run(workflow_owner_id, run_user_id, pg_workflow_id, query)
            return

        # Non-fatal: some attachments were dropped (oversize / unreadable). Emit a
        # ``notice`` -- NOT an ``error`` -- so the client surfaces which were dropped
        # without marking the turn failed or ending the stream (an ``error`` event is
        # terminal client-side and disables reconnect). The run then still executes
        # with the documents that did bridge.
        if dropped:
            yield {"type": "notice", "notice": " ".join(dropped)}

        self._engine.run_persisted = self._run_persisted
        interrupted = True
        try:
            yield from self._engine.execute({"input_documents": input_documents}, query)
            interrupted = False
        finally:
            self._finalize_workflow_run(
                workflow_owner_id,
                run_user_id,
                pg_workflow_id,
                query,
                interrupted=interrupted,
            )

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
                logger.error(f"Workflow owner not available for workflow load: {self.workflow_id}")
                return None

            with db_readonly() as conn:
                wf_repo = WorkflowsRepository(conn)
                if looks_like_uuid(self.workflow_id):
                    workflow_row = wf_repo.get(self.workflow_id, owner_id)
                else:
                    workflow_row = wf_repo.get_by_legacy_id(self.workflow_id, owner_id)
                if workflow_row is None:
                    logger.error(f"Workflow {self.workflow_id} not found or inaccessible for user {owner_id}")
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
                    pg_workflow_id,
                    graph_version,
                )
                edge_rows = WorkflowEdgesRepository(conn).find_by_version(
                    pg_workflow_id,
                    graph_version,
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

    def _resolve_owner_id(self) -> Optional[str]:
        """Resolve the workflow *owner* (used to resolve the owned workflow row)."""
        owner_id = self.workflow_owner
        if not owner_id and isinstance(self.decoded_token, dict):
            owner_id = self.decoded_token.get("sub")
        return owner_id

    def _resolve_run_user_id(self, workflow_owner_id: Optional[str]) -> Optional[str]:
        """Resolve the *runner* (caller) who owns the run and its artifacts.

        Equals the owner for a user running their own workflow (and for external
        API-key calls, where the key owner is the caller); for a shared agent it
        is the calling user, so their uploads/outputs are owned by and readable
        to them rather than silently accruing under the agent owner's account.
        """
        return getattr(self, "initial_user_id", None) or getattr(self, "user", None) or workflow_owner_id

    def _resolve_owned_workflow_pg_id(self, conn: Any, owner_id: Optional[str]) -> Optional[str]:
        """Return the owned workflow's PG id, or None for an unowned/draft id."""
        if not self.workflow_id or not owner_id:
            return None
        wf_repo = WorkflowsRepository(conn)
        if looks_like_uuid(self.workflow_id):
            workflow_row = wf_repo.get(self.workflow_id, owner_id)
        else:
            workflow_row = wf_repo.get_by_legacy_id(self.workflow_id, owner_id)
        return str(workflow_row["id"]) if workflow_row is not None else None

    def _precreate_workflow_run(
        self,
        workflow_owner_id: Optional[str],
        run_user_id: Optional[str],
        query: str,
    ) -> Optional[str]:
        """Insert the run row up front so run-scoped artifacts are authz-reachable mid-run.

        The workflow row is resolved against its *owner*; the run is owned by the
        *runner* so artifact access (``run.user_id == caller``) tracks the caller.
        """
        if not self._engine or not self.workflow_id or not workflow_owner_id or not run_user_id:
            return None
        try:
            with db_session() as conn:
                pg_workflow_id = self._resolve_owned_workflow_pg_id(conn, workflow_owner_id)
                if pg_workflow_id is None:
                    return None
                WorkflowRunsRepository(conn).create(
                    pg_workflow_id,
                    run_user_id,
                    ExecutionStatus.RUNNING.value,
                    run_id=self._engine.workflow_run_id,
                    inputs={"query": query},
                    started_at=datetime.now(timezone.utc),
                )
            return pg_workflow_id
        except Exception as e:
            logger.error(f"Failed to pre-create workflow run: {e}")
            return None

    def _bridge_attachments(
        self, run_user_id: Optional[str], *, persisted: bool
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Stage uploaded attachments as run-scoped artifacts the nodes can read.

        Bytes are read server-side from each attachment's ``upload_path`` (bounded
        by ``ARTIFACT_MAX_BYTES``, handle always closed) and re-persisted through
        ``persist_new_artifact`` (size/sha256/storage key all derived server-side);
        only the resulting references enter the run state. Artifacts are owned by
        the *runner* (the uploader), not the workflow owner.

        Returns the bridged references and a list of user-facing notices for
        attachments that were dropped (oversize / unreadable / unstorable).
        ``QuotaExceeded`` is NOT swallowed: it propagates to the caller so the run
        fails cleanly instead of running with silently-missing documents.
        """
        if not self._engine or not self.attachments or not run_user_id:
            return [], []
        # Without a persisted run row the artifacts would be orphaned (no authz
        # parent), so skip the bridge for unowned/draft ids.
        if not persisted:
            return [], []
        from application.sandbox.artifacts_capture import persist_new_artifact
        from application.storage.storage_creator import StorageCreator

        storage = StorageCreator.get_storage()
        max_bytes = int(getattr(settings, "ARTIFACT_MAX_BYTES", 0) or 0)
        dropped: List[str] = []
        if len(self.attachments) > _MAX_INPUT_DOCUMENTS:
            over = len(self.attachments) - _MAX_INPUT_DOCUMENTS
            logger.warning(
                "Workflow run input documents exceed cap (%d); dropping %d attachment(s)",
                _MAX_INPUT_DOCUMENTS,
                over,
            )
            dropped.append(
                f"Only the first {_MAX_INPUT_DOCUMENTS} input document(s) were used; "
                f"{over} additional attachment(s) were dropped."
            )
        refs: List[Dict[str, Any]] = []
        for attachment in self.attachments[:_MAX_INPUT_DOCUMENTS]:
            upload_path = attachment.get("upload_path") or attachment.get("path")
            if not upload_path:
                continue
            filename = attachment.get("filename") or "attachment"
            mime_type = attachment.get("mime_type") or "application/octet-stream"
            # Reject oversize attachments via the authoritative ``size`` column
            # BEFORE buffering the bytes into worker memory (a memory-DoS guard);
            # the bounded read below backstops a missing/lying ``size``.
            declared_size = attachment.get("size")
            if max_bytes and isinstance(declared_size, (int, float)) and declared_size > max_bytes:
                dropped.append(f'Document "{filename}" exceeds the artifact size limit and was skipped.')
                continue
            data = self._read_attachment_bytes(storage, upload_path, max_bytes)
            if data is None:
                dropped.append(f'Document "{filename}" could not be read and was skipped.')
                continue
            if max_bytes and len(data) > max_bytes:
                dropped.append(f'Document "{filename}" exceeds the artifact size limit and was skipped.')
                continue
            # QuotaExceeded propagates (fatal); persist_new_artifact returns None on
            # any other error, which we report as a per-attachment drop.
            ref = persist_new_artifact(
                user_id=run_user_id,
                kind="file",
                data=data,
                filename=filename,
                mime_type=mime_type,
                title=filename,
                workflow_run_id=self._engine.workflow_run_id,
            )
            if ref is None:
                dropped.append(f'Document "{filename}" could not be stored and was skipped.')
                continue
            refs.append(
                {
                    "artifact_id": ref["artifact_id"],
                    "ref": ref.get("ref"),
                    "filename": ref["filename"],
                    "mime_type": ref["mime_type"],
                }
            )
        return refs, dropped

    @staticmethod
    def _read_attachment_bytes(storage: Any, upload_path: str, max_bytes: int) -> Optional[bytes]:
        """Read an attachment with a bounded read and a guaranteed handle close; None on failure."""
        try:
            file_obj = storage.get_file(upload_path)
        except Exception as exc:
            logger.error("Failed to open attachment for workflow run: %s", type(exc).__name__)
            return None
        try:
            return file_obj.read(max_bytes + 1) if max_bytes else file_obj.read()
        except Exception as exc:
            logger.error("Failed to read attachment for workflow run: %s", type(exc).__name__)
            return None
        finally:
            close = getattr(file_obj, "close", None)
            if callable(close):
                close()

    def _finalize_workflow_run(
        self,
        workflow_owner_id: Optional[str],
        run_user_id: Optional[str],
        pg_workflow_id: Optional[str],
        query: str,
        interrupted: bool = False,
    ) -> None:
        """Write the run's terminal status/result; upsert the row if pre-creation was skipped.

        The run is owned by the *runner* (so it stays readable to the caller and
        matches the pre-created row); the workflow row is resolved by its *owner*.
        When ``interrupted`` is set (client disconnect / mid-run error), the run is
        recorded as FAILED regardless of the per-node log, so a partial run is never
        left looking complete.
        """
        if not self._engine:
            return
        try:
            status = ExecutionStatus.FAILED if interrupted else self._determine_run_status()
            run = WorkflowRun(
                workflow_id=self.workflow_id or "unknown",
                user=run_user_id,
                status=status,
                inputs={"query": query},
                outputs=self._serialize_state(self._engine.state),
                steps=self._engine.get_execution_summary(),
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            steps_json = [step.model_dump(mode="json") for step in run.steps]

            if not self.workflow_id or not workflow_owner_id or not run_user_id:
                return
            with db_session() as conn:
                if pg_workflow_id is None:
                    pg_workflow_id = self._resolve_owned_workflow_pg_id(conn, workflow_owner_id)
                    if pg_workflow_id is None:
                        return
                runs_repo = WorkflowRunsRepository(conn)
                updated = False
                if self._run_persisted:
                    updated = runs_repo.finalize(
                        self._engine.workflow_run_id,
                        run_user_id,
                        run.status.value,
                        result=run.outputs,
                        steps=steps_json,
                        ended_at=run.completed_at,
                    )
                    if not updated:
                        logger.warning(
                            "Workflow run %s finalize matched no row; "
                            "recovering via insert so terminal data is not lost",
                            self._engine.workflow_run_id,
                        )
                if not self._run_persisted or not updated:
                    runs_repo.create(
                        pg_workflow_id,
                        run_user_id,
                        run.status.value,
                        run_id=self._engine.workflow_run_id,
                        inputs=run.inputs,
                        result=run.outputs,
                        steps=steps_json,
                        started_at=run.created_at,
                        ended_at=run.completed_at,
                    )
        except Exception as e:
            logger.error(f"Failed to save workflow run: {e}")

    def _determine_run_status(self) -> ExecutionStatus:
        # A fatal input-document bridge failure (quota) means the engine never ran;
        # the run is FAILED even though there is no per-node failure log entry.
        if self._bridge_error is not None:
            return ExecutionStatus.FAILED
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
            return {str(dict_key): self._serialize_state_value(dict_value) for dict_key, dict_value in value.items()}
        if isinstance(value, list):
            return [self._serialize_state_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._serialize_state_value(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        return str(value)
