import asyncio
import datetime
import json
import logging
import os
import sys
import traceback

from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import Blueprint, current_app, make_response, request, Response
from flask_restx import fields, Namespace, Resource

from pymongo import MongoClient

from application.core.settings import settings
from application.error import bad_request
from application.extensions import api
from application.llm.llm_creator import LLMCreator
from application.retriever.retriever_creator import RetrieverCreator
from application.utils import check_required_fields

logger = logging.getLogger(__name__)

mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
api_key_collection = db["api_keys"]
user_logs_collection = db["user_logs"]

answer = Blueprint("answer", __name__)
answer_ns = Namespace("answer", description="Answer related operations", path="/")
api.add_namespace(answer_ns)

gpt_model = ""
# to have some kind of default behaviour
if settings.LLM_NAME == "openai":
    gpt_model = "gpt-3.5-turbo"
elif settings.LLM_NAME == "anthropic":
    gpt_model = "claude-2"
elif settings.LLM_NAME == "groq":
    gpt_model = "llama3-8b-8192"

if settings.MODEL_NAME:  # in case there is particular model name configured
    gpt_model = settings.MODEL_NAME

# load the prompts
current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
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
        data["retriever"] = None

    if "source" in data and isinstance(data["source"], DBRef):
        source_doc = db.dereference(data["source"])
        data["source"] = str(source_doc["_id"])
        if "retriever" in source_doc:
            data["retriever"] = source_doc["retriever"]
    else:
        data["source"] = {}
    return data


def get_retriever(source_id: str):
    doc = sources_collection.find_one({"_id": ObjectId(source_id)})
    if doc is None:
        raise Exception("Source document does not exist", 404)
    retriever_name = None if "retriever" not in doc else doc["retriever"]
    return retriever_name


def is_azure_configured():
    return (
        settings.OPENAI_API_BASE
        and settings.OPENAI_API_VERSION
        and settings.AZURE_DEPLOYMENT_NAME
    )


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
                "language as the system \n\nUser: "
                + question
                + "\n\n"
                + "AI: "
                + response,
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


def complete_stream(
    question, retriever, conversation_id, user_api_key, isNoneDoc=False
):

    try:
        response_full = ""
        source_log_docs = []
        answer = retriever.gen()
        sources = retriever.search()
        for source in sources:
            if "text" in source:
                source["text"] = source["text"][:100].strip() + "..."
        if len(sources) > 0:
            data = json.dumps({"type": "source", "source": sources})
            yield f"data: {data}\n\n"
        for line in answer:
            if "answer" in line:
                response_full += str(line["answer"])
                data = json.dumps(line)
                yield f"data: {data}\n\n"
            elif "source" in line:
                source_log_docs.append(line["source"])

        if isNoneDoc:
            for doc in source_log_docs:
                doc["source"] = "None"

        llm = LLMCreator.create_llm(
            settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=user_api_key
        )
        if user_api_key is None:
            conversation_id = save_conversation(
                conversation_id, question, response_full, source_log_docs, llm
            )
            # send data.type = "end" to indicate that the stream has ended as json
            data = json.dumps({"type": "id", "id": str(conversation_id)})
            yield f"data: {data}\n\n"

        retriever_params = retriever.get_params()
        user_logs_collection.insert_one(
            {
                "action": "stream_answer",
                "level": "info",
                "user": "local",
                "api_key": user_api_key,
                "question": question,
                "response": response_full,
                "sources": source_log_docs,
                "retriever_params": retriever_params,
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
            }
        )
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


@answer_ns.route("/stream")
class Stream(Resource):
    stream_model = api.model(
        "StreamModel",
        {
            "question": fields.String(
                required=True, description="Question to be asked"
            ),
            "history": fields.List(
                fields.String, required=False, description="Chat history"
            ),
            "conversation_id": fields.String(
                required=False, description="Conversation ID"
            ),
            "prompt_id": fields.String(
                required=False, default="default", description="Prompt ID"
            ),
            "chunks": fields.Integer(
                required=False, default=2, description="Number of chunks"
            ),
            "token_limit": fields.Integer(required=False, description="Token limit"),
            "retriever": fields.String(required=False, description="Retriever type"),
            "api_key": fields.String(required=False, description="API key"),
            "active_docs": fields.String(
                required=False, description="Active documents"
            ),
            "isNoneDoc": fields.Boolean(
                required=False, description="Flag indicating if no document is used"
            ),
        },
    )

    @api.expect(stream_model)
    @api.doc(description="Stream a response based on the question and retriever")
    def post(self):
        data = request.get_json()
        required_fields = ["question"]

        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            question = data["question"]
            history = data.get("history", [])
            history = json.loads(history)
            conversation_id = data.get("conversation_id")
            prompt_id = data.get("prompt_id", "default")
            

            chunks = int(data.get("chunks", 2))
            token_limit = data.get("token_limit", settings.DEFAULT_MAX_HISTORY)
            retriever_name = data.get("retriever", "classic")

            if "api_key" in data:
                data_key = get_data_from_api_key(data["api_key"])
                chunks = int(data_key.get("chunks", 2))
                prompt_id = data_key.get("prompt_id", "default")
                source = {"active_docs": data_key.get("source")}
                retriever_name = data_key.get("retriever", retriever_name)
                user_api_key = data["api_key"]

            elif "active_docs" in data:
                source = {"active_docs": data["active_docs"]}
                retriever_name = get_retriever(data["active_docs"]) or retriever_name
                user_api_key = None

            else:
                source = {}
                user_api_key = None

            current_app.logger.info(
                f"/stream - request_data: {data}, source: {source}",
                extra={"data": json.dumps({"request_data": data, "source": source})},
            )

            prompt = get_prompt(prompt_id)
            if "isNoneDoc" in data and data["isNoneDoc"] is True:
                chunks = 0
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
                    isNoneDoc=data.get("isNoneDoc"),
                ),
                mimetype="text/event-stream",
            )

        except ValueError:
            message = "Malformed request body"
            print("\033[91merr", str(message), file=sys.stderr)
            return Response(
                error_stream_generate(message),
                status=400,
                mimetype="text/event-stream",
            )
        except Exception as e:
            current_app.logger.error(
                f"/stream - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            message = e.args[0]
            status_code = 400
            # Custom exceptions with two arguments, index 1 as status code
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


@answer_ns.route("/api/answer")
class Answer(Resource):
    answer_model = api.model(
        "AnswerModel",
        {
            "question": fields.String(
                required=True, description="The question to answer"
            ),
            "history": fields.List(
                fields.String, required=False, description="Conversation history"
            ),
            "conversation_id": fields.String(
                required=False, description="Conversation ID"
            ),
            "prompt_id": fields.String(
                required=False, default="default", description="Prompt ID"
            ),
            "chunks": fields.Integer(
                required=False, default=2, description="Number of chunks"
            ),
            "token_limit": fields.Integer(required=False, description="Token limit"),
            "retriever": fields.String(required=False, description="Retriever type"),
            "api_key": fields.String(required=False, description="API key"),
            "active_docs": fields.String(
                required=False, description="Active documents"
            ),
            "isNoneDoc": fields.Boolean(
                required=False, description="Flag indicating if no document is used"
            ),
        },
    )

    @api.expect(answer_model)
    @api.doc(description="Provide an answer based on the question and retriever")
    def post(self):
        data = request.get_json()
        required_fields = ["question"]       
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            question = data["question"]
            history = data.get("history", [])
            conversation_id = data.get("conversation_id")
            prompt_id = data.get("prompt_id", "default")
            chunks = int(data.get("chunks", 2))
            token_limit = data.get("token_limit", settings.DEFAULT_MAX_HISTORY)
            retriever_name = data.get("retriever", "classic")

            if "api_key" in data:
                data_key = get_data_from_api_key(data["api_key"])
                chunks = int(data_key.get("chunks", 2))
                prompt_id = data_key.get("prompt_id", "default")
                source = {"active_docs": data_key.get("source")}
                retriever_name = data_key.get("retriever", retriever_name)
                user_api_key = data["api_key"]
            elif "active_docs" in data:
                source = {"active_docs": data["active_docs"]}
                retriever_name = get_retriever(data["active_docs"]) or retriever_name
                user_api_key = None
            else:
                source = {}
                user_api_key = None

            prompt = get_prompt(prompt_id)

            current_app.logger.info(
                f"/api/answer - request_data: {data}, source: {source}",
                extra={"data": json.dumps({"request_data": data, "source": source})},
            )

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

            if data.get("isNoneDoc"):
                for doc in source_log_docs:
                    doc["source"] = "None"

            llm = LLMCreator.create_llm(
                settings.LLM_NAME, api_key=settings.API_KEY, user_api_key=user_api_key
            )

            result = {"answer": response_full, "sources": source_log_docs}
            result["conversation_id"] = str(
                save_conversation(
                    conversation_id, question, response_full, source_log_docs, llm
                )
            )
            retriever_params = retriever.get_params()
            user_logs_collection.insert_one(
                {
                    "action": "api_answer",
                    "level": "info",
                    "user": "local",
                    "api_key": user_api_key,
                    "question": question,
                    "response": response_full,
                    "sources": source_log_docs,
                    "retriever_params": retriever_params,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc),
                }
            )

        except Exception as e:
            current_app.logger.error(
                f"/api/answer - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return bad_request(500, str(e))

        return make_response(result, 200)


@answer_ns.route("/api/search")
class Search(Resource):
    search_model = api.model(
        "SearchModel",
        {
            "question": fields.String(
                required=True, description="The question to search"
            ),
            "chunks": fields.Integer(
                required=False, default=2, description="Number of chunks"
            ),
            "api_key": fields.String(
                required=False, description="API key for authentication"
            ),
            "active_docs": fields.String(
                required=False, description="Active documents for retrieval"
            ),
            "retriever": fields.String(required=False, description="Retriever type"),
            "token_limit": fields.Integer(
                required=False, description="Limit for tokens"
            ),
            "isNoneDoc": fields.Boolean(
                required=False, description="Flag indicating if no document is used"
            ),
        },
    )

    @api.expect(search_model)
    @api.doc(
        description="Search for relevant documents based on the question and retriever"
    )
    def post(self):
        data = request.get_json()
        required_fields = ["question"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        try:
            question = data["question"]
            chunks = int(data.get("chunks", 2))
            token_limit = data.get("token_limit", settings.DEFAULT_MAX_HISTORY)
            retriever_name = data.get("retriever", "classic")

            if "api_key" in data:
                data_key = get_data_from_api_key(data["api_key"])
                chunks = int(data_key.get("chunks", 2))
                source = {"active_docs": data_key.get("source")}
                user_api_key = data["api_key"]
            elif "active_docs" in data:
                source = {"active_docs": data["active_docs"]}
                user_api_key = None
            else:
                source = {}
                user_api_key = None

            current_app.logger.info(
                f"/api/answer - request_data: {data}, source: {source}",
                extra={"data": json.dumps({"request_data": data, "source": source})},
            )

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
            retriever_params = retriever.get_params()

            user_logs_collection.insert_one(
                {
                    "action": "api_search",
                    "level": "info",
                    "user": "local",
                    "api_key": user_api_key,
                    "question": question,
                    "sources": docs,
                    "retriever_params": retriever_params,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc),
                }
            )

            if data.get("isNoneDoc"):
                for doc in docs:
                    doc["source"] = "None"

        except Exception as e:
            current_app.logger.error(
                f"/api/search - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return bad_request(500, str(e))

        return make_response(docs, 200)
