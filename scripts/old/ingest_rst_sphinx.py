import os
import pickle
import shutil
import sys
from argparse import ArgumentParser
from pathlib import Path

import dotenv
import faiss
import tiktoken
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import FAISS
from sphinx.cmd.build import main as sphinx_main


def convert_rst_to_txt(src_dir, dst_dir):
    # Check if the source directory exists
    if not os.path.exists(src_dir):
        raise Exception("Source directory does not exist")
    # Walk through the source directory
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            # Check if the file has .rst extension
            if file.endswith(".rst"):
                # Construct the full path of the file
                src_file = os.path.join(root, file.replace(".rst", ""))
                # Convert the .rst file to .txt file using sphinx-build
                args = f". -b text -D extensions=sphinx.ext.autodoc " \
                       f"-D master_doc={src_file} " \
                       f"-D source_suffix=.rst " \
                       f"-C {dst_dir} "
                sphinx_main(args.split())
            elif file.endswith(".md"):
                # Rename the .md file to .rst file
                src_file = os.path.join(root, file)
                dst_file = os.path.join(root, file.replace(".md", ".rst"))
                os.rename(src_file, dst_file)
                # Convert the .rst file to .txt file using sphinx-build
                args = f". -b text -D extensions=sphinx.ext.autodoc " \
                       f"-D master_doc={dst_file} " \
                       f"-D source_suffix=.rst " \
                       f"-C {dst_dir} "
                sphinx_main(args.split())


def num_tokens_from_string(string: str, encoding_name: str) -> int:
    # Function to convert string to tokens and estimate user cost.
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    total_price = ((num_tokens / 1000) * 0.0004)
    return num_tokens, total_price


def call_openai_api():
    # Function to create a vector store from the documents and save it to disk.
    store = FAISS.from_texts(docs, OpenAIEmbeddings(), metadatas=metadatas)
    faiss.write_index(store.index, "docs.index")
    store.index = None
    with open("faiss_store.pkl", "wb") as f:
        pickle.dump(store, f)


def get_user_permission():
    # Function to ask user permission to call the OpenAI api and spend their OpenAI funds.
    # Here we convert the docs list to a string and calculate the number of OpenAI tokens the string represents.
    docs_content = (" ".join(docs))
    tokens, total_price = num_tokens_from_string(string=docs_content, encoding_name="cl100k_base")
    # Here we print the number of tokens and the approx user cost with some visually appealing formatting.
    print(f"Number of Tokens = {format(tokens, ',d')}")
    print(f"Approx Cost = ${format(total_price, ',.2f')}")
    # Here we check for user permission before calling the API.
    user_input = input("Price Okay? (Y/N) \n").lower()
    if user_input == "y":
        call_openai_api()
    elif user_input == "":
        call_openai_api()
    else:
        print("The API was not called. No money was spent.")


ap = ArgumentParser("Script for training DocsGPT on Sphinx documentation")
ap.add_argument("-i", "--inputs",
                type=str,
                default="inputs",
                help="Directory containing documentation files")
args = ap.parse_args()

# Load .env file
dotenv.load_dotenv()

# Directory to vector
src_dir = args.inputs
dst_dir = "tmp"

convert_rst_to_txt(src_dir, dst_dir)

# Here we load in the data in the format that Notion exports it in.
ps = list(Path("tmp/" + src_dir).glob("**/*.txt"))

# parse all child directories
data = []
sources = []
for p in ps:
    with open(p) as f:
        data.append(f.read())
    sources.append(p)

# Here we split the documents, as needed, into smaller chunks.
# We do this due to the context limits of the LLMs.
text_splitter = CharacterTextSplitter(chunk_size=1500, separator="\n")
docs = []
metadatas = []
for i, d in enumerate(data):
    splits = text_splitter.split_text(d)
    docs.extend(splits)
    metadatas.extend([{"source": sources[i]}] * len(splits))

# Here we check for command line arguments for bot calls.
# If no argument exists or the permission_bypass_flag argument is not '-y',
# user permission is requested to call the API.
if len(sys.argv) > 1:
    permission_bypass_flag = sys.argv[1]
    if permission_bypass_flag == '-y':
        call_openai_api()
    else:
        get_user_permission()
else:
    get_user_permission()

# Delete tmp folder
# Commented out for now
shutil.rmtree(dst_dir)
