"""``GET /api/teams/<team_id>/chats/export``: every chat of a team workspace as one NDJSON file.

Behind ``TEAM_CHAT_EXPORT_ENABLED`` (404 while it is off), for the team's
Owner and Admins. A chat is in the file when it was started in the team
(``conversations.team_id``) and only then: Personal chats and another team's
chats can't match, whoever started them. A member who left keeps their
chats in the file; the team principal's chats (key, widget and link
traffic) are in it as ``via: "outside"``.

What a message line keeps: the prompt and answer, when, the model, source
titles, tool names, attachment file names and the feedback. Reasoning, tool
arguments and results (which can hold secrets) and attachment contents are
never written.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from flask import Response, jsonify, make_response, stream_with_context
from flask_restx import Resource
from sqlalchemy import text

from docsgpt.api.audit import record_required_event
from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.workspaces.principal import PRINCIPAL_PREFIX, is_principal_id

from .routes import _current_user, _user_labels, team_admin_refusal, teams_ns

logger = logging.getLogger(__name__)

#: Conversations read per round trip while the file streams.
PAGE_SIZE = 200

#: Most messages held at once while the file streams; a longer chat is read on its own.
MESSAGE_BATCH = 2000

_SLUG_UNSAFE = re.compile(r"[^a-z0-9-]+")

_CONVERSATIONS_SQL = (
    "SELECT c.id, c.name, c.user_id, c.agent_id, a.name AS agent_name, c.is_shared_usage, c.created_at, "
    "c.updated_at FROM conversations c LEFT JOIN agents a ON a.id = c.agent_id "
    "WHERE c.team_id = CAST(:team_id AS uuid) {after} ORDER BY c.id LIMIT :limit"
)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def export_filename(team: dict, now: datetime) -> str:
    """``docsgpt-<team-slug>-chats-<YYYY-MM-DD>.ndjson``, the slug reduced to safe characters."""
    slug = _SLUG_UNSAFE.sub("-", str(team.get("slug") or "team").lower()).strip("-") or "team"
    return f"docsgpt-{slug}-chats-{now.date().isoformat()}.ndjson"


def _counts(conn, team_id: str) -> tuple[int, int]:
    """``(conversations, people)`` in the team's chats; the principal is not a person."""
    row = conn.execute(
        text(
            "SELECT count(*), count(DISTINCT user_id) FILTER (WHERE left(user_id, :n) <> :prefix) "
            "FROM conversations WHERE team_id = CAST(:team_id AS uuid)"
        ),
        {"team_id": team_id, "n": len(PRINCIPAL_PREFIX), "prefix": PRINCIPAL_PREFIX},
    ).one()
    return int(row[0]), int(row[1])


def _members(conn, team_id: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT user_id FROM team_members WHERE team_id = CAST(:t AS uuid) "
            "UNION SELECT owner_id FROM teams WHERE id = CAST(:t AS uuid)"
        ),
        {"t": team_id},
    ).fetchall()
    return {row[0] for row in rows if row[0]}


def _source_titles(sources: Any) -> list[str]:
    titles = []
    for source in sources or []:
        title = source.get("title") if isinstance(source, dict) else None
        if title:
            titles.append(str(title))
    return titles


def _tool_names(tool_calls: Any) -> list[str]:
    names = []
    for call in tool_calls or []:
        if isinstance(call, dict):
            name = call.get("action_name") or call.get("tool_name")
            if name:
                names.append(str(name))
    return names


def _messages(conn, conversation_ids: list[str]) -> dict[str, list[dict]]:
    """The message lines of each conversation, in order, holding only what the file may carry."""
    rows = conn.execute(
        text(
            "SELECT conversation_id, prompt, response, timestamp, model_id, sources, tool_calls, attachments, "
            "feedback FROM conversation_messages WHERE conversation_id = ANY(CAST(:ids AS uuid[])) "
            "ORDER BY conversation_id, position"
        ),
        {"ids": conversation_ids},
    ).mappings().fetchall()
    attachment_ids = sorted({str(a) for row in rows for a in (row["attachments"] or [])})
    filenames: dict[str, str] = {}
    if attachment_ids:
        filenames = {
            str(rid): name
            for rid, name in conn.execute(
                text("SELECT id, filename FROM attachments WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": attachment_ids},
            ).fetchall()
        }
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(str(row["conversation_id"]), []).append({
            "prompt": row["prompt"],
            "response": row["response"],
            "created_at": _iso(row["timestamp"]),
            "model_id": row["model_id"],
            "sources": _source_titles(row["sources"]),
            "tool_calls": _tool_names(row["tool_calls"]),
            "attachments": [filenames[str(a)] for a in (row["attachments"] or []) if str(a) in filenames],
            "feedback": row["feedback"],
        })
    return out


def _message_batches(conn, conversation_ids: list[str]) -> list[list[str]]:
    """Split a page of conversations, in order, into runs of at most :data:`MESSAGE_BATCH` messages.

    A conversation is never split (it is one line of the file), so one longer
    than the bound makes a batch of its own.

    Args:
        conn: Open connection.
        conversation_ids: The page's conversations, in file order.

    Returns:
        The ids in batches, order kept.
    """
    counts = dict(conn.execute(
        text(
            "SELECT conversation_id::text, count(*) FROM conversation_messages "
            "WHERE conversation_id = ANY(CAST(:ids AS uuid[])) GROUP BY conversation_id"
        ),
        {"ids": conversation_ids},
    ).fetchall())
    batches: list[list[str]] = []
    held = 0
    for conversation_id in conversation_ids:
        size = int(counts.get(conversation_id, 0))
        if not batches or held + size > MESSAGE_BATCH:
            batches.append([])
            held = 0
        batches[-1].append(conversation_id)
        held += size
    return batches


def _labels(conn, user_ids: set[str]) -> dict[str, str]:
    labels = _user_labels(conn, {u for u in user_ids if not is_principal_id(u)})
    labels.update(UsersRepository(conn).principal_labels(user_ids))
    return labels


def conversation_lines(conn, team_id: str) -> Iterator[dict]:
    """Every conversation of the team as its export line, paged by id so a long export holds no big result.

    Messages are read a batch at a time (:func:`_message_batches`), so a page
    of long chats isn't held in memory at once.

    Args:
        conn: Open connection, held for the whole walk.
        team_id: The team.

    Yields:
        ``{type: "conversation", id, name, user {user_id, label, member}, agent {id, name} | None,
        via: "app" | "outside", created_at, updated_at, messages [...]}``.
    """
    members = _members(conn, team_id)
    after: Optional[str] = None
    while True:
        params: dict[str, Any] = {"team_id": team_id, "limit": PAGE_SIZE}
        clause = ""
        if after is not None:
            clause, params["after"] = "AND c.id > CAST(:after AS uuid)", after
        page = conn.execute(text(_CONVERSATIONS_SQL.format(after=clause)), params).mappings().fetchall()
        if not page:
            return
        ids = [str(row["id"]) for row in page]
        labels = _labels(conn, {row["user_id"] for row in page})
        rows = {str(row["id"]): row for row in page}
        for batch in _message_batches(conn, ids):
            yield from _batch_lines(conn, [rows[i] for i in batch], labels, members)
        after = ids[-1]
        if len(page) < PAGE_SIZE:
            return


def _batch_lines(conn, page: list[dict], labels: dict[str, str], members: set[str]) -> Iterator[dict]:
    """The export lines of a batch of conversations, their messages read in one query.

    Args:
        conn: Open connection.
        page: The batch's conversation rows, in file order.
        labels: ``user_id -> label`` for their owners.
        members: The team's current members.

    Yields:
        One conversation line each (see :func:`conversation_lines`).
    """
    messages = _messages(conn, [str(row["id"]) for row in page])
    for row in page:
        owner = row["user_id"]
        yield {
            "type": "conversation",
            "id": str(row["id"]),
            "name": row["name"],
            "user": {"user_id": owner, "label": labels.get(owner) or owner, "member": owner in members},
            "agent": {"id": str(row["agent_id"]), "name": row["agent_name"]} if row["agent_id"] else None,
            # Key, widget and public-link traffic, as opposed to a member chatting in the app.
            "via": "outside" if is_principal_id(owner) or row["is_shared_usage"] else "app",
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "messages": messages.get(str(row["id"]), []),
        }


def _stream(team_id: str, header: dict) -> Iterator[str]:
    yield json.dumps(header) + "\n"
    with db_readonly() as conn:
        for line in conversation_lines(conn, team_id):
            yield json.dumps(line, default=str) + "\n"


@teams_ns.route("/teams/<string:team_id>/chats/export")
class TeamChatsExport(Resource):
    def get(self, team_id):
        """Every chat of the team workspace as NDJSON: a header line, then one line per conversation.

        404 while ``TEAM_CHAT_EXPORT_ENABLED`` is off, as if the route were
        absent. The team's Owner and Admins only (403
        ``workspace_role_required`` below Admin, 404 outside the team). The
        ``team.chats_exported`` audit row is written before the first byte;
        503 ``audit_unavailable`` and no file when it can't be.
        """
        if not settings.TEAM_CHAT_EXPORT_ENABLED:
            return make_response(jsonify({"success": False, "message": "Not found"}), 404)
        user = _current_user()
        now = datetime.now(timezone.utc)
        try:
            with db_session() as conn:
                refusal = team_admin_refusal(conn, user, team_id)
                if refusal is not None:
                    return refusal
                team = TeamsRepository(conn).get(team_id) or {}
                conversations, people = _counts(conn, team_id)
                try:
                    record_required_event(
                        conn, "team.chats_exported", actor=user, team_id=team_id, conversations=conversations,
                        people=people,
                    )
                except Exception:
                    # Every export is audited: with no audit row there is no file.
                    logger.error("Team chat export refused: the audit row was not written", exc_info=True)
                    return make_response(
                        jsonify({"success": False, "error": "audit_unavailable",
                                 "message": "The export can't be recorded right now. Try again later."}),
                        503,
                    )
        except Exception as err:
            logger.error("Team chat export failed: %s", err, exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        header = {
            "type": "export",
            "team": {"id": str(team.get("id") or team_id), "name": team.get("name")},
            "exported_by": user,
            "exported_at": now.isoformat(),
            "conversations": conversations,
        }
        return Response(
            stream_with_context(_stream(team_id, header)),
            mimetype="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{export_filename(team, now)}"',
                "Cache-Control": "no-store",
            },
        )
