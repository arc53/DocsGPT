"""Source document management chunk management."""

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import get_vector_store, sources_collection
from application.utils import check_required_fields, num_tokens_from_string

sources_chunks_ns = Namespace(
    "sources", description="Source document management operations", path="/api"
)


@sources_chunks_ns.route("/get_chunks")
class GetChunks(Resource):
    @api.doc(
        description="Retrieves chunks from a document, optionally filtered by file path and search term",
        params={
            "id": "The document ID",
            "page": "Page number for pagination",
            "per_page": "Number of chunks per page",
            "path": "Optional: Filter chunks by relative file path",
            "search": "Optional: Search term to filter chunks by title or content",
        },
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        doc_id = request.args.get("id")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))
        path = request.args.get("path")
        search_term = request.args.get("search", "").strip().lower()

        if not ObjectId.is_valid(doc_id):
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        doc = sources_collection.find_one({"_id": ObjectId(doc_id), "user": user})
        if not doc:
            return make_response(
                jsonify({"error": "Document not found or access denied"}), 404
            )
        try:
            store = get_vector_store(doc_id)
            chunks = store.get_chunks()

            filtered_chunks = []
            for chunk in chunks:
                metadata = chunk.get("metadata", {})

                # Filter by path if provided

                if path:
                    chunk_source = metadata.get("source", "")
                    chunk_file_path = metadata.get("file_path", "")
                    # Check if the chunk matches the requested path
                    # For file uploads: source ends with path (e.g., "inputs/.../file.pdf" ends with "file.pdf")
                    # For crawlers: file_path ends with path (e.g., "guides/setup.md" ends with "setup.md")
                    source_match = chunk_source and chunk_source.endswith(path)
                    file_path_match = chunk_file_path and chunk_file_path.endswith(path)

                    if not (source_match or file_path_match):
                        continue
                # Filter by search term if provided

                if search_term:
                    text_match = search_term in chunk.get("text", "").lower()
                    title_match = search_term in metadata.get("title", "").lower()

                    if not (text_match or title_match):
                        continue
                filtered_chunks.append(chunk)
            chunks = filtered_chunks

            total_chunks = len(chunks)
            start = (page - 1) * per_page
            end = start + per_page
            paginated_chunks = chunks[start:end]

            return make_response(
                jsonify(
                    {
                        "page": page,
                        "per_page": per_page,
                        "total": total_chunks,
                        "chunks": paginated_chunks,
                        "path": path if path else None,
                        "search": search_term if search_term else None,
                    }
                ),
                200,
            )
        except Exception as e:
            current_app.logger.error(f"Error getting chunks: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


@sources_chunks_ns.route("/add_chunk")
class AddChunk(Resource):
    @api.expect(
        api.model(
            "AddChunkModel",
            {
                "id": fields.String(required=True, description="Document ID"),
                "text": fields.String(required=True, description="Text of the chunk"),
                "metadata": fields.Raw(
                    required=False,
                    description="Metadata associated with the chunk",
                ),
            },
        )
    )
    @api.doc(
        description="Adds a new chunk to the document",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "text"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        doc_id = data.get("id")
        text = data.get("text")
        metadata = data.get("metadata", {})
        token_count = num_tokens_from_string(text)
        metadata["token_count"] = token_count

        if not ObjectId.is_valid(doc_id):
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        doc = sources_collection.find_one({"_id": ObjectId(doc_id), "user": user})
        if not doc:
            return make_response(
                jsonify({"error": "Document not found or access denied"}), 404
            )
        try:
            store = get_vector_store(doc_id)
            chunk_id = store.add_chunk(text, metadata)
            return make_response(
                jsonify({"message": "Chunk added successfully", "chunk_id": chunk_id}),
                201,
            )
        except Exception as e:
            current_app.logger.error(f"Error adding chunk: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


@sources_chunks_ns.route("/delete_chunk")
class DeleteChunk(Resource):
    @api.doc(
        description="Deletes a specific chunk from the document.",
        params={"id": "The document ID", "chunk_id": "The ID of the chunk to delete"},
    )
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        doc_id = request.args.get("id")
        chunk_id = request.args.get("chunk_id")

        if not ObjectId.is_valid(doc_id):
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        doc = sources_collection.find_one({"_id": ObjectId(doc_id), "user": user})
        if not doc:
            return make_response(
                jsonify({"error": "Document not found or access denied"}), 404
            )
        try:
            store = get_vector_store(doc_id)
            deleted = store.delete_chunk(chunk_id)
            if deleted:
                return make_response(
                    jsonify({"message": "Chunk deleted successfully"}), 200
                )
            else:
                return make_response(
                    jsonify({"message": "Chunk not found or could not be deleted"}),
                    404,
                )
        except Exception as e:
            current_app.logger.error(f"Error deleting chunk: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)


@sources_chunks_ns.route("/update_chunk")
class UpdateChunk(Resource):
    @api.expect(
        api.model(
            "UpdateChunkModel",
            {
                "id": fields.String(required=True, description="Document ID"),
                "chunk_id": fields.String(
                    required=True, description="Chunk ID to update"
                ),
                "text": fields.String(
                    required=False, description="New text of the chunk"
                ),
                "metadata": fields.Raw(
                    required=False,
                    description="Updated metadata associated with the chunk",
                ),
            },
        )
    )
    @api.doc(
        description="Updates an existing chunk in the document.",
    )
    def put(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "chunk_id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        doc_id = data.get("id")
        chunk_id = data.get("chunk_id")
        text = data.get("text")
        metadata = data.get("metadata")

        if text is not None:
            token_count = num_tokens_from_string(text)
            if metadata is None:
                metadata = {}
            metadata["token_count"] = token_count
        if not ObjectId.is_valid(doc_id):
            return make_response(jsonify({"error": "Invalid doc_id"}), 400)
        doc = sources_collection.find_one({"_id": ObjectId(doc_id), "user": user})
        if not doc:
            return make_response(
                jsonify({"error": "Document not found or access denied"}), 404
            )
        try:
            store = get_vector_store(doc_id)

            chunks = store.get_chunks()
            existing_chunk = next((c for c in chunks if c["doc_id"] == chunk_id), None)
            if not existing_chunk:
                return make_response(jsonify({"error": "Chunk not found"}), 404)
            new_text = text if text is not None else existing_chunk["text"]

            if metadata is not None:
                new_metadata = existing_chunk["metadata"].copy()
                new_metadata.update(metadata)
            else:
                new_metadata = existing_chunk["metadata"].copy()
            if text is not None:
                new_metadata["token_count"] = num_tokens_from_string(new_text)
            try:
                new_chunk_id = store.add_chunk(new_text, new_metadata)

                deleted = store.delete_chunk(chunk_id)
                if not deleted:
                    current_app.logger.warning(
                        f"Failed to delete old chunk {chunk_id}, but new chunk {new_chunk_id} was created"
                    )
                return make_response(
                    jsonify(
                        {
                            "message": "Chunk updated successfully",
                            "chunk_id": new_chunk_id,
                            "original_chunk_id": chunk_id,
                        }
                    ),
                    200,
                )
            except Exception as add_error:
                current_app.logger.error(f"Failed to add updated chunk: {add_error}")
                return make_response(
                    jsonify({"error": "Failed to update chunk - addition failed"}), 500
                )
        except Exception as e:
            current_app.logger.error(f"Error updating chunk: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 500)
