"""Source document management routes."""

import json
import math
import os

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import fields, Namespace, Resource
from werkzeug.utils import secure_filename

from application.api import api
from application.api.user.base import sources_collection
from application.core.settings import settings
from application.storage.storage_creator import StorageCreator
from application.utils import check_required_fields
from application.vectorstore.vector_creator import VectorCreator


sources_ns = Namespace(
    "sources", description="Source document management operations", path="/api"
)


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
            for index in sources_collection.find({"user": user}).sort("date", -1):
                data.append(
                    {
                        "id": str(index["_id"]),
                        "name": index.get("name"),
                        "date": index.get("date"),
                        "model": settings.EMBEDDINGS_NAME,
                        "location": "local",
                        "tokens": index.get("tokens", ""),
                        "retriever": index.get("retriever", "classic"),
                        "syncFrequency": index.get("sync_frequency", ""),
                        "is_nested": bool(index.get("directory_structure")),
                        "type": index.get(
                            "type", "file"
                        ),  # Add type field with default "file"
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
        sort_field = request.args.get("sort", "date")  # Default to 'date'
        sort_order = request.args.get("order", "desc")  # Default to 'desc'
        page = int(request.args.get("page", 1))  # Default to 1
        rows_per_page = int(request.args.get("rows", 10))  # Default to 10
        # add .strip() to remove leading and trailing whitespaces

        search_term = request.args.get(
            "search", ""
        ).strip()  # add search for filter documents

        # Prepare query for filtering

        query = {"user": user}
        if search_term:
            query["name"] = {
                "$regex": search_term,
                "$options": "i",  # using case-insensitive search
            }
        total_documents = sources_collection.count_documents(query)
        total_pages = max(1, math.ceil(total_documents / rows_per_page))
        page = min(
            max(1, page), total_pages
        )  # add this to make sure page inbound is within the range
        sort_order = 1 if sort_order == "asc" else -1
        skip = (page - 1) * rows_per_page

        try:
            documents = (
                sources_collection.find(query)
                .sort(sort_field, sort_order)
                .skip(skip)
                .limit(rows_per_page)
            )

            paginated_docs = []
            for doc in documents:
                doc_data = {
                    "id": str(doc["_id"]),
                    "name": doc.get("name", ""),
                    "date": doc.get("date", ""),
                    "model": settings.EMBEDDINGS_NAME,
                    "location": "local",
                    "tokens": doc.get("tokens", ""),
                    "retriever": doc.get("retriever", "classic"),
                    "syncFrequency": doc.get("sync_frequency", ""),
                    "isNested": bool(doc.get("directory_structure")),
                    "type": doc.get("type", "file"),
                }
                paginated_docs.append(doc_data)
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


@sources_ns.route("/docs_check")
class CheckDocs(Resource):
    check_docs_model = api.model(
        "CheckDocsModel",
        {"docs": fields.String(required=True, description="Document name")},
    )

    @api.expect(check_docs_model)
    @api.doc(description="Check if document exists")
    def post(self):
        data = request.get_json()
        required_fields = ["docs"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            vectorstore = "vectors/" + secure_filename(data["docs"])
            if os.path.exists(vectorstore) or data["docs"] == "default":
                return {"status": "exists"}, 200
        except Exception as err:
            current_app.logger.error(f"Error checking document: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"status": "not found"}), 404)


@sources_ns.route("/delete_by_ids")
class DeleteByIds(Resource):
    @api.doc(
        description="Deletes documents from the vector store by IDs",
        params={"path": "Comma-separated list of IDs"},
    )
    def get(self):
        ids = request.args.get("path")
        if not ids:
            return make_response(
                jsonify({"success": False, "message": "Missing required fields"}), 400
            )
        try:
            result = sources_collection.delete_index(ids=ids)
            if result:
                return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            current_app.logger.error(f"Error deleting indexes: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
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
        source_id = request.args.get("source_id")
        if not source_id:
            return make_response(
                jsonify({"success": False, "message": "Missing required fields"}), 400
            )
        doc = sources_collection.find_one(
            {"_id": ObjectId(source_id), "user": decoded_token.get("sub")}
        )
        if not doc:
            return make_response(jsonify({"status": "not found"}), 404)
        storage = StorageCreator.get_storage()

        try:
            # Delete vector index

            if settings.VECTOR_STORE == "faiss":
                index_path = f"indexes/{str(doc['_id'])}"
                if storage.file_exists(f"{index_path}/index.faiss"):
                    storage.delete_file(f"{index_path}/index.faiss")
                if storage.file_exists(f"{index_path}/index.pkl"):
                    storage.delete_file(f"{index_path}/index.pkl")
            else:
                vectorstore = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE, source_id=str(doc["_id"])
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
        sources_collection.delete_one({"_id": ObjectId(source_id)})
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
        data = request.get_json()
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
        update_data = {"$set": {"sync_frequency": sync_frequency}}
        try:
            sources_collection.update_one(
                {
                    "_id": ObjectId(source_id),
                    "user": user,
                },
                update_data,
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating sync frequency: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


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
        if not ObjectId.is_valid(doc_id):
            return make_response(jsonify({"error": "Invalid document ID"}), 400)
        try:
            doc = sources_collection.find_one({"_id": ObjectId(doc_id), "user": user})
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
            return make_response(jsonify({"success": False, "error": str(e)}), 500)
