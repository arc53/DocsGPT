import asyncio
import datetime
import json
import logging
import os
import platform
import traceback

import dotenv
import openai
import requests
from celery import Celery
from celery.result import AsyncResult
from flask import Flask, request, send_from_directory, jsonify, Response, redirect
from langchain import FAISS
from langchain import VectorDBQA, Cohere, OpenAI
from langchain.chains import LLMChain, ConversationalRetrievalChain
from langchain.chains.conversational_retrieval.prompts import CONDENSE_QUESTION_PROMPT
from langchain.chains.question_answering import load_qa_chain
from langchain.chat_models import ChatOpenAI, AzureChatOpenAI
from langchain.embeddings import (
    OpenAIEmbeddings,
    HuggingFaceHubEmbeddings,
    CohereEmbeddings,
    HuggingFaceInstructEmbeddings,
)
from langchain.prompts import PromptTemplate
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    AIMessagePromptTemplate,
)
from langchain.schema import HumanMessage, AIMessage
from pymongo import MongoClient
from werkzeug.utils import secure_filename

from application.core.settings import settings
from application.error import bad_request
from application.worker import ingest_worker
from bson.objectid import ObjectId
from application.api.user.routes import user
from application.api.answer.routes import answer
from transformers import GPT2TokenizerFast

# os.environ["LANGCHAIN_HANDLER"] = "langchain"

logger = logging.getLogger(__name__)
if settings.LLM_NAME == "gpt4":
    gpt_model = 'gpt-4'
else:
    gpt_model = 'gpt-3.5-turbo'

if settings.SELF_HOSTED_MODEL:
    from langchain.llms import HuggingFacePipeline
    from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

    model_id = settings.LLM_NAME  # hf model id (Arc53/docsgpt-7b-falcon, Arc53/docsgpt-14b)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id)
    pipe = pipeline(
        "text-generation", model=model,
        tokenizer=tokenizer, max_new_tokens=2000,
        device_map="auto", eos_token_id=tokenizer.eos_token_id
    )
    hf = HuggingFacePipeline(pipeline=pipe)

# Redirect PosixPath to WindowsPath on Windows

if platform.system() == "Windows":
    import pathlib

    temp = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath

# loading the .env file
dotenv.load_dotenv()

# load the prompts
current_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(current_dir, "prompts", "combine_prompt.txt"), "r") as f:
    template = f.read()

with open(os.path.join(current_dir, "prompts", "combine_prompt_hist.txt"), "r") as f:
    template_hist = f.read()

with open(os.path.join(current_dir, "prompts", "question_prompt.txt"), "r") as f:
    template_quest = f.read()

with open(os.path.join(current_dir, "prompts", "chat_combine_prompt.txt"), "r") as f:
    chat_combine_template = f.read()

with open(os.path.join(current_dir, "prompts", "chat_reduce_prompt.txt"), "r") as f:
    chat_reduce_template = f.read()

api_key_set = settings.API_KEY is not None
embeddings_key_set = settings.EMBEDDINGS_KEY is not None

app = Flask(__name__)
app.register_blueprint(user)
app.register_blueprint(answer)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER = "inputs"
app.config["CELERY_BROKER_URL"] = settings.CELERY_BROKER_URL
app.config["CELERY_RESULT_BACKEND"] = settings.CELERY_RESULT_BACKEND
app.config["MONGO_URI"] = settings.MONGO_URI
celery = Celery()
celery.config_from_object("application.celeryconfig")
mongo = MongoClient(app.config["MONGO_URI"])
db = mongo["docsgpt"]
vectors_collection = db["vectors"]
conversations_collection = db["conversations"]


async def async_generate(chain, question, chat_history):
    result = await chain.arun({"question": question, "chat_history": chat_history})
    return result

def count_tokens(string):

    tokenizer = GPT2TokenizerFast.from_pretrained('gpt2')
    return len(tokenizer(string)['input_ids'])

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


def get_vectorstore(data):
    if "active_docs" in data:
        if data["active_docs"].split("/")[0] == "local":
            if data["active_docs"].split("/")[1] == "default":
                vectorstore = ""
            else:
                vectorstore = "indexes/" + data["active_docs"]
        else:
            vectorstore = "vectors/" + data["active_docs"]
        if data["active_docs"] == "default":
            vectorstore = ""
    else:
        vectorstore = ""
    vectorstore = os.path.join("application", vectorstore)
    return vectorstore


def get_docsearch(vectorstore, embeddings_key):
    if settings.EMBEDDINGS_NAME == "openai_text-embedding-ada-002":
        if is_azure_configured():
            os.environ["OPENAI_API_TYPE"] = "azure"
            openai_embeddings = OpenAIEmbeddings(model=settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME)
        else:
            openai_embeddings = OpenAIEmbeddings(openai_api_key=embeddings_key)
        docsearch = FAISS.load_local(vectorstore, openai_embeddings)
    elif settings.EMBEDDINGS_NAME == "huggingface_sentence-transformers/all-mpnet-base-v2":
        docsearch = FAISS.load_local(vectorstore, HuggingFaceHubEmbeddings())
    elif settings.EMBEDDINGS_NAME == "huggingface_hkunlp/instructor-large":
        docsearch = FAISS.load_local(vectorstore, HuggingFaceInstructEmbeddings())
    elif settings.EMBEDDINGS_NAME == "cohere_medium":
        docsearch = FAISS.load_local(vectorstore, CohereEmbeddings(cohere_api_key=embeddings_key))
    return docsearch


@celery.task(bind=True)
def ingest(self, directory, formats, name_job, filename, user):
    resp = ingest_worker(self, directory, formats, name_job, filename, user)
    return resp


@app.route("/")
def home():
    """
    The frontend source code lives in the /frontend directory of the repository.
    """
    if request.remote_addr in ('0.0.0.0', '127.0.0.1', 'localhost', '172.18.0.1'):
        # If users locally try to access DocsGPT running in Docker,
        # they will be redirected to the Frontend application.
        return redirect('http://localhost:5173')
    else:
        # Handle other cases or render the default page
        return 'Welcome to DocsGPT Backend!'




def is_azure_configured():
    return settings.OPENAI_API_BASE and settings.OPENAI_API_VERSION and settings.AZURE_DEPLOYMENT_NAME


@app.route("/api/answer", methods=["POST"])
def api_answer():
    data = request.get_json()
    question = data["question"]
    history = data["history"]
    if "conversation_id" not in data:
        conversation_id = None
    else:
        conversation_id = data["conversation_id"]
    print("-" * 5)
    if not api_key_set:
        api_key = data["api_key"]
    else:
        api_key = settings.API_KEY
    if not embeddings_key_set:
        embeddings_key = data["embeddings_key"]
    else:
        embeddings_key = settings.EMBEDDINGS_KEY

    # use try and except  to check for exception
    try:
        # check if the vectorstore is set
        vectorstore = get_vectorstore(data)
        # loading the index and the store and the prompt template
        # Note if you have used other embeddings than OpenAI, you need to change the embeddings
        docsearch = get_docsearch(vectorstore, embeddings_key)

        q_prompt = PromptTemplate(
            input_variables=["context", "question"], template=template_quest, template_format="jinja2"
        )
        if settings.LLM_NAME == "openai_chat":
            if is_azure_configured():
                logger.debug("in Azure")
                llm = AzureChatOpenAI(
                    openai_api_key=api_key,
                    openai_api_base=settings.OPENAI_API_BASE,
                    openai_api_version=settings.OPENAI_API_VERSION,
                    deployment_name=settings.AZURE_DEPLOYMENT_NAME,
                )
            else:
                logger.debug("plain OpenAI")
                llm = ChatOpenAI(openai_api_key=api_key, model_name=gpt_model)  # optional parameter: model_name="gpt-4"
            messages_combine = [SystemMessagePromptTemplate.from_template(chat_combine_template)]
            if history:
                tokens_current_history = 0
                # count tokens in history
                history.reverse()
                for i in history:
                    if "prompt" in i and "response" in i:
                        tokens_batch = count_tokens(i["prompt"]) + count_tokens(i["response"])
                        if tokens_current_history + tokens_batch < settings.TOKENS_MAX_HISTORY:
                            tokens_current_history += tokens_batch
                            messages_combine.append(HumanMessagePromptTemplate.from_template(i["prompt"]))
                            messages_combine.append(AIMessagePromptTemplate.from_template(i["response"]))
            messages_combine.append(HumanMessagePromptTemplate.from_template("{question}"))
            p_chat_combine = ChatPromptTemplate.from_messages(messages_combine)
        elif settings.LLM_NAME == "openai":
            llm = OpenAI(openai_api_key=api_key, temperature=0)
        elif settings.SELF_HOSTED_MODEL:
            llm = hf
        elif settings.LLM_NAME == "cohere":
            llm = Cohere(model="command-xlarge-nightly", cohere_api_key=api_key)
        else:
            raise ValueError("unknown LLM model")

        if settings.LLM_NAME == "openai_chat":
            question_generator = LLMChain(llm=llm, prompt=CONDENSE_QUESTION_PROMPT)
            doc_chain = load_qa_chain(llm, chain_type="map_reduce", combine_prompt=p_chat_combine)
            chain = ConversationalRetrievalChain(
                retriever=docsearch.as_retriever(k=2),
                question_generator=question_generator,
                combine_docs_chain=doc_chain,
            )
            chat_history = []
            # result = chain({"question": question, "chat_history": chat_history})
            # generate async with async generate method
            result = run_async_chain(chain, question, chat_history)
        elif settings.SELF_HOSTED_MODEL:
            question_generator = LLMChain(llm=llm, prompt=CONDENSE_QUESTION_PROMPT)
            doc_chain = load_qa_chain(llm, chain_type="map_reduce", combine_prompt=p_chat_combine)
            chain = ConversationalRetrievalChain(
                retriever=docsearch.as_retriever(k=2),
                question_generator=question_generator,
                combine_docs_chain=doc_chain,
            )
            chat_history = []
            # result = chain({"question": question, "chat_history": chat_history})
            # generate async with async generate method
            result = run_async_chain(chain, question, chat_history)

        else:
            qa_chain = load_qa_chain(
                llm=llm, chain_type="map_reduce", combine_prompt=chat_combine_template, question_prompt=q_prompt
            )
            chain = VectorDBQA(combine_documents_chain=qa_chain, vectorstore=docsearch, k=3)
            result = chain({"query": question})

        print(result)

        # some formatting for the frontend
        if "result" in result:
            result["answer"] = result["result"]
        result["answer"] = result["answer"].replace("\\n", "\n")
        try:
            result["answer"] = result["answer"].split("SOURCES:")[0]
        except Exception:
            pass

        sources = docsearch.similarity_search(question, k=2)
        sources_doc = []
        for doc in sources:
            if doc.metadata:
                sources_doc.append({'title': doc.metadata['title'], 'text': doc.page_content})
            else:
                sources_doc.append({'title': doc.page_content, 'text': doc.page_content})
        result['sources'] = sources_doc

        # generate conversationId
        if conversation_id is not None:
            conversations_collection.update_one(
                {"_id": ObjectId(conversation_id)},
                {"$push": {"queries": {"prompt": question,
                                       "response": result["answer"], "sources": result['sources']}}},
            )

        else:
            # create new conversation
            # generate summary
            messages_summary = [AIMessage(content="Summarise following conversation in no more than 3 " +
                                                  "words, respond ONLY with the summary, use the same " +
                                                  "language as the system \n\nUser: " + question + "\n\nAI: " +
                                                  result["answer"]),
                                HumanMessage(content="Summarise following conversation in no more than 3 words, " +
                                                     "respond ONLY with the summary, use the same language as the " +
                                                     "system")]

            # completion = openai.ChatCompletion.create(model='gpt-3.5-turbo', engine=settings.AZURE_DEPLOYMENT_NAME,
            #                                           messages=messages_summary, max_tokens=30, temperature=0)
            completion = llm.predict_messages(messages_summary)
            conversation_id = conversations_collection.insert_one(
                {"user": "local",
                 "date": datetime.datetime.utcnow(),
                 "name": completion.content,
                 "queries": [{"prompt": question, "response": result["answer"], "sources": result['sources']}]}
            ).inserted_id

        result["conversation_id"] = str(conversation_id)

        # mock result
        # result = {
        #     "answer": "The answer is 42",
        #     "sources": ["https://en.wikipedia.org/wiki/42_(number)", "https://en.wikipedia.org/wiki/42_(number)"]
        # }
        return result
    except Exception as e:
        # print whole traceback
        traceback.print_exc()
        print(str(e))
        return bad_request(500, str(e))


# handling CORS
@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    # response.headers.add("Access-Control-Allow-Credentials", "true")
    return response


if __name__ == "__main__":
    app.run(debug=True, port=7091)
