"""Website source routes: its settings, and adding, refreshing and removing pages.

A Website source stores what it fetches (pages and sites) and what a site's
crawl must skip; see ``parser/remote/website_loader.py``. These routes edit
that list, so every change survives a sync. Removing a page also deletes its
chunks and its tree entry at once; a page found by a site's crawl is added to
``skip`` so the next sync leaves it out. Added pages are fetched and appended
by ``website_pages_worker``. Sources made by the older url/crawler/sitemap
loaders read as Website sources and are converted on their first save.
"""

from typing import Any, Optional
from urllib.parse import urlparse

from flask import Response, current_app, jsonify, make_response, request
from flask_restx import fields, Resource

from docsgpt.api import api
from docsgpt.api.user.base import get_vector_store
from docsgpt.api.user.resource_access import AccessDenied
from docsgpt.api.user.sources.access import denied_response, load_source
from docsgpt.api.user.sources.routes import _WIKI_NO_SYNC, _is_wiki, sources_ns
from docsgpt.api.user.tasks import sync_source, website_pages
from docsgpt.core.settings import settings
from docsgpt.parser.remote.website_loader import SiteScope, page_key, parse_website_config
from docsgpt.parser.remote.website_tree import (
    config_from_legacy,
    count_pages,
    folder_skip_rule,
    pages_under,
    remove_pages,
    total_tokens,
    web_pages,
)
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields
from docsgpt.vectorstore.index_lock import REQUEST_WAIT_SECONDS, SourceBusy, source_index_lock
from docsgpt.vectorstore.vector_creator import VectorCreator

_SYNC_FREQUENCIES = ("never", "daily", "weekly", "monthly")


def _error(message: str, status: int = 400, code: Optional[str] = None, **details: Any) -> Response:
    """A failed response; ``code`` names an error the UI words itself, with ``details`` for its message."""
    body = {"success": False, "error": message, **details}
    if code:
        body["code"] = code
    return make_response(jsonify(body), status)


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
                fields.String, description="Pages (url) or sections (https://host/path/*) to leave out"
            ),
            "keep_links": fields.Boolean(description="Keep the URL of links inside sentences in page text"),
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
            return _error("Not a website source")
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
        data = request.get_json() or {}
        missing = check_required_fields(data, ["source_id", "entries"])
        if missing:
            return missing
        sync_frequency = data.get("sync_frequency")
        if sync_frequency is not None and sync_frequency not in _SYNC_FREQUENCIES:
            return _error(f"Unknown sync_frequency {sync_frequency!r}")
        try:
            config = parse_website_config(
                {"entries": data["entries"], "skip": data.get("skip") or [], "keep_links": data.get("keep_links")}
            )
        except ValueError as err:
            return _error(str(err))
        try:
            with db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                if _website_config(doc) is None:
                    return _error("Not a website source")
                refusal = _wiki_refusal(doc)
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
            "file_paths": fields.List(fields.String, description="Tree paths of pages to remove"),
            "directory_path": fields.String(description="Tree path of a folder to remove"),
        },
    )

    @api.expect(remove_model)
    @api.doc(
        description=(
            "Remove pages or a folder from a Website source: their chunks and tree entries go now. A page added "
            "by address leaves the list; one found by a site's crawl (or a whole folder) is skipped in later syncs."
        ),
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        missing = check_required_fields(data, ["source_id"])
        if missing:
            return missing
        file_paths = [p for p in data.get("file_paths") or [] if isinstance(p, str)]
        directory_path = (data.get("directory_path") or "").strip("/")
        try:
            with db_readonly() as conn:
                doc, _ra = load_source(conn, data["source_id"], user, "edit")
            refusal = _wiki_refusal(doc) or _chunk_edits_refusal()
            if refusal is not None:
                return refusal
            # Chunks are deleted here and now: wait briefly for a sync or a
            # page change on the source rather than race its index writes.
            with source_index_lock(str(doc["id"]), wait_seconds=REQUEST_WAIT_SECONDS), db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                config = _website_config(doc)
                if config is None:
                    return _error("Not a website source")
                structure = doc.get("directory_structure") or {}
                if not isinstance(structure, dict):
                    structure = {}

                known = dict(web_pages(structure))
                pages = [(path, known[path]) for path in file_paths if path in known]
                section_rule = None
                if directory_path:
                    folder_pages = pages_under(structure, directory_path)
                    pages.extend(p for p in folder_pages if p not in pages)
                    section_rule = folder_skip_rule(directory_path, folder_pages)
                if not pages:
                    return _error("No such pages in this source")

                config = _without_pages(config, pages, section_rule)
                if not config["entries"]:
                    return _error(
                        "That would leave the source with nothing to fetch; delete the source instead",
                        code="last_entry",
                    )
                # The skip list grows with each removal; it is held to the
                # same limits as a saved config.
                try:
                    config = parse_website_config(config)
                except ValueError as err:
                    return _error(str(err))

                # One pass for every page: FAISS rewrites its whole index per
                # save, so a folder is saved once rather than once per chunk.
                get_vector_store(str(doc["id"])).delete_chunks_by_source_paths([url for _path, url in pages])
                remove_pages(structure, [path for path, _url in pages])
                SourcesRepository(conn).update(
                    str(doc["id"]),
                    ra.owner_id,
                    {
                        "remote_data": config,
                        "type": "website",
                        "directory_structure": structure,
                        "tokens": str(total_tokens(structure)),
                    },
                )
        except AccessDenied as err:
            return denied_response(err)
        except SourceBusy as err:
            return _error(str(err), 409, code="source_busy")
        except Exception as err:
            current_app.logger.error(f"Error removing website pages: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify({"success": True, "removed": len(pages), "config": config}), 200)


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
        data = request.get_json() or {}
        missing = check_required_fields(data, ["source_id", "entries"])
        if missing:
            return missing
        try:
            new_entries = parse_website_config({"entries": data["entries"]})["entries"]
        except ValueError as err:
            return _error(str(err))
        try:
            with db_session() as conn:
                doc, ra = _load_locked(conn, data["source_id"], user, "edit")
                config = _website_config(doc)
                if config is None:
                    return _error("Not a website source")
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
                try:
                    config = parse_website_config({**config, "entries": config["entries"] + added})
                except ValueError as err:
                    return _error(str(err))
                SourcesRepository(conn).update(
                    str(doc["id"]), ra.owner_id, {"remote_data": config, "type": "website"}
                )
        except AccessDenied as err:
            return denied_response(err)

        structure = doc.get("directory_structure") if isinstance(doc.get("directory_structure"), dict) else {}
        hosts = {urlparse(url).netloc for _path, url in web_pages(structure)}
        page_urls = [e["url"] for e in new_entries if e["mode"] == "page"]
        new_hosts = hosts | {urlparse(url).netloc for url in page_urls}
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
        },
    )

    @api.expect(refresh_model)
    @api.doc(description="Re-fetch one page of a Website source now; if it can't be fetched, its content is kept.")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        missing = check_required_fields(data, ["source_id", "file_path"])
        if missing:
            return missing
        try:
            with db_readonly() as conn:
                doc, ra = load_source(conn, data["source_id"], user, "edit")
        except AccessDenied as err:
            return denied_response(err)
        if _website_config(doc) is None:
            return _error("Not a website source")
        refusal = _wiki_refusal(doc) or _chunk_edits_refusal()
        if refusal is not None:
            return refusal
        structure = doc.get("directory_structure") if isinstance(doc.get("directory_structure"), dict) else {}
        if data["file_path"] not in dict(web_pages(structure)):
            return _error("No such page in this source")
        task = website_pages.delay(str(doc["id"]), ra.owner_id, "refresh", file_path=data["file_path"])
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


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
