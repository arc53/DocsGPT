import asyncio
import os
from flask import Blueprint, request, Response
import json
import datetime
import logging
import traceback

from pymongo import MongoClient
from bson.objectid import ObjectId
from application.utils import count_tokens



from application.core.settings import settings
from application.vectorstore.vector_creator import VectorCreator
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
answer = Blueprint('answer', __name__)

gpt_model = ""
# to have some kind of default behaviour
if settings.LLM_NAME == "openai":
    gpt_model = 'gpt-3.5-turbo'
elif settings.LLM_NAME == "anthropic":
    gpt_model = 'claude-2'

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
    if data is None:
        return bad_request(401, "Invalid API key")
    return data
    

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
    if conversation_id is not None:
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id)},
            {"$push": {"queries": {"prompt": question, "response": response, "sources": source_log_docs}}},
        )

    else:
        # create new conversation
        # generate summary
        messages_summary = [{"role": "assistant", "content": "Summarise following conversation in no more than 3 "
                                                             "words, respond ONLY with the summary, use the same "
                                                             "language as the system \n\nUser: " + question + "\n\n" +
                                                             "AI: " +
                                                             response},
                            {"role": "user", "content": "Summarise following conversation in no more than 3 words, "
                                                        "respond ONLY with the summary, use the same language as the "
                                                        "system"}]

        completion = llm.gen(model=gpt_model,
                             messages=messages_summary, max_tokens=30)
        conversation_id = conversations_collection.insert_one(
            {"user": "local",
             "date": datetime.datetime.utcnow(),
             "name": completion,
             "queries": [{"prompt": question, "response": response, "sources": source_log_docs}]}
        ).inserted_id

def get_prompt(prompt_id):
    if prompt_id == 'default':
        prompt = chat_combine_template
    elif prompt_id == 'creative':
        prompt = chat_combine_creative
    elif prompt_id == 'strict':
        prompt = chat_combine_strict
    else:
        prompt = prompts_collection.find_one({"_id": ObjectId(prompt_id)})["content"]
    return prompt


def complete_stream(question, retriever, conversation_id):
    
    
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


    llm = LLMCreator.create_llm(settings.LLM_NAME, api_key=settings.API_KEY)
    conversation_id = save_conversation(conversation_id, question, response_full, source_log_docs, llm)

    # send data.type = "end" to indicate that the stream has ended as json
    data = json.dumps({"type": "id", "id": str(conversation_id)})
    yield f"data: {data}\n\n"
    data = json.dumps({"type": "end"})
    yield f"data: {data}\n\n"


@answer.route("/stream", methods=["POST"])
def stream():
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
    if 'prompt_id' in data:
        prompt_id = data["prompt_id"]
    else:
        prompt_id = 'default'
    if 'selectedDocs' in data and data['selectedDocs'] is None:
        chunks = 0
    elif 'chunks' in data:
        chunks = int(data["chunks"])
    else:
        chunks = 2
    
    prompt = get_prompt(prompt_id)

    # check if active_docs is set

    if "api_key" in data:
        data_key = get_data_from_api_key(data["api_key"])
        source = {"active_docs": data_key["source"]}
    elif "active_docs" in data:
        source = {"active_docs": data["active_docs"]}
    else:
        source = {}

    retriever = RetrieverCreator.create_retriever("classic", question=question, 
        source=source, chat_history=history, prompt=prompt, chunks=chunks, gpt_model=gpt_model
        )

    return Response(
        complete_stream(question=question, retriever=retriever,
                        conversation_id=conversation_id), mimetype="text/event-stream")


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
    if 'prompt_id' in data:
        prompt_id = data["prompt_id"]
    else:
        prompt_id = 'default'
    if 'chunks' in data:
        chunks = int(data["chunks"])
    else:
        chunks = 2
    
    prompt = get_prompt(prompt_id)

    # use try and except  to check for exception
    try:
        # check if the vectorstore is set
        if "api_key" in data:
            data_key = get_data_from_api_key(data["api_key"])
            source = {"active_docs": data_key["source"]}
        else:
            source = {data}

        retriever = RetrieverCreator.create_retriever("classic", question=question, 
            source=source, chat_history=history, prompt=prompt, chunks=chunks, gpt_model=gpt_model
            )
        source_log_docs = []
        response_full = ""
        for line in retriever.gen():
            if "source" in line:
                source_log_docs.append(line["source"])
            elif "answer" in line:
                response_full += line["answer"]
            
        llm = LLMCreator.create_llm(settings.LLM_NAME, api_key=settings.API_KEY)
            

        result = {"answer": response_full, "sources": source_log_docs}
        result["conversation_id"] = save_conversation(conversation_id, question, response_full, source_log_docs, llm)

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

    if "api_key" in data:
        data_key = get_data_from_api_key(data["api_key"])
        source = {"active_docs": data_key["source"]}
    elif "active_docs" in data:
        source = {"active_docs": data["active_docs"]}
    else:
        source = {}
    if 'chunks' in data:
        chunks = int(data["chunks"])
    else:
        chunks = 2

    retriever = RetrieverCreator.create_retriever("classic", question=question, 
            source=source, chat_history=[], prompt="default", chunks=chunks, gpt_model=gpt_model
            )
    docs = retriever.search()

    source_log_docs = []
    for doc in docs:
        if doc.metadata:
            source_log_docs.append({"title": doc.metadata['title'].split('/')[-1], "text": doc.page_content})
        else:
            source_log_docs.append({"title": doc.page_content, "text": doc.page_content})
    return source_log_docs

