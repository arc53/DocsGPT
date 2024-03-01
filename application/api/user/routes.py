import os
from flask import Blueprint, request, jsonify
import requests
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename

from application.api.user.tasks import ingest

from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
vectors_collection = db["vectors"]
prompts_collection = db["prompts"]
feedback_collection = db["feedback"]
user = Blueprint('user', __name__)

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

@user.route("/api/get_conversations", methods=["get"])
def get_conversations():
    # provides a list of conversations
    conversations = conversations_collection.find().sort("date", -1).limit(30)
    list_conversations = []
    for conversation in conversations:
        list_conversations.append({"id": str(conversation["_id"]), "name": conversation["name"]})

    #list_conversations = [{"id": "default", "name": "default"}, {"id": "jeff", "name": "jeff"}]

    return jsonify(list_conversations)


@user.route("/api/get_single_conversation", methods=["get"])
def get_single_conversation():
    # provides data for a conversation
    conversation_id = request.args.get("id")
    conversation = conversations_collection.find_one({"_id": ObjectId(conversation_id)})
    return jsonify(conversation['queries'])

@user.route("/api/update_conversation_name", methods=["POST"])
def update_conversation_name():
    # update data for a conversation
    data = request.get_json()
    id = data["id"]
    name = data["name"]
    conversations_collection.update_one({"_id": ObjectId(id)},{"$set":{"name":name}})
    return {"status": "ok"}


@user.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json()
    question = data["question"]
    answer = data["answer"]
    feedback = data["feedback"]


    feedback_collection.insert_one(
        {
            "question": question,
            "answer": answer,
            "feedback": feedback,
        }
    )
    return {"status": "ok"}

@user.route("/api/delete_by_ids", methods=["get"])
def delete_by_ids():
    """Delete by ID. These are the IDs in the vectorstore"""

    ids = request.args.get("path")
    if not ids:
        return {"status": "error"}

    if settings.VECTOR_STORE == "faiss":
        result = vectors_collection.delete_index(ids=ids)
        if result:
            return {"status": "ok"}
    return {"status": "error"}

@user.route("/api/delete_old", methods=["get"])
def delete_old():
    """Delete old indexes."""
    import shutil

    path = request.args.get("path")
    dirs = path.split("/")
    dirs_clean = []
    for i in range(0, len(dirs)):
        dirs_clean.append(secure_filename(dirs[i]))
    # check that path strats with indexes or vectors

    if dirs_clean[0] not in ["indexes", "vectors"]:
        return {"status": "error"}
    path_clean = "/".join(dirs_clean)
    vectors_collection.delete_one({"name": dirs_clean[-1], 'user': dirs_clean[-2]})
    if settings.VECTOR_STORE == "faiss":
        try:
            shutil.rmtree(os.path.join(current_dir, path_clean))
        except FileNotFoundError:
            pass
    else:
        vetorstore = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE, path=os.path.join(current_dir, path_clean)
        )
        vetorstore.delete_index()
        
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
    if "file" not in request.files:
        print("No file part")
        return {"status": "no file"}
    file = request.files["file"]
    if file.filename == "":
        return {"status": "no file name"}

    if file:
        filename = secure_filename(file.filename)
        # save dir
        save_dir = os.path.join(current_dir, settings.UPLOAD_FOLDER, user, job_name)
        # create dir if not exists
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        file.save(os.path.join(save_dir, filename))
        task = ingest.delay(settings.UPLOAD_FOLDER, [".rst", ".md", ".pdf", ".txt", ".docx", 
        ".csv", ".epub", ".html", ".mdx"],
         job_name, filename, user)
        # task id
        task_id = task.id
        return {"status": "ok", "task_id": task_id}
    else:
        return {"status": "error"}

@user.route("/api/task_status", methods=["GET"])
def task_status():
    """Get celery job status."""
    task_id = request.args.get("task_id")
    from application.celery import celery
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
            "language": "default",
            "version": "",
            "description": "default",
            "fullName": "default",
            "date": "default",
            "docLink": "default",
            "model": settings.EMBEDDINGS_NAME,
            "location": "remote",
        }
    ]
    # structure: name, language, version, description, fullName, date, docLink
    # append data from vectors_collection
    for index in vectors_collection.find({"user": user}):
        data.append(
            {
                "name": index["name"],
                "language": index["language"],
                "version": "",
                "description": index["name"],
                "fullName": index["name"],
                "date": index["date"],
                "docLink": index["location"],
                "model": settings.EMBEDDINGS_NAME,
                "location": "local",
            }
        )
    if settings.VECTOR_STORE == "faiss":
        data_remote = requests.get("https://d3dg1063dc54p9.cloudfront.net/combined.json").json()
        for index in data_remote:
            index["location"] = "remote"
            data.append(index)

    return jsonify(data)


@user.route("/api/docs_check", methods=["POST"])
def check_docs():
    # check if docs exist in a vectorstore folder
    data = request.get_json()
    # split docs on / and take first part
    if data["docs"].split("/")[0] == "local":
        return {"status": "exists"}
    vectorstore = "vectors/" + data["docs"]
    base_path = "https://raw.githubusercontent.com/arc53/DocsHUB/main/"
    if os.path.exists(vectorstore) or data["docs"] == "default":
        return {"status": "exists"}
    else:
        r = requests.get(base_path + vectorstore + "index.faiss")

        if r.status_code != 200:
            return {"status": "null"}
        else:
            if not os.path.exists(vectorstore):
                os.makedirs(vectorstore)
            with open(vectorstore + "index.faiss", "wb") as f:
                f.write(r.content)

            # download the store
            r = requests.get(base_path + vectorstore + "index.pkl")
            with open(vectorstore + "index.pkl", "wb") as f:
                f.write(r.content)

        return {"status": "loaded"}

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
    if prompt_id == 'default':
        with open(os.path.join(current_dir, "prompts", "chat_combine_default.txt"), "r") as f:
            chat_combine_template = f.read()
        return jsonify({"content": chat_combine_template})
    elif prompt_id == 'creative':
        with open(os.path.join(current_dir, "prompts", "chat_combine_creative.txt"), "r") as f:
            chat_reduce_creative = f.read()
        return jsonify({"content": chat_reduce_creative})
    elif prompt_id == 'strict':
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
    prompts_collection.update_one({"_id": ObjectId(id)},{"$set":{"name":name, "content": content}})
    return {"status": "ok"}





