"""Repository for the ``workflow_runs`` table.

In Mongo, workflow_runs_collection only has ``insert_one`` — runs are
written once after workflow execution completes and never updated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import Connection, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from docsgpt.storage.db.base_repository import row_to_dict
from docsgpt.storage.db.models import workflow_runs_table


class WorkflowRunsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        workflow_id: str,
        user_id: str,
        status: str,
        *,
        run_id: str | None = None,
        inputs: dict | None = None,
        result: dict | None = None,
        steps: list | None = None,
        started_at=None,
        ended_at=None,
        legacy_mongo_id: str | None = None,
    ) -> dict:
        values: dict = {
            "workflow_id": workflow_id,
            "user_id": user_id,
            "status": status,
        }
        # An explicit id lets the engine bind run-scoped artifacts to this row
        # before the run is persisted, so artifact authz can resolve the parent.
        if run_id is not None:
            values["id"] = run_id
        if inputs is not None:
            values["inputs"] = inputs
        if result is not None:
            values["result"] = result
        if steps is not None:
            values["steps"] = steps
        if started_at is not None:
            values["started_at"] = started_at
        if ended_at is not None:
            values["ended_at"] = ended_at
        if legacy_mongo_id is not None:
            values["legacy_mongo_id"] = legacy_mongo_id

        stmt = pg_insert(workflow_runs_table).values(**values).returning(workflow_runs_table)
        res = self._conn.execute(stmt)
        return row_to_dict(res.fetchone())

    def finalize(
        self,
        run_id: str,
        user_id: str,
        status: str,
        *,
        result: dict | None = None,
        steps: list | None = None,
        ended_at: Optional[datetime] = None,
    ) -> bool:
        """Update a pre-created run row with its terminal status/result; owner-scoped."""
        values: dict = {"status": status}
        if result is not None:
            values["result"] = result
        if steps is not None:
            values["steps"] = steps
        if ended_at is not None:
            values["ended_at"] = ended_at
        stmt = (
            workflow_runs_table.update()
            .where(workflow_runs_table.c.id == run_id)
            .where(workflow_runs_table.c.user_id == user_id)
            .values(**values)
        )
        res = self._conn.execute(stmt)
        return res.rowcount > 0

    def set_progress(self, run_id: str, user_id: str, progress: dict) -> bool:
        """Record the step a running run is on; owner-scoped.

        Args:
            run_id: The run.
            user_id: The run's owner (the person who started it).
            progress: ``{done, total, current: {node_id, title, type, started_at}}``.

        Returns:
            True when a running run was updated. A finished run keeps its
            last progress.
        """
        stmt = (
            workflow_runs_table.update()
            .where(workflow_runs_table.c.id == run_id)
            .where(workflow_runs_table.c.user_id == user_id)
            .where(workflow_runs_table.c.status == "running")
            .values(progress=progress)
        )
        return self._conn.execute(stmt).rowcount > 0

    def mark_stale_running_failed(self, older_than: datetime) -> int:
        """Fail runs left in ``running`` (no ``ended_at``) since before ``older_than``.

        The run row is pre-created as ``running`` and finalized when its generator
        finishes; a client disconnect or a worker crash can strand it in ``running``
        forever, since nothing else finalizes it. This closes those rows out so they
        don't linger. Returns the number of rows updated.
        """
        stmt = (
            workflow_runs_table.update()
            .where(workflow_runs_table.c.status == "running")
            .where(workflow_runs_table.c.ended_at.is_(None))
            .where(workflow_runs_table.c.started_at < older_than)
            .values(
                status="failed",
                ended_at=func.now(),
                # failed_reason marks the reap so readers know ended_at is the
                # reap time, not when the run actually died (duration is bogus).
                result={
                    "error": "Run did not complete (timed out or the client disconnected).",
                    "failed_reason": "stale_reaper",
                },
            )
        )
        res = self._conn.execute(stmt)
        return res.rowcount

    def get(self, run_id: str) -> Optional[dict]:
        res = self._conn.execute(
            text("SELECT * FROM workflow_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        )
        row = res.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(self, legacy_mongo_id: str) -> Optional[dict]:
        """Fetch a workflow run by the original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        res = self._conn.execute(
            text("SELECT * FROM workflow_runs WHERE legacy_mongo_id = :legacy_id"),
            {"legacy_id": legacy_mongo_id},
        )
        row = res.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_workflow(self, workflow_id: str) -> list[dict]:
        res = self._conn.execute(
            text(
                "SELECT * FROM workflow_runs "
                "WHERE workflow_id = CAST(:wf_id AS uuid) "
                "ORDER BY started_at DESC"
            ),
            {"wf_id": workflow_id},
        )
        return [row_to_dict(r) for r in res.fetchall()]

    def list_for_user(
        self,
        user_id: str,
        *,
        agent_id: Optional[str] = None,
        agent_ids: Optional[Iterable[str]] = None,
        since: Optional[datetime] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """The runs a user started, newest first, without their state and steps.

        A run belongs to the agent that ran it, recorded as
        ``inputs.agent_id``; a run started from the builder preview has none.

        Args:
            user_id: The person who started the runs.
            agent_id: Only runs of this agent.
            agent_ids: An allowlist of agents; runs of other agents, and runs
                without an agent, are left out. ``None`` means no allowlist.
            since: Only runs started at or after this moment.
            status: Only runs in this status.
            limit: Most rows to return.

        Returns:
            Run rows with ``step_count`` in place of ``steps`` and no ``result``.
        """
        clauses = ["user_id = :user_id"]
        params: dict = {"user_id": user_id, "limit": int(limit)}
        if agent_ids is not None:
            allowed = sorted({str(a).lower() for a in agent_ids})
            if not allowed:
                return []
            clauses.append("lower(inputs ->> 'agent_id') = ANY(:agent_ids)")
            params["agent_ids"] = allowed
        if agent_id is not None:
            clauses.append("lower(inputs ->> 'agent_id') = :agent_id")
            params["agent_id"] = str(agent_id).lower()
        if since is not None:
            clauses.append("started_at >= :since")
            params["since"] = since
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        res = self._conn.execute(
            text(
                "SELECT id, workflow_id, user_id, status, inputs, started_at, ended_at, progress, "
                "jsonb_array_length(steps) AS step_count "
                f"FROM workflow_runs WHERE {' AND '.join(clauses)} "
                "ORDER BY started_at DESC, id DESC LIMIT :limit"
            ),
            params,
        )
        return [row_to_dict(r) for r in res.fetchall()]
