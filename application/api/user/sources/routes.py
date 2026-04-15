"""Source document management routes."""

import json
import math

from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.tasks import sync_source
from application.core.settings import settings
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.session import db_readonly, db_session
from application.storage.storage_creator import StorageCreator
from application.utils import check_required_fields
from application.vectorstore.vector_creator import VectorCreator


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
                indexes = SourcesRepository(conn).list_for_user(user)
            # list_for_user sorts by created_at DESC; legacy shape sorted by
            # "date" DESC. Both are monotonic on creation so the ordering is
            # equivalent for dev; re-sort defensively.
            indexes = sorted(
                indexes, key=lambda r: r.get("date") or r.get("created_at") or "",
                reverse=True,
            )
            for index in indexes:
                provider = _get_provider_from_remote_data(index.get("remote_data"))
                data.append(
                    {
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
                    }
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
        page = int(request.args.get("page", 1))
        rows_per_page = int(request.args.get("rows", 10))
        search_term = request.args.get("search", "").strip()

        try:
            with db_readonly() as conn:
                all_docs = SourcesRepository(conn).list_for_user(user)
            # Case-insensitive substring filter on name (matches legacy
            # Mongo $regex with $options:"i" for typical search UX).
            if search_term:
                needle = search_term.lower()
                all_docs = [
                    d for d in all_docs
                    if needle in (d.get("name") or "").lower()
                ]

            reverse = sort_order != "asc"
            all_docs.sort(
                key=lambda d: (d.get(sort_field) is None, d.get(sort_field)),
                reverse=reverse,
            )

            total_documents = len(all_docs)
            total_pages = max(1, math.ceil(total_documents / rows_per_page))
            page = min(max(1, page), total_pages)
            skip = (page - 1) * rows_per_page
            window = all_docs[skip : skip + rows_per_page]

            paginated_docs = []
            for doc in window:
                provider = _get_provider_from_remote_data(doc.get("remote_data"))
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
                    }
                )
            response = {
                "total": total_documents,
                "totalPages": total_pages,
                "currentPage": page,
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
                if doc is None:
                    return make_response(
                        jsonify({"success": False, "message": "Source not found"}),
                        404,
                    )
                repo.update(str(doc["id"]), user, {"sync_frequency": sync_frequency})
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
        try:
            with db_readonly() as conn:
                doc = SourcesRepository(conn).get_any(source_id, user)
        except Exception as err:
            current_app.logger.error(f"Error looking up source: {err}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Invalid source ID"}), 400
            )
        if not doc:
            return make_response(
                jsonify({"success": False, "message": "Source not found"}), 404
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
        source_data = doc.get("remote_data")
        if not source_data:
            return make_response(
                jsonify({"success": False, "message": "Source is not syncable"}), 400
            )
        try:
            task = sync_source.delay(
                source_data=source_data,
                job_name=doc.get("name", ""),
                user=user,
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
