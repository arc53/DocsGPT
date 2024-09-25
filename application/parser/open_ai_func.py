import os

from retry import retry

from application.core.settings import settings

from application.vectorstore.vector_creator import VectorCreator


# from langchain_community.embeddings import HuggingFaceEmbeddings
# from langchain_community.embeddings import HuggingFaceInstructEmbeddings
# from langchain_community.embeddings import CohereEmbeddings


@retry(tries=10, delay=60)
def store_add_texts_with_retry(store, i, id):
    # add source_id to the metadata
    i.metadata["source_id"] = str(id)
    store.add_texts([i.page_content], metadatas=[i.metadata])
    # store_pine.add_texts([i.page_content], metadatas=[i.metadata])


def call_openai_api(docs, folder_name, id, task_status):
    # Function to create a vector store from the documents and save it to disk

    if not os.path.exists(f"{folder_name}"):
        os.makedirs(f"{folder_name}")

    from tqdm import tqdm

    c1 = 0
    if settings.VECTOR_STORE == "faiss":
        docs_init = [docs[0]]
        docs.pop(0)

        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            docs_init=docs_init,
            source_id=f"{folder_name}",
            embeddings_key=os.getenv("EMBEDDINGS_KEY"),
        )
    else:
        store = VectorCreator.create_vectorstore(
            settings.VECTOR_STORE,
            source_id=str(id),
            embeddings_key=os.getenv("EMBEDDINGS_KEY"),
        )
        store.delete_index()
    # Uncomment for MPNet embeddings
    # model_name = "sentence-transformers/all-mpnet-base-v2"
    # hf = HuggingFaceEmbeddings(model_name=model_name)
    # store = FAISS.from_documents(docs_test, hf)
    s1 = len(docs)
    for i in tqdm(
        docs,
        desc="Embedding 🦖",
        unit="docs",
        total=len(docs),
        bar_format="{l_bar}{bar}| Time Left: {remaining}",
    ):
        try:
            task_status.update_state(
                state="PROGRESS", meta={"current": int((c1 / s1) * 100)}
            )
            store_add_texts_with_retry(store, i, id)
        except Exception as e:
            print(e)
            print("Error on ", i)
            print("Saving progress")
            print(f"stopped at {c1} out of {len(docs)}")
            store.save_local(f"{folder_name}")
            break
        c1 += 1
    if settings.VECTOR_STORE == "faiss":
        store.save_local(f"{folder_name}")
