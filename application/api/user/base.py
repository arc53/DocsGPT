"""
Shared utilities, database connections, and helper functions for user API routes.
"""

import datetime
import os
import uuid
from functools import wraps
from typing import Optional, Tuple

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, Response
from pymongo import ReturnDocument
from werkzeug.utils import secure_filename

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.storage.storage_creator import StorageCreator
from application.vectorstore.vector_creator import VectorCreator


storage = StorageCreator.get_storage()


mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]


conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
feedback_collection = db["feedback"]
agents_collection = db["agents"]
agent_folders_collection = db["agent_folders"]
token_usage_collection = db["token_usage"]
shared_conversations_collections = db["shared_conversations"]
users_collection = db["users"]
user_logs_collection = db["user_logs"]
user_tools_collection = db["user_tools"]
attachments_collection = db["attachments"]
workflow_runs_collection = db["workflow_runs"]
workflows_collection = db["workflows"]
workflow_nodes_collection = db["workflow_nodes"]
workflow_edges_collection = db["workflow_edges"]


try:
    agents_collection.create_index(
        [("shared", 1)],
        name="shared_index",
        background=True,
    )
    users_collection.create_index("user_id", unique=True)
    workflows_collection.create_index(
        [("user", 1)], name="workflow_user_index", background=True
    )
    workflow_nodes_collection.create_index(
        [("workflow_id", 1)], name="node_workflow_index", background=True
    )
    workflow_nodes_collection.create_index(
        [("workflow_id", 1), ("graph_version", 1)],
        name="node_workflow_graph_version_index",
        background=True,
    )
    workflow_edges_collection.create_index(
        [("workflow_id", 1)], name="edge_workflow_index", background=True
    )
    workflow_edges_collection.create_index(
        [("workflow_id", 1), ("graph_version", 1)],
        name="edge_workflow_graph_version_index",
        background=True,
    )
except Exception as e:
    print("Error creating indexes:", e)
current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def generate_minute_range(start_date, end_date):
    """Generate a dictionary with minute-level time ranges."""
    return {
        (start_date + datetime.timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:00"): 0
        for i in range(int((end_date - start_date).total_seconds() // 60) + 1)
    }


def generate_hourly_range(start_date, end_date):
    """Generate a dictionary with hourly time ranges."""
    return {
        (start_date + datetime.timedelta(hours=i)).strftime("%Y-%m-%d %H:00"): 0
        for i in range(int((end_date - start_date).total_seconds() // 3600) + 1)
    }


def generate_date_range(start_date, end_date):
    """Generate a dictionary with daily date ranges."""
    return {
        (start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d"): 0
        for i in range((end_date - start_date).days + 1)
    }


def ensure_user_doc(user_id):
    """
    Ensure user document exists with proper agent preferences structure.

    Args:
        user_id: The user ID to ensure

    Returns:
        The user document
    """
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
    """
    Resolve tool IDs to their details.

    Args:
        tool_ids: List of tool IDs

    Returns:
        List of tool details with id, name, and display_name
    """
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
    Get the Vector Store for a given source ID.

    Args:
        source_id (str): source id of the document

    Returns:
        Vector store instance
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
    """
    Handle image file upload from request.

    Args:
        request: Flask request object
        existing_url: Existing image URL (fallback)
        user: User ID
        storage: Storage instance
        base_path: Base path for upload

    Returns:
        Tuple of (image_url, error_response)
    """
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


def require_agent(func):
    """
    Decorator to require valid agent webhook token.

    Args:
        func: Function to decorate

    Returns:
        Wrapped function
    """

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
