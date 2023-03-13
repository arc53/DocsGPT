import os

import dotenv
import tiktoken
from langchain import FAISS
from langchain.embeddings import OpenAIEmbeddings

dotenv.load_dotenv()
embeddings_key = os.getenv("API_KEY")
docsearch = FAISS.load_local('outputs/inputs', OpenAIEmbeddings(openai_api_key=embeddings_key))

d1 = docsearch.similarity_search("Whats new in 1.5.3?")
print(d1)
print("=====================================")
print("=====================================")
for i in d1:
    print("docs length (tokens)")
    doc_len = len(tiktoken.get_encoding("cl100k_base").encode(i.page_content))
    print(doc_len)
