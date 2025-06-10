import asyncio
import datetime
import json
import logging
import os
import traceback

from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import Blueprint, make_response, request, Response
from flask_restx import fields, Namespace, Resource

from application.agents.agent_creator import AgentCreator

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.error import bad_request
from application.extensions import api
from application.llm.llm_creator import LLMCreator
from application.retriever.retriever_creator import RetrieverCreator
from application.utils import check_required_fields, limit_chat_history

logger = logging.getLogger(__name__)

mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]
conversations_collection = db["conversations"]
sources_collection = db["sources"]
prompts_collection = db["prompts"]
agents_collection = db["agents"]
user_logs_collection = db["user_logs"]
attachments_collection = db["attachments"]

answer = Blueprint("answer", __name__)
answer_ns = Namespace("answer", description="Answer related operations", path="/")
api.add_namespace(answer_ns)

gpt_model = ""
# to have some kind of default behaviour
if settings.LLM_NAME == "openai":
    gpt_model = "gpt-4o-mini"
elif settings.LLM_NAME == "anthropic":
    gpt_model = "claude-2"
elif settings.LLM_NAME == "groq":
    gpt_model = "llama3-8b-8192"
elif settings.LLM_NAME == "novita":
    gpt_model = "deepseek/deepseek-r1"

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


def get_agent_key(agent_id, user_id):
    if not agent_id:
        return None, False, None

    try:
        agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
        if agent is None:
            raise Exception("Agent not found", 404)

        is_owner = agent.get("user") == user_id

        if is_owner:
            agents_collection.update_one(
                {"_id": ObjectId(agent_id)},
                {"$set": {"lastUsedAt": datetime.datetime.now(datetime.timezone.utc)}},
            )
            return str(agent["key"]), False, None

        is_shared_with_user = agent.get(
            "shared_publicly", False
        ) or user_id in agent.get("shared_with", [])

        if is_shared_with_user:
            return str(agent["key"]), True, agent.get("shared_token")

        raise Exception("Unauthorized access to the agent", 403)

    except Exception as e:
        logger.error(f"Error in get_agent_key: {str(e)}", exc_info=True)
        raise


def get_data_from_api_key(api_key):
    data = agents_collection.find_one({"key": api_key})
    if not data:
        raise Exception("Invalid API Key, please generate a new key", 401)

    source = data.get("source")
    if isinstance(source, DBRef):
        source_doc = db.dereference(source)
        data["source"] = str(source_doc["_id"])
        data["retriever"] = source_doc.get("retriever", data.get("retriever"))
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


def save_conversation(
    conversation_id,
    question,
    response,
    thought,
    source_log_docs,
    tool_calls,
    llm,
    decoded_token,
    index=None,
    api_key=None,
    agent_id=None,
    is_shared_usage=False,
    shared_token=None,
    attachment_ids=None,
):
    current_time = datetime.datetime.now(datetime.timezone.utc)
    if conversation_id is not None and index is not None:
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id), f"queries.{index}": {"$exists": True}},
            {
                "$set": {
                    f"queries.{index}.prompt": question,
                    f"queries.{index}.response": response,
                    f"queries.{index}.thought": thought,
                    f"queries.{index}.sources": source_log_docs,
                    f"queries.{index}.tool_calls": tool_calls,
                    f"queries.{index}.timestamp": current_time,
                    f"queries.{index}.attachments": attachment_ids,
                }
            },
        )
        ##remove following queries from the array
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id), f"queries.{index}": {"$exists": True}},
            {"$push": {"queries": {"$each": [], "$slice": index + 1}}},
        )
    elif conversation_id is not None and conversation_id != "None":
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id)},
            {
                "$push": {
                    "queries": {
                        "prompt": question,
                        "response": response,
                        "thought": thought,
                        "sources": source_log_docs,
                        "tool_calls": tool_calls,
                        "timestamp": current_time,
                        "attachments": attachment_ids,
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
                "language as the system",
            },
            {
                "role": "user",
                "content": "Summarise following conversation in no more than 3 words, "
                "respond ONLY with the summary, use the same language as the "
                "system \n\nUser: " + question + "\n\n" + "AI: " + response,
            },
        ]

        completion = llm.gen(model=gpt_model, messages=messages_summary, max_tokens=30)
        conversation_data = {
            "user": decoded_token.get("sub"),
            "date": datetime.datetime.utcnow(),
            "name": completion,
            "queries": [
                {
                    "prompt": question,
                    "response": response,
                    "thought": thought,
                    "sources": source_log_docs,
                    "tool_calls": tool_calls,
                    "timestamp": current_time,
                    "attachments": attachment_ids,
                }
            ],
        }
        if api_key:
            if agent_id:
                conversation_data["agent_id"] = agent_id
                if is_shared_usage:
                    conversation_data["is_shared_usage"] = is_shared_usage
                    conversation_data["shared_token"] = shared_token
            api_key_doc = agents_collection.find_one({"key": api_key})
            if api_key_doc:
                conversation_data["api_key"] = api_key_doc["key"]
        conversation_id = conversations_collection.insert_one(
            conversation_data
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
    question,
    agent,
    retriever,
    conversation_id,
    user_api_key,
    decoded_token,
    isNoneDoc=False,
    index=None,
    should_save_conversation=True,
    attachment_ids=None,
    agent_id=None,
    is_shared_usage=False,
    shared_token=None,
):
    try:
        response_full, thought, source_log_docs, tool_calls = "", "", [], []

        answer = agent.gen(query=question, retriever=retriever)

        for line in answer:
            if "answer" in line:
                response_full += str(line["answer"])
                data = json.dumps({"type": "answer", "answer": line["answer"]})
                yield f"data: {data}\n\n"
            elif "sources" in line:
                truncated_sources = []
                source_log_docs = line["sources"]
                for source in line["sources"]:
                    truncated_source = source.copy()
                    if "text" in truncated_source:
                        truncated_source["text"] = (
                            truncated_source["text"][:100].strip() + "..."
                        )
                    truncated_sources.append(truncated_source)
                if len(truncated_sources) > 0:
                    data = json.dumps({"type": "source", "source": truncated_sources})
                    yield f"data: {data}\n\n"
            elif "tool_calls" in line:
                tool_calls = line["tool_calls"]
                data = json.dumps({"type": "tool_calls", "tool_calls": tool_calls})
                yield f"data: {data}\n\n"
            elif "thought" in line:
                thought += line["thought"]
                data = json.dumps({"type": "thought", "thought": line["thought"]})
                yield f"data: {data}\n\n"

        if isNoneDoc:
            for doc in source_log_docs:
                doc["source"] = "None"

        llm = LLMCreator.create_llm(
            settings.LLM_NAME,
            api_key=settings.API_KEY,
            user_api_key=user_api_key,
            decoded_token=decoded_token,
        )

        if should_save_conversation:
            conversation_id = save_conversation(
                conversation_id,
                question,
                response_full,
                thought,
                source_log_docs,
                tool_calls,
                llm,
                decoded_token,
                index,
                api_key=user_api_key,
                attachment_ids=attachment_ids,
                agent_id=agent_id,
                is_shared_usage=is_shared_usage,
                shared_token=shared_token,
            )
        else:
            conversation_id = None

        # send data.type = "end" to indicate that the stream has ended as json
        data = json.dumps({"type": "id", "id": str(conversation_id)})
        yield f"data: {data}\n\n"

        retriever_params = retriever.get_params()
        user_logs_collection.insert_one(
            {
                "action": "stream_answer",
                "level": "info",
                "user": decoded_token.get("sub"),
                "api_key": user_api_key,
                "question": question,
                "response": response_full,
                "sources": source_log_docs,
                "retriever_params": retriever_params,
                "attachments": attachment_ids,
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
            }
        )
        data = json.dumps({"type": "end"})
        yield f"data: {data}\n\n"
    except Exception as e:
        logger.error(f"Error in stream: {str(e)}", exc_info=True)
        data = json.dumps(
            {
                "type": "error",
                "error": "Please try again later. We apologize for any inconvenience.",
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
            "index": fields.Integer(
                required=False, description="Index of the query to update"
            ),
            "save_conversation": fields.Boolean(
                required=False,
                default=True,
                description="Whether to save the conversation",
            ),
            "attachments": fields.List(
                fields.String, required=False, description="List of attachment IDs"
            ),
        },
    )

    @api.expect(stream_model)
    @api.doc(description="Stream a response based on the question and retriever")
    def post(self):
        data = request.get_json()
        required_fields = ["question"]
        if "index" in data:
            required_fields = ["question", "conversation_id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        save_conv = data.get("save_conversation", True)

        try:
            question = data["question"]
            history = limit_chat_history(
                json.loads(data.get("history", "[]")), gpt_model=gpt_model
            )
            conversation_id = data.get("conversation_id")
            prompt_id = data.get("prompt_id", "default")
            attachment_ids = data.get("attachments", [])

            index = data.get("index", None)
            chunks = int(data.get("chunks", 2))
            token_limit = data.get("token_limit", settings.DEFAULT_MAX_HISTORY)
            retriever_name = data.get("retriever", "classic")
            agent_id = data.get("agent_id", None)
            agent_type = settings.AGENT_NAME
            decoded_token = getattr(request, "decoded_token", None)
            user_sub = decoded_token.get("sub") if decoded_token else None
            agent_key, is_shared_usage, shared_token = get_agent_key(
                agent_id, user_sub
            )

            if agent_key:
                data.update({"api_key": agent_key})
            else:
                agent_id = None

            if "api_key" in data:
                data_key = get_data_from_api_key(data["api_key"])
                chunks = int(data_key.get("chunks", 2))
                prompt_id = data_key.get("prompt_id", "default")
                source = {"active_docs": data_key.get("source")}
                retriever_name = data_key.get("retriever", retriever_name)
                user_api_key = data["api_key"]
                agent_type = data_key.get("agent_type", agent_type)
                if is_shared_usage:
                    decoded_token = request.decoded_token
                else:
                    decoded_token = {"sub": data_key.get("user")}
                    is_shared_usage = False

            elif "active_docs" in data:
                source = {"active_docs": data["active_docs"]}
                retriever_name = get_retriever(data["active_docs"]) or retriever_name
                user_api_key = None
                decoded_token = request.decoded_token

            else:
                source = {}
                user_api_key = None
                decoded_token = request.decoded_token

            if not decoded_token:
                return make_response({"error": "Unauthorized"}, 401)

            attachments = get_attachments_content(
                attachment_ids, decoded_token.get("sub")
            )

            logger.info(
                f"/stream - request_data: {data}, source: {source}, attachments: {len(attachments)}",
                extra={"data": json.dumps({"request_data": data, "source": source})},
            )

            prompt = get_prompt(prompt_id)
            if "isNoneDoc" in data and data["isNoneDoc"] is True:
                chunks = 0

            agent = AgentCreator.create_agent(
                agent_type,
                endpoint="stream",
                llm_name=settings.LLM_NAME,
                gpt_model=gpt_model,
                api_key=settings.API_KEY,
                user_api_key=user_api_key,
                prompt=prompt,
                chat_history=history,
                decoded_token=decoded_token,
                attachments=attachments,
            )

            retriever = RetrieverCreator.create_retriever(
                retriever_name,
                source=source,
                chat_history=history,
                prompt=prompt,
                chunks=chunks,
                token_limit=token_limit,
                gpt_model=gpt_model,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
            )

            return Response(
                complete_stream(
                    question=question,
                    agent=agent,
                    retriever=retriever,
                    conversation_id=conversation_id,
                    user_api_key=user_api_key,
                    decoded_token=decoded_token,
                    isNoneDoc=data.get("isNoneDoc"),
                    index=index,
                    should_save_conversation=save_conv,
                    attachment_ids=attachment_ids,
                    agent_id=agent_id,
                    is_shared_usage=is_shared_usage,
                    shared_token=shared_token,
                ),
                mimetype="text/event-stream",
            )

        except ValueError:
            message = "Malformed request body"
            logger.error(f"/stream - error: {message}")
            return Response(
                error_stream_generate(message),
                status=400,
                mimetype="text/event-stream",
            )
        except Exception as e:
            logger.error(
                f"/stream - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            status_code = 400
            return Response(
                error_stream_generate("Unknown error occurred"),
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
            history = limit_chat_history(
                json.loads(data.get("history", [])), gpt_model=gpt_model
            )
            conversation_id = data.get("conversation_id")
            prompt_id = data.get("prompt_id", "default")
            chunks = int(data.get("chunks", 2))
            token_limit = data.get("token_limit", settings.DEFAULT_MAX_HISTORY)
            retriever_name = data.get("retriever", "classic")
            agent_type = settings.AGENT_NAME

            if "api_key" in data:
                data_key = get_data_from_api_key(data["api_key"])
                chunks = int(data_key.get("chunks", 2))
                prompt_id = data_key.get("prompt_id", "default")
                source = {"active_docs": data_key.get("source")}
                retriever_name = data_key.get("retriever", retriever_name)
                user_api_key = data["api_key"]
                agent_type = data_key.get("agent_type", agent_type)
                decoded_token = {"sub": data_key.get("user")}

            elif "active_docs" in data:
                source = {"active_docs": data["active_docs"]}
                retriever_name = get_retriever(data["active_docs"]) or retriever_name
                user_api_key = None
                decoded_token = request.decoded_token

            else:
                source = {}
                user_api_key = None
                decoded_token = request.decoded_token

            if not decoded_token:
                return make_response({"error": "Unauthorized"}, 401)

            prompt = get_prompt(prompt_id)

            logger.info(
                f"/api/answer - request_data: {data}, source: {source}",
                extra={"data": json.dumps({"request_data": data, "source": source})},
            )

            agent = AgentCreator.create_agent(
                agent_type,
                endpoint="api/answer",
                llm_name=settings.LLM_NAME,
                gpt_model=gpt_model,
                api_key=settings.API_KEY,
                user_api_key=user_api_key,
                prompt=prompt,
                chat_history=history,
                decoded_token=decoded_token,
            )

            retriever = RetrieverCreator.create_retriever(
                retriever_name,
                source=source,
                chat_history=history,
                prompt=prompt,
                chunks=chunks,
                token_limit=token_limit,
                gpt_model=gpt_model,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
            )

            response_full = ""
            source_log_docs = []
            tool_calls = []
            stream_ended = False
            thought = ""

            for line in complete_stream(
                question=question,
                agent=agent,
                retriever=retriever,
                conversation_id=conversation_id,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
                isNoneDoc=data.get("isNoneDoc"),
                index=None,
                should_save_conversation=False,
            ):
                try:
                    event_data = line.replace("data: ", "").strip()
                    event = json.loads(event_data)

                    if event["type"] == "answer":
                        response_full += event["answer"]
                    elif event["type"] == "source":
                        source_log_docs = event["source"]
                    elif event["type"] == "tool_calls":
                        tool_calls = event["tool_calls"]
                    elif event["type"] == "thought":
                        thought = event["thought"]
                    elif event["type"] == "error":
                        logger.error(f"Error from stream: {event['error']}")
                        return bad_request(500, event["error"])
                    elif event["type"] == "end":
                        stream_ended = True

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Error parsing stream event: {e}, line: {line}")
                    continue

            if not stream_ended:
                logger.error("Stream ended unexpectedly without an 'end' event.")
                return bad_request(500, "Stream ended unexpectedly.")

            if data.get("isNoneDoc"):
                for doc in source_log_docs:
                    doc["source"] = "None"

            llm = LLMCreator.create_llm(
                settings.LLM_NAME,
                api_key=settings.API_KEY,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
            )

            result = {"answer": response_full, "sources": source_log_docs}
            result["conversation_id"] = str(
                save_conversation(
                    conversation_id,
                    question,
                    response_full,
                    thought,
                    source_log_docs,
                    tool_calls,
                    llm,
                    decoded_token,
                    api_key=user_api_key,
                )
            )

            retriever_params = retriever.get_params()
            user_logs_collection.insert_one(
                {
                    "action": "api_answer",
                    "level": "info",
                    "user": decoded_token.get("sub"),
                    "api_key": user_api_key,
                    "question": question,
                    "response": response_full,
                    "sources": source_log_docs,
                    "retriever_params": retriever_params,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc),
                }
            )

        except Exception as e:
            logger.error(
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
                decoded_token = {"sub": data_key.get("user")}

            elif "active_docs" in data:
                source = {"active_docs": data["active_docs"]}
                user_api_key = None
                decoded_token = request.decoded_token

            else:
                source = {}
                user_api_key = None
                decoded_token = request.decoded_token

            if not decoded_token:
                return make_response({"error": "Unauthorized"}, 401)

            logger.info(
                f"/api/answer - request_data: {data}, source: {source}",
                extra={"data": json.dumps({"request_data": data, "source": source})},
            )

            retriever = RetrieverCreator.create_retriever(
                retriever_name,
                source=source,
                chat_history=[],
                prompt="default",
                chunks=chunks,
                token_limit=token_limit,
                gpt_model=gpt_model,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
            )

            docs = retriever.search(question)
            retriever_params = retriever.get_params()

            user_logs_collection.insert_one(
                {
                    "action": "api_search",
                    "level": "info",
                    "user": decoded_token.get("sub"),
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
            logger.error(
                f"/api/search - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return bad_request(500, str(e))

        return make_response(docs, 200)


def get_attachments_content(attachment_ids, user):
    """
    Retrieve content from attachment documents based on their IDs.

    Args:
        attachment_ids (list): List of attachment document IDs
        user (str): User identifier to verify ownership

    Returns:
        list: List of dictionaries containing attachment content and metadata
    """
    if not attachment_ids:
        return []

    attachments = []
    for attachment_id in attachment_ids:
        try:
            attachment_doc = attachments_collection.find_one(
                {"_id": ObjectId(attachment_id), "user": user}
            )

            if attachment_doc:
                attachments.append(attachment_doc)
        except Exception as e:
            logger.error(
                f"Error retrieving attachment {attachment_id}: {e}", exc_info=True
            )

    return attachments
