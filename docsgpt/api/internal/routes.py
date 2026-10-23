import os
import datetime
import hmac
import json
import time
from flask import Blueprint, request, send_from_directory, jsonify
from werkzeug.utils import secure_filename
import logging

from docsgpt.core.paths import home_dir
from docsgpt.core.settings import settings
from docsgpt.decisions.backends.http import INTERNAL_ROUTES
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db import source_defaults
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.session import db_session
from docsgpt.storage.db.source_config import SourceConfig
from docsgpt.storage.storage_creator import StorageCreator


logger = logging.getLogger(__name__)

current_dir = str(home_dir())


internal = Blueprint("internal", __name__)

# What a sync's write changes on an existing source: the content it rebuilt.
_SYNC_FIELDS = ("date", "model", "tokens", "directory_structure")


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
    if not internal_key or not hmac.compare_digest(internal_key.encode(), settings.INTERNAL_KEY.encode()):
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
    config = request.form.get("config")

    if config:
        try:
            config = json.loads(config)
        except Exception:
            logger.error("Error parsing config")
            config = None
    else:
        config = None

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
        faiss_files = (file_faiss, file_pkl)
    else:
        faiss_files = None

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
    # Only persist ``config`` when supplied so a re-ingest that omits it
    # doesn't clobber an existing source's config back to ``{}``. Config is
    # treated as immutable for the ingest dedup window (see upload.py).
    if config is not None:
        update_fields["config"] = config

    is_sync = request.form.get("operation") == "sync"
    with db_session() as conn:
        repo = SourcesRepository(conn)
        existing = None
        if looks_like_uuid(source_id):
            # Locked until the write: a settings change waits instead of
            # landing between this read and the update.
            existing = repo.get_for_update(source_id, user)
        if existing is None:
            existing = repo.get_by_legacy_id(source_id, user)
        if is_sync and existing is None:
            # Deleted while the sync ran: a sync rebuilds a source, never creates one.
            logger.info(f"Not re-creating deleted source {source_id} from a sync")
            return {"status": "skipped", "reason": "gone"}
        if is_sync:
            if SourceConfig.parse(existing.get("config")).kind == "wiki":
                # Converted while the sync ran: its pages are the content now.
                logger.info(f"Not writing a sync over wiki source {source_id}")
                return {"status": "skipped", "reason": "wiki"}
            # The form carries what the source looked like when the sync was
            # queued; name, type, remote_data, schedule and config may have
            # changed since, so a sync writes only what it rebuilt.
            update_fields = {key: update_fields[key] for key in _SYNC_FIELDS}
        if faiss_files is not None:
            storage.save_file(faiss_files[0], f"{index_base_path}/index.faiss")
            storage.save_file(faiss_files[1], f"{index_base_path}/index.pkl")
        if existing is not None:
            repo.update(str(existing["id"]), user, update_fields)
        else:
            repo.create(
                job_name,
                source_id=source_id if looks_like_uuid(source_id) else None,
                user_id=user,
                type=type,
                # Every ingest creates its source here: it starts from the
                # admin's default retrieval settings, under any the request set.
                config=source_defaults.seed(conn, config),
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


# The decision model for Celery workers in local mode: the ``docsgpt decide-server`` contract (``/v1/decide``,
# ``/v1/decide/batch``, ``/v1/models``, ``/v1/load``) over this process's own model, which workers never load.
# The calls are counted and traced by the worker that makes them, so nothing here records them again.


def _decision_service():
    """The contract over this process's model, or ``None`` when it runs none (``DECISION_MODE`` is not local)."""
    from docsgpt import decisions
    from docsgpt.decisions.server import DecideService

    backend = decisions.get_decider().served()
    return DecideService(backend) if backend is not None else None


def _no_decision_model():
    detail = "this API process runs no decision model: it does only with DECISION_MODE=local"
    return jsonify({"error": "unavailable", "detail": detail}), 503


def _decision_call(name: str):
    """Run ``DecideService.<name>`` with the lane and deadline the worker's headers ask for."""
    from docsgpt.decisions.server import RETRY_AFTER_S, deadline_of, lane_of

    service = _decision_service()
    if service is None:
        return _no_decision_model()
    lane = lane_of(request.headers.get("X-Decision-Priority"))
    deadline = deadline_of(request.headers.get("X-Decision-Deadline-Ms"), lane, time.monotonic())
    body = request.get_json(force=True, silent=True)
    if body is None:
        return jsonify({"error": "bad_request", "detail": "the body is not JSON"}), 400
    status, payload = getattr(service, name)(body, lane, deadline)
    headers = {"Retry-After": str(RETRY_AFTER_S)} if status == 429 else {}
    return jsonify(payload), status, headers


@internal.route(f"{INTERNAL_ROUTES}/v1/decide", methods=["POST"])
def decision_decide():
    return _decision_call("decide")


@internal.route(f"{INTERNAL_ROUTES}/v1/decide/batch", methods=["POST"])
def decision_batch():
    return _decision_call("batch")


@internal.route(f"{INTERNAL_ROUTES}/v1/models", methods=["GET"])
def decision_models():
    service = _decision_service()
    return jsonify(service.models()) if service is not None else _no_decision_model()


@internal.route(f"{INTERNAL_ROUTES}/v1/load", methods=["POST"])
def decision_load():
    """Start loading this process's model in the background; never blocks."""
    service = _decision_service()
    return (jsonify(service.load()), 202) if service is not None else _no_decision_model()
