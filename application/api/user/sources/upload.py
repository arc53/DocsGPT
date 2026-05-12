"""Source document management upload functionality."""

import json
import os
import tempfile
import uuid
import zipfile

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import text as sql_text

from application.api import api
from application.api.user.tasks import ingest, ingest_connector_task, ingest_remote
from application.core.settings import settings
from application.storage.db.source_ids import derive_source_id as _derive_source_id
from application.parser.connectors.connector_creator import ConnectorCreator
from application.parser.file.constants import SUPPORTED_SOURCE_EXTENSIONS
from application.storage.db.repositories.idempotency import IdempotencyRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.session import db_readonly, db_session
from application.storage.storage_creator import StorageCreator
from application.stt.upload_limits import (
    AudioFileTooLargeError,
    build_stt_file_size_limit_message,
    enforce_audio_file_size_limit,
    is_audio_filename,
)
from application.utils import check_required_fields, safe_filename


sources_upload_ns = Namespace(
    "sources", description="Source document management operations", path="/api"
)


_IDEMPOTENCY_KEY_MAX_LEN = 256


def _read_idempotency_key():
    """Return (key, error_response). Empty header → (None, None); oversized → (None, 400)."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None
    if len(key) > _IDEMPOTENCY_KEY_MAX_LEN:
        return None, make_response(
            jsonify(
                {
                    "success": False,
                    "message": (
                        f"Idempotency-Key exceeds maximum length of "
                        f"{_IDEMPOTENCY_KEY_MAX_LEN} characters"
                    ),
                }
            ),
            400,
        )
    return key, None


def _scoped_idempotency_key(idempotency_key, scope):
    """``{scope}:{key}`` so different users can't collide on the same key."""
    if not idempotency_key or not scope:
        return None
    return f"{scope}:{idempotency_key}"


def _claim_task_or_get_cached(key, task_name):
    """Claim ``key`` for this request OR return the winner's cached payload.

    Pre-generates the celery task_id so a losing writer sees the same
    id immediately. Returns ``(task_id, cached_response)``; non-None
    cached means the caller should return without enqueuing. The
    cached payload mirrors the fresh-request response shape (including
    ``source_id``) so the frontend can correlate SSE ingest events to
    the cached upload task without an extra round-trip — but only when
    the cached row actually exists; the "deduplicated" sentinel
    deliberately omits ``source_id`` so the frontend doesn't bind to a
    phantom source.
    """
    predetermined_id = str(uuid.uuid4())
    with db_session() as conn:
        claimed = IdempotencyRepository(conn).claim_task(
            key=key, task_name=task_name, task_id=predetermined_id,
        )
    if claimed is not None:
        return claimed["task_id"], None
    with db_readonly() as conn:
        existing = IdempotencyRepository(conn).get_task(key)
    cached_id = existing.get("task_id") if existing else None
    payload: dict = {
        "success": True,
        "task_id": cached_id or "deduplicated",
    }
    # Only surface ``source_id`` when there's a real winner whose worker
    # is publishing SSE events tagged with that id. The "deduplicated"
    # branch means the lock row vanished — we have nothing to correlate.
    if cached_id is not None:
        payload["source_id"] = str(_derive_source_id(key))
    return None, payload


def _release_claim(key):
    """Drop a pending claim so a client retry can re-claim it."""
    try:
        with db_session() as conn:
            conn.execute(
                sql_text(
                    "DELETE FROM task_dedup WHERE idempotency_key = :k "
                    "AND status = 'pending'"
                ),
                {"k": key},
            )
    except Exception:
        current_app.logger.exception(
            "Failed to release task_dedup claim for key=%s", key,
        )




def _enforce_audio_path_size_limit(file_path: str, filename: str) -> None:
    if not is_audio_filename(filename):
        return
    enforce_audio_file_size_limit(os.path.getsize(file_path))


@sources_upload_ns.route("/upload")
class UploadFile(Resource):
    @api.expect(
        api.model(
            "UploadModel",
            {
                "user": fields.String(required=True, description="User ID"),
                "name": fields.String(required=True, description="Job name"),
                "file": fields.Raw(required=True, description="File(s) to upload"),
            },
        )
    )
    @api.doc(
        description=(
            "Uploads a file to be vectorized and indexed. Honors an optional "
            "``Idempotency-Key`` header: a repeat request with the same key "
            "within 24h returns the original cached response without re-enqueuing."
        ),
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        idempotency_key, key_error = _read_idempotency_key()
        if key_error is not None:
            return key_error
        # User-scoped to avoid cross-user collisions; also feeds
        # ``_derive_source_id`` so uuid5 stays user-disjoint.
        scoped_key = _scoped_idempotency_key(idempotency_key, user)
        # Claim before enqueue; the loser returns the winner's task_id.
        predetermined_task_id = None
        if scoped_key:
            predetermined_task_id, cached = _claim_task_or_get_cached(
                scoped_key, "ingest",
            )
            if cached is not None:
                return make_response(jsonify(cached), 200)
        data = request.form
        files = request.files.getlist("file")
        required_fields = ["user", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields or not files or all(file.filename == "" for file in files):
            if scoped_key:
                _release_claim(scoped_key)
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "Missing required fields or files",
                    }
                ),
                400,
            )
        job_name = request.form["name"]

        # Create safe versions for filesystem operations

        safe_user = safe_filename(user)
        dir_name = safe_filename(job_name)
        base_path = f"{settings.UPLOAD_FOLDER}/{safe_user}/{dir_name}"
        file_name_map = {}

        try:
            storage = StorageCreator.get_storage()

            for file in files:
                original_filename = os.path.basename(file.filename)
                safe_file = safe_filename(original_filename)
                if original_filename:
                    file_name_map[safe_file] = original_filename

                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_file_path = os.path.join(temp_dir, safe_file)
                    file.save(temp_file_path)
                    _enforce_audio_path_size_limit(temp_file_path, safe_file)

                    # Only extract actual .zip files, not Office formats (.docx, .xlsx, .pptx)
                    # which are technically zip archives but should be processed as-is
                    is_office_format = safe_file.lower().endswith(
                        (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub")
                    )
                    if zipfile.is_zipfile(temp_file_path) and not is_office_format:
                        try:
                            with zipfile.ZipFile(temp_file_path, "r") as zip_ref:
                                zip_ref.extractall(path=temp_dir)

                                # Walk through extracted files and upload them

                                for root, _, files in os.walk(temp_dir):
                                    for extracted_file in files:
                                        if (
                                            os.path.join(root, extracted_file)
                                            == temp_file_path
                                        ):
                                            continue
                                        rel_path = os.path.relpath(
                                            os.path.join(root, extracted_file), temp_dir
                                        )
                                        storage_path = f"{base_path}/{rel_path}"
                                        _enforce_audio_path_size_limit(
                                            os.path.join(root, extracted_file),
                                            extracted_file,
                                        )

                                        with open(
                                            os.path.join(root, extracted_file), "rb"
                                        ) as f:
                                            storage.save_file(f, storage_path)
                        except Exception as e:
                            current_app.logger.error(
                                f"Error extracting zip: {e}", exc_info=True
                            )
                            # If zip extraction fails, save the original zip file

                            file_path = f"{base_path}/{safe_file}"
                            with open(temp_file_path, "rb") as f:
                                storage.save_file(f, file_path)
                    else:
                        # For non-zip files, save directly

                        file_path = f"{base_path}/{safe_file}"
                        with open(temp_file_path, "rb") as f:
                            storage.save_file(f, file_path)
            # Mint the source UUID up here so the HTTP response and the
            # worker's SSE envelopes share one id. With an idempotency
            # key we reuse the deterministic uuid5 (retried task lands on
            # the same source row); without a key we fall back to uuid4.
            # The worker is told to use this id verbatim — see
            # ``ingest_worker(source_id=...)``.
            source_uuid = (
                _derive_source_id(scoped_key) if scoped_key else uuid.uuid4()
            )
            ingest_kwargs = dict(
                args=(
                    settings.UPLOAD_FOLDER,
                    list(SUPPORTED_SOURCE_EXTENSIONS),
                    job_name,
                    user,
                ),
                kwargs={
                    "file_path": base_path,
                    "filename": dir_name,
                    "file_name_map": file_name_map,
                    # Scoped so the worker dedup row matches the HTTP claim.
                    "idempotency_key": scoped_key or idempotency_key,
                    "source_id": str(source_uuid),
                },
            )
            if predetermined_task_id is not None:
                ingest_kwargs["task_id"] = predetermined_task_id
            task = ingest.apply_async(**ingest_kwargs)
        except AudioFileTooLargeError:
            if scoped_key:
                _release_claim(scoped_key)
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": build_stt_file_size_limit_message(),
                    }
                ),
                413,
            )
        except Exception as err:
            current_app.logger.error(f"Error uploading file: {err}", exc_info=True)
            if scoped_key:
                _release_claim(scoped_key)
            return make_response(jsonify({"success": False}), 400)
        # Predetermined id matches the dedup-claim row; loser GET sees same.
        response_task_id = predetermined_task_id or task.id
        # ``source_uuid`` was minted above and passed to the worker as
        # ``source_id``; the worker uses it verbatim for every SSE event,
        # so the frontend can correlate inbound ``source.ingest.*`` to
        # this upload regardless of whether an idempotency key was set.
        response_payload: dict = {
            "success": True,
            "task_id": response_task_id,
            "source_id": str(source_uuid),
        }
        return make_response(jsonify(response_payload), 200)


@sources_upload_ns.route("/remote")
class UploadRemote(Resource):
    @api.expect(
        api.model(
            "RemoteUploadModel",
            {
                "user": fields.String(required=True, description="User ID"),
                "source": fields.String(
                    required=True, description="Source of the data"
                ),
                "name": fields.String(required=True, description="Job name"),
                "data": fields.String(required=True, description="Data to process"),
                "repo_url": fields.String(description="GitHub repository URL"),
            },
        )
    )
    @api.doc(
        description=(
            "Uploads remote source for vectorization. Honors an optional "
            "``Idempotency-Key`` header: a repeat request with the same key "
            "within 24h returns the original cached response without re-enqueuing."
        ),
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        idempotency_key, key_error = _read_idempotency_key()
        if key_error is not None:
            return key_error
        scoped_key = _scoped_idempotency_key(idempotency_key, user)
        data = request.form
        required_fields = ["user", "source", "name", "data"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        task_name_for_dedup = (
            "ingest_connector_task"
            if data.get("source") in ConnectorCreator.get_supported_connectors()
            else "ingest_remote"
        )
        predetermined_task_id = None
        if scoped_key:
            predetermined_task_id, cached = _claim_task_or_get_cached(
                scoped_key, task_name_for_dedup,
            )
            if cached is not None:
                return make_response(jsonify(cached), 200)
        # Mint the source UUID up here so the HTTP response and the
        # worker's SSE envelopes share one id. Same pattern as
        # ``UploadFile.post``: with an idempotency key we reuse the
        # deterministic uuid5 (retried task lands on the same source
        # row); without a key we fall back to uuid4. The worker is told
        # to use this id verbatim — see ``remote_worker`` and
        # ``ingest_connector``. Without this the no-key path would mint
        # a random uuid4 inside the worker that the frontend has no way
        # to correlate SSE events to.
        source_uuid = (
            _derive_source_id(scoped_key) if scoped_key else uuid.uuid4()
        )
        try:
            config = json.loads(data["data"])
            source_data = None

            if data["source"] == "github":
                source_data = config.get("repo_url")
            elif data["source"] in ["crawler", "url"]:
                source_data = config.get("url")
            elif data["source"] == "reddit":
                source_data = config
            elif data["source"] == "s3":
                source_data = config
            elif data["source"] in ConnectorCreator.get_supported_connectors():
                session_token = config.get("session_token")
                if not session_token:
                    if scoped_key:
                        _release_claim(scoped_key)
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": f"Missing session_token in {data['source']} configuration",
                            }
                        ),
                        400,
                    )
                # Process file_ids

                file_ids = config.get("file_ids", [])
                if isinstance(file_ids, str):
                    file_ids = [id.strip() for id in file_ids.split(",") if id.strip()]
                elif not isinstance(file_ids, list):
                    file_ids = []
                # Process folder_ids

                folder_ids = config.get("folder_ids", [])
                if isinstance(folder_ids, str):
                    folder_ids = [
                        id.strip() for id in folder_ids.split(",") if id.strip()
                    ]
                elif not isinstance(folder_ids, list):
                    folder_ids = []
                config["file_ids"] = file_ids
                config["folder_ids"] = folder_ids

                connector_kwargs = {
                    "kwargs": {
                        "job_name": data["name"],
                        "user": user,
                        "source_type": data["source"],
                        "session_token": session_token,
                        "file_ids": file_ids,
                        "folder_ids": folder_ids,
                        "recursive": config.get("recursive", False),
                        "retriever": config.get("retriever", "classic"),
                        "idempotency_key": scoped_key or idempotency_key,
                        "source_id": str(source_uuid),
                    },
                }
                if predetermined_task_id is not None:
                    connector_kwargs["task_id"] = predetermined_task_id
                task = ingest_connector_task.apply_async(**connector_kwargs)
                response_task_id = predetermined_task_id or task.id
                # ``source_uuid`` was minted above and passed to the
                # worker as ``source_id``; the worker uses it verbatim
                # for every SSE event, so the frontend can correlate
                # inbound ``source.ingest.*`` regardless of whether an
                # idempotency key was set.
                response_payload = {
                    "success": True,
                    "task_id": response_task_id,
                    "source_id": str(source_uuid),
                }
                return make_response(jsonify(response_payload), 200)
            remote_kwargs = {
                "kwargs": {
                    "source_data": source_data,
                    "job_name": data["name"],
                    "user": user,
                    "loader": data["source"],
                    "idempotency_key": scoped_key or idempotency_key,
                    "source_id": str(source_uuid),
                },
            }
            if predetermined_task_id is not None:
                remote_kwargs["task_id"] = predetermined_task_id
            task = ingest_remote.apply_async(**remote_kwargs)
        except Exception as err:
            current_app.logger.error(
                f"Error uploading remote source: {err}", exc_info=True
            )
            if scoped_key:
                _release_claim(scoped_key)
            return make_response(jsonify({"success": False}), 400)
        response_task_id = predetermined_task_id or task.id
        response_payload = {
            "success": True,
            "task_id": response_task_id,
            "source_id": str(source_uuid),
        }
        return make_response(jsonify(response_payload), 200)


@sources_upload_ns.route("/manage_source_files")
class ManageSourceFiles(Resource):
    @api.expect(
        api.model(
            "ManageSourceFilesModel",
            {
                "source_id": fields.String(
                    required=True, description="Source ID to modify"
                ),
                "operation": fields.String(
                    required=True,
                    description="Operation: 'add', 'remove', or 'remove_directory'",
                ),
                "file_paths": fields.List(
                    fields.String,
                    required=False,
                    description="File paths to remove (for remove operation)",
                ),
                "directory_path": fields.String(
                    required=False,
                    description="Directory path to remove (for remove_directory operation)",
                ),
                "file": fields.Raw(
                    required=False, description="Files to add (for add operation)"
                ),
                "parent_dir": fields.String(
                    required=False,
                    description="Parent directory path relative to source root",
                ),
            },
        )
    )
    @api.doc(
        description="Add files, remove files, or remove directories from an existing source",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(
                jsonify({"success": False, "message": "Unauthorized"}), 401
            )
        user = decoded_token.get("sub")
        idempotency_key, key_error = _read_idempotency_key()
        if key_error is not None:
            return key_error
        scoped_key = _scoped_idempotency_key(idempotency_key, user)
        source_id = request.form.get("source_id")
        operation = request.form.get("operation")

        if not source_id or not operation:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "source_id and operation are required",
                    }
                ),
                400,
            )
        if operation not in ["add", "remove", "remove_directory"]:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "operation must be 'add', 'remove', or 'remove_directory'",
                    }
                ),
                400,
            )
        try:
            with db_readonly() as conn:
                source = SourcesRepository(conn).get_any(source_id, user)
            if not source:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Source not found or access denied",
                        }
                    ),
                    404,
                )
        except Exception as err:
            current_app.logger.error(f"Error finding source: {err}", exc_info=True)
            return make_response(
                jsonify({"success": False, "message": "Database error"}), 500
            )
        resolved_source_id = str(source["id"])
        # Flips to True after each branch's ``apply_async`` returns
        # successfully — at that point the worker owns the predetermined
        # task_id. The outer ``except`` only releases the claim while
        # this is False, so a post-``apply_async`` failure (jsonify,
        # make_response, etc.) doesn't double-enqueue on the next retry.
        claim_transferred = False
        try:
            storage = StorageCreator.get_storage()
            source_file_path = source.get("file_path", "")
            parent_dir = request.form.get("parent_dir", "")
            file_name_map = source.get("file_name_map") or {}
            if isinstance(file_name_map, str):
                try:
                    file_name_map = json.loads(file_name_map)
                except Exception:
                    file_name_map = {}
            if not isinstance(file_name_map, dict):
                file_name_map = {}

            if parent_dir and (parent_dir.startswith("/") or ".." in parent_dir):
                return make_response(
                    jsonify(
                        {"success": False, "message": "Invalid parent directory path"}
                    ),
                    400,
                )
            if operation == "add":
                files = request.files.getlist("file")
                if not files or all(file.filename == "" for file in files):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "No files provided for add operation",
                            }
                        ),
                        400,
                    )

                # Claim before any storage mutation so a duplicate request
                # short-circuits without touching the filesystem. Mirrors
                # the pattern in ``UploadFile.post`` / ``UploadRemote.post``
                # — without it ``.delay()`` would enqueue twice for two
                # racing same-key POSTs (the worker decorator only
                # deduplicates *after* completion).
                predetermined_task_id = None
                if scoped_key:
                    predetermined_task_id, cached = _claim_task_or_get_cached(
                        scoped_key, "reingest_source_task",
                    )
                    if cached is not None:
                        # Frontend keys reingest polling on
                        # ``reingest_task_id``; the shared cache helper
                        # writes ``task_id``. Alias here so a dedup
                        # response doesn't silently break FileTree's
                        # poller. Override ``source_id`` too — the
                        # helper derives it from the scoped key, which
                        # is correct for upload but wrong for reingest
                        # (the worker publishes events scoped to the
                        # actual source row id).
                        cached_task_id = cached.pop("task_id", None)
                        if cached_task_id is not None:
                            cached["reingest_task_id"] = cached_task_id
                        cached["source_id"] = resolved_source_id
                        return make_response(jsonify(cached), 200)

                added_files = []
                map_updated = False

                target_dir = source_file_path
                if parent_dir:
                    target_dir = f"{source_file_path}/{parent_dir}"
                for file in files:
                    if file.filename:
                        original_filename = os.path.basename(file.filename)
                        safe_filename_str = safe_filename(original_filename)
                        file_path = f"{target_dir}/{safe_filename_str}"

                        # Save file to storage

                        storage.save_file(file, file_path)
                        added_files.append(safe_filename_str)
                        if original_filename:
                            relative_key = (
                                f"{parent_dir}/{safe_filename_str}"
                                if parent_dir
                                else safe_filename_str
                            )
                            file_name_map[relative_key] = original_filename
                            map_updated = True

                if map_updated:
                    with db_session() as conn:
                        SourcesRepository(conn).update(
                            resolved_source_id, user,
                            {"file_name_map": dict(file_name_map)},
                        )
                # Trigger re-ingestion pipeline

                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.apply_async(
                    kwargs={
                        "source_id": resolved_source_id,
                        "user": user,
                        "idempotency_key": scoped_key or idempotency_key,
                    },
                    task_id=predetermined_task_id,
                )
                claim_transferred = True

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Added {len(added_files)} files",
                            "added_files": added_files,
                            "parent_dir": parent_dir,
                            "reingest_task_id": task.id,
                            # ``source_id`` lets the frontend correlate
                            # inbound ``source.ingest.*`` SSE events
                            # (emitted by ``reingest_source_worker``)
                            # back to the reingest task — matches the
                            # upload route's contract from Phase 1D.
                            "source_id": resolved_source_id,
                        }
                    ),
                    200,
                )
            elif operation == "remove":
                file_paths_str = request.form.get("file_paths")
                if not file_paths_str:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "file_paths required for remove operation",
                            }
                        ),
                        400,
                    )
                try:
                    file_paths = (
                        json.loads(file_paths_str)
                        if isinstance(file_paths_str, str)
                        else file_paths_str
                    )
                except Exception:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Invalid file_paths format"}
                        ),
                        400,
                    )
                # Path-traversal guard runs *before* the claim so a 400
                # for an invalid path doesn't leave a pending dedup row.
                for file_path in file_paths:
                    if ".." in str(file_path) or str(file_path).startswith("/"):
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "message": "Invalid file path",
                                }
                            ),
                            400,
                        )

                # Claim before any storage mutation. See ``add`` branch
                # comment for rationale.
                predetermined_task_id = None
                if scoped_key:
                    predetermined_task_id, cached = _claim_task_or_get_cached(
                        scoped_key, "reingest_source_task",
                    )
                    if cached is not None:
                        cached_task_id = cached.pop("task_id", None)
                        if cached_task_id is not None:
                            cached["reingest_task_id"] = cached_task_id
                        # Override the helper's synthetic source_id (uuid5
                        # of the scoped key) with the real source row id
                        # — the reingest worker publishes SSE events
                        # scoped to ``resolved_source_id`` and FileTree
                        # correlates on it.
                        cached["source_id"] = resolved_source_id
                        return make_response(jsonify(cached), 200)

                # Remove files from storage and directory structure

                removed_files = []
                map_updated = False
                for file_path in file_paths:
                    full_path = f"{source_file_path}/{file_path}"

                    # Remove from storage

                    if storage.file_exists(full_path):
                        storage.delete_file(full_path)
                        removed_files.append(file_path)
                    if file_path in file_name_map:
                        file_name_map.pop(file_path, None)
                        map_updated = True

                if map_updated and isinstance(file_name_map, dict):
                    with db_session() as conn:
                        SourcesRepository(conn).update(
                            resolved_source_id, user,
                            {"file_name_map": dict(file_name_map)},
                        )
                # Trigger re-ingestion pipeline

                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.apply_async(
                    kwargs={
                        "source_id": resolved_source_id,
                        "user": user,
                        "idempotency_key": scoped_key or idempotency_key,
                    },
                    task_id=predetermined_task_id,
                )
                claim_transferred = True

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Removed {len(removed_files)} files",
                            "removed_files": removed_files,
                            "reingest_task_id": task.id,
                            "source_id": resolved_source_id,
                        }
                    ),
                    200,
                )
            elif operation == "remove_directory":
                directory_path = request.form.get("directory_path")
                if not directory_path:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "directory_path required for remove_directory operation",
                            }
                        ),
                        400,
                    )
                # Validate directory path (prevent path traversal)

                if directory_path.startswith("/") or ".." in directory_path:
                    current_app.logger.warning(
                        f"Invalid directory path attempted for removal. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}"
                    )
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Invalid directory path"}
                        ),
                        400,
                    )
                full_directory_path = (
                    f"{source_file_path}/{directory_path}"
                    if directory_path
                    else source_file_path
                )

                if not storage.is_directory(full_directory_path):
                    current_app.logger.warning(
                        f"Directory not found or is not a directory for removal. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                        f"Full path: {full_directory_path}"
                    )
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Directory not found or is not a directory",
                            }
                        ),
                        404,
                    )

                # Claim before mutation. See ``add`` branch for rationale.
                predetermined_task_id = None
                if scoped_key:
                    predetermined_task_id, cached = _claim_task_or_get_cached(
                        scoped_key, "reingest_source_task",
                    )
                    if cached is not None:
                        cached_task_id = cached.pop("task_id", None)
                        if cached_task_id is not None:
                            cached["reingest_task_id"] = cached_task_id
                        # Same source_id override as the ``remove`` /
                        # ``add`` cached branches — the helper's synthetic
                        # id doesn't match what reingest_source_worker
                        # tags its SSE events with.
                        cached["source_id"] = resolved_source_id
                        return make_response(jsonify(cached), 200)

                success = storage.remove_directory(full_directory_path)

                if not success:
                    current_app.logger.error(
                        f"Failed to remove directory from storage. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                        f"Full path: {full_directory_path}"
                    )
                    # Release so a client retry can reclaim — otherwise
                    # the next request would silently 200-cache to the
                    # task_id that never enqueued.
                    if scoped_key:
                        _release_claim(scoped_key)
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Failed to remove directory"}
                        ),
                        500,
                    )
                current_app.logger.info(
                    f"Successfully removed directory. "
                    f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                    f"Full path: {full_directory_path}"
                )
                if directory_path and file_name_map:
                    prefix = f"{directory_path.rstrip('/')}/"
                    keys_to_remove = [
                        key
                        for key in file_name_map.keys()
                        if key == directory_path or key.startswith(prefix)
                    ]
                    if keys_to_remove:
                        for key in keys_to_remove:
                            file_name_map.pop(key, None)
                        with db_session() as conn:
                            SourcesRepository(conn).update(
                                resolved_source_id, user,
                                {"file_name_map": dict(file_name_map)},
                            )

                # Trigger re-ingestion pipeline

                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.apply_async(
                    kwargs={
                        "source_id": resolved_source_id,
                        "user": user,
                        "idempotency_key": scoped_key or idempotency_key,
                    },
                    task_id=predetermined_task_id,
                )
                claim_transferred = True

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Successfully removed directory: {directory_path}",
                            "removed_directory": directory_path,
                            "reingest_task_id": task.id,
                            "source_id": resolved_source_id,
                        }
                    ),
                    200,
                )
        except Exception as err:
            # Release the dedup claim only if it wasn't transferred to
            # a worker. Without this, a same-key retry within the 24h
            # TTL would 200-cache to a predetermined task_id whose
            # ``apply_async`` never ran (or ran but the response builder
            # blew up afterward — only the first case matters in
            # practice; the flag protects both).
            if scoped_key and not claim_transferred:
                _release_claim(scoped_key)
            error_context = f"operation={operation}, user={user}, source_id={source_id}"
            if operation == "remove_directory":
                directory_path = request.form.get("directory_path", "")
                error_context += f", directory_path={directory_path}"
            elif operation == "remove":
                file_paths_str = request.form.get("file_paths", "")
                error_context += f", file_paths={file_paths_str}"
            elif operation == "add":
                parent_dir = request.form.get("parent_dir", "")
                error_context += f", parent_dir={parent_dir}"
            current_app.logger.error(
                f"Error managing source files: {err} ({error_context})", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Operation failed"}), 500
            )


@sources_upload_ns.route("/task_status")
class TaskStatus(Resource):
    task_status_model = api.model(
        "TaskStatusModel",
        {"task_id": fields.String(required=True, description="Task ID")},
    )

    @api.expect(task_status_model)
    @api.doc(description="Get celery job status")
    def get(self):
        task_id = request.args.get("task_id")
        if not task_id:
            return make_response(
                jsonify({"success": False, "message": "Task ID is required"}), 400
            )
        try:
            from application.celery_init import celery

            task = celery.AsyncResult(task_id)
            task_meta = task.info
            print(f"Task status: {task.status}")

            if task.status == "PENDING":
                inspect = celery.control.inspect()
                active_workers = inspect.ping()
                if not active_workers:
                    raise ConnectionError("Service unavailable")

            if not isinstance(
                task_meta, (dict, list, str, int, float, bool, type(None))
            ):
                task_meta = str(task_meta)  # Convert to a string representation
        except ConnectionError as err:
            current_app.logger.error(f"Connection error getting task status: {err}")
            return make_response(
                jsonify({"success": False, "message": "Service unavailable"}), 503
            )
        except Exception as err:
            current_app.logger.error(f"Error getting task status: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"status": task.status, "result": task_meta}), 200)
