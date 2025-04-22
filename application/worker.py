import logging
import os
import shutil
import string
import zipfile
import io
import datetime
import mimetypes
import requests
import tempfile

from collections import Counter
from urllib.parse import urljoin

from application.storage.storage_creator import StorageCreator
from application.utils import num_tokens_from_string
from application.core.settings import settings
from application.parser.file.bulk import SimpleDirectoryReader
from bson.objectid import ObjectId

from application.core.mongo_db import MongoDB
from application.parser.embedding_pipeline import embed_and_store_documents
from application.parser.remote.remote_creator import RemoteCreator
from application.parser.schema.base import Document
from application.parser.chunking import Chunker
from application.utils import count_tokens_docs

mongo = MongoDB.get_client()
db = mongo["docsgpt"]
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
        logging.error(f"Error extracting zip file {zip_path}: {e}")
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
    try:
        if settings.VECTOR_STORE == "faiss":
            files = {
                "file_faiss": open(full_path + "/index.faiss", "rb"),
                "file_pkl": open(full_path + "/index.pkl", "rb"),
            }
            response = requests.post(
                urljoin(settings.API_URL, "/api/upload_index"), files=files, data=file_data
            )
        else:
            response = requests.post(
                urljoin(settings.API_URL, "/api/upload_index"), data=file_data
            )
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Error uploading index: {e}")
        raise
    finally:
        if settings.VECTOR_STORE == "faiss":
            for file in files.values():
                file.close()

# Define the main function for ingesting and processing documents.
def ingest_worker(
    self, directory, formats, name_job, filename, user, retriever="classic"
):
    """
    Ingest and process documents.

    Args:
        self: Reference to the instance of the task.
        directory (str): Specifies the directory for ingesting ('inputs' or 'temp').
        formats (list of str): List of file extensions to consider for ingestion (e.g., [".rst", ".md"]).
        name_job (str): Name of the job for this ingestion task.
        filename (str): Name of the file to be ingested.
        user (str): Identifier for the user initiating the ingestion.
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
    
    full_path = os.path.join(directory, user, name_job)
    source_file_path = os.path.join(full_path, filename)
    
    logging.info(f"Ingest file: {full_path}", extra={"user": user, "job": name_job})
    
    # Create temporary working directory
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            os.makedirs(temp_dir, exist_ok=True)
            
            # Download file from storage to temp directory
            temp_file_path = os.path.join(temp_dir, filename)
            file_data = storage.get_file(source_file_path)
            
            with open(temp_file_path, 'wb') as f:
                f.write(file_data.read())
            
            self.update_state(state="PROGRESS", meta={"current": 1})

            # Handle zip files
            if filename.endswith('.zip'):
                logging.info(f"Extracting zip file: {filename}")
                extract_zip_recursive(
                    temp_file_path,
                    temp_dir,
                    current_depth=0,
                    max_depth=RECURSION_DEPTH
                )

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

            chunker = Chunker(
                chunking_strategy="classic_chunk",
                max_tokens=MAX_TOKENS,
                min_tokens=MIN_TOKENS,
                duplicate_headers=False
            )
            raw_docs = chunker.chunk(documents=raw_docs)
            
            docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
            
            id = ObjectId()
            
            vector_store_path = os.path.join(temp_dir, 'vector_store')
            os.makedirs(vector_store_path, exist_ok=True)
            
            embed_and_store_documents(docs, vector_store_path, id, self)
            
            tokens = count_tokens_docs(docs)
            
            self.update_state(state="PROGRESS", meta={"current": 100})

            if sample:
               for i in range(min(5, len(raw_docs))):
                    logging.info(f"Sample document {i}: {raw_docs[i]}")
            file_data = {
                "name": name_job,
                "file": filename,
                "user": user,
                "tokens": tokens,
                "retriever": retriever,
                "id": str(id),
                "type": "local",
            }


            upload_index(vector_store_path, file_data)

        except Exception as e:
            logging.error(f"Error in ingest_worker: {e}", exc_info=True)
            raise

    return {
        "directory": directory,
        "formats": formats,
        "name_job": name_job,
        "filename": filename,
        "user": user,
        "limited": False,
    }

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
            duplicate_headers=False
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
        logging.error(f"Error during sync: {e}")
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
    db = mongo["docsgpt"]
    attachments_collection = db["attachments"]

    filename = file_info["filename"]
    attachment_id = file_info["attachment_id"]
    relative_path = file_info["path"]
    file_content = file_info["file_content"]

    try:
        self.update_state(state="PROGRESS", meta={"current": 10})
        storage_type = getattr(settings, "STORAGE_TYPE", "local")
        storage = StorageCreator.create_storage(storage_type)
        self.update_state(state="PROGRESS", meta={"current": 30, "status": "Processing content"})

        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename)[1]) as temp_file:
            temp_file.write(file_content)
            temp_file.flush()
            reader = SimpleDirectoryReader(
                input_files=[temp_file.name],
                exclude_hidden=True,
                errors="ignore"
            )
            documents = reader.load_data()

            if not documents:
                logging.warning(f"No content extracted from file: {filename}")
                raise ValueError(f"Failed to extract content from file: {filename}")

            content = documents[0].text
            token_count = num_tokens_from_string(content)

            self.update_state(state="PROGRESS", meta={"current": 60, "status": "Saving file"})
            file_obj = io.BytesIO(file_content)

            metadata = storage.save_file(file_obj, relative_path)

            mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

            self.update_state(state="PROGRESS", meta={"current": 80, "status": "Storing in database"})

            doc_id = ObjectId(attachment_id)
            attachments_collection.insert_one({
                "_id": doc_id,
                "user": user,
                "path": relative_path,
                "content": content,
                "token_count": token_count,
                "mime_type": mime_type,
                "date": datetime.datetime.now(),
                "metadata": metadata
            })

            logging.info(f"Stored attachment with ID: {attachment_id}",
                        extra={"user": user})

            self.update_state(state="PROGRESS", meta={"current": 100, "status": "Complete"})

            return {
                "filename": filename,
                "path": relative_path,
                "token_count": token_count,
                "attachment_id": attachment_id,
                "mime_type": mime_type,
                "metadata": metadata
            }

    except Exception as e:
        logging.error(f"Error processing file {filename}: {e}", extra={"user": user}, exc_info=True)
        raise
