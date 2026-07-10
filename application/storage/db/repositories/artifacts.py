"""Repository for the ``artifacts`` / ``artifact_versions`` tables.

Append-only artifact store. An ``artifacts`` row is the stable identity; each
edit appends an immutable ``artifact_versions`` row and atomically bumps
``artifacts.current_version`` (mirroring ``workflows.increment_graph_version``).

Authz is parent-derived: reads are not gated on ``user_id`` — callers resolve
access via the artifact's ``conversation_id`` / ``workflow_run_id`` parent.
``user_id`` is carried for ownership / quota accounting only. Pass-by-reference:
only metadata + the ``BaseStorage`` key are stored here, never binary bytes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict

logger = logging.getLogger(__name__)


def _artifact_to_dict(row: Any) -> dict:
    """row_to_dict for an ``artifacts`` row (``metadata`` key preserved)."""
    return row_to_dict(row)


def _version_to_dict(row: Any) -> dict:
    """row_to_dict for an ``artifact_versions`` row (``spec``/``produced_by`` keys preserved)."""
    return row_to_dict(row)


class ArtifactsRepository:
    """CRUD for artifact identities and their append-only versions."""

    def __init__(self, conn: Connection) -> None:
        """Bind the repository to an open SQLAlchemy connection."""
        self._conn = conn

    def create_artifact(
        self,
        user_id: str,
        kind: str,
        *,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        team_id: Optional[str] = None,
        message_id: Optional[str] = None,
        title: Optional[str] = None,
        metadata: Any = None,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        storage_path: Optional[str] = None,
        size: Optional[int] = None,
        sha256: Optional[str] = None,
        spec: Any = None,
        preview_text: Optional[str] = None,
        produced_by: Any = None,
    ) -> dict:
        """Create the identity row and its version 1 atomically; return the artifact dict.

        When a parent is given, a STABLE per-parent ``ref_seq`` (max existing + 1) is
        computed BEFORE the insert and stored into ``metadata`` so the short ``A{n}`` ref
        the model receives survives later deletions. See ``next_ref_seq`` for the (benign)
        concurrent-create dup caveat.
        """
        metadata_payload = metadata
        if conversation_id is not None or workflow_run_id is not None:
            ref_seq = self.next_ref_seq(
                conversation_id=conversation_id, workflow_run_id=workflow_run_id
            )
            merged = dict(metadata) if isinstance(metadata, dict) else {}
            merged["ref_seq"] = ref_seq
            metadata_payload = merged
        artifact = self._conn.execute(
            text(
                """
                INSERT INTO artifacts (
                    user_id, conversation_id, workflow_run_id, team_id,
                    message_id, kind, title, metadata, current_version
                )
                VALUES (
                    :user_id,
                    CAST(:conversation_id AS uuid),
                    CAST(:workflow_run_id AS uuid),
                    CAST(:team_id AS uuid),
                    CAST(:message_id AS uuid),
                    :kind, :title, CAST(:metadata AS jsonb), 1
                )
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "workflow_run_id": workflow_run_id,
                "team_id": team_id,
                "message_id": message_id,
                "kind": kind,
                "title": title,
                "metadata": json.dumps(metadata_payload) if metadata_payload is not None else None,
            },
        ).fetchone()
        artifact_dict = _artifact_to_dict(artifact)
        self._insert_version(
            artifact_id=artifact_dict["id"],
            version=1,
            mime_type=mime_type,
            filename=filename,
            storage_path=storage_path,
            size=size,
            sha256=sha256,
            spec=spec,
            preview_text=preview_text,
            produced_by=produced_by,
        )
        return artifact_dict

    def get_artifact(self, artifact_id: str) -> Optional[dict]:
        """Fetch one artifact by id, unscoped (prefer ``get_artifact_in_parent`` at request boundaries)."""
        result = self._conn.execute(
            text("SELECT * FROM artifacts WHERE id = CAST(:id AS uuid)"),
            {"id": artifact_id},
        )
        row = result.fetchone()
        return _artifact_to_dict(row) if row is not None else None

    def get_artifact_in_parent(
        self,
        artifact_id: str,
        *,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Fetch an artifact only if it belongs to the given parent; the safe gate for request handlers."""
        if conversation_id is None and workflow_run_id is None:
            raise ValueError("get_artifact_in_parent requires conversation_id or workflow_run_id")
        clauses = ["id = CAST(:id AS uuid)"]
        params: dict[str, Any] = {"id": artifact_id}
        if conversation_id is not None:
            clauses.append("conversation_id = CAST(:conversation_id AS uuid)")
            params["conversation_id"] = conversation_id
        if workflow_run_id is not None:
            clauses.append("workflow_run_id = CAST(:workflow_run_id AS uuid)")
            params["workflow_run_id"] = workflow_run_id
        result = self._conn.execute(
            text(f"SELECT * FROM artifacts WHERE {' AND '.join(clauses)}"),
            params,
        )
        row = result.fetchone()
        return _artifact_to_dict(row) if row is not None else None

    def find_bridged_attachment(
        self,
        attachment_id: str,
        *,
        conversation_id: str,
    ) -> Optional[dict]:
        """Return the conversation artifact already bridged from ``attachment_id``, or None (idempotency gate)."""
        result = self._conn.execute(
            text(
                "SELECT a.* FROM artifacts a "
                "JOIN artifact_versions v "
                "  ON v.artifact_id = a.id AND v.version = a.current_version "
                "WHERE a.conversation_id = CAST(:conversation_id AS uuid) "
                "  AND v.produced_by ->> 'attachment_id' = :attachment_id "
                "ORDER BY a.created_at ASC, a.id ASC LIMIT 1"
            ),
            {"conversation_id": conversation_id, "attachment_id": str(attachment_id)},
        )
        row = result.fetchone()
        return _artifact_to_dict(row) if row is not None else None

    def list_artifacts(
        self,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """List artifacts filtered by parent / owner (newest first); at least one filter is required."""
        if conversation_id is None and workflow_run_id is None and user_id is None:
            raise ValueError("list_artifacts requires at least one of conversation_id, workflow_run_id, user_id")
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if conversation_id is not None:
            clauses.append("conversation_id = CAST(:conversation_id AS uuid)")
            params["conversation_id"] = conversation_id
        if workflow_run_id is not None:
            clauses.append("workflow_run_id = CAST(:workflow_run_id AS uuid)")
            params["workflow_run_id"] = workflow_run_id
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        result = self._conn.execute(
            text(f"SELECT * FROM artifacts {where} ORDER BY created_at DESC"),
            params,
        )
        return [_artifact_to_dict(r) for r in result.fetchall()]

    def list_artifacts_for_agent(
        self,
        agent_id: str,
        user_id: str,
        conversation_id: Optional[str] = None,
    ) -> list[dict]:
        """List an agent's artifacts (owner-scoped), optionally narrowed to one conversation.

        Scopes a per-agent api-key's artifact visibility to the conversations that
        agent produced, so the key cannot enumerate the owner's whole corpus. When
        ``conversation_id`` is given, the SQL narrows to that single conversation
        (the per-visitor bearer capability for a public widget key).
        """
        clauses = ["c.agent_id = CAST(:agent_id AS uuid)", "a.user_id = :user_id"]
        params: dict[str, Any] = {"agent_id": str(agent_id), "user_id": user_id}
        if conversation_id is not None:
            clauses.append("a.conversation_id = CAST(:conversation_id AS uuid)")
            params["conversation_id"] = conversation_id
        result = self._conn.execute(
            text(
                "SELECT a.* FROM artifacts a "
                "JOIN conversations c ON a.conversation_id = c.id "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY a.created_at DESC, a.id DESC"
            ),
            params,
        )
        return [_artifact_to_dict(r) for r in result.fetchall()]

    def artifact_in_agent_scope(self, artifact_id: str, agent_id: str) -> bool:
        """True if ``artifact_id``'s parent conversation belongs to ``agent_id``."""
        clauses = [
            "a.id = CAST(:id AS uuid)",
            "c.agent_id = CAST(:agent_id AS uuid)",
        ]
        result = self._conn.execute(
            text(
                "SELECT 1 FROM artifacts a "
                "JOIN conversations c ON a.conversation_id = c.id "
                f"WHERE {' AND '.join(clauses)} "
                "LIMIT 1"
            ),
            {"id": artifact_id, "agent_id": str(agent_id)},
        )
        return result.fetchone() is not None

    def position_in_parent(
        self,
        artifact_id: str,
        *,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> int:
        """Return the 1-based position of an artifact within its parent (by created_at, id tie-break); 0 if absent."""
        if conversation_id is None and workflow_run_id is None:
            raise ValueError("position_in_parent requires conversation_id or workflow_run_id")
        outer, params = self._parent_clauses(conversation_id, workflow_run_id, alias="a")
        inner, _ = self._parent_clauses(conversation_id, workflow_run_id, alias="t")
        params["id"] = artifact_id
        # The inner SELECT applies the same parent scope, so an artifact in a
        # different parent yields no anchor row -> count() is 0 (not in this parent).
        row = self._conn.execute(
            text(
                f"SELECT count(*) FROM artifacts a "
                f"WHERE {' AND '.join(outer)} AND (a.created_at, a.id) <= ("
                f"  SELECT t.created_at, t.id FROM artifacts t "
                f"  WHERE {' AND '.join(inner)} AND t.id = CAST(:id AS uuid)"
                f")"
            ),
            params,
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def artifact_id_at_position(
        self,
        n: int,
        *,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> Optional[str]:
        """Return the id of the n-th artifact (1-based, created_at asc, id tie-break) in a parent, or None."""
        if conversation_id is None and workflow_run_id is None:
            raise ValueError("artifact_id_at_position requires conversation_id or workflow_run_id")
        if not isinstance(n, int) or n < 1:
            return None
        clauses, params = self._parent_clauses(conversation_id, workflow_run_id)
        params["offset"] = n - 1
        row = self._conn.execute(
            text(
                f"SELECT id FROM artifacts WHERE {' AND '.join(clauses)} "
                f"ORDER BY created_at ASC, id ASC OFFSET :offset LIMIT 1"
            ),
            params,
        ).fetchone()
        return str(row[0]) if row is not None else None

    def next_ref_seq(
        self,
        *,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> int:
        """Return the next stable ``ref_seq`` for a parent (max stored + 1; 1 when empty).

        Caveat: two concurrent creates in one parent can read the same MAX and get a
        duplicate ``ref_seq`` (creates within a parent are normally serial from one agent
        turn); a dup resolves to the earliest — acceptable, and strictly better than the
        re-point bug. A DB unique index is a possible future hardening (no migration here).
        """
        if conversation_id is None and workflow_run_id is None:
            raise ValueError("next_ref_seq requires conversation_id or workflow_run_id")
        clauses, params = self._parent_clauses(conversation_id, workflow_run_id)
        # Guard the cast: legacy rows have no ``ref_seq`` (NULL, ignored), and the regex
        # match keeps any non-numeric value from erroring the cast.
        row = self._conn.execute(
            text(
                "SELECT COALESCE(MAX(CASE WHEN metadata ->> 'ref_seq' ~ '^[0-9]+$' "
                "THEN (metadata ->> 'ref_seq')::int END), 0) + 1 "
                f"FROM artifacts WHERE {' AND '.join(clauses)}"
            ),
            params,
        ).fetchone()
        return int(row[0]) if row is not None else 1

    def resolve_id_by_ref_seq(
        self,
        seq: int,
        *,
        conversation_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> Optional[str]:
        """Return the id of the artifact whose stored ``ref_seq`` == ``seq`` in a parent, or None.

        Earliest ``created_at`` wins on the rare concurrent-create tie (see ``next_ref_seq``).
        """
        if conversation_id is None and workflow_run_id is None:
            raise ValueError("resolve_id_by_ref_seq requires conversation_id or workflow_run_id")
        if not isinstance(seq, int) or seq < 1:
            return None
        clauses, params = self._parent_clauses(conversation_id, workflow_run_id)
        params["seq"] = str(seq)
        row = self._conn.execute(
            text(
                f"SELECT id FROM artifacts WHERE {' AND '.join(clauses)} "
                "AND metadata ->> 'ref_seq' = :seq "
                "ORDER BY created_at ASC, id ASC LIMIT 1"
            ),
            params,
        ).fetchone()
        return str(row[0]) if row is not None else None

    @staticmethod
    def _parent_clauses(
        conversation_id: Optional[str], workflow_run_id: Optional[str], alias: str = ""
    ) -> tuple[list[str], dict[str, Any]]:
        """Build the parent-scope WHERE clauses + params (optionally column-aliased) for the position helpers."""
        prefix = f"{alias}." if alias else ""
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if conversation_id is not None:
            clauses.append(f"{prefix}conversation_id = CAST(:conversation_id AS uuid)")
            params["conversation_id"] = conversation_id
        if workflow_run_id is not None:
            clauses.append(f"{prefix}workflow_run_id = CAST(:workflow_run_id AS uuid)")
            params["workflow_run_id"] = workflow_run_id
        return clauses, params

    def count_for_user(self, user_id: str) -> int:
        """Return how many artifacts ``user_id`` currently owns (quota accounting)."""
        row = self._conn.execute(
            text("SELECT count(*) FROM artifacts WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def total_bytes_for_user(self, user_id: str) -> int:
        """Return the stored byte size a user owns (quota accounting).

        Deduplicated by ``storage_path``: ``restore`` appends a version that
        re-points at an existing version's stored object (same key + size), so
        summing every version row would charge the same bytes N times and inflate
        usage without any new bytes being written. Each distinct stored object is
        counted once; versions with no object yet (``storage_path IS NULL`` --
        spec-only, whose size is normally NULL too) are counted individually since
        they share no key to dedupe on.
        """
        row = self._conn.execute(
            text(
                "SELECT COALESCE(SUM(t.size), 0) FROM ("
                "  SELECT DISTINCT v.storage_path, v.size "
                "  FROM artifact_versions v "
                "  JOIN artifacts a ON a.id = v.artifact_id "
                "  WHERE a.user_id = :user_id AND v.storage_path IS NOT NULL "
                "  UNION ALL "
                "  SELECT v.storage_path, v.size "
                "  FROM artifact_versions v "
                "  JOIN artifacts a ON a.id = v.artifact_id "
                "  WHERE a.user_id = :user_id AND v.storage_path IS NULL"
                ") t"
            ),
            {"user_id": user_id},
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def delete_artifact(self, artifact_id: str) -> list[str]:
        """Delete an artifact (+ its versions, via FK cascade); return its stored paths.

        The caller deletes the returned storage objects best-effort AFTER commit;
        the DB delete also frees the owner's count/byte quota.
        """
        paths = [
            v["storage_path"]
            for v in self.list_versions(artifact_id)
            if v.get("storage_path")
        ]
        self._conn.execute(
            text("DELETE FROM artifacts WHERE id = CAST(:id AS uuid)"),
            {"id": artifact_id},
        )
        return paths

    def storage_paths_for_conversation(self, conversation_id: str) -> list[str]:
        """Return every stored version path for a conversation's artifacts (for byte cleanup)."""
        result = self._conn.execute(
            text(
                "SELECT v.storage_path FROM artifact_versions v "
                "JOIN artifacts a ON a.id = v.artifact_id "
                "WHERE a.conversation_id = CAST(:cid AS uuid) "
                "AND v.storage_path IS NOT NULL"
            ),
            {"cid": conversation_id},
        )
        return [r[0] for r in result.fetchall()]

    def storage_paths_for_user_conversations(self, user_id: str) -> list[str]:
        """Return every stored version path for artifacts under a user's conversations."""
        result = self._conn.execute(
            text(
                "SELECT v.storage_path FROM artifact_versions v "
                "JOIN artifacts a ON a.id = v.artifact_id "
                "JOIN conversations c ON c.id = a.conversation_id "
                "WHERE c.user_id = :user_id AND v.storage_path IS NOT NULL"
            ),
            {"user_id": user_id},
        )
        return [r[0] for r in result.fetchall()]

    def delete_for_conversation(self, conversation_id: str) -> int:
        """Delete all artifacts (+ versions, via cascade) parented to a conversation.

        ``conversation_id`` is a bare uuid column (no FK), so the parent delete
        does not cascade — callers invoke this to reclaim the rows + their quota.
        """
        result = self._conn.execute(
            text("DELETE FROM artifacts WHERE conversation_id = CAST(:cid AS uuid)"),
            {"cid": conversation_id},
        )
        return result.rowcount

    def delete_for_user_conversations(self, user_id: str) -> int:
        """Delete every artifact parented to one of a user's conversations (+ versions)."""
        result = self._conn.execute(
            text(
                "DELETE FROM artifacts WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE user_id = :user_id)"
            ),
            {"user_id": user_id},
        )
        return result.rowcount

    def storage_paths_for_workflow(self, workflow_id: str) -> list[str]:
        """Return every stored version path for artifacts under a workflow's runs (for byte cleanup)."""
        result = self._conn.execute(
            text(
                "SELECT v.storage_path FROM artifact_versions v "
                "JOIN artifacts a ON a.id = v.artifact_id "
                "JOIN workflow_runs r ON r.id = a.workflow_run_id "
                "WHERE r.workflow_id = CAST(:wid AS uuid) "
                "AND v.storage_path IS NOT NULL"
            ),
            {"wid": workflow_id},
        )
        return [r[0] for r in result.fetchall()]

    def delete_for_workflow(self, workflow_id: str) -> int:
        """Delete all artifacts (+ versions, via cascade) parented to a workflow's runs.

        ``artifacts.workflow_run_id`` is a bare uuid column (no FK), so deleting the
        workflow (which cascade-deletes its ``workflow_runs``) does NOT reap these
        rows -- callers invoke this to reclaim the rows + their quota. Must run
        BEFORE the workflow delete, while the run rows still resolve the subquery.
        """
        result = self._conn.execute(
            text(
                "DELETE FROM artifacts WHERE workflow_run_id IN "
                "(SELECT id FROM workflow_runs WHERE workflow_id = CAST(:wid AS uuid))"
            ),
            {"wid": workflow_id},
        )
        return result.rowcount

    @staticmethod
    def reap_storage(paths: list) -> None:
        """Best-effort delete a batch of artifact byte objects; never raises."""
        if not paths:
            return
        try:
            from application.storage.storage_creator import StorageCreator

            storage = StorageCreator.get_storage()
        except Exception:
            logger.warning("artifact cleanup: storage unavailable", exc_info=True)
            return
        for path in paths:
            try:
                storage.delete_file(path)
            except Exception:
                logger.warning("artifact cleanup: failed to delete bytes %s", path, exc_info=True)

    def get_version(self, artifact_id: str, version: int) -> Optional[dict]:
        """Fetch a single version row by artifact id and version number."""
        result = self._conn.execute(
            text(
                "SELECT * FROM artifact_versions "
                "WHERE artifact_id = CAST(:artifact_id AS uuid) AND version = :version"
            ),
            {"artifact_id": artifact_id, "version": version},
        )
        row = result.fetchone()
        return _version_to_dict(row) if row is not None else None

    def list_versions(self, artifact_id: str) -> list[dict]:
        """List every version of an artifact, oldest first."""
        result = self._conn.execute(
            text(
                "SELECT * FROM artifact_versions "
                "WHERE artifact_id = CAST(:artifact_id AS uuid) ORDER BY version ASC"
            ),
            {"artifact_id": artifact_id},
        )
        return [_version_to_dict(r) for r in result.fetchall()]

    def append_version(
        self,
        artifact_id: str,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        storage_path: Optional[str] = None,
        size: Optional[int] = None,
        sha256: Optional[str] = None,
        spec: Any = None,
        preview_text: Optional[str] = None,
        produced_by: Any = None,
    ) -> dict:
        """Append a new version and atomically bump ``current_version``; return the version dict."""
        new_version = self._conn.execute(
            text(
                "UPDATE artifacts "
                "SET current_version = current_version + 1, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) "
                "RETURNING current_version"
            ),
            {"id": artifact_id},
        ).fetchone()
        if new_version is None:
            raise ValueError(f"artifact {artifact_id} not found")
        return self._insert_version(
            artifact_id=artifact_id,
            version=new_version[0],
            mime_type=mime_type,
            filename=filename,
            storage_path=storage_path,
            size=size,
            sha256=sha256,
            spec=spec,
            preview_text=preview_text,
            produced_by=produced_by,
        )

    def _insert_version(
        self,
        *,
        artifact_id: str,
        version: int,
        mime_type: Optional[str],
        filename: Optional[str],
        storage_path: Optional[str],
        size: Optional[int],
        sha256: Optional[str],
        spec: Any,
        preview_text: Optional[str],
        produced_by: Any,
    ) -> dict:
        """Insert one append-only version row; UNIQUE(artifact_id, version) guards duplicates."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO artifact_versions (
                    artifact_id, version, mime_type, filename, storage_path,
                    size, sha256, spec, preview_text, produced_by
                )
                VALUES (
                    CAST(:artifact_id AS uuid), :version, :mime_type, :filename,
                    :storage_path, :size, :sha256, CAST(:spec AS jsonb),
                    :preview_text, CAST(:produced_by AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "artifact_id": artifact_id,
                "version": version,
                "mime_type": mime_type,
                "filename": filename,
                "storage_path": storage_path,
                "size": size,
                "sha256": sha256,
                "spec": json.dumps(spec) if spec is not None else None,
                "preview_text": preview_text,
                "produced_by": json.dumps(produced_by) if produced_by is not None else None,
            },
        )
        return _version_to_dict(result.fetchone())
