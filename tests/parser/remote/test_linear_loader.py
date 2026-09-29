"""Linear issues and documents as Knowledge, read through Linear's MCP server (mocked)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from docsgpt.connectors import linear
from docsgpt.parser.remote.linear_loader import LinearLoader

# Input schemas shaped like the ones Linear's MCP server publishes.
SCHEMAS = {
    "list_issues": {"properties": {
        "team": {}, "project": {}, "limit": {"maximum": 250}, "cursor": {}, "orderBy": {}, "includeArchived": {},
    }},
    "get_issue": {"properties": {"id": {}}},
    "list_comments": {"properties": {"issueId": {}}},
    "list_documents": {"properties": {"projectId": {}, "limit": {}, "cursor": {}}},
    "get_document": {"properties": {"id": {}}},
    "list_teams": {"properties": {"limit": {}, "cursor": {}}},
    "list_projects": {"properties": {"limit": {}, "cursor": {}, "includeArchived": {}}},
}

ISSUE = {
    "id": "ENG-1310",
    "title": "Fix the loader",
    "description": "The spinner stays for 10 s.",
    "url": "https://linear.app/acme/issue/ENG-1310/fix-the-loader",
    "status": "In Progress",
    "priority": {"value": 2, "name": "High"},
    "assignee": "Sam",
    "labels": ["bug", {"id": "l2", "name": "ui"}],
    "project": "Acme",
    "team": "Engineering",
    "createdAt": "2026-09-20T10:00:00.000Z",
    "updatedAt": "2026-09-25T09:30:00.000Z",
}


class FakeLinear:
    """Linear's MCP server, answering tool calls from handlers."""

    def __init__(self, handlers, schemas=None):
        self.handlers = handlers
        self.schemas = SCHEMAS if schemas is None else schemas
        self.calls: list[tuple[str, dict]] = []

    async def input_schema(self, name):
        return self.schemas.get(name)

    async def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return self.handlers[name](arguments)

    def called(self, name):
        return [args for tool, args in self.calls if tool == name]


def _collect(session, **selection):
    selection = linear.normalize_selection({"teams": [], "projects": [], **selection})
    return asyncio.run(LinearLoader().collect(session, selection))


class TestIssues:
    def test_one_document_per_issue_with_what_it_says(self):
        session = FakeLinear({
            "list_issues": lambda args: {"issues": [ISSUE], "hasNextPage": False},
            "list_comments": lambda args: {"comments": [
                {"id": "c1", "body": "Reproduced on the current release.", "user": {"name": "Alex"},
                 "createdAt": "2026-09-21T11:00:00.000Z"},
                {"id": "c2", "body": "Fixed.", "author": "Sam", "createdAt": "2026-09-22T11:00:00.000Z"},
            ]},
        })
        [doc] = _collect(session, teams=[{"id": "team-1", "key": "ENG", "name": "Engineering"}])
        text = doc.text
        assert text.startswith("# ENG-1310: Fix the loader")
        for fragment in ("In Progress", "Sam", "High", "bug, ui", "Acme", "The spinner stays for 10 s.",
                         "Reproduced on the current release.", "Alex", "Fixed."):
            assert fragment in text
        assert doc.extra_info["title"] == "ENG-1310: Fix the loader"
        assert doc.extra_info["source"] == ISSUE["url"]
        assert doc.extra_info["file_path"] == "ENG/ENG-1310.md"
        assert session.called("list_comments") == [{"issueId": "ENG-1310"}]

    def test_pages_through_a_teams_issues(self):
        pages = {
            None: {"issues": [{**ISSUE, "id": "ENG-2"}], "hasNextPage": True, "cursor": "p2"},
            "p2": {"issues": [{**ISSUE, "id": "ENG-1"}], "hasNextPage": False},
        }
        session = FakeLinear({"list_issues": lambda args: pages[args.get("cursor")]})
        docs = _collect(session, teams=["team-1"], include_comments=False)
        assert [d.extra_info["title"].split(":")[0] for d in docs] == ["ENG-2", "ENG-1"]
        first, second = session.called("list_issues")
        assert first == {"team": "team-1", "limit": 100, "orderBy": "updatedAt", "includeArchived": False}
        assert second == {**first, "cursor": "p2"}

    def test_a_clipped_description_is_read_in_full(self):
        clipped = {**ISSUE, "description": "The spinner (truncated, use get_issue to read the full description)"}
        session = FakeLinear({
            "list_issues": lambda args: {"issues": [clipped]},
            "get_issue": lambda args: {"issue": {**ISSUE, "description": "The whole story."}},
        })
        [doc] = _collect(session, teams=["team-1"], include_comments=False)
        assert "The whole story." in doc.text
        assert "truncated" not in doc.text
        assert session.called("get_issue") == [{"id": "ENG-1310"}]

    def test_comments_are_paged_through(self):
        schemas = {**SCHEMAS, "list_comments": {"properties": {"issueId": {}, "cursor": {}}}}
        pages = {
            None: {"comments": [{"body": "First."}], "hasNextPage": True, "cursor": "c2"},
            "c2": {"comments": [{"body": "Second."}], "hasNextPage": False},
        }
        session = FakeLinear({
            "list_issues": lambda args: [ISSUE],
            "list_comments": lambda args: pages[args.get("cursor")],
        }, schemas)
        [doc] = _collect(session, teams=["team-1"])
        assert "First." in doc.text and "Second." in doc.text

    def test_comments_linear_cannot_list_are_skipped(self):
        schemas = {k: v for k, v in SCHEMAS.items() if k != "list_comments"}
        session = FakeLinear({"list_issues": lambda args: [ISSUE]}, schemas)
        [doc] = _collect(session, teams=["team-1"])
        assert "## Comments" not in doc.text

    def test_comments_are_left_out_when_not_wanted(self):
        session = FakeLinear({"list_issues": lambda args: [ISSUE]})
        [doc] = _collect(session, teams=["team-1"], include_comments=False)
        assert session.called("list_comments") == []
        assert "## Comments" not in doc.text

    def test_an_issue_in_a_picked_team_and_project_is_synced_once(self):
        session = FakeLinear({"list_issues": lambda args: {"issues": [ISSUE]}})
        docs = _collect(session, teams=["team-1"], projects=["project-1"], include_comments=False)
        assert len(docs) == 1
        assert [args.get("team") or args.get("project") for args in session.called("list_issues")] == [
            "team-1", "project-1",
        ]

    def test_stops_at_the_cap(self, monkeypatch):
        monkeypatch.setattr(linear, "MAX_ISSUES", 3)
        pages = iter(range(100))

        def endless(args):
            page = next(pages)
            issues = [{**ISSUE, "id": f"ENG-{page}{n}"} for n in range(2)]
            return {"issues": issues, "hasNextPage": True, "cursor": f"p{page + 1}"}

        session = FakeLinear({"list_issues": endless})
        docs = _collect(session, teams=["team-1"], projects=["project-1"], include_comments=False)
        assert len(docs) == 3
        assert len(session.called("list_issues")) == 2

    def test_a_repeated_cursor_ends_the_listing(self):
        session = FakeLinear({"list_issues": lambda args: {"issues": [ISSUE], "hasNextPage": True, "cursor": "same"}})
        _collect(session, teams=["team-1"], include_comments=False)
        assert len(session.called("list_issues")) == 2

    def test_nested_records_and_graphql_page_info_are_read(self):
        record = {
            "id": "5c1e3d2a-uuid", "identifier": "DES-7", "title": "Logo",
            "state": {"id": "s", "name": "Done"}, "assignee": {"id": "u", "displayName": "kim"},
            "team": {"id": "t", "key": "DES", "name": "Design"}, "labels": {"nodes": [{"name": "brand"}]},
        }
        session = FakeLinear({"list_issues": lambda args: {
            "nodes": [record], "pageInfo": {"hasNextPage": False, "endCursor": "x"},
        }})
        [doc] = _collect(session, teams=["t"], include_comments=False)
        assert doc.text.startswith("# DES-7: Logo")
        assert "Done" in doc.text and "kim" in doc.text and "brand" in doc.text
        assert doc.extra_info["file_path"] == "DES/DES-7.md"

    def test_argument_names_follow_the_tools_schema(self):
        schemas = {**SCHEMAS, "list_issues": {"properties": {"teamId": {}, "first": {"maximum": 50}, "after": {}}}}
        pages = {None: {"issues": [ISSUE], "hasNextPage": True, "cursor": "p2"}, "p2": {"issues": []}}
        session = FakeLinear({"list_issues": lambda args: pages[args.get("after")]}, schemas)
        _collect(session, teams=["team-1"], include_comments=False)
        assert session.called("list_issues") == [
            {"teamId": "team-1", "first": 50}, {"teamId": "team-1", "first": 50, "after": "p2"},
        ]

    def test_a_tool_that_cannot_filter_by_team_syncs_nothing(self):
        schemas = {**SCHEMAS, "list_issues": {"properties": {"query": {}, "limit": {}}}}
        session = FakeLinear({"list_issues": lambda args: pytest.fail("must not list the whole workspace")}, schemas)
        with pytest.raises(linear.LinearSyncError, match="team"):
            _collect(session, teams=["team-1"])

    def test_a_missing_tool_is_an_error(self):
        session = FakeLinear({}, schemas={})
        with pytest.raises(linear.LinearSyncError, match="list_issues"):
            _collect(session, teams=["team-1"])


class TestDocuments:
    def test_documents_of_the_picked_projects(self):
        session = FakeLinear({
            "list_issues": lambda args: {"issues": []},
            "list_documents": lambda args: {"documents": [
                {"id": "d1", "title": "Launch plan", "url": "https://linear.app/acme/document/launch-plan-d1"},
            ]},
            "get_document": lambda args: {"id": "d1", "title": "Launch plan", "content": "We ship on Monday.",
                                          "url": "https://linear.app/acme/document/launch-plan-d1"},
        })
        [doc] = _collect(session, projects=[{"id": "project-1", "name": "Acme"}], include_documents=True)
        assert doc.text.startswith("# Launch plan")
        assert "We ship on Monday." in doc.text
        assert doc.extra_info["source"] == "https://linear.app/acme/document/launch-plan-d1"
        assert doc.extra_info["file_path"] == "Acme/Documents/Launch plan.md"
        assert session.called("list_documents") == [{"projectId": "project-1", "limit": 100}]

    def test_a_listed_document_with_its_content_is_not_read_again(self):
        session = FakeLinear({
            "list_issues": lambda args: [],
            "list_documents": lambda args: [{"id": "d1", "title": "Notes", "content": "All here."}],
        })
        [doc] = _collect(session, projects=["project-1"], include_documents=True)
        assert "All here." in doc.text
        assert session.called("get_document") == []

    def test_documents_with_one_title_stay_two_files(self):
        session = FakeLinear({
            "list_issues": lambda args: [],
            "list_documents": lambda args: [
                {"id": "d1aaaaaaaa", "title": "Notes", "content": "One."},
                {"id": "d2bbbbbbbb", "title": "Notes", "content": "Two."},
            ],
        })
        docs = _collect(session, projects=[{"id": "p1", "name": "Acme"}], include_documents=True)
        assert [d.extra_info["file_path"] for d in docs] == [
            "Acme/Documents/Notes.md", "Acme/Documents/Notes (d2bbbbbb).md",
        ]

    def test_documents_are_left_out_when_not_wanted(self):
        session = FakeLinear({"list_issues": lambda args: []})
        assert _collect(session, projects=["project-1"]) == []
        assert session.called("list_documents") == []


class TestSelection:
    def test_ids_or_records_are_kept_once(self):
        selection = linear.normalize_selection({
            "teams": ["t1", {"id": "t1", "key": "ENG", "name": "Engineering"}, {"id": "t2"}, "", None],
            "projects": [{"id": "p1", "name": "Acme"}],
            "include_comments": "false",
            "include_documents": True,
            "unrelated": "dropped",
        })
        assert selection == {
            "teams": [{"id": "t1", "key": "ENG", "name": "Engineering"}, {"id": "t2", "key": "", "name": ""}],
            "projects": [{"id": "p1", "name": "Acme"}],
            "include_comments": False,
            "include_documents": True,
        }

    def test_comments_are_on_by_default(self):
        assert linear.normalize_selection({"teams": ["t1"]})["include_comments"] is True

    def test_something_must_be_picked(self):
        with pytest.raises(ValueError):
            linear.normalize_selection({"teams": [], "projects": []})

    def test_a_json_string_is_read(self):
        assert linear.normalize_selection('{"teams": ["t1"]}')["teams"] == [{"id": "t1", "key": "", "name": ""}]

    def test_default_name_lists_what_was_picked(self):
        selection = linear.normalize_selection({
            "teams": [{"id": "t1", "name": "Engineering"}], "projects": [{"id": "p1", "name": "Acme"}],
        })
        assert linear.selection_name(selection) == "Linear · Engineering, Acme"
        assert linear.selection_name(linear.normalize_selection({"teams": ["t1"]})) == "Linear"


class TestLoadData:
    def test_reads_with_the_sources_connection(self):
        connection = {"id": "c1", "user_id": "alice", "server_url": "https://mcp.linear.app"}
        loader = LinearLoader()
        with patch("docsgpt.parser.remote.linear_loader._connection", return_value=connection) as load, \
                patch("docsgpt.parser.remote.linear_loader.run_connection_session",
                      return_value=["doc"]) as run:
            result = loader.load_data({"teams": ["t1"], "connection_id": "c1"})
        assert result == ["doc"]
        load.assert_called_once_with("c1")
        assert run.call_args.args[:2] == (connection, "https://mcp.linear.app/mcp")

    def test_needs_a_connection(self):
        with pytest.raises(ValueError):
            LinearLoader().load_data({"teams": ["t1"]})
