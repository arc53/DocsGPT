"""Website source routes: its settings, and adding, refreshing and removing pages.

A Website source stores what it fetches (pages and sites) and what a site's
crawl must skip; see ``parser/remote/website_loader.py``. These routes edit
that list, so every change survives a sync. A page found by a site's crawl is
added to ``skip`` when it is removed, so the next sync leaves it out. The
chunks and tree entries change in ``website_pages_worker``: removed pages are
deleted there, and added pages are fetched and appended. Sources made by the older url/crawler/sitemap
loaders read as Website sources and are converted on their first save.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from flask import Response, current_app, jsonify, make_response, request
from flask_restx import fields, Resource

from docsgpt.api import api
from docsgpt.api.user.resource_access import AccessDenied
from docsgpt.api.user.sources.access import denied_response, load_source
from docsgpt.api.user.sources.routes import _WIKI_NO_SYNC, _is_wiki, _with_scheme, sources_ns
from docsgpt.api.user.tasks import sync_source, website_pages
from docsgpt.core.settings import settings
from docsgpt.parser.remote import website_loader
from docsgpt.parser.remote.website_loader import SiteScope, page_key, parse_website_config
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


def _error(message: str, status: int = 400, code: Optional[str] = None, **details: Any) -> Response:
    """A failed response; ``code`` names an error the UI words itself, with ``details`` for its message."""
    body = {"success": False, "error": message, **details}
    if code:
        body["code"] = code
    return make_response(jsonify(body), status)


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


def _growth_refusal(config: dict, stored: dict) -> Optional[Response]:
    """The 400 when a change grows a config past a write limit, or ``None``.

    The limits apply to what a change adds, not to what the source already
    holds: a source over a limit (the admin lowered ``WEB_MAX_PAGES``, or it
    was saved before a limit existed) can still shrink, and be saved as it
    is. So the page cap, the site limit and the skip-rule limit refuse only a
    count that is past the limit and larger than the stored one, and the
    length limit only an address or rule the source didn't hold.

    Args:
        config: The new config, parsed without the write limits.
        stored: The source's config before the change.

    Returns:
        The refusal, with a ``code`` and the limit for the UI's wording.
    """
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
    old_rules = set(stored["skip"])
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
        try:
            with db_readonly() as conn:
                doc, _ra = load_source(conn, request.args.get("id"), user, "view_config")
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
        description="Save a Website source's entries, skips, link setting and sync schedule. Applies at the next sync."
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
                try:
                    config = parse_website_config(raw, enforce_page_cap=False)
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
            "chunks and tree entries go in a background task (task_id), after any running sync."
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

                known = dict(web_pages(structure))
                pages = [(path, known[path]) for path in file_paths if path in known]
                section_rule = None
                if directory_path:
                    folder_pages = pages_under(structure, directory_path)
                    named = {path for path, _url in pages}
                    pages.extend(p for p in folder_pages if p[0] not in named)
                    section_rule = folder_skip_rule(directory_path, folder_pages)
                if not pages:
                    return _error("No such pages in this source", code="not_found")

                config = _without_pages(stored, pages, section_rule)
                if not config["entries"]:
                    return _error(
                        "That would leave the source with nothing to fetch; delete the source instead",
                        code="last_entry",
                    )
                # A removal only shrinks the entries, so of the write limits
                # only the skip rules it adds are checked: a source over the
                # page cap (lowered since it was saved) can still shrink.
                refusal = _growth_refusal(config, stored)
                if refusal is not None:
                    return refusal

                # Saved now, so a sync that starts before the worker runs
                # already leaves the pages out.
                SourcesRepository(conn).update(
                    str(doc["id"]), ra.owner_id, {"remote_data": config, "type": "website"}
                )
            # The chunks and tree entries go in the worker, under the source's
            # index lock: a running sync is waited for rather than refused, and
            # no request is held open while a large folder's chunks are deleted.
            # Each page goes with its URL: the worker finds it by that in the
            # tree as it is then, so a sync that moved it meanwhile still
            # removes the right page.
            task = website_pages.delay(
                str(doc["id"]), ra.owner_id, "remove", pages=[{"path": path, "url": url} for path, url in pages]
            )
        except AccessDenied as err:
            return denied_response(err)
        except Exception as err:
            current_app.logger.error(f"Error removing website pages: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
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
            "Add pages or sites to a Website source; they stay in every sync. Pages on the source's hosts are "
            "fetched and appended now; a site, or a page on a new host, rebuilds the source like a sync. "
            "Refused with code page_limit when the source would hold more than WEB_MAX_PAGES pages."
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
            new_entries = parse_website_config({"entries": data["entries"]})["entries"]
        except ValueError as err:
            return _config_error(err)
        try:
            with db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                config = _website_config(doc)
                if config is None:
                    return _error("Not a website source", code="not_website")
                refusal = _wiki_refusal(doc)
                if refusal is not None:
                    return refusal
                listed = {(e["mode"], page_key(e["url"])) for e in config["entries"]}
                added = [e for e in new_entries if (e["mode"], page_key(e["url"])) not in listed]
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
        page_urls = [e["url"] for e in new_entries if e["mode"] == "page"]
        new_hosts = hosts | {urlparse(_with_scheme(url)).netloc for url in page_urls}
        # A site can bring any number of pages, and a first second host puts
        # every page under a host folder: both rebuild rather than append.
        # A store that can't add single chunks (Elasticsearch) rebuilds too.
        needs_sync = (
            any(e["mode"] == "site" for e in new_entries)
            or (bool(hosts) and (len(hosts) > 1) != (len(new_hosts) > 1))
            or not VectorCreator.supports_chunk_edits(settings.VECTOR_STORE)
        )
        source_id = str(doc["id"])
        if needs_sync:
            task = sync_source.delay(
                source_data=config,
                job_name=doc.get("name", ""),
                user=ra.owner_id,
                loader="website",
                sync_frequency=doc.get("sync_frequency") or "never",
                retriever=doc.get("retriever") or "classic",
                doc_id=source_id,
            )
        else:
            task = website_pages.delay(source_id, ra.owner_id, "add", urls=page_urls)
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
    @api.doc(description="Re-fetch one page of a Website source now; if it can't be fetched, its content is kept.")
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
        page = _find_page(web_pages(structure), data["file_path"], data.get("url"))
        if page is None:
            return _error("No such page in this source", code="not_found")
        path, url = page
        # The worker finds the page by its address under the index lock: a
        # sync that runs first can give its path to another page.
        task = website_pages.delay(str(doc["id"]), ra.owner_id, "refresh", file_path=path, url=url)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


def _find_page(pages: list, file_path: str, url: Optional[str]) -> Optional[Tuple[str, str]]:
    """The tree page a refresh names: by address when it gives one, else by path.

    Args:
        pages: ``(path, url)`` of the tree's pages.
        file_path: The tree path the caller saw.
        url: The address the caller saw, if any; matched by ``page_key``.

    Returns:
        ``(path, url)`` as the tree holds it now, or ``None``.
    """
    if not url:
        return next(((path, page_url) for path, page_url in pages if path == file_path), None)
    key = _key(url)
    matches = [(path, page_url) for path, page_url in pages if _key(page_url) == key]
    return next((m for m in matches if m[0] == file_path), matches[0] if matches else None)


def _key(url: str) -> str:
    """``page_key``, or the URL itself when it can't be parsed."""
    try:
        return page_key(url)
    except ValueError:
        return url


def _held_pages(config: dict, structure) -> dict:
    """The pages a source holds toward ``WEB_MAX_PAGES``.

    Its page entries count from when they are listed (one still queued, or
    one whose fetch failed, keeps its place), and so do the pages in its tree
    (a site's crawl). A page that is both counts once.

    Args:
        config: The Website config.
        structure: ``directory_structure``.

    Returns:
        ``{"keys": page keys held, "count": how many pages}``; tree leaves
        without a URL (older crawls) count but have no key.
    """
    tree = structure if isinstance(structure, dict) else {}
    tree_pages = web_pages(tree)
    keys = {_key(url) for _path, url in tree_pages}
    keys |= {_key(e["url"]) for e in config["entries"] if e["mode"] == "page"}
    return {"keys": keys, "count": len(keys) + count_pages(tree) - len(tree_pages)}


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


def _without_pages(config: dict, pages: list, section_rule: Optional[str]) -> dict:
    """The config after removing pages: page entries leave, and what a site could find again is skipped.

    A removed page gets a skip rule whenever a remaining site entry's scope
    reaches it, whether it was added by address or found by the crawl;
    otherwise the next sync brings it back. A folder gets its section rule
    when a remaining site reaches any of its pages or the section itself.

    Args:
        config: The Website config.
        pages: ``(tree path, url)`` of the pages being removed.
        section_rule: A folder's ``https://host/path/*`` rule, when a folder is removed.

    Returns:
        A new config.
    """
    removed = {_key(url) for _path, url in pages}
    entries = [e for e in config["entries"] if not (e["mode"] == "page" and _key(e["url"]) in removed)]
    skip = list(config["skip"])
    if section_rule:
        section = section_rule[: -len("*")]
        urls = [url for _path, url in pages] + [section]
        new_rules = [section_rule] if any(_reachable(entries, skip, url) for url in urls) else []
    else:
        new_rules = [url for _path, url in pages if _reachable(entries, skip, url)]
    skip.extend(rule for rule in new_rules if rule not in skip)
    return {**config, "entries": entries, "skip": skip}
