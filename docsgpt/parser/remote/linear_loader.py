"""Load Linear issues and documents as Knowledge, through Linear's MCP server.

A Linear source names teams and projects (see
``docsgpt.connectors.linear.normalize_selection``). Each issue becomes one
document: its identifier and title, state, assignee, priority, labels,
description and, optionally, its comments. With ``include_documents`` the
picked projects' Linear documents come too. Every document carries its
Linear URL as ``source``, so answers cite the issue.

Each sync reads everything again (up to ``MAX_ISSUES`` issues and
``MAX_DOCUMENTS`` documents): the index of a synced source is rebuilt
whole, so there is nothing to merge an incremental read into.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from docsgpt.connectors import linear
from docsgpt.connectors.mcp import MCPToolError, run_connection_session
from docsgpt.parser.remote.base import BaseRemote
from docsgpt.parser.schema.base import Document

logger = logging.getLogger(__name__)

_UNSAFE_PATH = re.compile(r"[\\/\x00-\x1f]+")


def _connection(connection_id: str) -> Optional[dict]:
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        return ConnectorSessionsRepository(conn).get(str(connection_id))


def _segment(value: str, fallback: str) -> str:
    """A file tree segment: no slashes or control characters, never empty."""
    cleaned = _UNSAFE_PATH.sub(" ", value or "").strip().strip(".")
    return cleaned[:120] or fallback


def _day(value: Any) -> str:
    return str(value)[:10] if value else ""


class LinearLoader(BaseRemote):
    """Read a Linear source's issues and documents with its connection's sign-in."""

    def load_data(self, inputs: dict) -> list[Document]:
        """Read what ``inputs`` picks, signed in with its ``connection_id``.

        Args:
            inputs: The source's selection plus ``connection_id``, merged in
                by the worker from the source's connection.

        Raises:
            ValueError: No connection, or nothing picked.
            docsgpt.connectors.service.ConnectionUnavailable: The connection
                needs reconnecting.
        """
        inputs = inputs if isinstance(inputs, dict) else {}
        connection_id = inputs.get("connection_id")
        connection = _connection(connection_id) if connection_id else None
        if connection is None:
            raise ValueError("A Linear source needs its Linear connection")
        selection = linear.normalize_selection(inputs)
        return run_connection_session(
            connection, linear.mcp_url(), lambda session: self.collect(session, selection),
        )

    async def collect(self, session: Any, selection: dict) -> list[Document]:
        """The documents for ``selection``, read over an open MCP session."""
        issues: dict[str, dict] = {}
        filters = [(("team", "teamId"), team["id"]) for team in selection["teams"]]
        filters += [(("project", "projectId"), project["id"]) for project in selection["projects"]]
        for names, value in filters:
            remaining = linear.MAX_ISSUES - len(issues)
            if remaining <= 0:
                logger.info("Linear sync stopped at %d issues", linear.MAX_ISSUES)
                break
            async for issue in linear.paged(
                session, "list_issues", "issues", {names: value}, limit=remaining,
                extra={"orderBy": "updatedAt", "includeArchived": False},
            ):
                key = linear.issue_identifier(issue) or str(issue.get("id") or "")
                if key:
                    issues.setdefault(key, issue)
        documents = []
        for key, issue in issues.items():
            # One issue Linear will not read (deleted since it was listed, or
            # out of the token's reach) loses that detail, not the whole sync.
            if linear.is_truncated(issue.get("description")) or issue.get("descriptionTruncated"):
                try:
                    issue = await self._full_issue(session, key, issue)
                except MCPToolError as exc:
                    logger.warning("Linear sync keeps %s as listed: %s", key, exc)
            comments = []
            if selection["include_comments"]:
                try:
                    comments = await self._comments(session, key)
                except MCPToolError as exc:
                    logger.warning("Linear sync leaves out the comments of %s: %s", key, exc)
            documents.append(self._issue_document(issue, comments, selection))
        if selection["include_documents"]:
            documents.extend(await self._project_documents(session, selection["projects"]))
        return documents

    async def _full_issue(self, session: Any, key: str, issue: dict) -> dict:
        schema = await session.input_schema("get_issue")
        if schema is None:
            return issue
        full = linear.unwrap(await session.call("get_issue", {linear.argument(schema, "id", "issueId"): key}), "issue")
        return {**issue, **{k: v for k, v in full.items() if v not in (None, "")}}

    async def _comments(self, session: Any, key: str) -> list[dict]:
        """An issue's comments, oldest first as Linear lists them; none when Linear cannot list them."""
        schema = await session.input_schema("list_comments")
        names = ("issueId", "id", "issue")
        if schema is None or linear.argument(schema, *names) is None:
            return []
        return [
            comment async for comment in linear.paged(
                session, "list_comments", "comments", {names: key}, limit=linear.MAX_COMMENTS,
            )
        ]

    def _issue_document(self, issue: dict, comments: list[dict], selection: dict) -> Document:
        identifier = linear.issue_identifier(issue) or str(issue.get("id") or "")
        title = str(issue.get("title") or "").strip() or identifier
        heading = f"{identifier}: {title}" if identifier else title
        facts = [
            ("State", linear.name_of(issue.get("status") or issue.get("state"))),
            ("Assignee", linear.name_of(issue.get("assignee"))),
            ("Priority", linear.priority_of(issue.get("priority"))),
            ("Labels", ", ".join(linear.names_of(issue.get("labels")))),
            ("Project", linear.name_of(issue.get("project"))),
            ("Team", linear.name_of(issue.get("team"))),
            ("Due", _day(issue.get("dueDate"))),
            ("Created", _day(issue.get("createdAt"))),
            ("Updated", _day(issue.get("updatedAt"))),
            ("Link", str(issue.get("url") or "")),
        ]
        lines = [f"# {heading}", ""]
        lines += [f"- {label}: {value}" for label, value in facts if value]
        description = str(issue.get("description") or "").strip()
        if description:
            lines += ["", "## Description", "", description]
        written = [c for c in comments if str(c.get("body") or "").strip()]
        if written:
            lines += ["", "## Comments"]
            for comment in written:
                author = linear.name_of(comment.get("user") or comment.get("author")) or "Someone"
                when = _day(comment.get("createdAt"))
                lines += ["", f"**{author}**" + (f" · {when}" if when else ""), str(comment["body"]).strip()]
        return Document(
            text="\n".join(lines).strip() + "\n",
            extra_info={
                "title": heading,
                "source": str(issue.get("url") or ""),
                "file_path": f"{self._team_folder(issue, identifier, selection)}/{_segment(identifier, 'issue')}.md",
                "linear_id": str(issue.get("id") or identifier),
                "updated_at": str(issue.get("updatedAt") or ""),
            },
        )

    @staticmethod
    def _team_folder(issue: dict, identifier: str, selection: dict) -> str:
        """The folder an issue is filed under: its team's key (``ENG``), else its team's name."""
        team = issue.get("team")
        key = team.get("key") if isinstance(team, dict) else None
        if not key and "-" in identifier:
            key = identifier.rsplit("-", 1)[0]
        return _segment(str(key or linear.name_of(team) or ""), "Issues")

    async def _project_documents(self, session: Any, projects: list[dict]) -> list[Document]:
        """The Linear documents of ``projects``, each read in full, up to ``MAX_DOCUMENTS``."""
        documents: list[Document] = []
        paths: set[str] = set()
        get_schema = await session.input_schema("get_document")
        for project in projects:
            remaining = linear.MAX_DOCUMENTS - len(documents)
            if remaining <= 0:
                break
            async for record in linear.paged(
                session, "list_documents", "documents", {("projectId", "project"): project["id"]}, limit=remaining,
            ):
                content = record.get("content")
                if (not content or linear.is_truncated(content)) and get_schema is not None and record.get("id"):
                    try:
                        full = linear.unwrap(
                            await session.call("get_document", {linear.argument(get_schema, "id", "documentId"):
                                                                str(record["id"])}),
                            "document",
                        )
                    except MCPToolError as exc:
                        # A document that cannot be read is skipped, not the sync.
                        logger.warning("Linear sync skips document %s: %s", record.get("id"), exc)
                        continue
                    record = {**record, **{k: v for k, v in full.items() if v not in (None, "")}}
                document = self._linear_document(record, project)
                path = document.extra_info["file_path"]
                if path in paths:
                    # Two documents with one title stay two files.
                    document.extra_info["file_path"] = f"{path[:-3]} ({str(record.get('id') or len(paths))[:8]}).md"
                paths.add(document.extra_info["file_path"])
                documents.append(document)
        return documents

    @staticmethod
    def _linear_document(record: dict, project: dict) -> Document:
        title = str(record.get("title") or "").strip() or "Untitled document"
        content = str(record.get("content") or "").strip()
        project_name = project.get("name") or linear.name_of(record.get("project"))
        lines = [f"# {title}", ""]
        if project_name:
            lines.append(f"- Project: {project_name}")
        if record.get("url"):
            lines.append(f"- Link: {record['url']}")
        if content:
            lines += ["", content]
        folder = _segment(project_name or "", "Documents")
        return Document(
            text="\n".join(lines).strip() + "\n",
            extra_info={
                "title": title,
                "source": str(record.get("url") or ""),
                "file_path": f"{folder}/Documents/{_segment(title, 'Document')}.md",
                "linear_id": str(record.get("id") or ""),
                "updated_at": str(record.get("updatedAt") or ""),
            },
        )
