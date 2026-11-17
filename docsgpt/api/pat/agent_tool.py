"""An API tool, made from a new personal access token, for agents to work in this account.

The tool's actions are the endpoints an agent can drive with plain JSON (or
form) requests: reading and changing agents, sources, prompts, tools,
workflows, schedules and conversations, and reading analytics and logs. Only
the ones the token may call are included: its scopes allow them and its
resource filter does not close them (see ``RULES``). Every action sends the
token as its ``Authorization`` header, stored sealed like any API tool secret.

A token route that is not an action is listed in ``LEFT_OUT`` with the reason;
``tests/api/test_pat_routes.py`` fails when a route in ``RULES`` is in neither,
so a new endpoint is given to agents, or kept from them, on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from docsgpt.api.pat.rules import RULES
from docsgpt.api.pat.tokens import expand_scopes

JSON_BODY = "application/json"
FORM_BODY = "application/x-www-form-urlencoded"


def _param(description: str, *, type_: str = "string", required: bool = False, items: Optional[str] = None) -> dict:
    spec: dict[str, Any] = {
        "type": type_,
        "description": description,
        "value": "",
        "filled_by_llm": True,
        "required": required,
    }
    if type_ == "array":
        spec["items"] = {"type": items or "string"}
    return spec


def _req(description: str, *, type_: str = "string", items: Optional[str] = None) -> dict:
    return _param(description, type_=type_, required=True, items=items)


def _int(description: str) -> dict:
    return _param(description, type_="integer")


def _bool(description: str) -> dict:
    return _param(description, type_="boolean")


def _obj(description: str, *, required: bool = False) -> dict:
    return _param(description, type_="object", required=required)


def _list(description: str, *, of: str = "string", required: bool = False) -> dict:
    return _param(description, type_="array", required=required, items=of)


def _fixed(value: str) -> dict:
    """A body value the route wants and the model has no say in."""
    return {"type": "string", "description": "Fixed.", "value": value, "filled_by_llm": False, "required": True}


@dataclass(frozen=True)
class Action:
    """One endpoint offered to agents.

    Attributes:
        name: The action name the model calls.
        method: HTTP method.
        path: The Flask rule, as it is keyed in ``RULES``; each ``<id>`` in it
            is a required entry of ``query`` and is filled into the URL.
        description: What the action does, for the model.
        query: Query (and path) parameters.
        body: Body parameters.
        content_type: How the body is sent.
        active: Whether the action starts switched on. Deletes, and calls that
            run another agent, start off; the owner turns them on in the tool.
    """

    name: str
    method: str
    path: str
    description: str
    query: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    content_type: str = JSON_BODY
    active: bool = True


_AGENT_ID = "The agent's id, from list_agents."
_AGENT_FILTER = "The agent's id, from list_agents. Leave empty for the whole account."
_SOURCE_ID = "The source's id, from list_sources."
_SCHEDULE_ID = "The schedule's id, from list_schedules."
_PERIOD = "One of last_hour, last_24_hour, last_7_days, last_15_days, last_30_days."
_SYNC = "How often to re-fetch: never, daily, weekly or monthly."
_WEBSITE_ENTRIES = (
    "What to fetch, each {url, mode: page|site, max_pages, path_prefix, include_subdomains, "
    "discovery: auto|sitemap|links, sitemap_url}; only url and mode are needed."
)
_NODES = "The workflow's nodes, in the shape get_workflow returns."
_EDGES = "The workflow's edges, in the shape get_workflow returns."
_PERIOD_BODY = {"api_key_id": _param(_AGENT_FILTER), "filter_option": _param(_PERIOD)}


def _agent_fields(*, creating: bool) -> dict:
    need = _req if creating else _param
    return {
        "name": need("Name of the agent."),
        "description": _param("What the agent is for."),
        "status": _param(
            "draft (the default) or published. A published agent gets an API key and needs a description, "
            "chunks, retriever and prompt_id (a workflow agent needs its workflow instead)."
        ),
        "agent_type": _param("classic (the default), react or workflow."),
        "prompt_id": _param("A prompt id from list_prompts, or a preset: default, creative or strict."),
        "sources": _list("Ids of the sources the agent answers from, from list_sources."),
        "tools": _list("Ids of the tools the agent may use, from list_tools."),
        "chunks": _int("How many retrieved chunks each answer gets."),
        "retriever": _param("Retriever id; leave empty for the default."),
        "default_model_id": _param("Model id from list_models the agent answers with."),
        "models": _list("Model ids from list_models a user may pick for this agent."),
        "starters": _list("Up to 4 questions a new chat with the agent offers."),
        "folder_id": _param("Folder to keep the agent in, from list_agent_folders."),
        "json_schema": _obj("JSON schema every answer must follow."),
        "workflow": _param("Workflow id, for an agent of type workflow."),
        "limited_token_mode": _bool("Whether the token limit applies."),
        "token_limit": _int("Token limit while limited_token_mode is on."),
        "limited_request_mode": _bool("Whether the request limit applies."),
        "request_limit": _int("Request limit while limited_request_mode is on."),
        "allow_system_prompt_override": _bool("Let API callers replace the system prompt."),
    }


def _schedule_fields(*, creating: bool) -> dict:
    need = _req if creating else _param
    out = {
        "instruction": need("What the agent is told to do on each run."),
        "name": _param("Name of the schedule."),
        "cron": _param("Five-field cron expression; needed for a recurring schedule."),
        "timezone": _param("IANA timezone the cron is read in, e.g. Europe/London. Default UTC."),
        "end_at": _param("ISO 8601 moment after which a recurring schedule stops."),
        "model_id": _param("Model id from list_models the runs use."),
        "token_budget": _int("Most tokens one run may spend."),
        "tool_allowlist": _list("Ids of the only tools the runs may use."),
    }
    if creating:
        out["trigger_type"] = _param("recurring (the default) or once.")
        out["run_at"] = _param("ISO 8601 moment of the run; needed when trigger_type is once.")
    return out


#: Every action the tool can carry, in the order an owner reads them.
CATALOG: tuple[Action, ...] = (
    # --- The account ---
    Action("get_account", "GET", "/api/user/me", "Who this token acts as: user id, roles, email and name."),
    Action("get_quota", "GET", "/api/user/quota", "The account's usage limits: tokens and cost used, and when each resets."),
    Action("list_models", "GET", "/api/models", "List the models this account can use, with their ids and capabilities."),
    Action("list_custom_models", "GET", "/api/user/models", "List the custom models this account registered."),
    Action(
        "get_custom_model",
        "GET",
        "/api/user/models/<string:model_id>",
        "Read one custom model (its API key is never returned).",
        {"model_id": _req("The custom model's id, from list_custom_models.")},
    ),
    # --- Agents ---
    Action("list_agents", "GET", "/api/get_agents", "List the agents of this account with their ids and names."),
    Action("get_agent", "GET", "/api/get_agent", "Read one agent: its prompt, sources, tools, model and limits.",
           {"id": _req(_AGENT_ID)}),
    Action("list_shared_agents", "GET", "/api/shared_agents", "List the agents other people shared with this account."),
    Action("export_agent", "GET", "/api/export_agent", "Export an agent's definition as YAML.", {"id": _req(_AGENT_ID)}),
    Action(
        "create_agent",
        "POST",
        "/api/create_agent",
        "Create an agent. Returns its id, and its API key once published.",
        {},
        _agent_fields(creating=True),
    ),
    Action(
        "update_agent",
        "PUT",
        "/api/update_agent/<string:agent_id>",
        "Change an agent. Send only the fields to change.",
        {"agent_id": _req(_AGENT_ID)},
        _agent_fields(creating=False),
    ),
    Action("delete_agent", "DELETE", "/api/delete_agent", "Delete an agent for good.", {"id": _req(_AGENT_ID)},
           active=False),
    Action(
        "share_agent",
        "PUT",
        "/api/share_agent",
        "Turn an agent's public share link on or off. Anyone with the link can chat with a shared agent.",
        {},
        {
            "id": _req(_AGENT_ID),
            "shared": _req("true to share, false to stop sharing.", type_="boolean"),
            "username": _param("Name shown as the agent's author."),
        },
    ),
    Action("adopt_agent", "POST", "/api/adopt_agent", "Make a copy of a shared agent that this account owns.",
           {"id": _req("The shared agent's id, from list_shared_agents.")}),
    Action("remove_shared_agent", "DELETE", "/api/remove_shared_agent",
           "Drop a shared agent from this account's list. The agent itself is untouched.",
           {"id": _req("The shared agent's id, from list_shared_agents.")}),
    Action(
        "regenerate_agent_key",
        "POST",
        "/api/regenerate_agent_key/<string:agent_id>",
        "Replace an agent's API key. The old key stops working at once and the new one is returned once, "
        "so everything that used the old key must be given the new one.",
        {"agent_id": _req(_AGENT_ID)},
    ),
    Action("get_agent_webhook", "GET", "/api/agent_webhook",
           "Get the incoming webhook URL of an agent. The URL is a secret: whoever has it can run the agent.",
           {"id": _req(_AGENT_ID)}),
    Action("list_agent_folders", "GET", "/api/agents/folders/", "List the folders agents are kept in."),
    Action("get_agent_folder", "GET", "/api/agents/folders/<string:folder_id>", "Read one folder and the agents in it.",
           {"folder_id": _req("The folder's id, from list_agent_folders.")}),
    Action("create_agent_folder", "POST", "/api/agents/folders/", "Create a folder for agents.", {},
           {"name": _req("Name of the folder."), "parent_id": _param("Id of the folder to put it in.")}),
    Action(
        "update_agent_folder",
        "PUT",
        "/api/agents/folders/<string:folder_id>",
        "Rename, describe or move a folder. Send only the fields to change.",
        {"folder_id": _req("The folder's id, from list_agent_folders.")},
        {
            "name": _param("New name."),
            "description": _param("New description."),
            "parent_id": _param("Id of the folder to move it into."),
        },
    ),
    Action("delete_agent_folder", "DELETE", "/api/agents/folders/<string:folder_id>",
           "Delete a folder. Its agents are kept, outside any folder.",
           {"folder_id": _req("The folder's id, from list_agent_folders.")}, active=False),
    Action("move_agent_to_folder", "POST", "/api/agents/folders/move_agent", "Move one agent into a folder, or out of its folder.",
           {}, {"agent_id": _req(_AGENT_ID), "folder_id": _param("Target folder id. Leave out to take it out of its folder.")}),
    Action("move_agents_to_folder", "POST", "/api/agents/folders/bulk_move", "Move several agents into a folder.", {},
           {"agent_ids": _list("Ids of the agents to move.", required=True), "folder_id": _param("Target folder id.")}),
    Action(
        "list_guardrail_events",
        "GET",
        "/api/guardrails/events",
        "List the guardrail decisions recorded for an agent: what was blocked, redacted or flagged.",
        {
            "agent_id": _req(_AGENT_ID),
            "days": _int("Only the last this many days, 1 to 365."),
            "check": _param("Only this check, by its exact name."),
            "outcome": _param("One of block, redact, flag, not_evaluated."),
            "limit": _int("Most rows to return (default 100)."),
            "offset": _int("Rows to skip."),
        },
    ),
    Action("get_guardrail_summary", "GET", "/api/guardrails/summary", "Count guardrail decisions per check and outcome.",
           {"agent_id": _param(_AGENT_FILTER), "days": _int("Window in days (default 30).")}),
    # --- Schedules ---
    Action("list_schedules", "GET", "/api/schedules", "List every schedule of this account, with its agent, cadence and next run."),
    Action("list_agent_schedules", "GET", "/api/agents/<string:agent_id>/schedules", "List the schedules of one agent.",
           {"agent_id": _req(_AGENT_ID)}),
    Action("get_agent_schedule_stats", "GET", "/api/agents/<string:agent_id>/schedules/stats",
           "Count an agent's scheduled runs, failures and tokens over a recent window.",
           {"agent_id": _req(_AGENT_ID), "days": _int("Window in days (default 30).")}),
    Action("get_schedule", "GET", "/api/schedules/<string:schedule_id>", "Read one schedule.",
           {"schedule_id": _req(_SCHEDULE_ID)}),
    Action("list_schedule_runs", "GET", "/api/schedules/<string:schedule_id>/runs", "List the past runs of a schedule, newest first.",
           {"schedule_id": _req(_SCHEDULE_ID), "limit": _int("Page size (default 50)."), "offset": _int("Rows to skip.")}),
    Action("get_schedule_run", "GET", "/api/schedules/<string:schedule_id>/runs/<string:run_id>",
           "Read one scheduled run in full: its output or its error.",
           {"schedule_id": _req(_SCHEDULE_ID), "run_id": _req("The run's id, from list_schedule_runs.")}),
    Action(
        "create_schedule",
        "POST",
        "/api/agents/<string:agent_id>/schedules",
        "Schedule an agent to run an instruction, on a cron or once at a set time.",
        {"agent_id": _req(_AGENT_ID)},
        _schedule_fields(creating=True),
    ),
    Action(
        "update_schedule",
        "PUT",
        "/api/schedules/<string:schedule_id>",
        "Change a schedule. Send only the fields to change.",
        {"schedule_id": _req(_SCHEDULE_ID)},
        _schedule_fields(creating=False),
    ),
    Action("pause_or_resume_schedule", "PATCH", "/api/schedules/<string:schedule_id>", "Pause a schedule, or resume a paused one.",
           {"schedule_id": _req(_SCHEDULE_ID)}, {"action": _req("pause or resume.")}),
    Action("run_schedule_now", "POST", "/api/schedules/<string:schedule_id>/run", "Run a schedule right away, outside its cadence.",
           {"schedule_id": _req(_SCHEDULE_ID)}),
    Action("delete_schedule", "DELETE", "/api/schedules/<string:schedule_id>", "Cancel and delete a schedule.",
           {"schedule_id": _req(_SCHEDULE_ID)}, active=False),
    # --- Sources ---
    Action("list_sources", "GET", "/api/sources", "List the sources of this account with their ids and names."),
    Action(
        "search_sources_list",
        "GET",
        "/api/sources/paginated",
        "Page through the sources with sorting and filters; each row names the agents that use it.",
        {
            "page": _int("Page number, from 1."),
            "rows": _int("Rows per page."),
            "sort": _param("date (the default), name, tokens, type, created_at or updated_at."),
            "order": _param("asc or desc (the default)."),
            "search": _param("Text the name must contain."),
            "kind": _param("all (the default), files, websites, synced, wikis or shared."),
            "usage": _param("all (the default), in_use or unused."),
        },
    ),
    Action("get_source_files", "GET", "/api/directory_structure", "Read the file tree of a source.", {"id": _req(_SOURCE_ID)}),
    Action(
        "list_chunks",
        "GET",
        "/api/get_chunks",
        "Page through the chunks of a source, optionally one file's or those matching a search.",
        {
            "id": _req(_SOURCE_ID),
            "page": _int("Page number, from 1."),
            "per_page": _int("Chunks per page."),
            "path": _param("Only chunks of this file, by its path in the source."),
            "search": _param("Text the chunk's title or content must contain."),
            "injection": _param("flagged: only chunks suspected of prompt injection."),
        },
    ),
    Action("get_cited_chunk", "GET", "/api/sources/<string:source_id>/chunk", "Read the chunk behind a citation.",
           {"source_id": _req(_SOURCE_ID), "chunk_key": _param("The citation's chunk_key."),
            "excerpt": _param("The start of the cited passage, searched when the key finds nothing.")}),
    Action(
        "search_source",
        "POST",
        "/api/sources/<string:source_id>/search",
        "Search one source and return the chunks retrieval finds for a query.",
        {"source_id": _req(_SOURCE_ID)},
        {"query": _req("What to search for."), "retrieval": _obj("Retrieval settings to try instead of the saved ones.")},
    ),
    Action("get_task_status", "GET", "/api/task_status",
           "Check a background task (an ingest, sync or conversion) by the task_id the call that started it returned.",
           {"task_id": _req("The task id.")}),
    Action(
        "ingest_remote_source",
        "POST",
        "/api/remote",
        "Create a source from a remote location and start ingesting it. Returns a task_id for get_task_status.",
        {},
        {
            "user": _fixed("local"),
            "name": _req("Name of the new source."),
            "source": _req("The loader: website, crawler, url, sitemap or github."),
            "data": _req(
                "The loader's config as a JSON string. For website: {\"entries\": [{\"url\": \"https://…\", "
                "\"mode\": \"site\"}]} (mode page fetches one page). For crawler, url and sitemap: {\"url\": \"https://…\"}. "
                "For github: {\"repo_url\": \"https://github.com/owner/repo\"}."
            ),
            "sync_frequency": _param(_SYNC),
        },
        content_type=FORM_BODY,
    ),
    Action("create_wiki_source", "POST", "/api/sources/wiki", "Create a wiki source, whose pages are written rather than ingested.", {},
           {"name": _req("Name of the wiki."), "initial_content": _param("Markdown for its first page, /index.md.")}),
    Action("set_source_sync", "POST", "/api/manage_sync", "Set how often a source is re-fetched.", {},
           {"source_id": _req(_SOURCE_ID), "sync_frequency": _req(_SYNC)}),
    Action("sync_source", "POST", "/api/sync_source", "Re-fetch a source now. Returns a task_id.", {}, {"source_id": _req(_SOURCE_ID)}),
    Action("reingest_source", "POST", "/api/sources/reingest",
           "Run ingestion for a source again, to recover a stalled one or apply a chunking change.", {},
           {"source_id": _req(_SOURCE_ID)}),
    Action(
        "update_source_config",
        "PATCH",
        "/api/sources/<string:source_id>/config",
        "Change a source's chunking or retrieval settings. Send only the sections to change.",
        {"source_id": _req(_SOURCE_ID)},
        {
            "chunking": _obj("Chunking settings; applied by reingest_source."),
            "retrieval": _obj("Query-time retrieval settings."),
            "kind": _param("The source's kind."),
        },
    ),
    Action("delete_source", "GET", "/api/delete_old", "Delete a source for good: its index, files and row.",
           {"source_id": _req(_SOURCE_ID)}, active=False),
    Action("get_website_source", "GET", "/api/website", "Read a Website source's entries, skips, sync schedule and last ingest report.",
           {"id": _req(_SOURCE_ID)}),
    Action(
        "update_website_source",
        "POST",
        "/api/website",
        "Save what a Website source fetches and how often. Applies at the next sync.",
        {},
        {
            "source_id": _req(_SOURCE_ID),
            "entries": _list(_WEBSITE_ENTRIES, of="object", required=True),
            "skip": _list("Pages (a URL) or sections (https://host/path/*) to leave out. [] clears the list."),
            "keep_links": _bool("Keep the URL of links inside sentences in page text."),
            "sync_frequency": _param(_SYNC),
        },
    ),
    Action("add_website_pages", "POST", "/api/website/pages", "Add pages or sites to a Website source and fetch them now.", {},
           {"source_id": _req(_SOURCE_ID), "entries": _list(_WEBSITE_ENTRIES, of="object", required=True)}),
    Action("refresh_website_page", "POST", "/api/website/refresh", "Fetch one page of a Website source again.", {},
           {"source_id": _req(_SOURCE_ID), "file_path": _req("The page's path in the source's file tree."),
            "url": _param("The page's address, as the file tree shows it.")}),
    Action("remove_website_pages", "POST", "/api/website/remove", "Remove pages or a folder from a Website source.", {},
           {"source_id": _req(_SOURCE_ID), "file_paths": _list("File-tree paths of the pages to remove."),
            "directory_path": _param("File-tree path of a folder to remove.")}),
    Action("add_chunk", "POST", "/api/add_chunk", "Add a chunk of text to a source.", {},
           {"id": _req(_SOURCE_ID), "text": _req("The chunk's text."), "metadata": _obj("Metadata to store with it, e.g. {\"title\": …}.")}),
    Action("update_chunk", "PUT", "/api/update_chunk", "Change a chunk's text or metadata.", {},
           {"id": _req(_SOURCE_ID), "chunk_id": _req("The chunk's id, from list_chunks."), "text": _param("New text."),
            "metadata": _obj("New metadata.")}),
    Action("delete_chunk", "DELETE", "/api/delete_chunk", "Delete one chunk from a source.",
           {"id": _req(_SOURCE_ID), "chunk_id": _req("The chunk's id, from list_chunks.")}, active=False),
    Action("review_flagged_chunk", "POST", "/api/sources/<string:source_id>/injection_review",
           "Mark a chunk flagged for prompt injection as safe, or undo that.",
           {"source_id": _req(_SOURCE_ID)},
           {"content_hash": _req("The chunk's injection.content_hash, from list_chunks."), "decision": _req("allow or clear.")}),
    Action("list_wiki_pages", "GET", "/api/sources/<string:source_id>/wiki/pages", "List the pages of a wiki source.",
           {"source_id": _req(_SOURCE_ID)}),
    Action("get_wiki_page", "GET", "/api/sources/<string:source_id>/wiki/page", "Read one wiki page and its version.",
           {"source_id": _req(_SOURCE_ID), "path": _req("The page's path, e.g. /index.md.")}),
    Action("get_wiki_settings", "GET", "/api/sources/<string:source_id>/wiki/settings", "Read a wiki's settings.",
           {"source_id": _req(_SOURCE_ID)}),
    Action(
        "write_wiki_page",
        "PUT",
        "/api/sources/<string:source_id>/wiki/page",
        "Create a wiki page, or replace one's content.",
        {"source_id": _req(_SOURCE_ID)},
        {
            "path": _req("The page's path, e.g. /guides/setup.md."),
            "content": _req("The page as Markdown."),
            "expected_version": _int("The version from get_wiki_page; the write is refused if the page changed since."),
        },
    ),
    Action("convert_source_to_wiki", "POST", "/api/sources/<string:source_id>/wiki/convert",
           "Turn an ingested source into a wiki. Returns a task_id when it has files to convert.",
           {"source_id": _req(_SOURCE_ID)}),
    Action("enable_source_graph", "POST", "/api/sources/<string:source_id>/graphrag/enable",
           "Switch a source to graph retrieval and start building its knowledge graph.", {"source_id": _req(_SOURCE_ID)}),
    Action("get_source_graph", "GET", "/api/sources/<string:source_id>/graph",
           "Read an overview of a source's knowledge graph: its most connected nodes and the edges among them.",
           {"source_id": _req(_SOURCE_ID)}),
    Action("list_source_graph_nodes", "GET", "/api/sources/<string:source_id>/graph/nodes",
           "List a page of a source's knowledge-graph nodes, most connected first.", {"source_id": _req(_SOURCE_ID)}),
    Action("get_source_graph_node", "GET", "/api/sources/<string:source_id>/graph/node/<string:node_id>",
           "Read one knowledge-graph node: its description and the chunks it links to.",
           {"source_id": _req(_SOURCE_ID), "node_id": _req("The node's id, from get_source_graph.")}),
    # --- Prompts ---
    Action("list_prompts", "GET", "/api/get_prompts", "List the prompts of this account with their ids and names."),
    Action("get_prompt", "GET", "/api/get_single_prompt", "Read one prompt's content.",
           {"id": _req("The prompt's id, from list_prompts.")}),
    Action("create_prompt", "POST", "/api/create_prompt", "Create a prompt.", {},
           {"name": _req("Name of the prompt."), "content": _req("The prompt text.")}),
    Action("update_prompt", "POST", "/api/update_prompt", "Replace a prompt's name and content.", {},
           {"id": _req("The prompt's id, from list_prompts."), "name": _req("Its name."), "content": _req("Its text.")}),
    Action("check_prompt", "POST", "/api/check_prompt",
           "Check a prompt's text without a model: blanks left in, lines DocsGPT already adds, and a template "
           "that doesn't parse, runs tool variables, or lacks the Boundaries section or citation rules.", {},
           {"content": _req("The prompt text to check.")}),
    Action("delete_prompt", "POST", "/api/delete_prompt", "Delete a prompt.", {},
           {"id": _req("The prompt's id, from list_prompts.")}, active=False),
    # --- Tools ---
    Action("list_tool_types", "GET", "/api/available_tools", "List the kinds of tool that can be added, with the config each needs."),
    Action("list_tools", "GET", "/api/get_tools",
           "List the tools set up in this account with their ids and actions. Stored credentials are never returned."),
    Action(
        "create_tool",
        "POST",
        "/api/create_tool",
        "Add a tool of one of the kinds list_tool_types returns.",
        {},
        {
            "name": _req("The kind of tool: a name from list_tool_types."),
            "displayName": _req("Name shown for the tool."),
            "description": _req("What the tool does."),
            "config": _obj("The config that kind needs, as list_tool_types describes it.", required=True),
            "status": _req("Whether the tool is switched on.", type_="boolean"),
            "customName": _param("A name of your own for it."),
        },
    ),
    Action(
        "update_tool",
        "POST",
        "/api/update_tool",
        "Change a tool: its names, config, actions or whether it is on. Send only the fields to change. "
        "A credential the tool already stores is kept unless a new one is sent, and never moves to another server. "
        "A tool that holds an access token, like this one, cannot be changed this way.",
        {},
        {
            "id": _req("The tool's id, from list_tools."),
            "displayName": _param("Name shown for the tool."),
            "customName": _param("A name of your own for it."),
            "description": _param("What the tool does."),
            "config": _obj("New config."),
            "actions": _list("The tool's actions, in the shape list_tools returns, with those to change edited.", of="object"),
            "status": _bool("Whether the tool is switched on."),
        },
    ),
    Action("delete_tool", "POST", "/api/delete_tool", "Delete a tool.", {}, {"id": _req("The tool's id, from list_tools.")},
           active=False),
    Action(
        "test_mcp_server",
        "POST",
        "/api/mcp_server/test",
        "Check that an MCP server answers with a given config, without saving it.",
        {},
        {
            "config": _obj("{server_url, auth_type: none|bearer|api_key|basic, transport_type: auto|sse|http, …}.", required=True),
            "id": _param("A saved MCP tool's id, to test with its stored credentials."),
        },
    ),
    Action(
        "save_mcp_server",
        "POST",
        "/api/mcp_server/save",
        "Add an MCP server, or update a saved one, and load the tools it offers. "
        "A server that signs in with OAuth has to be connected in Settings by a person.",
        {},
        {
            "displayName": _req("Name shown for the server."),
            "config": _obj("{server_url, auth_type: none|bearer|api_key|basic, transport_type: auto|sse|http, …}.", required=True),
            "id": _param("The tool's id, to update a saved server."),
            "status": _bool("Whether the server's tools are switched on."),
        },
    ),
    # --- Workflows ---
    Action("get_workflow", "GET", "/api/workflows/<string:workflow_id>", "Read a workflow with its nodes and edges.",
           {"workflow_id": _req("The workflow's id; a workflow agent names it as workflow in get_agent.")}),
    Action(
        "create_workflow",
        "POST",
        "/api/workflows",
        "Create a workflow from nodes and edges.",
        {},
        {
            "name": _req("Name of the workflow."),
            "description": _param("What it does."),
            "nodes": _list(_NODES, of="object", required=True),
            "edges": _list(_EDGES, of="object", required=True),
            "retry_defaults": _obj("Retry settings its nodes fall back to."),
        },
    ),
    Action(
        "update_workflow",
        "PUT",
        "/api/workflows/<string:workflow_id>",
        "Replace a workflow's name, nodes and edges. Send the whole graph: what is left out is removed.",
        {"workflow_id": _req("The workflow's id.")},
        {
            "name": _req("Name of the workflow."),
            "description": _param("What it does."),
            "nodes": _list(_NODES, of="object", required=True),
            "edges": _list(_EDGES, of="object", required=True),
            "retry_defaults": _obj("Retry settings its nodes fall back to."),
        },
    ),
    Action("delete_workflow", "DELETE", "/api/workflows/<string:workflow_id>", "Delete a workflow and its graph.",
           {"workflow_id": _req("The workflow's id.")}, active=False),
    Action(
        "list_workflow_runs",
        "GET",
        "/api/workflow_runs",
        "List the workflow runs this account started, newest first.",
        {
            "agent_id": _param("Only runs of this agent."),
            "since": _param("Only runs started at or after this ISO 8601 moment."),
            "status": _param("One of pending, running, completed, failed."),
            "limit": _int("Most runs to return, 1 to 100 (default 20)."),
        },
    ),
    Action("get_workflow_run", "GET", "/api/workflow_runs/<string:run_id>", "Read one workflow run: its status and timing, plus extras on request.",
           {"run_id": _req("The run's id, from list_workflow_runs."),
            "include": _param("Comma-separated extras: steps, state, artifacts."),
            "state_key": _param("Return only this key of the final state, in full.")}),
    Action("get_workflow_run_step", "GET", "/api/workflow_runs/<string:run_id>/steps/<int:step_index>",
           "Read one step of a workflow run with its full output and state changes.",
           {"run_id": _req("The run's id."), "step_index": _req("The step's index, from get_workflow_run.", type_="integer")}),
    # --- Artifacts ---
    Action("list_artifacts", "GET", "/api/artifacts", "List the artifacts of a conversation or workflow run, or all of the account's.",
           {"conversation_id": _param("Only this conversation's."), "workflow_run_id": _param("Only this workflow run's.")}),
    Action("get_artifact", "GET", "/api/artifacts/<artifact_id>", "Read an artifact: its metadata, versions and current content.",
           {"artifact_id": _req("The artifact's id, from list_artifacts.")}),
    Action("get_artifact_version", "GET", "/api/artifacts/<artifact_id>/versions/<int:version>", "Read one earlier version of an artifact.",
           {"artifact_id": _req("The artifact's id."), "version": _req("The version number.", type_="integer")}),
    # --- Conversations ---
    Action("list_conversations", "GET", "/api/get_conversations", "List this account's conversations, newest first.",
           {"limit": _int("Most to return, 1 to 100 (default 30)."),
            "before": _param("To page: the date of the last conversation seen (with before_id)."),
            "before_id": _param("To page: the id of the last conversation seen (with before).")}),
    Action("search_conversations", "GET", "/api/search_conversations", "Find conversations by name or message text.",
           {"q": _req("Text to look for."), "limit": _int("Most to return, up to 100 (default 30).")}),
    Action("get_conversation", "GET", "/api/get_single_conversation",
           "Read a whole conversation by its id: every question, answer and rating, and its passthrough values.",
           {"id": _req("The conversation id, from a log row or list_conversations.")}),
    Action("rename_conversation", "POST", "/api/update_conversation_name", "Rename a conversation.", {},
           {"id": _req("The conversation id."), "name": _req("Its new name.")}),
    Action(
        "rate_answer",
        "POST",
        "/api/feedback",
        "Rate one answer of a conversation.",
        {},
        {
            "conversation_id": _req("The conversation id."),
            "question_index": _req("Which turn, counting from 0.", type_="integer"),
            "feedback": _req("like or dislike."),
        },
    ),
    Action("delete_conversation", "POST", "/api/delete_conversation", "Delete one conversation for good.",
           {"id": _req("The conversation id.")}, active=False),
    Action("list_background_jobs", "GET", "/api/background_jobs", "List the background jobs of a conversation, newest first.",
           {"conversation_id": _req("The conversation id.")}),
    Action("get_background_job", "GET", "/api/background_jobs/<string:job_id>", "Read one background job: its state, progress and result preview.",
           {"job_id": _req("The job's id, from list_background_jobs.")}),
    Action("cancel_background_job", "POST", "/api/background_jobs/<string:job_id>/cancel", "Ask a running background job to stop.",
           {"job_id": _req("The job's id, from list_background_jobs.")}),
    Action("list_monitors", "GET", "/api/monitors", "List this account's monitors: what each watches, how often and when it last checked.",
           {"conversation_id": _param("Only this conversation's."), "status": _param("live (active and paused) or all (the default).")}),
    Action("get_monitor", "GET", "/api/monitors/<string:monitor_id>", "Read one monitor.",
           {"monitor_id": _req("The monitor's id, from list_monitors.")}),
    Action("change_monitor", "POST", "/api/monitors/<string:monitor_id>/<string:action>", "Pause, resume or cancel a monitor.",
           {"monitor_id": _req("The monitor's id, from list_monitors."), "action": _req("pause, resume or cancel.")}),
    # --- Analytics and logs ---
    Action(
        "get_logs",
        "POST",
        "/api/get_user_logs",
        "Read the Logs timeline, newest first: each chat turn's question, answer, "
        "conversation_id, passthrough values (who asked) and feedback (like or dislike).",
        {},
        {
            "api_key_id": _param(_AGENT_FILTER),
            "date_from": _param("Only rows at or after this ISO 8601 moment, e.g. 2026-10-17T00:00:00Z."),
            "date_to": _param("Only rows before this ISO 8601 moment."),
            "feedback": _param("like or dislike: only turns rated this way."),
            "event_type": _param("One of chat, schedule, webhook, workflow, system, search, graph."),
            "level": _param("One of info, warning, error."),
            "label": _param("Only turns labelled this way: a topic filter from list_topics, or a label such as docs_gap."),
            "passthrough": _obj("Only turns whose passthrough values match every key, e.g. {\"user_id\": \"42\"}."),
            "search": _param("Text the question must contain."),
            "conversation_id": _param("Only the turns of this conversation."),
            "page": _int("Page number, from 1."),
            "page_size": _int("Rows per page, up to 100."),
        },
    ),
    Action("get_trace", "GET", "/api/traces",
           "Read the execution trace of one answer (retrieval, model calls, tool calls) by its message id.",
           {"message_id": _req("The message id, from a log row."), "api_key_id": _param(_AGENT_FILTER)}),
    Action("get_message_counts", "POST", "/api/get_message_analytics", "Count messages over a period, per hour or day.", {},
           dict(_PERIOD_BODY)),
    Action("get_feedback_counts", "POST", "/api/get_feedback_analytics", "Count likes and dislikes over a period, per hour or day.", {},
           dict(_PERIOD_BODY)),
    Action("get_token_usage", "POST", "/api/get_token_analytics", "Count tokens used over a period, per hour or day.", {},
           {**_PERIOD_BODY, "group_by": _param("Split the series by one of none, model, agent, source.")}),
    Action("get_tool_usage", "POST", "/api/get_tool_analytics", "Count tool calls and their failures over a period.", {},
           dict(_PERIOD_BODY)),
    Action("get_schedule_outcomes", "POST", "/api/get_schedule_analytics", "Count scheduled runs by outcome over a period.", {},
           dict(_PERIOD_BODY)),
    Action("get_conversation_insights", "POST", "/api/get_conversation_insights",
           "Read what the conversations of a period were like: how often answers fell short, users reacted badly, and so on.", {},
           dict(_PERIOD_BODY)),
    Action("get_docs_gaps", "POST", "/api/get_docs_gaps",
           "Find what the docs do not cover: the topics, sources or pages whose questions most often went unanswered.", {},
           {**_PERIOD_BODY, "group_by": _param("One of topic, source, page."), "limit": _int("Most groups to return, 1 to 50.")}),
    Action("list_topics", "GET", "/api/analytics/topics", "List the topics an agent's conversations are about, each with its get_logs label filter.",
           {"agent_id": _req(_AGENT_ID)}),
    # --- Teams ---
    Action("list_teams", "GET", "/api/teams", "List the teams this account belongs to, with its role in each."),
    Action("get_team", "GET", "/api/teams/<string:team_id>", "Read one team with its members.",
           {"team_id": _req("The team's id, from list_teams.")}),
    Action("list_team_members", "GET", "/api/teams/<string:team_id>/members", "List or search the members of a team.",
           {"team_id": _req("The team's id, from list_teams."), "q": _param("Text the member's email or id must contain."),
            "page": _int("Page number, from 1."), "page_size": _int("Rows per page, up to 100.")}),
    Action("list_team_resources", "GET", "/api/teams/<string:team_id>/grants", "List what is shared with a team.",
           {"team_id": _req("The team's id, from list_teams."), "resource_type": _param("Only agent, source, prompt or tool.")}),
    Action("list_resource_shares", "GET", "/api/resource_shares", "List the teams one agent, source, prompt or tool is shared with.",
           {"resource_type": _req("agent, source, prompt or tool."), "resource_id": _req("The resource's id.")}),
    Action("get_resource_sharing_settings", "GET", "/api/resource_settings", "Read the sharing switches of one agent, source, prompt or tool.",
           {"resource_type": _req("agent, source, prompt or tool."), "resource_id": _req("The resource's id.")}),
    # --- Chat ---
    Action(
        "ask_agent",
        "POST",
        "/api/answer",
        "Ask one of the account's agents a question and get its whole answer. The agent runs for real: "
        "it uses its tools and spends tokens. Never ask the agent that is making this call.",
        {},
        {
            "question": _req("The question."),
            "agent_id": _req(_AGENT_ID),
            "conversation_id": _param("Continue this conversation instead of starting one."),
            "model_id": _param("Model id from list_models to answer with."),
            "passthrough": _obj("Values for the agent's prompt template."),
        },
        active=False,
    ),
)

#: Token routes that are not actions, by reason. Every route in ``RULES`` is here or in ``CATALOG``.
LEFT_OUT: dict[str, tuple[tuple[str, str], ...]] = {
    "wipes the whole account's history in one call": (("/api/delete_all_conversations", "GET"),),
    "custom models carry a provider key and a base URL that every chat is sent to": (
        ("/api/user/models", "POST"),
        ("/api/user/models/<string:model_id>", "PATCH"),
        ("/api/user/models/<string:model_id>", "DELETE"),
        ("/api/user/models/test", "POST"),
        ("/api/user/models/<string:model_id>/test", "POST"),
    ),
    "needs a file upload, a stream, or an agent API key the tool does not have": (
        ("/api/upload", "POST"),
        ("/api/store_attachment", "POST"),
        ("/api/manage_source_files", "POST"),
        ("/api/sources/from_attachments", "POST"),
        ("/api/import_agent/plan", "POST"),
        ("/api/import_agent", "POST"),
        ("/api/parse_spec", "POST"),
        ("/stream", "POST"),
        ("/api/messages/<string:message_id>/tail", "GET"),
        ("/api/search", "POST"),
        ("/api/agent_starters", "POST"),
    ),
    "serves the app's screens, not a task": (
        ("/api/health", "GET"),
        ("/api/config", "GET"),
        ("/api/pinned_agents", "GET"),
        ("/api/pin_agent", "POST"),
        ("/api/template_agents", "GET"),
        ("/api/guardrails/catalog", "GET"),
        ("/api/agents/defaults", "GET"),
        ("/api/sources/defaults", "GET"),
        ("/api/analytics/topic_folders", "GET"),
        ("/api/user/preferences", "GET"),
        ("/api/user/preferences", "PUT"),
        ("/api/mcp_server/oauth_cancel", "POST"),
    ),
    "covered by update_tool": (
        ("/api/update_tool_config", "POST"),
        ("/api/update_tool_actions", "POST"),
        ("/api/update_tool_status", "POST"),
    ),
}

_PATH_ID = re.compile(r"<(?:\w+:)?(\w+)>")


def _token_may_call(method: str, path: str, scopes: list[str], resource_filter: dict) -> bool:
    rule = RULES.get((path, method))
    if rule is None:
        return False
    if rule.scopes and not set(rule.scopes) & expand_scopes(scopes):
        return False
    return not set(rule.blocked_by) & set(resource_filter or {})


def build_actions(base_url: str, token: str, scopes: list[str], resource_filter: Optional[dict]) -> dict[str, Any]:
    """The API tool ``actions`` for a token: the catalog entries it may call.

    Args:
        base_url: Where the DocsGPT API is reached, e.g. ``https://docs.example.com``.
        token: The token's plaintext secret, sent as a Bearer header.
        scopes: The token's scopes.
        resource_filter: The token's resource filter.

    Returns:
        ``{action name: action}`` in the API tool config shape; empty when the
        token can call none of them.
    """
    root = base_url.rstrip("/")
    actions: dict[str, Any] = {}
    for entry in CATALOG:
        if not _token_may_call(entry.method, entry.path, scopes, resource_filter or {}):
            continue
        actions[entry.name] = {
            "name": entry.name,
            # The API tool fills ``{id}`` from the query parameter of that name.
            "url": root + _PATH_ID.sub(r"{\1}", entry.path),
            "method": entry.method,
            "description": entry.description,
            "query_params": {"type": "object", "properties": {k: dict(v) for k, v in entry.query.items()}},
            "headers": {
                "type": "object",
                "properties": {
                    "Authorization": {
                        "type": "string",
                        "description": "DocsGPT personal access token",
                        "value": f"Bearer {token}",
                        "filled_by_llm": False,
                        "required": True,
                    }
                },
            },
            "body": {"type": "object", "properties": {k: dict(v) for k, v in entry.body.items()}},
            "body_content_type": entry.content_type,
            "active": entry.active,
        }
    return actions
