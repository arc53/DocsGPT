import os
from flask import Blueprint, request, jsonify, Response
import requests
import json
import datetime

from langchain.chat_models import AzureChatOpenAI
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
import http.client

from application.app import (logger, count_tokens, chat_combine_template, gpt_model,
                             api_key_set, embeddings_key_set, get_docsearch, get_vectorstore)
from application.core.settings import settings
from application.llm.openai import OpenAILLM


mongo = MongoClient(settings.MONGO_URI)
db = mongo["docsgpt"]
conversations_collection = db["conversations"]
vectors_collection = db["vectors"]
answer = Blueprint('answer', __name__)

def is_azure_configured():
    return settings.OPENAI_API_BASE and settings.OPENAI_API_VERSION and settings.AZURE_DEPLOYMENT_NAME
def complete_stream(question, docsearch, chat_history, api_key, conversation_id):

    # openai.api_key = api_key

    if is_azure_configured():
        # logger.debug("in Azure")
        # openai.api_type = "azure"
        # openai.api_version = settings.OPENAI_API_VERSION
        # openai.api_base = settings.OPENAI_API_BASE
        # llm = AzureChatOpenAI(
        #     openai_api_key=api_key,
        #     openai_api_base=settings.OPENAI_API_BASE,
        #     openai_api_version=settings.OPENAI_API_VERSION,
        #     deployment_name=settings.AZURE_DEPLOYMENT_NAME,
        # )
        llm = OpenAILLM(api_key=api_key)
    else:
        logger.debug("plain OpenAI")
        llm = OpenAILLM(api_key=api_key)
        # llm = ChatOpenAI(openai_api_key=api_key)
    docs = docsearch.similarity_search(question, k=2)
    # join all page_content together with a newline
    docs_together = "\n".join([doc.page_content for doc in docs])
    p_chat_combine = chat_combine_template.replace("{summaries}", docs_together)
    messages_combine = [{"role": "system", "content": p_chat_combine}]
    source_log_docs = []
    for doc in docs:
        if doc.metadata:
            data = json.dumps({"type": "source", "doc": doc.page_content, "metadata": doc.metadata})
            source_log_docs.append({"title": doc.metadata['title'].split('/')[-1], "text": doc.page_content})
        else:
            data = json.dumps({"type": "source", "doc": doc.page_content})
            source_log_docs.append({"title": doc.page_content, "text": doc.page_content})
        yield f"data:{data}\n\n"

    if len(chat_history) > 1:
        tokens_current_history = 0
        # count tokens in history
        chat_history.reverse()
        for i in chat_history:
            if "prompt" in i and "response" in i:
                tokens_batch = count_tokens(i["prompt"]) + count_tokens(i["response"])
                if tokens_current_history + tokens_batch < settings.TOKENS_MAX_HISTORY:
                    tokens_current_history += tokens_batch
                    messages_combine.append({"role": "user", "content": i["prompt"]})
                    messages_combine.append({"role": "system", "content": i["response"]})
    messages_combine.append({"role": "user", "content": question})
    # completion = openai.ChatCompletion.create(model=gpt_model, engine=settings.AZURE_DEPLOYMENT_NAME,
    #                                           messages=messages_combine, stream=True, max_tokens=500, temperature=0)
    import sys
    print(api_key)
    reponse_full = ""
    # for line in completion:
    #     if "content" in line["choices"][0]["delta"]:
    #         # check if the delta contains content
    #         data = json.dumps({"answer": str(line["choices"][0]["delta"]["content"])})
    #         reponse_full += str(line["choices"][0]["delta"]["content"])
    #         yield f"data: {data}\n\n"
    # reponse_full = ""
    print(llm)
    completion = llm.gen_stream(model=gpt_model, engine=settings.AZURE_DEPLOYMENT_NAME,
                   messages=messages_combine)
    for line in completion:

        data = json.dumps({"answer": str(line)})
        reponse_full += str(line)
        yield f"data: {data}\n\n"


    # save conversation to database
    if conversation_id is not None:
        conversations_collection.update_one(
            {"_id": ObjectId(conversation_id)},
            {"$push": {"queries": {"prompt": question, "response": reponse_full, "sources": source_log_docs}}},
        )

    else:
        # create new conversation
        # generate summary
        messages_summary = [{"role": "assistant", "content": "Summarise following conversation in no more than 3 "
                                                             "words, respond ONLY with the summary, use the same "
                                                             "language as the system \n\nUser: " + question + "\n\n" +
                                                             "AI: " +
                                                             reponse_full},
                            {"role": "user", "content": "Summarise following conversation in no more than 3 words, "
                                                        "respond ONLY with the summary, use the same language as the "
                                                        "system"}]
        # completion = openai.ChatCompletion.create(model='gpt-3.5-turbo', engine=settings.AZURE_DEPLOYMENT_NAME,
        #                                           messages=messages_summary, max_tokens=30, temperature=0)
        completion = llm.gen(model=gpt_model, engine=settings.AZURE_DEPLOYMENT_NAME,
                                    messages=messages_combine, max_tokens=30)
        conversation_id = conversations_collection.insert_one(
            {"user": "local",
             "date": datetime.datetime.utcnow(),
             "name": completion["choices"][0]["message"]["content"],
             "queries": [{"prompt": question, "response": reponse_full, "sources": source_log_docs}]}
        ).inserted_id

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
    history = data["history"]
    # history to json object from string
    history = json.loads(history)
    conversation_id = data["conversation_id"]

    # check if active_docs is set

    if not api_key_set:
        api_key = data["api_key"]
    else:
        api_key = settings.API_KEY
    if not embeddings_key_set:
        embeddings_key = data["embeddings_key"]
    else:
        embeddings_key = settings.EMBEDDINGS_KEY
    if "active_docs" in data:
        vectorstore = get_vectorstore({"active_docs": data["active_docs"]})
    else:
        vectorstore = ""
    docsearch = get_docsearch(vectorstore, embeddings_key)

    # question = "Hi"
    return Response(
        complete_stream(question, docsearch,
                        chat_history=history, api_key=api_key,
                        conversation_id=conversation_id), mimetype="text/event-stream"
    )