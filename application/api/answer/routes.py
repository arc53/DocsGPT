import asyncio
import os
import sys
from flask import Blueprint, request, Response
import json
import datetime
import logging
import traceback

from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.dbref import DBRef

from application.core.settings import settings
from application.llm.llm_creator import LLMCreator
from application.retriever.retriever_creator import RetrieverCreator
from application.error import bad_request

logger = logging.getLogger(__name__)

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
vectors_collection = db["vectors"]
prompts_collection = db["prompts"]
api_key_collection = db["api_keys"]
answer = Blueprint("answer", __name__)

gpt_model = ""
# to have some kind of default behaviour
if settings.LLM_NAME == "openai":
    gpt_model = "gpt-3.5-turbo"
elif settings.LLM_NAME == "anthropic":
    gpt_model = "claude-2"

if settings.MODEL_NAME:  # in case there is particular model name configured
    gpt_model = settings.MODEL_NAME

# load the prompts
current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(current_dir, "prompts", "chat_combine_default.txt"), "r") as f:
    chat_combine_template = f.read()

with open(os.path.join(current_dir, "prompts", "chat_reduce_prompt.txt"), "r") as f:
    chat_reduce_template = f.read()

with open(os.path.join(current_dir, "prompts", "chat_combine_creative.txt"), "r") as f:
    chat_combine_creative = f.read()

with open(os.path.join(current_dir, "prompts", "chat_combine_strict.txt"), "r") as f:
    chat_combine_strict = f.read()

api_key_set = settings.API_KEY is not None
embeddings_key_set = settings.EMBEDDINGS_KEY is not None


async def async_generate(chain, question, chat_history):
    result = await chain.arun({"question": question, "chat_history": chat_history})
    return result


def run_async_chain(chain, question, chat_history):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = {}
    try:
        answer = loop.run_until_complete(async_generate(chain, question, chat_history))
    finally:
        loop.close()
    result["answer"] = answer
    return result


def get_data_from_api_key(api_key):
    data = api_key_collection.find_one({"key": api_key})
    # # Raise custom exception if the API key is not found
    if data is None:
        raise Exception("Invalid API Key, please generate new key", 401)

    if "retriever" not in data:
        data["retriever"] = "classic"

    if "source" in data and isinstance(data["source"], DBRef):
        source_doc = db.dereference(data["source"])
        data["source"] = str(source_doc._id)
        if "retriever" in source_doc:
            data["retriever"] = source_doc["retriever"]
    return data


def get_retriever(source_id: str):
    doc = vectors_collection.find_one({"_id": ObjectId(source_id)})
    if doc is None:
        raise Exception("Source document does not exist", 404)
    retriever_name = "classic" if "retriever" not in doc else doc["retriever"]
    return retriever_name


def get_vectorstore(data):
    if "active_docs" in data:
        if data["active_docs"].split("/")[0] == "default":
            vectorstore = ""
        elif data["active_docs"].split("/")[0] == "local":
            vectorstore = "indexes/" + data["active_docs"]
        else:
            vectorstore = "vectors/" + data["active_docs"]
        if data["active_docs"] == "default":
            vectorstore = ""
    else:
        vectorstore = ""
    vectorstore = os.path.join("application", vectorstore)
    return vectorstore


def is_azure_configured():
    return settings.OPENAI_API_BASE and settings.OPENAI_API_VERSION and settings.AZURE_DEPLOYMENT_NAME


def save_conversation(conversation_id, question, response, source_log_docs, llm):
    if conversation_id is not None and conversation_id != "None":
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id)},
            {
                "$push": {
                    "queries": {
                        "prompt": question,
                        "response": response,
                        "sources": source_log_docs,
                    }
                }
            },
        )

    else:
        # create new conversation
        # generate summary
        messages_summary = [
            {
                "role": "assistant",
                "content": "Summarise following conversation in no more than 3 "
                "words, respond ONLY with the summary, use the same "
                "language as the system \n\nUser: " + question + "\n\n" + "AI: " + response,
            },
            {
                "role": "user",
                "content": "Summarise following conversation in no more than 3 words, "
                "respond ONLY with the summary, use the same language as the "
                "system",
            },
        ]

        completion = llm.gen(model=gpt_model, messages=messages_summary, max_tokens=30)
        conversation_id = conversations_collection.insert_one(
            {
                "user": "local",
                "date": datetime.datetime.utcnow(),
                "name": completion,
                "queries": [
                    {
                        "prompt": question,
                        "response": response,
                        "sources": source_log_docs,
                    }
                ],
            }
        ).inserted_id
    return conversation_id


def get_prompt(prompt_id):
    if prompt_id == "default":
        prompt = chat_combine_template
    elif prompt_id == "creative":
        prompt = chat_combine_creative
    elif prompt_id == "strict":
        prompt = chat_combine_strict
    else:
        prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})["content"]
    return prompt


def complete_stream(question, retriever, conversation_id, user_api_key):
    try:
        response_full = ""
        source_log_docs = []
        answer = retriever.gen()
        for line in answer:
            if "answer" in line:
                response_full += str(line["answer"])
                data = json.dumps(line)
                yield f"data: {data}\n\n"
            elif "source" in line:
                source_log_docs.append(line["source"])

        llm = LLMCreator.create_llm(settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=user_api_key)
        if user_api_key is None:
            conversation_id = save_conversation(conversation_id, question, response_full, source_log_docs, llm)
            # send data.type = "end" to indicate that the stream has ended as json
            data = json.dumps({"type": "id", "id": str(conversation_id)})
            yield f"data: {data}\n\n"

        data = json.dumps({"type": "end"})
        yield f"data: {data}\n\n"
    except Exception as e:
        print("\033[91merr", str(e), file=sys.stderr)
        data = json.dumps(
            {
                "type": "error",
                "error": "Please try again later. We apologize for any inconvenience.",
                "error_exception": str(e),
            }
        )
        yield f"data: {data}\n\n"
        return


@answer.route("/stream", methods=["POST"])
def stream():
    try:
        data = request.get_json()
        # get parameter from url question
        question = data["question"]
        if "history" not in data:
            history = []
        else:
            history = data["history"]
            history = json.loads(history)
        if "conversation_id" not in data:
            conversation_id = None
        else:
            conversation_id = data["conversation_id"]
        if "prompt_id" in data:
            prompt_id = data["prompt_id"]
        else:
            prompt_id = "default"
        if "selectedDocs" in data and data["selectedDocs"] is None:
            chunks = 0
        elif "chunks" in data:
            chunks = int(data["chunks"])
        else:
            chunks = 2
        if "token_limit" in data:
            token_limit = data["token_limit"]
        else:
            token_limit = settings.DEFAULT_MAX_HISTORY

        ## retriever can be "brave_search, duckduck_search or classic"
        retriever_name = data["retriever"] if "retriever" in data else "classic"

        # check if active_docs or api_key is set
        if "api_key" in data:
            data_key = get_data_from_api_key(data["api_key"])
            chunks = int(data_key["chunks"])
            prompt_id = data_key["prompt_id"]
            source = {"active_docs": data_key["source"]}
            retriever_name = data_key["retriever"]
            user_api_key = data["api_key"]

        elif "active_docs" in data:
            source = {"active_docs" : data["active_docs"]}
            retriever_name = get_retriever(data["active_docs"])    
            user_api_key = None

        else:
            source = {}
            user_api_key = None

        """ if source["active_docs"].split("/")[0] == "default" or source["active_docs"].split("/")[0] == "local":
            retriever_name = "classic"
        else:
            retriever_name = source["active_docs"] """

        prompt = get_prompt(prompt_id)

        retriever = RetrieverCreator.create_retriever(
            retriever_name,
            question=question,
            source=source,
            chat_history=history,
            prompt=prompt,
            chunks=chunks,
            token_limit=token_limit,
            gpt_model=gpt_model,
            user_api_key=user_api_key,
        )

        return Response(
            complete_stream(
                question=question,
                retriever=retriever,
                conversation_id=conversation_id,
                user_api_key=user_api_key,
            ),
            mimetype="text/event-stream",
        )

    except ValueError as err:
        message = "Malformed request body"
        print("\033[91merr", str(err), file=sys.stderr)
        return Response(
            error_stream_generate(message),
            status=400,
            mimetype="text/event-stream",
        )
    except Exception as e:
        print("\033[91merr", str(e), file=sys.stderr)
        message = e.args[0]
        status_code = 400
        # # Custom exceptions with two arguments, index 1 as status code
        if len(e.args) >= 2:
            status_code = e.args[1]
        return Response(
            error_stream_generate(message),
            status=status_code,
            mimetype="text/event-stream",
        )


def error_stream_generate(err_response):
    data = json.dumps({"type": "error", "error": err_response})
    yield f"data: {data}\n\n"


@answer.route("/api/answer", methods=["POST"])
def api_answer():
    data = request.get_json()
    question = data["question"]
    if "history" not in data:
        history = []
    else:
        history = data["history"]
    if "conversation_id" not in data:
        conversation_id = None
    else:
        conversation_id = data["conversation_id"]
    print("-" * 5)
    if "prompt_id" in data:
        prompt_id = data["prompt_id"]
    else:
        prompt_id = "default"
    if "chunks" in data:
        chunks = int(data["chunks"])
    else:
        chunks = 2
    if "token_limit" in data:
        token_limit = data["token_limit"]
    else:
        token_limit = settings.DEFAULT_MAX_HISTORY

    ## retriever can be brave_search, duckduck_search or classic
    retriever_name = data["retriever"] if "retriever" in data else "classic"

    # use try and except  to check for exception
    try:
        # check if the vectorstore is set
        if "api_key" in data:
            data_key = get_data_from_api_key(data["api_key"])
            chunks = int(data_key["chunks"])
            prompt_id = data_key["prompt_id"]
            source = data_key["source"]
            user_api_key = data["api_key"]
        elif "active_docs" in data:
            source = data["active_docs"]
            user_api_key = None

        prompt = get_prompt(prompt_id)

        retriever = RetrieverCreator.create_retriever(
            retriever_name,
            question=question,
            source=source,
            chat_history=history,
            prompt=prompt,
            chunks=chunks,
            token_limit=token_limit,
            gpt_model=gpt_model,
            user_api_key=user_api_key,
        )
        source_log_docs = []
        response_full = ""
        for line in retriever.gen():
            if "source" in line:
                source_log_docs.append(line["source"])
            elif "answer" in line:
                response_full += line["answer"]

        llm = LLMCreator.create_llm(settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=user_api_key)

        result = {"answer": response_full, "sources": source_log_docs}
        result["conversation_id"] = str(
            save_conversation(conversation_id, question, response_full, source_log_docs, llm)
        )

        return result
    except Exception as e:
        # print whole traceback
        traceback.print_exc()
        print(str(e))
        return bad_request(500, str(e))


@answer.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json()
    # get parameter from url question
    question = data["question"]
    if "chunks" in data:
        chunks = int(data["chunks"])
    else:
        chunks = 2
    if "api_key" in data:
        data_key = get_data_from_api_key(data["api_key"])
        chunks = int(data_key["chunks"])
        source = data_key["source"]
        user_api_key = data_key["api_key"]
    elif "active_docs" in data:
        source = data["active_docs"]
        user_api_key = None
    else:
        source = {}
        user_api_key = None

    if "retriever" in data:
        retriever_name = data["retriever"]
    else:
        retriever_name = "classic"
    if "token_limit" in data:
        token_limit = data["token_limit"]
    else:
        token_limit = settings.DEFAULT_MAX_HISTORY

    retriever = RetrieverCreator.create_retriever(
        retriever_name,
        question=question,
        source=source,
        chat_history=[],
        prompt="default",
        chunks=chunks,
        token_limit=token_limit,
        gpt_model=gpt_model,
        user_api_key=user_api_key,
    )
    docs = retriever.search()
    return docs
