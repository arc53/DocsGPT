import os
import datetime
import json
from flask import Blueprint, request, send_from_directory, jsonify
from werkzeug.utils import secure_filename
import logging

from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.session import db_session
from application.storage.storage_creator import StorageCreator


logger = logging.getLogger(__name__)

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


internal = Blueprint("internal", __name__)


@internal.before_request
def verify_internal_key():
    """Verify INTERNAL_KEY for all internal endpoint requests.

    Deny by default: if INTERNAL_KEY is not configured, reject all requests.
    """
    if not settings.INTERNAL_KEY:
        logger.warning(
            f"Internal API request rejected from {request.remote_addr}: "
            "INTERNAL_KEY is not configured"
        )
        return jsonify({"error": "Unauthorized", "message": "Internal API is not configured"}), 401
    internal_key = request.headers.get("X-Internal-Key")
    if not internal_key or internal_key != settings.INTERNAL_KEY:
        logger.warning(f"Unauthorized internal API access attempt from {request.remote_addr}")
        return jsonify({"error": "Unauthorized", "message": "Invalid or missing internal key"}), 401


@internal.route("/api/download", methods=["get"])
def download_file():
    user = secure_filename(request.args.get("user"))
    job_name = secure_filename(request.args.get("name"))
    filename = secure_filename(request.args.get("file"))
    save_dir = os.path.join(current_dir, settings.UPLOAD_FOLDER, user, job_name)
    return send_from_directory(save_dir, filename, as_attachment=True)


@internal.route("/api/upload_index", methods=["POST"])
def upload_index_files():
    """Upload two files(index.faiss, index.pkl) to the user's folder."""
    if "user" not in request.form:
        return {"status": "no user"}
    user = request.form["user"]
    if "name" not in request.form:
        return {"status": "no name"}
    job_name = request.form["name"]
    tokens = request.form["tokens"]
    retriever = request.form["retriever"]
    source_id = request.form["id"]
    type = request.form["type"]
    remote_data = request.form["remote_data"] if "remote_data" in request.form else None
    sync_frequency = request.form["sync_frequency"] if "sync_frequency" in request.form else None

    file_path = request.form.get("file_path")
    directory_structure = request.form.get("directory_structure")
    file_name_map = request.form.get("file_name_map")

    if directory_structure:
        try:
            directory_structure = json.loads(directory_structure)
        except Exception:
            logger.error("Error parsing directory_structure")
            directory_structure = {}
    else:
        directory_structure = {}
    if file_name_map:
        try:
            file_name_map = json.loads(file_name_map)
        except Exception:
            logger.error("Error parsing file_name_map")
            file_name_map = None
    else:
        file_name_map = None

    storage = StorageCreator.get_storage()
    index_base_path = f"indexes/{source_id}"

    if settings.VECTOR_STORE == "faiss":
        if "file_faiss" not in request.files:
            logger.error("No file_faiss part")
            return {"status": "no file"}
        file_faiss = request.files["file_faiss"]
        if file_faiss.filename == "":
            return {"status": "no file name"}
        if "file_pkl" not in request.files:
            logger.error("No file_pkl part")
            return {"status": "no file"}
        file_pkl = request.files["file_pkl"]
        if file_pkl.filename == "":
            return {"status": "no file name"}

        # Save index files to storage
        faiss_storage_path = f"{index_base_path}/index.faiss"
        pkl_storage_path = f"{index_base_path}/index.pkl"
        storage.save_file(file_faiss, faiss_storage_path)
        storage.save_file(file_pkl, pkl_storage_path)

    now = datetime.datetime.now(datetime.timezone.utc)
    update_fields = {
        "name": job_name,
        "type": type,
        "language": job_name,
        "date": now,
        "model": settings.EMBEDDINGS_NAME,
        "tokens": tokens,
        "retriever": retriever,
        "remote_data": remote_data,
        "sync_frequency": sync_frequency,
        "file_path": file_path,
        "directory_structure": directory_structure,
    }
    if file_name_map is not None:
        update_fields["file_name_map"] = file_name_map

    with db_session() as conn:
        repo = SourcesRepository(conn)
        existing = None
        if looks_like_uuid(source_id):
            existing = repo.get(source_id, user)
        if existing is None:
            existing = repo.get_by_legacy_id(source_id, user)
        if existing is not None:
            repo.update(str(existing["id"]), user, update_fields)
        else:
            repo.create(
                job_name,
                user_id=user,
                type=type,
                tokens=tokens,
                retriever=retriever,
                remote_data=remote_data,
                sync_frequency=sync_frequency,
                file_path=file_path,
                directory_structure=directory_structure,
                file_name_map=file_name_map,
                language=job_name,
                model=settings.EMBEDDINGS_NAME,
                date=now,
                legacy_mongo_id=None if looks_like_uuid(source_id) else str(source_id),
            )
    return {"status": "ok"}
