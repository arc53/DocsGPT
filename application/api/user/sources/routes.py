"""Source document management routes."""

import json
import math
import uuid

from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import fields, Namespace, Resource
from pydantic import ValidationError

from application.agents.tools.path_utils import validate_tool_path
from application.api import api
from application.api.user.tasks import (
    convert_source_to_wiki,
    extract_graph,
    reembed_wiki_page,
    reingest_source_task,
    sync_source,
)
from application.api.user.team_sharing import (
    can_access,
    effective_write_owner,
    visible_with_access,
)
from application.core.settings import settings
from application.graphrag import graphrag_available
from application.parser.remote.remote_creator import normalize_remote_data
from application.storage.db.repositories.ingest_chunk_progress import (
    IngestChunkProgressRepository,
)
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.wiki_pages import (
    WikiPageConflict,
    WikiPagesRepository,
    _content_hash,
    rebuild_wiki_directory_structure,
)
from application.storage.db.session import db_readonly, db_session
from application.storage.db.source_config import SourceConfig
from application.storage.storage_creator import StorageCreator
from application.utils import check_required_fields
from application.vectorstore.vector_creator import VectorCreator


WIKI_INDEX_PATH = "/index.md"


sources_ns = Namespace(
    "sources", description="Source document management operations", path="/api"
)


def _get_provider_from_remote_data(remote_data):
    if not remote_data:
        return None
    if isinstance(remote_data, dict):
        return remote_data.get("provider")
    if isinstance(remote_data, str):
        try:
            remote_data_obj = json.loads(remote_data)
        except Exception:
            return None
        if isinstance(remote_data_obj, dict):
            return remote_data_obj.get("provider")
    return None


@sources_ns.route("/sources")
class CombinedJson(Resource):
    @api.doc(description="Provide JSON file with combined available indexes")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = [
            {
                "name": "Default",
                "date": "default",
                "model": settings.EMBEDDINGS_NAME,
                "location": "remote",
                "tokens": "",
                "retriever": "classic",
            }
        ]

        try:
            with db_readonly() as conn:
                repo = SourcesRepository(conn)
                indexes = repo.list_for_user(user)
                owned_ids = {str(i["id"]) for i in indexes}
                # Sources shared with the caller's teams — surfaced here so they
                # are attachable to the member's own agents (direct sharing).
                team_shared = visible_with_access(conn, user, "source")
                shared_ids = [sid for sid in team_shared if sid not in owned_ids]
                shared_sources = repo.list_by_ids(shared_ids)
            # list_for_user sorts by created_at DESC; legacy shape sorted by
            # "date" DESC. Both are monotonic on creation so the ordering is
            # equivalent for dev; re-sort defensively.
            indexes = sorted(
                indexes, key=lambda r: r.get("date") or r.get("created_at") or "",
                reverse=True,
            )

            def _source_entry(index, *, ownership="user", team_access=None):
                provider = _get_provider_from_remote_data(index.get("remote_data"))
                return {
                    "id": str(index["id"]),
                    "name": index.get("name"),
                    "date": index.get("date"),
                    "model": settings.EMBEDDINGS_NAME,
                    "location": "local",
                    "tokens": index.get("tokens", ""),
                    "retriever": index.get("retriever", "classic"),
                    "syncFrequency": index.get("sync_frequency", ""),
                    "provider": provider,
                    "is_nested": bool(index.get("directory_structure")),
                    "type": index.get("type", "file"),
                    # Lenient read (D7): always emit a fully-defaulted config so
                    # the frontend edit modal can pre-fill from a legacy {} row.
                    "config": SourceConfig.parse(index.get("config")).model_dump(),
                    "ownership": ownership,
                    "team_access": team_access,
                }

            for index in indexes:
                data.append(_source_entry(index))
            for index in shared_sources:
                data.append(
                    _source_entry(
                        index,
                        ownership="team",
                        team_access=team_shared.get(str(index["id"])),
                    )
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving sources: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(data), 200)


@sources_ns.route("/sources/paginated")
class PaginatedSources(Resource):
    @api.doc(description="Get document with pagination, sorting and filtering")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        sort_field = request.args.get("sort", "date")
        sort_order = request.args.get("order", "desc")
        page = max(1, int(request.args.get("page", 1)))
        rows_per_page = max(1, int(request.args.get("rows", 10)))
        search_term = request.args.get("search", "").strip() or None

        try:
            with db_readonly() as conn:
                repo = SourcesRepository(conn)
                # Include sources shared with the caller's teams so the settings
                # list matches the /api/sources dropdown. Unioned into the query
                # by id so count/sort/search/pagination stay correct.
                team_shared = visible_with_access(conn, user, "source")
                extra_ids = list(team_shared.keys())
                total_documents = repo.count_for_user(
                    user, search_term=search_term, extra_ids=extra_ids,
                )
                # Prior in-Python implementation returned ``totalPages = 1``
                # for empty result sets (``max(1, ceil(0/rows))``); we
                # preserve that contract so the frontend pager stays stable.
                total_pages = max(1, math.ceil(total_documents / rows_per_page))
                effective_page = min(page, total_pages)
                offset = (effective_page - 1) * rows_per_page
                window = repo.list_for_user(
                    user,
                    limit=rows_per_page,
                    offset=offset,
                    search_term=search_term,
                    sort_field=sort_field,
                    sort_order=sort_order,
                    extra_ids=extra_ids,
                )

            paginated_docs = []
            for doc in window:
                provider = _get_provider_from_remote_data(doc.get("remote_data"))
                # Owner vs team-shared: a row in the window is the caller's own
                # when its user_id matches; otherwise it arrived via extra_ids.
                owned = str(doc.get("user_id")) == str(user)
                paginated_docs.append(
                    {
                        "id": str(doc["id"]),
                        "name": doc.get("name", ""),
                        "date": doc.get("date", ""),
                        "model": settings.EMBEDDINGS_NAME,
                        "location": "local",
                        "tokens": doc.get("tokens", ""),
                        "retriever": doc.get("retriever", "classic"),
                        "syncFrequency": doc.get("sync_frequency", ""),
                        "provider": provider,
                        "isNested": bool(doc.get("directory_structure")),
                        "type": doc.get("type", "file"),
                        # Lenient read (D7): always emit a fully-defaulted
                        # config so the edit modal can pre-fill, even for a
                        # legacy {} row.
                        "config": SourceConfig.parse(
                            doc.get("config")
                        ).model_dump(),
                        # Derived in SourcesRepository.list_for_user.
                        "ingestStatus": doc.get("ingest_status"),
                        "ownership": "user" if owned else "team",
                        "team_access": (
                            None if owned else team_shared.get(str(doc["id"]))
                        ),
                    }
                )
            response = {
                "total": total_documents,
                "totalPages": total_pages,
                "currentPage": effective_page,
                "paginated": paginated_docs,
            }
            return make_response(jsonify(response), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving paginated sources: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)


@sources_ns.route("/delete_old")
class DeleteOldIndexes(Resource):
    @api.doc(
        description="Deletes old indexes and associated files",
        params={"source_id": "The source ID to delete"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        source_id = request.args.get("source_id")
        if not source_id:
            return make_response(
                jsonify({"success": False, "message": "Missing required fields"}), 400
            )
        try:
            with db_readonly() as conn:
                doc = SourcesRepository(conn).get_any(source_id, user)
        except Exception as err:
            current_app.logger.error(f"Error looking up source: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        if not doc:
            return make_response(jsonify({"status": "not found"}), 404)
        storage = StorageCreator.get_storage()
        resolved_id = str(doc["id"])

        try:
            if settings.VECTOR_STORE == "faiss":
                index_path = f"indexes/{resolved_id}"
                if storage.file_exists(f"{index_path}/index.faiss"):
                    storage.delete_file(f"{index_path}/index.faiss")
                if storage.file_exists(f"{index_path}/index.pkl"):
                    storage.delete_file(f"{index_path}/index.pkl")
            else:
                vectorstore = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE, source_id=resolved_id
                )
                vectorstore.delete_index()
            if "file_path" in doc and doc["file_path"]:
                file_path = doc["file_path"]
                if storage.is_directory(file_path):
                    files = storage.list_files(file_path)
                    for f in files:
                        storage.delete_file(f)
                else:
                    storage.delete_file(file_path)
        except FileNotFoundError:
            pass
        except Exception as err:
            current_app.logger.error(
                f"Error deleting files and indexes: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            with db_session() as conn:
                SourcesRepository(conn).delete(resolved_id, user)
        except Exception as err:
            current_app.logger.error(
                f"Error deleting source row: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@sources_ns.route("/combine")
class RedirectToSources(Resource):
    @api.doc(
        description="Redirects /api/combine to /api/sources for backward compatibility"
    )
    def get(self):
        return redirect("/api/sources", code=301)


@sources_ns.route("/manage_sync")
class ManageSync(Resource):
    manage_sync_model = api.model(
        "ManageSyncModel",
        {
            "source_id": fields.String(required=True, description="Source ID"),
            "sync_frequency": fields.String(
                required=True,
                description="Sync frequency (never, daily, weekly, monthly)",
            ),
        },
    )

    @api.expect(manage_sync_model)
    @api.doc(description="Manage sync frequency for sources")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        required_fields = ["source_id", "sync_frequency"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        source_id = data["source_id"]
        sync_frequency = data["sync_frequency"]

        if sync_frequency not in ["never", "daily", "weekly", "monthly"]:
            return make_response(
                jsonify({"success": False, "message": "Invalid frequency"}), 400
            )
        try:
            with db_session() as conn:
                repo = SourcesRepository(conn)
                doc = repo.get_any(source_id, user)
                if doc is not None:
                    repo.update(str(doc["id"]), user, {"sync_frequency": sync_frequency})
                else:
                    # Team editor write path (sync_frequency is metadata, no
                    # ingestion side effects). Reingest/sync triggers stay
                    # owner-only pending a cost/side-effect decision.
                    owner = effective_write_owner(conn, "source", source_id, user)
                    if not owner:
                        return make_response(
                            jsonify({"success": False, "message": "Source not found"}),
                            404,
                        )
                    repo.update(source_id, owner, {"sync_frequency": sync_frequency})
        except Exception as err:
            current_app.logger.error(
                f"Error updating sync frequency: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@sources_ns.route("/sync_source")
class SyncSource(Resource):
    sync_source_model = api.model(
        "SyncSourceModel",
        {"source_id": fields.String(required=True, description="Source ID")},
    )

    @api.expect(sync_source_model)
    @api.doc(description="Trigger an immediate sync for a source")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["source_id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        source_id = data["source_id"]
        # Resolve the owner to run the sync AS: ``user`` when they own the
        # source, the real owner when ``user`` holds a team ``editor`` grant
        # (re-sync is an editor-allowed write). Vector partitions are keyed by
        # source_id (owner-agnostic), so dispatching as the owner is correct.
        try:
            with db_readonly() as conn:
                doc = SourcesRepository(conn).get_any(source_id, user)
                owner = user
                if doc is None:
                    owner = effective_write_owner(conn, "source", source_id, user)
                    if owner:
                        doc = SourcesRepository(conn).get_any(source_id, owner)
        except Exception as err:
            current_app.logger.error(f"Error looking up source: {err}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Invalid source ID"}), 400
            )
        if not doc:
            return make_response(
                jsonify({"success": False, "message": "Source not accessible"}), 403
            )
        source_type = doc.get("type", "")
        if source_type and source_type.startswith("connector"):
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Connector sources must be synced via /api/connectors/sync",
                    }
                ),
                400,
            )
        source_data = normalize_remote_data(source_type, doc.get("remote_data"))
        if not source_data:
            return make_response(
                jsonify({"success": False, "message": "Source is not syncable"}), 400
            )
        try:
            task = sync_source.delay(
                source_data=source_data,
                job_name=doc.get("name", ""),
                user=owner,
                loader=source_type,
                sync_frequency=doc.get("sync_frequency", "never"),
                retriever=doc.get("retriever", "classic"),
                doc_id=str(doc["id"]),
            )
        except Exception as err:
            current_app.logger.error(
                f"Error starting sync for source {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


@sources_ns.route("/sources/reingest")
class ReingestSource(Resource):
    reingest_source_model = api.model(
        "ReingestSourceModel",
        {"source_id": fields.String(required=True, description="Source ID")},
    )

    @api.expect(reingest_source_model)
    @api.doc(
        description="Re-run ingestion for a source — e.g. to recover a "
        "stalled embed flagged by the reconciler."
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json() or {}
        missing_fields = check_required_fields(data, ["source_id"])
        if missing_fields:
            return missing_fields
        source_id = data["source_id"]
        # Run the reingest AS the owner: ``user`` when they own the source,
        # the real owner when ``user`` holds a team ``editor`` grant (reingest
        # is an editor-allowed write). Vector partitions are keyed by source_id
        # (owner-agnostic), so dispatching as the owner is correct.
        try:
            with db_readonly() as conn:
                doc = SourcesRepository(conn).get_any(source_id, user)
                owner = user
                if doc is None:
                    owner = effective_write_owner(conn, "source", source_id, user)
                    if owner:
                        doc = SourcesRepository(conn).get_any(source_id, owner)
        except Exception as err:
            current_app.logger.error(
                f"Error looking up source: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Invalid source ID"}), 400
            )
        if not doc:
            return make_response(
                jsonify({"success": False, "message": "Source not accessible"}), 403
            )
        resolved_source_id = str(doc["id"])
        # Drop the stale chunk-progress row so the sources list stops
        # deriving a 'failed' status; reingest never rewrites it itself.
        try:
            with db_session() as conn:
                IngestChunkProgressRepository(conn).delete(resolved_source_id)
        except Exception as err:
            current_app.logger.warning(
                f"Could not clear ingest progress for {resolved_source_id}: "
                f"{err}",
                exc_info=True,
            )
        try:
            # Scoped key so repeated clicks collapse onto one reingest.
            task = reingest_source_task.delay(
                source_id=resolved_source_id,
                user=owner,
                idempotency_key=f"reingest-source:{owner}:{resolved_source_id}",
            )
        except Exception as err:
            current_app.logger.error(
                f"Error starting reingest for source {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


@sources_ns.route("/directory_structure")
class DirectoryStructure(Resource):
    @api.doc(
        description="Get the directory structure for a document",
        params={"id": "The document ID"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        doc_id = request.args.get("id")

        if not doc_id:
            return make_response(jsonify({"error": "Document ID is required"}), 400)
        try:
            with db_readonly() as conn:
                doc = SourcesRepository(conn).get_any(doc_id, user)
            if not doc:
                return make_response(
                    jsonify({"error": "Document not found or access denied"}), 404
                )
            directory_structure = doc.get("directory_structure", {})
            base_path = doc.get("file_path", "")

            provider = None
            remote_data = doc.get("remote_data")
            try:
                if isinstance(remote_data, str) and remote_data:
                    remote_data_obj = json.loads(remote_data)
                    provider = remote_data_obj.get("provider")
                elif isinstance(remote_data, dict):
                    provider = remote_data.get("provider")
            except Exception as e:
                current_app.logger.warning(
                    f"Failed to parse remote_data for doc {doc_id}: {e}"
                )
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "directory_structure": directory_structure,
                        "base_path": base_path,
                        "provider": provider,
                    }
                ),
                200,
            )
        except Exception as e:
            current_app.logger.error(
                f"Error retrieving directory structure: {e}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "error": "Failed to retrieve directory structure"}),
                500,
            )


@sources_ns.route("/sources/<string:source_id>/config")
class SourceConfigResource(Resource):
    source_config_model = api.model(
        "SourceConfigModel",
        {
            "kind": fields.String(description="Behavior selector (e.g. classic)"),
            "chunking": fields.Raw(description="Ingest-time chunking config"),
            "retrieval": fields.Raw(description="Query-time retrieval config"),
        },
    )

    @api.expect(source_config_model)
    @api.doc(
        description="Edit a source's behavior config. Retrieval-time fields "
        "take effect live; chunking changes require an explicit re-ingest "
        "(surfaced as requires_reingest)."
    )
    def patch(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return make_response(
                jsonify({"success": False, "message": "Invalid config body"}), 400
            )
        # Strict validation (D7 strict-on-write): reject invalid config → 400.
        # Return a static message (no exception text) so validation internals
        # aren't exposed to the caller; the client validates the same rules
        # before submitting.
        try:
            new_config = SourceConfig.model_validate(body)
        except ValidationError:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Invalid config: one or more fields failed validation.",
                    }
                ),
                400,
            )

        try:
            with db_session() as conn:
                repo = SourcesRepository(conn)
                # Resolve the owner to write AS: ``user`` when they own the
                # source, the real owner when ``user`` holds a team ``editor``
                # grant. A viewer / no-access resolves to None → 403.
                owner = effective_write_owner(conn, "source", source_id, user)
                if not owner:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Source not accessible"}
                        ),
                        403,
                    )
                doc = repo.get_any(source_id, owner)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                # Ingest-time fields (config.chunking) only take effect after a
                # re-ingest (D8); compare against the current config to decide.
                current_config = SourceConfig.parse(doc.get("config"))
                # kind changes route exclusively through /wiki/convert. An
                # explicit kind in the body that differs from the persisted
                # kind is rejected (either direction); otherwise the current
                # kind is preserved so a partial edit omitting it (the model
                # defaults to "classic") never demotes a wiki.
                if "kind" in body and body["kind"] != current_config.kind:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": (
                                    "Change wiki mode via "
                                    "POST /api/sources/<id>/wiki/convert, "
                                    "not the config endpoint."
                                ),
                            }
                        ),
                        400,
                    )
                new_config.kind = current_config.kind
                requires_reingest = (
                    new_config.chunking.model_dump()
                    != current_config.chunking.model_dump()
                )
                repo.update(
                    str(doc["id"]), owner, {"config": new_config.model_dump()}
                )
        except Exception as err:
            current_app.logger.error(
                f"Error updating source config for {source_id}: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)

        return make_response(
            jsonify(
                {
                    "success": True,
                    "config": new_config.model_dump(),
                    "requires_reingest": requires_reingest,
                }
            ),
            200,
        )


def _resolve_readable_source(conn, source_id, user):
    """Return a source dict the caller may READ, or None.

    Read access = owner or any team grant (viewer/editor). Resolves the row
    without ownership scoping only after the grant check passes.
    """
    doc = SourcesRepository(conn).get_any(source_id, user)
    if doc is not None:
        return doc
    if not can_access(conn, "source", source_id, user):
        return None
    return SourcesRepository(conn).get_by_id(source_id)


def _wiki_page_node(page):
    return {
        "path": page.get("path"),
        "title": page.get("title"),
        "token_count": page.get("token_count") or 0,
        "version": page.get("version"),
        "embed_status": page.get("embed_status"),
        "updated_by": page.get("updated_by"),
        "updated_via": page.get("updated_via"),
        "updated_at": (
            page["updated_at"].isoformat()
            if page.get("updated_at") is not None
            and hasattr(page["updated_at"], "isoformat")
            else page.get("updated_at")
        ),
    }


_wiki_page_edit_model = sources_ns.model(
    "WikiPageEditModel",
    {
        "path": fields.String(required=True, description="Page path"),
        "content": fields.String(required=True, description="Markdown content"),
        "expected_version": fields.Integer(
            description="Optimistic-lock version from the last read"
        ),
    },
)


@sources_ns.route("/sources/wiki")
class CreateWikiSource(Resource):
    create_wiki_model = api.model(
        "CreateWikiModel",
        {
            "name": fields.String(required=True, description="Wiki source name"),
            "initial_content": fields.String(
                description="Optional markdown seed for /index.md"
            ),
        },
    )

    @api.expect(create_wiki_model)
    @api.doc(
        description="Create an LLM-editable wiki source. No ingestion task is "
        "enqueued; pages are authored via the WikiTool. An optional "
        "initial_content seeds /index.md and triggers its per-page re-embed."
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json(silent=True) or {}
        missing_fields = check_required_fields(data, ["name"])
        if missing_fields:
            return missing_fields
        name = str(data["name"]).strip()
        if not name:
            return make_response(
                jsonify({"success": False, "message": "Name is required"}), 400
            )
        initial_content = data.get("initial_content")
        source_id = str(uuid.uuid4())
        try:
            with db_session() as conn:
                repo = SourcesRepository(conn)
                repo.create(
                    name,
                    source_id=source_id,
                    user_id=user,
                    type="wiki",
                    config={"kind": "wiki"},
                    directory_structure={},
                    tokens=0,
                )
                if initial_content:
                    WikiPagesRepository(conn).upsert(
                        source_id,
                        WIKI_INDEX_PATH,
                        initial_content,
                        updated_by=user,
                        updated_via="human",
                    )
                    rebuild_wiki_directory_structure(conn, source_id, user)
        except Exception as err:
            current_app.logger.error(
                f"Error creating wiki source: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        if initial_content:
            try:
                reembed_wiki_page.delay(
                    source_id,
                    WIKI_INDEX_PATH,
                    _content_hash(initial_content),
                    user=user,
                    idempotency_key=(
                        f"reembed-wiki:{source_id}:{WIKI_INDEX_PATH}:"
                        f"{_content_hash(initial_content)}"
                    ),
                )
            except Exception as err:
                current_app.logger.error(
                    f"Error enqueuing wiki seed re-embed for {source_id}: {err}",
                    exc_info=True,
                )
        return make_response(
            jsonify({"success": True, "source_id": source_id}), 200
        )


@sources_ns.route("/sources/<string:source_id>/wiki/pages")
class WikiPages(Resource):
    @api.doc(
        description="List a wiki source's pages (read access: owner or shared)."
    )
    def get(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                doc = _resolve_readable_source(conn, source_id, user)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                pages = WikiPagesRepository(conn).list_for_source(str(doc["id"]))
                directory_structure = doc.get("directory_structure") or {}
        except Exception as err:
            current_app.logger.error(
                f"Error listing wiki pages for {source_id}: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "pages": [_wiki_page_node(p) for p in pages],
                    "directory_structure": directory_structure,
                }
            ),
            200,
        )


@sources_ns.route("/sources/<string:source_id>/wiki/page")
class WikiPage(Resource):
    @api.doc(
        description="Fetch a single wiki page's content fresh from storage.",
        params={"path": "Page path (e.g. /index.md)"},
    )
    def get(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        raw_path = request.args.get("path")
        if not raw_path:
            return make_response(
                jsonify({"success": False, "message": "path is required"}), 400
            )
        path = validate_tool_path(raw_path)
        if not path or path == "/" or path.endswith("/"):
            return make_response(
                jsonify({"success": False, "message": "Invalid page path"}), 400
            )
        try:
            with db_readonly() as conn:
                doc = _resolve_readable_source(conn, source_id, user)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                page = WikiPagesRepository(conn).get_by_path(str(doc["id"]), path)
        except Exception as err:
            current_app.logger.error(
                f"Error fetching wiki page for {source_id}: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        if page is None:
            return make_response(
                jsonify({"success": False, "message": "Page not found"}), 404
            )
        node = _wiki_page_node(page)
        node["content"] = page.get("content") or ""
        return make_response(jsonify({"success": True, "page": node}), 200)

    @api.expect(_wiki_page_edit_model)
    @api.doc(
        description="Create or overwrite a wiki page (human edit). Write access "
        "required; a stale expected_version returns 409."
    )
    def put(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json(silent=True) or {}
        missing_fields = check_required_fields(data, ["path", "content"])
        if missing_fields:
            return missing_fields
        path = validate_tool_path(data["path"])
        if not path or path == "/" or path.endswith("/"):
            return make_response(
                jsonify({"success": False, "message": "Invalid page path"}), 400
            )
        content = data["content"]
        expected_version = data.get("expected_version")
        try:
            with db_session() as conn:
                owner = effective_write_owner(conn, "source", source_id, user)
                if not owner:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Source not accessible"}
                        ),
                        403,
                    )
                doc = SourcesRepository(conn).get_any(source_id, owner)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                resolved_source_id = str(doc["id"])
                try:
                    page = WikiPagesRepository(conn).upsert(
                        resolved_source_id,
                        path,
                        content,
                        updated_by=user,
                        updated_via="human",
                        expected_version=expected_version,
                    )
                except WikiPageConflict:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": (
                                    "Page changed since you loaded it. "
                                    "Reload and reapply your edit."
                                ),
                            }
                        ),
                        409,
                    )
                rebuild_wiki_directory_structure(conn, resolved_source_id, owner)
        except Exception as err:
            current_app.logger.error(
                f"Error editing wiki page for {source_id}: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            reembed_wiki_page.delay(
                resolved_source_id,
                path,
                _content_hash(content),
                user=owner,
                idempotency_key=(
                    f"reembed-wiki:{resolved_source_id}:{path}:"
                    f"{_content_hash(content)}"
                ),
            )
        except Exception as err:
            current_app.logger.error(
                f"Error enqueuing wiki re-embed for {source_id}: {err}",
                exc_info=True,
            )
        return make_response(
            jsonify({"success": True, "page": _wiki_page_node(page)}), 200
        )


def _source_is_blank(doc):
    """True when a source has no ingested files to convert into pages."""
    structure = doc.get("directory_structure") or {}
    if isinstance(structure, str):
        try:
            structure = json.loads(structure)
        except Exception:
            structure = {}
    return not bool(structure)


def _enable_wiki_inline(conn, doc, owner):
    """Flip a blank source to wiki mode + agentic exposure with no task."""
    cfg = SourceConfig.parse(doc.get("config"))
    SourcesRepository(conn).update(
        str(doc["id"]), owner, {"config": cfg.wiki_enabled()}
    )


@sources_ns.route("/sources/<string:source_id>/wiki/convert")
class ConvertSourceToWiki(Resource):
    @api.doc(
        description="Convert an ingested source into a wiki. A blank source is "
        "enabled inline; a source with files runs a conversion task (poll its "
        "status for the per-file summary). Write access required (owner/editor)."
    )
    def post(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                owner = effective_write_owner(conn, "source", source_id, user)
                if not owner:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Source not accessible"}
                        ),
                        403,
                    )
                doc = SourcesRepository(conn).get_any(source_id, owner)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                resolved_source_id = str(doc["id"])
                # A mid-ingest source has an incomplete directory structure, so
                # it could be mis-detected as blank and wrongly enabled inline.
                # Reject while an embed is still in flight (mirrors the
                # "processing" ingest status the sources list derives).
                progress = IngestChunkProgressRepository(conn).get_progress(
                    resolved_source_id
                )
                if (
                    progress
                    and progress.get("status") != "stalled"
                    and (progress.get("embedded_chunks") or 0)
                    < (progress.get("total_chunks") or 0)
                ):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": (
                                    "Source is still ingesting; wait for it to "
                                    "finish before converting to a wiki."
                                ),
                            }
                        ),
                        409,
                    )
                cfg = SourceConfig.parse(doc.get("config"))
                if cfg.kind == "wiki":
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "converted": False,
                                "enabled": True,
                            }
                        ),
                        200,
                    )
                if _source_is_blank(doc):
                    _enable_wiki_inline(conn, doc, owner)
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "converted": False,
                                "enabled": True,
                            }
                        ),
                        200,
                    )
        except Exception as err:
            current_app.logger.error(
                f"Error preparing wiki conversion for {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            task = convert_source_to_wiki.delay(
                source_id=resolved_source_id,
                user=owner,
                idempotency_key=f"convert-wiki:{resolved_source_id}",
            )
        except Exception as err:
            current_app.logger.error(
                f"Error starting wiki conversion for {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "task_id": task.id}), 200
        )


@sources_ns.route("/sources/<string:source_id>/graphrag/enable")
class EnableSourceGraphRAG(Resource):
    @api.doc(
        description="Enable GraphRAG on a source: flips its config to graphrag "
        "mode and enqueues graph extraction over its embedded chunks. Requires "
        "VECTOR_STORE=pgvector and GRAPHRAG_ENABLED. Write access required "
        "(owner/editor). The config kind cannot be set to graphrag via the "
        "config PATCH endpoint."
    )
    def post(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        if not graphrag_available():
            current_app.logger.warning(
                "GraphRAG enable rejected for %s: unavailable "
                "(VECTOR_STORE=%s, GRAPHRAG_ENABLED=%s)",
                source_id,
                settings.VECTOR_STORE,
                settings.GRAPHRAG_ENABLED,
            )
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "GraphRAG isn't available on this workspace.",
                    }
                ),
                400,
            )
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                owner = effective_write_owner(conn, "source", source_id, user)
                if not owner:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Source not accessible"}
                        ),
                        403,
                    )
                doc = SourcesRepository(conn).get_any(source_id, owner)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                resolved_source_id = str(doc["id"])
                cfg = SourceConfig.parse(doc.get("config"))
                repo = SourcesRepository(conn)
                repo.update(
                    resolved_source_id, owner, {"config": cfg.graph_enabled()}
                )
                # Re-read after the config write — it bumps ``updated_at``,
                # which keys the extraction so each enable re-runs.
                updated = repo.get_any(resolved_source_id, owner)
        except Exception as err:
            current_app.logger.error(
                f"Error enabling GraphRAG for {source_id}: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            from application.worker import (
                _source_updated_at,
                graph_extraction_key,
            )

            task = extract_graph.delay(
                resolved_source_id,
                owner,
                idempotency_key=graph_extraction_key(
                    resolved_source_id, _source_updated_at(updated)
                ),
            )
        except Exception as err:
            current_app.logger.error(
                f"Error starting GraphRAG extraction for {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "task_id": task.id}), 200
        )


def _graph_overview_payload(source_id, limit):
    """Return a bounded ``{nodes, edges}`` overview for a graphrag source.

    An empty graph (extraction pending/capped/failed) yields empty lists rather
    than an error, mirroring the ClassicRAG degradation guarantee.
    """
    from application.graphrag.store import GraphStore

    store = GraphStore()
    if store.count_nodes(source_id) == 0:
        return {"nodes": [], "edges": []}
    return store.get_graph_overview(source_id, limit)


@sources_ns.route("/sources/<string:source_id>/graph")
class SourceGraph(Resource):
    @api.doc(
        description="Bounded knowledge-graph overview for a graphrag source: "
        "top nodes by degree and the edges among them (read access: owner or "
        "shared). Returns empty lists when no graph has been built yet."
    )
    def get(self, source_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            limit = int(request.args.get("limit", 0)) or None
        except (TypeError, ValueError):
            limit = None
        try:
            with db_readonly() as conn:
                doc = _resolve_readable_source(conn, source_id, user)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                resolved_source_id = str(doc["id"])
        except Exception as err:
            current_app.logger.error(
                f"Error resolving source {source_id} for graph: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            from application.graphrag.store import GRAPH_OVERVIEW_DEFAULT_LIMIT

            overview = _graph_overview_payload(
                resolved_source_id, limit or GRAPH_OVERVIEW_DEFAULT_LIMIT
            )
        except Exception as err:
            current_app.logger.error(
                f"Error building graph overview for {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "nodes": overview["nodes"],
                    "edges": overview["edges"],
                }
            ),
            200,
        )


@sources_ns.route("/sources/<string:source_id>/graph/node/<string:node_id>")
class SourceGraphNode(Resource):
    @api.doc(
        description="A graph node's description and its linked chunks (read "
        "access: owner or shared)."
    )
    def get(self, source_id, node_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                doc = _resolve_readable_source(conn, source_id, user)
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                resolved_source_id = str(doc["id"])
        except Exception as err:
            current_app.logger.error(
                f"Error resolving source {source_id} for graph node: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            from application.graphrag.store import GraphStore

            node = GraphStore().get_node_detail(resolved_source_id, node_id)
        except Exception as err:
            current_app.logger.error(
                f"Error fetching graph node {node_id} for {source_id}: {err}",
                exc_info=True,
            )
            return make_response(jsonify({"success": False}), 400)
        if node is None:
            return make_response(
                jsonify({"success": False, "message": "Node not found"}), 404
            )
        return make_response(jsonify({"success": True, "node": node}), 200)
