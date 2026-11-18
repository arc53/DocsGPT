"""What an API client needs to fetch the artifacts a turn produced.

Tool calls report each artifact they produced as ``{id, filename, ref,
version}``. A client of ``/stream`` or ``/v1/chat/completions`` also needs
the type, size and checksum of that version and a URL to download it, and a
list of every artifact the turn touched without walking the tool calls.
:class:`ArtifactDescriber` adds those fields as the events leave the server;
what is persisted with the message is not changed.

The URL is the artifact download route, pinned to the version the call
produced and carrying the artifact's conversation, which an agent API key
must name. It never carries a credential: the client authenticates with
``Authorization: Bearer <agent API key>`` (or its session), and on S3 storage
the route answers with a short-lived presigned URL. It is absolute when
``PUBLIC_API_BASE_URL`` is set, else a path on the API's own host.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from docsgpt.core.settings import settings
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

# Version fields copied into a described entry, by their row names.
_VERSION_FIELDS = ("version", "mime_type", "size", "sha256", "filename")


def artifact_download_url(
    artifact_id: str, *, version: Optional[int] = None, conversation_id: Optional[str] = None
) -> str:
    """The download URL of an artifact version, without any credential in it.

    Args:
        artifact_id: The artifact.
        version: The version to pin; the current one when None.
        conversation_id: The artifact's conversation, which an agent API key
            has to name to read it.

    Returns:
        ``/api/artifacts/{id}/download?...``, prefixed with
        ``PUBLIC_API_BASE_URL`` when that is set.
    """
    query: Dict[str, Any] = {}
    if conversation_id:
        query["conversation_id"] = str(conversation_id)
    if version is not None:
        query["version"] = int(version)
    path = f"/api/artifacts/{quote(str(artifact_id), safe='')}/download"
    if query:
        path += "?" + urlencode(query)
    base = (settings.PUBLIC_API_BASE_URL or "").strip().rstrip("/")
    return f"{base}{path}" if base else path


class ArtifactDescriber:
    """Describes the artifact entries of one turn's tool calls, and keeps the turn's list.

    One database read per artifact version, cached for the turn: the same
    entry is described again when the turn's tool calls are sent as a whole.
    A failed read never fails the turn; the entry keeps what it had plus its
    URL.
    """

    def __init__(self, user_id: Optional[str], conversation_id: Optional[str] = None) -> None:
        """Bind to the turn.

        Args:
            user_id: The turn's user; only their artifacts, or this
                conversation's, are described.
            conversation_id: The turn's conversation.
        """
        self.user_id = str(user_id) if user_id else None
        self.conversation_id = str(conversation_id) if conversation_id else None
        self._rows: Dict[Tuple[str, Optional[int]], Dict[str, Any]] = {}
        self._turn: Dict[str, Dict[str, Any]] = {}

    def describe(self, entries: Any) -> List[Dict[str, Any]]:
        """``entries`` with each artifact's version metadata and download URL added.

        Args:
            entries: A tool call's ``artifacts`` list.

        Returns:
            New entry dicts; non-dict items are dropped.
        """
        described = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            described.append(self._describe_one(entry))
        return described

    def tool_call(self, data: Any) -> Any:
        """A tool call event's ``data`` with its artifacts described; other data unchanged."""
        if not isinstance(data, dict) or not data.get("artifacts"):
            return data
        return {**data, "artifacts": self.describe(data["artifacts"])}

    def tool_calls(self, calls: Any) -> Any:
        """A list of tool calls with each one's artifacts described."""
        if not isinstance(calls, list):
            return calls
        return [self.tool_call(call) for call in calls]

    def summary(self) -> List[Dict[str, Any]]:
        """Every artifact described this turn, once each at its latest version, in first-seen order."""
        return [dict(entry) for entry in self._turn.values()]

    # ---- internals ----

    def _describe_one(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        artifact_id = str(entry["id"]).strip()
        version = entry.get("version") if isinstance(entry.get("version"), int) else None
        row = self._row(artifact_id, version)
        out = dict(entry)
        for key, value in row.items():
            if value is None or key == "conversation_id" or (key == "filename" and out.get("filename")):
                continue
            out[key] = value
        out["download_url"] = artifact_download_url(
            artifact_id,
            version=out.get("version") if isinstance(out.get("version"), int) else None,
            conversation_id=row.get("conversation_id") or self.conversation_id,
        )
        current = self._turn.get(artifact_id)
        if current is None or (out.get("version") or 0) >= (current.get("version") or 0):
            self._turn[artifact_id] = out
        return out

    def _row(self, artifact_id: str, version: Optional[int]) -> Dict[str, Any]:
        key = (artifact_id, version)
        if key not in self._rows:
            self._rows[key] = self._load(artifact_id, version)
        return self._rows[key]

    def _load(self, artifact_id: str, version: Optional[int]) -> Dict[str, Any]:
        """The artifact's identity and version fields, or ``{}`` when it is not the turn's to describe."""
        if not looks_like_uuid(artifact_id):
            return {}
        try:
            with db_readonly() as conn:
                repo = ArtifactsRepository(conn)
                artifact = repo.get_artifact(artifact_id)
                if artifact is None or not self._owns(artifact):
                    return {}
                row = repo.get_version(artifact_id, version or artifact.get("current_version"))
        except Exception:
            logger.warning("Could not describe artifact %s", artifact_id, exc_info=True)
            return {}
        described: Dict[str, Any] = {
            "kind": artifact.get("kind"),
            "title": artifact.get("title"),
            "conversation_id": (
                str(artifact["conversation_id"]) if artifact.get("conversation_id") is not None else None
            ),
        }
        for field in _VERSION_FIELDS:
            if row is not None:
                described[field] = row.get(field)
        return described

    def _owns(self, artifact: Dict[str, Any]) -> bool:
        if self.user_id and str(artifact.get("user_id")) == self.user_id:
            return True
        parent = artifact.get("conversation_id")
        return bool(self.conversation_id and parent is not None and str(parent) == self.conversation_id)

