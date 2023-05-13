import os

import tiktoken
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from retry import retry


# from langchain.embeddings import HuggingFaceEmbeddings
# from langchain.embeddings import HuggingFaceInstructEmbeddings
# from langchain.embeddings import CohereEmbeddings


def num_tokens_from_string(string: str, encoding_name: str) -> int:
    # Function to convert string to tokens and estimate user cost.
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    total_price = ((num_tokens / 1000) * 0.0004)
    return num_tokens, total_price


@retry(tries=10, delay=60)
def store_add_texts_with_retry(store, i):
    store.add_texts([i.page_content], metadatas=[i.metadata])
    # store_pine.add_texts([i.page_content], metadatas=[i.metadata])


def call_openai_api(docs, folder_name, task_status):
    # Function to create a vector store from the documents and save it to disk.

    # create output folder if it doesn't exist
    if not os.path.exists(f"{folder_name}"):
        os.makedirs(f"{folder_name}")

    from tqdm import tqdm
    docs_test = [docs[0]]
    docs.pop(0)
    c1 = 0

    store = FAISS.from_documents(docs_test, OpenAIEmbeddings(openai_api_key=os.getenv("EMBEDDINGS_KEY")))

    # Uncomment for MPNet embeddings
    # model_name = "sentence-transformers/all-mpnet-base-v2"
    # hf = HuggingFaceEmbeddings(model_name=model_name)
    # store = FAISS.from_documents(docs_test, hf)
    s1 = len(docs)
    for i in tqdm(docs, desc="Embedding 🦖", unit="docs", total=len(docs),
                  bar_format='{l_bar}{bar}| Time Left: {remaining}'):
        try:
            task_status.update_state(state='PROGRESS', meta={'current': int((c1 / s1) * 100)})
            store_add_texts_with_retry(store, i)
        except Exception as e:
            print(e)
            print("Error on ", i)
            print("Saving progress")
            print(f"stopped at {c1} out of {len(docs)}")
            store.save_local(f"{folder_name}")
            break
        c1 += 1
    store.save_local(f"{folder_name}")


def get_user_permission(docs, folder_name):
    # Function to ask user permission to call the OpenAI api and spend their OpenAI funds.
    # Here we convert the docs list to a string and calculate the number of OpenAI tokens the string represents.
    # docs_content = (" ".join(docs))
    docs_content = ""
    for doc in docs:
        docs_content += doc.page_content

    tokens, total_price = num_tokens_from_string(string=docs_content, encoding_name="cl100k_base")
    # Here we print the number of tokens and the approx user cost with some visually appealing formatting.
    print(f"Number of Tokens = {format(tokens, ',d')}")
    print(f"Approx Cost = ${format(total_price, ',.2f')}")
    # Here we check for user permission before calling the API.
    user_input = input("Price Okay? (Y/N) \n").lower()
    if user_input == "y":
        call_openai_api(docs, folder_name)
    elif user_input == "":
        call_openai_api(docs, folder_name)
    else:
        print("The API was not called. No money was spent.")
