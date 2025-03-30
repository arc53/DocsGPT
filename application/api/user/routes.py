import datetime
import json
import math
import os
import shutil
import uuid

from bson.binary import Binary, UuidRepresentation
from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import Blueprint, current_app, jsonify, make_response, redirect, request
from flask_restx import fields, inputs, Namespace, Resource
from werkzeug.utils import secure_filename

from application.agents.tools.tool_manager import ToolManager

from application.api.user.tasks import ingest, ingest_remote
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.extensions import api
from application.tts.google_tts import GoogleTTS
from application.utils import check_required_fields, validate_function_name
from application.vectorstore.vector_creator import VectorCreator

mongo = MongoDB.get_client()
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
proxies_collection = db["proxies"]
feedback_collection = db["feedback"]
api_key_collection = db["api_keys"]
token_usage_collection = db["token_usage"]
shared_conversations_collections = db["shared_conversations"]
user_logs_collection = db["user_logs"]
user_tools_collection = db["user_tools"]

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
            current_app.logger.error(f"Error deleting conversation: {err}")
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
            current_app.logger.error(f"Error deleting all conversations: {err}")
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
                    {"api_key": {"$exists": False}, "user": decoded_token.get("sub")}
                )
                .sort("date", -1)
                .limit(30)
            )

            list_conversations = [
                {"id": str(conversation["_id"]), "name": conversation["name"]}
                for conversation in conversations
            ]
        except Exception as err:
            current_app.logger.error(f"Error retrieving conversations: {err}")
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
        except Exception as err:
            current_app.logger.error(f"Error retrieving conversation: {err}")
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(conversation["queries"]), 200)


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
            current_app.logger.error(f"Error updating conversation name: {err}")
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
            current_app.logger.error(f"Error submitting feedback: {err}")
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
            current_app.logger.error(f"Error deleting indexes: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/delete_old")
class DeleteOldIndexes(Resource):
    @api.doc(
        description="Deletes old indexes",
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
        try:
            if settings.VECTOR_STORE == "faiss":
                shutil.rmtree(os.path.join(current_dir, "indexes", str(doc["_id"])))
            else:
                vectorstore = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE, source_id=str(doc["_id"])
                )
                vectorstore.delete_index()

        except FileNotFoundError:
            pass
        except Exception as err:
            current_app.logger.error(f"Error deleting old indexes: {err}")
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

        user = secure_filename(decoded_token.get("sub"))
        job_name = secure_filename(request.form["name"])
        try:
            save_dir = os.path.join(current_dir, settings.UPLOAD_FOLDER, user, job_name)
            os.makedirs(save_dir, exist_ok=True)

            if len(files) > 1:
                temp_dir = os.path.join(save_dir, "temp")
                os.makedirs(temp_dir, exist_ok=True)

                for file in files:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(temp_dir, filename))
                    print(f"Saved file: {filename}")
                zip_path = shutil.make_archive(
                    base_name=os.path.join(save_dir, job_name),
                    format="zip",
                    root_dir=temp_dir,
                )
                final_filename = os.path.basename(zip_path)
                shutil.rmtree(temp_dir)
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
                    final_filename,
                    user,
                )
            else:
                file = files[0]
                final_filename = secure_filename(file.filename)
                file_path = os.path.join(save_dir, final_filename)
                file.save(file_path)

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
                    final_filename,
                    user,
                )

        except Exception as err:
            current_app.logger.error(f"Error uploading file: {err}")
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


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
            current_app.logger.error(f"Error uploading remote source: {err}")
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
            current_app.logger.error(f"Error getting task status: {err}")
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
            current_app.logger.error(f"Error retrieving paginated sources: {err}")
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
                    }
                )

            if "duckduck_search" in settings.RETRIEVERS_ENABLED:
                data.append(
                    {
                        "name": "DuckDuckGo Search",
                        "date": "duckduck_search",
                        "model": settings.EMBEDDINGS_NAME,
                        "location": "custom",
                        "tokens": "",
                        "retriever": "duckduck_search",
                    }
                )

            if "brave_search" in settings.RETRIEVERS_ENABLED:
                data.append(
                    {
                        "name": "Brave Search",
                        "language": "en",
                        "date": "brave_search",
                        "model": settings.EMBEDDINGS_NAME,
                        "location": "custom",
                        "tokens": "",
                        "retriever": "brave_search",
                    }
                )

        except Exception as err:
            current_app.logger.error(f"Error retrieving sources: {err}")
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
            current_app.logger.error(f"Error checking document: {err}")
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
            current_app.logger.error(f"Error creating prompt: {err}")
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
            current_app.logger.error(f"Error retrieving prompts: {err}")
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
            current_app.logger.error(f"Error retrieving prompt: {err}")
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
            current_app.logger.error(f"Error deleting prompt: {err}")
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
            current_app.logger.error(f"Error updating prompt: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"success": True}), 200)

@user_ns.route("/api/get_proxies")
class GetProxies(Resource):
    @api.doc(description="Get all proxies for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            proxies = proxies_collection.find({"user": user})
            list_proxies = [
                {"id": "none", "name": "None", "type": "public"},
            ]

            for proxy in proxies:
                list_proxies.append(
                    {
                        "id": str(proxy["_id"]),
                        "name": proxy["name"],
                        "type": "private",
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving proxies: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify(list_proxies), 200)


@user_ns.route("/api/get_single_proxy")
class GetSingleProxy(Resource):
    @api.doc(params={"id": "ID of the proxy"}, description="Get a single proxy by ID")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        proxy_id = request.args.get("id")
        if not proxy_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )

        try:
            if proxy_id == "none":
                return make_response(jsonify({"connection": ""}), 200)

            proxy = proxies_collection.find_one(
                {"_id": ObjectId(proxy_id), "user": user}
            )
            if not proxy:
                return make_response(jsonify({"status": "not found"}), 404)
        except Exception as err:
            current_app.logger.error(f"Error retrieving proxy: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"connection": proxy["connection"]}), 200)


@user_ns.route("/api/create_proxy")
class CreateProxy(Resource):
    create_proxy_model = api.model(
        "CreateProxyModel",
        {
            "connection": fields.String(
                required=True, description="Connection string of the proxy"
            ),
            "name": fields.String(required=True, description="Name of the proxy"),
        },
    )

    @api.expect(create_proxy_model)
    @api.doc(description="Create a new proxy")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["connection", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        user = decoded_token.get("sub")
        try:
            resp = proxies_collection.insert_one(
                {
                    "name": data["name"],
                    "connection": data["connection"],
                    "user": user,
                }
            )
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating proxy: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"id": new_id}), 200)


@user_ns.route("/api/delete_proxy")
class DeleteProxy(Resource):
    delete_proxy_model = api.model(
        "DeleteProxyModel",
        {"id": fields.String(required=True, description="Proxy ID to delete")},
    )

    @api.expect(delete_proxy_model)
    @api.doc(description="Delete a proxy by ID")
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
            # Don't allow deleting the 'none' proxy
            if data["id"] == "none":
                return make_response(jsonify({"success": False, "message": "Cannot delete default proxy"}), 400)
                
            result = proxies_collection.delete_one({"_id": ObjectId(data["id"]), "user": user})
            if result.deleted_count == 0:
                return make_response(jsonify({"success": False, "message": "Proxy not found"}), 404)
        except Exception as err:
            current_app.logger.error(f"Error deleting proxy: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/update_proxy")
class UpdateProxy(Resource):
    update_proxy_model = api.model(
        "UpdateProxyModel",
        {
            "id": fields.String(required=True, description="Proxy ID to update"),
            "name": fields.String(required=True, description="New name of the proxy"),
            "connection": fields.String(
                required=True, description="New connection string of the proxy"
            ),
        },
    )

    @api.expect(update_proxy_model)
    @api.doc(description="Update an existing proxy")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "name", "connection"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            # Don't allow updating the 'none' proxy
            if data["id"] == "none":
                return make_response(jsonify({"success": False, "message": "Cannot update default proxy"}), 400)
                
            result = proxies_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"name": data["name"], "connection": data["connection"]}},
            )
            if result.modified_count == 0:
                return make_response(jsonify({"success": False, "message": "Proxy not found"}), 404)
        except Exception as err:
            current_app.logger.error(f"Error updating proxy: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"success": True}), 200)

@user_ns.route("/api/get_api_keys")
class GetApiKeys(Resource):
    @api.doc(description="Retrieve API keys for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            keys = api_key_collection.find({"user": user})
            list_keys = []
            for key in keys:
                if "source" in key and isinstance(key["source"], DBRef):
                    source = db.dereference(key["source"])
                    if source is None:
                        continue
                    source_name = source["name"]
                elif "retriever" in key:
                    source_name = key["retriever"]
                else:
                    continue

                list_keys.append(
                    {
                        "id": str(key["_id"]),
                        "name": key["name"],
                        "key": key["key"][:4] + "..." + key["key"][-4:],
                        "source": source_name,
                        "prompt_id": key["prompt_id"],
                        "chunks": key["chunks"],
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving API keys: {err}")
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_keys), 200)


@user_ns.route("/api/create_api_key")
class CreateApiKey(Resource):
    create_api_key_model = api.model(
        "CreateApiKeyModel",
        {
            "name": fields.String(required=True, description="Name of the API key"),
            "prompt_id": fields.String(required=True, description="Prompt ID"),
            "chunks": fields.Integer(required=True, description="Chunks count"),
            "source": fields.String(description="Source ID (optional)"),
            "retriever": fields.String(description="Retriever (optional)"),
        },
    )

    @api.expect(create_api_key_model)
    @api.doc(description="Create a new API key")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["name", "prompt_id", "chunks"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            key = str(uuid.uuid4())
            new_api_key = {
                "name": data["name"],
                "key": key,
                "user": user,
                "prompt_id": data["prompt_id"],
                "chunks": data["chunks"],
            }
            if "source" in data and ObjectId.is_valid(data["source"]):
                new_api_key["source"] = DBRef("sources", ObjectId(data["source"]))
            if "retriever" in data:
                new_api_key["retriever"] = data["retriever"]

            resp = api_key_collection.insert_one(new_api_key)
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating API key: {err}")
            return make_response(jsonify({"success": False}), 400)

        return make_response(jsonify({"id": new_id, "key": key}), 201)


@user_ns.route("/api/delete_api_key")
class DeleteApiKey(Resource):
    delete_api_key_model = api.model(
        "DeleteApiKeyModel",
        {"id": fields.String(required=True, description="API Key ID to delete")},
    )

    @api.expect(delete_api_key_model)
    @api.doc(description="Delete an API key by ID")
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
            result = api_key_collection.delete_one(
                {"_id": ObjectId(data["id"]), "user": user}
            )
            if result.deleted_count == 0:
                return {"success": False, "message": "API Key not found"}, 404
        except Exception as err:
            current_app.logger.error(f"Error deleting API key: {err}")
            return {"success": False}, 400

        return {"success": True}, 200


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

                pre_existing_api_document = api_key_collection.find_one(
                    new_api_key_data
                )
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

                    api_key_collection.insert_one(new_api_key_data)
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
            current_app.logger.error(f"Error sharing conversation: {err}")
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
                                "sucess": False,
                                "error": "might have broken url or the conversation does not exist",
                            }
                        ),
                        404,
                    )
                conversation_queries = conversation["queries"][
                    : (shared["first_n_queries"])
                ]
            else:
                return make_response(
                    jsonify(
                        {
                            "sucess": False,
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
            current_app.logger.error(f"Error getting shared conversation: {err}")
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
                api_key_collection.find_one(
                    {"_id": ObjectId(api_key_id), "user": user}
                )["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}")
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
            current_app.logger.error(f"Error getting message analytics: {err}")
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
                api_key_collection.find_one(
                    {"_id": ObjectId(api_key_id), "user": user}
                )["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}")
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
            current_app.logger.error(f"Error getting token analytics: {err}")
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
                api_key_collection.find_one(
                    {"_id": ObjectId(api_key_id), "user": user}
                )["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}")
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
            current_app.logger.error(f"Error getting feedback analytics: {err}")
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
                api_key_collection.find_one({"_id": ObjectId(api_key_id)})["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            current_app.logger.error(f"Error getting API key: {err}")
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
            current_app.logger.error(f"Error updating sync frequency: {err}")
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
            current_app.logger.error(f"Error synthesizing audio: {err}")
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
            current_app.logger.error(f"Error getting available tools: {err}")
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
            current_app.logger.error(f"Error getting user tools: {err}")
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
                "actions": transformed_actions,
                "config": data["config"],
                "status": data["status"],
            }
            resp = user_tools_collection.insert_one(new_tool)
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating tool: {err}")
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
                update_data["config"] = data["config"]
            if "status" in data:
                update_data["status"] = data["status"]

            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": update_data},
            )
        except Exception as err:
            current_app.logger.error(f"Error updating tool: {err}")
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
            current_app.logger.error(f"Error updating tool config: {err}")
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
            current_app.logger.error(f"Error updating tool actions: {err}")
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
            current_app.logger.error(f"Error updating tool status: {err}")
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
            current_app.logger.error(f"Error deleting tool: {err}")
            return {"success": False}, 400

        return {"success": True}, 200


@user_ns.route("/api/get_chunks")
class GetChunks(Resource):
    @api.doc(
        description="Retrieves all chunks associated with a document",
        params={"id": "The document ID"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        doc_id = request.args.get("id")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))

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
                    }
                ),
                200,
            )

        except Exception as e:
            current_app.logger.error(f"Error getting chunks: {e}")
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
            current_app.logger.error(f"Error adding chunk: {e}")
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
            current_app.logger.error(f"Error deleting chunk: {e}")
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

            deleted = store.delete_chunk(chunk_id)
            if not deleted:
                return make_response(
                    jsonify({"error": "Failed to delete existing chunk"}), 500
                )

            new_text = text if text is not None else existing_chunk["text"]
            new_metadata = (
                metadata if metadata is not None else existing_chunk["metadata"]
            )

            new_chunk_id = store.add_chunk(new_text, new_metadata)

            return make_response(
                jsonify(
                    {
                        "message": "Chunk updated successfully",
                        "new_chunk_id": new_chunk_id,
                    }
                ),
                200,
            )
        except Exception as e:
            current_app.logger.error(f"Error updating chunk: {e}")
            return make_response(jsonify({"success": False}), 500)
