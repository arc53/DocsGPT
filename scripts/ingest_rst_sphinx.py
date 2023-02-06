import os
import pickle
import dotenv
import faiss
import shutil
from pathlib import Path
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
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

#Load .env file
dotenv.load_dotenv()

#Directory to vector
src_dir = "scikit-learn"
dst_dir = "tmp"

convert_rst_to_txt(src_dir, dst_dir)

# Here we load in the data in the format that Notion exports it in.
ps = list(Path("tmp/"+ src_dir).glob("**/*.txt"))

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


# Here we create a vector store from the documents and save it to disk.
store = FAISS.from_texts(docs, OpenAIEmbeddings(), metadatas=metadatas)
faiss.write_index(store.index, "docs.index")
store.index = None
with open("faiss_store.pkl", "wb") as f:
    pickle.dump(store, f)

# Delete tmp folder
# Commented out for now 
#shutil.rmtree(dst_dir)