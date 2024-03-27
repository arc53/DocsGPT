import os
import sys

import tiktoken
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from retry import retry


# from langchain.embeddings import HuggingFaceEmbeddings
# from langchain.embeddings import HuggingFaceInstructEmbeddings
# from langchain.embeddings import CohereEmbeddings

import boto3
import shutil

def num_tokens_from_string(string: str, encoding_name: str) -> tuple[int, float]:
    # Function to convert string to tokens and estimate user cost.
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    total_price = (num_tokens / 1000) * 0.0004
    return num_tokens, total_price


@retry(tries=10, delay=60)
def store_add_texts_with_retry(store, i):
    store.add_texts([i.page_content], metadatas=[i.metadata])
    # store_pine.add_texts([i.page_content], metadatas=[i.metadata])


def call_openai_api(docs, folder_name, use_s3, s3_bucket, s3_save_folder, s3_assume_role, aws_assume_role_profile):
    # Function to create a vector store from the documents and save it to disk.

    # create output folder if it doesn't exist
    if not os.path.exists(f"outputs/{folder_name}"):
        os.makedirs(f"outputs/{folder_name}")

    from tqdm import tqdm

    docs_test = [docs[0]]
    # remove the first element from docs
    docs.pop(0)
    # cut first n docs if you want to restart
    # docs = docs[:n]
    c1 = 0
    # pinecone.init(
    #     api_key="",  # find at app.pinecone.io
    #     environment="us-east1-gcp"  # next to api key in console
    # )
    # index_name = "pandas"
    if (  # azure
        os.environ.get("OPENAI_API_BASE")
        and os.environ.get("OPENAI_API_VERSION")
        and os.environ.get("AZURE_DEPLOYMENT_NAME")
        and os.environ.get("AZURE_EMBEDDINGS_DEPLOYMENT_NAME")
    ):
        os.environ["OPENAI_API_TYPE"] = "azure"
        openai_embeddings = OpenAIEmbeddings(model=os.environ.get("AZURE_EMBEDDINGS_DEPLOYMENT_NAME"))
    else:
        openai_embeddings = OpenAIEmbeddings()
    store = FAISS.from_documents(docs_test, openai_embeddings)
    # store_pine = Pinecone.from_documents(docs_test, OpenAIEmbeddings(), index_name=index_name)

    # Uncomment for MPNet embeddings
    # model_name = "sentence-transformers/all-mpnet-base-v2"
    # hf = HuggingFaceEmbeddings(model_name=model_name)
    # store = FAISS.from_documents(docs_test, hf)
    for i in tqdm(
        docs, desc="Embedding 🦖", unit="docs", total=len(docs), bar_format="{l_bar}{bar}| Time Left: {remaining}"
    ):
        try:
            store_add_texts_with_retry(store, i)
        except Exception as e:
            print(e)
            print("Error on ", i)
            print("Saving progress")
            print(f"stopped at {c1} out of {len(docs)}")
            store.save_local(f"outputs/{folder_name}")
            break
        c1 += 1
    store.save_local(f"outputs/{folder_name}")

    if use_s3:
        upload_to_s3(s3_bucket, s3_save_folder, s3_assume_role, aws_assume_role_profile)

def get_user_permission(docs, folder_name, use_s3, s3_bucket, s3_save_folder, s3_assume_role, aws_assume_role_profile):
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
        call_openai_api(docs, folder_name, use_s3, s3_bucket, s3_save_folder, s3_assume_role, aws_assume_role_profile)
    elif user_input == "":
        call_openai_api(docs, folder_name, use_s3, s3_bucket, s3_save_folder, s3_assume_role, aws_assume_role_profile)
    else:
        print("The API was not called. No money was spent.")

def upload_to_s3(s3_bucket, s3_save_folder, s3_assume_role, aws_assume_role_profile):
    # Set defaults from environment variables if not provided via command line
    s3_bucket = s3_bucket or os.environ.get("S3_BUCKET")
    s3_save_folder = s3_save_folder or os.environ.get("S3_SAVE_FOLDER")
    aws_assume_role_profile = aws_assume_role_profile or os.environ.get("AWS_ASSUME_ROLE_PROFILE")
    
    if not s3_bucket:
        print("Error: S3_BUCKET environment variable is not set.")
        sys.exit(1)

    if s3_assume_role and not aws_assume_role_profile:
        print("Error: AWS_ASSUME_ROLE_PROFILE environment variable is not set.")
        sys.exit(1)

    if not s3_save_folder:
        print("WARNING: S3_SAVE_FOLDER environment variable is not set. Root will be used.")
        s3_save_folder = ""

    session_parameters = {'profile_name': aws_assume_role_profile} if s3_assume_role else {}
    s3 = boto3.Session(**session_parameters).resource("s3")

    from tqdm import tqdm

    with tqdm(
            total=2,
            desc=f"Uploading vectors to '{s3_save_folder}' folder in S3 bucket '{s3_bucket}' 🦖",
            unit="doc(s)",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} {unit} [Time Left: {remaining}]",
        ) as pbar:
            # First File Upload
            s3.Bucket(s3_bucket).upload_file(
                "outputs/s3_temp_storage/index.faiss",
                f"{s3_save_folder}" + "/" + "index.faiss",
            )
            pbar.update(1)  # update progress bar after first file

            # Second File Upload
            s3.Bucket(s3_bucket).upload_file(
                "outputs/s3_temp_storage/index.pkl",
                f"{s3_save_folder}" + "/" + "index.pkl",
            )
            pbar.update(1)  # Update progress bar after second file

            # Cleanup
            os.remove("outputs/s3_temp_storage/index.faiss")
            os.remove("outputs/s3_temp_storage/index.pkl")
            os.removedirs("outputs/s3_temp_storage")
            shutil.rmtree("s3_temp_storage")