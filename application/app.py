import datetime
import json
import os
import traceback
import asyncio

import dotenv
import requests
import datetime
from gridfs import GridFS
from celery import Celery
from celery.result import AsyncResult
from flask import Flask, request, render_template, send_from_directory, jsonify
from langchain import FAISS
from langchain import VectorDBQA, HuggingFaceHub, Cohere, OpenAI
from langchain.chains import LLMChain, ConversationalRetrievalChain
from langchain.chains.conversational_retrieval.prompts import CONDENSE_QUESTION_PROMPT
from langchain.chains.question_answering import load_qa_chain
from langchain.chains.qa_with_sources import load_qa_with_sources_chain
from langchain.chat_models import ChatOpenAI
from langchain.embeddings import OpenAIEmbeddings, HuggingFaceHubEmbeddings, CohereEmbeddings, \
    HuggingFaceInstructEmbeddings
from langchain.prompts import PromptTemplate
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from pymongo import MongoClient
from werkzeug.utils import secure_filename

from error import bad_request
from worker import ingest_worker
import celeryconfig

# os.environ["LANGCHAIN_HANDLER"] = "langchain"

if os.getenv("LLM_NAME") is not None:
    llm_choice = os.getenv("LLM_NAME")
else:
    llm_choice = "openai_chat"

if os.getenv("EMBEDDINGS_NAME") is not None:
    embeddings_choice = os.getenv("EMBEDDINGS_NAME")
else:
    embeddings_choice = "openai_text-embedding-ada-002"

if llm_choice == "manifest":
    from manifest import Manifest
    from langchain.llms.manifest import ManifestWrapper

    manifest = Manifest(
        client_name="huggingface",
        client_connection="http://127.0.0.1:5000"
    )

# Redirect PosixPath to WindowsPath on Windows
import platform

if platform.system() == "Windows":
    import pathlib

    temp = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath

# loading the .env file
dotenv.load_dotenv()

# load the prompts
with open("prompts/combine_prompt.txt", "r") as f:
    template = f.read()

with open("prompts/combine_prompt_hist.txt", "r") as f:
    template_hist = f.read()

with open("prompts/question_prompt.txt", "r") as f:
    template_quest = f.read()

with open("prompts/chat_combine_prompt.txt", "r") as f:
    chat_combine_template = f.read()

with open("prompts/chat_reduce_prompt.txt", "r") as f:
    chat_reduce_template = f.read()

if os.getenv("API_KEY") is not None:
    api_key_set = True
else:
    api_key_set = False
if os.getenv("EMBEDDINGS_KEY") is not None:
    embeddings_key_set = True
else:
    embeddings_key_set = False

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER = "inputs"
app.config['CELERY_BROKER_URL'] = os.getenv("CELERY_BROKER_URL")
app.config['CELERY_RESULT_BACKEND'] = os.getenv("CELERY_RESULT_BACKEND")
app.config['MONGO_URI'] = os.getenv("MONGO_URI")
celery = Celery()
celery.config_from_object('celeryconfig')
mongo = MongoClient(app.config['MONGO_URI'])
db = mongo["docgen"]
vectors_collection = db["vectors"]
users = db['users']
fs = GridFS(db)


def async_generate(chain, question, chat_history):
    result = chain({"question": question, "chat_history": chat_history})
    return result


def run_async_chain(chain, question, chat_history):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = {}
    try:
        answer = loop.run_until_complete(
            async_generate(chain, question, chat_history))
    finally:
        loop.close()
    result["answer"] = answer
    return result


def extract_metadata(metadata):
    result = {}
    path, filename = os.path.split(metadata['source'])
    print('after split')
    print(path)
    # Remove the first two path elements
    new_path = os.path.join(*path.split(os.path.sep)[2:])
    new_path = os.path.join(new_path, filename)
    print(new_path)
    # Add the metadata to the result list
    result['source'] = new_path
    result['title'] = metadata['title']
    return result


@celery.task(bind=True, name="app.ingest")
def ingest(self, directory, formats, name_job, filename, user):
    resp = ingest_worker(self, directory, formats, name_job, filename, user)
    return resp


@app.route("/")
def home():
    return render_template("index.html", api_key_set=api_key_set, llm_choice=llm_choice,
                           embeddings_choice=embeddings_choice)


@app.route("/api/answer", methods=["POST"])
def api_answer():
    # Sample data, use it for testing
    data = {
        "answer": "To change the oil in your car, follow these steps:\n\n1. Remove the old oil filter.\n2. Drain the old oil.\n3. Install a new oil filter and gasket.\n4. Add new oil to the engine.\n\nHere's a breakdown of each step:\n\n1. Locate the oil filter and use an oil filter wrench to remove it. Be sure to have a basin or container beneath the filter to catch any oil that may spill out.\n\n2. Locate the drain plug on the oil pan beneath your car. Place a container large enough to hold all of the old oil beneath the drain plug. Remove the drain plug and let the oil drain completely.\n\n3. Install a new oil filter using the recommended torque specifications. Be sure to use a new gasket as well.\n\n4. Add new oil to the engine using a funnel and the specified amount of oil recommended by the manufacturer. Double check the oil level with the dipstick.\n\nRemember to consult your car's owner's manual for specific instructions and recommendations, including the type of oil to use. Also, keep in mind that motor oil should be changed every 6000 kilometers.",
        "sources": [
            {
                "source": "ditawithdirectory.zip\\tasks\\changingtheoil.html",
                "title": "Changing the oil in your car"
            },
            {
                "source": "ditawithdirectory.zip\\tasks\\changingtheoil.html",
                "title": "Changing the oil in your car"
            },
            {
                "source": "ditawithdirectory.zip\\concepts\\oil.html",
                "title": "Oil"
            },
            {
                "source": "ditawithdirectory.zip\\concepts\\oil.html",
                "title": "Oil"
            }
        ]
    }

    json_data = json.dumps(data)

    return (json_data)
    data = request.get_json()
    question = data["question"]
    history = data["history"]
    print('-' * 5)
    if not api_key_set:
        api_key = data["api_key"]
    else:
        api_key = os.getenv("API_KEY")
    if not embeddings_key_set:
        embeddings_key = data["embeddings_key"]
    else:
        embeddings_key = os.getenv("EMBEDDINGS_KEY")

    # use try and except  to check for exception
    try:
        # check if the vectorstore is set
        if "active_docs" in data:
            if data["active_docs"].split("/")[0] == "local":
                if data["active_docs"].split("/")[1] == "default":
                    vectorstore = ""
                else:
                    vectorstore = "indexes/" + data["active_docs"]
            else:
                vectorstore = "vectors/" + data["active_docs"]
            if data['active_docs'] == "default":
                vectorstore = ""
        else:
            vectorstore = ""
        print('vector store is' + vectorstore)
        # vectorstore = "outputs/inputs/"
        # loading the index and the store and the prompt template
        # Note if you have used other embeddings than OpenAI, you need to change the embeddings
        if embeddings_choice == "openai_text-embedding-ada-002":
            docsearch = FAISS.load_local(
                vectorstore, OpenAIEmbeddings(openai_api_key=embeddings_key))
        elif embeddings_choice == "huggingface_sentence-transformers/all-mpnet-base-v2":
            docsearch = FAISS.load_local(
                vectorstore, HuggingFaceHubEmbeddings())
        elif embeddings_choice == "huggingface_hkunlp/instructor-large":
            docsearch = FAISS.load_local(
                vectorstore, HuggingFaceInstructEmbeddings())
        elif embeddings_choice == "cohere_medium":
            docsearch = FAISS.load_local(
                vectorstore, CohereEmbeddings(cohere_api_key=embeddings_key))

        # create a prompt template
        if history:
            history = json.loads(history)
            template_temp = template_hist.replace("{historyquestion}", history[0]).replace("{historyanswer}",
                                                                                           history[1])
            c_prompt = PromptTemplate(input_variables=["summaries", "question"], template=template_temp,
                                      template_format="jinja2")
        else:
            c_prompt = PromptTemplate(input_variables=["summaries", "question"], template=template,
                                      template_format="jinja2")

        q_prompt = PromptTemplate(input_variables=["context", "question"], template=template_quest,
                                  template_format="jinja2")
        if llm_choice == "openai_chat":
            # llm = ChatOpenAI(openai_api_key=api_key, model_name="gpt-4")
            llm = ChatOpenAI(openai_api_key=api_key)
            messages_combine = [
                SystemMessagePromptTemplate.from_template(
                    chat_combine_template),
                HumanMessagePromptTemplate.from_template("{question}")
            ]
            p_chat_combine = ChatPromptTemplate.from_messages(messages_combine)
            messages_reduce = [
                SystemMessagePromptTemplate.from_template(
                    chat_reduce_template),
                HumanMessagePromptTemplate.from_template("{question}")
            ]
            p_chat_reduce = ChatPromptTemplate.from_messages(messages_reduce)
        elif llm_choice == "openai":
            llm = OpenAI(openai_api_key=api_key, temperature=0)
        elif llm_choice == "manifest":
            llm = ManifestWrapper(client=manifest, llm_kwargs={
                                  "temperature": 0.001, "max_tokens": 2048})
        elif llm_choice == "huggingface":
            llm = HuggingFaceHub(repo_id="bigscience/bloom",
                                 huggingfacehub_api_token=api_key)
        elif llm_choice == "cohere":
            llm = Cohere(model="command-xlarge-nightly",
                         cohere_api_key=api_key)

        if llm_choice == "openai_chat":
            question_generator = LLMChain(
                llm=llm, prompt=CONDENSE_QUESTION_PROMPT)
            doc_chain = load_qa_with_sources_chain(
                llm, chain_type="map_reduce", combine_prompt=p_chat_combine)
            chain = ConversationalRetrievalChain(
                retriever=docsearch.as_retriever(k=2),
                question_generator=question_generator,
                combine_docs_chain=doc_chain,
                return_source_documents=True
            )
            chat_history = []
            # result = chain({"question": question, "chat_history": chat_history})
            # generate async with async generate method
            result = async_generate(chain, question, chat_history)
        else:
            qa_chain = load_qa_with_sources_chain(llm=llm, chain_type="map_reduce",
                                                  combine_prompt=c_prompt, question_prompt=q_prompt)
            chain = VectorDBQA(combine_documents_chain=qa_chain,
                               vectorstore=docsearch, k=3)
            result = chain({"query": question})

        print(result)

        # some formatting for the frontend
        # if "result" in result:
        #     result['answer'] = result['result']
        # result['answer'] = result['answer'].replace("\\n", "\n")
        # try:
        #     result['answer'] = result['answer'].split("SOURCES:")[0]
        # except:
        #     pass

        # mock result
        # result = {
        #     "answer": "The answer is 42",
        #     "sources": ["https://en.wikipedia.org/wiki/42_(number)", "https://en.wikipedia.org/wiki/42_(number)"]
        # }

        print('test')
        sources = []
        if result['source_documents']:
            print(result['source_documents'])
            for doc in result['source_documents']:
                metadata = extract_metadata(doc.metadata)
                sources.append(metadata)
                print('metadata')
                print(metadata)
            return jsonify(
                answer=result['answer'],
                sources=sources,
            )

        return jsonify(
            answer=result['answer']
        )

    except Exception as e:
        # print whole traceback
        traceback.print_exc()
        print(str(e))
        return bad_request(500, str(e))


@app.route("/api/docs_check", methods=["POST"])
def check_docs():
    # check if docs exist in a vectorstore folder
    data = request.get_json()
    # split docs on / and take first part
    if data["docs"].split("/")[0] == "local":
        return {"status": 'exists'}
    vectorstore = "vectors/" + data["docs"]
    base_path = 'https://raw.githubusercontent.com/arc53/DocsHUB/main/'
    if os.path.exists(vectorstore) or data["docs"] == "default":
        return {"status": 'exists'}
    else:
        r = requests.get(base_path + vectorstore + "index.faiss")

        if r.status_code != 200:
            return {"status": 'null'}
        else:
            if not os.path.exists(vectorstore):
                os.makedirs(vectorstore)
            with open(vectorstore + "index.faiss", "wb") as f:
                f.write(r.content)

            # download the store
            r = requests.get(base_path + vectorstore + "index.pkl")
            with open(vectorstore + "index.pkl", "wb") as f:
                f.write(r.content)

        return {"status": 'loaded'}


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json()
    question = data["question"]
    answer = data["answer"]
    feedback = data["feedback"]

    print('-' * 5)
    print("Question: " + question)
    print("Answer: " + answer)
    print("Feedback: " + feedback)
    print('-' * 5)
    response = requests.post(
        url="https://86x89umx77.execute-api.eu-west-2.amazonaws.com/docsgpt-feedback",
        headers={
            "Content-Type": "application/json; charset=utf-8",
        },
        data=json.dumps({
            "answer": answer,
            "question": question,
            "feedback": feedback
        })
    )
    return {"status": 'ok'}


@app.route('/api/combine', methods=['GET'])
def combined_json():
    user = 'local'
    """Provide json file with combined available indexes."""
    # get json from https://d3dg1063dc54p9.cloudfront.net/combined.json

    data = [{
        "name": 'default',
        "language": 'default',
        "version": '',
        "description": 'default',
        "fullName": 'default',
        "date": 'default',
        "docLink": 'default',
        "model": embeddings_choice,
        "location": "local"
    }]
    # structure: name, language, version, description, fullName, date, docLink
    # append data from vectors_collection
    for index in vectors_collection.find({'user': user}):
        data.append({
            "name": index['name'],
            "language": index['language'],
            "version": '',
            "description": index['name'],
            "fullName": index['name'],
            "date": index['date'],
            "docLink": index['location'],
            "model": embeddings_choice,
            "location": "local"
        })

    data_remote = requests.get(
        "https://d3dg1063dc54p9.cloudfront.net/combined.json").json()
    for index in data_remote:
        index['location'] = "remote"
        data.append(index)

    return jsonify(data)


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload a file to get vectorized and indexed."""
    if 'user' not in request.form:
        return {"status": 'no user'}
    user = secure_filename(request.form['user'])
    if 'name' not in request.form:
        return {"status": 'no name'}
    job_name = secure_filename(request.form['name'])
    # check if the post request has the file part
    if 'file' not in request.files:
        print('No file part')
        return {"status": 'no file'}
    file = request.files['file']
    if file.filename == '':
        return {"status": 'no file name'}

    date = datetime.datetime.now()
    file_id = fs.put(file, file_name=file.filename, user_id=user, date=date)

    if file:
        filename = secure_filename(file.filename)
        # save dir
        save_dir = os.path.join(app.config['UPLOAD_FOLDER'], user, job_name)
        # create dir if not exists
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        file.seek(0)
        file.save(os.path.join(save_dir, filename))
        print("Size of file is :", file.tell(), "bytes")
        print('save the file into: ' + os.path.join(save_dir, filename))
        task = ingest.delay(
            'temp', [".rst", ".md", ".pdf", ".html"], job_name, filename, user)
        # task id
        task_id = task.id
        return {"status": 'ok', "task_id": task_id}
    else:
        return {"status": 'error'}


@app.route('/api/get_docs', methods=['POST'])
def serve_html():
    print(request.json)
    user = secure_filename(request.json['user'])
    rawPath = os.path.normpath(request.json['path'])
    path, filename = os.path.split(rawPath)
    print(user)
    print(app.config['UPLOAD_FOLDER'])
    print(path)
    print(filename)
    save_dir = os.path.join(app.config['UPLOAD_FOLDER'], user, path)
    print(save_dir)
    return send_from_directory(save_dir, filename)


@app.route('/api/get_index', methods=['POST'])
def serve_index():
    user = secure_filename(request.json['user'])
    data = [
        {
            "title": "Working in the garage",
            "navigation_links": [
                {
                    "text": "Garage Tasks",
                    "url": "tasks/garagetaskoverview.html",
                    "sub_links": [
                        {
                            "text": "Changing the oil in your car",
                            "url": "tasks/changingtheoil.html"
                        },
                        {
                            "text": "Organizing the workbench and tools",
                            "url": "tasks/organizing.html"
                        },
                        {
                            "text": "Shovelling snow",
                            "url": "tasks/shovellingsnow.html"
                        },
                        {
                            "text": "Spray painting",
                            "url": "tasks/spraypainting.html"
                        },
                        {
                            "text": "Taking out the garbage",
                            "url": "tasks/takinggarbage.html"
                        },
                        {
                            "text": "Washing the car",
                            "url": "tasks/washingthecar.html"
                        }
                    ]
                },
                {
                    "text": "Garage Concepts",
                    "url": "concepts/garageconceptsoverview.html",
                    "sub_links": [
                        {
                            "text": "Lawnmower",
                            "url": "concepts/lawnmower.html"
                        },
                        {
                            "text": "Oil",
                            "url": "concepts/oil.html"
                        },
                        {
                            "text": "Paint",
                            "url": "concepts/paint.html"
                        },
                        {
                            "text": "Shelving",
                            "url": "concepts/shelving.html"
                        },
                        {
                            "text": "Snow shovel",
                            "url": "concepts/snowshovel.html"
                        },
                        {
                            "text": "Tool box",
                            "url": "concepts/toolbox.html"
                        },
                        {
                            "text": "Tools",
                            "url": "concepts/tools.html"
                        },
                        {
                            "text": "Water hose",
                            "url": "concepts/waterhose.html"
                        },
                        {
                            "text": "Wheel barrow",
                            "url": "concepts/wheelbarrow.html"
                        },
                        {
                            "text": "Workbench",
                            "url": "concepts/workbench.html"
                        },
                        {
                            "text": "Windshield washer fluid",
                            "url": "concepts/wwfluid.html"
                        }
                    ]
                }
            ]
        }

    ]

    json_data = json.dumps(data)
    return json_data


@app.route('/api/register', methods=['POST'])
def register():
    username = request.json['username']
    password = request.json['password']

    user = users.find_one({'username': username})

    if user:
        return {'status': 'user already exists'}
    else:
        user = users.insert_one({'username': username, 'password': password})

    return {'status': 'ok'}


@app.route('/api/login', methods=['POST'])
def login():
    username = request.json['username']
    password = request.json['password']
    user = users.find_one({'username': username})
    print(user)
    if not user:
        return {"status": 'no user name'}
    if password != user['password']:
        return {'status': 'password incorrect'}

    return {'status': 'ok'}


@app.route('/api/task_status', methods=['GET'])
def task_status():
    """Get celery job status."""
    task_id = request.args.get('task_id')
    task = AsyncResult(task_id)
    task_meta = task.info
    return {"status": task.status, "result": task_meta}


# Backgound task api
@app.route('/api/upload_index', methods=['POST'])
def upload_index_files():
    """Upload two files(index.faiss, index.pkl) to the user's folder."""
    if 'user' not in request.form:
        return {"status": 'no user'}
    user = secure_filename(request.form['user'])
    if 'name' not in request.form:
        return {"status": 'no name'}
    job_name = secure_filename(request.form['name'])
    if 'file_faiss' not in request.files:
        print('No file part')
        return {"status": 'no file'}
    file_faiss = request.files['file_faiss']
    if file_faiss.filename == '':
        return {"status": 'no file name'}
    if 'file_pkl' not in request.files:
        print('No file part')
        return {"status": 'no file'}
    file_pkl = request.files['file_pkl']
    if file_pkl.filename == '':
        return {"status": 'no file name'}

    # saves index files
    save_dir = os.path.join('indexes', user, job_name)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    file_faiss.save(os.path.join(save_dir, 'index.faiss'))
    file_pkl.save(os.path.join(save_dir, 'index.pkl'))
    # create entry in vectors_collection
    vectors_collection.insert_one({
        "user": user,
        "name": job_name,
        "language": job_name,
        "location": save_dir,
        "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "model": embeddings_choice,
        "type": "local"
    })
    return {"status": 'ok'}


@app.route('/api/download', methods=['get'])
def download_file():
    user = secure_filename(request.args.get('user'))
    job_name = secure_filename(request.args.get('name'))
    filename = secure_filename(request.args.get('file'))
    save_dir = os.path.join(app.config['UPLOAD_FOLDER'], user, job_name)
    return send_from_directory(save_dir, filename, as_attachment=True)


@app.route('/api/delete_old', methods=['get'])
def delete_old():
    """Delete old indexes."""
    import shutil
    path = request.args.get('path')
    dirs = path.split('/')
    dirs_clean = []
    for i in range(1, len(dirs)):
        dirs_clean.append(secure_filename(dirs[i]))
    # check that path strats with indexes or vectors
    if dirs[0] not in ['indexes', 'vectors']:
        return {"status": 'error'}
    path_clean = '/'.join(dirs)
    vectors_collection.delete_one({'location': path})
    try:
        print('deleting ' + path_clean)
        shutil.rmtree(path_clean)
    except FileNotFoundError:
        pass
    return {"status": 'ok'}


# This code will be deleted after the test.
@app.route('/api/getdoctest', methods=['get'])
def sendhtml():
    print("hello")
    print("Current working directory: ", {os.getcwd()})

    filename = 'test.html'
    directory = os.path.join(app.root_path, 'inputs/local/temp/')

    return send_from_directory(directory, filename)


# handling CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         'Content-Type,Authorization,Access-Control-Allow-Origin,Access-Control-Allow-Methods,Access-Control-Allow-Credentials')
    response.headers.add('Access-Control-Allow-Methods',
                         'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response


if __name__ == "__main__":
    app.run(debug=True, port=5001)
