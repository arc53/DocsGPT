"""Website source routes: its settings, and adding, refreshing and removing pages.

A Website source stores what it fetches (pages and sites) and what a site's
crawl must skip; see ``parser/remote/website_loader.py``. These routes edit
that list, so every change survives a sync. A page found by a site's crawl is
added to ``skip`` when it is removed, so the next sync leaves it out. The
chunks and tree entries change in ``website_pages_worker``: removed pages are
deleted there, and added pages are fetched and appended. Sources made by the older url/crawler/sitemap
loaders read as Website sources and are converted on their first save; their
tree leaves carry no address, so a removal reads each one's from its chunks.
"""

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from flask import Response, current_app, jsonify, make_response, request
from flask_restx import fields, Resource

from docsgpt.api import api
from docsgpt.api.user.base import get_vector_store
from docsgpt.api.user.resource_access import AccessDenied
from docsgpt.api.user.sources.access import denied_response, load_source
from docsgpt.api.user.sources.routes import _WIKI_NO_SYNC, _is_wiki, _with_scheme, sources_ns
from docsgpt.api.user.sources.upload import _pages_once
from docsgpt.api.user.tasks import sync_source, website_pages
from docsgpt.core.settings import settings
from docsgpt.parser.remote import website_loader
from docsgpt.parser.remote.page_content import MAX_PATH_SEGMENTS
from docsgpt.parser.remote.website_loader import SiteScope, is_web_address, page_key, parse_website_config
from docsgpt.parser.remote.website_tree import (
    config_from_legacy,
    count_pages,
    folder_skip_rule,
    pages_under,
    web_pages,
)
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.vectorstore.vector_creator import VectorCreator

_SYNC_FREQUENCIES = ("never", "daily", "weekly", "monthly")

#: How many tree paths one removal may name; a folder is one path however many pages it holds.
MAX_REMOVE_PATHS = 1000

# C0 controls and DEL: no address, path or skip rule carries them, and a NUL can't be stored.
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


def _error(message: str, status: int = 400, code: Optional[str] = None, **details: Any) -> Response:
    """A failed response; ``code`` names an error the UI words itself, with ``details`` for its message."""
    body = {"success": False, "error": message, **details}
    if code:
        body["code"] = code
    return make_response(jsonify(body), status)


#: The ``already_listed`` wording for an add that names only what the source already lists.
ALREADY_LISTED = "These pages and sites are already in this source."
#: The ``queue_failed`` wording for a change saved before its task couldn't be queued.
QUEUE_FAILED_SAVED = "The change was saved, but its task couldn't be queued; the next sync picks it up."
#: The ``queue_failed`` wording for a refresh, which saves nothing first.
QUEUE_FAILED_REFRESH = "The refresh couldn't be queued; try again, or sync the source."


def _queue_failed(message: str, err: Exception) -> Response:
    """The 500 for a task the broker wouldn't take (``code: queue_failed``), logged.

    Args:
        message: What happened to the change, for the UI.
        err: What queueing raised.
    """
    current_app.logger.error(f"Could not queue a website task: {err}", exc_info=True)
    return _error(message, 500, code="queue_failed")


def _config_error(err: ValueError) -> Response:
    """The 400 for a config ``parse_website_config`` refused.

    The parser's typed error carries a ``code`` (``site_limit``,
    ``invalid_address``, ...) and ``details`` for its wording; any other
    ``ValueError`` is ``invalid_config``.
    """
    details = getattr(err, "details", None) or {}
    details = {k: v for k, v in details.items() if k not in ("message", "status", "code", "success", "error")}
    return _error(str(err), code=getattr(err, "code", None) or "invalid_config", **details)


def _is_str_list(value: Any) -> bool:
    """Whether ``value`` is a list of strings."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


# The type each body field of these routes must have, and how a refusal words it.
_FIELD_TYPES: Dict[str, Tuple[Callable[[Any], bool], str]] = {
    "source_id": (lambda value: isinstance(value, str), "a string"),
    "entries": (lambda value: isinstance(value, list), "a list"),
    "skip": (_is_str_list, "a list of strings"),
    "keep_links": (lambda value: isinstance(value, bool), "true or false"),
    "sync_frequency": (lambda value: isinstance(value, str), "a string"),
    "file_paths": (_is_str_list, "a list of strings"),
    "directory_path": (lambda value: isinstance(value, str), "a string"),
    "file_path": (lambda value: isinstance(value, str), "a string"),
    "url": (lambda value: isinstance(value, str), "a string"),
}


def _read_body(required: List[str]) -> Tuple[dict, Optional[Response]]:
    """The request's JSON object, with its required fields present and every known field of the right type.

    A missing or unreadable body reads as ``{}`` (so it is refused for its
    missing fields); a body that isn't an object, a missing field and a field
    of the wrong type are each a 400 with a ``code``. A field sent as
    ``null`` counts as left out.

    Args:
        required: The fields the route needs.

    Returns:
        ``(body, None)``, or ``({}, the 400)``.
    """
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return {}, _error("The request body must be a JSON object", code="invalid_body")
    missing = [name for name in required if data.get(name) is None]
    if missing:
        return {}, _error(
            f"Missing required fields: {', '.join(missing)}", code="missing_fields", fields=missing
        )
    for name, (check, wording) in _FIELD_TYPES.items():
        if data.get(name) is not None and not check(data[name]):
            return {}, _error(f"{name} must be {wording}", code="invalid_field", field=name)
    if "\x00" in data.get("source_id", ""):
        # No source has one, and the database can't even be asked for it.
        return {}, denied_response(AccessDenied(404, "Source not found"))
    return data, None


def _load_locked(conn, source_id: str, user: str, action: str) -> tuple:
    """``load_source``, then the row re-read under a row lock for this transaction.

    A route that reads ``remote_data`` or the tree and writes it back builds on
    the locked row, so a change committed meanwhile is kept, and the next
    writer waits for this one.

    Args:
        conn: The write transaction's connection.
        source_id: Source id from the request.
        user: The caller's ``sub``.
        action: The ``source`` action to check.

    Returns:
        ``(locked row, ResourceAccess)``.

    Raises:
        AccessDenied: As ``load_source``.
    """
    doc, ra = load_source(conn, source_id, user, action)
    locked = SourcesRepository(conn).get_for_update(str(doc["id"]))
    return (locked if locked is not None else doc), ra


def _wiki_refusal(doc: dict) -> Optional[Response]:
    """The 400 for a source converted to a wiki, or ``None``.

    A converted source keeps its website ``type`` and ``remote_data``, but its
    pages are the wiki's now: adding, refreshing or removing web pages would
    write raw chunks into it, and a schedule would sync over it.
    """
    return _error(_WIKI_NO_SYNC, code="wiki") if _is_wiki(doc) else None


def _chunk_edits_refusal() -> Optional[Response]:
    """The 400 when the vector store can't change single chunks (Elasticsearch), or ``None``.

    Refreshing or removing a page edits that page's chunks; on such a store
    the change would report success and leave the chunks as they were.
    """
    if VectorCreator.supports_chunk_edits(settings.VECTOR_STORE):
        return None
    return _error(
        f"The {settings.VECTOR_STORE} vector store can't change single pages; sync the source instead",
        code="chunks_unsupported",
    )


def _website_config(doc: dict) -> Optional[dict]:
    """The source's Website config, converting an older web source; ``None`` for any other."""
    return config_from_legacy(doc.get("type"), doc.get("remote_data"))


def _cleaned(config: dict) -> dict:
    """A config parsed without the write limits, cleaned as the write routes store one.

    Each page is listed once (by ``page_key``, the first spelling kept), and
    a site's ``max_pages`` is cut to ``WEB_MAX_PAGES``: neither refuses a
    save, so a source stored before either rule still saves.

    Args:
        config: ``parse_website_config(..., enforce_page_cap=False)``'s result.

    Returns:
        A new config.
    """
    cap = int(settings.WEB_MAX_PAGES)
    config = _pages_once(config)
    entries = [
        {**entry, "max_pages": min(entry["max_pages"], cap)}
        if entry["mode"] == "site" and entry.get("max_pages") is not None else entry
        for entry in config["entries"]
    ]
    return {**config, "entries": entries}


def _within_depth(url: str) -> bool:
    """Whether an address is at most ``MAX_PATH_SEGMENTS`` folders deep, as a load fetches one.

    Args:
        url: An address that parsed.

    Returns:
        False for a deeper one.
    """
    return urlparse(url).path.count("/") <= MAX_PATH_SEGMENTS


def _added_value_refusal(config: dict, stored: dict) -> Optional[Response]:
    """The 400 for an address, path or skip rule a change adds that a write may not store, or ``None``.

    A config parsed without the write limits only needs addresses that
    parse, so what the change adds is checked as a strict parse checks it:
    each new address (an entry's or its ``sitemap_url``) must be an
    ``is_web_address`` (no ``user:password@`` credentials, no malformed
    host, no control character) at most ``MAX_PATH_SEGMENTS`` folders deep;
    a long one is ``url_too_long``, below. What the source already holds is left
    alone. A control character in a path or skip rule is checked on the
    request body (``_control_character_refusal``): the parse drops it.

    Args:
        config: The new config, parsed without the write limits.
        stored: The source's config before the change.

    Returns:
        The refusal, ``invalid_address`` with the ``url``.
    """
    old_entries = stored["entries"]
    old_urls = {url for entry in old_entries for url in (entry["url"], entry.get("sitemap_url")) if url}
    for entry in config["entries"]:
        for label, url in (("Address", entry["url"]), ("Sitemap address", entry.get("sitemap_url"))):
            if url and url not in old_urls and not (is_web_address(url) and _within_depth(url)):
                # The value is echoed back to the client: kept to a URL's length.
                return _error(
                    f"{label} {url[:200]!r} is not a web address",
                    code="invalid_address",
                    url=url[: website_loader.MAX_URL_LENGTH],
                )
    return None


def _control_character_refusal(raw: dict) -> Optional[Response]:
    """The 400 when a settings body's path or skip rule holds a control character, or ``None``.

    A parse without the write limits strips such characters from a path and
    drops such a rule, so a stored row that has one still reads; a save is
    refused instead of quietly changing what was sent. A stored config
    never holds one (its read drops it), so any found here is new.

    Args:
        raw: The settings body as sent: ``entries`` and ``skip``.

    Returns:
        The refusal, ``invalid_config``.
    """
    entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
    if any(
        isinstance(entry, dict)
        and isinstance(entry.get("path_prefix"), str)
        and _CONTROL_CHARACTER.search(entry["path_prefix"])
        for entry in entries
    ):
        return _error("A path can't contain control characters", code="invalid_config")
    rules = raw.get("skip") if isinstance(raw.get("skip"), list) else []
    if any(isinstance(rule, str) and _CONTROL_CHARACTER.search(rule) for rule in rules):
        return _error("A skip rule can't contain control characters", code="invalid_config")
    return None


def _growth_refusal(config: dict, stored: dict, built_rules: Iterable[str] = ()) -> Optional[Response]:
    """The 400 when a change grows a config past a write limit or adds a value it may not store, or ``None``.

    The limits apply to what a change adds, not to what the source already
    holds: a source over a limit (the admin lowered ``WEB_MAX_PAGES``, or it
    was saved before a limit existed) can still shrink, and be saved as it
    is. So the page cap, the site limit and the skip-rule limit refuse only a
    count that is past the limit and larger than the stored one, and the
    length limit only an address, path or rule the source didn't hold. The
    address check (``_added_value_refusal``) runs first, by the same rule.

    Args:
        config: The new config, parsed without the write limits.
        stored: The source's config before the change.
        built_rules: Skip rules the server built from addresses the source
            already holds (a removed page's or folder's): exempt from the
            length limit, or a page whose stored address is long could
            never be removed. They still count toward the skip-rule limit.

    Returns:
        The refusal, with a ``code`` and the limit (or the address) for the UI's wording.
    """
    refusal = _added_value_refusal(config, stored)
    if refusal is not None:
        return refusal
    entries, old_entries = config["entries"], stored["entries"]
    cap = int(settings.WEB_MAX_PAGES)
    # A site brings at least one page, so it counts toward the cap too.
    if len(entries) > cap and len(entries) > len(old_entries):
        return _error(f"A website source holds up to {cap} pages", code="page_limit", max_pages=cap)
    max_sites = website_loader.MAX_SITE_ENTRIES
    sites = sum(1 for entry in entries if entry["mode"] == "site")
    if sites > max_sites and sites > sum(1 for entry in old_entries if entry["mode"] == "site"):
        return _error(f"A website source holds up to {max_sites} sites", code="site_limit", max_sites=max_sites)
    max_skip = website_loader.MAX_SKIP_RULES
    if len(config["skip"]) > max_skip and len(config["skip"]) > len(stored["skip"]):
        return _error(
            f"A website source holds up to {max_skip} skip rules", code="skip_limit", max_skip=max_skip
        )
    max_length = website_loader.MAX_URL_LENGTH
    old_urls = {url for entry in old_entries for url in (entry["url"], entry.get("sitemap_url")) if url}
    new_urls = [url for entry in entries for url in (entry["url"], entry.get("sitemap_url")) if url]
    if any(len(url) > max_length and url not in old_urls for url in new_urls):
        return _error(
            f"An address is longer than {max_length} characters", code="url_too_long", max_length=max_length
        )
    old_prefixes = {entry.get("path_prefix") or "" for entry in old_entries if entry["mode"] == "site"}
    if any(
        len(entry.get("path_prefix") or "") > max_length and (entry.get("path_prefix") or "") not in old_prefixes
        for entry in entries
        if entry["mode"] == "site"
    ):
        return _error(
            f"Path is longer than {max_length} characters", code="url_too_long", max_length=max_length
        )
    old_rules = set(stored["skip"]) | set(built_rules)
    if any(len(rule.removesuffix("*")) > max_length and rule not in old_rules for rule in config["skip"]):
        return _error(
            f"A skip rule is longer than {max_length} characters", code="url_too_long", max_length=max_length
        )
    return None


@sources_ns.route("/website")
class WebsiteSettings(Resource):
    save_model = api.model(
        "WebsiteSettingsModel",
        {
            "source_id": fields.String(required=True, description="Source ID"),
            "entries": fields.List(
                fields.Raw,
                required=True,
                description=(
                    "What the source fetches: {url, mode: page|site, max_pages, path_prefix, "
                    "include_subdomains, discovery: auto|sitemap|links, sitemap_url}"
                ),
            ),
            "skip": fields.List(
                fields.String,
                description=(
                    "Pages (url) or sections (https://host/path/*) to leave out; left out, the stored "
                    "list is kept, and [] clears it"
                ),
            ),
            "keep_links": fields.Boolean(
                description="Keep the URL of links inside sentences in page text; left out, the stored setting is kept"
            ),
            "sync_frequency": fields.String(description="never, daily, weekly or monthly"),
        },
    )

    @api.doc(
        description="A Website source's config, sync schedule and last ingest report.",
        params={"id": "Source ID"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        source_id = request.args.get("id")
        try:
            if source_id and "\x00" in source_id:
                raise AccessDenied(404, "Source not found")
            with db_readonly() as conn:
                doc, _ra = load_source(conn, source_id, user, "view_config")
        except AccessDenied as err:
            return denied_response(err)
        config = _website_config(doc)
        if config is None:
            return _error("Not a website source", code="not_website")
        report = (doc.get("metadata") or {}).get("website")
        return make_response(
            jsonify({
                "success": True,
                "source_id": str(doc["id"]),
                "legacy": doc.get("type") != "website",
                "config": config,
                "sync_frequency": doc.get("sync_frequency") or "never",
                "report": report,
            }),
            200,
        )

    @api.expect(save_model)
    @api.doc(
        description=(
            "Save a Website source's entries, skips, link setting and sync schedule. Applies at the next sync. "
            "An address the save adds is checked as in /api/website/pages: one that isn't a web address "
            "(user:password@ credentials, a malformed host, a control character) is a 400 with code "
            "invalid_address, and a new path or skip rule with a control character one with code invalid_config. "
            "What the source already stores is saved as it is."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data, refusal = _read_body(["source_id", "entries"])
        if refusal is not None:
            return refusal
        sync_frequency = data.get("sync_frequency")
        if sync_frequency is not None and sync_frequency not in _SYNC_FREQUENCIES:
            return _error(f"Unknown sync_frequency {sync_frequency!r}", code="bad_sync_frequency")
        try:
            with db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                stored = _website_config(doc)
                if stored is None:
                    return _error("Not a website source", code="not_website")
                refusal = _wiki_refusal(doc)
                if refusal is not None:
                    return refusal
                # A key left out keeps its stored value, as in PATCH /sources/<id>/config.
                raw = {
                    "entries": data["entries"],
                    "skip": data["skip"] if data.get("skip") is not None else stored["skip"],
                    "keep_links": (
                        data["keep_links"] if data.get("keep_links") is not None else stored["keep_links"]
                    ),
                }
                refusal = _control_character_refusal(raw)
                if refusal is not None:
                    return refusal
                try:
                    config = _cleaned(parse_website_config(raw, enforce_page_cap=False))
                except ValueError as err:
                    return _config_error(err)
                refusal = _growth_refusal(config, stored)
                if refusal is not None:
                    return refusal
                fields_ = {"remote_data": config, "type": "website"}
                if sync_frequency is not None:
                    fields_["sync_frequency"] = sync_frequency
                SourcesRepository(conn).update(str(doc["id"]), ra.owner_id, fields_)
        except AccessDenied as err:
            return denied_response(err)
        return make_response(jsonify({"success": True, "config": config}), 200)


@sources_ns.route("/website/remove")
class RemoveWebsitePages(Resource):
    remove_model = api.model(
        "RemoveWebsitePagesModel",
        {
            "source_id": fields.String(required=True, description="Source ID"),
            "file_paths": fields.List(
                fields.String, description=f"Tree paths of pages to remove, up to {MAX_REMOVE_PATHS}"
            ),
            "directory_path": fields.String(description="Tree path of a folder to remove"),
        },
    )

    @api.expect(remove_model)
    @api.doc(
        description=(
            "Remove pages or a folder from a Website source. The config changes now: a page added by address "
            "leaves the list; one found by a site's crawl (or a whole folder) is skipped in later syncs. Their "
            "chunks and tree entries go in a background task (task_id), after any running sync; a 500 with code "
            "queue_failed when the config was saved but the task couldn't be queued. A page an older url, crawler "
            "or sitemap source stored without its address is matched by the address on its chunks; when none is "
            "found it is still removed, by its path, and the config is left as it is."
        ),
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data, refusal = _read_body(["source_id"])
        if refusal is not None:
            return refusal
        file_paths = list(dict.fromkeys(data.get("file_paths") or []))
        if len(file_paths) > MAX_REMOVE_PATHS:
            return _error(
                f"One removal names up to {MAX_REMOVE_PATHS} pages",
                code="too_many_paths",
                max_paths=MAX_REMOVE_PATHS,
            )
        directory_path = (data.get("directory_path") or "").strip("/")
        try:
            with db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                refusal = _wiki_refusal(doc) or _chunk_edits_refusal()
                if refusal is not None:
                    return refusal
                stored = _website_config(doc)
                if stored is None:
                    return _error("Not a website source", code="not_website")
                structure = doc.get("directory_structure") or {}
                if not isinstance(structure, dict):
                    structure = {}

                # An older loader's leaves carry no address (listed with "").
                known = dict(web_pages(structure, include_unaddressed=True))
                requested = _requested_urls(structure)
                pages = [(path, known[path]) for path in file_paths if path in known]
                folder_paths: set = set()
                if directory_path:
                    folder_pages = pages_under(structure, directory_path, include_unaddressed=True)
                    folder_paths = {path for path, _url in folder_pages}
                    named = {path for path, _url in pages}
                    pages.extend(p for p in folder_pages if p[0] not in named)
                if not pages:
                    return _error("No such pages in this source", code="not_found")
                # Their addresses come from their chunks; one that can't be
                # found edits nothing, and the worker removes it by its path.
                unaddressed = [path for path, url in pages if not url]
                found = _addresses_from_chunks(str(doc["id"]), unaddressed) if unaddressed else {}
                addressed = [(path, url or found.get(path, "")) for path, url in pages]
                section_rule = None
                if directory_path:
                    section_rule = folder_skip_rule(
                        directory_path, [(path, url) for path, url in addressed if path in folder_paths and url]
                    )

                config = _without_pages(stored, addressed, section_rule, requested, folder_paths)
                if not config["entries"]:
                    return _error(
                        "That would leave the source with nothing to fetch; delete the source instead",
                        code="last_entry",
                    )
                # A removal only shrinks the entries, so of the write limits
                # only the skip rules it adds are checked: a source over the
                # page cap (lowered since it was saved) can still shrink.
                # Their length isn't: each is built from an address the tree
                # already holds, however long the crawl found it.
                refusal = _growth_refusal(config, stored, built_rules=config["skip"])
                if refusal is not None:
                    return refusal

                # Saved now, so a sync that starts before the worker runs
                # already leaves the pages out. With no address to go by,
                # an older source is left as stored rather than converted.
                if any(url for _path, url in addressed):
                    SourcesRepository(conn).update(
                        str(doc["id"]), ra.owner_id, {"remote_data": config, "type": "website"}
                    )
            # The chunks and tree entries go in the worker, under the source's
            # index lock: a running sync is waited for rather than refused, and
            # no request is held open while a large folder's chunks are deleted.
        except AccessDenied as err:
            return denied_response(err)
        except Exception as err:
            current_app.logger.error(f"Error removing website pages: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        # Each page goes with its URL and every address that redirected to
        # it: the worker finds it by those in the tree as it is then, so a
        # sync that moved it meanwhile still removes the right page. A leaf
        # stored without an address goes with the one read from its chunks
        # (a sync that ran first gave its path to another page, and a url
        # loader's chunks carry no path); only one whose address couldn't be
        # found goes with "", and is found by its path.
        try:
            task = website_pages.delay(
                str(doc["id"]), ra.owner_id, "remove", pages=[
                    {"path": path, "url": url, "requested_urls": requested.get(path, [])}
                    for path, url in addressed
                ], actor_id=user,
            )
        except Exception as err:
            # The config is saved, so the next sync leaves the pages out.
            return _queue_failed(QUEUE_FAILED_SAVED, err)
        return make_response(
            jsonify({"success": True, "task_id": task.id, "removed": len(pages), "config": config}), 200
        )


@sources_ns.route("/website/pages")
class AddWebsitePages(Resource):
    add_model = api.model(
        "AddWebsitePagesModel",
        {
            "source_id": fields.String(required=True, description="Source ID"),
            "entries": fields.List(fields.Raw, required=True, description="Pages or sites to add (as in /api/website)"),
        },
    )

    @api.expect(add_model)
    @api.doc(
        description=(
            "Add pages or sites to a Website source; they stay in every sync. Pages are fetched and appended "
            "now (mode append). A site rebuilds the source like a sync (mode sync), and so does a page whose host "
            "makes a single-host source span several hosts (every page moves under a host folder), or any add on "
            "a vector store that can't change single chunks. Only what the source doesn't list yet is added and "
            "fetched: a page it lists under any spelling, or a site with the same address and settings; when "
            "that leaves nothing, a 400 with code already_listed and nothing is queued. Refused with code "
            "page_limit when the source would hold more than WEB_MAX_PAGES pages; a 500 with code queue_failed "
            "when the entries were saved but the task couldn't be queued (the next sync fetches them)."
        ),
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data, refusal = _read_body(["source_id", "entries"])
        if refusal is not None:
            return refusal
        try:
            parsed = parse_website_config({"entries": data["entries"]})["entries"]
        except ValueError as err:
            return _config_error(err)
        # One page named several ways (``/new``, ``/new/``, ``www.…/new#a``)
        # is one entry: the first spelling is kept, so the cap counts it once.
        firsts: Dict[tuple, dict] = {}
        for entry in parsed:
            firsts.setdefault(_entry_identity(entry), entry)
        new_entries = list(firsts.values())
        try:
            with db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                config = _website_config(doc)
                if config is None:
                    return _error("Not a website source", code="not_website")
                refusal = _wiki_refusal(doc)
                if refusal is not None:
                    return refusal
                listed = {_entry_identity(e) for e in config["entries"]}
                added = [e for e in new_entries if _entry_identity(e) not in listed]
                if not added:
                    return _error(ALREADY_LISTED, code="already_listed")
                # WEB_MAX_PAGES caps the whole source, so it can't grow past
                # what a sync may fetch again.
                cap = int(settings.WEB_MAX_PAGES)
                held = _held_pages(config, doc.get("directory_structure"))
                new_pages = len({_key(e["url"]) for e in added if e["mode"] == "page"} - held["keys"])
                adds_site = any(e["mode"] == "site" for e in added)
                total = held["count"] + new_pages
                if total > cap or (adds_site and total >= cap):
                    return _error(f"A website source holds up to {cap} pages", code="page_limit", max_pages=cap)
                # The new entries were checked against the write limits above;
                # what the source already holds is checked only for growth.
                try:
                    merged = parse_website_config(
                        {**config, "entries": config["entries"] + added}, enforce_page_cap=False
                    )
                except ValueError as err:
                    return _config_error(err)
                refusal = _growth_refusal(merged, config)
                if refusal is not None:
                    return refusal
                config = merged
                SourcesRepository(conn).update(
                    str(doc["id"]), ra.owner_id, {"remote_data": config, "type": "website"}
                )
        except AccessDenied as err:
            return denied_response(err)

        structure = doc.get("directory_structure") if isinstance(doc.get("directory_structure"), dict) else {}
        # Read through ``_with_scheme``: an address written without a scheme
        # has no host for ``urlparse``, and would count as a new one.
        hosts = {urlparse(_with_scheme(url)).netloc for _path, url in web_pages(structure)}
        # Only what was added is fetched: a listed entry named again changes nothing.
        page_urls = [e["url"] for e in added if e["mode"] == "page"]
        new_hosts = hosts | {urlparse(_with_scheme(url)).netloc for url in page_urls}
        # A site can bring any number of pages, and a first second host puts
        # every page under a host folder: both rebuild rather than append.
        # A store that can't add single chunks (Elasticsearch) rebuilds too.
        needs_sync = (
            any(e["mode"] == "site" for e in added)
            or (bool(hosts) and (len(hosts) > 1) != (len(new_hosts) > 1))
            or not VectorCreator.supports_chunk_edits(settings.VECTOR_STORE)
        )
        source_id = str(doc["id"])
        try:
            if needs_sync:
                task = sync_source.delay(
                    source_data=config,
                    job_name=doc.get("name", ""),
                    user=ra.owner_id,
                    loader="website",
                    sync_frequency=doc.get("sync_frequency") or "never",
                    retriever=doc.get("retriever") or "classic",
                    doc_id=source_id,
                    actor_id=user,
                )
            else:
                task = website_pages.delay(source_id, ra.owner_id, "add", urls=page_urls, actor_id=user)
        except Exception as err:
            # The entries are saved: the next sync fetches them.
            return _queue_failed(QUEUE_FAILED_SAVED, err)
        return make_response(
            jsonify({
                "success": True,
                "task_id": task.id,
                "mode": "sync" if needs_sync else "append",
                "config": config,
            }),
            200,
        )


@sources_ns.route("/website/refresh")
class RefreshWebsitePage(Resource):
    refresh_model = api.model(
        "RefreshWebsitePageModel",
        {
            "source_id": fields.String(required=True, description="Source ID"),
            "file_path": fields.String(required=True, description="Tree path of the page"),
            "url": fields.String(
                description=(
                    "The page's address, as its tree leaf shows it; when given, the page is found by it "
                    "wherever a sync moved it"
                )
            ),
        },
    )

    @api.expect(refresh_model)
    @api.doc(
        description=(
            "Re-fetch one page of a Website source now; if it can't be fetched, its content is kept. A page "
            "found by a site's crawl that now leads outside the site's scope or to a skipped address is removed, "
            "as the next sync would drop it (the task's failed event carries reason out_of_scope). A 500 with "
            "code queue_failed when the task couldn't be queued."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data, refusal = _read_body(["source_id", "file_path"])
        if refusal is not None:
            return refusal
        try:
            with db_readonly() as conn:
                doc, ra = load_source(conn, data["source_id"], user, "edit")
        except AccessDenied as err:
            return denied_response(err)
        if _website_config(doc) is None:
            return _error("Not a website source", code="not_website")
        refusal = _wiki_refusal(doc) or _chunk_edits_refusal()
        if refusal is not None:
            return refusal
        structure = doc.get("directory_structure") if isinstance(doc.get("directory_structure"), dict) else {}
        page = _find_page(web_pages(structure), data["file_path"], data.get("url"), _requested_urls(structure))
        if page is None:
            return _error("No such page in this source", code="not_found")
        path, url = page
        # The worker finds the page by its address under the index lock: a
        # sync that runs first can give its path to another page.
        try:
            task = website_pages.delay(
                str(doc["id"]), ra.owner_id, "refresh", file_path=path, url=url, actor_id=user
            )
        except Exception as err:
            return _queue_failed(QUEUE_FAILED_REFRESH, err)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


def _addresses_from_chunks(source_id: str, paths: List[str]) -> Dict[str, str]:
    """The address of each tree leaf an older loader stored without one, read from its chunks.

    The url/crawler/sitemap loaders kept a page's address only on its
    chunks (``metadata.source``), under the tree path the leaf was named
    after: ``metadata.file_path``, or for chunks without one (the url
    loader's) ``metadata.title``.

    Args:
        source_id: The source.
        paths: Tree paths of leaves without a ``url``.

    Returns:
        ``{path: address}`` for each path whose chunks name a web address;
        empty when the store can't list its chunks (logged).
    """
    wanted = set(paths)
    try:
        chunks = get_vector_store(source_id).get_chunks() or []
    except Exception as err:
        current_app.logger.warning(f"Could not read the chunks of source {source_id}: {err}", exc_info=True)
        return {}
    found: Dict[str, str] = {}
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        address = metadata.get("source")
        if not isinstance(address, str) or not is_web_address(address):
            continue
        file_path = metadata.get("file_path")
        path = file_path if file_path else (None if metadata.get("key") else metadata.get("title"))
        if isinstance(path, str) and path in wanted:
            found.setdefault(path, address)
    return found


def _find_page(
    pages: list, file_path: str, url: Optional[str], requested: Optional[Dict[str, List[str]]] = None,
) -> Optional[Tuple[str, str]]:
    """The tree page a refresh names: by address when it gives one, else by path.

    Args:
        pages: ``(path, url)`` of the tree's pages.
        file_path: The tree path the caller saw.
        url: The address the caller saw, if any; matched by ``page_key``
            against each page's address and every address that redirected to it.
        requested: ``{path: [requested addresses]}`` of the pages stored after a redirect.

    Returns:
        ``(path, url)`` as the tree holds it now, or ``None``.
    """
    if not url:
        return next(((path, page_url) for path, page_url in pages if path == file_path), None)
    key = _key(url)
    requested = requested or {}
    matches = [
        (path, page_url) for path, page_url in pages
        if key in {_key(u) for u in (page_url, *requested.get(path, ())) if u}
    ]
    return next((m for m in matches if m[0] == file_path), matches[0] if matches else None)


def _key(url: str) -> str:
    """``page_key``, or the URL itself when it can't be parsed."""
    try:
        return page_key(url)
    except ValueError:
        return url


def _entry_identity(entry: dict) -> tuple:
    """What makes an entry the same as another: a page's address, or a site's address and every setting.

    A page is one page under any spelling (``page_key``). A site's settings
    are part of it: one address crawled under ``/guide/`` and under ``/api/``
    (or with another limit, discovery or sitemap) is two entries.

    Args:
        entry: A parsed config entry.

    Returns:
        A hashable key.
    """
    if entry["mode"] != "site":
        return ("page", _key(entry["url"]))
    sitemap_url = entry.get("sitemap_url")
    return (
        "site",
        _key(entry["url"]),
        entry.get("path_prefix") or "",
        bool(entry.get("include_subdomains")),
        entry.get("discovery") or "auto",
        _key(sitemap_url) if sitemap_url else None,
        entry.get("max_pages"),
    )


def _held_pages(config: dict, structure) -> dict:
    """The pages a source holds toward ``WEB_MAX_PAGES``.

    Its page entries count from when they are listed (one still queued, or
    one whose fetch failed, keeps its place), and so do the pages in its tree
    (a site's crawl). A page that is both counts once, a redirected one too
    (its entries list the addresses its leaf keeps as ``requested_urls``).

    Args:
        config: The Website config.
        structure: ``directory_structure``.

    Returns:
        ``{"keys": page keys held, "count": how many pages}``; tree leaves
        without a URL (older crawls) count but have no key.
    """
    tree = structure if isinstance(structure, dict) else {}
    tree_pages = web_pages(tree)
    tree_keys = {_key(url) for _path, url in tree_pages}
    asked_keys = {_key(url) for urls in _requested_urls(tree).values() for url in urls} - tree_keys
    entry_keys = {_key(e["url"]) for e in config["entries"] if e["mode"] == "page"}
    held = len(tree_keys) + len(entry_keys - tree_keys - asked_keys)
    return {"keys": tree_keys | asked_keys | entry_keys, "count": held + count_pages(tree) - len(tree_pages)}


def _reachable(entries: list, skip: list, url: str) -> bool:
    """Whether a site entry's crawl could still bring ``url`` back.

    Args:
        entries: The config's remaining entries.
        skip: Its skip rules; a page they already cover needs no new rule.
        url: A page or section address.

    Returns:
        True when some site entry's scope accepts it.
    """
    return any(
        SiteScope(e["url"], e.get("path_prefix") or "", bool(e.get("include_subdomains")), skip).accepts(url)
        for e in entries
        if e["mode"] == "site"
    )


def _requested_urls(structure: Any, prefix: str = "") -> Dict[str, List[str]]:
    """``{tree path: [requested addresses]}`` for the pages stored after a redirect.

    A redirected page's leaf keeps every address it was asked for
    (``requested_urls``; a leaf from before keeps one, ``requested_url``)
    beside the one it was stored under (``url``). Page entries are listed as
    typed, so removing the page has to find each entry by those addresses:
    several entries can redirect to one page.

    Args:
        structure: ``directory_structure``.
        prefix: Path of ``structure`` within the whole tree.

    Returns:
        The asked-for addresses of each page leaf that has any, one per
        ``page_key`` and none the same page as its ``url``, in stored order.
    """
    found: Dict[str, List[str]] = {}
    for name, node in structure.items() if isinstance(structure, dict) else ():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(node, dict) and "token_count" in node:
            if not node.get("url"):
                continue
            listed = node.get("requested_urls")
            asked = [u for u in listed if isinstance(u, str) and u] if isinstance(listed, list) else []
            if isinstance(node.get("requested_url"), str) and node["requested_url"]:
                asked.append(node["requested_url"])
            aliases: Dict[str, str] = {}
            for address in asked:
                aliases.setdefault(_key(address), address)
            aliases.pop(_key(node["url"]), None)
            if aliases:
                found[path] = list(aliases.values())
        elif isinstance(node, dict):
            found.update(_requested_urls(node, path))
    return found


def _without_pages(
    config: dict,
    pages: list,
    section_rule: Optional[str],
    requested: Optional[Dict[str, List[str]]] = None,
    section_paths: Iterable[str] = (),
) -> dict:
    """The config after removing pages: page entries leave, and what a site could find again is skipped.

    A removed page gets a skip rule whenever a remaining site entry's scope
    reaches it, whether it was added by address or found by the crawl;
    otherwise the next sync brings it back. A folder gets its section rule
    when a remaining site reaches any of its pages or the section itself; a
    page named beside the folder but outside it gets its own rule.

    A redirected page is one page under several addresses: the one it was
    stored under and each one it was asked for (its leaf's
    ``requested_urls``). A page entry leaves when it lists any of them, and
    each address a site reaches gets a rule.

    Args:
        config: The Website config.
        pages: ``(tree path, url)`` of the pages being removed.
        section_rule: A folder's ``https://host/path/*`` rule, when a folder is removed.
        requested: ``{tree path: [requested addresses]}`` of the pages stored after a redirect.
        section_paths: Tree paths of the pages the folder (``section_rule``) holds.

    Returns:
        A new config.
    """
    requested = requested or {}

    def addresses(path: str, url: str) -> List[str]:
        return list(dict.fromkeys(u for u in (url, *requested.get(path, ())) if u))

    removed = {_key(address) for path, url in pages for address in addresses(path, url)}
    entries = [e for e in config["entries"] if not (e["mode"] == "page" and _key(e["url"]) in removed)]
    skip = list(config["skip"])
    in_section = set(section_paths) if section_rule else set()
    new_rules = []
    if section_rule:
        section = section_rule[: -len("*")]
        urls = [a for path, url in pages if path in in_section for a in addresses(path, url)] + [section]
        if any(_reachable(entries, skip, url) for url in urls):
            new_rules.append(section_rule)
    new_rules.extend(
        address
        for path, url in pages
        if path not in in_section
        for address in addresses(path, url)
        if _reachable(entries, skip, address)
    )
    skip.extend(rule for rule in dict.fromkeys(new_rules) if rule not in skip)
    return {**config, "entries": entries, "skip": skip}
