import os
import pickle
import dotenv
import datetime
from flask import Flask, request, render_template
# os.environ["LANGCHAIN_HANDLER"] = "langchain"
import faiss
from langchain import OpenAI
from langchain.chains import VectorDBQAWithSourcesChain
from langchain.prompts import PromptTemplate
import requests

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

# check if OPENAI_API_KEY is set
if os.getenv("OPENAI_API_KEY") is not None:
    api_key_set = True

else:
    api_key_set = False



app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html", api_key_set=api_key_set)


@app.route("/api/answer", methods=["POST"])
def api_answer():
    data = request.get_json()
    question = data["question"]
    if not api_key_set:
        api_key = data["api_key"]
    else:
        api_key = os.getenv("OPENAI_API_KEY")

    # check if the vectorstore is set
    if "active_docs" in data:
        vectorstore = "vectors/" + data["active_docs"]
        if data['active_docs'] == "default":
            vectorstore = ""
    else:
        vectorstore = ""

    # loading the index and the store and the prompt template
    index = faiss.read_index(f"{vectorstore}docs.index")

    with open(f"{vectorstore}faiss_store.pkl", "rb") as f:
        store = pickle.load(f)

    store.index = index
    # create a prompt template
    c_prompt = PromptTemplate(input_variables=["summaries", "question"], template=template)
    # create a chain with the prompt template and the store

    chain = VectorDBQAWithSourcesChain.from_llm(llm=OpenAI(openai_api_key=api_key, temperature=0), vectorstore=store, combine_prompt=c_prompt)
    # fetch the answer
    result = chain({"question": question})

    # some formatting for the frontend
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

        return {"status":  'loaded'}

# handling CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


if __name__ == "__main__":
    app.run(debug=True)
