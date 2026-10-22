"""Website source routes: its settings, and removing pages.

A Website source stores what it fetches (pages and sites) and what a site's
crawl must skip; see ``parser/remote/website_loader.py``. These routes edit
that list. Removing a page also deletes its chunks and its tree entry at once;
a page found by a site's crawl is added to ``skip`` so the next sync leaves it
out. Sources made by the older url/crawler/sitemap loaders read as Website
sources and are converted on their first save.
"""

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Resource

from docsgpt.api import api
from docsgpt.api.user.base import get_vector_store
from docsgpt.api.user.resource_access import AccessDenied
from docsgpt.api.user.sources.access import denied_response, load_source
from docsgpt.api.user.sources.routes import sources_ns
from docsgpt.parser.remote.website_loader import page_key, parse_website_config
from docsgpt.parser.remote.website_tree import (
    config_from_legacy,
    folder_skip_rule,
    pages_under,
    remove_pages,
    total_tokens,
    web_pages,
)
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields

_SYNC_FREQUENCIES = ("never", "daily", "weekly", "monthly")


def _error(message: str, status: int = 400):
    return make_response(jsonify({"success": False, "error": message}), status)


def _website_config(doc: dict):
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
            "skip": fields.List(fields.String, description="Pages (url) or sections (https://host/path/*) to leave out"),
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
    @api.doc(description="Save a Website source's entries, skips, link setting and sync schedule. Applies at the next sync.")
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
                doc, ra = load_source(conn, data["source_id"], user, "edit")
                if _website_config(doc) is None:
                    return _error("Not a website source")
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
            with db_session() as conn:
                doc, ra = load_source(conn, data["source_id"], user, "edit")
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
                    return _error("That would leave the source with nothing to fetch; delete the source instead")

                store = get_vector_store(str(doc["id"]))
                for _path, url in pages:
                    store.delete_chunks_by_source_path(url)
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
        except Exception as err:
            current_app.logger.error(f"Error removing website pages: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
        return make_response(jsonify({"success": True, "removed": len(pages), "config": config}), 200)


def _without_pages(config: dict, pages: list, section_rule) -> dict:
    """The config after removing pages: page entries leave, crawled pages are skipped.

    Args:
        config: The Website config.
        pages: ``(tree path, url)`` of the pages being removed.
        section_rule: A folder's ``https://host/path/*`` rule, when a folder is removed.

    Returns:
        A new config.
    """
    removed = {page_key(url) for _path, url in pages}
    page_entries = {page_key(e["url"]) for e in config["entries"] if e["mode"] == "page"}
    entries = [e for e in config["entries"] if not (e["mode"] == "page" and page_key(e["url"]) in removed)]
    skip = list(config["skip"])
    if any(e["mode"] == "site" for e in entries):
        crawled = [url for _path, url in pages if page_key(url) not in page_entries]
        if section_rule:
            new_rules = [section_rule] if crawled else []
        else:
            new_rules = crawled
        skip.extend(rule for rule in new_rules if rule not in skip)
    return {**config, "entries": entries, "skip": skip}
