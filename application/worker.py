import datetime
import json
import logging
import mimetypes
import os
import shutil
import string
import tempfile
from typing import Any, Dict
import zipfile

from collections import Counter
from urllib.parse import urljoin

import requests
from bson.dbref import DBRef
from bson.objectid import ObjectId

from application.agents.agent_creator import AgentCreator
from application.api.answer.services.stream_processor import get_prompt

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.parser.chunking import Chunker
from application.parser.embedding_pipeline import embed_and_store_documents
from application.parser.file.bulk import SimpleDirectoryReader
from application.parser.remote.remote_creator import RemoteCreator
from application.parser.schema.base import Document
from application.retriever.retriever_creator import RetrieverCreator

from application.storage.storage_creator import StorageCreator
from application.utils import count_tokens_docs, num_tokens_from_string

mongo = MongoDB.get_client()
db = mongo[settings.MONGO_DB_NAME]
sources_collection = db["sources"]

# Constants

MIN_TOKENS = 150
MAX_TOKENS = 1250
RECURSION_DEPTH = 2


# Define a function to extract metadata from a given filename.


def metadata_from_filename(title):
    return {"title": title}


# Define a function to generate a random string of a given length.


def generate_random_string(length):
    return "".join([string.ascii_letters[i % 52] for i in range(length)])


current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def extract_zip_recursive(zip_path, extract_to, current_depth=0, max_depth=5):
    """
    Recursively extract zip files with a limit on recursion depth.

    Args:
        zip_path (str): Path to the zip file to be extracted.
        extract_to (str): Destination path for extracted files.
        current_depth (int): Current depth of recursion.
        max_depth (int): Maximum allowed depth of recursion to prevent infinite loops.
    """
    if current_depth > max_depth:
        logging.warning(f"Reached maximum recursion depth of {max_depth}")
        return
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
        os.remove(zip_path)  # Remove the zip file after extracting
    except Exception as e:
        logging.error(f"Error extracting zip file {zip_path}: {e}", exc_info=True)
        return
    # Check for nested zip files and extract them

    for root, dirs, files in os.walk(extract_to):
        for file in files:
            if file.endswith(".zip"):
                # If a nested zip file is found, extract it recursively

                file_path = os.path.join(root, file)
                extract_zip_recursive(file_path, root, current_depth + 1, max_depth)


def download_file(url, params, dest_path):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(response.content)
    except requests.RequestException as e:
        logging.error(f"Error downloading file: {e}")
        raise


def upload_index(full_path, file_data):
    files = None
    try:
        if settings.VECTOR_STORE == "faiss":
            faiss_path = full_path + "/index.faiss"
            pkl_path = full_path + "/index.pkl"

            if not os.path.exists(faiss_path):
                logging.error(f"FAISS index file not found: {faiss_path}")
                raise FileNotFoundError(f"FAISS index file not found: {faiss_path}")

            if not os.path.exists(pkl_path):
                logging.error(f"FAISS pickle file not found: {pkl_path}")
                raise FileNotFoundError(f"FAISS pickle file not found: {pkl_path}")

            files = {
                "file_faiss": open(faiss_path, "rb"),
                "file_pkl": open(pkl_path, "rb"),
            }
            response = requests.post(
                urljoin(settings.API_URL, "/api/upload_index"),
                files=files,
                data=file_data,
            )
        else:
            response = requests.post(
                urljoin(settings.API_URL, "/api/upload_index"), data=file_data
            )
        response.raise_for_status()
    except (requests.RequestException, FileNotFoundError) as e:
        logging.error(f"Error uploading index: {e}")
        raise
    finally:
        if settings.VECTOR_STORE == "faiss" and files is not None:
            for file in files.values():
                file.close()


def run_agent_logic(agent_config, input_data):
    try:
        source = agent_config.get("source")
        retriever = agent_config.get("retriever", "classic")
        if isinstance(source, DBRef):
            source_doc = db.dereference(source)
            source = str(source_doc["_id"])
            retriever = source_doc.get("retriever", agent_config.get("retriever"))
        else:
            source = {}
        source = {"active_docs": source}
        chunks = int(agent_config.get("chunks", 2))
        prompt_id = agent_config.get("prompt_id", "default")
        user_api_key = agent_config["key"]
        agent_type = agent_config.get("agent_type", "classic")
        decoded_token = {"sub": agent_config.get("user")}
        prompt = get_prompt(prompt_id, db["prompts"])
        agent = AgentCreator.create_agent(
            agent_type,
            endpoint="webhook",
            llm_name=settings.LLM_PROVIDER,
            gpt_model=settings.LLM_NAME,
            api_key=settings.API_KEY,
            user_api_key=user_api_key,
            prompt=prompt,
            chat_history=[],
            decoded_token=decoded_token,
            attachments=[],
        )
        retriever = RetrieverCreator.create_retriever(
            retriever,
            source=source,
            chat_history=[],
            prompt=prompt,
            chunks=chunks,
            token_limit=settings.DEFAULT_MAX_HISTORY,
            gpt_model=settings.LLM_NAME,
            user_api_key=user_api_key,
            decoded_token=decoded_token,
        )
        answer = agent.gen(query=input_data, retriever=retriever)
        response_full = ""
        thought = ""
        source_log_docs = []
        tool_calls = []

        for line in answer:
            if "answer" in line:
                response_full += str(line["answer"])
            elif "sources" in line:
                source_log_docs.extend(line["sources"])
            elif "tool_calls" in line:
                tool_calls.extend(line["tool_calls"])
            elif "thought" in line:
                thought += line["thought"]
        result = {
            "answer": response_full,
            "sources": source_log_docs,
            "tool_calls": tool_calls,
            "thought": thought,
        }
        logging.info(f"Agent response: {result}")
        return result
    except Exception as e:
        logging.error(f"Error in run_agent_logic: {e}", exc_info=True)
        raise


# Define the main function for ingesting and processing documents.


def ingest_worker(
    self, directory, formats, job_name, file_path, filename, user, 
    retriever="classic"
):
    """
    Ingest and process documents.

    Args:
        self: Reference to the instance of the task.
        directory (str): Specifies the directory for ingesting ('inputs' or 'temp').
        formats (list of str): List of file extensions to consider for ingestion (e.g., [".rst", ".md"]).
        job_name (str): Name of the job for this ingestion task (original, unsanitized).
        file_path (str): Complete file path to use consistently throughout the pipeline.
        filename (str): Original unsanitized filename provided by the user.
        user (str): Identifier for the user initiating the ingestion (original, unsanitized).
        retriever (str): Type of retriever to use for processing the documents.

    Returns:
        dict: Information about the completed ingestion task, including input parameters and a "limited" flag.
    """
    input_files = None
    recursive = True
    limit = None
    exclude = True
    sample = False

    storage = StorageCreator.get_storage()
    
    logging.info(f"Ingest path: {file_path}", extra={"user": user, "job": job_name})

    # Create temporary working directory

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            os.makedirs(temp_dir, exist_ok=True)

            if storage.is_directory(file_path):
                # Handle directory case
                logging.info(f"Processing directory: {file_path}")
                files_list = storage.list_files(file_path)
                
                for storage_file_path in files_list:
                    if storage.is_directory(storage_file_path):
                        continue
                        
                    # Create relative path structure in temp directory
                    rel_path = os.path.relpath(storage_file_path, file_path)
                    local_file_path = os.path.join(temp_dir, rel_path)
                    
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    
                    # Download file
                    try:
                        file_data = storage.get_file(storage_file_path)
                        with open(local_file_path, "wb") as f:
                            f.write(file_data.read())
                    except Exception as e:
                        logging.error(f"Error downloading file {storage_file_path}: {e}")
                        continue
            else:
                # Handle single file case
                temp_filename = os.path.basename(file_path)
                temp_file_path = os.path.join(temp_dir, temp_filename)
                
                file_data = storage.get_file(file_path)
                with open(temp_file_path, "wb") as f:
                    f.write(file_data.read())

                # Handle zip files
                if temp_filename.endswith(".zip"):
                    logging.info(f"Extracting zip file: {temp_filename}")
                    extract_zip_recursive(
                        temp_file_path, temp_dir, current_depth=0, max_depth=RECURSION_DEPTH
                    )

            self.update_state(state="PROGRESS", meta={"current": 1})
            if sample:
                logging.info(f"Sample mode enabled. Using {limit} documents.")
            reader = SimpleDirectoryReader(
                input_dir=temp_dir,
                input_files=input_files,
                recursive=recursive,
                required_exts=formats,
                exclude_hidden=exclude,
                file_metadata=metadata_from_filename,
            )
            raw_docs = reader.load_data()
            
            directory_structure = getattr(reader, 'directory_structure', {})
            logging.info(f"Directory structure from reader: {directory_structure}")

            chunker = Chunker(
                chunking_strategy="classic_chunk",
                max_tokens=MAX_TOKENS,
                min_tokens=MIN_TOKENS,
                duplicate_headers=False,
            )
            raw_docs = chunker.chunk(documents=raw_docs)

            docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]

            id = ObjectId()

            vector_store_path = os.path.join(temp_dir, "vector_store")
            os.makedirs(vector_store_path, exist_ok=True)

            embed_and_store_documents(docs, vector_store_path, id, self)

            tokens = count_tokens_docs(docs)

            self.update_state(state="PROGRESS", meta={"current": 100})

            if sample:
                for i in range(min(5, len(raw_docs))):
                    logging.info(f"Sample document {i}: {raw_docs[i]}")
            file_data = {
                "name": job_name,
                "file": filename,
                "user": user,
                "tokens": tokens,
                "retriever": retriever,
                "id": str(id),
                "type": "local",
                "file_path": file_path,
                "directory_structure": json.dumps(directory_structure),
            }

            upload_index(vector_store_path, file_data)
        except Exception as e:
            logging.error(f"Error in ingest_worker: {e}", exc_info=True)
            raise
    return {
        "directory": directory,
        "formats": formats,
        "name_job": job_name,  # Use original job_name
        "filename": filename,
        "user": user,  # Use original user
        "limited": False,
    }


def reingest_source_worker(self, source_id, user):
    """
    Re-ingestion worker that handles incremental updates by:
    1. Adding chunks from newly added files
    2. Removing chunks from deleted files

    Args:
        self: Task instance
        source_id: ID of the source to re-ingest
        user: User identifier

    Returns:
        dict: Information about the re-ingestion task
    """
    try:
        from application.vectorstore.vector_creator import VectorCreator

        self.update_state(state="PROGRESS", meta={"current": 10, "status": "Initializing re-ingestion scan"})

        source = sources_collection.find_one({"_id": ObjectId(source_id), "user": user})
        if not source:
            raise ValueError(f"Source {source_id} not found or access denied")

        storage = StorageCreator.get_storage()
        source_file_path = source.get("file_path", "")

        self.update_state(state="PROGRESS", meta={"current": 20, "status": "Scanning current files"})

        with tempfile.TemporaryDirectory() as temp_dir:
            # Download all files from storage to temp directory, preserving directory structure
            if storage.is_directory(source_file_path):
                files_list = storage.list_files(source_file_path)

                for storage_file_path in files_list:
                    if storage.is_directory(storage_file_path):
                        continue


                    rel_path = os.path.relpath(storage_file_path, source_file_path)
                    local_file_path = os.path.join(temp_dir, rel_path)

                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

                    # Download file
                    try:
                        file_data = storage.get_file(storage_file_path)
                        with open(local_file_path, "wb") as f:
                            f.write(file_data.read())
                    except Exception as e:
                        logging.error(f"Error downloading file {storage_file_path}: {e}")
                        continue

            reader = SimpleDirectoryReader(
                input_dir=temp_dir,
                recursive=True,
                required_exts=[
                    ".rst", ".md", ".pdf", ".txt", ".docx", ".csv", ".epub",
                    ".html", ".mdx", ".json", ".xlsx", ".pptx", ".png",
                    ".jpg", ".jpeg",
                ],
                exclude_hidden=True,
                file_metadata=metadata_from_filename,
            )
            reader.load_data()
            directory_structure = reader.directory_structure
            logging.info(f"Directory structure built with token counts: {directory_structure}")

            try:
                old_directory_structure = source.get("directory_structure") or {}
                if isinstance(old_directory_structure, str):
                    try:
                        old_directory_structure = json.loads(old_directory_structure)
                    except Exception:
                        old_directory_structure = {}

                def _flatten_directory_structure(struct, prefix=""):
                    files = set()
                    if isinstance(struct, dict):
                        for name, meta in struct.items():
                            current_path = os.path.join(prefix, name) if prefix else name
                            if isinstance(meta, dict) and ("type" in meta and "size_bytes" in meta):
                                files.add(current_path)
                            elif isinstance(meta, dict):
                                files |= _flatten_directory_structure(meta, current_path)
                    return files

                old_files = _flatten_directory_structure(old_directory_structure)
                new_files = _flatten_directory_structure(directory_structure)

                added_files = sorted(new_files - old_files)
                removed_files = sorted(old_files - new_files)

                if added_files:
                    logging.info(f"Files added since last ingest: {added_files}")
                else:
                    logging.info("No files added since last ingest.")

                if removed_files:
                    logging.info(f"Files removed since last ingest: {removed_files}")
                else:
                    logging.info("No files removed since last ingest.")

            except Exception as e:
                logging.error(f"Error comparing directory structures: {e}", exc_info=True)
                added_files = []
                removed_files = []
            try:
                if not added_files and not removed_files:
                    logging.info("No changes detected.")
                    return {
                        "source_id": source_id,
                        "user": user,
                        "status": "no_changes",
                        "added_files": [],
                        "removed_files": [],
                    }

                vector_store = VectorCreator.create_vectorstore(
                    settings.VECTOR_STORE,
                    source_id,
                    settings.EMBEDDINGS_KEY,
                )

                self.update_state(state="PROGRESS", meta={"current": 40, "status": "Processing file changes"})

                # 1) Delete chunks from removed files
                deleted = 0
                if removed_files:
                    try:
                        for ch in vector_store.get_chunks() or []:
                            metadata = ch.get("metadata", {}) if isinstance(ch, dict) else getattr(ch, "metadata", {})
                            raw_source = metadata.get("source")

                            source_file = str(raw_source) if raw_source else ""

                            if source_file in removed_files:
                                cid = ch.get("doc_id")
                                if cid:
                                    try:
                                        vector_store.delete_chunk(cid)
                                        deleted += 1
                                    except Exception as de:
                                        logging.error(f"Failed deleting chunk {cid}: {de}")
                        logging.info(f"Deleted {deleted} chunks from {len(removed_files)} removed files")
                    except Exception as e:
                        logging.error(f"Error during deletion of removed file chunks: {e}", exc_info=True)

                # 2) Add chunks from new files
                added = 0
                if added_files:
                    try:
                        # Build list of local files for added files only
                        added_local_files = []
                        for rel_path in added_files:
                            local_path = os.path.join(temp_dir, rel_path)
                            if os.path.isfile(local_path):
                                added_local_files.append(local_path)

                        if added_local_files:
                            reader_new = SimpleDirectoryReader(
                                input_files=added_local_files,
                                exclude_hidden=True,
                                errors="ignore",
                                file_metadata=metadata_from_filename,
                            )
                            raw_docs_new = reader_new.load_data()
                            chunker_new = Chunker(
                                chunking_strategy="classic_chunk",
                                max_tokens=MAX_TOKENS,
                                min_tokens=MIN_TOKENS,
                                duplicate_headers=False,
                            )
                            chunked_new = chunker_new.chunk(documents=raw_docs_new)

                            for file_path, token_count in reader_new.file_token_counts.items():
                                try:
                                    rel_path = os.path.relpath(file_path, start=temp_dir)
                                    path_parts = rel_path.split(os.sep)
                                    current_dir = directory_structure

                                    for part in path_parts[:-1]:
                                        if part in current_dir and isinstance(current_dir[part], dict):
                                            current_dir = current_dir[part]
                                        else:
                                            break

                                    filename = path_parts[-1]
                                    if filename in current_dir and isinstance(current_dir[filename], dict):
                                        current_dir[filename]["token_count"] = token_count
                                        logging.info(f"Updated token count for {rel_path}: {token_count}")
                                except Exception as e:
                                    logging.warning(f"Could not update token count for {file_path}: {e}")

                            for d in chunked_new:
                                meta = dict(d.extra_info or {})
                                try:
                                    raw_src = meta.get("source")
                                    if isinstance(raw_src, str) and os.path.isabs(raw_src):
                                        meta["source"] = os.path.relpath(raw_src, start=temp_dir)
                                except Exception:
                                    pass

                                vector_store.add_chunk(d.text, metadata=meta)
                                added += 1
                            logging.info(f"Added {added} chunks from {len(added_files)} new files")
                    except Exception as e:
                        logging.error(f"Error during ingestion of new files: {e}", exc_info=True)

                # 3) Update source directory structure timestamp
                try:
                    total_tokens = sum(reader.file_token_counts.values())
                    
                    sources_collection.update_one(
                        {"_id": ObjectId(source_id)},
                        {
                            "$set": {
                                "directory_structure": directory_structure,
                                "date": datetime.datetime.now(),
                                "tokens": total_tokens
                            }
                        },
                    )
                except Exception as e:
                    logging.error(f"Error updating directory_structure in DB: {e}", exc_info=True)

                self.update_state(state="PROGRESS", meta={"current": 100, "status": "Re-ingestion completed"})

                return {
                    "source_id": source_id,
                    "user": user,
                    "status": "completed",
                    "added_files": added_files,
                    "removed_files": removed_files,
                    "chunks_added": added,
                    "chunks_deleted": deleted,
                }
            except Exception as e:
                logging.error(f"Error while processing file changes: {e}", exc_info=True)
                raise



    except Exception as e:
        logging.error(f"Error in reingest_source_worker: {e}", exc_info=True)
        raise

def remote_worker(
    self,
    source_data,
    name_job,
    user,
    loader,
    directory="temp",
    retriever="classic",
    sync_frequency="never",
    operation_mode="upload",
    doc_id=None,
):
    full_path = os.path.join(directory, user, name_job)
    if not os.path.exists(full_path):
        os.makedirs(full_path)
    self.update_state(state="PROGRESS", meta={"current": 1})
    try:
        logging.info("Initializing remote loader with type: %s", loader)
        remote_loader = RemoteCreator.create_loader(loader)
        raw_docs = remote_loader.load_data(source_data)

        chunker = Chunker(
            chunking_strategy="classic_chunk",
            max_tokens=MAX_TOKENS,
            min_tokens=MIN_TOKENS,
            duplicate_headers=False,
        )
        docs = chunker.chunk(documents=raw_docs)
        docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
        tokens = count_tokens_docs(docs)
        logging.info("Total tokens calculated: %d", tokens)

        if operation_mode == "upload":
            id = ObjectId()
            embed_and_store_documents(docs, full_path, id, self)
        elif operation_mode == "sync":
            if not doc_id or not ObjectId.is_valid(doc_id):
                logging.error("Invalid doc_id provided for sync operation: %s", doc_id)
                raise ValueError("doc_id must be provided for sync operation.")
            id = ObjectId(doc_id)
            embed_and_store_documents(docs, full_path, id, self)
        self.update_state(state="PROGRESS", meta={"current": 100})

        file_data = {
            "name": name_job,
            "user": user,
            "tokens": tokens,
            "retriever": retriever,
            "id": str(id),
            "type": loader,
            "remote_data": source_data,
            "sync_frequency": sync_frequency,
        }
        upload_index(full_path, file_data)
    except Exception as e:
        logging.error("Error in remote_worker task: %s", str(e), exc_info=True)
        raise
    finally:
        if os.path.exists(full_path):
            shutil.rmtree(full_path)
    logging.info("remote_worker task completed successfully")
    return {"urls": source_data, "name_job": name_job, "user": user, "limited": False}


def sync(
    self,
    source_data,
    name_job,
    user,
    loader,
    sync_frequency,
    retriever,
    doc_id=None,
    directory="temp",
):
    try:
        remote_worker(
            self,
            source_data,
            name_job,
            user,
            loader,
            directory,
            retriever,
            sync_frequency,
            "sync",
            doc_id,
        )
    except Exception as e:
        logging.error(f"Error during sync: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    return {"status": "success"}


def sync_worker(self, frequency):
    sync_counts = Counter()
    sources = sources_collection.find()
    for doc in sources:
        if doc.get("sync_frequency") == frequency:
            name = doc.get("name")
            user = doc.get("user")
            source_type = doc.get("type")
            source_data = doc.get("remote_data")
            retriever = doc.get("retriever")
            doc_id = str(doc.get("_id"))
            resp = sync(
                self, source_data, name, user, source_type, frequency, retriever, doc_id
            )
            sync_counts["total_sync_count"] += 1
            sync_counts[
                "sync_success" if resp["status"] == "success" else "sync_failure"
            ] += 1
    return {
        key: sync_counts[key]
        for key in ["total_sync_count", "sync_success", "sync_failure"]
    }


def attachment_worker(self, file_info, user):
    """
    Process and store a single attachment without vectorization.
    """

    mongo = MongoDB.get_client()
    db = mongo[settings.MONGO_DB_NAME]
    attachments_collection = db["attachments"]

    filename = file_info["filename"]
    attachment_id = file_info["attachment_id"]
    relative_path = file_info["path"]
    metadata = file_info.get("metadata", {})

    try:
        self.update_state(state="PROGRESS", meta={"current": 10})
        storage = StorageCreator.get_storage()

        self.update_state(
            state="PROGRESS", meta={"current": 30, "status": "Processing content"}
        )

        content = storage.process_file(
            relative_path,
            lambda local_path, **kwargs: SimpleDirectoryReader(
                input_files=[local_path], exclude_hidden=True, errors="ignore"
            )
            .load_data()[0]
            .text,
        )
        
        
        token_count = num_tokens_from_string(content)
        if token_count > 100000:
            content = content[:250000]
            token_count = num_tokens_from_string(content)
        
        self.update_state(
            state="PROGRESS", meta={"current": 80, "status": "Storing in database"}
        )

        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        doc_id = ObjectId(attachment_id)
        attachments_collection.insert_one(
            {
                "_id": doc_id,
                "user": user,
                "path": relative_path,
                "filename": filename,
                "content": content,
                "token_count": token_count,
                "mime_type": mime_type,
                "date": datetime.datetime.now(),
                "metadata": metadata,
            }
        )

        logging.info(
            f"Stored attachment with ID: {attachment_id}", extra={"user": user}
        )

        self.update_state(state="PROGRESS", meta={"current": 100, "status": "Complete"})

        return {
            "filename": filename,
            "path": relative_path,
            "token_count": token_count,
            "attachment_id": attachment_id,
            "mime_type": mime_type,
            "metadata": metadata,
        }
    except Exception as e:
        logging.error(
            f"Error processing file {filename}: {e}",
            extra={"user": user},
            exc_info=True,
        )
        raise


def agent_webhook_worker(self, agent_id, payload):
    """
    Process the webhook payload for an agent.

    Args:
        self: Reference to the instance of the task.
        agent_id (str): Unique identifier for the agent.
        payload (dict): The payload data from the webhook.

    Returns:
        dict: Information about the processed webhook.
    """
    mongo = MongoDB.get_client()
    db = mongo["docsgpt"]
    agents_collection = db["agents"]

    self.update_state(state="PROGRESS", meta={"current": 1})
    try:
        agent_oid = ObjectId(agent_id)
        agent_config = agents_collection.find_one({"_id": agent_oid})
        if not agent_config:
            raise ValueError(f"Agent with ID {agent_id} not found.")
        input_data = json.dumps(payload)
    except Exception as e:
        logging.error(f"Error processing agent webhook: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    self.update_state(state="PROGRESS", meta={"current": 50})
    try:
        result = run_agent_logic(agent_config, input_data)
    except Exception as e:
        logging.error(f"Error running agent logic: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        self.update_state(state="PROGRESS", meta={"current": 100})
        logging.info(
            f"Webhook processed for agent {agent_id}", extra={"agent_id": agent_id}
        )
        return {"status": "success", "result": result}


def ingest_connector(
    self, job_name: str, user: str, source_type: str,
    source_config: Dict[str, Any], retriever: str = "classic"
) -> Dict[str, Any]:
    """
    ingestion for internal knowledge bases(GoogleDrive).

    Args:
        job_name: Name of the ingestion job
        user: User identifier
        source_type: Type of remote source ("google_drive", "dropbox", etc.)
        source_config: Configuration specific to the source type
        retriever: Type of retriever to use
    """
    logging.info(f"Starting remote ingestion from {source_type} for user: {user}, job: {job_name}")
    self.update_state(state="PROGRESS", meta={"current": 1})

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Step 1: Get the appropriate remote loader
            logging.info(f"source_config {source_config}")
            
            if source_type == "google_drive":
                session_token = source_config.get("session_token")
                if not session_token:
                    raise ValueError("Google Drive connector requires session_token in source_config")

                from application.parser.remote.google_drive_loader import GoogleDriveLoader
                remote_loader = GoogleDriveLoader(session_token)
                
                # Create a clean config for storage that excludes the session token
                api_source_config = {
                    "file_ids": source_config.get("file_ids", []),
                    "folder_id": source_config.get("folder_id", ""),
                }
                
                if source_config.get("recursive") is not None:
                    api_source_config["recursive"] = source_config.get("recursive")
            else:
                remote_loader = RemoteCreator.create_loader(source_type, source_config)
                api_source_config = source_config
            
            # Step 2: Download files to temp directory
            self.update_state(state="PROGRESS", meta={"current": 20, "status": "Downloading files"})

            # For Google Drive, pass the source_config to download_to_directory
            if source_type == "google_drive":
                download_info = remote_loader.download_to_directory(temp_dir, source_config)
            else:
                download_info = remote_loader.download_to_directory(temp_dir)
            
            if download_info.get("empty_result", False) or not download_info.get("files_downloaded", 0):
                logging.warning(f"No files were downloaded from {source_type}")
                # Create empty result directly instead of calling a separate method
                return {
                    "name": job_name,
                    "user": user,
                    "tokens": 0,
                    "type": source_type,
                    "source_config": source_config,
                    "directory_structure": "{}",
                }
            
            # Step 3: Use SimpleDirectoryReader to process downloaded files
            self.update_state(state="PROGRESS", meta={"current": 40, "status": "Processing files"})
            reader = SimpleDirectoryReader(
                input_dir=temp_dir,
                recursive=True,
                required_exts=[
                    ".rst", ".md", ".pdf", ".txt", ".docx", ".csv", ".epub",
                    ".html", ".mdx", ".json", ".xlsx", ".pptx", ".png",
                    ".jpg", ".jpeg",
                ],
                exclude_hidden=True,
                file_metadata=metadata_from_filename,
            )
            raw_docs = reader.load_data()
            directory_structure = getattr(reader, 'directory_structure', {})
            
            # Step 4: Process documents (chunking, embedding, etc.)
            self.update_state(state="PROGRESS", meta={"current": 60, "status": "Processing documents"})
            
            chunker = Chunker(
                chunking_strategy="classic_chunk",
                max_tokens=MAX_TOKENS,
                min_tokens=MIN_TOKENS,
                duplicate_headers=False,
            )
            raw_docs = chunker.chunk(documents=raw_docs)
            
            # Preserve source information in document metadata
            for doc in raw_docs:
                if hasattr(doc, 'extra_info') and doc.extra_info:
                    source = doc.extra_info.get('source')
                    if source and os.path.isabs(source):
                        # Convert absolute path to relative path
                        doc.extra_info['source'] = os.path.relpath(source, start=temp_dir)
            
            docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
            
            # Step 5: Store in vector database
            id = ObjectId()
            vector_store_path = os.path.join(temp_dir, "vector_store")
            os.makedirs(vector_store_path, exist_ok=True)

            self.update_state(state="PROGRESS", meta={"current": 80, "status": "Storing documents"})
            embed_and_store_documents(docs, vector_store_path, id, self)

            tokens = count_tokens_docs(docs)

            # Step 6: Upload index files
            file_data = {
                "user": user,
                "name": job_name,
                "tokens": tokens,
                "retriever": retriever,
                "id": str(id),
                "type": source_type,
                "remote_data": json.dumps(api_source_config),
                "directory_structure": json.dumps(directory_structure)
            }
            
            upload_index(vector_store_path, file_data)
            
            # Ensure we mark the task as complete
            self.update_state(state="PROGRESS", meta={"current": 100, "status": "Complete"})
            
            logging.info(f"Remote ingestion completed: {job_name}")
            
            return {
                "user": user,
                "name": job_name,
                "tokens": tokens,
                "type": source_type,
                "id": str(id),
                "status": "complete"
            }
            
        except Exception as e:
            logging.error(f"Error during remote ingestion: {e}", exc_info=True)
            raise
