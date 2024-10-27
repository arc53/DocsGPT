import datetime
import os
import shutil
import uuid

from bson.binary import Binary, UuidRepresentation
from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import Blueprint, jsonify, make_response, request
from flask_restx import inputs, fields, Namespace, Resource
from pymongo import MongoClient
from werkzeug.utils import secure_filename

from application.api.user.tasks import ingest, ingest_remote

from application.core.settings import settings
from application.extensions import api
from application.utils import check_required_fields
from application.vectorstore.vector_creator import VectorCreator

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
feedback_collection = db["feedback"]
api_key_collection = db["api_keys"]
token_usage_collection = db["token_usage"]
shared_conversations_collections = db["shared_conversations"]
user_logs_collection = db["user_logs"]

user = Blueprint("user", __name__)
user_ns = Namespace("user", description="User related operations", path="/")
api.add_namespace(user_ns)

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


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


@user_ns.route("/api/delete_conversation")
class DeleteConversation(Resource):
    @api.doc(
        description="Deletes a conversation by ID",
        params={"id": "The ID of the conversation to delete"},
    )
    def post(self):
        conversation_id = request.args.get("id")
        if not conversation_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )

        try:
            conversations_collection.delete_one({"_id": ObjectId(conversation_id)})
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/delete_all_conversations")
class DeleteAllConversations(Resource):
    @api.doc(
        description="Deletes all conversations for a specific user",
    )
    def get(self):
        user_id = "local"
        try:
            conversations_collection.delete_many({"user": user_id})
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/get_conversations")
class GetConversations(Resource):
    @api.doc(
        description="Retrieve a list of the latest 30 conversations",
    )
    def get(self):
        try:
            conversations = conversations_collection.find().sort("date", -1).limit(30)
            list_conversations = [
                {"id": str(conversation["_id"]), "name": conversation["name"]}
                for conversation in conversations
            ]
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        return make_response(jsonify(list_conversations), 200)


@user_ns.route("/api/get_single_conversation")
class GetSingleConversation(Resource):
    @api.doc(
        description="Retrieve a single conversation by ID",
        params={"id": "The conversation ID"},
    )
    def get(self):
        conversation_id = request.args.get("id")
        if not conversation_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )

        try:
            conversation = conversations_collection.find_one(
                {"_id": ObjectId(conversation_id)}
            )
            if not conversation:
                return make_response(jsonify({"status": "not found"}), 404)
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
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
        data = request.get_json()
        required_fields = ["id", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            conversations_collection.update_one(
                {"_id": ObjectId(data["id"])}, {"$set": {"name": data["name"]}}
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/feedback")
class SubmitFeedback(Resource):
    @api.expect(
        api.model(
            "FeedbackModel",
            {
                "question": fields.String(
                    required=True, description="The user question"
                ),
                "answer": fields.String(required=True, description="The AI answer"),
                "feedback": fields.String(required=True, description="User feedback"),
                "api_key": fields.String(description="Optional API key"),
            },
        )
    )
    @api.doc(
        description="Submit feedback for a conversation",
    )
    def post(self):
        data = request.get_json()
        required_fields = ["question", "answer", "feedback"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        new_doc = {
            "question": data["question"],
            "answer": data["answer"],
            "feedback": data["feedback"],
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
        }

        if "api_key" in data:
            new_doc["api_key"] = data["api_key"]

        try:
            feedback_collection.insert_one(new_doc)
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify({"success": False}), 400)


@user_ns.route("/api/delete_old")
class DeleteOldIndexes(Resource):
    @api.doc(
        description="Deletes old indexes",
        params={"source_id": "The source ID to delete"},
    )
    def get(self):
        source_id = request.args.get("source_id")
        if not source_id:
            return make_response(
                jsonify({"success": False, "message": "Missing required fields"}), 400
            )

        try:
            doc = sources_collection.find_one(
                {"_id": ObjectId(source_id), "user": "local"}
            )
            if not doc:
                return make_response(jsonify({"status": "not found"}), 404)

            if settings.VECTOR_STORE == "faiss":
                shutil.rmtree(os.path.join(current_dir, "indexes", str(doc["_id"])))
            else:
                vectorstore = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE, source_id=str(doc["_id"])
                )
                vectorstore.delete_index()

            sources_collection.delete_one({"_id": ObjectId(source_id)})
        except FileNotFoundError:
            pass
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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

        user = secure_filename(request.form["user"])
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

                zip_path = shutil.make_archive(
                    base_name=os.path.join(save_dir, job_name),
                    format="zip",
                    root_dir=temp_dir,
                )
                final_filename = os.path.basename(zip_path)
                shutil.rmtree(temp_dir)
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
                    ],
                    job_name,
                    final_filename,
                    user,
                )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.form
        required_fields = ["user", "source", "name", "data"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            if "repo_url" in data:
                source_data = data["repo_url"]
                loader = "github"
            else:
                source_data = data["data"]
                loader = data["source"]

            task = ingest_remote.delay(
                source_data=source_data,
                job_name=data["name"],
                user=data["user"],
                loader=loader,
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify({"status": task.status, "result": task_meta}), 200)


@user_ns.route("/api/combine")
class CombinedJson(Resource):
    @api.doc(description="Provide JSON file with combined available indexes")
    def get(self):
        user = "local"
        data = [
            {
                "name": "default",
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.get_json()
        required_fields = ["content", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        user = "local"
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify({"id": new_id}), 200)


@user_ns.route("/api/get_prompts")
class GetPrompts(Resource):
    @api.doc(description="Get all prompts for the user")
    def get(self):
        user = "local"
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify(list_prompts), 200)


@user_ns.route("/api/get_single_prompt")
class GetSinglePrompt(Resource):
    @api.doc(params={"id": "ID of the prompt"}, description="Get a single prompt by ID")
    def get(self):
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

            prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            prompts_collection.delete_one({"_id": ObjectId(data["id"])})
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.get_json()
        required_fields = ["id", "name", "content"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            prompts_collection.update_one(
                {"_id": ObjectId(data["id"])},
                {"$set": {"name": data["name"], "content": data["content"]}},
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify({"success": True}), 200)


@user_ns.route("/api/get_api_keys")
class GetApiKeys(Resource):
    @api.doc(description="Retrieve API keys for the user")
    def get(self):
        user = "local"
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
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
        data = request.get_json()
        required_fields = ["name", "prompt_id", "chunks"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        user = "local"
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            result = api_key_collection.delete_one({"_id": ObjectId(data["id"])})
            if result.deleted_count == 0:
                return {"success": False, "message": "API Key not found"}, 404
        except Exception as err:
            return {"success": False, "error": str(err)}, 400

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

        user = data.get("user", "local")
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)


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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)


@user_ns.route("/api/get_message_analytics")
class GetMessageAnalytics(Resource):
    get_message_analytics_model = api.model(
        "GetMessageAnalyticsModel",
        {
            "api_key_id": fields.String(
                required=False,
                description="API Key ID",
            ),
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
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                api_key_collection.find_one({"_id": ObjectId(api_key_id)})["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
            group_stage = {
                "$group": {
                    "_id": {
                        "minute": {
                            "$dateToString": {"format": group_format, "date": "$date"}
                        }
                    },
                    "total_messages": {"$sum": 1},
                }
            }

        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
            group_stage = {
                "$group": {
                    "_id": {
                        "hour": {
                            "$dateToString": {"format": group_format, "date": "$date"}
                        }
                    },
                    "total_messages": {"$sum": 1},
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
                            "$dateToString": {"format": group_format, "date": "$date"}
                        }
                    },
                    "total_messages": {"$sum": 1},
                }
            }

        try:
            match_stage = {
                "$match": {
                    "date": {"$gte": start_date, "$lte": end_date},
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key
            message_data = conversations_collection.aggregate(
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

            daily_messages = {interval: 0 for interval in intervals}

            for entry in message_data:
                if filter_option == "last_hour":
                    daily_messages[entry["_id"]["minute"]] = entry["total_messages"]
                elif filter_option == "last_24_hour":
                    daily_messages[entry["_id"]["hour"]] = entry["total_messages"]
                else:
                    daily_messages[entry["_id"]["day"]] = entry["total_messages"]

        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                api_key_collection.find_one({"_id": ObjectId(api_key_id)})["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
        data = request.get_json()
        api_key_id = data.get("api_key_id")
        filter_option = data.get("filter_option", "last_30_days")

        try:
            api_key = (
                api_key_collection.find_one({"_id": ObjectId(api_key_id)})["key"]
                if api_key_id
                else None
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if filter_option == "last_hour":
            start_date = end_date - datetime.timedelta(hours=1)
            group_format = "%Y-%m-%d %H:%M:00"
            group_stage_1 = {
                "$group": {
                    "_id": {
                        "minute": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        },
                        "feedback": "$feedback",
                    },
                    "count": {"$sum": 1},
                }
            }
            group_stage_2 = {
                "$group": {
                    "_id": "$_id.minute",
                    "likes": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.feedback", "LIKE"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                    "dislikes": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.feedback", "DISLIKE"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                }
            }

        elif filter_option == "last_24_hour":
            start_date = end_date - datetime.timedelta(hours=24)
            group_format = "%Y-%m-%d %H:00"
            group_stage_1 = {
                "$group": {
                    "_id": {
                        "hour": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        },
                        "feedback": "$feedback",
                    },
                    "count": {"$sum": 1},
                }
            }
            group_stage_2 = {
                "$group": {
                    "_id": "$_id.hour",
                    "likes": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.feedback", "LIKE"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                    "dislikes": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.feedback", "DISLIKE"]},
                                "$count",
                                0,
                            ]
                        }
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
            group_stage_1 = {
                "$group": {
                    "_id": {
                        "day": {
                            "$dateToString": {
                                "format": group_format,
                                "date": "$timestamp",
                            }
                        },
                        "feedback": "$feedback",
                    },
                    "count": {"$sum": 1},
                }
            }
            group_stage_2 = {
                "$group": {
                    "_id": "$_id.day",
                    "likes": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.feedback", "LIKE"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                    "dislikes": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.feedback", "DISLIKE"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                }
            }

        try:
            match_stage = {
                "$match": {
                    "timestamp": {"$gte": start_date, "$lte": end_date},
                }
            }
            if api_key:
                match_stage["$match"]["api_key"] = api_key

            feedback_data = feedback_collection.aggregate(
                [
                    match_stage,
                    group_stage_1,
                    group_stage_2,
                    {"$sort": {"_id": 1}},
                ]
            )

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
                    "positive": entry["likes"],
                    "negative": entry["dislikes"],
                }

        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

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
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        query = {}
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
                    "user": "local",
                },
                update_data,
            )
        except Exception as err:
            return make_response(jsonify({"success": False, "error": str(err)}), 400)

        return make_response(jsonify({"success": True}), 200)
