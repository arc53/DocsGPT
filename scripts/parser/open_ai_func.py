import faiss
import pickle
import tiktoken
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings


def num_tokens_from_string(string: str, encoding_name: str) -> int:
# Function to convert string to tokens and estimate user cost.
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    total_price = ((num_tokens/1000) * 0.0004)
    return num_tokens, total_price

def call_openai_api(docs):
# Function to create a vector store from the documents and save it to disk.
    from tqdm import tqdm
    docs_test = [docs[0]]
    # remove the first element from docs
    docs.pop(0)
    # cut first n docs if you want to restart
    #docs = docs[:n]
    c1 = 0
    store = FAISS.from_documents(docs_test, OpenAIEmbeddings())
    for i in tqdm(docs, desc="Embedding 🦖", unit="docs", total=len(docs), bar_format='{l_bar}{bar}| Time Left: {remaining}'):
        try:
            import time
            store.add_texts([i.page_content], metadatas=[i.metadata])
        except Exception as e:
            print(e)
            print("Error on ", i)
            print("Saving progress")
            print(f"stopped at {c1} out of {len(docs)}")
            faiss.write_index(store.index, "docs.index")
            store.index = None
            with open("faiss_store.pkl", "wb") as f:
                pickle.dump(store, f)
            print("Sleeping for 10 seconds and trying again")
            time.sleep(10)
            store.add_texts([i.page_content], metadatas=[i.metadata])
        c1 += 1


    faiss.write_index(store.index, "docs.index")
    store.index = None
    with open("faiss_store.pkl", "wb") as f:
        pickle.dump(store, f)

def get_user_permission(docs):
# Function to ask user permission to call the OpenAI api and spend their OpenAI funds.
    # Here we convert the docs list to a string and calculate the number of OpenAI tokens the string represents.
    #docs_content = (" ".join(docs))
    docs_content = ""
    for doc in docs:
        docs_content += doc.page_content


    tokens, total_price = num_tokens_from_string(string=docs_content, encoding_name="cl100k_base")
    # Here we print the number of tokens and the approx user cost with some visually appealing formatting.
    print(f"Number of Tokens = {format(tokens, ',d')}")
    print(f"Approx Cost = ${format(total_price, ',.2f')}")
    #Here we check for user permission before calling the API.
    user_input = input("Price Okay? (Y/N) \n").lower()
    if user_input == "y":
        call_openai_api(docs)
    elif user_input == "":
        call_openai_api(docs)
    else:
        print("The API was not called. No money was spent.")