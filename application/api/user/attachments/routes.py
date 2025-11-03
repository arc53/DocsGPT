"""File attachments and media routes."""

import os
import time
from typing import Any, Dict, List, Tuple

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from werkzeug.datastructures import FileStorage

from application.api import api
from application.api.user.base import agents_collection, storage
from application.api.user.tasks import store_attachment
from application.core.settings import settings
from application.tts.tts_creator import TTSCreator
from application.utils import safe_filename


attachments_ns = Namespace(
    "attachments", description="File attachments and media operations", path="/api"
)


@attachments_ns.route("/store_attachment")
class StoreAttachment(Resource):
    @api.expect(
        api.model(
            "AttachmentModel",
            {
                "file": fields.Raw(required=True, description="File(s) to upload"),
                "api_key": fields.String(
                    required=False, description="API key (optional)"
                ),
            },
        )
    )
    @api.doc(
        description="Stores single or multiple attachments without vectorization or training. Supports user or API key authentication."
    )
    def post(self) -> Tuple[Any, int]:
        """Store single or multiple file attachments.
        
        Processes files uploaded via multipart form data. Supports both single
        file uploads (backward compatibility) and multiple file uploads in a
        single request for improved efficiency.
        
        Returns:
            Tuple containing response object and HTTP status code.
            Response format:
            {
                "success": bool,
                "results": [
                    {
                        "success": bool,
                        "filename": str,
                        "attachment_id": str,
                        "task_id": str,
                        "message": str,
                        "error": str (optional)
                    }
                ]
            }
        """
        try:
            # Authenticate user
            user, auth_error = self._authenticate_user()
            if auth_error:
                return auth_error
            
            # Get files from request
            files = request.files.getlist("file")
            if not files:
                # Fallback to single file for backward compatibility
                single_file = request.files.get("file")
                if single_file:
                    files = [single_file]
                else:
                    return make_response(
                        jsonify({"success": False, "message": "No files provided"}),
                        400,
                    )
            
            # Process files in batch
            results = self._process_files_batch(files, user)
            
            # Determine overall success
            overall_success = any(result["success"] for result in results)
            
            return make_response(
                jsonify({
                    "success": overall_success,
                    "results": results
                }),
                200 if overall_success else 400,
            )
            
        except Exception as err:
            current_app.logger.error(
                f"Error in batch attachment upload: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "error": str(err)}), 500
            )
    
    def _authenticate_user(self) -> Tuple[str, Any]:
        """Authenticate user via JWT token or API key.
        
        Returns:
            Tuple of (username, error_response). If authentication succeeds,
            error_response is None. If authentication fails, username is None
            and error_response contains the Flask response object.
        """
        decoded_token = getattr(request, "decoded_token", None)
        api_key = request.form.get("api_key") or request.args.get("api_key")
        
        if decoded_token:
            return safe_filename(decoded_token.get("sub")), None
        elif api_key:
            agent = agents_collection.find_one({"key": api_key})
            if not agent:
                return None, make_response(
                    jsonify({"success": False, "message": "Invalid API key"}), 401
                )
            return safe_filename(agent.get("user")), None
        else:
            return None, make_response(
                jsonify({"success": False, "message": "Authentication required"}), 401
            )
    
    def _process_files_batch(self, files: List[FileStorage], user: str) -> List[Dict[str, Any]]:
        """Process multiple files in batch with enhanced error isolation.
        
        Args:
            files: List of FileStorage objects to process
            user: Authenticated username
        
        Returns:
            List of dictionaries containing processing results for each file.
            Each dict contains success status, filename, attachment_id, task_id,
            message, and optional error information.
        """
        results = []
        
        for i, file in enumerate(files):
            try:
                current_app.logger.info(
                    f"Processing file {i+1}/{len(files)}: {getattr(file, 'filename', 'unknown')}",
                    extra={"user": user, "batch_size": len(files)}
                )
                result = self._process_single_file(file, user)
                results.append(result)
                
                if result["success"]:
                    current_app.logger.info(
                        f"Successfully queued file for processing: {result['filename']}",
                        extra={"user": user, "task_id": result["task_id"], "attachment_id": result["attachment_id"]}
                    )
                else:
                    current_app.logger.warning(
                        f"Failed to process file: {result['filename']}, error: {result.get('error', 'Unknown')}",
                        extra={"user": user}
                    )
                    
            except Exception as err:
                filename = getattr(file, "filename", "unknown")
                current_app.logger.error(
                    f"Exception processing file {filename}: {err}",
                    exc_info=True,
                    extra={"user": user, "file_index": i}
                )
                results.append({
                    "success": False,
                    "filename": filename,
                    "attachment_id": None,
                    "task_id": None,
                    "message": "File processing failed",
                    "error": str(err)
                })
        
        # Log batch summary
        successful_count = sum(1 for result in results if result["success"])
        current_app.logger.info(
            f"Batch processing completed: {successful_count}/{len(results)} files successful",
            extra={"user": user, "success_rate": successful_count / len(results) if results else 0}
        )
        
        return results
    
    def _process_single_file(self, file: FileStorage, user: str) -> Dict[str, Any]:
        """Process a single file upload with comprehensive error handling.
        
        Args:
            file: FileStorage object to process
            user: Authenticated username
        
        Returns:
            Dictionary containing processing result with success status,
            filename, attachment_id, task_id, and message.
        
        Raises:
            Exception: If file processing fails for any reason.
        """
        # Validate file
        if not file or not file.filename or file.filename == "":
            return {
                "success": False,
                "filename": getattr(file, "filename", "unknown"),
                "attachment_id": None,
                "task_id": None,
                "message": "Empty or invalid file",
                "error": "File is empty or has no filename"
            }
        
        # Generate attachment ID and prepare file info
        attachment_id = ObjectId()
        original_filename = safe_filename(os.path.basename(file.filename))
        relative_path = f"{settings.UPLOAD_FOLDER}/{user}/attachments/{str(attachment_id)}/{original_filename}"
        
        try:
            # Save file to storage
            current_app.logger.debug(
                f"Saving file to storage: {original_filename} -> {relative_path}",
                extra={"user": user, "attachment_id": str(attachment_id)}
            )
            metadata = storage.save_file(file, relative_path)
            
            # CRITICAL FIX: Verify file was actually saved and is accessible
            # This prevents the race condition that was causing Celery worker crashes
            max_verification_attempts = 3
            file_verified = False
            
            for attempt in range(max_verification_attempts):
                try:
                    # Check if file exists
                    if storage.file_exists(relative_path):
                        # Additional verification: ensure file is readable
                        test_file = storage.get_file(relative_path)
                        test_file.close()
                        file_verified = True
                        current_app.logger.debug(
                            f"File verification successful on attempt {attempt + 1}: {original_filename}",
                            extra={"user": user, "attachment_id": str(attachment_id)}
                        )
                        break
                    else:
                        current_app.logger.warning(
                            f"File existence check failed on attempt {attempt + 1}: {relative_path}",
                            extra={"user": user, "attachment_id": str(attachment_id)}
                        )
                except Exception as verify_error:
                    current_app.logger.warning(
                        f"File verification attempt {attempt + 1} failed: {verify_error}",
                        extra={"user": user, "attachment_id": str(attachment_id)}
                    )
                
                # If not the last attempt, wait before retrying
                if attempt < max_verification_attempts - 1 and not file_verified:
                    wait_time = 0.1 * (attempt + 1)  # Exponential backoff: 0.1, 0.2, 0.3 seconds
                    current_app.logger.debug(
                        f"Waiting {wait_time}s before retry {attempt + 2} for file: {original_filename}"
                    )
                    time.sleep(wait_time)
            
            if not file_verified:
                error_msg = f"File save verification failed after {max_verification_attempts} attempts: {original_filename}"
                current_app.logger.error(
                    error_msg,
                    extra={"user": user, "attachment_id": str(attachment_id), "path": relative_path}
                )
                # Attempt cleanup of potentially corrupted file
                try:
                    if storage.file_exists(relative_path):
                        storage.delete_file(relative_path)
                        current_app.logger.info(
                            f"Cleaned up unverified file: {relative_path}",
                            extra={"user": user, "attachment_id": str(attachment_id)}
                        )
                except Exception as cleanup_error:
                    current_app.logger.warning(
                        f"Failed to cleanup unverified file {relative_path}: {cleanup_error}",
                        extra={"user": user, "attachment_id": str(attachment_id)}
                    )
                
                raise Exception(error_msg)
            
            # Prepare file info for background task
            file_info = {
                "filename": original_filename,
                "attachment_id": str(attachment_id),
                "path": relative_path,
                "metadata": metadata,
            }
            
            # Queue background processing task only after successful verification
            current_app.logger.debug(
                f"Queuing background task for verified file: {original_filename}",
                extra={"user": user, "attachment_id": str(attachment_id)}
            )
            task = store_attachment.delay(file_info, user)
            
            current_app.logger.info(
                f"File upload and verification completed successfully: {original_filename}",
                extra={
                    "user": user,
                    "attachment_id": str(attachment_id),
                    "task_id": task.id,
                    "file_size": getattr(file, 'content_length', 'unknown')
                }
            )
            
            return {
                "success": True,
                "filename": original_filename,
                "attachment_id": str(attachment_id),
                "task_id": task.id,
                "message": "File uploaded successfully. Processing started."
            }
            
        except Exception as storage_error:
            current_app.logger.error(
                f"Storage operation failed for file {original_filename}: {storage_error}",
                exc_info=True,
                extra={"user": user, "attachment_id": str(attachment_id)}
            )
            
            # Return structured error response instead of re-raising
            return {
                "success": False,
                "filename": original_filename,
                "attachment_id": str(attachment_id),
                "task_id": None,
                "message": "File upload failed",
                "error": str(storage_error)
            }


@attachments_ns.route("/images/<path:image_path>")
class ServeImage(Resource):
    @api.doc(description="Serve an image from storage")
    def get(self, image_path):
        try:
            file_obj = storage.get_file(image_path)
            extension = image_path.split(".")[-1].lower()
            content_type = f"image/{extension}"
            if extension == "jpg":
                content_type = "image/jpeg"
            response = make_response(file_obj.read())
            response.headers.set("Content-Type", content_type)
            response.headers.set("Cache-Control", "max-age=86400")

            return response
        except FileNotFoundError:
            return make_response(
                jsonify({"success": False, "message": "Image not found"}), 404
            )
        except Exception as e:
            current_app.logger.error(f"Error serving image: {e}")
            return make_response(
                jsonify({"success": False, "message": "Error retrieving image"}), 500
            )


@attachments_ns.route("/tts")
class TextToSpeech(Resource):
    tts_model = api.model(
        "TextToSpeechModel",
        {
            "text": fields.String(
                required=True, description="Text to be synthesized as audio"
            ),
        },
    )

    @api.expect(tts_model)
    @api.doc(description="Synthesize audio speech from text")
    def post(self):
        from application.utils import clean_text_for_tts

        data = request.get_json()
        text = data["text"]
        cleaned_text = clean_text_for_tts(text)

        try:
            tts_instance = TTSCreator.create_tts(settings.TTS_PROVIDER)
            audio_base64, detected_language = tts_instance.text_to_speech(cleaned_text)
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "audio_base64": audio_base64,
                        "lang": detected_language,
                    }
                ),
                200,
            )
        except Exception as err:
            current_app.logger.error(f"Error synthesizing audio: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
