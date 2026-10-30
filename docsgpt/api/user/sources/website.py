"""Website source routes: its settings, and adding, refreshing and removing pages.

A Website source stores what it fetches (pages and sites) and what a site's
crawl must skip; see ``parser/remote/website_loader.py``. These routes edit
that list, so every change survives a sync: a page a site's crawl found is
added to ``skip`` when it is removed. The chunks and tree entries change in
``website_pages_worker``. Sources made by the older url/crawler/sitemap
loaders read as Website sources and are converted on their first save; their
tree leaves carry no address, so a removal reads each one's from its chunks.
"""

import re
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, NoReturn, Optional, Tuple
from urllib.parse import urlparse

from flask import Response, current_app, jsonify, make_response, request
from flask_restx import fields, Resource

from docsgpt.api import api
from docsgpt.api.user.base import get_vector_store
from docsgpt.api.user.resource_access import AccessDenied, ResourceAccess
from docsgpt.api.user.sources.access import SYNC_FREQUENCIES, denied_response, load_source
from docsgpt.api.user.sources.routes import _WIKI_NO_SYNC, _is_wiki, _with_scheme, sources_ns
from docsgpt.api.user.sources.upload import _website_config_error
from docsgpt.api.user.tasks import sync_source, website_pages
from docsgpt.api.user.utils import error_response
from docsgpt.core.settings import settings
from docsgpt.parser.remote import website_loader
from docsgpt.parser.remote.website_loader import SiteScope, is_web_address, parse_website_config
from docsgpt.parser.remote.website_tree import (
    config_from_legacy,
    folder_skip_rule,
    held_pages,
    page_aliases,
    pages_under,
    stored_page_key as _key,
    tree_leaves,
    web_pages,
)
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.vectorstore.vector_creator import VectorCreator

#: How many tree paths one removal may name; a folder is one path however many pages it holds.
MAX_REMOVE_PATHS = 1000

#: The ``already_listed`` wording for an add that names only what the source already lists.
ALREADY_LISTED = "These pages and sites are already in this source."
#: The ``queue_failed`` wording for a change saved before its task couldn't be queued.
QUEUE_FAILED_SAVED = "The change was saved, but its task couldn't be queued; the next sync picks it up."
#: The ``queue_failed`` wording for a refresh, which saves nothing first.
QUEUE_FAILED_REFRESH = "The refresh couldn't be queued; try again, or sync the source."

# C0 controls and DEL: the parse without the write limits drops a skip rule holding one.
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
# Stands in for an entry's address when only its path or sitemap address is new.
_PROBE_URL = "https://example.com/"


class _Refused(Exception):
    """A refusal raised by a website route's checks; ``_website_route`` answers with its response."""

    def __init__(self, response: Response):
        super().__init__()
        self.response = response


def _refuse(message: str, code: str, status: int = 400, **details: Any) -> NoReturn:
    """Raise the refusal ``{"success": false, "error", "code", ...details}``; ``code`` is what the UI words."""
    raise _Refused(error_response(message, status, code=code, **details))


def _website_route(handler: Callable[..., Response]) -> Callable[..., Response]:
    """Wrap a website route: a 401 without a token, and the response of any refusal its checks raise.

    Args:
        handler: The route method, called with the caller's ``sub``.

    Returns:
        The route method.
    """

    @wraps(handler)
    def route(self) -> Response:
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        try:
            return handler(self, decoded_token.get("sub"))
        except _Refused as refused:
            return refused.response
        except AccessDenied as err:
            return denied_response(err)

    return route


def _queue_failed(message: str, err: Exception) -> Response:
    """The 500 for a task the broker wouldn't take (``code: queue_failed``), logged.

    Args:
        message: What happened to the change, for the UI.
        err: What queueing raised.
    """
    current_app.logger.error(f"Could not queue a website task: {err}", exc_info=True)
    return error_response(message, 500, code="queue_failed")


def _parsed(raw: dict, enforce_page_cap: bool = True) -> dict:
    """``parse_website_config``, its refusal raised with the parser's ``code`` and details."""
    try:
        return parse_website_config(raw, enforce_page_cap=enforce_page_cap)
    except ValueError as err:
        raise _Refused(_website_config_error(err)) from err


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


def _read_body(required: List[str]) -> dict:
    """The request's JSON object, with its required fields present and every known field of the right type.

    A missing or unreadable body reads as ``{}``; a field sent as ``null``
    counts as left out.

    Args:
        required: The fields the route needs.

    Returns:
        The body.

    Raises:
        _Refused: ``invalid_body``, ``missing_fields`` or ``invalid_field``.
    """
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _refuse("The request body must be a JSON object", "invalid_body")
    missing = [name for name in required if data.get(name) is None]
    if missing:
        _refuse(f"Missing required fields: {', '.join(missing)}", "missing_fields", fields=missing)
    for name, (check, wording) in _FIELD_TYPES.items():
        if data.get(name) is not None and not check(data[name]):
            _refuse(f"{name} must be {wording}", "invalid_field", field=name)
    return data


def _load_website(
    conn, source_id: Optional[str], user: str, action: str, *, lock: bool = False, edits_chunks: bool = False,
) -> Tuple[dict, ResourceAccess, dict]:
    """The Website source a route acts on, checked, with its config (an older web source's converted).

    Args:
        conn: The connection; a write's transaction when ``lock``.
        source_id: Source id from the request.
        user: The caller's ``sub``.
        action: The ``source`` action to check; any but ``view_config`` is a change.
        lock: Re-read the row under a row lock, so a route that writes its
            ``remote_data`` back builds on a change committed meanwhile and
            the next writer waits for this one.
        edits_chunks: The change edits single pages' chunks.

    Returns:
        ``(row, ResourceAccess, Website config)``.

    Raises:
        AccessDenied: As ``load_source``; a 404 too for an id holding a NUL,
            which no source has and the database can't be asked for.
        _Refused: ``not_website``; for a change, ``wiki`` (a converted
            source's pages are the wiki's now) and, when it edits chunks on a
            store that can't change single chunks (Elasticsearch, where it
            would report success and leave them), ``chunks_unsupported``.
    """
    if source_id and "\x00" in source_id:
        raise AccessDenied(404, "Source not found")
    doc, ra = load_source(conn, source_id, user, action)
    if lock:
        doc = SourcesRepository(conn).get_for_update(str(doc["id"])) or doc
    config = config_from_legacy(doc.get("type"), doc.get("remote_data"))
    if config is None:
        _refuse("Not a website source", "not_website")
    if action != "view_config" and _is_wiki(doc):
        _refuse(_WIKI_NO_SYNC, "wiki")
    if edits_chunks and not VectorCreator.supports_chunk_edits(settings.VECTOR_STORE):
        _refuse(
            f"The {settings.VECTOR_STORE} vector store can't change single pages; sync the source instead",
            "chunks_unsupported",
        )
    return doc, ra, config


def _cleaned(config: dict) -> dict:
    """A config parsed without the write limits, cleaned as the write routes store one.

    Each page is listed once (by ``page_key``, the first spelling kept), and
    a site's ``max_pages`` is cut to ``WEB_MAX_PAGES``: neither refuses a
    save, so a source stored before either rule still saves.
    """
    cap = int(settings.WEB_MAX_PAGES)
    seen = set()
    entries = []
    for entry in config["entries"]:
        if entry["mode"] == "page":
            if _key(entry["url"]) in seen:
                continue
            seen.add(_key(entry["url"]))
        elif entry.get("max_pages") is not None:
            entry = {**entry, "max_pages": min(entry["max_pages"], cap)}
        entries.append(entry)
    return {**config, "entries": entries}


def _addresses(entries: Iterable[dict]) -> set:
    """Every entry address and sitemap address of a config's entries."""
    return {url for entry in entries for url in (entry["url"], entry.get("sitemap_url")) if url}


def _check_new_values(raw: dict, parsed: dict, stored: dict) -> None:
    """Refuse an address, path or skip rule a settings save adds that a write may not store.

    The save is parsed without the write limits, so what the source already
    holds saves as it is; each value it doesn't hold yet is put through the
    strict parse on its own, for its value checks only. A path and a skip
    rule with a control character are read as sent: the lenient parse
    strips one and drops the other.

    Args:
        raw: The settings body: ``entries`` and ``skip``.
        parsed: ``raw`` parsed without the write limits.
        stored: The source's config before the change.

    Raises:
        _Refused: The strict parse's refusal (``invalid_address``, ``url_too_long``, ``invalid_config``).
    """
    old_urls = _addresses(stored["entries"])
    old_prefixes = {entry.get("path_prefix") or "" for entry in stored["entries"] if entry["mode"] == "site"}
    probes = []
    for item, entry in zip(raw["entries"], parsed["entries"]):
        url = entry["url"] if entry["url"] not in old_urls else None
        sitemap_url = entry.get("sitemap_url") if entry.get("sitemap_url") not in old_urls else None
        path_prefix = str(item.get("path_prefix") or "") if entry["mode"] == "site" else ""
        if entry.get("path_prefix") in old_prefixes and not _CONTROL_CHARACTER.search(path_prefix):
            path_prefix = ""
        if url or sitemap_url or path_prefix:
            probes.append({
                "url": url or _PROBE_URL, "mode": entry["mode"], "sitemap_url": sitemap_url,
                "path_prefix": path_prefix,
            })
    # Refused as sent: the parse would strip one off the rule's ends and accept it.
    for rule in raw["skip"]:
        if _CONTROL_CHARACTER.search(rule):
            _refuse(f"Skip rule {rule!r} is not a web address", "invalid_address", url=rule)
    old_rules = set(stored["skip"])
    rules = [rule for rule in parsed["skip"] if rule not in old_rules]
    # One value per parse, so none of its count limits can apply: counts are _check_growth's.
    for probe in probes:
        _parsed({"entries": [probe]})
    for rule in rules:
        _parsed({"entries": [{"url": _PROBE_URL}], "skip": [rule]})


def _check_growth(config: dict, stored: dict) -> None:
    """Refuse a change that grows the page, site or skip-rule count past its write limit.

    A source past a limit (the admin lowered ``WEB_MAX_PAGES``, or it was
    saved before the limit existed) can still shrink and be saved as it is,
    so only a count past its limit and larger than the stored one is refused.

    Args:
        config: The config after the change.
        stored: The source's config before it.

    Raises:
        _Refused: ``page_limit``, ``site_limit`` or ``skip_limit``, with the limit.
    """
    def sites(of: dict) -> int:
        return sum(1 for entry in of["entries"] if entry["mode"] == "site")

    cap = int(settings.WEB_MAX_PAGES)
    # A site brings at least one page, so it counts toward the cap too.
    if len(config["entries"]) > max(cap, len(stored["entries"])):
        _refuse(f"A website source holds up to {cap} pages", "page_limit", max_pages=cap)
    max_sites = website_loader.MAX_SITE_ENTRIES
    if sites(config) > max(max_sites, sites(stored)):
        _refuse(f"A website source holds up to {max_sites} sites", "site_limit", max_sites=max_sites)
    max_skip = website_loader.MAX_SKIP_RULES
    if len(config["skip"]) > max(max_skip, len(stored["skip"])):
        _refuse(f"A website source holds up to {max_skip} skip rules", "skip_limit", max_skip=max_skip)


def _entry_paths(config: dict, structure: Any) -> List[str]:
    """Tree paths of the pages a ``mode: "page"`` entry lists, by their address or one that redirected to them.

    Args:
        config: The Website config.
        structure: ``directory_structure``.

    Returns:
        The paths, in stored order.
    """
    keys = {_key(entry["url"]) for entry in config["entries"] if entry["mode"] == "page"}
    return [
        path for path, node in tree_leaves(structure)
        if isinstance(node.get("url"), str) and node["url"]
        and any(_key(url) in keys for url in (node["url"], *page_aliases(node["url"], node)))
    ]


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
        description=(
            "A Website source's config, sync schedule and last ingest report. entry_paths lists the tree paths "
            "of the pages a mode: page entry lists (by its address, or one that redirected to the page); the "
            "other pages were found by a site's crawl."
        ),
        params={"id": "Source ID"},
    )
    @_website_route
    def get(self, user: str) -> Response:
        with db_readonly() as conn:
            doc, _ra, config = _load_website(conn, request.args.get("id"), user, "view_config")
        return make_response(
            jsonify({
                "success": True,
                "source_id": str(doc["id"]),
                "legacy": doc.get("type") != "website",
                "config": config,
                "sync_frequency": doc.get("sync_frequency") or "never",
                "report": (doc.get("metadata") or {}).get("website"),
                "entry_paths": _entry_paths(config, doc.get("directory_structure")),
            }),
            200,
        )

    @api.expect(save_model)
    @api.doc(
        description=(
            "Save a Website source's entries, skips, link setting and sync schedule. Applies at the next sync. "
            "An address the save adds is checked as in /api/website/pages: one that isn't a web address "
            "(user:password@ credentials, a malformed host, a control character) is a 400 with code "
            "invalid_address, as is a new skip rule with a control character; a new path with one is a 400 with "
            "code invalid_config. What the source already stores is saved as it is."
        )
    )
    @_website_route
    def post(self, user: str) -> Response:
        data = _read_body(["source_id", "entries"])
        sync_frequency = data.get("sync_frequency")
        if sync_frequency is not None and sync_frequency not in SYNC_FREQUENCIES:
            _refuse(f"Unknown sync_frequency {sync_frequency!r}", "bad_sync_frequency")
        with db_session() as conn:
            doc, ra, stored = _load_website(conn, data["source_id"], user, "edit", lock=True)
            # A key left out keeps its stored value, as in PATCH /sources/<id>/config.
            raw = {
                "entries": data["entries"],
                "skip": data["skip"] if data.get("skip") is not None else stored["skip"],
                "keep_links": data["keep_links"] if data.get("keep_links") is not None else stored["keep_links"],
            }
            parsed = _parsed(raw, enforce_page_cap=False)
            _check_new_values(raw, parsed, stored)
            config = _cleaned(parsed)
            _check_growth(config, stored)
            fields_ = {"remote_data": config, "type": "website"}
            if sync_frequency is not None:
                fields_["sync_frequency"] = sync_frequency
            SourcesRepository(conn).update(str(doc["id"]), ra.owner_id, fields_)
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
    @_website_route
    def post(self, user: str) -> Response:
        data = _read_body(["source_id"])
        file_paths = list(dict.fromkeys(data.get("file_paths") or []))
        if len(file_paths) > MAX_REMOVE_PATHS:
            _refuse(
                f"One removal names up to {MAX_REMOVE_PATHS} pages", "too_many_paths", max_paths=MAX_REMOVE_PATHS
            )
        directory_path = (data.get("directory_path") or "").strip("/")
        try:
            with db_session() as conn:
                doc, ra, stored = _load_website(conn, data["source_id"], user, "edit", lock=True, edits_chunks=True)
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
                    _refuse("No such pages in this source", "not_found")
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
                    _refuse(
                        "That would leave the source with nothing to fetch; delete the source instead", "last_entry"
                    )
                # Only the skip rules can grow, and each is built from an
                # address the tree already holds, so only their count is checked.
                _check_growth(config, stored)

                # Saved now, so a sync that starts before the worker runs
                # already leaves the pages out. With no address to go by,
                # an older source is left as stored rather than converted.
                if any(url for _path, url in addressed):
                    SourcesRepository(conn).update(
                        str(doc["id"]), ra.owner_id, {"remote_data": config, "type": "website"}
                    )
        except (_Refused, AccessDenied):
            raise
        except Exception as err:
            current_app.logger.error(f"Error removing website pages: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        # The worker deletes the chunks and tree entries under the source's
        # index lock, finding each page by its URL and every address that
        # redirected to it, so a sync that ran meanwhile still removes the
        # right page; one whose address couldn't be found goes by its path.
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
    @_website_route
    def post(self, user: str) -> Response:
        data = _read_body(["source_id", "entries"])
        # One page named several ways (``/new``, ``/new/``, ``www.…/new#a``)
        # is one entry: the first spelling is kept, so the cap counts it once.
        firsts: Dict[tuple, dict] = {}
        for entry in _parsed({"entries": data["entries"]})["entries"]:
            firsts.setdefault(_entry_identity(entry), entry)
        with db_session() as conn:
            doc, ra, config = _load_website(conn, data["source_id"], user, "edit", lock=True)
            listed = {_entry_identity(e) for e in config["entries"]}
            added = [e for e in firsts.values() if _entry_identity(e) not in listed]
            if not added:
                _refuse(ALREADY_LISTED, "already_listed")
            # WEB_MAX_PAGES caps the whole source, so it can't grow past what a sync may fetch again.
            cap = int(settings.WEB_MAX_PAGES)
            held = held_pages(config, doc.get("directory_structure"))
            new_pages = len({_key(e["url"]) for e in added if e["mode"] == "page"} - held["keys"])
            adds_site = any(e["mode"] == "site" for e in added)
            total = held["count"] + new_pages
            if total > cap or (adds_site and total >= cap):
                _refuse(f"A website source holds up to {cap} pages", "page_limit", max_pages=cap)
            # The new entries passed the write limits above; what the source
            # already holds is checked only for growth.
            merged = _parsed({**config, "entries": config["entries"] + added}, enforce_page_cap=False)
            _check_growth(merged, config)
            config = merged
            SourcesRepository(conn).update(str(doc["id"]), ra.owner_id, {"remote_data": config, "type": "website"})

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
            adds_site
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
    @_website_route
    def post(self, user: str) -> Response:
        data = _read_body(["source_id", "file_path"])
        with db_readonly() as conn:
            doc, ra, _config = _load_website(conn, data["source_id"], user, "edit", edits_chunks=True)
        structure = doc.get("directory_structure") if isinstance(doc.get("directory_structure"), dict) else {}
        page = _find_page(web_pages(structure), data["file_path"], data.get("url"), _requested_urls(structure))
        if page is None:
            _refuse("No such page in this source", "not_found")
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
    (``requested_urls``) beside the one it was stored under (``url``); page
    entries are listed as typed, so removing or refreshing the page finds
    them by those addresses.

    Args:
        structure: ``directory_structure``.
        prefix: Path of ``structure`` within the whole tree.

    Returns:
        The asked-for addresses of each page leaf that has any, one per
        ``page_key`` and none the same page as its ``url``, in stored order.
    """
    return {
        path: aliases for path, node in tree_leaves(structure, prefix)
        if node.get("url") and (aliases := page_aliases(node["url"], node))
    }


def _without_pages(
    config: dict,
    pages: list,
    section_rule: Optional[str],
    requested: Optional[Dict[str, List[str]]] = None,
    section_paths: Iterable[str] = (),
) -> dict:
    """The config after removing pages: page entries leave, and what a site could find again is skipped.

    A page entry leaves when it lists the page under any of its addresses
    (its ``url`` and each ``requested_urls``). Each address a remaining site
    reaches gets a skip rule, or the next sync brings it back; a folder gets
    its section rule instead when a site reaches the section or any of its
    pages.

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
