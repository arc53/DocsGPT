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

# Redirect PosixPath to WindowsPath on Windows
import platform
if platform.system() == "Windows":
    import pathlib
    temp = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath

# loading the .env file
dotenv.load_dotenv()

# loading the index and the store and the prompt template
index = faiss.read_index("docs.index")
with open("combine_prompt.txt", "r") as f:
    template = f.read()

with open("faiss_store.pkl", "rb") as f:
    store = pickle.load(f)

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/answer", methods=["POST"])
def api_answer():
    data = request.get_json()
    question = data["question"]
    api_key = data["api_key"]

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


# handling CORS
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


if __name__ == "__main__":
    app.run(debug=True)
