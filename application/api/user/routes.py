import os
import uuid
import shutil
from flask import Blueprint, request, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.binary import Binary, UuidRepresentation
from werkzeug.utils import secure_filename
from bson.dbref import DBRef
from application.api.user.tasks import ingest, ingest_remote

from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
feedback_collection = db["feedback"]
api_key_collection = db["api_keys"]
shared_conversations_collections = db["shared_conversations"]

user = Blueprint("user", __name__)

current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@user.route("/api/delete_conversation", methods=["POST"])
def delete_conversation():
    # deletes a conversation from the database
    conversation_id = request.args.get("id")
    # write to mongodb
    conversations_collection.delete_one(
        {
            "_id": ObjectId(conversation_id),
        }
    )

    return {"status": "ok"}


@user.route("/api/delete_all_conversations", methods=["GET"])
def delete_all_conversations():
    user_id = "local"
    conversations_collection.delete_many({"user": user_id})
    return {"status": "ok"}


@user.route("/api/get_conversations", methods=["get"])
def get_conversations():
    # provides a list of conversations
    conversations = conversations_collection.find().sort("date", -1).limit(30)
    list_conversations = []
    for conversation in conversations:
        list_conversations.append({"id": str(conversation["_id"]), "name": conversation["name"]})

    # list_conversations = [{"id": "default", "name": "default"}, {"id": "jeff", "name": "jeff"}]

    return jsonify(list_conversations)


@user.route("/api/get_single_conversation", methods=["get"])
def get_single_conversation():
    # provides data for a conversation
    conversation_id = request.args.get("id")
    conversation = conversations_collection.find_one({"_id": ObjectId(conversation_id)})
    return jsonify(conversation["queries"])


@user.route("/api/update_conversation_name", methods=["POST"])
def update_conversation_name():
    # update data for a conversation
    data = request.get_json()
    id = data["id"]
    name = data["name"]
    conversations_collection.update_one({"_id": ObjectId(id)}, {"$set": {"name": name}})
    return {"status": "ok"}


@user.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json()
    question = data["question"]
    answer = data["answer"]
    feedback = data["feedback"]
    new_doc = {"question": question, "answer": answer, "feedback": feedback}
    if "api_key" in data:
        new_doc["api_key"] = data["api_key"]
    feedback_collection.insert_one(new_doc)
    return {"status": "ok"}


@user.route("/api/delete_by_ids", methods=["get"])
def delete_by_ids():
    """Delete by ID. These are the IDs in the vectorstore"""

    ids = request.args.get("path")
    if not ids:
        return {"status": "error"}

    if settings.VECTOR_STORE == "faiss":
        result = sources_collection.delete_index(ids=ids)
        if result:
            return {"status": "ok"}
    return {"status": "error"}


@user.route("/api/delete_old", methods=["get"])
def delete_old():
    """Delete old indexes."""
    import shutil
    source_id = request.args.get("source_id")
    doc = sources_collection.find_one({
        "_id": ObjectId(source_id),
        "user": "local",
    })
    if(doc is None):
        return {"status":"not found"},404
    if settings.VECTOR_STORE == "faiss":
        try:
            shutil.rmtree(os.path.join(current_dir, str(doc["_id"])))
        except FileNotFoundError:
            pass
    else:
        vetorstore = VectorCreator.create_vectorstore(settings.VECTOR_STORE, source_id=str(doc["_id"]))
        vetorstore.delete_index()
    sources_collection.delete_one({
        "_id": ObjectId(source_id),
    })

    return {"status": "ok"}


@user.route("/api/upload", methods=["POST"])
def upload_file():
    """Upload a file to get vectorized and indexed."""
    if "user" not in request.form:
        return {"status": "no user"}
    user = secure_filename(request.form["user"])
    if "name" not in request.form:
        return {"status": "no name"}
    job_name = secure_filename(request.form["name"])
    # check if the post request has the file part
    files = request.files.getlist("file")

    if not files or all(file.filename == "" for file in files):
        return {"status": "no file name"}

    # Directory where files will be saved
    save_dir = os.path.join(current_dir, settings.UPLOAD_FOLDER, user, job_name)
    os.makedirs(save_dir, exist_ok=True)

    if len(files) > 1:
        # Multiple files; prepare them for zip
        temp_dir = os.path.join(save_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)

        for file in files:
            filename = secure_filename(file.filename)
            file.save(os.path.join(temp_dir, filename))

        # Use shutil.make_archive to zip the temp directory
        zip_path = shutil.make_archive(base_name=os.path.join(save_dir, job_name), format="zip", root_dir=temp_dir)
        final_filename = os.path.basename(zip_path)

        # Clean up the temporary directory after zipping
        shutil.rmtree(temp_dir)
    else:
        # Single file
        file = files[0]
        final_filename = secure_filename(file.filename)
        file_path = os.path.join(save_dir, final_filename)
        file.save(file_path)

    # Call ingest with the single file or zipped file
    task = ingest.delay(
        settings.UPLOAD_FOLDER,
        [".rst", ".md", ".pdf", ".txt", ".docx", ".csv", ".epub", ".html", ".mdx"],
        job_name,
        final_filename,
        user,
    )

    return {"status": "ok", "task_id": task.id}


@user.route("/api/remote", methods=["POST"])
def upload_remote():
    """Upload a remote source to get vectorized and indexed."""
    if "user" not in request.form:
        return {"status": "no user"}
    user = secure_filename(request.form["user"])
    if "source" not in request.form:
        return {"status": "no source"}
    source = secure_filename(request.form["source"])
    if "name" not in request.form:
        return {"status": "no name"}
    job_name = secure_filename(request.form["name"])
    if "data" not in request.form:
        print("No data")
        return {"status": "no data"}
    source_data = request.form["data"]

    if source_data:
        task = ingest_remote.delay(source_data=source_data, job_name=job_name, user=user, loader=source)
        task_id = task.id
        return {"status": "ok", "task_id": task_id}
    else:
        return {"status": "error"}


@user.route("/api/task_status", methods=["GET"])
def task_status():
    """Get celery job status."""
    task_id = request.args.get("task_id")
    from application.celery_init import celery

    task = celery.AsyncResult(task_id)
    task_meta = task.info
    return {"status": task.status, "result": task_meta}


@user.route("/api/combine", methods=["GET"])
def combined_json():
    user = "local"
    """Provide json file with combined available indexes."""
    # get json from https://d3dg1063dc54p9.cloudfront.net/combined.json

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
    # structure: name, language, version, description, fullName, date, docLink
    # append data from sources_collection in sorted order in descending order of date
    for index in sources_collection.find({"user": user}).sort("date", -1):
        data.append(
            {
                "id": str(index["_id"]),
                "name": index["name"],
                "date": index["date"],
                "model": settings.EMBEDDINGS_NAME,
                "location": "local",
                "tokens": index["tokens"] if ("tokens" in index.keys()) else "",
                "retriever": index["retriever"] if ("retriever" in index.keys()) else "classic",
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

    return jsonify(data)


@user.route("/api/docs_check", methods=["POST"])
def check_docs():
    data = request.get_json()

    vectorstore = "vectors/" + secure_filename(data["docs"])
    if os.path.exists(vectorstore) or data["docs"] == "default":
        return {"status": "exists"}
    else:
        return {"status": "not found"}


@user.route("/api/create_prompt", methods=["POST"])
def create_prompt():
    data = request.get_json()
    content = data["content"]
    name = data["name"]
    if name == "":
        return {"status": "error"}
    user = "local"
    resp = prompts_collection.insert_one(
        {
            "name": name,
            "content": content,
            "user": user,
        }
    )
    new_id = str(resp.inserted_id)
    return {"id": new_id}


@user.route("/api/get_prompts", methods=["GET"])
def get_prompts():
    user = "local"
    prompts = prompts_collection.find({"user": user})
    list_prompts = []
    list_prompts.append({"id": "default", "name": "default", "type": "public"})
    list_prompts.append({"id": "creative", "name": "creative", "type": "public"})
    list_prompts.append({"id": "strict", "name": "strict", "type": "public"})
    for prompt in prompts:
        list_prompts.append({"id": str(prompt["_id"]), "name": prompt["name"], "type": "private"})

    return jsonify(list_prompts)


@user.route("/api/get_single_prompt", methods=["GET"])
def get_single_prompt():
    prompt_id = request.args.get("id")
    if prompt_id == "default":
        with open(os.path.join(current_dir, "prompts", "chat_combine_default.txt"), "r") as f:
            chat_combine_template = f.read()
        return jsonify({"content": chat_combine_template})
    elif prompt_id == "creative":
        with open(os.path.join(current_dir, "prompts", "chat_combine_creative.txt"), "r") as f:
            chat_reduce_creative = f.read()
        return jsonify({"content": chat_reduce_creative})
    elif prompt_id == "strict":
        with open(os.path.join(current_dir, "prompts", "chat_combine_strict.txt"), "r") as f:
            chat_reduce_strict = f.read()
        return jsonify({"content": chat_reduce_strict})

    prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})
    return jsonify({"content": prompt["content"]})


@user.route("/api/delete_prompt", methods=["POST"])
def delete_prompt():
    data = request.get_json()
    id = data["id"]
    prompts_collection.delete_one(
        {
            "_id": ObjectId(id),
        }
    )
    return {"status": "ok"}


@user.route("/api/update_prompt", methods=["POST"])
def update_prompt_name():
    data = request.get_json()
    id = data["id"]
    name = data["name"]
    content = data["content"]
    # check if name is null
    if name == "":
        return {"status": "error"}
    prompts_collection.update_one({"_id": ObjectId(id)}, {"$set": {"name": name, "content": content}})
    return {"status": "ok"}


@user.route("/api/get_api_keys", methods=["GET"])
def get_api_keys():
    user = "local"
    keys = api_key_collection.find({"user": user})
    list_keys = []
    for key in keys:
        if "source" in key and isinstance(key["source"],DBRef):
            source = db.dereference(key["source"])
            if source is None:
                continue
            else:
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
    return jsonify(list_keys)


@user.route("/api/create_api_key", methods=["POST"])
def create_api_key():
    data = request.get_json()
    name = data["name"]
    prompt_id = data["prompt_id"]
    chunks = data["chunks"]
    key = str(uuid.uuid4())
    user = "local"
    new_api_key = {
        "name": name,
        "key": key,
        "user": user,
        "prompt_id": prompt_id,
        "chunks": chunks,
    }
    if "source" in data and ObjectId.is_valid(data["source"]):
        new_api_key["source"] = DBRef("sources", ObjectId(data["source"]))
    if "retriever" in data:
        new_api_key["retriever"] = data["retriever"]
    resp = api_key_collection.insert_one(new_api_key)
    new_id = str(resp.inserted_id)
    return {"id": new_id, "key": key}


@user.route("/api/delete_api_key", methods=["POST"])
def delete_api_key():
    data = request.get_json()
    id = data["id"]
    api_key_collection.delete_one(
        {
            "_id": ObjectId(id),
        }
    )
    return {"status": "ok"}


# route to share conversation
##isPromptable should be passed through queries
@user.route("/api/share", methods=["POST"])
def share_conversation():
    try:
        data = request.get_json()
        user = "local" if "user" not in data else data["user"]
        conversation_id = data["conversation_id"]
        isPromptable = request.args.get("isPromptable").lower() == "true"

        conversation = conversations_collection.find_one({"_id": ObjectId(conversation_id)})
        if(conversation is None):
            raise Exception("Conversation does not exist")
        current_n_queries = len(conversation["queries"])

        ##generate binary representation of uuid
        explicit_binary = Binary.from_uuid(uuid.uuid4(), UuidRepresentation.STANDARD)

        if isPromptable:
            prompt_id = "default" if "prompt_id" not in data else data["prompt_id"]
            chunks = "2" if "chunks" not in data else data["chunks"]

            name = conversation["name"] + "(shared)"
            new_api_key_data =  {
                    "prompt_id": prompt_id,
                    "chunks": chunks,
                    "user": user,
                }
            if "source" in data and ObjectId.is_valid(data["source"]):
                new_api_key_data["source"] = DBRef("sources",ObjectId(data["source"]))
            elif "retriever" in data:
                new_api_key_data["retriever"] = data["retriever"]
                 
            pre_existing_api_document = api_key_collection.find_one(
                new_api_key_data
            )
            if pre_existing_api_document:
                api_uuid = pre_existing_api_document["key"]
                pre_existing = shared_conversations_collections.find_one(
                    {
                        "conversation_id": DBRef("conversations", ObjectId(conversation_id)),
                        "isPromptable": isPromptable,
                        "first_n_queries": current_n_queries,
                        "user": user,
                        "api_key": api_uuid,
                    }
                )
                if pre_existing is not None:
                    return (
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
                            "isPromptable": isPromptable,
                            "first_n_queries": current_n_queries,
                            "user": user,
                            "api_key": api_uuid,
                        }
                    )
                    return jsonify({"success": True, "identifier": str(explicit_binary.as_uuid())})
            else:
                
                api_uuid = str(uuid.uuid4())
                new_api_key_data["key"] = api_uuid
                new_api_key_data["name"] = name
                if "source" in data and ObjectId.is_valid(data["source"]):
                    new_api_key_data["source"] = DBRef("sources", ObjectId(data["source"]))
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
                    "isPromptable": isPromptable,
                    "first_n_queries": current_n_queries,
                    "user": user,
                    "api_key": api_uuid,
                }
              )
            ## Identifier as route parameter in frontend
            return (
                jsonify({"success": True, "identifier": str(explicit_binary.as_uuid())}),
                201,
            )

        ##isPromptable = False
        pre_existing = shared_conversations_collections.find_one(
            {
                "conversation_id": DBRef("conversations", ObjectId(conversation_id)),
                "isPromptable": isPromptable,
                "first_n_queries": current_n_queries,
                "user": user,
            }
        )
        if pre_existing is not None:
            return (
                jsonify({"success": True, "identifier": str(pre_existing["uuid"].as_uuid())}),
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
                    "isPromptable": isPromptable,
                    "first_n_queries": current_n_queries,
                    "user": user,
                }
            )
            ## Identifier as route parameter in frontend
            return (
                jsonify({"success": True, "identifier": str(explicit_binary.as_uuid())}),
                201,
            )
    except Exception as err:
        print(err)
        return jsonify({"success": False, "error": str(err)}), 400


# route to get publicly shared conversations
@user.route("/api/shared_conversation/<string:identifier>", methods=["GET"])
def get_publicly_shared_conversations(identifier: str):
    try:
        query_uuid = Binary.from_uuid(uuid.UUID(identifier), UuidRepresentation.STANDARD)
        shared = shared_conversations_collections.find_one({"uuid": query_uuid})
        conversation_queries = []
        if shared and "conversation_id" in shared and isinstance(shared["conversation_id"], DBRef):
            # Resolve the DBRef
            conversation_ref = shared["conversation_id"]
            conversation = db.dereference(conversation_ref)
            if conversation is None:
                return (
                    jsonify(
                        {
                            "sucess": False,
                            "error": "might have broken url or the conversation does not exist",
                        }
                    ),
                    404,
                )
            conversation_queries = conversation["queries"][: (shared["first_n_queries"])]
            for query in conversation_queries:
                query.pop("sources")  ## avoid exposing sources
        else:
            return (
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
        return jsonify(res), 200
    except Exception as err:
        print(err)
        return jsonify({"success": False, "error": str(err)}), 400
