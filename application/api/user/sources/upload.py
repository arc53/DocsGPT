"""Source document management upload functionality."""

import json
import os
import tempfile
import zipfile

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import sources_collection
from application.api.user.tasks import ingest, ingest_connector_task, ingest_remote
from application.core.settings import settings
from application.parser.connectors.connector_creator import ConnectorCreator
from application.storage.storage_creator import StorageCreator
from application.utils import check_required_fields, safe_filename


sources_upload_ns = Namespace(
    "sources", description="Source document management operations", path="/api"
)


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
        description="Uploads a file to be vectorized and indexed",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.form
        files = request.files.getlist("file")
        required_fields = ["user", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields or not files or all(file.filename == "" for file in files):
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "Missing required fields or files",
                    }
                ),
                400,
            )
        user = decoded_token.get("sub")
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
            task = ingest.delay(
                settings.UPLOAD_FOLDER,
                [
                    ".rst",
                    ".md",
                    ".pdf",
                    ".txt",
                    ".docx",
                    ".csv",
                    ".epub",
                    ".html",
                    ".mdx",
                    ".json",
                    ".xlsx",
                    ".pptx",
                    ".png",
                    ".jpg",
                    ".jpeg",
                ],
                job_name,
                user,
                file_path=base_path,
                filename=dir_name,
                file_name_map=file_name_map,
            )
        except Exception as err:
            current_app.logger.error(f"Error uploading file: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


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
        description="Uploads remote source for vectorization",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.form
        required_fields = ["user", "source", "name", "data"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
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

                task = ingest_connector_task.delay(
                    job_name=data["name"],
                    user=decoded_token.get("sub"),
                    source_type=data["source"],
                    session_token=session_token,
                    file_ids=file_ids,
                    folder_ids=folder_ids,
                    recursive=config.get("recursive", False),
                    retriever=config.get("retriever", "classic"),
                )
                return make_response(
                    jsonify({"success": True, "task_id": task.id}), 200
                )
            task = ingest_remote.delay(
                source_data=source_data,
                job_name=data["name"],
                user=decoded_token.get("sub"),
                loader=data["source"],
            )
        except Exception as err:
            current_app.logger.error(
                f"Error uploading remote source: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "task_id": task.id}), 200)


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
            ObjectId(source_id)
        except Exception:
            return make_response(
                jsonify({"success": False, "message": "Invalid source ID format"}), 400
            )
        try:
            source = sources_collection.find_one(
                {"_id": ObjectId(source_id), "user": user}
            )
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
                    sources_collection.update_one(
                        {"_id": ObjectId(source_id)},
                        {"$set": {"file_name_map": file_name_map}},
                    )
                # Trigger re-ingestion pipeline

                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.delay(source_id=source_id, user=user)

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Added {len(added_files)} files",
                            "added_files": added_files,
                            "parent_dir": parent_dir,
                            "reingest_task_id": task.id,
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
                    sources_collection.update_one(
                        {"_id": ObjectId(source_id)},
                        {"$set": {"file_name_map": file_name_map}},
                    )
                # Trigger re-ingestion pipeline

                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.delay(source_id=source_id, user=user)

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Removed {len(removed_files)} files",
                            "removed_files": removed_files,
                            "reingest_task_id": task.id,
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
                success = storage.remove_directory(full_directory_path)

                if not success:
                    current_app.logger.error(
                        f"Failed to remove directory from storage. "
                        f"User: {user}, Source ID: {source_id}, Directory path: {directory_path}, "
                        f"Full path: {full_directory_path}"
                    )
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
                        sources_collection.update_one(
                            {"_id": ObjectId(source_id)},
                            {"$set": {"file_name_map": file_name_map}},
                        )

                # Trigger re-ingestion pipeline

                from application.api.user.tasks import reingest_source_task

                task = reingest_source_task.delay(source_id=source_id, user=user)

                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": f"Successfully removed directory: {directory_path}",
                            "removed_directory": directory_path,
                            "reingest_task_id": task.id,
                        }
                    ),
                    200,
                )
        except Exception as err:
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
