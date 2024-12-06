import os, sys

from retry import retry
import numpy as np

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


@retry(tries=10, delay=60)
def store_add_images_with_retry(store, image_base64: str, metadata: dict, id: str):
    try:
        print("Starting to embed image", file=sys.stderr)
        metadata["source_id"] = str(id)

        # Embed the image
        image_vector = store.embeddings.embed_image(image_base64=image_base64)
        print("Image embedded successfully", file=sys.stderr)

        # Call add_image to handle indexing and docstore insertion
        doc_id = store.add_image(image_vector, metadata)
        print(
            f"Completed store_add_images_with_retry, doc_id={doc_id}", file=sys.stderr
        )
    except Exception as e:
        print(f"Error in store_add_images_with_retry: {e}", file=sys.stderr)
        print(f"error line number: {sys.exc_info()[-1].tb_lineno}", file=sys.stderr)
        raise e


def call_openai_api(docs, folder_name, id, task_status):
    # Function to create a vector store from the documents and save it to disk

    if not os.path.exists(f"{folder_name}"):
        os.makedirs(f"{folder_name}")

    from tqdm import tqdm

    try:
        # c1 = 0
        text_docs = []
        images_docs = []
        for d in docs:
            """What this does is that it separates the text documents from the images documents"""
            """This is done to ensure that the text documents are indexed and the images are not"""
            """Because we will index image documents separately"""

            tables = d.metadata.get("tables", None)
            if tables and isinstance(tables, list):
                combined_text = (d.page_content or "") + "\n\n" + "\n".join(tables)
                d.page_content = combined_text.strip()
                del d.metadata["tables"]

            if d.page_content and d.page_content.strip():
                text_docs.append(d)

            images = d.metadata.get("images", None)
            if images and isinstance(images, list):
                for img in images:
                    images_docs.append((d, img))
                del d.metadata["images"]

        store = None
        if settings.VECTOR_STORE == "faiss":
            if text_docs:
                docs_init = [text_docs[0]]
                rest_docs = text_docs[1:]
                print(
                    "Dimension validation completed successfully",
                    file=sys.stderr,
                    flush=True,
                )
                print(
                    "Now proceeding with document indexing...",
                    file=sys.stderr,
                    flush=True,
                )

                print(
                    f"Number of text_docs: {len(text_docs)}",
                    file=sys.stderr,
                    flush=True,
                )
                print(
                    f"Number of images_docs: {len(images_docs)}",
                    file=sys.stderr,
                    flush=True,
                )

                print("Creating vectorstore...", file=sys.stderr, flush=True)
                store = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE,
                    docs_init=docs_init,
                    source_id=f"{folder_name}",
                    embeddings_key=os.getenv("EMBEDDINGS_KEY"),
                )
                print("Vectorstore created", file=sys.stderr, flush=True)
                s1 = len(rest_docs)
                c1 = 0
                for i in tqdm(
                    rest_docs,
                    desc="Embedding 🦖",
                    unit="docs",
                    total=len(rest_docs),
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
                # if settings.VECTOR_STORE == "faiss": no need we already checked
                store.save_local(f"{folder_name}")
        else:
            store = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE,
                source_id=str(id),
                embeddings_key=os.getenv("EMBEDDINGS_KEY"),
            )
            store.save_local(f"{folder_name}")

        """ Handling Image Seperately """
        print("Handling Images 🩻", file=sys.stderr)
        if images_docs and settings.VECTOR_STORE == "faiss":
            print(
                "Embedding Images 🦖 🩻 - Using the same text vector store",
                file=sys.stderr,
            )
            s2 = len(images_docs)
            c2 = 0
            print(f"Total images to embed: {s2}", file=sys.stderr)
            for origin_doc, img in tqdm(
                images_docs,
                desc="Embedding Images 🦖 🩻",
                unit="imgs",
                total=s2,
                bar_format="{l_bar}{bar}| Time Left: {remaining}",
            ):
                print(f"Processing image {c2+1}/{s2}", file=sys.stderr)
                image_base64 = img.get("image_base64")
                if not image_base64:
                    print("No base64 found for this image", file=sys.stderr)
                    continue

                try:
                    task_status.update_state(
                        state="PROGRESS", meta={"current": int((c2 / s2) * 100)}
                    )
                    print("Calling store_add_images_with_retry", file=sys.stderr)
                    store_add_images_with_retry(
                        store, image_base64, origin_doc.metadata, id
                    )
                    print("Image stored successfully", file=sys.stderr)
                except Exception as e:
                    print(e, file=sys.stderr)
                    print("Error on ", img.get("filename"), file=sys.stderr)
                    print("Saving progress", file=sys.stderr)
                    print(f"stopped at {c2} out of {len(images_docs)}", file=sys.stderr)
                    store.save_local(f"{folder_name}")
                    break
                c2 += 1

            print("Finished image embedding loop", file=sys.stderr)
            store.save_local(f"{folder_name}")
            print("Image store saved", file=sys.stderr)
    except Exception as e:
        print(f"Error in call_openai_api: {e}", file=sys.stderr)
        print(f"error line number: {sys.exc_info()[-1].tb_lineno}", file=sys.stderr)
        raise e

    # Uncomment for MPNet embeddings
    # model_name = "sentence-transformers/all-mpnet-base-v2"
    # hf = HuggingFaceEmbeddings(model_name=model_name)
    # store = FAISS.from_documents(docs_test, hf)
