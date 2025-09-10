import datetime
import json
import math
import os
import secrets
import tempfile
import uuid
import zipfile
from functools import wraps
from typing import Optional, Tuple

from bson.binary import Binary, UuidRepresentation
from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    Response,
)
from flask_restx import fields, inputs, Namespace, Resource
from pymongo import ReturnDocument
from werkzeug.utils import secure_filename

from application.agents.tools.mcp_tool import MCPTool

from application.agents.tools.tool_manager import ToolManager
from application.api import api

from application.api.user.tasks import (
    ingest,
    ingest_remote,
    process_agent_webhook,
    store_attachment,
)
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.security.encryption import encrypt_credentials, decrypt_credentials
from application.storage.storage_creator import StorageCreator
from application.tts.google_tts import GoogleTTS
from application.utils import (
    check_required_fields,
    generate_image_url,
    num_tokens_from_string,
    safe_filename,
    validate_function_name,
    validate_required_fields,
)
from application.vectorstore.vector_creator import VectorCreator

storage = StorageCreator.get_storage()

mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]
conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
feedback_collection = db["feedback"]
agents_collection = db["agents"]
token_usage_collection = db["token_usage"]
shared_conversations_collections = db["shared_conversations"]
users_collection = db["users"]
user_logs_collection = db["user_logs"]
user_tools_collection = db["user_tools"]
attachments_collection = db["attachments"]

try:
    agents_collection.create_index(
        [("shared", 1)],
        name="shared_index",
        background=True,
    )
    users_collection.create_index("user_id", unique=True)
except Exception as e:
    print("Error creating indexes:", e)

user = Blueprint("user", __name__)
user_ns = Namespace("user", description="User related operations", path="/")
api.add_namespace(user_ns)

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

tool_config = {}
tool_manager = ToolManager(config=tool_config)


def generate_minute_range(start_date, end_date):
    return {
        (start_date + datetime.timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:00"): 0
        for i in range(int((end_date - start_date).total_seconds() // 60) + 1)
    }


def generate_hourly_range(start_date, end_date):
    return {
        (start_date + datetime.timedelta(hours=i)).strftime("%Y-%m-%d %H:00"): 0
        for i in range(int((end_date - start_date).total_seconds() // 3600) + 1)
    }


def generate_date_range(start_date, end_date):
    return {
        (start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d"): 0
        for i in range((end_date - start_date).days + 1)
    }


def ensure_user_doc(user_id):
    default_prefs = {
        "pinned": [],
        "shared_with_me": [],
    }

    user_doc = users_collection.find_one_and_update(
        {"user_id": user_id},
        {"$setOnInsert": {"agent_preferences": default_prefs}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    prefs = user_doc.get("agent_preferences", {})
    updates = {}
    if "pinned" not in prefs:
        updates["agent_preferences.pinned"] = []
    if "shared_with_me" not in prefs:
        updates["agent_preferences.shared_with_me"] = []

    if updates:
        users_collection.update_one({"user_id": user_id}, {"$set": updates})
        user_doc = users_collection.find_one({"user_id": user_id})

    return user_doc


def resolve_tool_details(tool_ids):
    tools = user_tools_collection.find(
        {"_id": {"$in": [ObjectId(tid) for tid in tool_ids]}}
    )
    return [
        {
            "id": str(tool["_id"]),
            "name": tool.get("name", ""),
            "display_name": tool.get("displayName", tool.get("name", "")),
        }
        for tool in tools
    ]


def get_vector_store(source_id):
    """
    Get the Vector Store
    Args:
        source_id (str): source id of the document
    """

    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE,
        source_id=source_id,
        embeddings_key=os.getenv("EMBEDDINGS_KEY"),
    )
    return store


def handle_image_upload(
    request, existing_url: str, user: str, storage, base_path: str = "attachments/"
) -> Tuple[str, Optional[Response]]:
    image_url = existing_url

    if "image" in request.files:
        file = request.files["image"]
        if file.filename != "":
            filename = secure_filename(file.filename)
            upload_path = f"{settings.UPLOAD_FOLDER.rstrip('/')}/{user}/{base_path.rstrip('/')}/{uuid.uuid4()}_{filename}"
            try:
                storage.save_file(file, upload_path, storage_class="STANDARD")
                image_url = upload_path
            except Exception as e:
                current_app.logger.error(f"Error uploading image: {e}")
                return None, make_response(
                    jsonify({"success": False, "message": "Image upload failed"}),
                    400,
                )

    return image_url, None


@user_ns.route("/api/delete_conversation")
class DeleteConversation(Resource):
    @api.doc(
        description="Deletes a conversation by ID",
        params={"id": "The ID of the conversation to delete"},
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        conversation_id = request.args.get("id")
        if not conversation_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            conversations_collection.delete_one(
                {"_id": ObjectId(conversation_id), "user": decoded_token["sub"]}
            )
        except Exception as err:
            current_app.logger.error(
                f"Error deleting conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/delete_all_conversations")
class DeleteAllConversations(Resource):
    @api.doc(
        description="Deletes all conversations for a specific user",
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        try:
            conversations_collection.delete_many({"user": user_id})
        except Exception as err:
            current_app.logger.error(
                f"Error deleting all conversations: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/get_conversations")
class GetConversations(Resource):
    @api.doc(
        description="Retrieve a list of the latest 30 conversations (excluding API key conversations)",
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        try:
            conversations = (
                conversations_collection.find(
                    {
                        "$or": [
                            {"api_key": {"$exists": False}},
                            {"agent_id": {"$exists": True}},
                        ],
                        "user": decoded_token.get("sub"),
                    }
                )
                .sort("date", -1)
                .limit(30)
            )

            list_conversations = [
                {
                    "id": str(conversation["_id"]),
                    "name": conversation["name"],
                    "agent_id": conversation.get("agent_id", None),
                    "is_shared_usage": conversation.get("is_shared_usage", False),
                    "shared_token": conversation.get("shared_token", None),
                }
                for conversation in conversations
            ]
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving conversations: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_conversations), 200)


@user_ns.route("/api/get_single_conversation")
class GetSingleConversation(Resource):
    @api.doc(
        description="Retrieve a single conversation by ID",
        params={"id": "The conversation ID"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        conversation_id = request.args.get("id")
        if not conversation_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            conversation = conversations_collection.find_one(
                {"_id": ObjectId(conversation_id), "user": decoded_token.get("sub")}
            )
            if not conversation:
                return make_response(jsonify({"status": "not found"}), 404)

            # Process queries to include attachment names
            queries = conversation["queries"]
            for query in queries:
                if "attachments" in query and query["attachments"]:
                    attachment_details = []
                    for attachment_id in query["attachments"]:
                        try:
                            attachment = attachments_collection.find_one(
                                {"_id": ObjectId(attachment_id)}
                            )
                            if attachment:
                                attachment_details.append(
                                    {
                                        "id": str(attachment["_id"]),
                                        "fileName": attachment.get(
                                            "filename", "Unknown file"
                                        ),
                                    }
                                )
                        except Exception as e:
                            current_app.logger.error(
                                f"Error retrieving attachment {attachment_id}: {e}",
                                exc_info=True,
                            )
                    query["attachments"] = attachment_details
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        data = {
            "queries": queries,
            "agent_id": conversation.get("agent_id"),
            "is_shared_usage": conversation.get("is_shared_usage", False),
            "shared_token": conversation.get("shared_token", None),
        }
        return make_response(jsonify(data), 200)


@user_ns.route("/api/update_conversation_name")
class UpdateConversationName(Resource):
    @api.expect(
        api.model(
            "UpdateConversationModel",
            {
                "id": fields.String(required=True, description="Conversation ID"),
                "name": fields.String(
                    required=True, description="New name of the conversation"
                ),
            },
        )
    )
    @api.doc(
        description="Updates the name of a conversation",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["id", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            conversations_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": decoded_token.get("sub")},
                {"$set": {"name": data["name"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating conversation name: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/feedback")
class SubmitFeedback(Resource):
    @api.expect(
        api.model(
            "FeedbackModel",
            {
                "question": fields.String(
                    required=False, description="The user question"
                ),
                "answer": fields.String(required=False, description="The AI answer"),
                "feedback": fields.String(required=True, description="User feedback"),
                "question_index": fields.Integer(
                    required=True,
                    description="The question number in that particular conversation",
                ),
                "conversation_id": fields.String(
                    required=True, description="id of the particular conversation"
                ),
                "api_key": fields.String(description="Optional API key"),
            },
        )
    )
    @api.doc(
        description="Submit feedback for a conversation",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["feedback", "conversation_id", "question_index"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            if data["feedback"] is None:
                # Remove feedback and feedback_timestamp if feedback is null

                conversations_collection.update_one(
                    {
                        "_id": ObjectId(data["conversation_id"]),
                        "user": decoded_token.get("sub"),
                        f"queries.{data['question_index']}": {"$exists": True},
                    },
                    {
                        "$unset": {
                            f"queries.{data['question_index']}.feedback": "",
                            f"queries.{data['question_index']}.feedback_timestamp": "",
                        }
                    },
                )
            else:
                # Set feedback and feedback_timestamp if feedback has a value

                conversations_collection.update_one(
                    {
                        "_id": ObjectId(data["conversation_id"]),
                        "user": decoded_token.get("sub"),
                        f"queries.{data['question_index']}": {"$exists": True},
                    },
                    {
                        "$set": {
                            f"queries.{data['question_index']}.feedback": data[
                                "feedback"
                            ],
                            f"queries.{data['question_index']}.feedback_timestamp": datetime.datetime.now(
                                datetime.timezone.utc
                            ),
                        }
                    },
                )
        except Exception as err:
            current_app.logger.error(f"Error submitting feedback: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/delete_by_ids")
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


@user_ns.route("/api/delete_old")
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


@user_ns.route("/api/upload")
class UploadFile(Resource):
    @api.expect(
        api.model(
            "UploadModel",
            {
                "user": fields.String(required=True, description="User ID"),
                "name": fields.String(required=True, description="Job name"),
                "file": fields.Raw(required=True, description="File(s) to upload"),
            },
        )
    )
    @api.doc(
        description="Uploads a file to be vectorized and indexed",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.form
        files = request.files.getlist("file")
        required_fields = ["user", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields or not files or all(file.filename == "" for file in files):
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "Missing required fields or files",
                    }
                ),
                400,
            )
        user = decoded_token.get("sub")
        job_name = request.form["name"]

        # Create safe versions for filesystem operations
        safe_user = safe_filename(user)
        dir_name = safe_filename(job_name)
        base_path = f"{settings.UPLOAD_FOLDER}/{safe_user}/{dir_name}"

        try:
            storage = StorageCreator.get_storage()

            for file in files:
                original_filename = file.filename
                safe_file = safe_filename(original_filename)

                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_file_path = os.path.join(temp_dir, safe_file)
                    file.save(temp_file_path)

                    if zipfile.is_zipfile(temp_file_path):
                        try:
                            with zipfile.ZipFile(temp_file_path, "r") as zip_ref:
                                zip_ref.extractall(path=temp_dir)

                                # Walk through extracted files and upload them
                                for root, _, files in os.walk(temp_dir):
                                    for extracted_file in files:
                                        if (
                                            os.path.join(root, extracted_file)
                                            == temp_file_path
                                        ):
                                            continue

                                        rel_path = os.path.relpath(
                                            os.path.join(root, extracted_file), temp_dir
                                        )
                                        storage_path = f"{base_path}/{rel_path}"

                                        with open(
                                            os.path.join(root, extracted_file), "rb"
                                        ) as f:
                                            storage.save_file(f, storage_path)
                        except Exception as e:
                            current_app.logger.error(
                                f"Error extracting zip: {e}", exc_info=True
                            )
                            # If zip extraction fails, save the original zip file
                            file_path = f"{base_path}/{safe_file}"
                            with open(temp_file_path, "rb") as f:
                                storage.save_file(f, file_path)
                    else:
                        # For non-zip files, save directly
                        file_path = f"{base_path}/{safe_file}"
                        with open(temp_file_path, "rb") as f:
                            storage.save_file(f, file_path)

            task = ingest.delay(
                settings.UPLOAD_FOLDER,
                [
                    ".rst",
                    ".md",
                    ".pdf",
                    ".txt",
                    ".docx",
                    ".csv",
                    ".epub",
                    ".html",
                    ".mdx",
                    ".json",
                    ".xlsx",
                    ".pptx",
                    ".png",
                    ".jpg",
                    ".jpeg",
                ],
                job_name,
                user,
                file_path=base_path,
                filename=dir_name,
            )
        except Exception as err:
            current_app.logger.error(f"Error uploading file: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


@user_ns.route("/api/manage_source_files")
class ManageSourceFiles(Resource):
    @api.expect(
        api.model(
            "ManageSourceFilesModel",
            {
                "source_id": fields.String(
                    required=True, description="Source ID to modify"
                ),
                "operation": fields.String(
                    required=True,
                    description="Operation: 'add', 'remove', or 'remove_directory'",
                ),
                "file_paths": fields.List(
                    fields.String,
                    required=False,
                    description="File paths to remove (for remove operation)",
                ),
                "directory_path": fields.String(
                    required=False,
                    description="Directory path to remove (for remove_directory operation)",
                ),
                "file": fields.Raw(
                    required=False, description="Files to add (for add operation)"
                ),
                "parent_dir": fields.String(
                    required=False,
                    description="Parent directory path relative to source root",
                ),
            },
        )
    )
    @api.doc(
        description="Add files, remove files, or remove directories from an existing source",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(
                jsonify({"success": False, "message": "Unauthorized"}), 401
            )

        user = decoded_token.get("sub")
        source_id = request.form.get("source_id")
        operation = request.form.get("operation")

        if not source_id or not operation:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "source_id and operation are required",
                    }
                ),
                400,
            )

        if operation not in ["add", "remove", "remove_directory"]:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "operation must be 'add', 'remove', or 'remove_directory'",
                    }
                ),
                400,
            )

        try:
            ObjectId(source_id)
        except Exception:
            return make_response(
                jsonify({"success": False, "message": "Invalid source ID format"}), 400
            )

        try:
            source = sources_collection.find_one(
                {"_id": ObjectId(source_id), "user": user}
            )
            if not source:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Source not found or access denied",
                        }
                    ),
                    404,
                )
        except Exception as err:
            current_app.logger.error(f"Error finding source: {err}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Database error"}), 500
            )

        try:
            storage = StorageCreator.get_storage()
            source_file_path = source.get("file_path", "")
            parent_dir = request.form.get("parent_dir", "")

            if parent_dir and (parent_dir.startswith("/") or ".." in parent_dir):
                return make_response(
                    jsonify(
                        {"success": False, "message": "Invalid parent directory path"}
                    ),
                    400,
                )

            if operation == "add":
                files = request.files.getlist("file")
                if not files or all(file.filename == "" for file in files):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "No files provided for add operation",
                            }
                        ),
                        400,
                    )

                added_files = []

                target_dir = source_file_path
                if parent_dir:
                    target_dir = f"{source_file_path}/{parent_dir}"

                for file in files:
                    if file.filename:
                        safe_filename_str = safe_filename(file.filename)
                        file_path = f"{target_dir}/{safe_filename_str}"

                        # Save file to storage
                        storage.save_file(file, file_path)
                        added_files.append(safe_filename_str)

                # Trigger re-ingestion pipeline
                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.delay(source_id=source_id, user=user)

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Added {len(added_files)} files",
                            "added_files": added_files,
                            "parent_dir": parent_dir,
                            "reingest_task_id": task.id,
                        }
                    ),
                    200,
                )

            elif operation == "remove":
                file_paths_str = request.form.get("file_paths")
                if not file_paths_str:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "file_paths required for remove operation",
                            }
                        ),
                        400,
                    )

                try:
                    file_paths = (
                        json.loads(file_paths_str)
                        if isinstance(file_paths_str, str)
                        else file_paths_str
                    )
                except Exception:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Invalid file_paths format"}
                        ),
                        400,
                    )

                # Remove files from storage and directory structure
                removed_files = []
                for file_path in file_paths:
                    full_path = f"{source_file_path}/{file_path}"

                    # Remove from storage
                    if storage.file_exists(full_path):
                        storage.delete_file(full_path)
                        removed_files.append(file_path)

                # Trigger re-ingestion pipeline
                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.delay(source_id=source_id, user=user)

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Removed {len(removed_files)} files",
                            "removed_files": removed_files,
                            "reingest_task_id": task.id,
                        }
                    ),
                    200,
                )

            elif operation == "remove_directory":
                directory_path = request.form.get("directory_path")
                if not directory_path:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "directory_path required for remove_directory operation",
                            }
                        ),
                        400,
                    )

                # Validate directory path (prevent path traversal)
                if directory_path.startswith("/") or ".." in directory_path:
                    current_app.logger.warning(
                        f"Invalid directory path attempted for removal. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}"
                    )
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Invalid directory path"}
                        ),
                        400,
                    )

                full_directory_path = (
                    f"{source_file_path}/{directory_path}"
                    if directory_path
                    else source_file_path
                )

                if not storage.is_directory(full_directory_path):
                    current_app.logger.warning(
                        f"Directory not found or is not a directory for removal. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                        f"Full path: {full_directory_path}"
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Directory not found or is not a directory",
                            }
                        ),
                        404,
                    )

                success = storage.remove_directory(full_directory_path)

                if not success:
                    current_app.logger.error(
                        f"Failed to remove directory from storage. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                        f"Full path: {full_directory_path}"
                    )
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Failed to remove directory"}
                        ),
                        500,
                    )

                current_app.logger.info(
                    f"Successfully removed directory. "
                    f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                    f"Full path: {full_directory_path}"
                )

                # Trigger re-ingestion pipeline
                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.delay(source_id=source_id, user=user)

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Successfully removed directory: {directory_path}",
                            "removed_directory": directory_path,
                            "reingest_task_id": task.id,
                        }
                    ),
                    200,
                )

        except Exception as err:
            error_context = f"operation={operation}, user={user}, source_id={source_id}"
            if operation == "remove_directory":
                directory_path = request.form.get("directory_path", "")
                error_context += f", directory_path={directory_path}"
            elif operation == "remove":
                file_paths_str = request.form.get("file_paths", "")
                error_context += f", file_paths={file_paths_str}"
            elif operation == "add":
                parent_dir = request.form.get("parent_dir", "")
                error_context += f", parent_dir={parent_dir}"

            current_app.logger.error(
                f"Error managing source files: {err} ({error_context})", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Operation failed"}), 500
            )


@user_ns.route("/api/remote")
class UploadRemote(Resource):
    @api.expect(
        api.model(
            "RemoteUploadModel",
            {
                "user": fields.String(required=True, description="User ID"),
                "source": fields.String(
                    required=True, description="Source of the data"
                ),
                "name": fields.String(required=True, description="Job name"),
                "data": fields.String(required=True, description="Data to process"),
                "repo_url": fields.String(description="GitHub repository URL"),
            },
        )
    )
    @api.doc(
        description="Uploads remote source for vectorization",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.form
        required_fields = ["user", "source", "name", "data"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            config = json.loads(data["data"])
            source_data = None

            if data["source"] == "github":
                source_data = config.get("repo_url")
            elif data["source"] in ["crawler", "url"]:
                source_data = config.get("url")
            elif data["source"] == "reddit":
                source_data = config
            task = ingest_remote.delay(
                source_data=source_data,
                job_name=data["name"],
                user=decoded_token.get("sub"),
                loader=data["source"],
            )
        except Exception as err:
            current_app.logger.error(
                f"Error uploading remote source: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


@user_ns.route("/api/task_status")
class TaskStatus(Resource):
    task_status_model = api.model(
        "TaskStatusModel",
        {"task_id": fields.String(required=True, description="Task ID")},
    )

    @api.expect(task_status_model)
    @api.doc(description="Get celery job status")
    def get(self):
        task_id = request.args.get("task_id")
        if not task_id:
            return make_response(
                jsonify({"success": False, "message": "Task ID is required"}), 400
            )
        try:
            from application.celery_init import celery

            task = celery.AsyncResult(task_id)
            task_meta = task.info
            print(f"Task status: {task.status}")
            if not isinstance(
                task_meta, (dict, list, str, int, float, bool, type(None))
            ):
                task_meta = str(task_meta)  # Convert to a string representation
        except Exception as err:
            current_app.logger.error(f"Error getting task status: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"status": task.status, "result": task_meta}), 200)


@user_ns.route("/api/combine")
class RedirectToSources(Resource):
    @api.doc(
        description="Redirects /api/combine to /api/sources for backward compatibility"
    )
    def get(self):
        return redirect("/api/sources", code=301)


@user_ns.route("/api/sources/paginated")
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


@user_ns.route("/api/sources")
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
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving sources: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(data), 200)


@user_ns.route("/api/docs_check")
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


@user_ns.route("/api/create_prompt")
class CreatePrompt(Resource):
    create_prompt_model = api.model(
        "CreatePromptModel",
        {
            "content": fields.String(
                required=True, description="Content of the prompt"
            ),
            "name": fields.String(required=True, description="Name of the prompt"),
        },
    )

    @api.expect(create_prompt_model)
    @api.doc(description="Create a new prompt")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["content", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        user = decoded_token.get("sub")
        try:

            resp = prompts_collection.insert_one(
                {
                    "name": data["name"],
                    "content": data["content"],
                    "user": user,
                }
            )
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id}), 200)


@user_ns.route("/api/get_prompts")
class GetPrompts(Resource):
    @api.doc(description="Get all prompts for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            prompts = prompts_collection.find({"user": user})
            list_prompts = [
                {"id": "default", "name": "default", "type": "public"},
                {"id": "creative", "name": "creative", "type": "public"},
                {"id": "strict", "name": "strict", "type": "public"},
            ]

            for prompt in prompts:
                list_prompts.append(
                    {
                        "id": str(prompt["_id"]),
                        "name": prompt["name"],
                        "type": "private",
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompts: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_prompts), 200)


@user_ns.route("/api/get_single_prompt")
class GetSinglePrompt(Resource):
    @api.doc(params={"id": "ID of the prompt"}, description="Get a single prompt by ID")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        prompt_id = request.args.get("id")
        if not prompt_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            if prompt_id == "default":
                with open(
                    os.path.join(current_dir, "prompts", "chat_combine_default.txt"),
                    "r",
                ) as f:
                    chat_combine_template = f.read()
                return make_response(jsonify({"content": chat_combine_template}), 200)
            elif prompt_id == "creative":
                with open(
                    os.path.join(current_dir, "prompts", "chat_combine_creative.txt"),
                    "r",
                ) as f:
                    chat_reduce_creative = f.read()
                return make_response(jsonify({"content": chat_reduce_creative}), 200)
            elif prompt_id == "strict":
                with open(
                    os.path.join(current_dir, "prompts", "chat_combine_strict.txt"), "r"
                ) as f:
                    chat_reduce_strict = f.read()
                return make_response(jsonify({"content": chat_reduce_strict}), 200)
            prompt = prompts_collection.find_one(
                {"_id": ObjectId(prompt_id), "user": user}
            )
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"content": prompt["content"]}), 200)


@user_ns.route("/api/delete_prompt")
class DeletePrompt(Resource):
    delete_prompt_model = api.model(
        "DeletePromptModel",
        {"id": fields.String(required=True, description="Prompt ID to delete")},
    )

    @api.expect(delete_prompt_model)
    @api.doc(description="Delete a prompt by ID")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            prompts_collection.delete_one({"_id": ObjectId(data["id"]), "user": user})
        except Exception as err:
            current_app.logger.error(f"Error deleting prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/update_prompt")
class UpdatePrompt(Resource):
    update_prompt_model = api.model(
        "UpdatePromptModel",
        {
            "id": fields.String(required=True, description="Prompt ID to update"),
            "name": fields.String(required=True, description="New name of the prompt"),
            "content": fields.String(
                required=True, description="New content of the prompt"
            ),
        },
    )

    @api.expect(update_prompt_model)
    @api.doc(description="Update an existing prompt")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "name", "content"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            prompts_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"name": data["name"], "content": data["content"]}},
            )
        except Exception as err:
            current_app.logger.error(f"Error updating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/get_agent")
class GetAgent(Resource):
    @api.doc(params={"id": "Agent ID"}, description="Get agent by ID")
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401

        if not (agent_id := request.args.get("id")):
            return {"success": False, "message": "ID required"}, 400

        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "user": decoded_token["sub"]}
            )
            if not agent:
                return {"status": "Not found"}, 404

            data = {
                "id": str(agent["_id"]),
                "name": agent["name"],
                "description": agent.get("description", ""),
                "image": (
                    generate_image_url(agent["image"]) if agent.get("image") else ""
                ),
                "source": (
                    str(source_doc["_id"])
                    if isinstance(agent.get("source"), DBRef)
                    and (source_doc := db.dereference(agent.get("source")))
                    else ""
                ),
                "chunks": agent["chunks"],
                "retriever": agent.get("retriever", ""),
                "prompt_id": agent.get("prompt_id", ""),
                "tools": agent.get("tools", []),
                "tool_details": resolve_tool_details(agent.get("tools", [])),
                "agent_type": agent.get("agent_type", ""),
                "status": agent.get("status", ""),
                "json_schema": agent.get("json_schema"),
                "created_at": agent.get("createdAt", ""),
                "updated_at": agent.get("updatedAt", ""),
                "last_used_at": agent.get("lastUsedAt", ""),
                "key": (
                    f"{agent['key'][:4]}...{agent['key'][-4:]}"
                    if "key" in agent
                    else ""
                ),
                "pinned": agent.get("pinned", False),
                "shared": agent.get("shared_publicly", False),
                "shared_metadata": agent.get("shared_metadata", {}),
                "shared_token": agent.get("shared_token", ""),
            }
            return make_response(jsonify(data), 200)

        except Exception as e:
            current_app.logger.error(f"Agent fetch error: {e}", exc_info=True)
            return {"success": False}, 400


@user_ns.route("/api/get_agents")
class GetAgents(Resource):
    @api.doc(description="Retrieve agents for the user")
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401

        user = decoded_token.get("sub")
        try:
            user_doc = ensure_user_doc(user)
            pinned_ids = set(user_doc.get("agent_preferences", {}).get("pinned", []))

            agents = agents_collection.find({"user": user})
            list_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent["name"],
                    "description": agent.get("description", ""),
                    "image": (
                        generate_image_url(agent["image"]) if agent.get("image") else ""
                    ),
                    "source": (
                        str(source_doc["_id"])
                        if isinstance(agent.get("source"), DBRef)
                        and (source_doc := db.dereference(agent.get("source")))
                        else ""
                    ),
                    "chunks": agent["chunks"],
                    "retriever": agent.get("retriever", ""),
                    "prompt_id": agent.get("prompt_id", ""),
                    "tools": agent.get("tools", []),
                    "tool_details": resolve_tool_details(agent.get("tools", [])),
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", ""),
                    "json_schema": agent.get("json_schema"),
                    "created_at": agent.get("createdAt", ""),
                    "updated_at": agent.get("updatedAt", ""),
                    "last_used_at": agent.get("lastUsedAt", ""),
                    "key": (
                        f"{agent['key'][:4]}...{agent['key'][-4:]}"
                        if "key" in agent
                        else ""
                    ),
                    "pinned": str(agent["_id"]) in pinned_ids,
                    "shared": agent.get("shared_publicly", False),
                    "shared_metadata": agent.get("shared_metadata", {}),
                    "shared_token": agent.get("shared_token", ""),
                }
                for agent in agents
                if "source" in agent or "retriever" in agent
            ]
        except Exception as err:
            current_app.logger.error(f"Error retrieving agents: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_agents), 200)


@user_ns.route("/api/create_agent")
class CreateAgent(Resource):
    create_agent_model = api.model(
        "CreateAgentModel",
        {
            "name": fields.String(required=True, description="Name of the agent"),
            "description": fields.String(
                required=True, description="Description of the agent"
            ),
            "image": fields.Raw(
                required=False, description="Image file upload", type="file"
            ),
            "source": fields.String(required=True, description="Source ID"),
            "chunks": fields.Integer(required=True, description="Chunks count"),
            "retriever": fields.String(required=True, description="Retriever ID"),
            "prompt_id": fields.String(required=True, description="Prompt ID"),
            "tools": fields.List(
                fields.String, required=False, description="List of tool identifiers"
            ),
            "agent_type": fields.String(required=True, description="Type of the agent"),
            "status": fields.String(
                required=True, description="Status of the agent (draft or published)"
            ),
            "json_schema": fields.Raw(
                required=False,
                description="JSON schema for enforcing structured output format",
            ),
        },
    )

    @api.expect(create_agent_model)
    @api.doc(description="Create a new agent")
    def post(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        user = decoded_token.get("sub")
        if request.content_type == "application/json":
            data = request.get_json()
        else:
            data = request.form.to_dict()
            if "tools" in data:
                try:
                    data["tools"] = json.loads(data["tools"])
                except json.JSONDecodeError:
                    data["tools"] = []
            if "json_schema" in data:
                try:
                    data["json_schema"] = json.loads(data["json_schema"])
                except json.JSONDecodeError:
                    data["json_schema"] = None
        print(f"Received data: {data}")

        # Validate JSON schema if provided
        if data.get("json_schema"):
            try:
                # Basic validation - ensure it's a valid JSON structure
                json_schema = data.get("json_schema")
                if not isinstance(json_schema, dict):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "JSON schema must be a valid JSON object",
                            }
                        ),
                        400,
                    )

                # Validate that it has either a 'schema' property or is itself a schema
                if "schema" not in json_schema and "type" not in json_schema:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "JSON schema must contain either a 'schema' property or be a valid JSON schema with 'type' property",
                            }
                        ),
                        400,
                    )
            except Exception as e:
                return make_response(
                    jsonify(
                        {"success": False, "message": f"Invalid JSON schema: {str(e)}"}
                    ),
                    400,
                )

        if data.get("status") not in ["draft", "published"]:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Status must be either 'draft' or 'published'",
                    }
                ),
                400,
            )

        if data.get("status") == "published":
            required_fields = [
                "name",
                "description",
                "source",
                "chunks",
                "retriever",
                "prompt_id",
                "agent_type",
            ]
            validate_fields = ["name", "description", "prompt_id", "agent_type"]
        else:
            required_fields = ["name"]
            validate_fields = []
        missing_fields = check_required_fields(data, required_fields)
        invalid_fields = validate_required_fields(data, validate_fields)
        if missing_fields:
            return missing_fields
        if invalid_fields:
            return invalid_fields

        image_url, error = handle_image_upload(request, "", user, storage)
        if error:
            return make_response(
                jsonify({"success": False, "message": "Image upload failed"}), 400
            )

        try:
            key = str(uuid.uuid4()) if data.get("status") == "published" else ""
            new_agent = {
                "user": user,
                "name": data.get("name"),
                "description": data.get("description", ""),
                "image": image_url,
                "source": (
                    DBRef("sources", ObjectId(data.get("source")))
                    if ObjectId.is_valid(data.get("source"))
                    else ""
                ),
                "chunks": data.get("chunks", ""),
                "retriever": data.get("retriever", ""),
                "prompt_id": data.get("prompt_id", ""),
                "tools": data.get("tools", []),
                "agent_type": data.get("agent_type", ""),
                "status": data.get("status"),
                "json_schema": data.get("json_schema"),
                "createdAt": datetime.datetime.now(datetime.timezone.utc),
                "updatedAt": datetime.datetime.now(datetime.timezone.utc),
                "lastUsedAt": None,
                "key": key,
            }
            if new_agent["chunks"] == "":
                new_agent["chunks"] = "0"
            if new_agent["source"] == "" and new_agent["retriever"] == "":
                new_agent["retriever"] = "classic"
            resp = agents_collection.insert_one(new_agent)
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id, "key": key}), 201)


@user_ns.route("/api/update_agent/<string:agent_id>")
class UpdateAgent(Resource):
    update_agent_model = api.model(
        "UpdateAgentModel",
        {
            "name": fields.String(required=True, description="New name of the agent"),
            "description": fields.String(
                required=True, description="New description of the agent"
            ),
            "image": fields.String(
                required=False, description="New image URL or identifier"
            ),
            "source": fields.String(required=True, description="Source ID"),
            "chunks": fields.Integer(required=True, description="Chunks count"),
            "retriever": fields.String(required=True, description="Retriever ID"),
            "prompt_id": fields.String(required=True, description="Prompt ID"),
            "tools": fields.List(
                fields.String, required=False, description="List of tool identifiers"
            ),
            "agent_type": fields.String(required=True, description="Type of the agent"),
            "status": fields.String(
                required=True, description="Status of the agent (draft or published)"
            ),
            "json_schema": fields.Raw(
                required=False,
                description="JSON schema for enforcing structured output format",
            ),
        },
    )

    @api.expect(update_agent_model)
    @api.doc(description="Update an existing agent")
    def put(self, agent_id):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        user = decoded_token.get("sub")
        if request.content_type == "application/json":
            data = request.get_json()
        else:
            data = request.form.to_dict()
            if "tools" in data:
                try:
                    data["tools"] = json.loads(data["tools"])
                except json.JSONDecodeError:
                    data["tools"] = []
            if "json_schema" in data:
                try:
                    data["json_schema"] = json.loads(data["json_schema"])
                except json.JSONDecodeError:
                    data["json_schema"] = None

        if not ObjectId.is_valid(agent_id):
            return make_response(
                jsonify({"success": False, "message": "Invalid agent ID format"}), 400
            )
        oid = ObjectId(agent_id)

        try:
            existing_agent = agents_collection.find_one({"_id": oid, "user": user})
        except Exception as err:
            return make_response(
                current_app.logger.error(
                    f"Error finding agent {agent_id}: {err}", exc_info=True
                ),
                jsonify({"success": False, "message": "Database error finding agent"}),
                500,
            )
        if not existing_agent:
            return make_response(
                jsonify(
                    {"success": False, "message": "Agent not found or not authorized"}
                ),
                404,
            )

        image_url, error = handle_image_upload(
            request, existing_agent.get("image", ""), user, storage
        )
        if error:
            return make_response(
                jsonify({"success": False, "message": "Image upload failed"}), 400
            )

        update_fields = {}
        allowed_fields = [
            "name",
            "description",
            "image",
            "source",
            "chunks",
            "retriever",
            "prompt_id",
            "tools",
            "agent_type",
            "status",
            "json_schema",
        ]

        for field in allowed_fields:
            if field in data:
                if field == "status":
                    new_status = data.get("status")
                    if new_status not in ["draft", "published"]:
                        return make_response(
                            jsonify(
                                {"success": False, "message": "Invalid status value"}
                            ),
                            400,
                        )
                    update_fields[field] = new_status
                elif field == "source":
                    source_id = data.get("source")
                    if source_id and ObjectId.is_valid(source_id):
                        update_fields[field] = DBRef("sources", ObjectId(source_id))
                    elif source_id:
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "message": "Invalid source ID format provided",
                                }
                            ),
                            400,
                        )
                    else:
                        update_fields[field] = ""
                elif field == "chunks":
                    chunks_value = data.get("chunks")
                    if chunks_value == "":
                        update_fields[field] = "0"
                    else:
                        try:
                            if int(chunks_value) < 0:
                                return make_response(
                                    jsonify(
                                        {
                                            "success": False,
                                            "message": "Chunks value must be a positive integer",
                                        }
                                    ),
                                    400,
                                )
                            update_fields[field] = chunks_value
                        except ValueError:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": "Invalid chunks value provided",
                                    }
                                ),
                                400,
                            )
                else:
                    update_fields[field] = data[field]
        if image_url:
            update_fields["image"] = image_url
        if not update_fields:
            return make_response(
                jsonify({"success": False, "message": "No update data provided"}), 400
            )
        newly_generated_key = None
        final_status = update_fields.get("status", existing_agent.get("status"))
        if final_status == "published":
            required_published_fields = [
                "name",
                "description",
                "source",
                "chunks",
                "retriever",
                "prompt_id",
                "agent_type",
            ]
            missing_published_fields = []
            for req_field in required_published_fields:
                final_value = update_fields.get(
                    req_field, existing_agent.get(req_field)
                )
                if req_field == "source" and final_value:
                    if not isinstance(final_value, DBRef):
                        missing_published_fields.append(req_field)
            if missing_published_fields:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": f"Cannot publish agent. Missing or invalid required fields: {', '.join(missing_published_fields)}",
                        }
                    ),
                    400,
                )

            if not existing_agent.get("key"):
                newly_generated_key = str(uuid.uuid4())
                update_fields["key"] = newly_generated_key
        update_fields["updatedAt"] = datetime.datetime.now(datetime.timezone.utc)

        try:
            result = agents_collection.update_one(
                {"_id": oid, "user": user}, {"$set": update_fields}
            )

            if result.matched_count == 0:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Agent not found or update failed unexpectedly",
                        }
                    ),
                    404,
                )
            if result.modified_count == 0 and result.matched_count == 1:
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": "Agent found, but no changes were applied",
                        }
                    ),
                    304,
                )
        except Exception as err:
            current_app.logger.error(
                f"Error updating agent {agent_id}: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Database error during update"}),
                500,
            )
        response_data = {
            "success": True,
            "id": agent_id,
            "message": "Agent updated successfully",
        }
        if newly_generated_key:
            response_data["key"] = newly_generated_key
        return make_response(
            jsonify(response_data),
            200,
        )


@user_ns.route("/api/delete_agent")
class DeleteAgent(Resource):
    @api.doc(params={"id": "ID of the agent"}, description="Delete an agent by ID")
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        agent_id = request.args.get("id")
        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            deleted_agent = agents_collection.find_one_and_delete(
                {"_id": ObjectId(agent_id), "user": user}
            )
            if not deleted_agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            deleted_id = str(deleted_agent["_id"])
        except Exception as err:
            current_app.logger.error(f"Error deleting agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": deleted_id}), 200)


@user_ns.route("/api/pinned_agents")
class PinnedAgents(Resource):
    @api.doc(description="Get pinned agents for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)

        user_id = decoded_token.get("sub")

        try:
            user_doc = ensure_user_doc(user_id)
            pinned_ids = user_doc.get("agent_preferences", {}).get("pinned", [])

            if not pinned_ids:
                return make_response(jsonify([]), 200)

            pinned_object_ids = [ObjectId(agent_id) for agent_id in pinned_ids]

            pinned_agents_cursor = agents_collection.find(
                {"_id": {"$in": pinned_object_ids}}
            )
            pinned_agents = list(pinned_agents_cursor)
            existing_ids = {str(agent["_id"]) for agent in pinned_agents}

            # Clean up any stale pinned IDs
            stale_ids = [
                agent_id for agent_id in pinned_ids if agent_id not in existing_ids
            ]
            if stale_ids:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$pullAll": {"agent_preferences.pinned": stale_ids}},
                )

            list_pinned_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "image": (
                        generate_image_url(agent["image"]) if agent.get("image") else ""
                    ),
                    "source": (
                        str(db.dereference(agent["source"])["_id"])
                        if "source" in agent
                        and agent["source"]
                        and isinstance(agent["source"], DBRef)
                        and db.dereference(agent["source"]) is not None
                        else ""
                    ),
                    "chunks": agent.get("chunks", ""),
                    "retriever": agent.get("retriever", ""),
                    "prompt_id": agent.get("prompt_id", ""),
                    "tools": agent.get("tools", []),
                    "tool_details": resolve_tool_details(agent.get("tools", [])),
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", ""),
                    "created_at": agent.get("createdAt", ""),
                    "updated_at": agent.get("updatedAt", ""),
                    "last_used_at": agent.get("lastUsedAt", ""),
                    "key": (
                        f"{agent['key'][:4]}...{agent['key'][-4:]}"
                        if "key" in agent
                        else ""
                    ),
                    "pinned": True,
                }
                for agent in pinned_agents
                if "source" in agent or "retriever" in agent
            ]

        except Exception as err:
            current_app.logger.error(f"Error retrieving pinned agents: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify(list_pinned_agents), 200)


@user_ns.route("/api/pin_agent")
class PinAgent(Resource):
    @api.doc(params={"id": "ID of the agent"}, description="Pin or unpin an agent")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        agent_id = request.args.get("id")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            user_doc = ensure_user_doc(user_id)
            pinned_list = user_doc.get("agent_preferences", {}).get("pinned", [])

            if agent_id in pinned_list:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$pull": {"agent_preferences.pinned": agent_id}},
                )
                action = "unpinned"
            else:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$addToSet": {"agent_preferences.pinned": agent_id}},
                )
                action = "pinned"
        except Exception as err:
            current_app.logger.error(f"Error pinning/unpinning agent: {err}")
            return make_response(
                jsonify({"success": False, "message": "Server error"}), 500
            )
        return make_response(jsonify({"success": True, "action": action}), 200)


@user_ns.route("/api/remove_shared_agent")
class RemoveSharedAgent(Resource):
    @api.doc(
        params={"id": "ID of the shared agent"},
        description="Remove a shared agent from the current user's shared list",
    )
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        agent_id = request.args.get("id")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )

        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "shared_publicly": True}
            )
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Shared agent not found"}),
                    404,
                )

            ensure_user_doc(user_id)
            users_collection.update_one(
                {"user_id": user_id},
                {
                    "$pull": {
                        "agent_preferences.shared_with_me": agent_id,
                        "agent_preferences.pinned": agent_id,
                    }
                },
            )

            return make_response(jsonify({"success": True, "action": "removed"}), 200)

        except Exception as err:
            current_app.logger.error(f"Error removing shared agent: {err}")
            return make_response(
                jsonify({"success": False, "message": "Server error"}), 500
            )


@user_ns.route("/api/shared_agent")
class SharedAgent(Resource):
    @api.doc(
        params={
            "token": "Shared token of the agent",
        },
        description="Get a shared agent by token or ID",
    )
    def get(self):
        shared_token = request.args.get("token")

        if not shared_token:
            return make_response(
                jsonify({"success": False, "message": "Token or ID is required"}), 400
            )

        try:
            query = {
                "shared_publicly": True,
                "shared_token": shared_token,
            }
            shared_agent = agents_collection.find_one(query)
            if not shared_agent:
                return make_response(
                    jsonify({"success": False, "message": "Shared agent not found"}),
                    404,
                )

            agent_id = str(shared_agent["_id"])
            data = {
                "id": agent_id,
                "user": shared_agent.get("user", ""),
                "name": shared_agent.get("name", ""),
                "image": (
                    generate_image_url(shared_agent["image"])
                    if shared_agent.get("image")
                    else ""
                ),
                "description": shared_agent.get("description", ""),
                "source": (
                    str(source_doc["_id"])
                    if isinstance(shared_agent.get("source"), DBRef)
                    and (source_doc := db.dereference(shared_agent.get("source")))
                    else ""
                ),
                "chunks": shared_agent.get("chunks", "0"),
                "retriever": shared_agent.get("retriever", "classic"),
                "prompt_id": shared_agent.get("prompt_id", "default"),
                "tools": shared_agent.get("tools", []),
                "tool_details": resolve_tool_details(shared_agent.get("tools", [])),
                "agent_type": shared_agent.get("agent_type", ""),
                "status": shared_agent.get("status", ""),
                "json_schema": shared_agent.get("json_schema"),
                "created_at": shared_agent.get("createdAt", ""),
                "updated_at": shared_agent.get("updatedAt", ""),
                "shared": shared_agent.get("shared_publicly", False),
                "shared_token": shared_agent.get("shared_token", ""),
                "shared_metadata": shared_agent.get("shared_metadata", {}),
            }

            if data["tools"]:
                enriched_tools = []
                for tool in data["tools"]:
                    tool_data = user_tools_collection.find_one({"_id": ObjectId(tool)})
                    if tool_data:
                        enriched_tools.append(tool_data.get("name", ""))
                data["tools"] = enriched_tools

            decoded_token = getattr(request, "decoded_token", None)
            if decoded_token:
                user_id = decoded_token.get("sub")
                owner_id = shared_agent.get("user")

                if user_id != owner_id:
                    ensure_user_doc(user_id)
                    users_collection.update_one(
                        {"user_id": user_id},
                        {"$addToSet": {"agent_preferences.shared_with_me": agent_id}},
                    )

            return make_response(jsonify(data), 200)

        except Exception as err:
            current_app.logger.error(f"Error retrieving shared agent: {err}")
            return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/shared_agents")
class SharedAgents(Resource):
    @api.doc(description="Get shared agents explicitly shared with the user")
    def get(self):
        try:
            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False}), 401)
            user_id = decoded_token.get("sub")

            user_doc = ensure_user_doc(user_id)
            shared_with_ids = user_doc.get("agent_preferences", {}).get(
                "shared_with_me", []
            )
            shared_object_ids = [ObjectId(id) for id in shared_with_ids]

            shared_agents_cursor = agents_collection.find(
                {"_id": {"$in": shared_object_ids}, "shared_publicly": True}
            )
            shared_agents = list(shared_agents_cursor)

            found_ids_set = {str(agent["_id"]) for agent in shared_agents}
            stale_ids = [id for id in shared_with_ids if id not in found_ids_set]
            if stale_ids:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$pullAll": {"agent_preferences.shared_with_me": stale_ids}},
                )

            pinned_ids = set(user_doc.get("agent_preferences", {}).get("pinned", []))

            list_shared_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "image": (
                        generate_image_url(agent["image"]) if agent.get("image") else ""
                    ),
                    "tools": agent.get("tools", []),
                    "tool_details": resolve_tool_details(agent.get("tools", [])),
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", ""),
                    "json_schema": agent.get("json_schema"),
                    "created_at": agent.get("createdAt", ""),
                    "updated_at": agent.get("updatedAt", ""),
                    "pinned": str(agent["_id"]) in pinned_ids,
                    "shared": agent.get("shared_publicly", False),
                    "shared_token": agent.get("shared_token", ""),
                    "shared_metadata": agent.get("shared_metadata", {}),
                }
                for agent in shared_agents
            ]

            return make_response(jsonify(list_shared_agents), 200)

        except Exception as err:
            current_app.logger.error(f"Error retrieving shared agents: {err}")
            return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/share_agent")
class ShareAgent(Resource):
    @api.expect(
        api.model(
            "ShareAgentModel",
            {
                "id": fields.String(required=True, description="ID of the agent"),
                "shared": fields.Boolean(
                    required=True, description="Share or unshare the agent"
                ),
                "username": fields.String(
                    required=False, description="Name of the user"
                ),
            },
        )
    )
    @api.doc(description="Share or unshare an agent")
    def put(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")

        data = request.get_json()
        if not data:
            return make_response(
                jsonify({"success": False, "message": "Missing JSON body"}), 400
            )
        agent_id = data.get("id")
        shared = data.get("shared")
        username = data.get("username", "")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        if shared is None:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Shared parameter is required and must be true or false",
                    }
                ),
                400,
            )
        try:
            try:
                agent_oid = ObjectId(agent_id)
            except Exception:
                return make_response(
                    jsonify({"success": False, "message": "Invalid agent ID"}), 400
                )
            agent = agents_collection.find_one({"_id": agent_oid, "user": user})
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            if shared:
                shared_metadata = {
                    "shared_by": username,
                    "shared_at": datetime.datetime.now(datetime.timezone.utc),
                }
                shared_token = secrets.token_urlsafe(32)
                agents_collection.update_one(
                    {"_id": agent_oid, "user": user},
                    {
                        "$set": {
                            "shared_publicly": shared,
                            "shared_metadata": shared_metadata,
                            "shared_token": shared_token,
                        }
                    },
                )
            else:
                agents_collection.update_one(
                    {"_id": agent_oid, "user": user},
                    {"$set": {"shared_publicly": shared, "shared_token": None}},
                    {"$unset": {"shared_metadata": ""}},
                )
        except Exception as err:
            current_app.logger.error(f"Error sharing/unsharing agent: {err}")
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        shared_token = shared_token if shared else None
        return make_response(
            jsonify({"success": True, "shared_token": shared_token}), 200
        )


@user_ns.route("/api/agent_webhook")
class AgentWebhook(Resource):
    @api.doc(
        params={"id": "ID of the agent"},
        description="Generate webhook URL for the agent",
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        agent_id = request.args.get("id")
        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "user": user}
            )
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            webhook_token = agent.get("incoming_webhook_token")
            if not webhook_token:
                webhook_token = secrets.token_urlsafe(32)
                agents_collection.update_one(
                    {"_id": ObjectId(agent_id), "user": user},
                    {"$set": {"incoming_webhook_token": webhook_token}},
                )
            base_url = settings.API_URL.rstrip("/")
            full_webhook_url = f"{base_url}/api/webhooks/agents/{webhook_token}"
        except Exception as err:
            current_app.logger.error(
                f"Error generating webhook URL: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Error generating webhook URL"}),
                400,
            )
        return make_response(
            jsonify({"success": True, "webhook_url": full_webhook_url}), 200
        )


def require_agent(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        webhook_token = kwargs.get("webhook_token")
        if not webhook_token:
            return make_response(
                jsonify({"success": False, "message": "Webhook token missing"}), 400
            )
        agent = agents_collection.find_one(
            {"incoming_webhook_token": webhook_token}, {"_id": 1}
        )
        if not agent:
            current_app.logger.warning(
                f"Webhook attempt with invalid token: {webhook_token}"
            )
            return make_response(
                jsonify({"success": False, "message": "Agent not found"}), 404
            )
        kwargs["agent"] = agent
        kwargs["agent_id_str"] = str(agent["_id"])
        return func(*args, **kwargs)

    return wrapper


@user_ns.route("/api/webhooks/agents/<string:webhook_token>")
class AgentWebhookListener(Resource):
    method_decorators = [require_agent]

    def _enqueue_webhook_task(self, agent_id_str, payload, source_method):
        if not payload:
            current_app.logger.warning(
                f"Webhook ({source_method}) received for agent {agent_id_str} with empty payload."
            )
        current_app.logger.info(
            f"Incoming {source_method} webhook for agent {agent_id_str}. Enqueuing task with payload: {payload}"
        )

        try:
            task = process_agent_webhook.delay(
                agent_id=agent_id_str,
                payload=payload,
            )
            current_app.logger.info(
                f"Task {task.id} enqueued for agent {agent_id_str} ({source_method})."
            )
            return make_response(jsonify({"success": True, "task_id": task.id}), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error enqueuing webhook task ({source_method}) for agent {agent_id_str}: {err}",
                exc_info=True,
            )
            return make_response(
                jsonify({"success": False, "message": "Error processing webhook"}), 500
            )

    @api.doc(
        description="Webhook listener for agent events (POST). Expects JSON payload, which is used to trigger processing.",
    )
    def post(self, webhook_token, agent, agent_id_str):
        payload = request.get_json()
        if payload is None:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Invalid or missing JSON data in request body",
                    }
                ),
                400,
            )
        return self._enqueue_webhook_task(agent_id_str, payload, source_method="POST")

    @api.doc(
        description="Webhook listener for agent events (GET). Uses URL query parameters as payload to trigger processing.",
    )
    def get(self, webhook_token, agent, agent_id_str):
        payload = request.args.to_dict(flat=True)
        return self._enqueue_webhook_task(agent_id_str, payload, source_method="GET")


@user_ns.route("/api/share")
class ShareConversation(Resource):
    share_conversation_model = api.model(
        "ShareConversationModel",
        {
            "conversation_id": fields.String(
                required=True, description="Conversation ID"
            ),
            "user": fields.String(description="User ID (optional)"),
            "prompt_id": fields.String(description="Prompt ID (optional)"),
            "chunks": fields.Integer(description="Chunks count (optional)"),
        },
    )

    @api.expect(share_conversation_model)
    @api.doc(description="Share a conversation")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["conversation_id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        is_promptable = request.args.get("isPromptable", type=inputs.boolean)
        if is_promptable is None:
            return make_response(
                jsonify({"success": False, "message": "isPromptable is required"}), 400
            )
        conversation_id = data["conversation_id"]

        try:
            conversation = conversations_collection.find_one(
                {"_id": ObjectId(conversation_id)}
            )
            if conversation is None:
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "Conversation does not exist",
                        }
                    ),
                    404,
                )
            current_n_queries = len(conversation["queries"])
            explicit_binary = Binary.from_uuid(
                uuid.uuid4(), UuidRepresentation.STANDARD
            )

            if is_promptable:
                prompt_id = data.get("prompt_id", "default")
                chunks = data.get("chunks", "2")

                name = conversation["name"] + "(shared)"
                new_api_key_data = {
                    "prompt_id": prompt_id,
                    "chunks": chunks,
                    "user": user,
                }

                if "source" in data and ObjectId.is_valid(data["source"]):
                    new_api_key_data["source"] = DBRef(
                        "sources", ObjectId(data["source"])
                    )
                if "retriever" in data:
                    new_api_key_data["retriever"] = data["retriever"]
                pre_existing_api_document = agents_collection.find_one(new_api_key_data)
                if pre_existing_api_document:
                    api_uuid = pre_existing_api_document["key"]
                    pre_existing = shared_conversations_collections.find_one(
                        {
                            "conversation_id": DBRef(
                                "conversations", ObjectId(conversation_id)
                            ),
                            "isPromptable": is_promptable,
                            "first_n_queries": current_n_queries,
                            "user": user,
                            "api_key": api_uuid,
                        }
                    )
                    if pre_existing is not None:
                        return make_response(
                            jsonify(
                                {
                                    "success": True,
                                    "identifier": str(pre_existing["uuid"].as_uuid()),
                                }
                            ),
                            200,
                        )
                    else:
                        shared_conversations_collections.insert_one(
                            {
                                "uuid": explicit_binary,
                                "conversation_id": {
                                    "$ref": "conversations",
                                    "$id": ObjectId(conversation_id),
                                },
                                "isPromptable": is_promptable,
                                "first_n_queries": current_n_queries,
                                "user": user,
                                "api_key": api_uuid,
                            }
                        )
                        return make_response(
                            jsonify(
                                {
                                    "success": True,
                                    "identifier": str(explicit_binary.as_uuid()),
                                }
                            ),
                            201,
                        )
                else:
                    api_uuid = str(uuid.uuid4())
                    new_api_key_data["key"] = api_uuid
                    new_api_key_data["name"] = name

                    if "source" in data and ObjectId.is_valid(data["source"]):
                        new_api_key_data["source"] = DBRef(
                            "sources", ObjectId(data["source"])
                        )
                    if "retriever" in data:
                        new_api_key_data["retriever"] = data["retriever"]
                    agents_collection.insert_one(new_api_key_data)
                    shared_conversations_collections.insert_one(
                        {
                            "uuid": explicit_binary,
                            "conversation_id": {
                                "$ref": "conversations",
                                "$id": ObjectId(conversation_id),
                            },
                            "isPromptable": is_promptable,
                            "first_n_queries": current_n_queries,
                            "user": user,
                            "api_key": api_uuid,
                        }
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": True,
                                "identifier": str(explicit_binary.as_uuid()),
                            }
                        ),
                        201,
                    )
            pre_existing = shared_conversations_collections.find_one(
                {
                    "conversation_id": DBRef(
                        "conversations", ObjectId(conversation_id)
                    ),
                    "isPromptable": is_promptable,
                    "first_n_queries": current_n_queries,
                    "user": user,
                }
            )
            if pre_existing is not None:
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "identifier": str(pre_existing["uuid"].as_uuid()),
                        }
                    ),
                    200,
                )
            else:
                shared_conversations_collections.insert_one(
                    {
                        "uuid": explicit_binary,
                        "conversation_id": {
                            "$ref": "conversations",
                            "$id": ObjectId(conversation_id),
                        },
                        "isPromptable": is_promptable,
                        "first_n_queries": current_n_queries,
                        "user": user,
                    }
                )
                return make_response(
                    jsonify(
                        {"success": True, "identifier": str(explicit_binary.as_uuid())}
                    ),
                    201,
                )
        except Exception as err:
            current_app.logger.error(
                f"Error sharing conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/shared_conversation/<string:identifier>")
class GetPubliclySharedConversations(Resource):
    @api.doc(description="Get publicly shared conversations by identifier")
    def get(self, identifier: str):
        try:
            query_uuid = Binary.from_uuid(
                uuid.UUID(identifier), UuidRepresentation.STANDARD
            )
            shared = shared_conversations_collections.find_one({"uuid": query_uuid})
            conversation_queries = []

            if (
                shared
                and "conversation_id" in shared
                and isinstance(shared["conversation_id"], DBRef)
            ):
                conversation_ref = shared["conversation_id"]
                conversation = db.dereference(conversation_ref)
                if conversation is None:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "might have broken url or the conversation does not exist",
                            }
                        ),
                        404,
                    )
                conversation_queries = conversation["queries"][
                    : (shared["first_n_queries"])
                ]

                for query in conversation_queries:
                    if "attachments" in query and query["attachments"]:
                        attachment_details = []
                        for attachment_id in query["attachments"]:
                            try:
                                attachment = attachments_collection.find_one(
                                    {"_id": ObjectId(attachment_id)}
                                )
                                if attachment:
                                    attachment_details.append(
                                        {
                                            "id": str(attachment["_id"]),
                                            "fileName": attachment.get(
                                                "filename", "Unknown file"
                                            ),
                                        }
                                    )
                            except Exception as e:
                                current_app.logger.error(
                                    f"Error retrieving attachment {attachment_id}: {e}",
                                    exc_info=True,
                                )
                        query["attachments"] = attachment_details
            else:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "error": "might have broken url or the conversation does not exist",
                        }
                    ),
                    404,
                )
            date = conversation["_id"].generation_time.isoformat()
            res = {
                "success": True,
                "queries": conversation_queries,
                "title": conversation["name"],
                "timestamp": date,
            }
            if shared["isPromptable"] and "api_key" in shared:
                res["api_key"] = shared["api_key"]
            return make_response(jsonify(res), 200)
        except Exception as err:
            current_app.logger.error(
                f"Error getting shared conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/get_message_analytics")
class GetMessageAnalytics(Resource):
    get_message_analytics_model = api.model(
        "GetMessageAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=[
                    "last_hour",
                    "last_24_hour",
                    "last_7_days",
                    "last_15_days",
                    "last_30_days",
                ],
            ),
        },
    )

    @api.expect(get_message_analytics_model)
    @api.doc(description="Get message analytics based on filter option")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id), "user": user})[
                    "key"
                ]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
        else:
            if filter_option in ["last_7_days", "last_15_days", "last_30_days"]:
                filter_days = (
                    6
                    if filter_option == "last_7_days"
                    else 14 if filter_option == "last_15_days" else 29
                )
            else:
                return make_response(
                    jsonify({"success": False, "message": "Invalid option"}), 400
                )
            start_date = end_date - datetime.timedelta(days=filter_days)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            group_format = "%Y-%m-%d"
        try:
            match_stage = {
                "$match": {
                    "user": user,
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            pipeline = [
                match_stage,
                {"$unwind": "$queries"},
                {
                    "$match": {
                        "queries.timestamp": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$queries.timestamp",
                            }
                        },
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"_id": 1}},
            ]

            message_data = conversations_collection.aggregate(pipeline)

            if filter_option == "last_hour":
                intervals = generate_minute_range(start_date, end_date)
            elif filter_option == "last_24_hour":
                intervals = generate_hourly_range(start_date, end_date)
            else:
                intervals = generate_date_range(start_date, end_date)
            daily_messages = {interval: 0 for interval in intervals}

            for entry in message_data:
                daily_messages[entry["_id"]] = entry["count"]
        except Exception as err:
            current_app.logger.error(
                f"Error getting message analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "messages": daily_messages}), 200
        )


@user_ns.route("/api/get_token_analytics")
class GetTokenAnalytics(Resource):
    get_token_analytics_model = api.model(
        "GetTokenAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=[
                    "last_hour",
                    "last_24_hour",
                    "last_7_days",
                    "last_15_days",
                    "last_30_days",
                ],
            ),
        },
    )

    @api.expect(get_token_analytics_model)
    @api.doc(description="Get token analytics data")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id), "user": user})[
                    "key"
                ]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
            group_stage = {
                "$group": {
                    "_id": {
                        "minute": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        }
                    },
                    "total_tokens": {
                        "$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}
                    },
                }
            }
        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
            group_stage = {
                "$group": {
                    "_id": {
                        "hour": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        }
                    },
                    "total_tokens": {
                        "$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}
                    },
                }
            }
        else:
            if filter_option in ["last_7_days", "last_15_days", "last_30_days"]:
                filter_days = (
                    6
                    if filter_option == "last_7_days"
                    else (14 if filter_option == "last_15_days" else 29)
                )
            else:
                return make_response(
                    jsonify({"success": False, "message": "Invalid option"}), 400
                )
            start_date = end_date - datetime.timedelta(days=filter_days)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            group_format = "%Y-%m-%d"
            group_stage = {
                "$group": {
                    "_id": {
                        "day": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        }
                    },
                    "total_tokens": {
                        "$sum": {"$add": ["$prompt_tokens", "$generated_tokens"]}
                    },
                }
            }
        try:
            match_stage = {
                "$match": {
                    "user_id": user,
                    "timestamp": {"$gte": start_date, "$lte": end_date},
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            token_usage_data = token_usage_collection.aggregate(
                [
                    match_stage,
                    group_stage,
                    {"$sort": {"_id": 1}},
                ]
            )

            if filter_option == "last_hour":
                intervals = generate_minute_range(start_date, end_date)
            elif filter_option == "last_24_hour":
                intervals = generate_hourly_range(start_date, end_date)
            else:
                intervals = generate_date_range(start_date, end_date)
            daily_token_usage = {interval: 0 for interval in intervals}

            for entry in token_usage_data:
                if filter_option == "last_hour":
                    daily_token_usage[entry["_id"]["minute"]] = entry["total_tokens"]
                elif filter_option == "last_24_hour":
                    daily_token_usage[entry["_id"]["hour"]] = entry["total_tokens"]
                else:
                    daily_token_usage[entry["_id"]["day"]] = entry["total_tokens"]
        except Exception as err:
            current_app.logger.error(
                f"Error getting token analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "token_usage": daily_token_usage}), 200
        )


@user_ns.route("/api/get_feedback_analytics")
class GetFeedbackAnalytics(Resource):
    get_feedback_analytics_model = api.model(
        "GetFeedbackAnalyticsModel",
        {
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "filter_option": fields.String(
                required=False,
                description="Filter option for analytics",
                default="last_30_days",
                enum=[
                    "last_hour",
                    "last_24_hour",
                    "last_7_days",
                    "last_15_days",
                    "last_30_days",
                ],
            ),
        },
    )

    @api.expect(get_feedback_analytics_model)
    @api.doc(description="Get feedback analytics data")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id), "user": user})[
                    "key"
                ]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
            date_field = {
                "$dateToString": {
                    "format": group_format,
                    "date": "$queries.feedback_timestamp",
                }
            }
        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
            date_field = {
                "$dateToString": {
                    "format": group_format,
                    "date": "$queries.feedback_timestamp",
                }
            }
        else:
            if filter_option in ["last_7_days", "last_15_days", "last_30_days"]:
                filter_days = (
                    6
                    if filter_option == "last_7_days"
                    else (14 if filter_option == "last_15_days" else 29)
                )
            else:
                return make_response(
                    jsonify({"success": False, "message": "Invalid option"}), 400
                )
            start_date = end_date - datetime.timedelta(days=filter_days)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = end_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            group_format = "%Y-%m-%d"
            date_field = {
                "$dateToString": {
                    "format": group_format,
                    "date": "$queries.feedback_timestamp",
                }
            }
        try:
            match_stage = {
                "$match": {
                    "queries.feedback_timestamp": {
                        "$gte": start_date,
                        "$lte": end_date,
                    },
                    "queries.feedback": {"$exists": True},
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            pipeline = [
                match_stage,
                {"$unwind": "$queries"},
                {"$match": {"queries.feedback": {"$exists": True}}},
                {
                    "$group": {
                        "_id": {"time": date_field, "feedback": "$queries.feedback"},
                        "count": {"$sum": 1},
                    }
                },
                {
                    "$group": {
                        "_id": "$_id.time",
                        "positive": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$_id.feedback", "LIKE"]},
                                    "$count",
                                    0,
                                ]
                            }
                        },
                        "negative": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$_id.feedback", "DISLIKE"]},
                                    "$count",
                                    0,
                                ]
                            }
                        },
                    }
                },
                {"$sort": {"_id": 1}},
            ]

            feedback_data = conversations_collection.aggregate(pipeline)

            if filter_option == "last_hour":
                intervals = generate_minute_range(start_date, end_date)
            elif filter_option == "last_24_hour":
                intervals = generate_hourly_range(start_date, end_date)
            else:
                intervals = generate_date_range(start_date, end_date)
            daily_feedback = {
                interval: {"positive": 0, "negative": 0} for interval in intervals
            }

            for entry in feedback_data:
                daily_feedback[entry["_id"]] = {
                    "positive": entry["positive"],
                    "negative": entry["negative"],
                }
        except Exception as err:
            current_app.logger.error(
                f"Error getting feedback analytics: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "feedback": daily_feedback}), 200
        )


@user_ns.route("/api/get_user_logs")
class GetUserLogs(Resource):
    get_user_logs_model = api.model(
        "GetUserLogsModel",
        {
            "page": fields.Integer(
                required=False,
                description="Page number for pagination",
                default=1,
            ),
            "api_key_id": fields.String(required=False, description="API Key ID"),
            "page_size": fields.Integer(
                required=False,
                description="Number of logs per page",
                default=10,
            ),
        },
    )

    @api.expect(get_user_logs_model)
    @api.doc(description="Get user logs with pagination")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        page = int(data.get("page", 1))
        api_key_id = data.get("api_key_id")
        page_size = int(data.get("page_size", 10))
        skip = (page - 1) * page_size

        try:
            api_key = (
                agents_collection.find_one({"_id": ObjectId(api_key_id)})["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        query = {"user": user}
        if api_key:
            query = {"api_key": api_key}
        items_cursor = (
            user_logs_collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(page_size + 1)
        )
        items = list(items_cursor)

        results = [
            {
                "id": str(item.get("_id")),
                "action": item.get("action"),
                "level": item.get("level"),
                "user": item.get("user"),
                "question": item.get("question"),
                "sources": item.get("sources"),
                "retriever_params": item.get("retriever_params"),
                "timestamp": item.get("timestamp"),
            }
            for item in items[:page_size]
        ]

        has_more = len(items) > page_size

        return make_response(
            jsonify(
                {
                    "success": True,
                    "logs": results,
                    "page": page,
                    "page_size": page_size,
                    "has_more": has_more,
                }
            ),
            200,
        )


@user_ns.route("/api/manage_sync")
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


@user_ns.route("/api/tts")
class TextToSpeech(Resource):
    tts_model = api.model(
        "TextToSpeechModel",
        {
            "text": fields.String(
                required=True, description="Text to be synthesized as audio"
            ),
        },
    )

    @api.expect(tts_model)
    @api.doc(description="Synthesize audio speech from text")
    def post(self):
        data = request.get_json()
        text = data["text"]
        try:
            tts_instance = GoogleTTS()
            audio_base64, detected_language = tts_instance.text_to_speech(text)
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "audio_base64": audio_base64,
                        "lang": detected_language,
                    }
                ),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error synthesizing audio: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/available_tools")
class AvailableTools(Resource):
    @api.doc(description="Get available tools for a user")
    def get(self):
        try:
            tools_metadata = []
            for tool_name, tool_instance in tool_manager.tools.items():
                doc = tool_instance.__doc__.strip()
                lines = doc.split("\n", 1)
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                tools_metadata.append(
                    {
                        "name": tool_name,
                        "displayName": name,
                        "description": description,
                        "configRequirements": tool_instance.get_config_requirements(),
                        "actions": tool_instance.get_actions_metadata(),
                    }
                )
        except Exception as err:
            current_app.logger.error(
                f"Error getting available tools: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "data": tools_metadata}), 200)


@user_ns.route("/api/get_tools")
class GetTools(Resource):
    @api.doc(description="Get tools created by a user")
    def get(self):
        try:
            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False}), 401)
            user = decoded_token.get("sub")
            tools = user_tools_collection.find({"user": user})
            user_tools = []
            for tool in tools:
                tool["id"] = str(tool["_id"])
                tool.pop("_id")
                user_tools.append(tool)
        except Exception as err:
            current_app.logger.error(f"Error getting user tools: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "tools": user_tools}), 200)


@user_ns.route("/api/create_tool")
class CreateTool(Resource):
    @api.expect(
        api.model(
            "CreateToolModel",
            {
                "name": fields.String(required=True, description="Name of the tool"),
                "displayName": fields.String(
                    required=True, description="Display name for the tool"
                ),
                "description": fields.String(
                    required=True, description="Tool description"
                ),
                "config": fields.Raw(
                    required=True, description="Configuration of the tool"
                ),
                "customName": fields.String(
                    required=False, description="Custom name for the tool"
                ),
                "actions": fields.List(
                    fields.Raw,
                    required=True,
                    description="Actions the tool can perform",
                ),
                "status": fields.Boolean(
                    required=True, description="Status of the tool"
                ),
            },
        )
    )
    @api.doc(description="Create a new tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = [
            "name",
            "displayName",
            "description",
            "actions",
            "config",
            "status",
        ]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        transformed_actions = []
        for action in data["actions"]:
            action["active"] = True
            if "parameters" in action:
                if "properties" in action["parameters"]:
                    for param_name, param_details in action["parameters"][
                        "properties"
                    ].items():
                        param_details["filled_by_llm"] = True
                        param_details["value"] = ""
            transformed_actions.append(action)
        try:
            new_tool = {
                "user": user,
                "name": data["name"],
                "displayName": data["displayName"],
                "description": data["description"],
                "customName": data.get("customName", ""),
                "actions": transformed_actions,
                "config": data["config"],
                "status": data["status"],
            }
            resp = user_tools_collection.insert_one(new_tool)
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id}), 200)


@user_ns.route("/api/update_tool")
class UpdateTool(Resource):
    @api.expect(
        api.model(
            "UpdateToolModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "name": fields.String(description="Name of the tool"),
                "displayName": fields.String(description="Display name for the tool"),
                "customName": fields.String(description="Custom name for the tool"),
                "description": fields.String(description="Tool description"),
                "config": fields.Raw(description="Configuration of the tool"),
                "actions": fields.List(
                    fields.Raw, description="Actions the tool can perform"
                ),
                "status": fields.Boolean(description="Status of the tool"),
            },
        )
    )
    @api.doc(description="Update a tool by ID")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            update_data = {}
            if "name" in data:
                update_data["name"] = data["name"]
            if "displayName" in data:
                update_data["displayName"] = data["displayName"]
            if "customName" in data:
                update_data["customName"] = data["customName"]
            if "description" in data:
                update_data["description"] = data["description"]
            if "actions" in data:
                update_data["actions"] = data["actions"]
            if "config" in data:
                if "actions" in data["config"]:
                    for action_name in list(data["config"]["actions"].keys()):
                        if not validate_function_name(action_name):
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": f"Invalid function name '{action_name}'. Function names must match pattern '^[a-zA-Z0-9_-]+$'.",
                                        "param": "tools[].function.name",
                                    }
                                ),
                                400,
                            )
                tool_doc = user_tools_collection.find_one(
                    {"_id": ObjectId(data["id"]), "user": user}
                )
                if tool_doc and tool_doc.get("name") == "mcp_tool":
                    config = data["config"]
                    existing_config = tool_doc.get("config", {})
                    storage_config = existing_config.copy()

                    storage_config.update(config)
                    existing_credentials = {}
                    if "encrypted_credentials" in existing_config:
                        existing_credentials = decrypt_credentials(
                            existing_config["encrypted_credentials"], user
                        )
                    auth_credentials = existing_credentials.copy()
                    auth_type = storage_config.get("auth_type", "none")
                    if auth_type == "api_key":
                        if "api_key" in config and config["api_key"]:
                            auth_credentials["api_key"] = config["api_key"]
                        if "api_key_header" in config:
                            auth_credentials["api_key_header"] = config[
                                "api_key_header"
                            ]
                    elif auth_type == "bearer":
                        if "bearer_token" in config and config["bearer_token"]:
                            auth_credentials["bearer_token"] = config["bearer_token"]
                        elif "encrypted_token" in config and config["encrypted_token"]:
                            auth_credentials["bearer_token"] = config["encrypted_token"]
                    elif auth_type == "basic":
                        if "username" in config and config["username"]:
                            auth_credentials["username"] = config["username"]
                        if "password" in config and config["password"]:
                            auth_credentials["password"] = config["password"]
                    if auth_type != "none" and auth_credentials:
                        encrypted_credentials_string = encrypt_credentials(
                            auth_credentials, user
                        )
                        storage_config["encrypted_credentials"] = (
                            encrypted_credentials_string
                        )
                    elif auth_type == "none":
                        storage_config.pop("encrypted_credentials", None)
                    for field in [
                        "api_key",
                        "bearer_token",
                        "encrypted_token",
                        "username",
                        "password",
                        "api_key_header",
                    ]:
                        storage_config.pop(field, None)
                    update_data["config"] = storage_config
                else:
                    update_data["config"] = data["config"]
            if "status" in data:
                update_data["status"] = data["status"]
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": update_data},
            )
        except Exception as err:
            current_app.logger.error(f"Error updating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/update_tool_config")
class UpdateToolConfig(Resource):
    @api.expect(
        api.model(
            "UpdateToolConfigModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "config": fields.Raw(
                    required=True, description="Configuration of the tool"
                ),
            },
        )
    )
    @api.doc(description="Update the configuration of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"config": data["config"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool config: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/update_tool_actions")
class UpdateToolActions(Resource):
    @api.expect(
        api.model(
            "UpdateToolActionsModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "actions": fields.List(
                    fields.Raw,
                    required=True,
                    description="Actions the tool can perform",
                ),
            },
        )
    )
    @api.doc(description="Update the actions of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "actions"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"actions": data["actions"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool actions: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/update_tool_status")
class UpdateToolStatus(Resource):
    @api.expect(
        api.model(
            "UpdateToolStatusModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "status": fields.Boolean(
                    required=True, description="Status of the tool"
                ),
            },
        )
    )
    @api.doc(description="Update the status of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "status"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"status": data["status"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool status: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/delete_tool")
class DeleteTool(Resource):
    @api.expect(
        api.model(
            "DeleteToolModel",
            {"id": fields.String(required=True, description="Tool ID")},
        )
    )
    @api.doc(description="Delete a tool by ID")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            result = user_tools_collection.delete_one(
                {"_id": ObjectId(data["id"]), "user": user}
            )
            if result.deleted_count == 0:
                return {"success": False, "message": "Tool not found"}, 404
        except Exception as err:
            current_app.logger.error(f"Error deleting tool: {err}", exc_info=True)
            return {"success": False}, 400
        return {"success": True}, 200


@user_ns.route("/api/get_chunks")
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
                    # Check if the chunk's source matches the requested path
                    if not chunk_source or not chunk_source.endswith(path):
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


@user_ns.route("/api/add_chunk")
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


@user_ns.route("/api/delete_chunk")
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


@user_ns.route("/api/update_chunk")
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


@user_ns.route("/api/store_attachment")
class StoreAttachment(Resource):
    @api.expect(
        api.model(
            "AttachmentModel",
            {
                "file": fields.Raw(required=True, description="File to upload"),
                "api_key": fields.String(
                    required=False, description="API key (optional)"
                ),
            },
        )
    )
    @api.doc(
        description="Stores a single attachment without vectorization or training. Supports user or API key authentication."
    )
    def post(self):
        decoded_token = getattr(request, "decoded_token", None)
        api_key = request.form.get("api_key") or request.args.get("api_key")
        file = request.files.get("file")

        if not file or file.filename == "":
            return make_response(
                jsonify({"status": "error", "message": "Missing file"}),
                400,
            )

        user = None
        if decoded_token:
            user = safe_filename(decoded_token.get("sub"))
        elif api_key:
            agent = agents_collection.find_one({"key": api_key})
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Invalid API key"}), 401
                )
            user = safe_filename(agent.get("user"))
        else:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}), 401
            )

        try:
            attachment_id = ObjectId()
            original_filename = safe_filename(os.path.basename(file.filename))
            relative_path = f"{settings.UPLOAD_FOLDER}/{user}/attachments/{str(attachment_id)}/{original_filename}"

            metadata = storage.save_file(file, relative_path)

            file_info = {
                "filename": original_filename,
                "attachment_id": str(attachment_id),
                "path": relative_path,
                "metadata": metadata,
            }

            task = store_attachment.delay(file_info, user)

            return make_response(
                jsonify(
                    {
                        "success": True,
                        "task_id": task.id,
                        "message": "File uploaded successfully. Processing started.",
                    }
                ),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error storing attachment: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": str(err)}), 400)


@user_ns.route("/api/images/<path:image_path>")
class ServeImage(Resource):
    @api.doc(description="Serve an image from storage")
    def get(self, image_path):
        try:
            file_obj = storage.get_file(image_path)
            extension = image_path.split(".")[-1].lower()
            content_type = f"image/{extension}"
            if extension == "jpg":
                content_type = "image/jpeg"

            response = make_response(file_obj.read())
            response.headers.set("Content-Type", content_type)
            response.headers.set("Cache-Control", "max-age=86400")

            return response
        except FileNotFoundError:
            return make_response(
                jsonify({"success": False, "message": "Image not found"}), 404
            )
        except Exception as e:
            current_app.logger.error(f"Error serving image: {e}")
            return make_response(
                jsonify({"success": False, "message": "Error retrieving image"}), 500
            )


@user_ns.route("/api/directory_structure")
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

            return make_response(
                jsonify(
                    {
                        "success": True,
                        "directory_structure": directory_structure,
                        "base_path": doc.get("file_path", ""),
                    }
                ),
                200,
            )

        except Exception as e:
            current_app.logger.error(
                f"Error retrieving directory structure: {e}", exc_info=True
            )
            return make_response(jsonify({"success": False, "error": str(e)}), 500)


@user_ns.route("/api/mcp_server/test")
class TestMCPServerConfig(Resource):
    @api.expect(
        api.model(
            "MCPServerTestModel",
            {
                "config": fields.Raw(
                    required=True, description="MCP server configuration to test"
                ),
            },
        )
    )
    @api.doc(description="Test MCP server connection with provided configuration")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()

        required_fields = ["config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            config = data["config"]

            auth_credentials = {}
            auth_type = config.get("auth_type", "none")

            if auth_type == "api_key" and "api_key" in config:
                auth_credentials["api_key"] = config["api_key"]
                if "api_key_header" in config:
                    auth_credentials["api_key_header"] = config["api_key_header"]
            elif auth_type == "bearer" and "bearer_token" in config:
                auth_credentials["bearer_token"] = config["bearer_token"]
            elif auth_type == "basic":
                if "username" in config:
                    auth_credentials["username"] = config["username"]
                if "password" in config:
                    auth_credentials["password"] = config["password"]

            test_config = config.copy()
            test_config["auth_credentials"] = auth_credentials

            mcp_tool = MCPTool(test_config, user)
            result = mcp_tool.test_connection()

            return make_response(jsonify(result), 200)
        except Exception as e:
            current_app.logger.error(f"Error testing MCP server: {e}", exc_info=True)
            return make_response(
                jsonify(
                    {"success": False, "error": f"Connection test failed: {str(e)}"}
                ),
                500,
            )


@user_ns.route("/api/mcp_server/save")
class MCPServerSave(Resource):
    @api.expect(
        api.model(
            "MCPServerSaveModel",
            {
                "id": fields.String(
                    required=False, description="Tool ID for updates (optional)"
                ),
                "displayName": fields.String(
                    required=True, description="Display name for the MCP server"
                ),
                "config": fields.Raw(
                    required=True, description="MCP server configuration"
                ),
                "status": fields.Boolean(
                    required=False, default=True, description="Tool status"
                ),
            },
        )
    )
    @api.doc(description="Create or update MCP server with automatic tool discovery")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()

        required_fields = ["displayName", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            config = data["config"]

            auth_credentials = {}
            auth_type = config.get("auth_type", "none")
            if auth_type == "api_key":
                if "api_key" in config and config["api_key"]:
                    auth_credentials["api_key"] = config["api_key"]
                if "api_key_header" in config:
                    auth_credentials["api_key_header"] = config["api_key_header"]
            elif auth_type == "bearer":
                if "bearer_token" in config and config["bearer_token"]:
                    auth_credentials["bearer_token"] = config["bearer_token"]
            elif auth_type == "basic":
                if "username" in config and config["username"]:
                    auth_credentials["username"] = config["username"]
                if "password" in config and config["password"]:
                    auth_credentials["password"] = config["password"]
            mcp_config = config.copy()
            mcp_config["auth_credentials"] = auth_credentials

            if auth_type == "none" or auth_credentials:
                mcp_tool = MCPTool(mcp_config, user)
                mcp_tool.discover_tools()
                actions_metadata = mcp_tool.get_actions_metadata()
            else:
                raise Exception(
                    "No valid credentials provided for the selected authentication type"
                )

            storage_config = config.copy()
            if auth_credentials:
                encrypted_credentials_string = encrypt_credentials(
                    auth_credentials, user
                )
                storage_config["encrypted_credentials"] = encrypted_credentials_string

            for field in [
                "api_key",
                "bearer_token",
                "username",
                "password",
                "api_key_header",
            ]:
                storage_config.pop(field, None)
            transformed_actions = []
            for action in actions_metadata:
                action["active"] = True
                if "parameters" in action:
                    if "properties" in action["parameters"]:
                        for param_name, param_details in action["parameters"][
                            "properties"
                        ].items():
                            param_details["filled_by_llm"] = True
                            param_details["value"] = ""
                transformed_actions.append(action)
            tool_data = {
                "name": "mcp_tool",
                "displayName": data["displayName"],
                "customName": data["displayName"],
                "description": f"MCP Server: {storage_config.get('server_url', 'Unknown')}",
                "config": storage_config,
                "actions": transformed_actions,
                "status": data.get("status", True),
                "user": user,
            }

            tool_id = data.get("id")
            if tool_id:
                result = user_tools_collection.update_one(
                    {"_id": ObjectId(tool_id), "user": user, "name": "mcp_tool"},
                    {"$set": {k: v for k, v in tool_data.items() if k != "user"}},
                )
                if result.matched_count == 0:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "Tool not found or access denied",
                            }
                        ),
                        404,
                    )
                response_data = {
                    "success": True,
                    "id": tool_id,
                    "message": f"MCP server updated successfully! Discovered {len(transformed_actions)} tools.",
                    "tools_count": len(transformed_actions),
                }
            else:
                result = user_tools_collection.insert_one(tool_data)
                tool_id = str(result.inserted_id)
                response_data = {
                    "success": True,
                    "id": tool_id,
                    "message": f"MCP server created successfully! Discovered {len(transformed_actions)} tools.",
                    "tools_count": len(transformed_actions),
                }
            return make_response(jsonify(response_data), 200)
        except Exception as e:
            current_app.logger.error(f"Error saving MCP server: {e}", exc_info=True)
            return make_response(
                jsonify(
                    {"success": False, "error": f"Failed to save MCP server: {str(e)}"}
                ),
                500,
            )
