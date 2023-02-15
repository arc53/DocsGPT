import os

import dotenv
import requests
from flask import Flask, request, render_template
from langchain import FAISS
from langchain import OpenAI, VectorDBQA, HuggingFaceHub, Cohere
from langchain.chains.question_answering import load_qa_chain
from langchain.embeddings import OpenAIEmbeddings, HuggingFaceHubEmbeddings, CohereEmbeddings, HuggingFaceInstructEmbeddings
from langchain.prompts import PromptTemplate

# os.environ["LANGCHAIN_HANDLER"] = "langchain"

if os.getenv("LLM_NAME") is not None:
    llm_choice = os.getenv("LLM_NAME")
else:
    llm_choice = "openai"

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

with open("combine_prompt.txt", "r") as f:
    template = f.read()

if os.getenv("API_KEY") is not None:
    api_key_set = True
else:
    api_key_set = False
if os.getenv("EMBEDDINGS_KEY") is not None:
    embeddings_key_set = True
else:
    embeddings_key_set = False

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html", api_key_set=api_key_set, llm_choice=llm_choice,
                           embeddings_choice=embeddings_choice)


@app.route("/api/answer", methods=["POST"])
def api_answer():
    data = request.get_json()
    question = data["question"]
    if not api_key_set:
        api_key = data["api_key"]
    else:
        api_key = os.getenv("API_KEY")
    if not embeddings_key_set:
        embeddings_key = data["embeddings_key"]
    else:
        embeddings_key = os.getenv("EMBEDDINGS_KEY")

    print(embeddings_key)
    print(api_key)

    # check if the vectorstore is set
    if "active_docs" in data:
        vectorstore = "vectors/" + data["active_docs"]
        if data['active_docs'] == "default":
            vectorstore = ""
    else:
        vectorstore = ""

    # loading the index and the store and the prompt template
    # Note if you have used other embeddings than OpenAI, you need to change the embeddings
    if embeddings_choice == "openai_text-embedding-ada-002":
        docsearch = FAISS.load_local(vectorstore, OpenAIEmbeddings(openai_api_key=embeddings_key))
    elif embeddings_choice == "huggingface_sentence-transformers/all-mpnet-base-v2":
        docsearch = FAISS.load_local(vectorstore, HuggingFaceHubEmbeddings())
    elif embeddings_choice == "huggingface_hkunlp/instructor-large":
        docsearch = FAISS.load_local(vectorstore, HuggingFaceInstructEmbeddings())
    elif embeddings_choice == "cohere_medium":
        docsearch = FAISS.load_local(vectorstore, CohereEmbeddings(cohere_api_key=embeddings_key))

    # create a prompt template
    c_prompt = PromptTemplate(input_variables=["summaries", "question"], template=template)

    if llm_choice == "openai":
        llm = OpenAI(openai_api_key=api_key, temperature=0)
    elif llm_choice == "manifest":
        llm = ManifestWrapper(client=manifest, llm_kwargs={"temperature": 0.001, "max_tokens": 2048})
    elif llm_choice == "huggingface":
        llm = HuggingFaceHub(repo_id="bigscience/bloom", huggingfacehub_api_token=api_key)
    elif llm_choice == "cohere":
        llm = Cohere(model="command-xlarge-nightly", cohere_api_key=api_key)

    qa_chain = load_qa_chain(llm=llm, chain_type="map_reduce",
                             combine_prompt=c_prompt)

    chain = VectorDBQA(combine_documents_chain=qa_chain, vectorstore=docsearch, k=2)

    # fetch the answer
    result = chain({"query": question})
    print(result)

    # some formatting for the frontend
    result['answer'] = result['result']
    result['answer'] = result['answer'].replace("\\n", "<br>")
    result['answer'] = result['answer'].replace("SOURCES:", "")
    # mock result
    # result = {
    #     "answer": "The answer is 42",
    #     "sources": ["https://en.wikipedia.org/wiki/42_(number)", "https://en.wikipedia.org/wiki/42_(number)"]
    # }
    return result


@app.route("/api/docs_check", methods=["POST"])
def check_docs():
    # check if docs exist in a vectorstore folder
    data = request.get_json()
    vectorstore = "vectors/" + data["docs"]
    base_path = 'https://raw.githubusercontent.com/arc53/DocsHUB/main/'
    #
    if os.path.exists(vectorstore):
        return {"status": 'exists'}
    else:
        r = requests.get(base_path + vectorstore + "docs.index")
        # save to vectors directory
        # check if the directory exists
        if not os.path.exists(vectorstore):
            os.makedirs(vectorstore)

        with open(vectorstore + "docs.index", "wb") as f:
            f.write(r.content)
        # download the store
        r = requests.get(base_path + vectorstore + "faiss_store.pkl")
        with open(vectorstore + "faiss_store.pkl", "wb") as f:
            f.write(r.content)

        return {"status": 'loaded'}


# handling CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


if __name__ == "__main__":
    app.run(debug=True)
